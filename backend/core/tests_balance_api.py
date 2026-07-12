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

class BalanceAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass')
        self.rohan = User.objects.create_user(username='Rohan', email='r@t.com', password='pass')
        
        self.group = Group.objects.create(name='Test Group', created_by=self.aisha)
        today = timezone.now().date()
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=today)
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=today)
        
        # Aisha paid 200, split equally
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
        
        # Rohan's balance is -100, Aisha's is +100
        
        self.client.force_authenticate(user=self.aisha)

    def test_group_balances_list(self):
        url = reverse('group-balances', args=[self.group.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn(str(self.aisha.id), data)
        self.assertIn(str(self.rohan.id), data)
        
        self.assertEqual(float(data[str(self.aisha.id)]), 100.0)
        self.assertEqual(float(data[str(self.rohan.id)]), -100.0)

    def test_user_balance_detail(self):
        url = reverse('group-user-balance', args=[self.group.id, self.rohan.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertEqual(float(data['balance']), -100.0)
        
        # Underlying rows
        self.assertEqual(float(data['total_paid']), 0.0)
        self.assertEqual(len(data['paid_expenses']), 0)
        
        self.assertEqual(float(data['total_owed']), 100.0)
        self.assertEqual(len(data['owed_splits']), 1)
        self.assertEqual(data['owed_splits'][0]['expense']['description'], 'Lunch')
        
        self.assertEqual(float(data['settlements_made']), 0.0)
        self.assertEqual(float(data['settlements_received']), 0.0)
