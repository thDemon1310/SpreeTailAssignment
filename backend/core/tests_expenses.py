"""
API tests for Expense create / list / detail endpoints.

Run with:
    python manage.py test core.tests_expenses --verbosity=2

These tests hit real views via APIClient (Django test DB, no network).
Every test verifies:
  - HTTP status is correct
  - ExpenseSplit rows are written (or not) as expected
  - sum(split.share_amount for split in expense) == expense.amount (invariant)

Reference: GEMINI.md Section 3 — tests must pass before the view is considered done.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Expense, ExpenseSplit, Group, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


def _make_user(username, password='testpass123!'):
    return User.objects.create_user(username=username, email=f'{username}@test.com', password=password)


def _get_token(client, username, password='testpass123!'):
    resp = client.post('/api/token/', {'username': username, 'password': password}, format='json')
    return resp.data['access']


def _auth(client, token):
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')


class ExpenseCreateEqualSplitTest(TestCase):
    """POST /api/groups/<id>/expenses/ with split_type='equal'."""

    def setUp(self):
        self.client = APIClient()
        self.alice = _make_user('alice')
        self.bob = _make_user('bob')
        self.carol = _make_user('carol')

        self.group = Group.objects.create(name='Test Group', created_by=self.alice)
        today = timezone.now().date()
        Membership.objects.create(user=self.alice, group=self.group, joined_on=today)
        Membership.objects.create(user=self.bob, group=self.group, joined_on=today)
        Membership.objects.create(user=self.carol, group=self.group, joined_on=today)

        token = _get_token(self.client, 'alice')
        _auth(self.client, token)
        self.url = f'/api/groups/{self.group.id}/expenses/'

    def test_create_equal_split_three_way(self):
        """₹300 split equally among 3 → each owes ₹100.00."""
        payload = {
            'description': 'Dinner',
            'amount': '300.00',
            'date': '2026-02-08',
            'split_type': 'equal',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id, self.carol.id],
            'split_details': {},
        }
        resp = self.client.post(self.url, payload, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        expense_id = resp.data['id']
        expense = Expense.objects.get(id=expense_id)

        splits = {s.user_id: s.share_amount for s in expense.splits.all()}
        self.assertEqual(splits[self.alice.id], Decimal('100.00'))
        self.assertEqual(splits[self.bob.id], Decimal('100.00'))
        self.assertEqual(splits[self.carol.id], Decimal('100.00'))
        # Invariant: sum == total
        self.assertEqual(sum(splits.values()), Decimal('300.00'))

    def test_create_equal_split_remainder_to_payer(self):
        """₹100 ÷ 3: payer (alice) absorbs the 1-paisa remainder → 33.34."""
        payload = {
            'description': 'Coffee',
            'amount': '100.00',
            'date': '2026-02-10',
            'split_type': 'equal',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id, self.carol.id],
            'split_details': {},
        }
        resp = self.client.post(self.url, payload, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        splits = {
            s.user_id: s.share_amount
            for s in Expense.objects.get(id=resp.data['id']).splits.all()
        }
        # Payer absorbs remainder
        self.assertEqual(splits[self.alice.id], Decimal('33.34'))
        self.assertEqual(splits[self.bob.id], Decimal('33.33'))
        self.assertEqual(splits[self.carol.id], Decimal('33.33'))
        self.assertEqual(sum(splits.values()), Decimal('100.00'))

    def test_response_includes_splits_nested(self):
        """POST response must include nested splits list — not a bare id."""
        payload = {
            'description': 'Groceries',
            'amount': '600.00',
            'date': '2026-03-01',
            'split_type': 'equal',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id],
            'split_details': {},
        }
        resp = self.client.post(self.url, payload, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('splits', resp.data)
        self.assertEqual(len(resp.data['splits']), 2)

    def test_expense_saved_to_db(self):
        """An Expense row and its ExpenseSplit rows must be in the DB."""
        payload = {
            'description': 'Rent',
            'amount': '15000.00',
            'date': '2026-03-01',
            'split_type': 'equal',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id],
            'split_details': {},
        }
        before_expenses = Expense.objects.count()
        before_splits = ExpenseSplit.objects.count()

        self.client.post(self.url, payload, format='json')

        self.assertEqual(Expense.objects.count(), before_expenses + 1)
        self.assertEqual(ExpenseSplit.objects.count(), before_splits + 2)


class ExpenseCreateUnequalSplitTest(TestCase):
    """POST with split_type='unequal'."""

    def setUp(self):
        self.client = APIClient()
        self.alice = _make_user('alice_u')
        self.bob = _make_user('bob_u')
        self.group = Group.objects.create(name='Unequal Group', created_by=self.alice)
        today = timezone.now().date()
        Membership.objects.create(user=self.alice, group=self.group, joined_on=today)
        Membership.objects.create(user=self.bob, group=self.group, joined_on=today)
        token = _get_token(self.client, 'alice_u')
        _auth(self.client, token)
        self.url = f'/api/groups/{self.group.id}/expenses/'

    def test_create_unequal_split(self):
        """alice pays ₹500, split ₹300 alice / ₹200 bob."""
        payload = {
            'description': 'Dinner',
            'amount': '500.00',
            'date': '2026-03-01',
            'split_type': 'unequal',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id],
            'split_details': {
                str(self.alice.id): '300.00',
                str(self.bob.id): '200.00',
            },
        }
        resp = self.client.post(self.url, payload, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        splits = {
            s.user_id: s.share_amount
            for s in Expense.objects.get(id=resp.data['id']).splits.all()
        }
        self.assertEqual(splits[self.alice.id], Decimal('300.00'))
        self.assertEqual(splits[self.bob.id], Decimal('200.00'))
        self.assertEqual(sum(splits.values()), Decimal('500.00'))

    def test_unequal_missing_participant_rejects(self):
        """split_details must cover all participant_ids — missing entry → 400."""
        payload = {
            'description': 'Test',
            'amount': '500.00',
            'date': '2026-03-01',
            'split_type': 'unequal',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id],
            'split_details': {str(self.alice.id): '500.00'},  # bob missing
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Expense.objects.count(), 0)  # nothing written


class ExpenseCreatePercentageSplitTest(TestCase):
    """POST with split_type='percentage'."""

    def setUp(self):
        self.client = APIClient()
        self.alice = _make_user('alice_p')
        self.bob = _make_user('bob_p')
        self.group = Group.objects.create(name='Pct Group', created_by=self.alice)
        today = timezone.now().date()
        Membership.objects.create(user=self.alice, group=self.group, joined_on=today)
        Membership.objects.create(user=self.bob, group=self.group, joined_on=today)
        token = _get_token(self.client, 'alice_p')
        _auth(self.client, token)
        self.url = f'/api/groups/{self.group.id}/expenses/'

    def test_create_percentage_split(self):
        """60/40 percentage split on ₹1000."""
        payload = {
            'description': 'Subscription',
            'amount': '1000.00',
            'date': '2026-03-15',
            'split_type': 'percentage',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id],
            'split_details': {
                str(self.alice.id): '60',
                str(self.bob.id): '40',
            },
        }
        resp = self.client.post(self.url, payload, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        splits = {
            s.user_id: s.share_amount
            for s in Expense.objects.get(id=resp.data['id']).splits.all()
        }
        self.assertEqual(splits[self.alice.id], Decimal('600.00'))
        self.assertEqual(splits[self.bob.id], Decimal('400.00'))
        self.assertEqual(sum(splits.values()), Decimal('1000.00'))

    def test_percentage_not_summing_100_rejects(self):
        """Percentages that don't sum to 100 → 400, nothing written."""
        payload = {
            'description': 'Bad split',
            'amount': '1000.00',
            'date': '2026-03-15',
            'split_type': 'percentage',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id],
            'split_details': {
                str(self.alice.id): '60',
                str(self.bob.id): '60',  # sums to 120
            },
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Expense.objects.count(), 0)


