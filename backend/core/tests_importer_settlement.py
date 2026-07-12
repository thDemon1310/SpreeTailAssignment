"""
Tests for settlement-as-expense detection in the CSV importer.

Detection (DECISIONS.md [2026-07-11]):
  All three: split_type blank + single recipient in split_with + description regex.
  Two-of-three: blocked for manual review (low confidence).
Policy: auto-route to Settlement table on 3/3; block on 2/3.
CSV row: Row 14 — "Rohan paid Aisha back", 2026-02-25, 5000 INR.

Run with:
    python manage.py test core.tests_importer_settlement --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_settlement, run_import
from core.models import Expense, Group, ImportAnomaly, Membership, Settlement
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectSettlementUnitTest(TestCase):
    def test_all_three_conditions_auto_resolved(self):
        row = {
            'split_type': '',
            'split_with': 'Aisha',
            'description': 'Rohan paid Aisha back',
        }
        result = detect_settlement(row)
        self.assertIsNotNone(result)
        self.assertEqual(result.problem_type, 'settlement_as_expense')
        self.assertEqual(result.status, 'auto_resolved')

    def test_two_conditions_blocked(self):
        """split_type blank + single recipient but description doesn't match → blocked."""
        row = {
            'split_type': '',
            'split_with': 'Aisha',
            'description': 'Grocery run',
        }
        result = detect_settlement(row)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'blocked')

    def test_non_blank_split_type_not_auto_resolved(self):
        """If split_type is set, settlement rule scores only 2/3 → blocked, not auto_resolved."""
        row = {
            'split_type': 'equal',
            'split_with': 'Aisha',
            'description': 'Rohan paid Aisha back',
        }
        result = detect_settlement(row)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'blocked')  # 2/3 conditions met → manual review

    def test_multiple_recipients_not_flagged(self):
        """More than one recipient → not a settlement."""
        row = {
            'split_type': '',
            'split_with': 'Aisha;Priya',
            'description': 'Rohan paid everyone back',
        }
        result = detect_settlement(row)
        # 2 of 3 conditions (blank type + desc match) → blocked, not auto_resolved
        self.assertNotEqual(result.status if result else None, 'auto_resolved')

    def test_description_regex_variants(self):
        """Various settlement description words must all fire."""
        words = ['paid', 'repaid', 'returned', 'gave', 'sent', 'back', 'settled', 'settlement']
        for word in words:
            row = {'split_type': '', 'split_with': 'Aisha', 'description': f'Rohan {word} Aisha'}
            result = detect_settlement(row)
            self.assertIsNotNone(result, f"'{word}' should trigger settlement detection")
            self.assertEqual(result.status, 'auto_resolved', f"'{word}' should be auto_resolved")

    def test_action_mentions_settlement_table(self):
        row = {'split_type': '', 'split_with': 'Aisha', 'description': 'Rohan paid Aisha back'}
        result = detect_settlement(row)
        self.assertIn('Settlement', result.action_taken)


class SettlementIntegrationTest(TestCase):
    def setUp(self):
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass1234!')
        self.rohan = User.objects.create_user(username='Rohan', email='r@t.com', password='pass1234!')
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        today = timezone.now().date()
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=today)
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=today)

    def _csv(self, rows):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        f.write('date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n')
        f.write(rows)
        f.close()
        return f.name

    def test_settlement_row_creates_settlement_not_expense(self):
        """Row 14: Rohan paid Aisha back → Settlement row, no Expense row."""
        path = self._csv(
            '2026-02-25,Rohan paid Aisha back,Rohan,5000.0,INR,,Aisha,,this is a settlement\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Settlement.objects.count(), 1)

    def test_settlement_amount_and_parties_correct(self):
        path = self._csv(
            '2026-02-25,Rohan paid Aisha back,Rohan,5000.0,INR,,Aisha,,this is a settlement\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        s = Settlement.objects.first()
        self.assertEqual(s.from_user, self.rohan)
        self.assertEqual(s.to_user, self.aisha)
        self.assertEqual(s.amount, Decimal('5000.00'))

    def test_settlement_anomaly_logged(self):
        path = self._csv(
            '2026-02-25,Rohan paid Aisha back,Rohan,5000.0,INR,,Aisha,,this is a settlement\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        anomaly = ImportAnomaly.objects.filter(problem_type='settlement_as_expense').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')
