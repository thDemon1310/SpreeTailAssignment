"""
Tests for percentage-sum detection in the CSV importer.

Detection: sum split_details percentages; compare to 100 ± 0.01.
Policy: normalize proportionally, flag loudly. Both raw and normalized stored in anomaly.
CSV row: Row 15 — Pizza Friday, 30+30+30+20=110% (sums to 110, not 100).
CSV row: Row 32 — Weekend brunch, 30+30+30+20=110% (same issue).

Run with:
    python manage.py test core.tests_importer_percentage --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_percentage_sum, run_import
from core.models import Expense, ExpenseSplit, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectPercentageSumUnitTest(TestCase):
    def test_110_percent_flagged(self):
        row = {
            'split_type': 'percentage',
            'split_details': 'Aisha 30%; Rohan 30%; Priya 30%; Meera 20%',
        }
        normalized, spec = detect_percentage_sum(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'percentage_sum')
        self.assertEqual(spec.status, 'auto_resolved')

    def test_100_percent_not_flagged(self):
        row = {
            'split_type': 'percentage',
            'split_details': 'Aisha 25%; Rohan 25%; Priya 25%; Meera 25%',
        }
        normalized, spec = detect_percentage_sum(row)
        self.assertIsNone(spec)
        self.assertIsNone(normalized)

    def test_non_percentage_split_type_not_checked(self):
        row = {
            'split_type': 'equal',
            'split_details': 'Aisha 30%; Rohan 70%',
        }
        normalized, spec = detect_percentage_sum(row)
        self.assertIsNone(spec)

    def test_normalized_percentages_sum_to_100(self):
        row = {
            'split_type': 'percentage',
            'split_details': 'Aisha 30%; Rohan 30%; Priya 30%; Meera 20%',
        }
        normalized, _ = detect_percentage_sum(row)
        total = sum(v for _, v in normalized)
        self.assertAlmostEqual(float(total), 100.0, places=4)

    def test_raw_sum_in_detected_value(self):
        row = {
            'split_type': 'percentage',
            'split_details': 'Aisha 30%; Rohan 30%; Priya 30%; Meera 20%',
        }
        _, spec = detect_percentage_sum(row)
        self.assertIn('110', spec.detected_value)

    def test_within_tolerance_not_flagged(self):
        """100.005% is within ±0.01 tolerance."""
        row = {
            'split_type': 'percentage',
            'split_details': 'Aisha 50%; Rohan 50.005%',
        }
        normalized, spec = detect_percentage_sum(row)
        self.assertIsNone(spec)


class PercentageSumIntegrationTest(TestCase):
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

    def test_expense_created_with_normalized_percentages(self):
        """Expense created despite 110% — normalized proportionally."""
        path = self._csv(
            '2026-02-28,Pizza Friday,Aisha,1440.0,INR,percentage,'
            'Aisha;Rohan;Priya;Meera,Aisha 30%; Rohan 30%; Priya 30%; Meera 20%,percentages off\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        self.assertEqual(Expense.objects.count(), 1)

    def test_splits_sum_to_total(self):
        """After normalization splits must still sum to the expense total."""
        path = self._csv(
            '2026-02-28,Pizza Friday,Aisha,1440.0,INR,percentage,'
            'Aisha;Rohan;Priya;Meera,Aisha 30%; Rohan 30%; Priya 30%; Meera 20%,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        expense = Expense.objects.first()
        total = sum(s.share_amount for s in expense.splits.all())
        self.assertEqual(total, Decimal('1440.00'))

    def test_anomaly_logged_with_raw_sum(self):
        path = self._csv(
            '2026-02-28,Pizza Friday,Aisha,1440.0,INR,percentage,'
            'Aisha;Rohan;Priya;Meera,Aisha 30%; Rohan 30%; Priya 30%; Meera 20%,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)
        anomaly = ImportAnomaly.objects.filter(problem_type='percentage_sum').first()
        self.assertIsNotNone(anomaly)
        self.assertIn('110', anomaly.detected_value)