class ExpenseCreateSharesSplitTest(TestCase):
    """POST with split_type='shares'."""

    def setUp(self):
        self.client = APIClient()
        self.alice = _make_user('alice_s')
        self.bob = _make_user('bob_s')
        self.group = Group.objects.create(name='Shares Group', created_by=self.alice)
        today = timezone.now().date()
        Membership.objects.create(user=self.alice, group=self.group, joined_on=today)
        Membership.objects.create(user=self.bob, group=self.group, joined_on=today)
        token = _get_token(self.client, 'alice_s')
        _auth(self.client, token)
        self.url = f'/api/groups/{self.group.id}/expenses/'

    def test_create_shares_split_2_to_1(self):
        """alice has 2 shares, bob 1 share → ₹300 splits ₹200/₹100."""
        payload = {
            'description': 'Villa rent',
            'amount': '300.00',
            'date': '2026-04-01',
            'split_type': 'shares',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id, self.bob.id],
            'split_details': {
                str(self.alice.id): '2',
                str(self.bob.id): '1',
            },
        }
        resp = self.client.post(self.url, payload, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        splits = {
            s.user_id: s.share_amount
            for s in Expense.objects.get(id=resp.data['id']).splits.all()
        }
        self.assertEqual(splits[self.alice.id], Decimal('200.00'))
        self.assertEqual(splits[self.bob.id], Decimal('100.00'))
        self.assertEqual(sum(splits.values()), Decimal('300.00'))


class ExpenseListDetailTest(TestCase):
    """GET /expenses/ and GET /expenses/<id>/."""

    def setUp(self):
        self.client = APIClient()
        self.alice = _make_user('alice_ld')
        self.bob = _make_user('bob_ld')
        self.group = Group.objects.create(name='List Group', created_by=self.alice)
        today = timezone.now().date()
        Membership.objects.create(user=self.alice, group=self.group, joined_on=today)
        Membership.objects.create(user=self.bob, group=self.group, joined_on=today)
        token = _get_token(self.client, 'alice_ld')
        _auth(self.client, token)
        self.url = f'/api/groups/{self.group.id}/expenses/'

        # Create one expense directly to test list/detail
        self.expense = Expense.objects.create(
            group=self.group,
            paid_by=self.alice,
            description='Existing expense',
            amount=Decimal('600.00'),
            date='2026-03-01',
            split_type='equal',
        )
        ExpenseSplit.objects.create(expense=self.expense, user=self.alice, share_amount=Decimal('300.00'))
        ExpenseSplit.objects.create(expense=self.expense, user=self.bob, share_amount=Decimal('300.00'))

    def test_list_returns_expenses(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['description'], 'Existing expense')

    def test_list_does_not_include_splits(self):
        """List serializer is lightweight — splits are omitted."""
        resp = self.client.get(self.url)
        self.assertNotIn('splits', resp.data[0])

    def test_detail_includes_splits(self):
        resp = self.client.get(f'{self.url}{self.expense.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('splits', resp.data)
        self.assertEqual(len(resp.data['splits']), 2)

    def test_detail_404_for_wrong_group(self):
        """Expense from a different group returns 404."""
        other_group = Group.objects.create(name='Other', created_by=self.alice)
        Membership.objects.create(user=self.alice, group=other_group, joined_on=timezone.now().date())
        other_expense = Expense.objects.create(
            group=other_group,
            paid_by=self.alice,
            description='Unrelated',
            amount=Decimal('100.00'),
            date='2026-03-01',
            split_type='equal',
        )
        resp = self.client.get(f'{self.url}{other_expense.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_expense_removes_splits(self):
        """DELETE must cascade to ExpenseSplit rows."""
        split_count_before = ExpenseSplit.objects.filter(expense=self.expense).count()
        self.assertEqual(split_count_before, 2)

        resp = self.client.delete(f'{self.url}{self.expense.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Expense.objects.filter(id=self.expense.id).count(), 0)
        self.assertEqual(ExpenseSplit.objects.filter(expense=self.expense).count(), 0)


class ExpenseAccessControlTest(TestCase):
    """Non-members and unauthenticated users must be rejected."""

    def setUp(self):
        self.client = APIClient()
        self.alice = _make_user('alice_ac')
        self.eve = _make_user('eve_ac')  # not a member
        self.group = Group.objects.create(name='AC Group', created_by=self.alice)
        Membership.objects.create(
            user=self.alice, group=self.group, joined_on=timezone.now().date()
        )
        self.url = f'/api/groups/{self.group.id}/expenses/'

    def test_unauthenticated_get_rejected(self):
        self.client.credentials()  # clear auth
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_post_rejected(self):
        self.client.credentials()
        resp = self.client.post(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_member_get_rejected(self):
        token = _get_token(self.client, 'eve_ac')
        _auth(self.client, token)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_member_post_rejected(self):
        token = _get_token(self.client, 'eve_ac')
        _auth(self.client, token)
        resp = self.client.post(self.url, {
            'description': 'Hack',
            'amount': '100.00',
            'date': '2026-03-01',
            'split_type': 'equal',
            'paid_by_id': self.eve.id,
            'participant_ids': [self.eve.id],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Expense.objects.count(), 0)


class ExpenseValidationTest(TestCase):
    """Input validation — bad requests must return 400 and write nothing."""

    def setUp(self):
        self.client = APIClient()
        self.alice = _make_user('alice_v')
        self.group = Group.objects.create(name='Validation Group', created_by=self.alice)
        Membership.objects.create(
            user=self.alice, group=self.group, joined_on=timezone.now().date()
        )
        token = _get_token(self.client, 'alice_v')
        _auth(self.client, token)
        self.url = f'/api/groups/{self.group.id}/expenses/'

    def _base_payload(self):
        return {
            'description': 'Test',
            'amount': '100.00',
            'date': '2026-03-01',
            'split_type': 'equal',
            'paid_by_id': self.alice.id,
            'participant_ids': [self.alice.id],
            'split_details': {},
        }

    def test_negative_amount_rejected(self):
        payload = self._base_payload()
        payload['amount'] = '-50.00'
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_zero_amount_rejected(self):
        payload = self._base_payload()
        payload['amount'] = '0.00'
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_paid_by_rejected(self):
        payload = self._base_payload()
        payload['paid_by_id'] = 999999
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_participant_rejected(self):
        payload = self._base_payload()
        payload['participant_ids'] = [self.alice.id, 999999]
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_split_type_rejected(self):
        payload = self._base_payload()
        payload['split_type'] = 'magic'
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nothing_written_on_bad_request(self):
        """Confirmed atomicity: no DB rows on any validation failure."""
        payload = self._base_payload()
        payload['amount'] = '-100.00'
        self.client.post(self.url, payload, format='json')
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(ExpenseSplit.objects.count(), 0)
