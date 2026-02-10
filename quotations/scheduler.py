

import logging
from datetime import date, timedelta
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
from django.db.models import Q
from .models import Lead, AdminProfile, Emails
from django.db import connection
from datetime import datetime, time
from django.utils import timezone

logger = logging.getLogger(__name__)

def send_payment_reminder():
    try:
        today = date.today()
        three_days_from_now = today + timedelta(days=3)
        # Fetch leads with travel_date between tomorrow and three days from now,
        # where status is ACCEPTED, and either no transaction exists or the existing transaction has a PENDING status.
        # Removed the 'reminder_email_sent=False' filter
        leads = Lead.objects.filter(
            travel_date__gt=today,
            travel_date__lte=three_days_from_now,
            status='ACCEPTED',
            email_sent=False
        ).filter(
            Q(transaction__isnull=True) | Q(transaction__status='PENDING')
        ).distinct()

        if leads:
            logger.info("Leads found for reminder")

        for lead in leads:
            try:
                transaction = lead.transaction.first()  # Returns None if no transaction exists

                # Case 1: No transaction exists
                if transaction is None:
                    subject = f"Payment Reminder for Lead #{lead.id}"
                    message = (
                        f"Dear {lead.name},\n\n"
                        f"This is a reminder that payment for your lead #{lead.id} "
                        f"is still pending (no payment record exists). Your ride is scheduled soon (on {lead.travel_date}).\n\n"
                        f"Please complete the payment at your earliest convenience.\n\n"
                        f"Best regards,\nYour Transport Team"
                    )
                # Case 2: A transaction exists and its status is PENDING
                elif transaction.status == 'PENDING':
                    if transaction.payment_type == 'COMPLETE':
                        subject = f"Payment Reminder for Lead #{lead.id}"
                        message = (
                            f"Dear {lead.name},\n\n"
                            f"This is a reminder that the complete payment for your lead #{lead.id} "
                            f"is still pending. Your ride is scheduled soon (on {lead.travel_date}).\n\n"
                            f"Please complete the payment at your earliest convenience.\n\n"
                            f"Best regards,\nYour Transport Team"
                        )
                    elif transaction.payment_type == 'SPLIT':
                        subject = f"Payment Reminder for Lead #{lead.id}"
                        splits_paid = transaction.split_paid_count if transaction.split_paid_count is not None else 0
                        total_splits = transaction.total_splits_count if transaction.total_splits_count is not None else "N/A"
                        message = (
                            f"Dear {lead.name},\n\n"
                            f"This is a reminder that the split payment for your lead #{lead.id} "
                            f"is still pending. Your ride is scheduled soon (on {lead.travel_date}).\n\n"
                            f"You have paid {splits_paid} out of {total_splits} splits.\n\n"
                            f"Please complete your pending splits as soon as possible.\n\n"
                            f"Best regards,\nYour Transport Team"
                        )
                    else:
                        logger.info(f"Unknown payment type '{transaction.payment_type}' for Lead #{lead.id}")
                        lead.reminder_processed = True
                        lead.email_sent = True
                        lead.save(update_fields=['reminder_processed', 'email_sent'])
                        continue                # Case 3: Transaction exists and its status is COMPLETED: Skip sending email.
                else:
                    logger.info(f"Lead #{lead.id} has transaction status '{transaction.status}'. No email sent.")
                    continue

                if lead.email:
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                        recipient_list=[lead.email],
                        fail_silently=False,
                    )
                    logger.info(f"Email sent for Lead #{lead.id}")
                    
                    # Set email_sent flag instead if needed
                    lead.email_sent = True
                    lead.save(update_fields=['email_sent'])
                    logger.info(f"Set email_sent flag for Lead #{lead.id}")
                else:
                    logger.warning(f"Lead #{lead.id} has no email address. Skipping email.")

            except Exception as loop_e:
                logger.error(f"Error processing payment reminder for Lead #{lead.id}: {str(loop_e)}")
    except Exception as e:
        logger.error(f"Error in send_payment_reminder: {str(e)}")


