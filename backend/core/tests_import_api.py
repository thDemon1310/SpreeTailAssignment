import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from core.models import Group, Membership, Expense, ImportBatch, ImportAnomaly
from django.utils import timezone

User = get_user_model()

class ImportAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass')
        self.group = Group.objects.create(name='Test Group', created_by=self.aisha)
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=timezone.now().date())
        
        self.client.force_authenticate(user=self.aisha)
        self.url = reverse('group-import', args=[self.group.id])

    def test_run_import_success(self):
        # Create a temporary CSV file
        csv_content = b"date,description,amount,currency,paid_by,split_with,split_type,split_details\n"
        csv_content += b"2026-03-01,Lunch,100,INR,Aisha,Aisha,equal,\n"
        
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_path = f.name
            
        try:
            with open(temp_path, 'rb') as f:
                response = self.client.post(self.url, {'file': f}, format='multipart')
                
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            data = response.json()
            self.assertIn('batch_id', data)
            self.assertEqual(data['total_rows_processed'], 1)
            
            # Check DB
            self.assertEqual(ImportBatch.objects.count(), 1)
            self.assertEqual(Expense.objects.count(), 1)
            self.assertEqual(ImportAnomaly.objects.count(), 0)
        finally:
            os.remove(temp_path)

    def test_run_import_with_anomaly(self):
        # Missing currency defaults to INR but creates anomaly
        csv_content = b"date,description,amount,currency,paid_by,split_with,split_type,split_details\n"
        csv_content += b"2026-03-01,Lunch,100,,Aisha,Aisha,equal,\n"
        
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_path = f.name
            
        try:
            with open(temp_path, 'rb') as f:
                response = self.client.post(self.url, {'file': f}, format='multipart')
                
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            data = response.json()
            
            # Anomalies list endpoint
            batch_id = data['batch_id']
            anomalies_url = reverse('group-import-anomalies', args=[self.group.id, batch_id])
            anomalies_resp = self.client.get(anomalies_url)
            self.assertEqual(anomalies_resp.status_code, status.HTTP_200_OK)
            anomalies = anomalies_resp.json()
            
            self.assertEqual(len(anomalies), 1)
            self.assertEqual(anomalies[0]['status'], 'auto_resolved')
            self.assertEqual(anomalies[0]['problem_type'], 'missing_currency')
        finally:
            os.remove(temp_path)
