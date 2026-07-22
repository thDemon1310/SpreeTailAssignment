from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Group, Membership, Expense, ExpenseSplit, Settlement

User = get_user_model()

class LeaveGroupAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user(username='Alice', email='a@t.com', password='pass')
        self.bob = User.objects.create_user(username='Bob', email='b@t.com', password='pass')
        self.carol = User.objects.create_user(username='Carol', email='c@t.com', password='pass')
        
        self.group = Group.objects.create(name='Test Group', created_by=self.alice)
        self.today = timezone.now().date()
        self.alice_mem = Membership.objects.create(user=self.alice, group=self.group, joined_on=self.today)
        self.bob_mem = Membership.objects.create(user=self.bob, group=self.group, joined_on=self.today)
        self.carol_mem = Membership.objects.create(user=self.carol, group=self.group, joined_on=self.today)
        
        self.url = reverse('group-leave', args=[self.group.id])

    def test_leave_group_not_member(self):
        """A user not in the group cannot leave it."""
        eve = User.objects.create_user(username='Eve', email='e@t.com', password='pass')
        self.client.force_authenticate(user=eve)
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not a member', resp.data['detail'])

    def test_leave_group_already_left(self):
        """A user who has already left cannot leave again."""
        self.bob_mem.left_on = self.today
        self.bob_mem.save()
        self.client.force_authenticate(user=self.bob)
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already left', resp.data['detail'])

    def test_leave_group_blocked_owing(self):
        """Alice pays 300, split equally. Bob owes 100, so Bob cannot leave."""
        exp = Expense.objects.create(
            group=self.group,
            paid_by=self.alice,
            description="Dinner",
            amount=Decimal('300.00'),
            date=self.today,
            split_type='equal'
        )
        ExpenseSplit.objects.create(expense=exp, user=self.alice, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.bob, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.carol, share_amount=Decimal('100.00'))

        self.client.force_authenticate(user=self.bob)
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Cannot leave group', resp.data['detail'])
        self.assertIn('outstanding balance', resp.data['detail'])
        self.assertIn('Alice', resp.data['detail']) # Bob owes Alice

    def test_leave_group_blocked_owed(self):
        """Alice pays 300, split equally. Alice is owed 200, so Alice cannot leave."""
        exp = Expense.objects.create(
            group=self.group,
            paid_by=self.alice,
            description="Dinner",
            amount=Decimal('300.00'),
            date=self.today,
            split_type='equal'
        )
        ExpenseSplit.objects.create(expense=exp, user=self.alice, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.bob, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.carol, share_amount=Decimal('100.00'))

        self.client.force_authenticate(user=self.alice)
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Cannot leave group', resp.data['detail'])
        self.assertIn('outstanding balance', resp.data['detail'])
        self.assertIn('Bob', resp.data['detail']) # Alice is owed by Bob and Carol

    def test_leave_group_succeeds_at_zero_balance(self):
        """Bob settles up his 100 debt to Alice. Bob's balance becomes 0, and he can leave."""
        exp = Expense.objects.create(
            group=self.group,
            paid_by=self.alice,
            description="Dinner",
            amount=Decimal('300.00'),
            date=self.today,
            split_type='equal'
        )
        ExpenseSplit.objects.create(expense=exp, user=self.alice, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.bob, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.carol, share_amount=Decimal('100.00'))

        # Bob settles with Alice
        Settlement.objects.create(
            group=self.group,
            from_user=self.bob,
            to_user=self.alice,
            amount=Decimal('100.00'),
            date=self.today
        )

        self.client.force_authenticate(user=self.bob)
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        
        # Verify left_on is set to today
        self.bob_mem.refresh_from_db()
        self.assertEqual(self.bob_mem.left_on, self.today)

    def test_leaving_does_not_affect_prior_expense_calculations(self):
        """Alice pays 300, split equally. Bob settles, leaves group. A new expense is created.
        Prior expense split must not be changed, but new expense must exclude Bob since he left."""
        exp1 = Expense.objects.create(
            group=self.group,
            paid_by=self.alice,
            description="Dinner 1",
            amount=Decimal('300.00'),
            date=self.today,
            split_type='equal'
        )
        ExpenseSplit.objects.create(expense=exp1, user=self.alice, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp1, user=self.bob, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp1, user=self.carol, share_amount=Decimal('100.00'))

        # Bob settles with Alice
        Settlement.objects.create(
            group=self.group,
            from_user=self.bob,
            to_user=self.alice,
            amount=Decimal('100.00'),
            date=self.today
        )

        # Bob leaves
        self.client.force_authenticate(user=self.bob)
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Bob's prior split is unchanged
        self.assertEqual(ExpenseSplit.objects.get(expense=exp1, user=self.bob).share_amount, Decimal('100.00'))
