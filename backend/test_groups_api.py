import os
import django
from datetime import date
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spreetail_backend.settings")
django.setup()

from django.test import Client
from core.models import User, Group, Membership

user, created = User.objects.get_or_create(username='testuser', email='test@test.com')
if created:
    user.set_password('password')
    user.save()

if not Group.objects.exists():
    group = Group.objects.create(name='Test Group', description='Test', created_by=user)
    Membership.objects.create(user=user, group=group, joined_on=date.today())

client = Client()
client.force_login(user)

response = client.get('/api/groups/')
print("Status:", response.status_code)
print("Body:", response.json())
