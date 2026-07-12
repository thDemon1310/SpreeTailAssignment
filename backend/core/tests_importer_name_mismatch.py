"""
Tests for inconsistent payer name detection in the CSV importer.

Detection: normalize paid_by (strip + casefold), look up in member name table.
  - Exact match after normalization (different raw string) → auto-map, anomaly logged
  - No match even after normalization → row blocked, anomaly logged
CSV rows:
  - Row 9: paid_by="priya" → auto-maps to "Priya" (username)
  - Row 11: paid_by="Priya S" → no match → blocked
  - Row 27: paid_by="rohan " (trailing space) → auto-maps to "Rohan"

Run with:
    python manage.py test core.tests_importer_name_mismatch --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_name_mismatch, normalize_name, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


def _make_user(username, password='pass1234!'):
    return User.objects.create_user(
        username=username, email=f'{username.lower()}@t.com', password=password
    )


class DetectNameMismatchUnitTest(TestCase):
    """Unit tests for detect_name_mismatch — requires minimal DB (User objects)."""

    def setUp(self):
        self.priya = _make_user('Priya')
        self.rohan = _make_user('Rohan')
        self.name_to_user = {
            normalize_name('Priya'): self.priya,
            normalize_name('Rohan'): self.rohan,
        }

    def test_exact_match_no_anomaly(self):
        """paid_by matches username exactly → no anomaly."""
        user, spec = detect_name_mismatch({'paid_by': 'Priya'}, self.name_to_user)
        self.assertEqual(user, self.priya)
        self.assertIsNone(spec)

    def test_casefold_auto_maps(self):
        """'priya' (lowercase) → auto-maps to Priya, anomaly logged as auto_resolved."""
        user, spec = detect_name_mismatch({'paid_by': 'priya'}, self.name_to_user)
        self.assertEqual(user, self.priya)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'name_mismatch')
        self.assertEqual(spec.status, 'auto_resolved')
        self.assertIn('Priya', spec.detected_value)

    def test_trailing_space_auto_maps(self):
        """'rohan ' (trailing space) → auto-maps to Rohan."""
        user, spec = detect_name_mismatch({'paid_by': 'rohan '}, self.name_to_user)
        self.assertEqual(user, self.rohan)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.status, 'auto_resolved')

    def test_no_match_blocked(self):
        """'Priya S' doesn't match any member → user=None, status=blocked."""
        user, spec = detect_name_mismatch({'paid_by': 'Priya S'}, self.name_to_user)
        self.assertIsNone(user)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'name_mismatch')
        self.assertEqual(spec.status, 'blocked')
        self.assertIn('Priya S', spec.detected_value)

    def test_blank_payer_returns_none_none(self):
        """Blank payer is handled by detect_missing_payer, not this function."""
        user, spec = detect_name_mismatch({'paid_by': ''}, self.name_to_user)
        self.assertIsNone(user)
        self.assertIsNone(spec)

    def test_raw_name_in_detected_value(self):
        """The original raw string must appear in detected_value."""
        _, spec = detect_name_mismatch({'paid_by': 'priya'}, self.name_to_user)
        self.assertIn('priya', spec.detected_value)

    def test_matched_username_in_detected_value(self):
        """The matched canonical username must also appear in detected_value."""
        _, spec = detect_name_mismatch({'paid_by': 'priya'}, self.name_to_user)
        self.assertIn('Priya', spec.detected_value)


class NameMismatchIntegrationTest(TestCase):
    """
    Integration: run_import on CSV rows with name mismatches.
    Verifies auto-map, block, and correct Expense.paid_by FK.
    """

    def setUp(self):
        self.aisha = _make_user('Aisha')
        self.rohan = _make_user('Rohan')
        self.priya = _make_user('Priya')
        self.meera = _make_user('Meera')
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        today = timezone.now().date()
        for u in [self.aisha, self.rohan, self.priya, self.meera]:
            Membership.objects.create(user=u, group=self.group, joined_on=today)

    def _csv(self, rows: str) -> str:
        f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8'
        )
        f.write('date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n')
        f.write(rows)
        f.close()
        return f.name

    def test_lowercase_priya_auto_mapped(self):
        """'priya' → Expense.paid_by = Priya user object."""
        path = self._csv(
            '2026-02-14,Movie night snacks,priya,640.0,INR,equal,Aisha;Rohan;Priya,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expense = Expense.objects.get(description='Movie night snacks')
        self.assertEqual(expense.paid_by, self.priya)

    def test_lowercase_priya_anomaly_logged(self):
        """Auto-mapped name mismatch must produce an ImportAnomaly."""
        path = self._csv(
            '2026-02-14,Movie night snacks,priya,640.0,INR,equal,Aisha;Rohan;Priya,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        anomaly = ImportAnomaly.objects.filter(problem_type='name_mismatch').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')

    def test_priya_s_blocks_row(self):
        """'Priya S' doesn't match → row blocked, no Expense written."""
        path = self._csv(
            '2026-02-18,Groceries DMart,Priya S,1875.0,INR,equal,Aisha;Rohan;Priya;Meera,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        self.assertEqual(Expense.objects.count(), 0)
        anomaly = ImportAnomaly.objects.filter(problem_type='name_mismatch').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'blocked')

    def test_rohan_trailing_space_auto_mapped(self):
        """'rohan ' (trailing space) → Expense.paid_by = Rohan."""
        path = self._csv(
            '2026-02-15,Some expense,rohan ,500.0,INR,equal,Aisha;Rohan;Priya,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expense = Expense.objects.get(description='Some expense')
        self.assertEqual(expense.paid_by, self.rohan)

    def test_nothing_written_for_blocked_name(self):
        """Blocked row must not create any Expense or ExpenseSplit rows."""
        from core.models import ExpenseSplit
        path = self._csv(
            '2026-02-18,Groceries DMart,Priya S,1875.0,INR,equal,Aisha;Rohan;Priya;Meera,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(ExpenseSplit.objects.count(), 0)
