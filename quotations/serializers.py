from rest_framework.validators import UniqueValidator
from .models import Emails
from rest_framework import serializers
from django.utils import timezone
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, TrackingSettings, ClickTracking
from django.core.mail import EmailMessage

from django.contrib.auth.models import User
from .models import *
import random
import string
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .quotation_services import get_aggregated_distance_lead

class ProfileSerializer(serializers.ModelSerializer):
    contact_number = serializers.CharField(default='', allow_blank=True, allow_null=True)
    school_name = serializers.CharField(default='', allow_blank=True, allow_null=True)
    date_of_birth = serializers.DateField(default=None, allow_null=True)
    verified_by_admin = serializers.BooleanField(required=False)

    class Meta:
        model = Profile
        fields = ['contact_number', 'school_name', 'verified_by_admin', 'date_of_birth']
class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'profile']  
        extra_kwargs = {
            'password': {'write_only': True},
            'username': {'read_only': True}
        }
class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ('id', 'address', 'latitude', 'longitude')


class TripStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripStop
        fields = ('id', 'location', 'estimated_time', 'stop_order')
        extra_kwargs = {
            'location': {'required': False},
            'estimated_time': {'required': False},
            'stop_order': {'required': False}
        }


class TripSerializer(serializers.ModelSerializer):
    stops = TripStopSerializer(many=True, required=False)

    class Meta:
        model = Trip
        fields = (
            'id', 'type', 'pickup_location', 'dropoff_location',
            'pickup_date', 'pickup_time', 'arrival_time', 'duration',
            'distance', 'created_at', 'stops'
        )


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'user', 'lead', 'notification_type', 'title', 'message',
                  'sent_at', 'email_sent', 'is_read', 'created_at']


# Removed QuotationSerializer as the model is deleted.




