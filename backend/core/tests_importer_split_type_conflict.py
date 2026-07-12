"""
Tests for split_type conflict detection in the CSV importer.

Detection: split_type == 'equal' AND split_details is non-empty.
Policy: split_details wins (explicit numbers override the label).
CSV row: Row 32 (Furniture for common room, 2026-04-18, equal but has explicit details)

Run with:
    python manage.py test core.tests_importer_split_type_conflict --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_split_type_conflict, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectSplitTypeConflictUnitTest(TestCase):
    def test_equal_no_details_not_flagged(self):
        row = {'split_type': 'equal', 'split_details': ''}
        spec = detect_split_type_conflict(row)
        self.assertIsNone(spec)

    def test_unequal_with_details_not_flagged(self):
        row = {'split_type': 'unequal', 'split_details': 'Aisha 100; Rohan 200'}
        spec = detect_split_type_conflict(row)
        self.assertIsNone(spec)

    def test_equal_with_details_flagged(self):
        row = {'split_type': 'equal', 'split_details': 'Aisha 1000; Rohan 2000'}
        spec = detect_split_type_conflict(row)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'split_type_conflict')
        self.assertEqual(spec.status, 'auto_resolved')
        self.assertIn('Aisha 1000; Rohan 2000', spec.detected_value)


class SplitTypeConflictIntegrationTest(TestCase):
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

    def test_split_details_wins_and_is_applied(self):
        # 3000 total. split_type says equal, but details say Aisha 1000, Rohan 2000
        path = self._csv(
            '2026-04-18,Furniture for common room,Aisha,3000.0,INR,equal,Aisha;Rohan,Aisha 1000; Rohan 2000,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expense = Expense.objects.get(description='Furniture for common room')
        self.assertEqual(expense.split_type, 'shares')
        
        splits = list(expense.splits.all())
        self.assertEqual(len(splits), 2)
        
        aisha_split = next(s for s in splits if s.user == self.aisha)
        rohan_split = next(s for s in splits if s.user == self.rohan)
        
        self.assertEqual(aisha_split.share_amount, Decimal('1000.00'))
        self.assertEqual(rohan_split.share_amount, Decimal('2000.00'))

    def test_anomaly_logged_for_conflict(self):
        path = self._csv(
            '2026-04-18,Furniture for common room,Aisha,3000.0,INR,equal,Aisha;Rohan,Aisha 1000; Rohan 2000,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        anomaly = ImportAnomaly.objects.filter(problem_type='split_type_conflict').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')
        self.assertIn('Aisha 1000; Rohan 2000', anomaly.detected_value)
