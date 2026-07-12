"""
Tests for foreign currency detection and conversion in the CSV importer.

Detection: currency field != 'INR'.
Policy: convert USD→INR at fixed rate 1 USD = 83.50 INR (DECISIONS.md [2026-07-11]).
Store: original_amount, exchange_rate, currency, converted amount on Expense row.
CSV rows: 20 (Goa villa 540 USD), 21 (Beach shack 84 USD), 23 (Parasailing 150 USD),
          26 (Parasailing refund -30 USD — negative, so treated as refund first).

Run with:
    python manage.py test core.tests_importer_fx --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import USD_TO_INR, detect_foreign_currency, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectForeignCurrencyUnitTest(TestCase):
    def test_inr_not_flagged(self):
        self.assertIsNone(detect_foreign_currency({'currency': 'INR', 'amount': '1000'}))

    def test_usd_flagged(self):
        result = detect_foreign_currency({'currency': 'USD', 'amount': '540.0'})
        self.assertIsNotNone(result)
        self.assertEqual(result.problem_type, 'foreign_currency')
        self.assertEqual(result.status, 'auto_resolved')

    def test_converted_amount_correct(self):
        """540 USD × 83.50 = 45090.00 INR."""
        result = detect_foreign_currency({'currency': 'USD', 'amount': '540.0'})
        self.assertIn('45090.00', result.detected_value)

    def test_original_and_rate_both_in_detected_value(self):
        result = detect_foreign_currency({'currency': 'USD', 'amount': '84.0'})
        self.assertIn('84', result.detected_value)
        self.assertIn('83.50', result.detected_value)

    def test_unknown_currency_blocked(self):
        result = detect_foreign_currency({'currency': 'EUR', 'amount': '100'})
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'blocked')

    def test_lowercase_currency_handled(self):
        """currency field is uppercased by the function."""
        result = detect_foreign_currency({'currency': 'usd', 'amount': '100'})
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'auto_resolved')


class FXIntegrationTest(TestCase):
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

    def test_usd_expense_amount_converted(self):
        """540 USD → Expense.amount = 45090.00 INR."""
        path = self._csv(
            '2026-03-09,Goa villa booking,Dev,540.0,USD,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        expense = Expense.objects.get(description='Goa villa booking')
        expected = (Decimal('540.0') * USD_TO_INR).quantize(Decimal('0.01'))
        self.assertEqual(expense.amount, expected)

    def test_original_amount_stored(self):
        """Expense.original_amount must be set (not None) for USD rows."""
        path = self._csv(
            '2026-03-09,Goa villa booking,Dev,540.0,USD,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        expense = Expense.objects.get(description='Goa villa booking')
        self.assertIsNotNone(expense.original_amount)
        self.assertIsNotNone(expense.exchange_rate)

    def test_fx_anomaly_logged(self):
        path = self._csv(
            '2026-03-09,Goa villa booking,Dev,540.0,USD,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        anomaly = ImportAnomaly.objects.filter(problem_type='foreign_currency').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')

    def test_splits_sum_to_converted_amount(self):
        """Splits must sum to the INR-converted total."""
        path = self._csv(
            '2026-03-09,Goa villa booking,Dev,540.0,USD,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        expense = Expense.objects.get(description='Goa villa booking')
        split_sum = sum(s.share_amount for s in expense.splits.all())
        self.assertEqual(split_sum, expense.amount)
