try:
    from typing import override
except ImportError:
    # Python < 3.12 compatibility
    def override(func):
        return func
from rest_framework.permissions import AllowAny
from django.db.models import Q
from rest_framework import status
#from .quotation_services import update_quotation_values
from rest_framework.pagination import PageNumberPagination
from .pagination import StandardResultsPagination
import math
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from datetime import timedelta
from django.shortcuts import redirect
from django.http import HttpResponse
from urllib.parse import urlencode

from .utils import (
    generate_otp,
    create_notification,
    send_notification_email,
    get_stops_and_roundtrip_details, send_chat_notification
)

def round_to_nearest_5(n):
    return 5 * round(n / 5)
from .serializers import *
from .models import (
    Emails, Lead, OTP, AdminProfile, VehicleType,
    AdminNotification, Transaction, Notification,
    ChatMessage
)
from django.contrib.auth import get_user_model

# from .serializers import TransactionLeadSerializer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework import viewsets, status, permissions, serializers
from django.conf import settings
from .xero_services import XeroManager
from .models import XeroToken
import requests
from django.shortcuts import redirect
from django.core.mail import send_mail
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, TrackingSettings, ClickTracking
import stripe
from django.utils import timezone
from django.shortcuts import get_object_or_404                                                                                   
from .quotation_services import get_aggregated_distance_lead
# from .fare_calculation.training import retrain_model_on_admin_prices
from .fare_calculation.prediction import predict_fare
import logging
import threading
from decimal import Decimal
import os
from rest_framework import viewsets, permissions
from .models import Emails
from .serializers import EmailsSerializer
from dotenv import load_dotenv
from django.db import transaction
from rest_framework.exceptions import ValidationError
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

load_dotenv()

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY


# ------------------------------------------------------------------------------
# Public Endpoints
# ------------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def list_vehicle_types(request):
    """
    GET /api/vehicles/
    Returns a list of active vehicle types for regular users.
    """
    vehicles = VehicleType.objects.filter(is_active=True)
    serializer = VehicleTypeSerializer(vehicles, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def register_user(request):
    serializer = UserRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        try:
            email = serializer.validated_data['email']
            otp = generate_otp()
            otp_obj = OTP.objects.create(
                email=email,
                otp=otp,
                purpose='SIGNUP',
                registration_data=serializer.validated_data
            )
            subject = 'Verify Your Email for Registration'
            message = f"""
Hello!

Your verification code is: {otp}

This code will expire in 10 minutes.

If you didn't request this code, please ignore this email.

Best regards,
Your Transport Team
"""
            if send_notification_email(email, subject, message):
                return Response({'message': 'OTP sent successfully', 'email': email})
            else:
                otp_obj.delete()
                return Response({'error': 'Failed to send OTP email'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def verify_registration_otp(request):
    serializer = OTPSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        try:
            otp_obj = OTP.objects.get(
                email=email, otp=otp, purpose='SIGNUP', is_verified=False)
            if not otp_obj.is_valid():
                return Response({'error': 'OTP has expired'}, status=status.HTTP_400_BAD_REQUEST)
            reg_data = otp_obj.registration_data
            user = User.objects.create_user(
                username=email,
                email=email,
                password=reg_data['password'],
                first_name=reg_data['first_name'],
                last_name=reg_data['last_name']
            )
            otp_obj.is_verified = True
            otp_obj.user = user
            otp_obj.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'message': 'Registration successful',
                'user': UserSerializer(user).data,
                'access': str(refresh.access_token)
            })
        except OTP.DoesNotExist:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)





