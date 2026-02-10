from django.contrib import admin
from .models import (
    Emails, Lead, Trip, TripStop, Notification, Location, AdminProfile, VehicleType,
    AdminNotification, Transaction, ChatMessage
)


class TripStopInline(admin.TabularInline):
    model = TripStop
    extra = 0

# Admin configuration for Location
@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('address', 'latitude', 'longitude')
    search_fields = ('address',)


@admin.register(Emails)
class EmailsAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'purpose', 'subject', 'message'
    )
@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('id', 'type', 'pickup_location', 'dropoff_location', 'pickup_date', 'pickup_time', 'distance')
    list_filter = ('type', 'pickup_date')
    inlines = [TripStopInline]


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):

    list_display = (
        'id', 'name', 'email', 'vehicle_type', 'estimated_price',
        'created_at', 'status', 'invoice_sent'
    )
    list_filter = (
        'vehicle_type', 'created_at'
    )
    search_fields = ('name', 'email')
    readonly_fields = ('created_at', 'updated_at')
    # actions = ['mark_as_accepted', 'mark_as_rejected']

    fieldsets = (
        # ('Basic Information', {
        #     'fields': ('user', 'status', 'needs_review')
        # }),
        ('Journey Details', {
            'fields': (
                'outbound_trip', 'return_trip',
                'vehicle_type', 'number_of_passengers',
                'status', 'email_sent', 'invoice_sent'
            )
        }),
        ('Pricing', {
            'fields': ('estimated_price', 'distance')
        }),
        # ('Additional Information', {
        #     'fields': ('special_instructions',)
        # }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # def mark_as_accepted(self, request, queryset):
    #     queryset.update(status='ACCEPTED')
    #     for quote in queryset:
    #         self.message_user(request, f"Quote #{quote.id} marked as accepted")

    # mark_as_accepted.short_description = "Mark selected quotes as accepted"

    # def mark_as_rejected(self, request, queryset):
    #     queryset.update(status='REJECTED')
    #     for quote in queryset:
    #         self.message_user(request, f"Quote #{quote.id} marked as rejected")

    # mark_as_rejected.short_description = "Mark selected quotes as rejected"


# Admin configuration for Notification
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'notification_type', 'sent_at',
                    'email_sent', 'is_read', 'created_at')
    list_filter = ('notification_type', 'email_sent',
                   'sent_at', 'is_read', 'created_at')
    search_fields = ('user__email', 'message', 'title')
    readonly_fields = ('sent_at',)

# Admin configuration for VehicleType


@admin.register(VehicleType)
class VehicleTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at',
                    'updated_at', 'is_model_trained')
    list_filter = ('is_active', 'created_at', 'is_model_trained')
    search_fields = ('name',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('message_type', 'message', 'sender', 'is_read')
    search_fields = ('message_type',)


# Register other models without additional business logic.
admin.site.register(AdminProfile)
admin.site.register(AdminNotification)
admin.site.register(Transaction)
