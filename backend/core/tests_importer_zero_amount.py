"""
Tests for zero-amount expense detection in the CSV importer.

Detection: amount == 0.
Policy: exclude from balance calc by default, flag for human confirmation, preserve the note text.
CSV row: Row 29 (Dinner order Swiggy, amount 0, "counted twice earlier - fixing later")

Run with:
    python manage.py test core.tests_importer_zero_amount --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_zero_amount, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectZeroAmountUnitTest(TestCase):
    def test_positive_amount_not_flagged(self):
        row = {'amount': '150.0'}
        spec = detect_zero_amount(row)
        self.assertIsNone(spec)

    def test_zero_amount_flagged(self):
        row = {'amount': '0.0', 'notes': 'counted twice earlier - fixing later'}
        spec = detect_zero_amount(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'zero_amount')
        self.assertEqual(spec.status, 'blocked')
        self.assertIn('amount=0', spec.detected_value)
        self.assertIn('counted twice earlier - fixing later', spec.detected_value)


class ZeroAmountIntegrationTest(TestCase):
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

    def test_zero_amount_expense_blocked_and_flagged(self):
        path = self._csv(
            '2026-03-20,Dinner order Swiggy,Aisha,0.0,INR,equal,Aisha;Rohan;Priya;Dev,,counted twice earlier - fixing later\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expenses = Expense.objects.all()
        self.assertEqual(expenses.count(), 0)

        anomaly = ImportAnomaly.objects.filter(problem_type='zero_amount').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')
        self.assertIn('amount=0', anomaly.detected_value)
        self.assertIn('counted twice earlier - fixing later', anomaly.detected_value)