class LeadSerializer(serializers.ModelSerializer):
    outbound_trip = TripSerializer(required=False)
    return_trip = TripSerializer(required=False)

    # Allow vehicle_type override
    vehicle_type = serializers.CharField(required=False, allow_blank=True)

    # NEW PICKUP STOP FIELDS
    pickup_stop = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Additional pickup stop location"
    )
    return_pickup_stop = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Return pickup stop location for roundtrip"
    )
    final_destination = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Final destination for roundtrip journeys"
    )
    final_pickup = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Final pickup location for roundtrip journeys"
    )
    duration = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Duration string for journey (e.g. '4:43hrs')"
    )

    # New contact fields - REMOVE UNIQUENESS VALIDATION
    name = serializers.CharField()
    email = serializers.EmailField(required=False)  # Removed UniqueValidator
    phone_number = serializers.CharField(
        required=False,
        max_length=20,
        allow_blank=True,
        allow_null=True)
    email_sent = serializers.BooleanField(default=False)

    # New payment-related fields
    PAYMENT_TYPE_CHOICES = [
        ('completed', 'Completed'),
        ('split', 'Split')
    ]
    payment_type = serializers.ChoiceField(
        choices=PAYMENT_TYPE_CHOICES,
        required=False,
        allow_null=True
    )
    split_counts = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0
    )
    # New fields as requested
    institute_name = serializers.CharField(
        required=False, allow_blank=True, allow_null=True)
    number_of_students = serializers.IntegerField(
        required=False, allow_null=True, min_value=0)
    number_of_teachers = serializers.IntegerField(
        required=False, allow_null=True, min_value=0)

    class Meta:
        model = Lead
        fields = (
            'id',
            'user',
            'pickup_location',
            'dropoff_location',
            'pickup_stop',
            'return_pickup_stop',
            'final_destination',
            'final_pickup',
            'duration',
            'is_roundtrip',
            'vehicle_type',
            'number_of_passengers',
            'distance',
            'estimated_price',
            'calculated_price',  # 👈 add this
            'admin_message',
            'invoice_sent',
            'created_at',
            'updated_at',
            # New fields
            'name',
            'email',
            'phone_number',
            'email_sent',
            # Payment-related fields
            'payment_type',
            'split_counts',
            # New fields as requested
            'institute_name',
            'number_of_students',
            'number_of_teachers',
            # Nested trips
            'outbound_trip',
            'return_trip',
            'status',
            'special_instructions',
            'pickup_reminder_sent',
        )
        read_only_fields = (
            'distance',
            'created_at',
            'updated_at',
            'user',  
            'pickup_reminder_sent',
            'is_edited',  
            #'invoice_sent'
        )

    def validate(self, data):
        request = self.context.get('request')

        # Check if user is authenticated
        if request and request.user.is_authenticated:
            # Authenticated user - allow creation
            return data

        # For unauthenticated users, check if email already exists in User model
        email = data.get('email')

        # Existing validation logic
        # Get the current date and time
        now = timezone.now()
        today = now.date()
        current_time = now.time()

        # Validate that travel_date is not in the past
        travel_date = data.get('travel_date')
        roundtrip_pickup_date = data.get("roundtrip_pickup_date")


        # Validate payment-related fields
        payment_type = data.get('payment_type')
        split_counts = data.get('split_counts')

        # If payment_type is 'split', split_counts must be provided and > 0
        if payment_type == 'split':
            if not split_counts or split_counts <= 0:
                raise serializers.ValidationError({
                    "split_counts": "Split counts must be a positive number when payment type is split."
                })

        # If split_counts is provided, payment_type must be 'split'
        if split_counts is not None and payment_type != 'split':
            raise serializers.ValidationError({
                "payment_type": "Payment type must be 'split' when split counts are specified."
            })
        # If payment_type is 'completed', split_counts must be null
        if payment_type == 'completed' and split_counts is not None:
            raise serializers.ValidationError({
                "split_counts": "Split counts must be null when payment type is completed."
            })

        if 'outbound_trip' in data:
            self._validate_trip(data['outbound_trip'], 'outbound_trip')
        if 'return_trip' in data:
            self._validate_trip(data['return_trip'], 'return_trip')

        status = data.get('status')
        rejection_reason = data.get('rejection_reason')
        if status == 'REJECTED' and not rejection_reason:
            raise serializers.ValidationError(
                {"rejection_reason": "Rejection reason is required when status is REJECTED."})

        return data

    def _validate_trip(self, trip_data, field_name):
        required_fields = ['pickup_location', 'dropoff_location', 'pickup_date', 'pickup_time']
        for field in required_fields:
            if not trip_data.get(field):
                raise serializers.ValidationError({
                    field_name: {field: "This field is required."}
                })
        
        # Validate stops
        if 'trip_stops' in trip_data:
            for stop in trip_data['trip_stops']:
                if not stop.get('location'):
                    raise serializers.ValidationError("Stop location is required.")

    def _create_trip(self, trip_data, trip_type):
        stops_data = trip_data.pop('trip_stops', [])
        
        # Create Trip
        trip = Trip.objects.create(type=trip_type, **trip_data)
        
        # Create TripStops
        for stop_data in stops_data:
            TripStop.objects.create(trip=trip, **stop_data)
            
        return trip

    def create(self, validated_data):
        request = self.context.get('request')
        contact_number = validated_data.get("phone_number")
        school_name = validated_data.get("institute_name")
        
        # Pop nested trip data
        outbound_data = validated_data.pop('outbound_trip', None)
        return_data = validated_data.pop('return_trip', None)
        
        # Pop legacy stops data (ignored)
        validated_data.pop('stops_lead', None)
        validated_data.pop('roundtrip_stops_lead', None)

        # 2) Handle user authentication logic
        if request and request.user.is_authenticated:
            # User is logged in - use their account
            user = request.user
            email = user.email  # Use the logged-in user's email
            name = validated_data.get(
                'name', user.get_full_name() or user.username)
            plain_password = None

            # Update name from user profile if not provided
            if 'name' not in validated_data and user.get_full_name():
                validated_data['name'] = user.get_full_name()
            elif 'name' not in validated_data:
                validated_data['name'] = user.username

        else:
            # User is not logged in - require email
            email = validated_data.get('email')
            name = validated_data.get('name')

            if not email:
                raise serializers.ValidationError({
                    "email": "Email is required for new users."
                })

            # Create new user
            user, plain_password = self.create_or_get_user(email, name)

        # 3) Ensure email is set in validated_data (for logged-in users)
        validated_data['email'] = email

        # 4) Create the lead instance
        lead = Lead.objects.create(**validated_data, user=user)

        # Handle Trips
        if outbound_data:
            outbound_trip = self._create_trip(outbound_data, 'OUTBOUND')
            lead.outbound_trip = outbound_trip
            
        if return_data:
            return_trip = self._create_trip(return_data, 'RETURN')
            lead.return_trip = return_trip
        
        # Ensure is_roundtrip is set if return trip exists
        if lead.return_trip:
            lead.is_roundtrip = True
            
        lead.save()

        # ------------------------------------------------------------
        # ⭐⭐⭐ ADD PROFILE SAVE HERE ⭐⭐⭐
        # ------------------------------------------------------------
        profile, created = Profile.objects.get_or_create(user=user)

        profile.contact_number = contact_number or profile.contact_number
        profile.school_name = school_name or profile.school_name
        # profile.verified_by_admin stays unchanged unless admin updates it
        profile.save()
        # ------------------------------------------------------------
        try:
            lead.distance = get_aggregated_distance_lead(lead)
        except ValueError:
            lead.distance = 0
            
        # 6) Handle email sending
        if plain_password is not None:  # New user
            lead.temp_password = plain_password
            lead.save(update_fields=['temp_password'])
            self.send_quote_request_email(lead)
            lead.temp_password = None
            lead.save(update_fields=['temp_password'])
        else:
            self.send_existing_user_email(lead)

        return lead

    def update(self, instance, validated_data):
        # Handle nested fields - extract them first
        outbound_data = validated_data.pop('outbound_trip', None)
        return_data = validated_data.pop('return_trip', None)
        
        stops_lead_data = validated_data.pop('stops_lead', None) # Ignored
        roundtrip_stops_lead_data = validated_data.pop('roundtrip_stops_lead', None) # Ignored
        user_data = validated_data.pop('user', None)  # Remove user if present


        # Update Basic Lead fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Update Trips
        if outbound_data and instance.outbound_trip:
            self._update_trip(instance.outbound_trip, outbound_data)
        elif outbound_data: # create if missing
            instance.outbound_trip = self._create_trip(outbound_data, 'OUTBOUND')
            
        if return_data and instance.return_trip:
            self._update_trip(instance.return_trip, return_data)
        elif return_data: # create if missing
             instance.return_trip = self._create_trip(return_data, 'RETURN')
             instance.is_roundtrip = True

        # Save the instance with all the updated fields
        instance.save()

        return instance

    def _update_trip(self, trip, trip_data):
        stops_data = trip_data.pop('trip_stops', None)
        
        # Update trip fields
        for attr, value in trip_data.items():
            setattr(trip, attr, value)
        trip.save()
        
        # Handle stops only if provided
        if stops_data is not None:
            # Simple strategy: Delete all existing stops and recreate (easier than syncing)
            trip.stops.all().delete()
            for stop_data in stops_data:
                TripStop.objects.create(trip=trip, **stop_data)

    # _update_nested_stops helper removed

    def create_or_get_user(self, email, name):
        """Create a new user or return existing one with plain password"""
        # First check if user already exists
        if User.objects.filter(email=email).exists():
            # User exists, just fetch and return
            user = User.objects.get(email=email)
            # Update name fields if they're empty and name is provided
            if not user.first_name and name:
                names = name.split(' ', 1)
                user.first_name = names[0]
                if len(names) > 1:
                    user.last_name = names[1]
                user.save()
            # Return existing user with None password
            return user, None

        # User doesn't exist, create new user
        # Generate random password
        plain_password = ''.join(random.choices(
            string.ascii_letters + string.digits + '!@#$%^&*', k=12))

        # Split name into first and last name
        names = name.split(' ', 1)
        first_name = names[0]
        last_name = names[1] if len(names) > 1 else ''

        # Create user with plain text password
        user = User(
            username=email,
            email=email,
            password=plain_password,  # Store as plain text
            first_name=first_name,
            last_name=last_name
        )
        user.save()
        return user, plain_password

    def get_email_context(self, lead):
        """Prepare context for email template variables"""
        # Stops info
        stops_info = ""
        if lead.outbound_trip:
            for stop in lead.outbound_trip.stops.order_by('stop_order'):
                stops_info += f"- {stop.location} ({stop.estimated_time} mins)\n"
        
        if lead.return_trip:
             for stop in lead.return_trip.stops.order_by('stop_order'):
                stops_info += f"- (Return) {stop.location} ({stop.estimated_time} mins)\n"

        distance_str = f"{lead.distance:.2f} km" if lead.distance else "0 km"

        context = {
            'name': lead.name or '',
            'lead': lead,
            'pickup_location': lead.pickup_location or '',
            'dropoff_location': lead.dropoff_location or '',
            'round_trip_text': 'Yes' if lead.is_roundtrip else 'No',
            'lead_url': f"https://schoolbooking.davelongcoachtravel.ie/user_dashboard/{lead.id}",
            'login_url': 'https://schoolbooking.davelongcoachtravel.ie/login',
            'username': lead.user.username if lead.user else lead.email or '',
            'email': lead.user.email if lead.user else lead.email or '',
            'pickup_date': lead.travel_date.strftime("%d-%m-%Y") if lead.travel_date else 'null',
            'pickup_time': lead.pickup_time.strftime("%I:%M %p") if lead.pickup_time else 'null',
            'dropoff_date': lead.roundtrip_pickup_date.strftime("%d-%m-%Y") if lead.roundtrip_pickup_date else 'null',
            'dropoff_time': lead.roundtrip_pickup_time.strftime("%I:%M %p") if lead.roundtrip_pickup_time else 'null',
            'pickup_stop': lead.pickup_stop or 'null',
            'return_pickup_stop': lead.return_pickup_stop or 'null',
            'final_destination': lead.final_destination or 'null',
            'final_pickup': lead.final_pickup or 'null',
            'stops_info': stops_info if stops_info else "No additional stops",
            'number_of_passengers': lead.number_of_passengers or 'null',
            'duration': lead.duration or 'null',
            'total_distance': f"{lead.distance:.2f} km" if lead.distance else '0 km',
            'return_pickup_info': f"{lead.return_pickup_stop or 'null'} on {lead.roundtrip_pickup_date.strftime('%d-%m-%Y') if lead.roundtrip_pickup_date else 'null'} at {lead.roundtrip_pickup_time.strftime('%I:%M %p') if lead.roundtrip_pickup_time else 'null'}",
            'return_dropoff_info': f"{lead.final_destination or 'null'} ",
        }

        if hasattr(lead, 'temp_password') and lead.temp_password:
            context['password'] = lead.temp_password
        else:
            context['password'] = 'Use your existing password'

        return context  
    def send_existing_user_email(self, lead):
        """Send email to existing users telling them they already have an account"""
        try:
            email_template, created = Emails.objects.get_or_create(
                purpose='existing_user_quote_request',
                defaults={
                    'subject': 'Quote Request Received - Please Login to Your Account',
                    'message': '''Hi {name},

    We've received your quote request. You already have an account with us.

    Please login to your account to view your quote request and manage your bookings:
    {login_url}

    Your login email: {email}
    Please use your existing password to login.

    Quote Details:
    - Pickup: {pickup_location} on {pickup_date} at {pickup_time}
    - Dropoff: {dropoff_location} on {dropoff_date} at {dropoff_time}
    - Round Trip: {round_trip_text}
    - Stops:{stops_info}
    - Passengers: {number_of_passengers}
    - Duration: {duration}
    - Total Distance: {total_distance}
    - Return Pickup: {return_pickup_info}
    - Return Dropoff: {return_dropoff_info}
    Thank you for choosing our service!
 
    Best regards,
    Customer Service Team.
    Dave Long Coach Travel
    General Enquires: info@davelongcoachtravel.ie
    Bookings: booking@davelongcoachtravel.ie
    Call: 028 21138
    Dave Long Coach Travel
    Curragh, Skibbereen, Co. Cork
    
    '''
                }
            )

            # Prepare context
            context = self.get_email_context(lead)

            # Render the template with context
            subject = email_template.subject.format(**context)
            message_body = email_template.message.format(**context)

            # Create SendGrid Mail object
            message = Mail(
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                to_emails=lead.email,
                subject=subject,
                plain_text_content=message_body
            )

            # Disable click tracking so original URL is shown
            tracking_settings = TrackingSettings(click_tracking=ClickTracking(enable=False, enable_text=False))
            message.tracking_settings = tracking_settings

            # Send email
            sg = SendGridAPIClient(settings.EMAIL_HOST_PASSWORD)
            response = sg.send(message)


        except Exception as e:
            print(f"Failed to send existing user email: {e}")

    def send_quote_request_email(self, lead):
        """Send quote request email using template with dynamic variables via SMTP"""
        try:
         
            # Get the email template
            email_template = Emails.objects.get(purpose='quote_request_received')

            # Prepare context
            context = self.get_email_context(lead)

            # Render subject and message
            subject = email_template.subject.format(**context)
            message_body = email_template.message.format(**context)

            # Construct email
            email = EmailMessage(
                subject=subject,
                body=message_body,
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                to=[lead.email],
            )
            email.send(fail_silently=False)
            print("Quote request email sent successfully")

        except Emails.DoesNotExist:
            print("Quote request email template not found")
        except Exception as e:
            print(f"Failed to send quote request email: {e}")


