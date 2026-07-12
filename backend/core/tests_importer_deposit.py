"""
Tests for deposit/transfer detection (now consolidated into settlement_as_expense).

Detection:
Uses the settlement rule's 2-of-3 fallback.
If description matches settlement/deposit keywords AND split_with has 1 name,
but split_type is not blank, it scores 2/3 and gets blocked as settlement_as_expense.
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_settlement, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectDepositUnitTest(TestCase):
    def test_deposit_with_single_person_flagged(self):
        row = {
            'split_type': 'equal',
            'split_with': 'Sam',
            'description': 'Sam deposit share for moving in'
        }
        spec = detect_settlement(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'settlement_as_expense')
        self.assertEqual(spec.status, 'blocked')
        self.assertIn('Sam deposit share', spec.detected_value)

    def test_deposit_with_multiple_people_not_flagged(self):
        row = {
            'split_type': 'equal',
            'split_with': 'Aisha; Sam',
            'description': 'deposit share for moving in'
        }
        spec = detect_settlement(row)
        # Score is 1 (desc match only). 1/3 does not trigger.
        self.assertIsNone(spec)

    def test_non_deposit_description_not_flagged(self):
        row = {
            'split_type': 'equal',
            'split_with': 'Sam',
            'description': 'Groceries'
        }
        spec = detect_settlement(row)
        # Score is 1 (single recipient only). 1/3 does not trigger.
        self.assertIsNone(spec)

    def test_blank_split_type_auto_resolved(self):
        row = {
            'split_type': '',
            'split_with': 'Sam',
            'description': 'Sam deposit share'
        }
        spec = detect_settlement(row)
        # Score 3/3 -> auto_resolved to settlement
        self.assertIsNotNone(spec)
        self.assertEqual(spec.status, 'auto_resolved')


class DepositIntegrationTest(TestCase):
    def setUp(self):
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass1234!')
        self.sam = User.objects.create_user(username='Sam', email='s@t.com', password='pass1234!')
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        today = timezone.now().date()
        for u in [self.aisha, self.sam]:
            Membership.objects.create(user=u, group=self.group, joined_on=today)

    def _csv(self, rows):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        f.write('date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n')
        f.write(rows)
        f.close()
        return f.name

    def test_deposit_blocked_and_anomaly_logged(self):
        path = self._csv(
            '2026-04-08,Sam deposit share,Aisha,5000.0,INR,equal,Sam,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expenses = Expense.objects.all()
        self.assertEqual(expenses.count(), 0)

        anomaly = ImportAnomaly.objects.filter(problem_type='settlement_as_expense').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')
        self.assertIn('Sam deposit share', anomaly.detected_value)
