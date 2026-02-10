from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from quotations import views
from quotations.views import *

# Create router for regular endpoints
router = DefaultRouter()
router.register(r'user-notifications', UserNotificationViewSet,
                basename='user-notifications')

# Create router for admin endpoints
admin_router = DefaultRouter()
admin_router.register(r'users', AdminUserViewSet, basename='admin-user')
# admin_router.register(r'quotations', AdminQuotationViewSet,
#                       basename='admin-quotation')
admin_router.register(r'vehicles', VehicleTypeViewSet,
                      basename='admin-vehicle')
admin_router.register(
    r'notifications', AdminNotificationViewSet, basename='admin-notification')
router.register(r'admin/leads', AdminLeadViewSet, basename='admin-leads')
router.register(r'leads', LeadViewSet, basename='leads')

router.register(r'admin/email', AdminEmailsViewSet, basename='admin-email')
router.register(r'calendar/events', CalendarEventViewSet, basename='calendar-events')
# router.register(r'api/email', AdminEmailsViewSet, basename='admin-email')
# router.register(r'admin/email', AdminEmailsViewSet, basename='admin-email')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/admin/users/', AdminUserProfileList.as_view(), name='admin-users'),
    path('api/profile/update/', UserProfileUpdateAPIView.as_view(), name='user-profile-update'),
    path('api/admin/users/<int:user_id>/update-profile/', AdminUserProfileUpdateAPIView.as_view(),
         name='admin-update-profile'),

    # Regular API endpoints
    path('api/', include(router.urls)),
    path('api/register/', register_user, name='register'),
    path('api/login/', login_user, name='login'),
    path('api/verify-registration-otp/', verify_registration_otp,
         name='verify_registration_otp'),
    path('api/verify-login-otp/', verify_login_otp, name='verify_login_otp'),
    path('api/forgot-password/', forgot_password, name='forgot_password'),
    path('api/reset-password-confirm/', reset_password_confirm,
         name='reset_password_confirm'),
    path('api/google-auth/', google_auth, name='google_auth'),
    path('api/quotation-users/', views.ListLeadsUserOnlyView, name='quotation-users'),
    path('api/leads/<int:lead_id>/similar-locations-leads/',
         SimilarLocationsLeadsView.as_view(), name='admin-similar-leads'),

    path('api/leads/<int:lead_id>/chat/', views.lead_chat, name='lead_chat'),
    path('api/leads/<int:lead_id>/chat/unread/', views.lead_unread_message_count,
         name='lead_unread_message_count'),
    path('api/leads/<int:lead_id>/conversation/',
         views.lead_conversation_history, name='lead_conversation_history'),
    #LEAD REJECTIONS

    path('api/leads/<int:lead_id>/rejections/', views.get_lead_rejections, name='lead-rejections'),
    # Public Lead Creation
    path('api/lead/', views.public_create_lead, name='public-create-lead'),
    # Transaction
    path('api/leads/transactions/<int:lead_id>/', views.LeadTransactionView.as_view(), name='lead-transactions'),
    path('api/transactions/user/', list_user_transactions,
         name='list-user-transactions'),
    path('api/transactions/admin/', list_all_transactions_admin,
         name='list-all-transactions-admin'),
    path('api/email/', email_list, name='email-list'),
    path('api/email/<int:pk>/', email_get_update, name='email-get-update'),
    # path('api/email/<int:pk>/', email_detail, name='email-detail'),
    # Admin API endpoints
    path('api/admin/', include(admin_router.urls)),
    path('api/admin/login/', admin_login, name='admin-login'),
    path('api/admin/profile/', admin_profile, name='admin-profile'),
    path('api/admin/change-password/', change_admin_password,
         name='admin-change-password'),
    path('api/get-school-by-email', GetSchoolByEmailAPIView.as_view()),
    path("api/lead/pay-later/", mark_lead_pay_later, name="lead-pay-later"),

    path('api/admin/users/<int:user_id>/delete/', views.delete_user, name='delete-user'),
    path('api/admin/xero/connect/', views.xero_connect, name='xero-connect'),
    path('api/admin/xero/callback/', views.xero_callback, name='xero-callback'),
    path('api/admin/leads/<int:lead_id>/send-invoice/', views.send_lead_invoice_manually, name='send-lead-invoice'),
    # path('api/admin/leads/<int:lead_id>/mark-paid/', views.mark_invoice_paid, name='mark-invoice-paid'),
    path('api/admin/leads/<int:lead_id>/invoice-sent/', views.update_invoice_sent_status, name='update-invoice-sent'),
    # for vehicles
    path('api/vehicles/', list_vehicle_types, name='public-vehicles'),
    # path('predict/', PredictView.as_view(), name='predict'),
    # path('model-info/', ModelInfoView.as_view(), name='model-info'),
]