def send_pickup_time_reminders():
    """
    Send pickup time reminder emails to users and admins for leads with upcoming pickup times.
    Checks for leads where pickup_time is within the next 24 hours and sends reminders every 24 hours.
    """
    try:
        now = timezone.now()
        today = now.date()
        current_time = now.time()
        
        # Calculate 24 hours from now and 24 hours ago
        twenty_four_hours_later = now + timedelta(hours=24)
        twenty_four_hours_ago = now - timedelta(hours=24)
        
        # Find leads with pickup times in the next 24 hours
        # This includes today's leads with pickup time after current time, and tomorrow's leads
        # Also filter out leads that already had reminders sent within the last 24 hours
        leads_today = Lead.objects.filter(
            travel_date=today,
            pickup_time__gt=current_time,
            pickup_time__isnull=False,
            status__in=['PENDING', 'ACCEPTED']
        ).filter(
            Q(pickup_reminder_sent__isnull=True) | Q(pickup_reminder_sent__lt=twenty_four_hours_ago)
        )
        
        leads_tomorrow = Lead.objects.filter(
            travel_date=today + timedelta(days=1),
            pickup_time__isnull=False,
            status__in=['PENDING', 'ACCEPTED']
        ).filter(
            Q(pickup_reminder_sent__isnull=True) | Q(pickup_reminder_sent__lt=twenty_four_hours_ago)
        )
        
        # Combine both querysets
        upcoming_leads = list(leads_today) + list(leads_tomorrow)
        
        # Filter to only those within exactly 24 hours
        filtered_leads = []
        for lead in upcoming_leads:
            pickup_datetime = datetime.combine(lead.travel_date, lead.pickup_time)
            pickup_datetime = timezone.make_aware(pickup_datetime) if timezone.is_naive(pickup_datetime) else pickup_datetime
            
            # Check if pickup time is within next 24 hours
            if now <= pickup_datetime <= twenty_four_hours_later:
                filtered_leads.append(lead)
        
        if filtered_leads:
            logger.info(f"Found {len(filtered_leads)} leads with pickup times in next 24 hours")
        
        for lead in filtered_leads:
            # Send email to user
            try:
                # Get user email template
                try:
                    user_email_template = Emails.objects.get(purpose="pickup_reminder_user")
                except Emails.DoesNotExist:
                    logger.error("User pickup reminder email template not found!")
                    continue
                
                # Prepare template variables
                final_destination_info = f"Final Destination: {lead.final_destination}" if lead.final_destination else ""
                final_pickup_info = f"Final Pickup: {lead.final_pickup}" if getattr(lead, 'final_pickup', None) else ""
                roundtrip_info = ""
                if lead.is_roundtrip:
                    roundtrip_parts = ["Roundtrip: Yes"]
                    if lead.roundtrip_pickup_date:
                        roundtrip_parts.append(f"Return Date: {lead.roundtrip_pickup_date}")
                    if lead.roundtrip_pickup_time:
                        roundtrip_parts.append(f"Return Time: {lead.roundtrip_pickup_time.strftime('%H:%M')}")
                    roundtrip_info = "\n".join(roundtrip_parts)
                
                user_subject = user_email_template.subject.format(lead_id=lead.id)
                user_message = user_email_template.message.format(
                    name=lead.name,
                    lead_id=lead.id,
                    travel_date=lead.travel_date,
                    pickup_time=lead.pickup_time.strftime('%H:%M'),
                    pickup_location=lead.pickup_location,
                    dropoff_location=lead.dropoff_location,
                    number_of_passengers=lead.number_of_passengers,
                    vehicle_type=lead.vehicle_type,
                    status=lead.status,
                    final_destination_info=final_destination_info,
                    final_pickup_info=final_pickup_info,
                    roundtrip_info=roundtrip_info
                )

                # Send to lead's email
                if lead.email:
                    send_mail(
                        subject=user_subject,
                        message=user_message,
                        from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                        recipient_list=[lead.email],
                        fail_silently=False,
                    )
                    logger.info(f"Pickup reminder sent to user: {lead.email} for Lead #{lead.id}")
                
                # Send to associated user's email if different
                if lead.user and lead.user.email and lead.user.email != lead.email:
                    send_mail(
                        subject=user_subject,
                        message=user_message,
                        from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                        recipient_list=[lead.user.email],
                        fail_silently=False,
                    )
                    logger.info(f"Pickup reminder sent to associated user: {lead.user.email} for Lead #{lead.id}")
                
            except Exception as e:
                logger.error(f"Error sending pickup reminder to user for Lead #{lead.id}: {str(e)}")
            
            # Send email to all approved admins
            try:
                # Get admin email template
                try:
                    admin_email_template = Emails.objects.get(purpose="pickup_alert_admin")
                except Emails.DoesNotExist:
                    logger.error("Admin pickup alert email template not found!")
                    continue
                
                # Prepare template variables
                final_destination_info = f"Final Destination: {lead.final_destination}" if lead.final_destination else ""
                final_pickup_info = f"Final Pickup: {lead.final_pickup}" if getattr(lead, 'final_pickup', None) else ""
                roundtrip_info = ""
                if lead.is_roundtrip:
                    roundtrip_parts = ["Roundtrip: Yes"]
                    if lead.roundtrip_pickup_date:
                        roundtrip_parts.append(f"Return Date: {lead.roundtrip_pickup_date}")
                    if lead.roundtrip_pickup_time:
                        roundtrip_parts.append(f"Return Time: {lead.roundtrip_pickup_time.strftime('%H:%M')}")
                    roundtrip_info = "\n".join(roundtrip_parts)
                else:
                    roundtrip_info = "Roundtrip: No"
                
                special_instructions = f"Special Instructions: {lead.special_instructions}" if lead.special_instructions else ""
                
                admin_subject = admin_email_template.subject.format(lead_id=lead.id)
                admin_message = admin_email_template.message.format(
                    lead_id=lead.id,
                    name=lead.name,
                    email=lead.email,
                    institute_name=lead.institute_name or 'N/A',
                    travel_date=lead.travel_date,
                    pickup_time=lead.pickup_time.strftime('%H:%M'),
                    pickup_location=lead.pickup_location,
                    dropoff_location=lead.dropoff_location,
                    number_of_passengers=lead.number_of_passengers,
                    vehicle_type=lead.vehicle_type,
                    status=lead.status,
                    distance=lead.distance,
                    estimated_price=lead.estimated_price,
                    final_destination_info=final_destination_info,
                    final_pickup_info=final_pickup_info,
                    roundtrip_info=roundtrip_info,
                    special_instructions=special_instructions
                )

                # Get all approved admins
                approved_admins = AdminProfile.objects.filter(is_approved=True)
                admin_emails = [admin.user.email for admin in approved_admins if admin.user.email]
                
                if admin_emails:
                    email = EmailMessage(
                        subject=admin_subject,
                        body=admin_message,
                        from_email=f"{settings.EMAIL_SENDER_NAME_ADMIN} <{settings.DEFAULT_FROM_EMAIL}>",
                        to=[],  # Intentionally empty to use BCC
                        bcc=admin_emails,
                    )
                    email.send(fail_silently=False)
                    logger.info(f"Pickup alert sent to {len(admin_emails)} admins for Lead #{lead.id}")
                else:
                    logger.warning("No admin emails found for pickup alert")
                    
            except Exception as e:
                logger.error(f"Error sending pickup alert to admins for Lead #{lead.id}: {str(e)}")
            
            # Update the pickup_reminder_sent timestamp after successfully sending emails
            try:
                lead.pickup_reminder_sent = now
                lead.save(update_fields=['pickup_reminder_sent'])
                logger.info(f"Updated pickup_reminder_sent timestamp for Lead #{lead.id}")
            except Exception as e:
                logger.error(f"Error updating pickup_reminder_sent for Lead #{lead.id}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error in send_pickup_time_reminders: {str(e)}")



