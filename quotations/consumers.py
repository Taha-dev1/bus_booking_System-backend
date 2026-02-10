from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from .models import *
from channels.layers import get_channel_layer
import json
import threading

User = get_user_model()
channel_layer = get_channel_layer()

# Track active users per lead
active_users_in_chat = {}  # {lead_id: set(user_ids)}


# --- Helper function to send email in a separate thread ---
def send_email_thread(recipient_list, subject, message, from_email=None):
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False
        )
    except Exception as e:
        print(f"[Email Error] {e}")


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.lead_id = self.scope["url_route"]["kwargs"]["lead_id"]
        self.room_group_name = f"lead_chat_{self.lead_id}"
        self.user = self.scope["user"]

        if self.lead_id not in active_users_in_chat:
            active_users_in_chat[self.lead_id] = set()

        if self.user.is_authenticated:
            active_users_in_chat[self.lead_id].add(self.user.id)

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        print(f"[ChatConsumer] {self.user.username} connected to lead {self.lead_id}")

    async def disconnect(self, close_code):
        if self.user.is_authenticated and self.lead_id in active_users_in_chat:
            active_users_in_chat[self.lead_id].discard(self.user.id)
            if not active_users_in_chat[self.lead_id]:
                del active_users_in_chat[self.lead_id]
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        print(f"[ChatConsumer] {self.user.username} disconnected from lead {self.lead_id}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message = data.get("message")
            if not message:
                await self.send(text_data=json.dumps({"error": "Message is required"}))
                return
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "Invalid JSON"}))
            return

        if not self.user.is_authenticated:
            await self.send(text_data=json.dumps({"error": "Authentication required"}))
            return

        # 1 Save message first
        chat_data = await self.save_message(self.user, message)

        # 2️ Broadcast message to all users in chat room
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                **chat_data,
            },
        )

        # 3️ Send email only to users NOT currently active in this chat
        await self.send_email_to_recipient_if_inactive(self.user, message)

        # 4️ Save notifications and send WebSocket notifications
        await self.send_notifications(chat_data)

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def save_message(self, sender, message):
        lead = Lead.objects.get(id=self.lead_id)
        message_type = "ADMIN" if sender.is_staff else "USER"
        chat = ChatMessage.objects.create(
            lead=lead,
            sender=sender,
            message=message,
            message_type=message_type
        )
        return {
            "id": chat.id,
            "lead_id": self.lead_id,
            "message": chat.message,
            "sender": sender.username,
            "created_at": chat.created_at.isoformat(),
            "message_type": message_type,
        }

    @database_sync_to_async
    def send_email_to_recipient_if_inactive(self, sender, message):
        lead = Lead.objects.get(id=self.lead_id)
        active_users = active_users_in_chat.get(self.lead_id, set())

        if sender.is_staff:
            # Admin sent message → email lead.user if not active
            if lead.user and lead.user.email and lead.user.id not in active_users:
                threading.Thread(
                    target=send_email_thread,
                    args=([lead.user.email],
                          f"New message about Lead #{lead.id}",
                          f"From: {sender.get_full_name() or sender.username}\n\n{message}",
                          f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>")
                ).start()
        else:
            # User sent message → email all approved admins who are not active
            admins = AdminProfile.objects.filter(is_approved=True)
            for admin in admins:
                if admin.user.email and admin.user.id not in active_users:
                    threading.Thread(
                        target=send_email_thread,
                        args=([admin.user.email],
                              f"New message about Lead #{lead.id}",
                              f"From: {sender.get_full_name() or sender.username}\n\n{message}",
                              f"{settings.EMAIL_SENDER_NAME_ADMIN} <{settings.DEFAULT_FROM_EMAIL}>")
                    ).start()

    async def send_notifications(self, chat_data):
        """Send notifications to all related users except sender and active users."""
        users_to_notify = await self.get_related_users()
        active_users = active_users_in_chat.get(self.lead_id, set())

        for user in users_to_notify:
            if user.id == self.user.id or user.id in active_users:
                continue

            notif = await self.create_chat_notification(user, chat_data)
            if not notif:
                continue

            try:
                await self.channel_layer.group_send(
                    f"user_notify_{user.id}",
                    {
                        "type": "notify_user",
                        "id": notif.id,
                        "user": user.id,
                        "quotation": None,
                        "notification_type": "CHAT_ADMIN" if user.is_staff else "CHAT_USER",
                        "title": "New Chat Message",
                        "message": f"New message from {chat_data['sender']}: {chat_data['message']}",
                        "sent_at": chat_data["created_at"],
                        "email_sent": True,
                        "is_read": False,
                        "created_at": chat_data["created_at"],
                        "lead_id": self.lead_id,
                    },
                )
            except Exception as e:
                print(f"[Notification Error] Could not send WebSocket to {user.username}: {e}")

    @database_sync_to_async
    def create_chat_notification(self, user, chat_data):
        if user.id == self.user.id:
            return None
        try:
            sender = User.objects.get(username=chat_data["sender"])
            lead = Lead.objects.get(id=self.lead_id)

            if user.is_staff:
                notif = AdminNotification.objects.create(
                    admin=user,
                    lead=lead,
                    message=f"New message from {sender.username}: {chat_data['message']}",
                    is_read=False
                )
            else:
                notif = Notification.objects.create(
                    user=user,
                    lead=lead,
                    notification_type="CHAT_USER",
                    title="New Chat Message",
                    message=f"New message from {sender.username}: {chat_data['message']}",
                    is_read=False
                )
            return notif
        except Exception as e:
            print(f"[Notification DB Error] {e}")
            return None

    @database_sync_to_async
    def get_related_users(self):
        lead = Lead.objects.get(id=self.lead_id)
        users = [lead.user] if lead.user else []

        if hasattr(lead, "assigned_admin") and lead.assigned_admin:
            users.append(lead.assigned_admin)

        staff_users = list(User.objects.filter(is_staff=True))
        for staff in staff_users:
            if staff not in users:
                users.append(staff)

        return users


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return

        self.group_name = f"user_notify_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        print(f"[NotificationConsumer] {self.user.username} connected")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        print(f"[NotificationConsumer] {self.user.username} disconnected")

    async def notify_user(self, event):
        """Send notification to front-end in JSON format."""
        await self.send(text_data=json.dumps({
            "id": event.get("id"),
            "user": event.get("user"),
            "quotation": event.get("quotation"),
            "notification_type": event.get("notification_type"),
            "title": event.get("title"),
            "message": event.get("message"),
            "sent_at": event.get("sent_at"),
            "email_sent": event.get("email_sent"),
            "is_read": event.get("is_read"),
            "created_at": event.get("created_at"),
            "lead_id": event.get("lead_id"),
        }))
