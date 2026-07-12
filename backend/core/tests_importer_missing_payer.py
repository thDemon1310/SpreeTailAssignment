"""
Tests for missing paid_by detection in the CSV importer.

Detection: paid_by field is null/blank after strip().
Policy: block row entirely, no default, no guess. Full row preserved in ImportAnomaly.
CSV row: Row 13 — House cleaning supplies, 2026-02-22, blank paid_by.

Run with:
    python manage.py test core.tests_importer_missing_payer --verbosity=2
"""

import os
import tempfile

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_missing_payer, run_import
from core.models import Expense, ExpenseSplit, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectMissingPayerUnitTest(TestCase):
    def test_blank_payer_detected(self):
        result = detect_missing_payer({'paid_by': ''})
        self.assertIsNotNone(result)
        self.assertEqual(result.problem_type, 'missing_payer')
        self.assertEqual(result.status, 'blocked')

    def test_whitespace_only_payer_detected(self):
        result = detect_missing_payer({'paid_by': '   '})
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'blocked')

    def test_missing_key_detected(self):
        result = detect_missing_payer({})
        self.assertIsNotNone(result)

    def test_valid_payer_not_flagged(self):
        self.assertIsNone(detect_missing_payer({'paid_by': 'Aisha'}))

    def test_action_taken_says_blocked(self):
        result = detect_missing_payer({'paid_by': ''})
        self.assertIn('blocked', result.action_taken.lower())

    def test_never_defaults_to_anyone(self):
        """Policy: must never assign a default payer. Action text must say so."""
        result = detect_missing_payer({'paid_by': ''})
        self.assertNotIn('default', result.action_taken.lower().replace('never default', ''))


class MissingPayerIntegrationTest(TestCase):
    def setUp(self):
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass1234!')
        self.rohan = User.objects.create_user(username='Rohan', email='r@t.com', password='pass1234!')
        self.priya = User.objects.create_user(username='Priya', email='p@t.com', password='pass1234!')
        self.meera = User.objects.create_user(username='Meera', email='m@t.com', password='pass1234!')
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        today = timezone.now().date()
        for u in [self.aisha, self.rohan, self.priya, self.meera]:
            Membership.objects.create(user=u, group=self.group, joined_on=today)

    def _csv(self, rows):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        f.write('date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n')
        f.write(rows)
        f.close()
        return f.name

    def test_row_blocked_no_expense(self):
        path = self._csv('2026-02-22,House cleaning supplies,,780.0,INR,equal,Aisha;Rohan;Priya;Meera,,\n')
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(ExpenseSplit.objects.count(), 0)

    def test_anomaly_logged_blocked(self):
        path = self._csv('2026-02-22,House cleaning supplies,,780.0,INR,equal,Aisha;Rohan;Priya;Meera,,\n')
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        anomaly = ImportAnomaly.objects.filter(problem_type='missing_payer').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')

    def test_raw_data_preserved(self):
        path = self._csv('2026-02-22,House cleaning supplies,,780.0,INR,equal,Aisha;Rohan;Priya;Meera,,can\'t remember\n')
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        anomaly = ImportAnomaly.objects.filter(problem_type='missing_payer').first()
        self.assertIn('House cleaning supplies', str(anomaly.raw_data))