# DISABLED: This function uses the deleted Quotation model
# def send_pending_quote_reminders():
#     """
#     Send reminder emails to users who have pending quotes every Sunday midnight.
#     """
#     try:
#         # Find all pending quotes
#         pending_quotes = Quotation.objects.filter(status='PENDING')
#         
#         if pending_quotes.exists():
#             logger.info(f"Found {pending_quotes.count()} pending quotes for weekly reminder.")
#             
#             # Get or create the email template
#             email_template, created = Emails.objects.get_or_create(
#                 purpose='pending_quote_weekly_reminder',
#                 defaults={
#                     'subject': 'Action Required: Pending Quote #{quotation_id}',
#                     'message': '''Dear {user_name},
# 
# We noticed you have a pending quote request #{quotation_id} with us.
# 
# Details:
# - Pickup: {pickup_location}
# - Dropoff: {dropoff_location}
# - Date: {travel_date}
# - Price: €{price}
# 
# Please log in to your dashboard to Accept or Reject this quote so we can proceed or close the request.
# 
# Dashboard Link: https://schoolbooking.davelongcoachtravel.ie/user_dashboard
# 
# Best regards,
# Dave Long Coach Travel Team'''
#                 }
#             )
# 
#             for quote in pending_quotes:
#                 try:
#                     user = quote.user
#                     if not user or not user.email:
#                         continue
# 
#                     # Prepare context
#                     context = {
#                         'user_name': user.first_name or user.username,
#                         'quotation_id': quote.id,
#                         'pickup_location': quote.pickup_location,
#                         'dropoff_location': quote.dropoff_location,
#                         'travel_date': quote.travel_date,
#                         'price': quote.estimated_price
#                     }
# 
#                     subject = email_template.subject.format(**context)
#                     message = email_template.message.format(**context)
# 
#                     send_mail(
#                         subject=subject,
#                         message=message,
#                         from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
#                         recipient_list=[user.email],
#                         fail_silently=False,
#                     )
#                     logger.info(f"Pending quote reminder sent to {user.email} for Quote #{quote.id}")
# 
#                 except Exception as e:
#                     logger.error(f"Failed to send pending quote reminder for Quote #{quote.id}: {e}")
# 
#     except Exception as e:
#         logger.error(f"Error in send_pending_quote_reminders: {e}")


