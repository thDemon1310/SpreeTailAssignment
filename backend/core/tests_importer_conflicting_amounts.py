"""
Tests for conflicting amounts from different loggers in the CSV importer.

Detection: same date + similar description (fuzzy match) + different payer + different amount.
Policy: Both rows imported as separate expenses, but flagged as a linked pair in ImportAnomaly.
CSV rows: 24 ("Dinner at Thalassa", Aisha/2400) vs 25 ("Thalassa dinner", Rohan/2450)

Run with:
    python manage.py test core.tests_importer_conflicting_amounts --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_conflicting_amounts, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectConflictingAmountsUnitTest(TestCase):
    def test_different_amount_and_payer_flagged(self):
        seen_fuzzy = {}
        row1 = {
            'date': '2026-03-11',
            'description': 'Dinner at Thalassa',
            'paid_by': 'Aisha',
            'amount': '2400.0'
        }
        spec1 = detect_conflicting_amounts(row1, seen_fuzzy, 24)
        self.assertIsNone(spec1)
        self.assertEqual(len(seen_fuzzy), 1)

        row2 = {
            'date': '2026-03-11',
            'description': 'Thalassa dinner',
            'paid_by': 'Rohan',
            'amount': '2450.0'
        }
        spec2 = detect_conflicting_amounts(row2, seen_fuzzy, 25)
        self.assertIsNotNone(spec2)
        self.assertEqual(spec2.problem_type, 'conflicting_amounts')
        self.assertEqual(spec2.status, 'blocked')
        self.assertIn('aisha', spec2.detected_value)
        self.assertIn('2400', spec2.detected_value)
        self.assertIn('rohan', spec2.detected_value)
        self.assertIn('2450', spec2.detected_value)

    def test_same_amount_and_payer_not_flagged(self):
        # This is an exact duplicate, which should be caught by duplicate check,
        # but here we ensure detect_conflicting_amounts doesn't flag it as conflicting.
        seen_fuzzy = {}
        row1 = {
            'date': '2026-03-11',
            'description': 'Dinner at Thalassa',
            'paid_by': 'Aisha',
            'amount': '2400.0'
        }
        detect_conflicting_amounts(row1, seen_fuzzy, 24)
        
        row2 = {
            'date': '2026-03-11',
            'description': 'Dinner at Thalassa',
            'paid_by': 'Aisha',
            'amount': '2400.0'
        }
        spec2 = detect_conflicting_amounts(row2, seen_fuzzy, 25)
        self.assertIsNone(spec2)


class ConflictingAmountsIntegrationTest(TestCase):
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

    def test_both_rows_imported_and_flagged(self):
        path = self._csv(
            '2026-03-11,Dinner at Thalassa,Aisha,2400.0,INR,equal,Aisha;Rohan;Priya;Dev,,\n'
            '2026-03-11,Thalassa dinner,Rohan,2450.0,INR,equal,Aisha;Rohan;Priya;Dev,,Aisha also logged this\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        # Both expenses should be created
        expenses = Expense.objects.all().order_by('id')
        self.assertEqual(expenses.count(), 2)
        
        self.assertEqual(expenses[0].amount, Decimal('2400.00'))
        self.assertEqual(expenses[0].paid_by, self.aisha)
        
        self.assertEqual(expenses[1].amount, Decimal('2450.00'))
        self.assertEqual(expenses[1].paid_by, self.rohan)

        # One anomaly should be created for the second row flagging the conflict
        anomaly = ImportAnomaly.objects.filter(problem_type='conflicting_amounts').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')
        self.assertIn('aisha', anomaly.detected_value)
        self.assertIn('2400', anomaly.detected_value)
