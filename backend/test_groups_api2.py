import os
import django
from datetime import date
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spreetail_backend.settings")
django.setup()

from django.test import Client
from core.models import User, Group, Membership

user, created = User.objects.get_or_create(username='testuser2', email='test2@test.com')
if created:
    user.set_password('password')
    user.save()

group, gcreated = Group.objects.get_or_create(name='Test Group 2', description='Test2', created_by=user)
if gcreated:
    Membership.objects.create(user=user, group=group, joined_on=date.today())

client = Client()
client.force_login(user)

response = client.get('/api/groups/', HTTP_HOST='localhost:8000')
print("Status:", response.status_code)
print("Body:", response.json())