class LeadSimilarityCheckSerializer(serializers.Serializer):
    pickup_location = serializers.CharField(required=False, allow_blank=True)
    dropoff_location = serializers.CharField(required=False, allow_blank=True)
    is_roundtrip = serializers.BooleanField(default=False)
    stops_lead = TripStopSerializer(many=True, required=False)
    roundtrip_stops_lead = TripStopSerializer(
        many=True, required=False)

    def validate(self, data):
        # Basic validation - at least one location should be provided
        if not data.get('pickup_location') and not data.get('dropoff_location'):
            raise serializers.ValidationError(
                "At least one location (pickup or dropoff) must be provided."
            )
        return data


class PublicLeadCreationSerializer(serializers.Serializer):
    """
    Serializer for public lead creation with nested trip structure.
    Handles the payload format from the frontend form.
    """
    # School/Contact Information
    school_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    teacher_incharge = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=False, max_length=20, allow_blank=True)
    special_instructions = serializers.CharField(required=False, allow_blank=True, default="")
    
    # Student/Teacher counts
    teachers_count = serializers.IntegerField(required=True, min_value=0)
    students_count = serializers.IntegerField(required=True, min_value=0)
    
    # Nested trip data
    outbound_trip = serializers.DictField(required=True)
    return_trip = serializers.DictField(required=False, allow_null=True)
    
    # Additional fields
    privacy_agreed = serializers.BooleanField(required=False, default=False)
    submitted_at = serializers.DateTimeField(required=False)

    def validate_outbound_trip(self, value):
        """Validate outbound trip structure"""
        required_fields = ['pickup_location', 'dropoff_location', 'pickup_date', 'pickup_time']
        for field in required_fields:
            if field not in value:
                raise serializers.ValidationError(f"'{field}' is required in outbound_trip")
        return value

    def create(self, validated_data):
        """Create Lead with nested Trip and TripStop objects"""
        from django.contrib.auth.models import User
        from .models import Lead, Trip, TripStop, Profile
        
        # Extract trip data
        outbound_data = validated_data.pop('outbound_trip')
        return_data = validated_data.pop('return_trip', None)
        
        # Extract contact info
        email = validated_data['email']
        teacher_name = validated_data['teacher_incharge']
        phone_number = validated_data['phone_number']
        school_name = validated_data['school_name']
        
        # Get or create user
        try:
            user = User.objects.get(email=email)
            plain_password = None
        except User.DoesNotExist:
            # Generate random password
            plain_password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=teacher_name.split()[0] if teacher_name else '',
                last_name=' '.join(teacher_name.split()[1:]) if len(teacher_name.split()) > 1 else '',
                password=plain_password
            )
        
        # Create or update profile
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.contact_number = phone_number
        profile.school_name = school_name
        profile.save()
        
        # Create outbound trip
        outbound_trip = self._create_trip(outbound_data, 'OUTBOUND')
        
        # Create return trip if provided
        return_trip = None
        if return_data:
            return_trip = self._create_trip(return_data, 'RETURN')
        
        # Calculate total passengers
        total_passengers = validated_data['teachers_count'] + validated_data['students_count']
        
        # Create lead
        lead = Lead.objects.create(
            user=user,
            name=teacher_name,
            email=email,
            phone_number=phone_number,
            institute_name=school_name,
            number_of_teachers=validated_data['teachers_count'],
            number_of_students=validated_data['students_count'],
            number_of_passengers=total_passengers,
            special_instructions=validated_data.get('special_instructions', ''),
            outbound_trip=outbound_trip,
            return_trip=return_trip,
            is_roundtrip=return_trip is not None,
            # Copy essential fields from outbound trip for backward compatibility
            pickup_location=outbound_data['pickup_location'],
            dropoff_location=outbound_data['dropoff_location'],
            travel_date=outbound_data['pickup_date'],
            pickup_time=outbound_data['pickup_time'],
            distance=outbound_data.get('distance', 0),
            status='PENDING'
        )
        
        # Calculate aggregated distance
        try:
            from .quotation_services import get_aggregated_distance_lead
            lead.distance = get_aggregated_distance_lead(lead)
            lead.save(update_fields=['distance'])
        except Exception as e:
            print(f"Failed to calculate distance: {e}")
        
        # Send email if new user
        if plain_password:
            lead.temp_password = plain_password
            lead.save(update_fields=['temp_password'])
            self._send_welcome_email(lead)
            lead.temp_password = None
            lead.save(update_fields=['temp_password'])
        else:
            self._send_quote_email(lead)
        
        return lead
    
    def _create_trip(self, trip_data, trip_type):
        """Helper method to create a Trip with TripStops"""
        from .models import Trip, TripStop
        
        # Extract stops data
        stops_data = trip_data.pop('trip_stops', [])
        
        # Create trip
        trip = Trip.objects.create(
            type=trip_type,
            pickup_location=trip_data['pickup_location'],
            dropoff_location=trip_data['dropoff_location'],
            pickup_date=trip_data['pickup_date'],
            pickup_time=trip_data['pickup_time'],
            arrival_time=trip_data.get('arrival_time'),
            duration=trip_data.get('duration'),
            distance=trip_data.get('distance', 0)
        )
        
        # Create trip stops
        for stop_data in stops_data:
            TripStop.objects.create(
                trip=trip,
                location=stop_data['location'],
                estimated_time=stop_data.get('estimated_time', 30),
                stop_order=stop_data['stop_order']
            )
        
        return trip
    
    def _send_welcome_email(self, lead):
        """Send welcome email to new user"""
        try:
            from django.core.mail import EmailMessage
            from django.conf import settings
            
            email_template = Emails.objects.get(purpose='quote_request_received')
            
            context = {
                'first_name': lead.name.split()[0] if lead.name else 'User',
                'email': lead.email,
                'password': lead.temp_password,
                'login_url': f"{settings.FRONTEND_URL}/login",
                'lead_id': lead.id,
                'pickup_location': lead.pickup_location,
                'dropoff_location': lead.dropoff_location,
                'travel_date': lead.travel_date,
                'pickup_time': lead.pickup_time,
            }
            
            subject = email_template.subject.format(**context)
            message = email_template.message.format(**context)
            
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                to=[lead.email],
            )
            email.send(fail_silently=False)
        except Exception as e:
            print(f"Failed to send welcome email: {e}")
    
    def _send_quote_email(self, lead):
        """Send quote request email to existing user"""
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            
            subject = f"New Quote Request - Lead #{lead.id}"
            message = f"""Dear {lead.name},

We have received your quote request for:
- From: {lead.pickup_location}
- To: {lead.dropoff_location}
- Date: {lead.travel_date}
- Passengers: {lead.number_of_passengers}

We will review your request and get back to you shortly.

Best regards,
Your Transport Team"""
            
            send_mail(
                subject=subject,
                message=message,
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                recipient_list=[lead.email],
                fail_silently=False
            )
        except Exception as e:
            print(f"Failed to send quote email: {e}")



