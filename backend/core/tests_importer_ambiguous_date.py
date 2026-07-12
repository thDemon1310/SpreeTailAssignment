"""
Tests for ambiguous date format detection in the CSV importer.

Detection: date where day <= 12 AND month <= 12 AND the note field explicitly casts doubt.
Policy: exclude from balance calc pending human resolution, raw date kept.
CSV row: Row 30 (Deep cleaning service, 2026-05-04, note questions April 5 vs May 4)

Run with:
    python manage.py test core.tests_importer_ambiguous_date --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_ambiguous_date, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectAmbiguousDateUnitTest(TestCase):
    def test_unambiguous_date_not_flagged(self):
        row = {'date': '2026-05-13', 'notes': 'is this April?'}
        spec = detect_ambiguous_date(row)
        self.assertIsNone(spec)

    def test_ambiguous_date_without_note_not_flagged(self):
        row = {'date': '2026-05-04', 'notes': 'cleaning done well'}
        spec = detect_ambiguous_date(row)
        self.assertIsNone(spec)

    def test_ambiguous_date_with_note_flagged(self):
        row = {'date': '2026-05-04', 'notes': 'wait is this april 5 or may 4?'}
        spec = detect_ambiguous_date(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'ambiguous_date')
        self.assertEqual(spec.status, 'blocked')
        self.assertIn('2026-05-04', spec.detected_value)
        self.assertIn('april 5', spec.detected_value)


class AmbiguousDateIntegrationTest(TestCase):
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

    def test_ambiguous_date_blocked(self):
        path = self._csv(
            '2026-05-04,Deep cleaning service,Priya,3000.0,INR,equal,Aisha;Rohan;Priya;Dev,,is this April 5 or May 4?\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expenses = Expense.objects.all()
        self.assertEqual(expenses.count(), 0)

        anomaly = ImportAnomaly.objects.filter(problem_type='ambiguous_date').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')
        self.assertIn('2026-05-04', anomaly.detected_value)
        self.assertIn('April', anomaly.detected_value)
