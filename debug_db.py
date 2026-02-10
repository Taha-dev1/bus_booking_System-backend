import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

with connection.cursor() as cursor:
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'quotations_lead'")
    columns = [col[0] for col in cursor.fetchall()]
    print("Columns in quotations_lead:", columns)
    
    if 'final_pickup' in columns:
        print("final_pickup EXISTS")
    else:
        print("final_pickup MISSING")
        
    if 'finalpickup' in columns:
        print("finalpickup EXISTS (without underscore)")
