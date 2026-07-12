"""
Tests for non-standard precision amount detection in the CSV importer.

Detection: any amount with >2 decimal places.
Policy: round ROUND_HALF_UP, flag; both raw and rounded values stored in ImportAnomaly.
CSV row: Cylinder refill, 899.995 INR (row 10 in expenses_export.csv).

Run with:
    python manage.py test core.tests_importer_precision --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_precision, run_import
from core.models import Expense, ExpenseSplit, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectPrecisionUnitTest(TestCase):
    """Unit tests for detect_precision — pure function, no DB."""

    def test_normal_2dp_not_flagged(self):
        self.assertIsNone(detect_precision({'amount': '899.99'}))

    def test_zero_dp_not_flagged(self):
        self.assertIsNone(detect_precision({'amount': '1200.0'}))

    def test_exactly_2dp_not_flagged(self):
        self.assertIsNone(detect_precision({'amount': '48000.00'}))

    def test_3dp_flagged(self):
        """899.995 should trigger the anomaly."""
        result = detect_precision({'amount': '899.995'})
        self.assertIsNotNone(result)
        self.assertEqual(result.problem_type, 'precision')
        self.assertEqual(result.status, 'auto_resolved')

    def test_raw_and_rounded_both_in_detected_value(self):
        """Both the raw amount and the rounded amount must appear in detected_value."""
        result = detect_precision({'amount': '899.995'})
        self.assertIn('899.995', result.detected_value)
        self.assertIn('900.00', result.detected_value)  # ROUND_HALF_UP: .995 → 1.00 → 900.00

    def test_rounding_is_round_half_up(self):
        """899.995 → 900.00 (ROUND_HALF_UP), not 899.99 (truncate)."""
        result = detect_precision({'amount': '899.995'})
        self.assertIn('900.00', result.detected_value)

    def test_4dp_flagged(self):
        result = detect_precision({'amount': '100.1234'})
        self.assertIsNotNone(result)
        self.assertEqual(result.problem_type, 'precision')

    def test_blank_amount_not_flagged(self):
        """Blank amount is someone else's problem — precision check returns None."""
        self.assertIsNone(detect_precision({'amount': ''}))

    def test_action_taken_mentions_round_half_up(self):
        result = detect_precision({'amount': '899.995'})
        self.assertIn('ROUND_HALF_UP', result.action_taken)


class PrecisionIntegrationTest(TestCase):
    """
    Integration: run_import on CSV containing the Cylinder refill row (899.995).
    Verifies the Expense is created with the rounded amount AND the anomaly is logged.
    """

    def setUp(self):
        self.aisha = User.objects.create_user(username='Aisha', email='aisha@t.com', password='pass1234!')
        self.rohan = User.objects.create_user(username='Rohan', email='rohan@t.com', password='pass1234!')
        self.priya = User.objects.create_user(username='Priya', email='priya@t.com', password='pass1234!')
        self.meera = User.objects.create_user(username='Meera', email='meera@t.com', password='pass1234!')
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        today = timezone.now().date()
        for u in [self.aisha, self.rohan, self.priya, self.meera]:
            Membership.objects.create(user=u, group=self.group, joined_on=today)

        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8'
        )
        self.tmpfile.write(
            'date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n'
            '2026-02-15,Cylinder refill,Rohan,899.995,INR,equal,Aisha;Rohan;Priya;Meera,,\n'
        )
        self.tmpfile.close()
        self.csv_path = self.tmpfile.name

    def tearDown(self):
        os.unlink(self.csv_path)

    def test_expense_created_with_rounded_amount(self):
        """Expense.amount must be 900.00 (rounded), not 899.995 (raw)."""
        run_import(self.csv_path, self.group, self.aisha)
        expense = Expense.objects.get(description='Cylinder refill')
        self.assertEqual(expense.amount, Decimal('900.00'))

    def test_precision_anomaly_logged(self):
        """An ImportAnomaly with problem_type=precision must be created."""
        run_import(self.csv_path, self.group, self.aisha)
        anomaly = ImportAnomaly.objects.filter(problem_type='precision').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')

    def test_raw_value_preserved_in_anomaly(self):
        """Raw value '899.995' must appear in ImportAnomaly.detected_value."""
        run_import(self.csv_path, self.group, self.aisha)
        anomaly = ImportAnomaly.objects.filter(problem_type='precision').first()
        self.assertIn('899.995', anomaly.detected_value)

    def test_splits_sum_to_rounded_total(self):
        """Splits must sum to 900.00 (the rounded total), not 899.995."""
        run_import(self.csv_path, self.group, self.aisha)
        expense = Expense.objects.get(description='Cylinder refill')
        split_sum = sum(s.share_amount for s in expense.splits.all())
        self.assertEqual(split_sum, Decimal('900.00'))
