from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from .constants import default_price_constants

#user profile model
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    # Your custom fields
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    school_name = models.CharField(max_length=255, blank=True, null=True)
    verified_by_admin = models.BooleanField(default=False)

    # Add any other fields you want
    date_of_birth = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.user.username

#vehicle type model
class VehicleType(models.Model):
    """
    Minimal VehicleType model for dynamic vehicle names.
    """
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    factor = models.FloatField(
        default=1.0, help_text="Multiplier for pricing based on bus type")
    is_model_trained = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

#
class Location(models.Model):
    address = models.CharField(max_length=255)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.address



#rejected lead willl use this model  
class LeadRejection(models.Model):
    lead = models.ForeignKey(
        'Lead',
        on_delete=models.CASCADE,
        related_name='rejections'
    )
    role = models.CharField(max_length=50, null=True, blank=True)
    reason = models.TextField(help_text="Reason or comment for rejecting the price or lead.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rejection for Lead #{self.lead.id}: {self.reason[:40]}"


class Trip(models.Model):
    """
    Trip model storing journey details (Outbound or Return).
    """
    TYPE_CHOICES = [
        ('OUTBOUND', 'Outbound'),
        ('RETURN', 'Return')
    ]

    type = models.CharField(max_length=10, choices=TYPE_CHOICES, help_text="OUTBOUND or RETURN")
    
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    
    pickup_date = models.DateField()
    pickup_time = models.TimeField()
    
    arrival_time = models.CharField(max_length=50, null=True, blank=True)
    duration = models.CharField(max_length=50, null=True, blank=True)
    
    distance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} Trip: {self.pickup_location} -> {self.dropoff_location}"


class TripStop(models.Model):
    """
    Stops associated with a Trip.
    """
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='stops')
    location = models.CharField(max_length=255)
    estimated_time = models.IntegerField(default=30)
    stop_order = models.IntegerField()

    class Meta:
        ordering = ['stop_order']

    def __str__(self):
        return f"Stop {self.stop_order} for Trip {self.trip.id}"


