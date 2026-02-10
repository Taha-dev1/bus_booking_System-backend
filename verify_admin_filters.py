import os
import django
from django.conf import settings
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from quotations.models import Lead, AdminProfile
from rest_framework.test import APIRequestFactory, force_authenticate
from quotations.views import AdminLeadViewSet
from django.contrib.auth import get_user_model

User = get_user_model()

def run_verification():
    print("--- Starting Admin Filter Verification ---")

    # 1. Setup Data
    admin_user, _ = User.objects.get_or_create(email="verify_admin_filter@example.com", defaults={"username": "verify_admin_filter", "is_staff": True})
    AdminProfile.objects.get_or_create(user=admin_user, defaults={"is_approved": True})
    
    Lead.objects.filter(email__startswith="verify_filter_").delete()

    today = timezone.now().date()
    
    lead_pending = Lead.objects.create(
        name="Lead Pending",
        travel_date=today,
        email="verify_filter_pending@example.com",
        pickup_location="London",
        dropoff_location="Manchester",
        distance=100.0,
        number_of_passengers=10,
        status='PENDING'
    )
    
    lead_edited = Lead.objects.create(
        name="Lead Edited",
        travel_date=today,
        email="verify_filter_edited@example.com",
        pickup_location="London",
        dropoff_location="Manchester",
        distance=100.0,
        number_of_passengers=10,
        status='EDITED'
    )
    
    lead_accepted = Lead.objects.create(
        name="Lead Accepted",
        travel_date=today,
        email="verify_filter_accepted@example.com",
        pickup_location="London",
        dropoff_location="Manchester",
        distance=100.0,
        number_of_passengers=10,
        status='ACCEPTED'
    )

    print(f"Created Leads: Pending={lead_pending.id}, Edited={lead_edited.id}, Accepted={lead_accepted.id}")

    # 2. Call the View with PENDING filter
    factory = APIRequestFactory()
    request = factory.get('/api/admin/leads/?status=PENDING')
    force_authenticate(request, user=admin_user)
    
    view = AdminLeadViewSet.as_view({'get': 'list'})
    response = view(request)

    print("\n--- Response Analysis (status=PENDING) ---")
    if response.status_code == 200:
        data = response.data
        # data might be paginated or a list depending on ViewSet settings
        results = data['results'] if isinstance(data, dict) and 'results' in data else data
        
        found_ids = [l['id'] for l in results]
        print(f"Found IDs: {found_ids}")
        
        found_pending = lead_pending.id in found_ids
        found_edited = lead_edited.id in found_ids
        found_accepted = lead_accepted.id in found_ids
        
        print(f"Pending Lead: {'[OK] FOUND' if found_pending else '[FAIL] NOT FOUND'}")
        print(f"Edited Lead:  {'[OK] FOUND' if found_edited else '[FAIL] NOT FOUND'}")
        print(f"Accepted Lead: {'[OK] NOT FOUND' if not found_accepted else '[FAIL] FOUND'}")
        
        if found_pending and found_edited and not found_accepted:
            print("\n*** VERIFICATION SUCCESSFUL ***")
        else:
            print("\n*** VERIFICATION FAILED ***")
            if not found_edited: print(" - Edited lead is missing! (Main Goal)")

    else:
        print(f"Error: {response.status_code} - {response.data}")

    # Cleanup
    Lead.objects.filter(email__startswith="verify_filter_").delete()

if __name__ == "__main__":
    run_verification()
