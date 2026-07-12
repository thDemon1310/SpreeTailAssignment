"""
Tests for negative amounts (refunds) in the CSV importer.

Detection: amount < 0.
Policy: treat as refund — preserve negative sign in Expense.amount and splits.
CSV row: Row 26 (Parasailing refund, -30 USD)

Run with:
    python manage.py test core.tests_importer_negative --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_negative_amount, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectNegativeAmountUnitTest(TestCase):
    def test_positive_amount_not_flagged(self):
        row = {'amount': '150.0'}
        spec = detect_negative_amount(row)
        self.assertIsNone(spec)

    def test_negative_amount_flagged(self):
        row = {'amount': '-30.0'}
        spec = detect_negative_amount(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'negative_amount')
        self.assertEqual(spec.status, 'auto_resolved')
        self.assertIn('-30.0', spec.detected_value)


class NegativeAmountIntegrationTest(TestCase):
    def setUp(self):
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass1234!')
        self.rohan = User.objects.create_user(username='Rohan', email='r@t.com', password='pass1234!')
        self.priya = User.objects.create_user(username='Priya', email='p@t.com', password='pass1234!')
        self.dev = User.objects.create_user(username='Dev', email='d@t.com', password='pass1234!')
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        today = timezone.now().date()
        for u in [self.aisha, self.rohan, self.priya, self.dev]:
            Membership.objects.create(user=u, group=self.group, joined_on=today)

    def _csv(self, rows):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        f.write('date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n')
        f.write(rows)
        f.close()
        return f.name

    def test_expense_created_with_negative_amount(self):
        # 30 USD * 83.50 = 2505 INR.
        # It should be -2505.00
        path = self._csv(
            '2026-03-12,Parasailing refund,Dev,-30.0,USD,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expense = Expense.objects.get(description='Parasailing refund')
        self.assertEqual(expense.amount, Decimal('-2505.00'))
        
        splits = expense.splits.all()
        self.assertEqual(splits.count(), 4)
        for split in splits:
            # -2505 / 4 = -626.25
            self.assertEqual(split.share_amount, Decimal('-626.25'))

    def test_anomaly_logged_for_negative_amount(self):
        path = self._csv(
            '2026-03-12,Parasailing refund,Dev,-30.0,USD,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        anomaly = ImportAnomaly.objects.filter(problem_type='negative_amount').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')
        self.assertIn('-30.0', anomaly.detected_value)