def complete_past_leads():
    """
    Automatically mark leads as 'COMPLETED' if their travel_date has passed.
    """
    try:
        today = timezone.now().date()
        # Find leads where travel_date is in the past and status is 'ACCEPTED'
        past_leads = Lead.objects.filter(
            travel_date__lt=today,
            status='ACCEPTED'
        )
        
        count = past_leads.count()
        if count > 0:
            updated_count = past_leads.update(status='COMPLETED')
            logger.info(f"Automatically completed {updated_count} past leads.")
        else:
            logger.info("No past leads found to complete.")

    except Exception as e:
        logger.error(f"Error in complete_past_leads: {str(e)}")

def start_scheduler():
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names()
        if "django_apscheduler_djangojob" not in tables:
            logger.warning("django_apscheduler_djangojob table does not exist yet. Scheduler not started.")
            return
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), "default")
    scheduler.add_job(send_payment_reminder, 'interval', minutes=1, id='payment_reminder_job', replace_existing=True)
    scheduler.add_job(send_pickup_time_reminders, 'interval', hours=1, id='pickup_reminder_job', replace_existing=True)
    
    # DISABLED: Weekly Sunday Midnight Job for pending quote reminders (function disabled)
    # scheduler.add_job(
    #     send_pending_quote_reminders, 
    #     'cron', 
    #     day_of_week='sun', 
    #     hour=0, 
    #     minute=0, 
    #     id='weekly_pending_quote_reminder', 
    #     replace_existing=True
    # )

    # Daily job to complete past leads
    scheduler.add_job(
        complete_past_leads,
        'cron',
        hour=0,
        minute=5,  # Run just after midnight
        id='auto_complete_past_leads',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler started: Payment reminder (1m), Pickup reminder (1h), Weekly Pending Quote reminder (Sun 00:00), and Auto-complete past leads (daily 00:05).")