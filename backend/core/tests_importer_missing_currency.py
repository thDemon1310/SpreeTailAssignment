"""
Tests for missing currency detection in the CSV importer.

Detection: blank currency field.
Policy: default to INR, but log a visible auto_resolved anomaly.
CSV row: Row 28 (Groceries DMart 2026-03-15)

Run with:
    python manage.py test core.tests_importer_missing_currency --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_missing_currency, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectMissingCurrencyUnitTest(TestCase):
    def test_present_currency_not_flagged(self):
        row = {'currency': 'USD'}
        spec = detect_missing_currency(row)
        self.assertIsNone(spec)

    def test_missing_currency_flagged(self):
        row = {'currency': ''}
        spec = detect_missing_currency(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'missing_currency')
        self.assertEqual(spec.status, 'auto_resolved')
        self.assertIn('INR', spec.action_taken)


class MissingCurrencyIntegrationTest(TestCase):
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

    def test_expense_created_with_default_inr(self):
        path = self._csv(
            '2026-03-15,Groceries DMart,Priya,2105.0,,equal,Aisha;Rohan;Priya,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expense = Expense.objects.get(description='Groceries DMart')
        self.assertEqual(expense.currency, 'INR')
        self.assertEqual(expense.amount, Decimal('2105.00'))

    def test_anomaly_logged_for_missing_currency(self):
        path = self._csv(
            '2026-03-15,Groceries DMart,Priya,2105.0,,equal,Aisha;Rohan;Priya,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        anomaly = ImportAnomaly.objects.filter(problem_type='missing_currency').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')
        self.assertIn('INR', anomaly.action_taken)
