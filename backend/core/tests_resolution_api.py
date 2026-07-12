import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from core.models import Group, Membership, Expense, ImportBatch, ImportAnomaly
from django.utils import timezone

User = get_user_model()

class ResolutionAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass')
        self.group = Group.objects.create(name='Test Group', created_by=self.aisha)
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=timezone.now().date())
        
        self.batch = ImportBatch.objects.create(
            group=self.group, imported_by=self.aisha, filename='test.csv', total_rows=1
        )
        
        self.client.force_authenticate(user=self.aisha)

    def test_discard_anomaly(self):
        anomaly = ImportAnomaly.objects.create(
            batch=self.batch,
            row_number=1,
            raw_data={"description": "Test", "amount": "0"},
            problem_type="zero_amount",
            status="blocked"
        )
        url = reverse('group-anomaly-resolve', args=[self.group.id, anomaly.id])
        resp = self.client.post(url, {'action': 'discard'}, format='json')
        
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        anomaly.refresh_from_db()
        self.assertEqual(anomaly.status, 'manually_resolved')
        self.assertEqual(anomaly.action_taken, 'Discarded by user')
        self.assertEqual(Expense.objects.count(), 0)

    def test_apply_missing_payer(self):
        anomaly = ImportAnomaly.objects.create(
            batch=self.batch,
            row_number=1,
            raw_data={"description": "Lunch", "amount": "100", "date": "2026-03-01", "currency": "INR", "split_type": "equal", "split_with": "Aisha"},
            problem_type="missing_payer",
            status="blocked"
        )
        url = reverse('group-anomaly-resolve', args=[self.group.id, anomaly.id])
        resp = self.client.post(url, {
            'action': 'apply',
            'corrected_data': {'paid_by_id': self.aisha.id}
        }, format='json')
        
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        anomaly.refresh_from_db()
        self.assertEqual(anomaly.status, 'manually_resolved')
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(Expense.objects.first().paid_by, self.aisha)
        self.assertEqual(anomaly.linked_expense, Expense.objects.first())

    def test_apply_missing_field_fails(self):
        anomaly = ImportAnomaly.objects.create(
            batch=self.batch,
            row_number=1,
            raw_data={"description": "Lunch", "amount": "100", "date": "2026-03-01", "currency": "INR", "split_type": "equal", "split_with": "Aisha"},
            problem_type="missing_payer",
            status="blocked"
        )
        url = reverse('group-anomaly-resolve', args=[self.group.id, anomaly.id])
        resp = self.client.post(url, {
            'action': 'apply',
            'corrected_data': {}  # Missing paid_by_id
        }, format='json')
        
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("paid_by_id", resp.json()['detail'])
        self.assertEqual(Expense.objects.count(), 0)

    def test_apply_name_mismatch(self):
        anomaly = ImportAnomaly.objects.create(
            batch=self.batch,
            row_number=1,
            raw_data={"description": "Lunch", "amount": "100", "date": "2026-03-01", "currency": "INR", "split_type": "equal", "split_with": "Aisha", "paid_by": "Rohan"},
            problem_type="name_mismatch",
            status="blocked"
        )
        url = reverse('group-anomaly-resolve', args=[self.group.id, anomaly.id])
        resp = self.client.post(url, {
            'action': 'apply',
            'corrected_data': {'paid_by_id': self.aisha.id}
        }, format='json')
        
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        anomaly.refresh_from_db()
        self.assertEqual(anomaly.status, 'manually_resolved')
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(Expense.objects.first().paid_by, self.aisha)
        self.assertEqual(anomaly.linked_expense, Expense.objects.first())