class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, style={'input_type': 'password'})
    confirm_password = serializers.CharField(
        write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('email', 'password', 'confirm_password',
                  'first_name', 'last_name')
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True}
        }

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {"error": "Passwords don't match"})
        if len(data['password']) < 8:
            raise serializers.ValidationError(
                {"error": "Password must be at least 8 characters long"})
        if not any(char.isdigit() for char in data['password']):
            raise serializers.ValidationError(
                {"error": "Password must contain at least one number"})
        if not any(char.isupper() for char in data['password']):
            raise serializers.ValidationError(
                {"error": "Password must contain at least one uppercase letter"})
        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError(
                {"error": "Email already registered"})

        return data


class OTPSerializer(serializers.ModelSerializer):
    class Meta:
        model = OTP
        fields = ('email', 'otp')



# password reset

class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {"error": "Passwords don't match"})
        if len(data['new_password']) < 8:
            raise serializers.ValidationError(
                {"error": "Password must be at least 8 characters long"})
        if not any(char.isdigit() for char in data['new_password']):
            raise serializers.ValidationError(
                {"error": "Password must contain at least one number"})
        if not any(char.isupper() for char in data['new_password']):
            raise serializers.ValidationError(
                {"error": "Password must contain at least one uppercase letter"})
        return data


