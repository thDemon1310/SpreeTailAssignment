"""
Tests for corrupted/implausible dates in the CSV importer.

Detection: date outside a defined sane window (e.g. Feb 2026–Jun 2026).
Policy: row blocked, raw date kept, excluded from balance calc.
CSV row: Row 27 (Airport cab, 2014-03-01)

Run with:
    python manage.py test core.tests_importer_bad_date --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_bad_date, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectBadDateUnitTest(TestCase):
    def test_sane_date_not_flagged(self):
        row = {'date': '2026-03-01'}
        spec = detect_bad_date(row)
        self.assertIsNone(spec)

    def test_invalid_format_flagged(self):
        row = {'date': 'not-a-date'}
        spec = detect_bad_date(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'bad_date')
        self.assertEqual(spec.status, 'blocked')
        self.assertIn('not-a-date', spec.detected_value)

    def test_implausible_date_flagged(self):
        row = {'date': '2014-03-01'}
        spec = detect_bad_date(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'bad_date')
        self.assertEqual(spec.status, 'blocked')
        self.assertIn('2014-03-01', spec.detected_value)


class BadDateIntegrationTest(TestCase):
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

    def test_bad_date_row_blocked_not_imported(self):
        path = self._csv(
            '2014-03-01,Airport cab,rohan,1100.0,INR,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expenses = Expense.objects.all()
        self.assertEqual(expenses.count(), 0)

        anomaly = ImportAnomaly.objects.filter(problem_type='bad_date').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')
        self.assertIn('2014-03-01', anomaly.detected_value)
