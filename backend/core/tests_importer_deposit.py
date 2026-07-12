"""
Tests for deposit/transfer detection in the CSV importer.

Detection: split_type non-blank AND split_with has exactly one name AND description matches DEPOSIT_RE.
Policy: flag as blocked, no Expense written.
CSV row: Row 33 (Sam deposit share, 2026-04-08, single-person split_with)

Run with:
    python manage.py test core.tests_importer_deposit --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_deposit_not_expense, run_import
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
        spec = detect_deposit_not_expense(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'deposit_not_expense')
        self.assertEqual(spec.status, 'blocked')
        self.assertIn('Sam', spec.detected_value)

    def test_deposit_with_multiple_people_not_flagged(self):
        row = {
            'split_type': 'equal',
            'split_with': 'Aisha; Sam',
            'description': 'deposit share for moving in'
        }
        spec = detect_deposit_not_expense(row)
        self.assertIsNone(spec)

    def test_non_deposit_description_not_flagged(self):
        row = {
            'split_type': 'equal',
            'split_with': 'Sam',
            'description': 'Groceries'
        }
        spec = detect_deposit_not_expense(row)
        self.assertIsNone(spec)

    def test_blank_split_type_not_flagged_by_this_rule(self):
        # Blank split type is handled by settlement rule
        row = {
            'split_type': '',
            'split_with': 'Sam',
            'description': 'Sam deposit share'
        }
        spec = detect_deposit_not_expense(row)
        self.assertIsNone(spec)


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

        anomaly = ImportAnomaly.objects.filter(problem_type='deposit_not_expense').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')
        self.assertIn('Sam deposit share', anomaly.detected_value)
