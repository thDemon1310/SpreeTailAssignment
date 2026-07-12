import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from core.models import Group, Membership, Expense, ExpenseSplit, Settlement
from django.utils import timezone

User = get_user_model()

class SettlementAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass')
        self.rohan = User.objects.create_user(username='Rohan', email='r@t.com', password='pass')
        
        self.group = Group.objects.create(name='Test Group', created_by=self.aisha)
        today = timezone.now().date()
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=today)
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=today)
        
        # Aisha paid 200, split equally -> Rohan owes Aisha 100
        exp = Expense.objects.create(
            group=self.group,
            paid_by=self.aisha,
            description="Lunch",
            amount=Decimal('200.00'),
            date=today,
            split_type='equal'
        )
        ExpenseSplit.objects.create(expense=exp, user=self.aisha, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.rohan, share_amount=Decimal('100.00'))
        
        self.client.force_authenticate(user=self.rohan)
        self.url = reverse('group-settlement-list-create', args=[self.group.id])

    def test_create_settlement_and_check_balance(self):
        # 1. Verify initial balance
        bal_url = reverse('group-user-balance', args=[self.group.id, self.rohan.id])
        resp1 = self.client.get(bal_url)
        self.assertEqual(float(resp1.json()['balance']), -100.0)

        # 2. Create settlement (Rohan pays Aisha 100)
        payload = {
            'from_user_id': self.rohan.id,
            'to_user_id': self.aisha.id,
            'amount': '100.00',
            'date': timezone.now().date().isoformat()
        }
        resp2 = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)

        # 3. Verify balance is updated to 0
        resp3 = self.client.get(bal_url)
        self.assertEqual(float(resp3.json()['balance']), 0.0)
        self.assertEqual(float(resp3.json()['settlements_made']), 100.0)

    def test_list_settlements(self):
        Settlement.objects.create(
            group=self.group,
            from_user=self.rohan,
            to_user=self.aisha,
            amount=Decimal('50.00'),
            date=timezone.now().date()
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(float(response.json()[0]['amount']), 50.0)