# Admin dashboard
class AdminRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'confirm_password',
                  'first_name', 'last_name')

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords don't match")
        if len(data['password']) < 8:
            raise serializers.ValidationError(
                "Password must be at least 8 characters")
        return data


class VehicleTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = ('id', 'name', 'is_active', 'factor')


class AdminNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminNotification
        fields = ('id', 'admin', 'lead', 'message', 'is_read', 'created_at')
        read_only_fields = ('created_at',)


class AdminProfileSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = AdminProfile
        fields = ('id', 'user', 'is_approved',
                  'approved_by', 'approved_at', 'created_at')
        read_only_fields = ('approved_by', 'approved_at', 'created_at')

    def get_user(self, obj):
        return {
            'id': obj.user.id,
            'email': obj.user.email,
            'first_name': obj.user.first_name,
            'last_name': obj.user.last_name
        }
# serializers.py


class EmailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Emails
        fields = ['id', 'purpose', 'subject', 'message']
        read_only_fields = ['purpose']  # make purpose immutable if needed


# QuotationAdminSerializer removed


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = ['status', 'created_at', 'updated_at', 'lead']

    def create(self, validated_data):
        # Allow lead to be passed in validated_data (e.g. from view.perform_create or save(lead=...))
        # if 'lead' is in validated_data, it's already handled by ModelSerializer if it were writable,
        # but since it's read_only, we might need to inject it.
        
        # However, the view `LeadTransactionView` calls `serializer.save(lead=lead)`.
        # So `lead` is in `validated_data` by the time it reaches `create` IF we handle it right, 
        # or it's in `self.validated_data`. 
        
        # Actually ModelSerializer's save(lead=x) adds 'lead' to validated_data passed to create().
        # So checking quotation_id is legacy junk.
        return super().create(validated_data)


# TransactionLeadSerializer removed


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = [
            'id',
            'lead',
            'message_type',
            'message',
            # 'sender',
            # 'sender_name',
            # 'sender_email',
            'is_read',
            'created_at'
        ]
        # read_only_fields = ['sender', 'created_at']




class LeadRejectionSerializer(serializers.ModelSerializer):
    lead_estimated_price = serializers.SerializerMethodField()

    class Meta:
        model = LeadRejection
        fields = ['id', 'lead', 'role', 'reason', 'created_at', 'lead_estimated_price']
        read_only_fields = ['id', 'lead', 'created_at', 'lead_estimated_price']

    def get_lead_estimated_price(self, obj):
        # Safely handle if lead is missing
        if obj.lead and obj.lead.estimated_price is not None:
            return obj.lead.estimated_price
        return None