@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def login_user(request):
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        return Response({'error': 'Please provide both email and password'}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(request, username=email, password=password)

    # 🔄 Fallback for PLAINTEXT PASSWORDS
    if not user:
        try:
            u = User.objects.get(email=email)

            if not u.password.startswith("pbkdf2_"):
                if u.password == password:
                    u.set_password(password)
                    u.save()
                    user = authenticate(request, username=email, password=password)
            # else: hashed password → normal authentication
        except User.DoesNotExist:
            user = None

    if not user:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)

    # Determine role
    role = "admin" if user.is_superuser and user.is_staff else "user"

    # 🔍 Get profile (create one automatically if missing)
    profile, created = Profile.objects.get_or_create(user=user)

    # Build profile JSON
    profile_data = {
        "contact_number": profile.contact_number,
        "school_name": profile.school_name,
        "verified_by_admin": profile.verified_by_admin,
        "date_of_birth": profile.date_of_birth,
    }

    # Build user JSON
    user_info = {
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'username': user.username,
        'role': role,
        'profile': profile_data,  
    }

    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': user_info,
        'message': 'Login successful'
    }, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def verify_login_otp(request):
    serializer = OTPSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        try:
            otp_obj = OTP.objects.get(
                email=email, otp=otp, purpose='LOGIN', is_verified=False)
            if not otp_obj.is_valid():
                return Response({'error': 'OTP has expired'}, status=status.HTTP_400_BAD_REQUEST)
            user = otp_obj.user
            otp_obj.is_verified = True
            otp_obj.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'message': 'Login successful',
                'user': UserSerializer(user).data,
                'access': str(refresh.access_token)
            })
        except OTP.DoesNotExist:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def forgot_password(request):
    serializer = PasswordResetSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        try:
            user = User.objects.get(email=email)
            otp = generate_otp()
            OTP.objects.filter(email=email, purpose='RESET').delete()
            OTP.objects.create(user=user, email=email,
                               otp=otp, purpose='RESET')
            subject = 'Password Reset Code'
            message = f"""
Hello!

Your password reset code is: {otp}

This code will expire in 10 minutes.

If you didn't request this code, please ignore this email.

Best regards,
Your Transport Team
"""
            if send_notification_email(email, subject, message):
                return Response({'message': 'Password reset OTP sent', 'email': email})
            else:
                return Response({'error': 'Failed to send OTP'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except User.DoesNotExist:
            return Response({'error': 'No account found with this email'}, status=status.HTTP_404_NOT_FOUND)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def reset_password_confirm(request):
    serializer = PasswordResetConfirmSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        new_password = serializer.validated_data['new_password']
        try:
            otp_obj = OTP.objects.get(
                email=email, otp=otp, purpose='RESET', is_verified=False)
            if not otp_obj.is_valid():
                return Response({'error': 'OTP has expired'}, status=status.HTTP_400_BAD_REQUEST)
            user = otp_obj.user
            user.set_password(new_password)
            user.save()
            otp_obj.is_verified = True
            otp_obj.save()
            refresh = RefreshToken.for_user(user)
            return Response({'message': 'Password reset successful', 'access': str(refresh.access_token)})
        except OTP.DoesNotExist:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def google_auth(request):
    try:
        token = request.data.get('token')
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        email = idinfo['email']
        if not email:
            return Response({'error': 'Email not found in token'}, status=status.HTTP_400_BAD_REQUEST)
        first_name = idinfo.get('given_name', '')
        last_name = idinfo.get('family_name', '')
        try:
            user = User.objects.get(email=email)
            if first_name and not user.first_name:
                user.first_name = first_name
            if last_name and not user.last_name:
                user.last_name = last_name
            user.save()
        except User.DoesNotExist:
            user = User.objects.create_user(
                username=email, email=email, first_name=first_name, last_name=last_name)
            user.set_unusable_password()
            user.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'message': 'Authentication successful',
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data
        })
    except ValueError as e:
        logger.error(f"Token verification error: {str(e)}")
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Google auth error: {str(e)}")
        return Response({'error': 'Authentication failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ------------------------------------------------------------------------------
# User Notification Endpoint
# ------------------------------------------------------------------------------



@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def public_create_lead(request):
    """
    Public endpoint for creating leads with nested trip structure.
    Accepts payload with outbound_trip (and optional return_trip) containing trip_stops.
    """
    serializer = PublicLeadCreationSerializer(data=request.data)
    
    if serializer.is_valid():
        try:
            lead = serializer.save()
            
            # Return created lead data
            return Response({
                'success': True,
                'message': 'Lead created successfully',
                'lead_id': lead.id,
                'data': {
                    'id': lead.id,
                    'name': lead.name,
                    'email': lead.email,
                    'school_name': lead.institute_name,
                    'status': lead.status,
                    'pickup_location': lead.pickup_location,
                    'dropoff_location': lead.dropoff_location,
                    'travel_date': str(lead.travel_date),
                    'number_of_passengers': lead.number_of_passengers,
                    'distance': float(lead.distance) if lead.distance else 0,
                    'created_at': lead.created_at.isoformat(),
                }
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating lead: {str(e)}")
            return Response({
                'success': False,
                'error': 'Failed to create lead',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response({
        'success': False,
        'error': 'Validation failed',
        'details': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


class UserNotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    @override
    def get_queryset(self):
        # Returns notifications for the logged-in user (either direct user notifications or quotation-based)
        from django.db.models import Q

        # Ensure user is authenticated before querying
        if not self.request.user or not self.request.user.is_authenticated:
            return Notification.objects.none()

        return Notification.objects.filter(
            user=self.request.user
        ).order_by('-sent_at')

    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({'status': 'marked as read'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def mark_all_as_read(self, request):
        from django.db.models import Q

        # Update both user-direct and quotation-based notifications
        notifications = Notification.objects.filter(
            user=request.user,
            is_read=False
        )
        count = notifications.update(is_read=True)
        return Response({
            'status': 'all notifications marked as read',
            'count': count
        }, status=status.HTTP_200_OK)




class LeadViewSet(viewsets.ModelViewSet):
    """
    Allow anyone to create a Lead (unauthenticated users),
    but only staff can list or retrieve them.
    """
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsPagination
    queryset = Lead.objects.all()

    @action(detail=False, methods=['get'], url_path='unique-schools')
    def unique_schools(self, request):
        """
        Returns a list of unique schools (institute_name) from the user's leads.
        """
        try:
            schools = Lead.objects.filter(user=request.user).values_list('institute_name', flat=True).distinct()
            # Filter out None or empty strings
            schools = [school for school in schools if school]
            return Response(list(schools))
        except Exception as e:
            logger.error(f"Error in unique_schools: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @override
    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Lead.objects.none()
            
        queryset = Lead.objects.filter(user=self.request.user)

        status_filter = self.request.query_params.get('status', None)
        school_name = self.request.query_params.get('school_name', None)

        # 1. Filter by status
        if status_filter:
            if status_filter == 'PENDING':
                queryset = queryset.filter(status__in=['PENDING', 'EDITED'])
            elif status_filter == 'BOOKED':
                # Filter for PAY_LATER leads (all) OR ACCEPTED leads with PENDING transactions
                queryset = queryset.filter(
                    Q(status='PAY_LATER') | 
                    Q(status='ACCEPTED', transaction__status='PENDING')
                ).distinct()
            elif status_filter == 'ACCEPTED':
                 # Exclude leads with PENDING transactions (since they are now "BOOKED")
                 queryset = queryset.filter(status='ACCEPTED').exclude(transaction__status='PENDING')
            else:
                queryset = queryset.filter(status=status_filter)

        # 2. Filter by school name
        if school_name:
            queryset = queryset.filter(institute_name=school_name)

        # 3. Sorting
        # 3. Sorting
        sort_by = self.request.query_params.get('sort', 'updated_at')
        order = self.request.query_params.get('order', 'descending').lower()
        order = self.request.query_params.get('order', 'descending').lower()

        # Map 'departure_date' -> 'travel_date'
        if sort_by == 'departure_date':
            sort_field = 'travel_date'
        elif sort_by == 'created_at':
            sort_field = 'created_at'
        else:
            sort_field = 'updated_at'

        # Handle ascending vs descending (support various spellings)
        if order in ['assending', 'ascending', 'asc']:
            ordering = sort_field
        else:
            ordering = f'-{sort_field}'

        return queryset.order_by(ordering)

    @override

    def perform_create(self, serializer):
        with transaction.atomic():
            lead = serializer.save(distance=0, estimated_price=0)
            lead.refresh_from_db()

            # Calculate stops count from Trips
            stops_count = 0
            roundtrip_stops_count = 0
            total_stop_duration = 0

            if lead.outbound_trip:
                stops_count = lead.outbound_trip.stops.count()
                total_stop_duration += sum(s.estimated_time for s in lead.outbound_trip.stops.all())
            
            if lead.return_trip:
                roundtrip_stops_count = lead.return_trip.stops.count()
                total_stop_duration += sum(s.estimated_time for s in lead.return_trip.stops.all())
                
            lead.stops_count = stops_count
            lead.roundtrip_stops_count = roundtrip_stops_count

            try:
                distance_km = get_aggregated_distance_lead(lead)
            except ValueError as e:
                raise serializers.ValidationError({"error": str(e)})
            lead.distance = distance_km

            total_stops = stops_count + roundtrip_stops_count

            vt = (lead.vehicle_type or "").lower()
            vehicle_obj = VehicleType.objects.filter(name__iexact=vt).first()
            if not vehicle_obj or not vehicle_obj.is_model_trained:
                fallback = VehicleType.objects.filter(is_model_trained=True).first()
                if fallback:
                    vt = fallback.name.lower()

            row_data = {
                "total_distance": float(distance_km),
                "stops_count": total_stops,
                "total_stop_duration": total_stop_duration,
                "number_of_passengers": lead.number_of_passengers,
                "vehicle_type": vt
            }
            model_fare = predict_fare(row_data)
            lead.estimated_price = round_to_nearest_5(model_fare)
            lead.calculated_price = lead.estimated_price

            lead.save(update_fields=[
                'distance',
                'estimated_price',
                'calculated_price',
                'stops_count',
                'roundtrip_stops_count'
            ])
            for admin in AdminProfile.objects.filter(is_approved=True):
                AdminNotification.objects.create(
                    admin=admin.user,
                    lead=lead,
                    message=f"New lead from {lead.name} ({lead.email})"
                )


    def ensure_email_templates(self):
        """Ensure required email templates exist"""
        update_lead_template, created = Emails.objects.get_or_create(
            purpose="update_lead",
            defaults={
                'subject': 'Lead #{lead_id} Update - {lead_name}',
                'message': '''Dear Admin,

Lead #{quotation_id} from {institute_name} ({institute_email}) has been updated.

Status: {status}

Changes made:
{changes}

Current Details:
• Pickup: {pickup}
• Dropoff: {dropoff}
• Date: {date}
• Time: {time}
• Vehicle: {vehicle}
• Passengers: {passengers}
• Round Trip: {roundtrip}

Please review the updated lead in the admin panel.

Best regards,
Transportation System'''
            }
        )

        # ----------------------------------------------------------------------
        # ADDED TEMPLATES
        # ----------------------------------------------------------------------
        Emails.objects.get_or_create(
            purpose="payment_lead_completed",
            defaults={
                'subject': 'Payment Confirmation - Trip #{lead.id}',
                'message': '''Dear {lead.name},

We are pleased to confirm that your payment for Trip #{lead.id} has been successfully received.

Details:
- Amount Paid: €{amount_paid}
- Date: {payment_date}
- From: {lead.pickup_location}
- To: {lead.dropoff_location}

Thank you for choosing Dave Long Coach Travel. We look forward to seeing you soon!

Best regards,
School Transport Team'''
            }
        )

        Emails.objects.get_or_create(
            purpose="admin_payment_notification",
            defaults={
                'subject': 'Payment Received - Lead #{lead.id}',
                'message': '''Dear Admin,

A payment has been received for Lead #{lead.id}.

Details:
- Customer: {lead.name} ({lead.email})
- Amount Paid: €{amount_paid}
- Payment Date: {payment_date}

Please check the admin panel for more details.

Best regards,
DLCT Transport System'''
            }
        )

        if created:
            logger.info("Created missing 'update_lead' email template")
 

    @override
    def perform_update(self, serializer):

        self.ensure_email_templates()

        try:
            original_lead = self.get_object()
            lead = serializer.save()
            lead.refresh_from_db()
            
            # Automatically change status to 'EDITED' when lead is updated
            # Don't change if already in final states
            if lead.status not in ['COMPLETED', 'CANCELLED', 'REJECTED', 'PAY_LATER']:
                lead.status = 'EDITED'
                lead.is_edited = True
                lead.save(update_fields=['status', 'is_edited'])
                logger.info(f"Lead #{lead.id} status automatically changed to EDITED")
            
            important_fields_changed = False

            # Check if location-related fields changed
            location_changed = (
                original_lead.pickup_location != lead.pickup_location or
                original_lead.dropoff_location != lead.dropoff_location or
                original_lead.pickup_stop != lead.pickup_stop or
                original_lead.return_pickup_stop != lead.return_pickup_stop or
                original_lead.final_destination != lead.final_destination or
                original_lead.final_pickup != getattr(lead, 'final_pickup', None) or
                original_lead.duration != lead.duration

            )

            if (
                location_changed or
                original_lead.travel_date != lead.travel_date or
                original_lead.pickup_time != lead.pickup_time or
                original_lead.vehicle_type != lead.vehicle_type or
                original_lead.number_of_passengers != lead.number_of_passengers or
                original_lead.is_roundtrip != lead.is_roundtrip
            ):
                important_fields_changed = True

            original_stops = list(original_lead.stops_lead.values_list('location', 'estimated_time', 'order'))
            current_stops = list(lead.stops_lead.values_list('location', 'estimated_time', 'order'))

            if original_stops != current_stops:
                important_fields_changed = True
                location_changed = True

            original_roundtrip_stops = list(original_lead.roundtrip_stops_lead.values_list('location', 'estimated_time', 'order'))
            current_roundtrip_stops = list(lead.roundtrip_stops_lead.values_list('location', 'estimated_time', 'order'))
            if original_roundtrip_stops != current_roundtrip_stops:
                important_fields_changed = True
                location_changed = True
            # Update distance and estimated price if location-related fields changed
            if location_changed:
                try:
                    # Recalculate distance using the same logic as create
                    distance_km = get_aggregated_distance_lead(lead)
                    lead.distance = distance_km

                    # Update stops counts
                    lead.stops_count = lead.stops_lead.count()
                    lead.roundtrip_stops_count = lead.roundtrip_stops_lead.count()

                    # Recalculate estimated price using exact same logic as create
                    total_stops = lead.stops_lead.count() + lead.roundtrip_stops_lead.count()
                    total_stop_duration = (
                        sum(s.estimated_time for s in lead.stops_lead.all()) +
                        sum(rs.estimated_time for rs in lead.roundtrip_stops_lead.all())
                    )

                    vt = (lead.vehicle_type or "").lower()
                    vehicle_obj = VehicleType.objects.filter(name__iexact=vt).first()
                    if not vehicle_obj or not vehicle_obj.is_model_trained:
                        fallback = VehicleType.objects.filter(
                            is_model_trained=True).first()
                        if fallback:
                            vt = fallback.name.lower()

                    row_data = {
                        "total_distance": float(distance_km),
                        "stops_count": total_stops,
                        "total_stop_duration": total_stop_duration,
                        "number_of_passengers": lead.number_of_passengers,
                        "vehicle_type": vt
                    }
                    model_fare = predict_fare(row_data)
                    lead.estimated_price = round_to_nearest_5(model_fare)

                    lead.save(update_fields=['distance', 'estimated_price', 'stops_count', 'roundtrip_stops_count'])

                except ValueError as e:
                    logger.error(f"Error updating distance for lead {lead.id}: {str(e)}")
                    # Continue with the update process even if distance calculation fails

            if important_fields_changed and lead.status in ['ACCEPTED', 'REJECTED']:
                lead.status = 'PENDING'
                lead.save(update_fields=['status'])

            # ------------------------------------------------------------------
            # XERO INTEGRATION: Create Invoice on COMPLETED
            # ------------------------------------------------------------------
            if original_lead.status != 'COMPLETED' and lead.status == 'COMPLETED':
                logger.info(f"Lead #{lead.id} status changed to COMPLETED. Triggering Xero invoice.")
                try:
                    admin_user = AdminProfile.objects.filter(is_approved=True).first()
                    if admin_user:
                        xero_manager = XeroManager(admin_user.user)
                        if xero_manager.get_token():
                            amount = lead.calculated_price if lead.calculated_price else lead.estimated_price
                            invoice, error = xero_manager.create_invoice_for_lead(lead, amount)
                            
                            if invoice:
                                logger.info(f"Invoice created: {invoice.invoice_number} for Lead #{lead.id}")
                                # ------------------------------------------
                                # AUTO-PAYMENT
                                # ------------------------------------------
                                payment, pay_error = xero_manager.create_payment(invoice.invoice_id, invoice.amount_due)
                                if payment:
                                    logger.info(f"Auto-payment created: {payment.payment_id} for Invoice {invoice.invoice_number}")
                                else:
                                    logger.error(f"Auto-payment failed for Lead #{lead.id}: {pay_error}")
                                
                                xero_manager.email_invoice_pdf(invoice.invoice_id, lead)
                            else:
                                logger.error(f"Xero Invoice Creation Failed (COMPLETED): {error}")
                        else:
                            logger.error("Xero Integration Error: No connected admin found for COMPLETED invoice.")
                except Exception as e:
                    logger.error(f"Xero Integration Error (COMPLETED): {e}")
            # ------------------------------------------------------------------

            try:
                all_changes = []

                if original_lead.pickup_location != lead.pickup_location:
                    all_changes.append(f"Pickup location changed from '{original_lead.pickup_location}' to '{lead.pickup_location}'")
                if original_lead.dropoff_location != lead.dropoff_location:
                    all_changes.append(f"Dropoff location changed from '{original_lead.dropoff_location}' to '{lead.dropoff_location}'")
                if original_lead.pickup_stop != lead.pickup_stop:
                    all_changes.append(f"Pickup stop changed from '{original_lead.pickup_stop or 'None'}' to '{lead.pickup_stop or 'None'}'")
                if original_lead.return_pickup_stop != lead.return_pickup_stop:
                    all_changes.append(f"Return pickup stop changed from '{original_lead.return_pickup_stop or 'None'}' to '{lead.return_pickup_stop or 'None'}'")
                if original_lead.final_destination != lead.final_destination:
                    all_changes.append(f"Final destination changed from '{original_lead.final_destination or 'None'}' to '{lead.final_destination or 'None'}'")
                if getattr(original_lead, 'final_pickup', None) != getattr(lead, 'final_pickup', None):
                    all_changes.append(f"Final pickup changed from '{getattr(original_lead, 'final_pickup', None) or 'None'}' to '{getattr(lead, 'final_pickup', None) or 'None'}'")
                if original_lead.duration != lead.duration:
                    all_changes.append(f"Duration updated from {original_lead.duration or 'None'} to {lead.duration or 'None'}")
                if original_lead.distance != lead.distance:
                    all_changes.append(f"Distance updated from {original_lead.distance} km to {lead.distance} km")
                if original_lead.estimated_price != lead.estimated_price:
                    all_changes.append(f"Estimated price updated from €{original_lead.estimated_price} to €{lead.estimated_price}")
                if original_lead.travel_date != lead.travel_date:
                    all_changes.append(f"Travel date changed from '{original_lead.travel_date}' to '{lead.travel_date}'")
                if original_lead.pickup_time != lead.pickup_time:
                    all_changes.append(f"Pickup time changed from '{original_lead.pickup_time}' to '{lead.pickup_time}'")
                if original_lead.vehicle_type != lead.vehicle_type:
                    all_changes.append(f"Vehicle type changed from '{original_lead.vehicle_type}' to '{lead.vehicle_type}'")
                if original_lead.number_of_passengers != lead.number_of_passengers:
                    all_changes.append(f"Number of passengers changed from '{original_lead.number_of_passengers}' to '{lead.number_of_passengers}'")
                if original_lead.is_roundtrip != lead.is_roundtrip:
                    roundtrip_text = "Yes" if lead.is_roundtrip else "No"
                    original_roundtrip_text = "Yes" if original_lead.is_roundtrip else "No"
                    all_changes.append(f"Roundtrip changed from '{original_roundtrip_text}' to '{roundtrip_text}'")

                if original_lead.name != lead.name:
                    all_changes.append(f"Name changed from '{original_lead.name}' to '{lead.name}'")
                if original_lead.phone_number != lead.phone_number:
                    all_changes.append(f"Phone number changed from '{original_lead.phone_number}' to '{lead.phone_number}'")
                if original_lead.institute_name != lead.institute_name:
                    all_changes.append(f"Institute name changed from '{original_lead.institute_name}' to '{lead.institute_name}'")
                if original_lead.number_of_students != lead.number_of_students:
                    all_changes.append(f"Number of students changed from '{original_lead.number_of_students}' to '{lead.number_of_students}'")
                if original_lead.number_of_teachers != lead.number_of_teachers:
                    all_changes.append(f"Number of teachers changed from '{original_lead.number_of_teachers}' to '{lead.number_of_teachers}'")
                if original_lead.status != lead.status:
                    all_changes.append(f"Status changed from '{original_lead.status}' to '{lead.status}'")
                if original_lead.special_instructions != lead.special_instructions:
                    all_changes.append(f"Special instructions updated")

                if original_stops != current_stops:
                    all_changes.append("Stops have been modified")

                if original_roundtrip_stops != current_roundtrip_stops:
                    all_changes.append("Roundtrip stops have been modified")
                if True:
                    changes_text = "\n".join(f"• {change}" for change in all_changes) if all_changes else "• DEBUG: No changes detected but forcing notification"

                    try:
                        email = Emails.objects.get(purpose="update_lead")
                    except Emails.DoesNotExist:
                        logger.error("Admin email template 'update_lead' does not exist!")
                        raise
                    lead_name = lead.name or lead.email
                    
                    # Safe user access
                    user_name = "N/A"
                    user_email = "N/A"
                    if lead.user:
                        user_name = lead.user.get_full_name() or lead.user.email
                        user_email = lead.user.email

                    formatted_subject = email.subject.format(
                        lead=lead,
                        lead_id=lead.id,
                        lead_name=lead_name,
                        name=lead_name
                    )
                    formatted_message = email.message.format(
                        lead=lead,
                        quotation_id=lead.id,
                        institute_name=user_name,
                        institute_email=user_email,
                        status=lead.status,
                        changes=changes_text,
                        pickup=lead.pickup_location,
                        dropoff=lead.dropoff_location,
                        date=lead.travel_date,
                        time=lead.pickup_time,
                        vehicle=lead.vehicle_type,
                        passengers=lead.number_of_passengers,
                        roundtrip='Yes' if lead.is_roundtrip else 'No'
                    )

                    approved_admins = AdminProfile.objects.filter(is_approved=True)
                    admin_emails = [admin.user.email for admin in approved_admins if admin.user.email]

                    if admin_emails:
                        try:
                            send_mail(
                                subject=formatted_subject,
                                message=formatted_message,
                                from_email=f"{settings.EMAIL_SENDER_NAME_ADMIN} <{settings.DEFAULT_FROM_EMAIL}>",
                                recipient_list=admin_emails,
                                fail_silently=False
                            )
                        except Exception as email_error:
                            logger.error(f"Failed to send admin email: {str(email_error)}")
                            raise
                    else:
                        logger.warning("No admin emails found to send notifications")
                    try:
                        user_email_template, created = Emails.objects.get_or_create(
                            purpose="user_lead_update",
                            defaults={
                                'subject': 'Your Transportation Request #{lead_id} Has Been Updated',
                                'message': '''Hello {name},

Your transportation request #{lead_id} has been updated with the following changes:

{changes}

Updated Request Details:
• Pickup Location: {pickup}
• Dropoff Location: {dropoff}
• Travel Date: {date}
• Pickup Time: {time}
• Vehicle Type: {vehicle}
• Number of Passengers: {passengers}
• Round Trip: {roundtrip}
• Status: {status}

If you have any questions about these changes, please contact us.

Best regards,
Transportation Team'''
                            }
                        )

                        if created:
                            logger.info("Created new user email template for lead updates")

                        user_formatted_subject = user_email_template.subject.format(
                            lead_id=lead.id,
                            lead_name=lead.name or lead.email
                        )
                        user_formatted_message = user_email_template.message.format(
                            lead_id=lead.id,
                            name=lead.name,
                            status=lead.status,
                            changes=changes_text,
                            pickup=lead.pickup_location,
                            final_pickup=lead.final_pickup,
                            dropoff=lead.dropoff_location,
                            date=lead.travel_date,
                            time=lead.pickup_time,
                            vehicle=lead.vehicle_type,
                            passengers=lead.number_of_passengers,
                            roundtrip='Yes' if lead.is_roundtrip else 'No'
                        )
                        if lead.email:
                            send_mail(
                                subject=user_formatted_subject,
                                message=user_formatted_message,
                                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                                recipient_list=[lead.email],
                                fail_silently=False
                            )
                            logger.info(f"User notification email sent to {lead.email} for lead #{lead.id}")

                        if lead.user and lead.user.email and lead.user.email != lead.email:
                            send_mail(
                                subject=user_formatted_subject,
                                message=user_formatted_message,
                                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                                recipient_list=[lead.user.email],
                                fail_silently=False
                            )
                            logger.info(f"User notification email sent to associated user {lead.user.email} for lead #{lead.id}")

                    except Exception as e:
                        logger.error(f"Failed to send user notification email: {str(e)}")
                        try:
                            if lead.email:
                                send_mail(
                                    subject=formatted_subject,
                                    message=formatted_message,
                                    from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                                    recipient_list=[lead.email],
                                    fail_silently=False
                                )
                                logger.info(f"User notification email sent (using admin template fallback) to {lead.email} for lead #{lead.id}")
                        except Exception as fallback_error:
                            logger.error(f"Failed to send fallback user notification email: {str(fallback_error)}")
                else:
                    logger.info("DEBUG MODE: This block should not be reached when forcing notifications")

            except Exception as e:
                logger.error(f"Failed to send admin notification email: {str(e)}")
                import traceback
                logger.error(f"Email sending traceback: {traceback.format_exc()}")
            approved_admins_for_notifications = AdminProfile.objects.filter(is_approved=True)

            for admin_profile in approved_admins_for_notifications:
                try:
                    AdminNotification.objects.create(
                        admin=admin_profile.user,
                        lead=lead,
                        message=f'Lead #{lead.id} has been updated by {lead.name or lead.email}'
                    )
                    logger.info(f"Created admin notification for {admin_profile.user.email}")
                except Exception as notification_error:
                    logger.error(f"Failed to create admin notification for {admin_profile.user.email}: {str(notification_error)}")

            if lead.user:
                try:
                    notification = Notification.objects.create(
                        user=lead.user,
                        quotation=None,
                        notification_type='ADMIN_UPDATE',
                        title=f'Your trip #{lead.id} has been updated',
                        message=f'Your transportation request (trip #{lead.id}) has been updated. Please check your user dashboard for the latest details.',
                        email_sent=True if lead.email else False
                    )
                except Exception as e:
                    logger.error(f"Failed to create user notification: {str(e)}")
            else:
                logger.info("No associated user found for lead, skipping user notification creation")

        except Exception as e:
            logger.error(f"perform_update error: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise Exception(str(e))


class LeadListView(APIView):
    """
    View to list all leads, or filtered leads based on query parameters.
    """
    def get(self, request, *args, **kwargs):
        user = request.user
        filter_params = {}
        if 'email' in request.query_params:
            filter_params['email'] = request.query_params['email']
        if 'pickup_location' in request.query_params:
            filter_params['pickup_location__icontains'] = request.query_params['pickup_location']
        if 'dropoff_location' in request.query_params:
            filter_params['dropoff_location__icontains'] = request.query_params['dropoff_location']

        if request.user.is_staff:
            leads = Lead.objects.filter(
                **filter_params).order_by('-created_at')
        else:
            leads = Lead.objects.filter(
                user=request.user, **filter_params).order_by('-created_at')

        serializer = LeadSerializer(leads, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SimilarLocationsLeadsView(APIView):
    """
    GET API for admin users to find similar leads based on pickup_location, dropoff_location,
    number_of_passengers, AND distance.
    Only accessible by admin users.
    All must match exactly (case-insensitive for locations).
    """
    permission_classes = [IsAdminUser]

    def get(self, request, lead_id, *args, **kwargs):
        try:
            try:
                reference_lead = Lead.objects.get(id=lead_id)
            except Lead.DoesNotExist:
                return Response({
                    "success": False,
                    "error": f"Lead with id {lead_id} does not exist"
                }, status=status.HTTP_404_NOT_FOUND)

            pickup_location = reference_lead.pickup_location
            dropoff_location = reference_lead.dropoff_location
            number_of_passengers = reference_lead.number_of_passengers
            distance = reference_lead.distance

            if not pickup_location:
                return Response({
                    "success": False,
                    "error": "Reference trip has no pickup location"
                }, status=status.HTTP_400_BAD_REQUEST)

            if not dropoff_location:
                return Response({
                    "success": False,
                    "error": "Reference trip has no dropoff location"
                }, status=status.HTTP_400_BAD_REQUEST)

            if distance is None:
                return Response({
                    "success": False,
                    "error": "Reference trip has no distance value"
                }, status=status.HTTP_400_BAD_REQUEST)

            from django.db.models import Q, Case, When, IntegerField

            # Fuzzy matching ranges
            # Distance within 10%
            range_margin = 0.1
            min_dist = float(distance) * (1 - range_margin)
            max_dist = float(distance) * (1 + range_margin)

            # Passengers +/- 5
            pax_margin = 5
            min_pax = max(0, number_of_passengers - pax_margin)
            max_pax = number_of_passengers + pax_margin

            # Create Q objects for each matching criteria
            q_pickup = Q(pickup_location__iexact=pickup_location)
            q_dropoff = Q(dropoff_location__iexact=dropoff_location)
            # Use ranges for fuzzy matching
            q_passengers = Q(number_of_passengers__range=(min_pax, max_pax))
            q_distance = Q(distance__range=(min_dist, max_dist))
            potential_leads = Lead.objects.filter(
                (q_passengers & q_distance) | q_dropoff
            ).exclude(id=lead_id).annotate(
                match_score=Case(
                    When(q_pickup & q_dropoff, then=5),      # Perfect location match + (dist/pax OR dropoff match)
                    When(q_pickup | q_dropoff, then=3),      # One location match
                    default=1,                               # Just matched on dist/pax (no location match)
                    output_field=IntegerField()
                )
            ).distinct().order_by('-match_score', '-created_at')

            serializer = LeadSerializer(potential_leads, many=True)

            # Add match score to each lead in response
            leads_with_scores = []
            for i, lead_data in enumerate(serializer.data):
                lead_with_score = lead_data.copy()
                lead_with_score['match_score'] = potential_leads[i].match_score

                # Add which criteria matched
                matched_criteria = []
                lead_obj = potential_leads[i]
                
                # Check fuzzy matches manually for the response flag
                if lead_obj.pickup_location and lead_obj.pickup_location.lower() == pickup_location.lower():
                    matched_criteria.append('pickup_location')
                if lead_obj.dropoff_location and lead_obj.dropoff_location.lower() == dropoff_location.lower():
                    matched_criteria.append('dropoff_location')
                
                # Fuzzy checks for flag
                if min_pax <= lead_obj.number_of_passengers <= max_pax:
                    matched_criteria.append('number_of_passengers')
                
                # Handle Decimal vs Float comparison safely
                obj_dist = float(lead_obj.distance)
                if min_dist <= obj_dist <= max_dist:
                    matched_criteria.append('distance')

                lead_with_score['matched_criteria'] = matched_criteria
                leads_with_scores.append(lead_with_score)

            return Response({
                'success': True,
                'reference_lead_id': lead_id,
                'reference_lead_pickup': pickup_location,
                'reference_lead_dropoff': dropoff_location,
                'reference_lead_passengers': number_of_passengers,
                'reference_lead_distance': str(distance),
                'matched_leads_count': potential_leads.count(),
                'matches': leads_with_scores
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_leads(request):
    """
    Get all leads for the currently authenticated user with optional filters
    """
    try:
        leads = Lead.objects.filter(user=request.user)

        # 1. Status Filter
        status_filter = request.GET.get('status')
        if status_filter: 
            if status_filter == 'BOOKED':
                from django.db.models import Q
                leads = leads.filter(
                    Q(status='PAY_LATER') | 
                    Q(status='ACCEPTED', transaction__status='PENDING')
                ).distinct()
            elif status_filter == 'PENDING':
                # Similar to LeadViewSet which includes EDITED
                leads = leads.filter(status__in=['PENDING', 'EDITED'])
            elif status_filter == 'ACCEPTED':
                 leads = leads.filter(status='ACCEPTED').exclude(transaction__status='PENDING')
            else:
                leads = leads.filter(status=status_filter)


        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        if start_date:
            leads = leads.filter(created_at__gte=start_date)
        if end_date:
            leads = leads.filter(created_at__lte=end_date)

        leads = leads.order_by('-updated_at')

        # Pagination
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
        page_number = request.GET.get('page', 1)
        page_size = request.GET.get('page_size', 10)  # Default 10 per page

        paginator = Paginator(leads, page_size)

        try:
            leads_page = paginator.page(page_number)
        except PageNotAnInteger:
            leads_page = paginator.page(1)
        except EmptyPage:
            leads_page = paginator.page(paginator.num_pages)

        serializer = LeadSerializer(
            leads_page, many=True, context={'request': request})

        return Response({
            'success': True,
            'count': paginator.count,
            'total_pages': paginator.num_pages,
            'current_page': int(page_number) if int(page_number) <= paginator.num_pages else paginator.num_pages,
            'filters': {
                'status': status_filter,
                'start_date': start_date,
                'end_date': end_date
            },
            'leads': serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ------------------------------------------------------------------------------
# Admin Endpoints and Viewsets
# ------------------------------------------------------------------------------

class IsApprovedAdmin(permissions.BasePermission):
    @override
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and
            hasattr(request.user,
                    'adminprofile') and request.user.adminprofile.is_approved
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def register_admin(request):
    serializer = AdminRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        try:
            user = User.objects.create_user(
                username=serializer.validated_data['email'],
                email=serializer.validated_data['email'],
                password=serializer.validated_data['password'],
                first_name=serializer.validated_data['first_name'],
                last_name=serializer.validated_data['last_name'],
                is_staff=True
            )
            AdminProfile.objects.create(user=user)
            # for superuser in User.objects.filter(is_superuser=True):
            #     email=Emails.objects.get(purpose='admin_reg')
            #     subject=email.subject
            #     message=email.message.format(user=user)

            #     send_mail(
            #         subject,
            #         message,
            #         settings.DEFAULT_FROM_EMAIL,
            #         [superuser.email],
            #         fail_silently=True
            #     )
            return Response({'message': 'Registration successful. Please wait for approval.'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VehicleTypeViewSet(viewsets.ModelViewSet):
    queryset = VehicleType.objects.all().order_by('-created_at')
    serializer_class = VehicleTypeSerializer
    permission_classes = [IsAdminUser]


# AdminQuotationViewSet removed


class AdminNotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdminNotificationSerializer
    permission_classes = [IsApprovedAdmin]

    @override
    def get_queryset(self):
        return AdminNotification.objects.filter(admin=self.request.user).order_by('-created_at')

    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({'status': 'marked as read'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def mark_all_as_read(self, request):
        notifications = AdminNotification.objects.filter(
            admin=request.user, is_read=False)
        notifications.update(is_read=True)
        return Response({'status': 'all notifications marked as read'}, status=status.HTTP_200_OK)



class AdminLeadViewSet(viewsets.ModelViewSet):
    queryset = Lead.objects.all().order_by('-updated_at')
    serializer_class = LeadSerializer
    permission_classes = [IsAdminUser]

    

    @override
    def get_queryset(self):
        queryset = Lead.objects.all()
        status_filter = self.request.query_params.get('status', None)
        school_name = self.request.query_params.get('school_name', None)

        if status_filter:
            if status_filter == 'PENDING':
                # Include EDITED leads in PENDING filter
                queryset = queryset.filter(status__in=['PENDING', 'EDITED'])
            elif status_filter == 'BOOKED':
                queryset = queryset.filter(
                    Q(status='PAY_LATER') | 
                    Q(status='ACCEPTED', transaction__status='PENDING')
                ).distinct()
            elif status_filter == 'ACCEPTED':
                 queryset = queryset.filter(status='ACCEPTED').exclude(transaction__status='PENDING')
            else:
                queryset = queryset.filter(status=status_filter)

        if school_name:
            queryset = queryset.filter(institute_name=school_name)

        return queryset.order_by('-updated_at')

    @override
    def perform_update(self, serializer):
        original_status = serializer.instance.status
        instance = serializer.save()
        
        if original_status != 'ACCEPTED' and instance.status == 'ACCEPTED':
            self._handle_approval(instance)
        elif original_status != 'REJECTED' and instance.status == 'REJECTED':
            self._handle_rejection(instance)

    def _handle_approval(self, lead):
        logger.info(f"Approved lead {lead.id}")
        
        if lead.user:
            Notification.objects.create(
                user=lead.user,
                notification_type='TRIP_APPROVED',
                title="Lead Approved",
                message=f"Your trip #{lead.id} from {lead.pickup_location} to {lead.dropoff_location} has been approved. You can now proceed with payment.",
                is_read=False
            )
            # send_chat_notification(lead, lead.user, "Your trip has been approved.") # Optional

        try:
            email = Emails.objects.get(purpose='lead_accepted')
            lead_display_name = getattr(lead, 'name', None) or f"#{lead.id}"
            
            # Format message
            formatted_message = email.message.format(
                lead=lead,
                name=lead_display_name,
                vehicle_type=lead.vehicle_type if lead.vehicle_type else "N/A",
                payment_text="You can now proceed with payment.",
                user_url=f"{settings.FRONTEND_URL}/user_dashboard",
            )
            
            formatted_subject = email.subject.format(lead=lead)

            message = Mail(
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                to_emails=lead.email,
                subject=formatted_subject,
                plain_text_content=formatted_message
            )
            message.tracking_settings = TrackingSettings(click_tracking=ClickTracking(enable=False, enable_text=False))
            
            sg = SendGridAPIClient(settings.EMAIL_HOST_PASSWORD)
            sg.send(message)
        except Emails.DoesNotExist:
            logger.warning("Email template 'lead_accepted' not found.")
        except Exception as e:
            logger.error(f"Error sending approval email for lead {lead.id}: {str(e)}")

    def _handle_rejection(self, lead):
        logger.info(f"Rejected lead {lead.id}")
        
        if lead.user:
            Notification.objects.create(
                user=lead.user,
                notification_type='TRIP_REJECTED',
                title="Lead Rejected",
                message=f"Your trip #{lead.id} has been rejected. Reason: {lead.rejection_reason}",
                is_read=False
            )

        try:
            email = Emails.objects.get(purpose='lead_rejected') # Assuming template exists
            lead_display_name = getattr(lead, 'name', None) or f"#{lead.id}"
            
            formatted_message = email.message.format(
                lead=lead,
                name=lead_display_name,
                reason=lead.rejection_reason or "No reason provided",
                user_url=f"{settings.FRONTEND_URL}/user_dashboard",
            )
             
            formatted_subject = email.subject.format(lead=lead)
            
            message = Mail(
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                to_emails=lead.email,
                subject=formatted_subject,
                plain_text_content=formatted_message
            )
            message.tracking_settings = TrackingSettings(click_tracking=ClickTracking(enable=False, enable_text=False))
            
            sg = SendGridAPIClient(settings.EMAIL_HOST_PASSWORD)
            sg.send(message)
        except Emails.DoesNotExist:
             logger.warning("Email template 'lead_rejected' not found.")
        except Exception as e:
            logger.error(f"Error sending rejection email for lead {lead.id}: {str(e)}")
            logger.info(f"User approval email sent to {lead.email}")
            lead.email_sent = True
            lead.save(update_fields=['email_sent'])
        except Exception as e:
            logger.error(f"Failed to send lead-approved email: {str(e)}")

        for admin in AdminProfile.objects.filter(is_approved=True):
            AdminNotification.objects.create(
                admin=admin.user,
                lead=lead,
                message=f"Lead #{lead.id} approved by you"
            )

        return Response({'status': 'approved'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        lead = self.get_object()
        rejection_reason = request.data.get('rejection_reason')

        if not rejection_reason:
            raise ValidationError({"error": "Rejection reason is required when rejecting the quotation."})

        lead.status = 'REJECTED'
        lead.updated_at = timezone.now()
        lead.rejection_reason = rejection_reason
        lead.save()

        if lead.user:
            human_rejection_reason = dict(Lead.REJECTION_CHOICES).get(rejection_reason, rejection_reason)
            Notification.objects.create(
                user=lead.user,
                notification_type='TRIP_REJECTED',
                title="Lead Rejected",
                message=f"Your trip #{lead.id} from {lead.pickup_location} to {lead.dropoff_location} has been rejected. Reason: {human_rejection_reason}",
                is_read=False
            )
            logger.info(f"Client notification sent to user {lead.user.id} for rejected trip {lead.id}")

        try:
            human_rejection_reason = dict(Lead.REJECTION_CHOICES).get(rejection_reason, rejection_reason)
        except Exception:
            human_rejection_reason = rejection_reason

        email = Emails.objects.get(purpose='lead_rejected')
        formatted_message = email.message.format(
            lead=lead,
            human_rejection_reason=lead.get_rejection_reason_display()
        )

        email = Emails.objects.get(purpose="lead_rejected")
        try:
            send_mail(
                subject=email.subject,
                message=formatted_message,
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                recipient_list=[lead.email],
                fail_silently=False
            )
            logger.info(f"User rejection email sent to {lead.email}")
            lead.email_sent = True
            lead.save(update_fields=['email_sent'])
        except Exception as e:
            logger.error(f"Failed to send lead-rejected email: {str(e)}")

        return Response({'status': 'rejected', 'rejection_reason': rejection_reason})

    @override
    def perform_update(self, serializer):
        allowed = {'estimated_price', 'admin_message'}
        incoming = set(serializer.validated_data.keys())

        if not incoming.issubset(allowed):
            raise serializers.ValidationError({
                "detail": f"Only the following fields may be updated: {', '.join(allowed)}"
            })

        # Get the original lead to compare prices
        lead = self.get_object()
        original_price = lead.estimated_price
        is_edited = lead.is_edited
        
        # Save the updated lead
        updated_lead = serializer.save()
        
        # Send re-quote email if:
        # 1. The lead was edited (is_edited = True)
        # 2. The estimated_price was updated
        # 3. The lead has an email address
        if is_edited and 'estimated_price' in incoming and updated_lead.email:
            new_price = updated_lead.estimated_price
            price_changed = original_price != new_price
            
            try:
                # Get or create the re-quote email template
                if price_changed:
                    email_template, created = Emails.objects.get_or_create(
                        purpose='requote_price_changed',
                        defaults={
                            'subject': 'Updated Quote for Your Trip #{lead_id}',
                            'message': '''Dear {name},

Thank you for your patience. We have reviewed your updated trip request and here is your new quote:

Trip Details:
• From: {pickup_location}
• To: {dropoff_location}
• Date: {travel_date}
• Time: {pickup_time}
• Passengers: {passengers}
• Vehicle: {vehicle_type}

Previous Price: €{original_price}
New Price: €{new_price}

{admin_message}

If you have any questions or would like to proceed with this booking, please let us know.

Best regards,
Dave Long Coach Travel Team'''
                        }
                    )
                else:
                    email_template, created = Emails.objects.get_or_create(
                        purpose='requote_price_same',
                        defaults={
                            'subject': 'Quote Confirmation for Your Trip #{lead_id}',
                            'message': '''Dear {name},

Thank you for your patience. We have reviewed your updated trip request.

Trip Details:
• From: {pickup_location}
• To: {dropoff_location}
• Date: {travel_date}
• Time: {pickup_time}
• Passengers: {passengers}
• Vehicle: {vehicle_type}

Price: €{price} (unchanged)

{admin_message}

If you have any questions or would like to proceed with this booking, please let us know.

Best regards,
Dave Long Coach Travel Team'''
                        }
                    )
                
                # Format the email
                formatted_subject = email_template.subject.format(
                    lead_id=updated_lead.id
                )
                
                if price_changed:
                    formatted_message = email_template.message.format(
                        name=updated_lead.name or 'Customer',
                        pickup_location=updated_lead.pickup_location,
                        dropoff_location=updated_lead.dropoff_location,
                        travel_date=updated_lead.travel_date,
                        pickup_time=updated_lead.pickup_time,
                        passengers=updated_lead.number_of_passengers,
                        vehicle_type=updated_lead.vehicle_type or 'Standard',
                        original_price=f"{original_price:.2f}",
                        new_price=f"{new_price:.2f}",
                        admin_message=updated_lead.admin_message or ''
                    )
                else:
                    formatted_message = email_template.message.format(
                        name=updated_lead.name or 'Customer',
                        pickup_location=updated_lead.pickup_location,
                        dropoff_location=updated_lead.dropoff_location,
                        travel_date=updated_lead.travel_date,
                        pickup_time=updated_lead.pickup_time,
                        passengers=updated_lead.number_of_passengers,
                        vehicle_type=updated_lead.vehicle_type or 'Standard',
                        price=f"{new_price:.2f}",
                        admin_message=updated_lead.admin_message or ''
                    )
                
                # Send the email
                send_mail(
                    subject=formatted_subject,
                    message=formatted_message,
                    from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                    recipient_list=[updated_lead.email],
                    fail_silently=False
                )
                
                logger.info(f"Re-quote email sent to {updated_lead.email} for lead #{updated_lead.id} (price_changed={price_changed})")
                
                # Create user notification if user exists
                if updated_lead.user:
                    notification_message = (
                        f"Your trip #{updated_lead.id} has been re-quoted. "
                        f"New price: €{new_price:.2f}" if price_changed 
                        else f"Your trip #{updated_lead.id} quote confirmed at €{new_price:.2f}"
                    )
                    Notification.objects.create(
                        user=updated_lead.user,
                        notification_type='ADMIN_UPDATE',
                        title='Updated Quote Available',
                        message=notification_message,
                        is_read=False,
                        email_sent=True
                    )
                    logger.info(f"User notification created for user {updated_lead.user.id}")
                
                # Reset is_edited flag after sending re-quote
                updated_lead.is_edited = False
                updated_lead.save(update_fields=['is_edited'])
                
            except Exception as e:
                logger.error(f"Failed to send re-quote email for lead #{updated_lead.id}: {str(e)}")
                # Don't raise the exception - the update should still succeed even if email fails


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_lead(request, lead_id):
    """
    Delete a specific lead by ID.
    """
    try:
        lead = Lead.objects.get(id=lead_id)
        lead.delete()
        return Response({
            "status": "success",
            "message": f"Successfully deleted lead #{lead_id}"
        }, status=status.HTTP_200_OK)
    except Lead.DoesNotExist:
        return Response({
            "status": "error",
            "message": f"Lead #{lead_id} not found"
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_user(request, user_id):
    """
    Delete a specific user by ID.
    """
    try:
        if request.user.id == user_id:
            return Response({
                "status": "error",
                "message": "You cannot delete your own admin account."
            }, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.get(id=user_id)
        user.delete()
        return Response({
            "status": "success",
            "message": f"Successfully deleted user #{user_id}"
        }, status=status.HTTP_200_OK)
    except User.DoesNotExist:
        return Response({
            "status": "error",
            "message": f"User #{user_id} not found"
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminUserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]

    @override
    def get_queryset(self):
        return User.objects.filter(is_staff=False).order_by('-date_joined')

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        try:
            user = self.get_object()
            user.is_active = not user.is_active
            user.save()
            return Response({'status': 'success', 'is_active': user.is_active})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def leads(self, request, pk=None):
        user = self.get_object()
        leads = Lead.objects.filter(email=user.email)
        serializer = LeadSerializer(leads, many=True)
        return Response(serializer.data)



@api_view(["GET"])
@permission_classes([IsAdminUser])
def xero_connect(request):
    xero = XeroManager(request.user)
    auth_url = xero.get_authorization_url(request)
    return Response({"url": auth_url})
@api_view(['GET'])
@permission_classes([AllowAny])  # public callback
def xero_callback(request):
    code = request.GET.get('code')
    # state = request.GET.get('state')  # ignore state

    if not code:
        return Response({"error": "Missing code"}, status=400)

    # Determine admin user
    user = request.user if request.user.is_authenticated else \
           AdminProfile.objects.filter(is_approved=True).first().user

    xero = XeroManager(user)
    try:
        token = xero.exchange_code_for_token(code)

        scope = token.get("scope", "")
        if isinstance(scope, list):
            scope = " ".join(scope)

        XeroToken.objects.update_or_create(
            user=user,
            defaults={
                "access_token": token["access_token"],
                "refresh_token": token["refresh_token"],
                "expires_at": timezone.now() + timedelta(seconds=token["expires_in"]),
                "scope": scope,
            }
        )

        # Fetch tenant ID
        xero.get_tenant_id()

        return redirect(f"{settings.FRONTEND_URL}/admin_dashboard?xero_success=true")
    except Exception as e:
        logger.error(f"Xero callback failed: {e}")
        return Response({"error": str(e)}, status=400)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def send_lead_invoice_manually(request, lead_id):
    """
    Manually triggers sending the Xero invoice email for a specific lead.
    """
    try:
        lead = get_object_or_404(Lead, id=lead_id)
        
        # Determine admin user (reuse logic from other views or just use request.user if they are admin)
        # The Xero token is usually stored against a specific admin user (often the first approved one, or the one who connected it)
        admin_user = request.user
        xero_manager = XeroManager(admin_user)
        
        # Check if this user has a token, if not try the first approved admin (common pattern in this codebase)
        if not xero_manager.get_token():
            first_admin = AdminProfile.objects.filter(is_approved=True).first()
            if first_admin:
                admin_user = first_admin.user
                xero_manager = XeroManager(admin_user)

        if not xero_manager.get_token():
            return Response({"error": "No Xero connection found. Please connect Xero first."}, status=400)

        # 1. Try to find existing invoice
        invoice = xero_manager.get_invoice_by_lead(lead)
        
        
        if not invoice:
             return Response({"error": "No invoice found for this lead in Xero. Please ensure payment is completed or sync manually."}, status=404)
        
        # 2. Email the invoice
        success = xero_manager.email_invoice_pdf(invoice.invoice_id, lead)
        
        if success:
            return Response({"message": f"Invoice email sent to {lead.email}"})
        else:
            return Response({"error": "Failed to send invoice email"}, status=500)

    except Exception as e:
        logger.error(f"Manual invoice send failed: {e}")
        return Response({"error": str(e)}, status=500)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_invoice_sent_status(request, lead_id):
    """
    Manually update the invoice_sent status of a lead.
    Expected body: {"invoice_sent": boolean}
    """
    try:
        lead = get_object_or_404(Lead, id=lead_id)
        invoice_sent = request.data.get('invoice_sent')

        if invoice_sent is None:
            return Response({"error": "field 'invoice_sent' is required"}, status=400)

        if not isinstance(invoice_sent, bool):
             return Response({"error": "field 'invoice_sent' must be a boolean"}, status=400)

        lead.invoice_sent = invoice_sent
        lead.save()
        
        return Response({
            "message": f"Invoice sent status updated to {invoice_sent}",
            "lead_id": lead.id,
            "invoice_sent": lead.invoice_sent
        })

    except Exception as e:
        logger.error(f"Failed to update invoice_sent status: {e}")
        return Response({"error": str(e)}, status=500)





@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def admin_login(request):
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password')

    if not email or not password:
        return Response({'error': 'Email and password are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email__iexact=email, is_staff=True)  # 👈 FIXED

        auth_user = authenticate(username=user.username, password=password)
        if not auth_user:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            admin_profile = user.adminprofile
            if not admin_profile.is_approved:
                return Response({'error': 'Your admin account is pending approval'},
                                status=status.HTTP_401_UNAUTHORIZED)
        except AdminProfile.DoesNotExist:
            return Response({'error': 'Admin profile not found'}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_staff': user.is_staff,
                'is_approved': admin_profile.is_approved
            }
        })

    except User.DoesNotExist:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_profile(request):
    user = request.user
    profile = AdminProfile.objects.get(user=user)
    return Response({
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_active': user.is_active,
        'is_approved': profile.is_approved,
        'date_joined': user.date_joined,
    })


@api_view(['POST'])
@permission_classes([IsAdminUser])
def change_admin_password(request):
    user = request.user
    current_password = request.data.get('current_password')
    new_password = request.data.get('new_password')
    if not user.check_password(current_password):
        return Response({'error': 'Current password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save()
    return Response({'message': 'Password updated successfully'})


# ------------------------------------------------------------------------------
# Transaction Endpoints
# ------------------------------------------------------------------------------


@api_view(['POST'])
@permission_classes([AllowAny])  # isAuthenticated
def create_transaction(request):
    data = request.data.copy()
    payment_type = data.get('payment_type')
    total_amount = data.get('total_amount')

    # Validation for payment type
    if payment_type not in ['COMPLETE', 'SPLIT']:
        return Response({"error": "payment_type must be either 'COMPLETE' or 'SPLIT'."},
                        status=status.HTTP_400_BAD_REQUEST)
    if not total_amount:
        return Response({"error": "total_amount is required."}, status=status.HTTP_400_BAD_REQUEST)

    # Validation for total amount
    try:
        total_amount = Decimal(total_amount)
    except:
        return Response({"error": "total_amount must be a valid number."}, status=status.HTTP_400_BAD_REQUEST)

    data['total_amount'] = total_amount

    # Set appropriate values based on payment type
    if payment_type == 'COMPLETE':
        data['total_splits_count'] = None
        data['split_paid_count'] = None
        data['amount_per_split'] = 0
    elif payment_type == 'SPLIT':
        total_splits_count = data.get('total_splits_count')
        if not total_splits_count:
            return Response({"error": "total_splits_count is required for a SPLIT payment."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            total_splits_count = int(total_splits_count)
        except ValueError:
            return Response({"error": "total_splits_count must be a valid integer."},
                            status=status.HTTP_400_BAD_REQUEST)
        data['total_splits_count'] = total_splits_count
        amount_per_split = data.get('amount_per_split')
        if not amount_per_split:
            data['amount_per_split'] = total_amount / total_splits_count
        else:
            try:
                amount_per_split = Decimal(amount_per_split)
            except:
                return Response({"error": "amount_per_split must be a valid number."},
                                status=status.HTTP_400_BAD_REQUEST)
            data['amount_per_split'] = amount_per_split
        data['split_paid_count'] = data.get('split_paid_count', 0)

    # Important: Verify that the lead exists before attempting to create a transaction
    lead_id = data.get('lead_id') #or data.get('quotation_id')
    try:
        # Check if the Lead exists
        lead = Lead.objects.get(id=lead_id)
    except Lead.DoesNotExist:
        return Response({"error": f"Lead with ID {lead_id} does not exist"},
                        status=status.HTTP_404_NOT_FOUND)
    data['lead'] = lead.id

    # Continue with transaction creation if lead exists
    serializer = TransactionSerializer(data=data)
    if serializer.is_valid():
        transaction = serializer.save()

        try:
            lead = transaction.lead
            payment_id = data.get('payment_id')
            payment_url = str(data.get('payment_url', ''))  # ensure it's a string

            # Fetch the email template
            email_template = Emails.objects.get(purpose='transaction_created')

            # Prepare context for template
            context = {
                'lead': lead,
                'total_amount': total_amount,
                'payment_id': payment_id,
                'payment_url': payment_url,
            }

            # Render subject and message
            subject = email_template.subject.replace('{quotation.id}', str(lead.id))
            message_body = email_template.message.format(**context)

            # Create SendGrid Mail object
            message = Mail(
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                to_emails=lead.email,
                subject=subject,
                plain_text_content=message_body
            )

            # Disable click tracking to preserve the exact URL
            tracking_settings = TrackingSettings(click_tracking=ClickTracking(enable=False, enable_text=False))
            message.tracking_settings = tracking_settings

            # Send email via SendGrid
            sg = SendGridAPIClient(settings.EMAIL_HOST_PASSWORD)
            response = sg.send(message)

            logger.info(f"Transaction email sent to {lead.email}. Status code: {response.status_code}")

        except Exception as e:
            logger.error(f"Failed to send transaction creation email: {str(e)}")
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_transaction_by_lead(request, lead_id):
    transactions = Transaction.objects.filter(lead_id=lead_id)
    if transactions.exists():
        serializer = TransactionSerializer(transactions, many=True)
        payment_ids = list(transactions.values_list('payment_id', flat=True))
        payment_ids = [pid for pid in payment_ids if pid is not None]

        response_data = {
            'transactions': serializer.data,
            'payment_ids': payment_ids
        }
        return Response(response_data, status=status.HTTP_200_OK)
    return Response({'transactions': [], 'payment_ids': []}, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([AllowAny])
def update_transaction(request, lead_id):
    transaction = get_object_or_404(Transaction, lead_id=lead_id)
    payment_type = transaction.payment_type
    new_split_paid_count = request.data.get('split_paid_count')

    if new_split_paid_count is not None:
        try:
            new_split_paid_count = int(new_split_paid_count)
            if new_split_paid_count < 0:
                return Response({"error": "split_paid_count cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({"error": "split_paid_count must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        if transaction.split_paid_count is None:
            transaction.split_paid_count = new_split_paid_count
        else:
            transaction.split_paid_count += new_split_paid_count

    if payment_type == 'COMPLETE':
        transaction.status = 'COMPLETED'
    elif payment_type == 'SPLIT':
        if transaction.split_paid_count is not None and transaction.split_paid_count >= transaction.total_splits_count:
            transaction.status = 'COMPLETED'
        else:
            transaction.status = 'PENDING'

    transaction.updated_at = timezone.now()
    transaction.save()

    if transaction.status == 'COMPLETED':
        try:
            lead = transaction.lead
            email = Emails.objects.get(purpose='payment_lead_completed')
            subject = email.subject.format(quotation_id=lead_id)
            message = email.message.format(
                lead=lead, quotation_id=lead_id)

            send_mail(
                subject=subject,
                message=message,
                from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                recipient_list=[lead.email],
                fail_silently=False
            )

            approved_admins = AdminProfile.objects.filter(is_approved=True)
            notification_message = f"Payment received for Lead #{lead_id}"
            for admin_profile in approved_admins:
                notification_exists = AdminNotification.objects.filter(
                    admin=admin_profile.user,
                    lead=lead,
                    message=notification_message
                ).exists()

                if not notification_exists:
                    AdminNotification.objects.create(
                        admin=admin_profile.user,
                        lead=lead,
                        message=notification_message
                    )
        except Lead.DoesNotExist:
            logger.error(
                f"Lead with id {transaction.lead.id} does not exist")
        except Exception as e:
            logger.error(f"Error sending completion notification: {str(e)}")

    serializer = TransactionSerializer(transaction)
    return Response(serializer.data, status=status.HTTP_200_OK)



@api_view(['GET'])
@permission_classes([AllowAny])
def update_transaction_status(request, lead_id):
    """
    Endpoint to update the status of all transactions with a given lead_id
    """
    new_status = "COMPLETED"
    
    # Ensure email templates exist
    LeadViewSet().ensure_email_templates()


    valid_statuses = [s[0] for s in Transaction.STATUS_CHOICES]
    if new_status not in valid_statuses:
        return Response(
            {"error": f"Invalid status. Must be one of: {valid_statuses}"},
            status=status.HTTP_400_BAD_REQUEST
        )


    transactions = Transaction.objects.filter(lead_id=lead_id)

    if not transactions.exists():
        return Response(
            {"error": "No transactions found for the given lead_id."},
            status=status.HTTP_404_NOT_FOUND
        )

    transactions.update(status=new_status, updated_at=timezone.now())

    if new_status == 'COMPLETED':
        
        # ------------------------------------------------------------------
        # XERO INTEGRATION START
        # ------------------------------------------------------------------
        try:
            admin_user = AdminProfile.objects.filter(is_approved=True).first().user
            xero_manager = XeroManager(admin_user)
            
            if xero_manager.get_token():
                lead = Lead.objects.get(id=lead_id)
                total_amount = sum(t.total_amount for t in transactions)
                invoice, error = xero_manager.create_invoice_for_lead(lead, total_amount)
                
                if invoice:
                   xero_manager.email_invoice_pdf(invoice.invoice_id, lead)
                else:
                    logger.error(f"Xero Invoice Creation Failed (Lead): {error}")
        except Exception as xero_e:
            logger.error(f"Xero Integration Error (Lead Payment): {xero_e}")
        # ------------------------------------------------------------------
        # XERO INTEGRATION END
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # Check if ALL transactions are COMPLETED -> Update Lead to COMPLETED
        # ------------------------------------------------------------------
        lead_transactions = Transaction.objects.filter(lead_id=lead_id)
        if not lead_transactions.filter(status__in=['PENDING', 'FAILED']).exists():
            try:
                lead_to_complete = Lead.objects.get(id=lead_id)
                # Only update if not already completed/cancelled to avoid reverting
                if lead_to_complete.status not in ['COMPLETED', 'CANCELLED']:
                    lead_to_complete.status = 'COMPLETED'
                    lead_to_complete.save(update_fields=['status'])
                    logger.info(f"Auto-completed Lead #{lead_id} as all transactions are completed.")
            except Lead.DoesNotExist:
                logger.error(f"Lead #{lead_id} not found during auto-completion check")


        try:
            lead = Lead.objects.get(id=lead_id)

            try:
                institute_email = Emails.objects.get(purpose='payment_lead_completed')
                institute_subject = institute_email.subject.format(
                    quotation_id=lead_id,
                    lead=lead
                )
                institute_message = institute_email.message.format(
                    quotation_id=lead_id,
                    lead=lead,
                    amount_paid=sum(t.total_amount for t in transactions),
                    payment_date=timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                send_mail(
                    subject=institute_subject,
                    message=institute_message,
                    from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                    recipient_list=[lead.email],
                    fail_silently=False
                )
            except Exception as e:
                logger.error(f"Failed to send institute payment confirmation: {str(e)}")

            try:
                admin_email = Emails.objects.get(purpose='admin_payment_notification')
                admin_subject = admin_email.subject.format(
                    lead_id=lead_id,
                    lead=lead
                )
                admin_message = admin_email.message.format(
                    lead=lead,
                    amount_paid=sum(t.total_amount for t in transactions),
                    payment_date=timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                admin_emails = [admin.user.email for admin in AdminProfile.objects.filter(is_approved=True)]

                if admin_emails:
                    send_mail(
                        subject=admin_subject,
                        message=admin_message,
                        from_email=f"{settings.EMAIL_SENDER_NAME_ADMIN} <{settings.DEFAULT_FROM_EMAIL}>",
                        recipient_list=admin_emails,
                        fail_silently=False
                    )
            except Exception as e:
                logger.error(f"Failed to send admin payment notification: {str(e)}")

            notification_message = f"Payment completed for Lead #{lead_id}"
            for admin_profile in AdminProfile.objects.filter(is_approved=True):
                if not AdminNotification.objects.filter(
                    admin=admin_profile.user,
                    lead=lead,
                    message=notification_message
                ).exists():
                    AdminNotification.objects.create(
                        admin=admin_profile.user,
                        lead=lead,
                        message=notification_message
                    )


            if lead.user:
                Notification.objects.create(
                    user=lead.user,
                    notification_type='PAYMENT_UPDATE',
                    title="Payment Completed",
                    message=f"Your payment for trip #{lead_id} from {lead.pickup_location} to {lead.dropoff_location} has been completed successfully.",
                    is_read=False
                )
                logger.info(f"User notification sent for payment completion on trip {lead_id}")

        except Lead.DoesNotExist:
            logger.error(f"Lead with id {lead_id} not found")
        except Exception as e:
            logger.error(f"Error processing payment completion notifications: {str(e)}")



    serializer = TransactionSerializer(transactions, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)




@api_view(['GET'])
@permission_classes([AllowAny])
def list_user_transactions(request):
    if request.user.is_authenticated:
        user_leads = Lead.objects.filter(email=request.user.email)
        transactions = Transaction.objects.filter(
            lead__in=user_leads).order_by('-created_at')
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def list_all_transactions_admin(request):
    transactions = Transaction.objects.all().order_by('-created_at')
    serializer = TransactionSerializer(transactions, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


class AdminEmailsViewSet(viewsets.ModelViewSet):
    """
    Admin-only access to view and update Email templates (subject & message).
    """
    queryset = Emails.objects.all().order_by('id')
    serializer_class = EmailsSerializer
    permission_classes = [permissions.IsAdminUser]

    def partial_update(self, request, *args, **kwargs):
        """
        Allow PATCH to update only subject and message.
        """
        allowed = {'subject', 'message'}
        incoming = set(request.data.keys())
        if not incoming.issubset(allowed):
            return Response(
                {"detail": f"Only 'subject' and 'message' can be updated."},
                status=400
            )
        return super().partial_update(request, *args, **kwargs)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def ListLeadsUserOnlyView(request):
    """
    GET API to fetch all users from leads table with name and email, sorted by id
    """
    users = Lead.objects.values('id', 'name', 'email').distinct().order_by('id')
    return Response({
        'success': True,
        'count': users.count(),
        'users': list(users)
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def email_list(request):
    """
    List all emails in the system.
    Only accessible by admin users.
    """
    emails = Emails.objects.all()
    serializer = EmailsSerializer(emails, many=True)
    return Response(serializer.data)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def email_get_update(request, pk):
    """
    GET: Retrieve a specific email by id.
    PATCH: Update a specific email (subject and message only).
    Only accessible by admin users.
    """
    try:
        email = Emails.objects.get(pk=pk)
    except Emails.DoesNotExist:
        return Response({"detail": "Email not found."}, status=404)

    if request.method == 'GET':
        serializer = EmailsSerializer(email)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        allowed = {'subject', 'message'}
        incoming = set(request.data.keys())
        if not incoming.issubset(allowed):
            return Response(
                {"detail": "Only 'subject' and 'message' can be updated."},
                status=400
            )

        serializer = EmailsSerializer(email, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)



@api_view(['POST'])
@permission_classes([AllowAny])
def create_transaction(request):
    data = request.data.copy()

    if 'lead' not in data:
        return Response({"lead": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

    total_amount = data.get('total_amount')
    if not total_amount:
        return Response({"error": "total_amount is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        total_amount = Decimal(total_amount)
    except:
        return Response({"error": "total_amount must be a valid number."}, status=status.HTTP_400_BAD_REQUEST)

    data['total_amount'] = total_amount
    serializer = TransactionSerializer(data=data)

    if serializer.is_valid():
        transaction = serializer.save()

        # Update Lead Status to BOOKED
        try:
            lead = transaction.lead
            if lead.status != 'BOOKED':
                lead.status = 'BOOKED'
                lead.save(update_fields=['status'])
                logger.info(f"Lead #{lead.id} status updated to BOOKED upon transaction creation.")

            # Send Transaction Email
            try:
                try:
                    email = Emails.objects.get(purpose='transaction_lead_created')
                    subject = email.subject.format(lead=lead)
                    message = email.message.format(
                        lead=lead,
                        total_amount=total_amount,
                        payment_id=data.get('payment_id'),
                        payment_url=data.get('payment_url'),
                        pickup_location=lead.pickup_location,
                        dropoff_location=lead.dropoff_location,
                        travel_date=lead.travel_date,
                        vehicle_type=lead.vehicle_type,
                        passenger_count=lead.number_of_passengers
                    )
                except Emails.DoesNotExist:
                    # Fallback email content
                    subject = f"Transaction Created - Lead #{lead.id}"
                    message = f"""Dear {lead.name},

Your transaction has been created successfully with the following details:

Total amount: {total_amount}
Payment ID: {data.get('payment_id')}
Payment URL: {data.get('payment_url')}

Pickup Location: {lead.pickup_location}
Dropoff Location: {lead.dropoff_location}
Travel Date: {lead.travel_date}
Vehicle Type: {lead.vehicle_type}
Passenger Count: {lead.number_of_passengers}

Thank you for your business!
Transport Team"""

                send_mail(
                    subject=subject,
                    message=message,
                    from_email=f"{settings.EMAIL_SENDER_NAME_USER} <{settings.DEFAULT_FROM_EMAIL}>",
                    recipient_list=[lead.email],
                    fail_silently=False
                )
            except Exception as e:
                logger.error(f"Failed to send transaction email: {str(e)}")

        except Exception as e:
            logger.error(f"Error updating lead status or sending email: {str(e)}")

        return Response(serializer.data, status=status.HTTP_201_CREATED)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)





# aj ka kam upar

#             transaction.status = new_status

#     transaction.updated_at = timezone.now()
#     transaction.save()

#     # Send email notification if transaction is completed
#     if transaction.status == 'COMPLETED':
#         email = Emails.objects.get(purpose='payment_completed')
#         quotation = Quotation.objects.get(id=transaction.quotation.id)
#         subject = email.subject.format(quotation_id=quotation.id)
#         message = email.message.format(transaction=transaction, quotation_id=quotation.id)

#         try:
#             send_mail(
#                 subject=subject,
#                 message=message,
#                 from_email=settings.DEFAULT_FROM_EMAIL,
#                 recipient_list=[transaction.quotation.user.email],
#                 fail_silently=True
#             )
#         except Exception as e:
#             logger.error(f"Failed to send payment update email: {str(e)}")

#         # Create notifications for admins
#         approved_admins = AdminProfile.objects.filter(is_approved=True)
#         notification_message = f"Payment received for Quotation #{quotation_id}"
#         for admin_profile in approved_admins:
#             # Check if the notification already exists
#             notification_exists = AdminNotification.objects.filter(
#                 admin=admin_profile.user,
#                 quotation=transaction.quotation,
#                 message=notification_message
#             ).exists()

#             if not notification_exists:
#                 AdminNotification.objects.create(
#                     admin=admin_profile.user,
#                     quotation=transaction.quotation,
#                     message=notification_message
#                 )

#     serializer = TransactionSerializer(transaction)
#     return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def lead_chat(request, lead_id):
    """
    Get chat messages for a lead or send a new message
    """
    try:
        lead = Lead.objects.get(id=lead_id)

        if not request.user.is_staff and lead.user != request.user:
            return Response(
                {"error": "You don't have permission to access this chat"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ----------------- GET MESSAGES -----------------
        if request.method == 'GET':
            messages = ChatMessage.objects.filter(lead=lead)
            serializer = ChatMessageSerializer(messages, many=True)

            if not request.user.is_staff:
                messages.filter(message_type='ADMIN', is_read=False).update(is_read=True)

            return Response({
                'success': True,
                'lead_id': lead_id,
                'messages': serializer.data,
                'count': messages.count()
            })

        # ----------------- SEND MESSAGE -----------------
        elif request.method == 'POST':
            data = request.data.copy()
            data['lead'] = lead_id
            data['sender'] = request.user.id
            data['message_type'] = 'ADMIN' if request.user.is_staff else 'USER'

            serializer = ChatMessageSerializer(data=data)
            if serializer.is_valid():
                serializer.save()

                # Send message to channel group
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f"lead_chat_{lead.id}",
                    {
                        "type": "chat_message",
                        "message": data['message'],
                        "sender": request.user.username,
                    }
                )

                # ----------------- EMAIL TO RECIPIENT -----------------
                # Email notifications are handled by send_chat_notification below.

                # ----------------- NOTIFICATIONS -----------------
                if not request.user.is_staff:
                    existing_messages = ChatMessage.objects.filter(
                        lead=lead,
                        message_type='USER'
                    ).count()
                    if existing_messages == 1:
                        for admin in AdminProfile.objects.filter(is_approved=True):
                            AdminNotification.objects.create(
                                admin=admin.user,
                                lead=lead,
                                message=f"New chat initiated for Lead #{lead.id} by {lead.name}"
                            )
                        logger.info(f"Admin notifications sent for new chat initiation on trip {lead.id}")
                else:
                    if lead.user:
                        existing_messages = ChatMessage.objects.filter(lead=lead).count()
                        if existing_messages == 1:
                            title = "Admin Started Chat"
                            message_text = f"Admin has initiated a conversation about your trip #{lead.id} from {lead.pickup_location} to {lead.dropoff_location}"
                        else:
                            title = "New Admin Reply"
                            message_text = f"Admin replied to your trip #{lead.id}: {data['message'][:50]}{'...' if len(data['message']) > 50 else ''}"

                        Notification.objects.create(
                            user=lead.user,
                            notification_type='ADMIN_UPDATE',
                            title=title,
                            message=message_text,
                            is_read=False
                        )
                        logger.info(f"User notification sent for admin message on trip {lead.id}")

                # ----------------- PUSH NOTIFICATION -----------------
                send_chat_notification(lead, request.user, data['message'])

                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Lead.DoesNotExist:
        return Response({"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND)





@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unread_message_count(request):
    """
    Get count of unread messages for user
    """
    if request.user.is_staff:
        unread_count = ChatMessage.objects.filter(
            message_type='USER',
            is_read=False
        ).count()
    else:
        user_leads = Lead.objects.filter(user=request.user)
        unread_count = ChatMessage.objects.filter(
            lead__in=user_leads,
            message_type='ADMIN',
            is_read=False
        ).count()

    return Response({
        'unread_count': unread_count
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lead_unread_message_count(request, lead_id):
    """
    Get count of unread messages for a specific lead
    """
    try:
        lead = Lead.objects.get(id=lead_id)
        if not request.user.is_staff and lead.user != request.user:
             return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
             
        if request.user.is_staff:
            unread_count = ChatMessage.objects.filter(
                lead=lead,
                message_type='USER',
                is_read=False
            ).count()
        else:
            unread_count = ChatMessage.objects.filter(
                lead=lead,
                message_type='ADMIN',
                is_read=False
            ).count()
            
        return Response({'unread_count': unread_count})
    except Lead.DoesNotExist:
        return Response({"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lead_conversation_history(request, lead_id):
    """
    Get complete conversation history for a specific lead (simplified version)
    """
    try:
        lead = Lead.objects.get(id=lead_id)

        if not request.user.is_staff and lead.user != request.user:
            return Response(
                {"error": "You don't have permission to access this conversation"},
                status=status.HTTP_403_FORBIDDEN
            )

        messages = ChatMessage.objects.filter(lead=lead).order_by('created_at')

        if not request.user.is_staff:
            messages.filter(message_type='ADMIN',
                            is_read=False).update(is_read=True)

        serializer = ChatMessageSerializer(messages, many=True)

        return Response({
            'success': True,
            'lead_id': lead_id,
            'conversation': serializer.data,
            'total_messages': messages.count(),
            'unread_messages': messages.filter(is_read=False).count() if not request.user.is_staff else 0
        })

    except Lead.DoesNotExist:
        return Response(
            {"error": "Lead not found"},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_pending_transactions(request, lead_id):
    """
    Delete all pending transactions related to a specific lead_id.
    """
    pending_transactions = Transaction.objects.filter(
        lead_id=lead_id,
        status='PENDING'
    )

    count = pending_transactions.count()
    pending_transactions.delete()

    return Response({
        "status": "success",
        "message": f"Successfully deleted {count} pending transactions",
        "lead_id": lead_id
    }, status=status.HTTP_200_OK)





@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_lead(request, lead_id):
    try:
        lead = Lead.objects.get(id=lead_id)
    except Lead.DoesNotExist:
        return Response({"error": "Lead not found"}, status=404)

    serializer = LeadRejectionSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(lead=lead)  # assign lead from URL
        lead.status = 'PENDING'
        lead.save()
        return Response(serializer.data, status=201)

    return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_lead_rejections(request, lead_id):
    """
    Get all rejection comments for a lead.
    """
    try:
        lead = Lead.objects.get(id=lead_id)
    except Lead.DoesNotExist:
        return Response({"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND)

    rejections = lead.rejections.all().order_by('-created_at')
    serializer = LeadRejectionSerializer(rejections, many=True)
    return Response(serializer.data)
class AdminUserProfileUpdateAPIView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            profile = user.profile
        except User.DoesNotExist:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except ObjectDoesNotExist:
            return Response({"detail": "Profile not found"}, status=404)

        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)
class CustomPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        pagination_data = {
            "count": self.page.paginator.count,
            "total_pages": self.page.paginator.num_pages,
            "current_page": self.page.number,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
        }

        # Optional: match your style (empty pagination object if only 1 page)
        if self.page.paginator.num_pages <= 1:
            pagination_data = {}

        return Response({
            "success": True,
            "results": {
                "data": data,
                "pagination": pagination_data
            }
        })


class AdminUserProfileList(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = User.objects.all().select_related("profile")
        paginator = CustomPagination()
        result_page = paginator.paginate_queryset(users, request)
        serializer = UserSerializer(result_page, many=True)
        return paginator.get_paginated_response(serializer.data)
class UserProfileUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        profile = request.user.profile
        serializer = ProfileSerializer(profile, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        profile = request.user.profile
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


User = get_user_model()

class GetSchoolByEmailAPIView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response(
                {"detail": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not registered"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Safely check if user has a profile
        profile = getattr(user, "profile", None)

        if profile is None:
            return Response(
                {"detail": "Profile not found for this user"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "email": user.email,
                "school_name": profile.school_name,
            },
            status=status.HTTP_200_OK
        )

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])    # 👈 Only logged-in users
def mark_lead_pay_later(request):
    lead_id = request.data.get("lead_id")

    if not lead_id:
        return Response(
            {"error": "lead_id is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 1️⃣ Only fetch lead belonging to logged-in user
    try:
        lead = Lead.objects.get(id=lead_id, user=request.user)
    except Lead.DoesNotExist:
        return Response(
            {"error": "Lead not found or not assigned to this user"},
            status=status.HTTP_404_NOT_FOUND
        )

    # 2️⃣ Status must be ACCEPTED
    if lead.status != "ACCEPTED":
        return Response(
            {"error": "Status must be ACCEPTED to mark as PAY_LATER"},
            status=status.HTTP_400_BAD_REQUEST
        )


    # 3️⃣ Update status
    lead.status = "PAY_LATER"
    lead.save()
    


    return Response(
        {"message": "Lead updated to PAY_LATER", "lead_id": lead.id},
        status=status.HTTP_200_OK
    )

class CalendarEventViewSet(viewsets.ViewSet):
    """
    Returns Leads as calendar events for the frontend.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        start_date = request.query_params.get('start')
        end_date = request.query_params.get('end')

        # Filter by date and status (COMPLETED, PAY_LATER)
        queryset = Lead.objects.filter(status__in=['COMPLETED', 'PAY_LATER'])

        if start_date:
            queryset = queryset.filter(travel_date__gte=start_date.split('T')[0])
        if end_date:
            queryset = queryset.filter(travel_date__lte=end_date.split('T')[0])

        events = []
        for lead in queryset:
            # Determine Color based on Status
            color = '#3788d8'  # Default Blue
            if lead.status == 'ACCEPTED':
                color = '#28a745'  # Green
            elif lead.status == 'PENDING':
                color = '#ffc107'  # Yellow/Orange
            elif lead.status == 'REJECTED':
                color = '#dc3545'  # Red
            elif lead.status == 'COMPLETED':
                color = '#17a2b8'  # Teal
            elif lead.status == 'PAY_LATER':
                color = '#6f42c1' # Purple
            
            # Construct Start/End Datetimes
            start_dt = f"{lead.travel_date}T{lead.pickup_time}"
            
            # Serialize Transactions
            transactions = []
            for trans in lead.transaction.all():
                transactions.append({
                    "id": trans.id,
                    "payment_type": trans.payment_type,
                    "payment_id": trans.payment_id,
                    "total_amount": str(trans.total_amount),
                    "admin_message": trans.admin_message,
                    "status": trans.status,
                    "total_splits_count": trans.total_splits_count,
                    "amount_per_split": str(trans.amount_per_split),
                    "split_paid_count": trans.split_paid_count,
                    "created_at": trans.created_at,
                    "updated_at": trans.updated_at,
                    "lead": trans.lead.id
                })

            events.append({
                "id": str(lead.id),
                "title": f"#{lead.id} - {lead.pickup_location} -> {lead.dropoff_location}",
                "start": start_dt,
                "backgroundColor": color,
                "borderColor": color,
                "extendedProps": {
                    "lead_id": lead.id,
                    "status": lead.status,
                    "vehicle": lead.vehicle_type,
                    "passengers": lead.number_of_passengers,
                    "name": lead.name,
                    "email": lead.email,
                    "phone": lead.phone_number,
                    "price": float(lead.calculated_price or 0),
                    # New fields
                    "school_name": lead.institute_name or "N/A",
                    "round_trip": lead.is_roundtrip,
                    "distance": float(lead.distance or 0),
                    "pickup": lead.pickup_location,
                    "dropoff": lead.dropoff_location,
                    "transactions": transactions
                }
            })

        return Response(events)


class LeadTransactionView(APIView):
    """
    Handle transactions for a specific lead.
    GET: List transactions for the lead.
    POST: Create a transaction for the lead.
    PATCH: Update transaction status.
    """
    permission_classes = [AllowAny]

    def get(self, request, lead_id):
        try:
            transactions = Transaction.objects.filter(lead_id=lead_id).order_by('-created_at')
            serializer = TransactionSerializer(transactions, many=True) 
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, lead_id):
        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            return Response({"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = TransactionSerializer(data=request.data)
        if serializer.is_valid():
             try:
                 with transaction.atomic():
                     txn = serializer.save(lead=lead)
                     
                     if lead.status != 'BOOKED':
                        lead.status = 'BOOKED'
                        lead.save(update_fields=['status'])
                         
                     return Response(serializer.data, status=status.HTTP_201_CREATED)
             except Exception as e:
                 return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
                 
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    def patch(self, request, lead_id):
         status_value = request.data.get('status')
         if not status_value:
             return Response({"error": "status is required"}, status=status.HTTP_400_BAD_REQUEST)
             
         try:
             with transaction.atomic():
                 txns = Transaction.objects.filter(lead_id=lead_id)
                 if not txns.exists():
                      return Response({"error": "No transactions found"}, status=status.HTTP_404_NOT_FOUND)
                      
                 txns.update(status=status_value)
                 
                 if status_value == 'COMPLETED':
                     Lead.objects.filter(id=lead_id).update(status='COMPLETED')
                     
                 return Response({"status": "updated", "count": txns.count()}, status=status.HTTP_200_OK)
         except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, lead_id):
        # Delete pending transactions
        txns = Transaction.objects.filter(lead_id=lead_id, status='PENDING')
        count = txns.count()
        txns.delete()
        return Response({"status": "deleted", "count": count}, status=status.HTTP_200_OK)
