import logging
import secrets
import string

from django.core.mail import send_mail, BadHeaderError
from django.conf import settings

from .models import Lead, Notification

logger = logging.getLogger(__name__)


def generate_otp(length=6):
    """Generate a numeric OTP of the given length."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def create_notification(quotation, notification_type, message, email_sent=False):
    """
    Create a notification for a given quotation.
    """
    Notification.objects.create(
        quotation=quotation,
        notification_type=notification_type,
        message=message,
        email_sent=email_sent
    )


def send_notification_email(recipient_email, subject, message):
    """
    Send an email using Django's send_mail function.
    """
    try:
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            logger.error("Email settings not configured properly")
            return False
        if not recipient_email:
            logger.error("No recipient email provided")
            return False
        send_mail(
            subject=subject,
            message=message,
            from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        return True
    except BadHeaderError:
        logger.error("Invalid header found in email")
        return False
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False


def get_stops_and_roundtrip_details(quotation):
    """
    Retrieve formatted strings for stops and roundtrip stops of a quotation.
    """
    stops_qs = quotation.stops.all()
    stops_str = "\n".join(
        f"- {stop.location} (Est. Time: {stop.estimated_time} min)"
        for stop in stops_qs
    ) if stops_qs.exists() else "No stops."

    roundtrip_qs = quotation.roundtrip_stops.all()
    roundtrip_str = "\n".join(
        f"- {rt.location} (Est. Time: {rt.estimated_time} min)"
        for rt in roundtrip_qs
    ) if roundtrip_qs.exists() else "No roundtrip stops."

    return stops_str, roundtrip_str


def get_stops_and_roundtrip_details_lead(lead: Lead) -> tuple[str, str]:
    """
    Retrieve formatted strings for stops and roundtrip stops of a Lead.
    """
    stops_qs = lead.stops_lead.all()
    stops_str = (
        "\n".join(
            f"- {stop.location} (Est. Time: {stop.estimated_time} min)"
            for stop in stops_qs
        ) if stops_qs.exists() else "No stops."
    )
    roundtrip_qs = lead.roundtrip_stops_lead.all()
    roundtrip_str = (
        "\n".join(
            f"- {rt.location} (Est. Time: {rt.estimated_time} min)"
            for rt in roundtrip_qs
        ) if roundtrip_qs.exists() else "No roundtrip stops."
    )
    return stops_str, roundtrip_str


def send_chat_notification(lead, sender, message):
    """
    Send email notification for new chat messages
    """
    try:
        recipient_email = None
        if sender.is_staff:
            if lead.user:
                recipient_email = lead.user.email
            subject = f"New message from admin regarding your lead #{lead.id}"
            role = "Admin"
        else:
            # Try to get assigned admin or fallback to default setting
            assigned_admin = getattr(lead, 'assigned_admin', None)
            if assigned_admin:
                email = getattr(assigned_admin, 'email', None)
                if email and email.strip():  # Check truthiness and non-empty after stripping
                    recipient_email = email.strip()
                else:
                    recipient_email = getattr(settings, 'DEFAULT_ADMIN_EMAIL', None)
            else:
                recipient_email = getattr(settings, 'DEFAULT_ADMIN_EMAIL', None)
            
            subject = f"New message from user regarding lead #{lead.id}"
            role = "User"

        if not recipient_email:
            logger.warning(f"No recipient email found for chat notification. Lead #{lead.id}, Sender ID: {sender.id}")
            return False
        body = (
            f"Hello,\n\n"
            f"You have received a new message from {role} ({sender.email}) regarding Lead #{lead.id}.\n\n"
            f"Message:\n{message}\n\n"
            f"Please log in to the dashboard to reply.\n\n"
            f"Best regards,\nTransportation Team"
        )
        
        return send_notification_email(recipient_email, subject, body)

    except Exception as e:
        logger.error(f"Failed to send chat notification: {str(e)}")
        return False