#this is the main lead model 
class Lead(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
        ('COMPLETED', 'Completed'),
        ('BOOKED', 'Booked'),
        ('PAY_LATER', 'Pay Later'),
        ('CANCELLED', 'Cancelled'),
        ('EDITED', 'Edited')
    ]

    REJECTION_CHOICES = [
        ('UNCOVERED AREA', 'We dont service that area.'),
        ('NO BUSSES', 'No busses available for that date.'),
        ('INCOMPLETE INFO', 'We need more information to provide a quote.')
    ]
    PAYMENT_TYPE_CHOICES = [
        ('completed', 'Completed'),
        ('split', 'Split')
    ]


    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='leads',
        null=True,
        blank=True
    )

    # Linked Trips
    outbound_trip = models.ForeignKey(
        Trip, 
        on_delete=models.SET_NULL, 
        related_name='lead_outbound', 
        null=True, 
        blank=True
    )
    return_trip = models.ForeignKey(
        Trip, 
        on_delete=models.SET_NULL, 
        related_name='lead_return', 
        null=True, 
        blank=True
    )

    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    
    pickup_location = models.CharField(max_length=255, null=True, blank=True)
    dropoff_location = models.CharField(max_length=255, null=True, blank=True)
    travel_date = models.DateField(null=True, blank=True)
    pickup_time = models.TimeField(null=True, blank=True)
    is_roundtrip = models.BooleanField(default=False)
    
    vehicle_type = models.CharField(max_length=100, blank=True, null=True)
    number_of_passengers = models.IntegerField(default=0)
    
    special_instructions = models.TextField(blank=True)
    
    status = models.CharField(max_length=10,choices=STATUS_CHOICES,default='PENDING')
    is_edited = models.BooleanField(default=False,null=True)

    payment_type = models.CharField(max_length=20,choices=PAYMENT_TYPE_CHOICES,null=True,blank=True)
    split_counts = models.PositiveIntegerField(null=True,blank=True)
    
    distance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    estimated_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    calculated_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) 
    
    invoice_sent = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    
    # Kept for backward compatibility or extra metadata if needed, 
    # but strictly user requested matching schema which doesn't list these explicitly 
    # except mostly in trips now. 
    # The user request Schema for Lead:
    # id, user_id, name, email, phone_number, vehicle_type, number_of_passengers,
    # special_instructions, status, payment_type, split_counts, distance, estimated_price, calculated_price,
    # invoice_sent, email_sent, outbound_trip, return_trip, created_at, updated_at
    
    # I will keep other fields as they might be used by existing views/logic until fully refactored,
    # otherwise I break the whole app.
    # However, the user request "add this to models" implies replacing or appending.
    # Given the manual cleanup by user, I should probably stick to what they asked for + essential fields.
    
    # ... restoring essential fields that might be used by legacy but not in new schema?
    # User manually deleted many fields in previous steps (Quotation etc).
    # I'll keep the ones currently in Lead that match the new schema + keys.
    
    institute_name = models.CharField(max_length=255, blank=True, null=True)
    number_of_students = models.PositiveIntegerField(blank=True, null=True)
    number_of_teachers = models.PositiveIntegerField(blank=True, null=True)

    admin_message = models.TextField(null=True, blank=True)
    
    pickup_reminder_sent = models.DateTimeField(null=True, blank=True,
        help_text="Timestamp of last pickup reminder email sent")
    reminder_processed = models.BooleanField(default=False,help_text="Indicates if the reminder was processed (even if skipped)")
    is_edited = models.BooleanField(default=False,null=True)
    
    temp_password = models.CharField(max_length=128, blank=True, null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    invoice_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"Lead {self.id} - {self.name} <{self.email}>"

    def save(self, *args, **kwargs):
        if self.payment_type == 'split' and (not self.split_counts or self.split_counts <= 0):
            raise ValueError("Split counts must be a positive number when payment type is split.")

        if self.split_counts is not None and self.payment_type != 'split':
            raise ValueError("Payment type must be 'split' when split counts are specified.")

        if not self.pk:  # only on creation
            self.calculated_price = self.estimated_price
        if self.payment_type == 'completed':
            self.split_counts = None

        super().save(*args, **kwargs)

#email templates are stored is this model
class Emails(models.Model):
    purpose = models.CharField(max_length=255)
    subject = models.TextField()
    message = models.TextField()

#notification model
class Notification(models.Model):
    TYPE_CHOICES = [
        ('QUOTE_CREATED', 'Quote Created'),
        ('STATUS_UPDATE', 'Status Update'),
        ('PRICE_UPDATE', 'Price Update'),
        ('ADMIN_UPDATE', 'Admin Update'),
        ('PAYMENT_UPDATE', 'Payment Update'),
        ('TRIP_APPROVED', 'Lead Approved'),
        ('TRIP_REJECTED', 'Lead Rejected'),
        ('CHAT_USER', 'Chat Message (User)'),
        ('CHAT_ADMIN', 'Chat Message (Admin)'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True) 
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='ADMIN_UPDATE')
    title = models.CharField(max_length=200, null=True, blank=True)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    email_sent = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.user and not self.lead:
            raise ValidationError("Either user or lead must be provided.")
        if self.user and not self.title:
            raise ValidationError("Title is required when user is specified.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.lead:
            return f"{self.notification_type} for Lead {self.lead.id}"
        elif self.user and self.title:
            return f"{self.title} for User {self.user.username}"
        else:
            return f"Notification {self.id}"


class OTP(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    purpose = models.CharField(
        max_length=20,
        choices=[
            ('SIGNUP', 'Signup Verification'),
            ('LOGIN', 'Login Verification'),
            ('RESET', 'Password Reset')
        ]
    )
    _registration_data = models.TextField(null=True, blank=True, db_column='registration_data')

    def is_valid(self):
        from datetime import timedelta
        return (timezone.now() - self.created_at) < timedelta(minutes=10)

    @property
    def registration_data(self):
        import json
        if self._registration_data:
            return json.loads(self._registration_data)
        return None

    @registration_data.setter
    def registration_data(self, value):
        import json
        self._registration_data = json.dumps(value) if value else None

    class Meta:
        indexes = [
            models.Index(fields=['email', 'purpose']),
        ]


class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='approved_admins'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Admin: {self.user.email}"


class AdminNotification(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE)
    lead = models.ForeignKey(
        Lead, on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.lead:
            return f"Notification for {self.admin.email}: Lead {self.lead.id}"
        return f"Notification for {self.admin.email}"


#this model is use for payment records 
class Transaction(models.Model):
    """Tracks all payment transactions, both complete and split payments"""

    PAYMENT_TYPE_CHOICES = [
        ('FULL', 'Full Payment'),
        ('SPLIT', 'Split Payment'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('PARTIAL', 'Partial'),
        ('FAILED', 'Failed'),
    ]

    # This should reference Lead, not Quotation
    lead = models.ForeignKey(
        Lead, on_delete=models.CASCADE, related_name='transaction')
    payment_type = models.CharField(
        max_length=20, choices=PAYMENT_TYPE_CHOICES)
    payment_id = models.CharField(max_length=255, null=True, blank=True)
    payment_url = models.CharField(max_length=255, null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    admin_message = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='PENDING')
    total_splits_count = models.IntegerField(null=True, blank=True)
    amount_per_split = models.DecimalField(max_digits=10, decimal_places=2)
    split_paid_count = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.payment_type} - {self.lead.id} - {self.status}"

class ChatMessage(models.Model):
    MESSAGE_TYPE_CHOICES = [
        ('USER', 'User'),
        ('ADMIN', 'Admin'),
        ('SYSTEM', 'System')
    ]

    lead = models.ForeignKey(
        Lead, on_delete=models.CASCADE, related_name='chat_messages')
    message_type = models.CharField(
        max_length=10, choices=MESSAGE_TYPE_CHOICES)
    message = models.TextField()
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_messages', null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Chat for trip {self.lead.id} - {self.message_type} - {self.created_at}"

class XeroToken(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='xero_token')
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    tenant_id = models.CharField(max_length=255, blank=True, null=True)
    scope = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Xero Token for {self.user.email}"

