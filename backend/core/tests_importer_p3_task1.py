"""
Tests for the CSV import pipeline — exact duplicate detection (Phase 3 Task 1).

Run with:
    python manage.py test core.tests_importer_p3_task1 --verbosity=2

Tests cover:
 - build_dup_hash produces same hash for case/punctuation variants
 - detect_exact_duplicate fires on second occurrence, not first
 - Integration: run_import marks duplicate row as skipped, logs anomaly
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import (
    build_dup_hash,
    normalize_description,
    normalize_name,
    detect_exact_duplicate,
    AnomalySpec,
)
from core.models import Group, Membership, ImportAnomaly, Expense
from django.contrib.auth import get_user_model

User = get_user_model()


class DupHashUnitTest(TestCase):
    """Unit tests for build_dup_hash — pure function, no DB."""

    def test_same_inputs_produce_same_hash(self):
        h1 = build_dup_hash('2026-02-08', '3200.0', 'Dev', 'Dinner at Marina Bites')
        h2 = build_dup_hash('2026-02-08', '3200.0', 'Dev', 'Dinner at Marina Bites')
        self.assertEqual(h1, h2)

    def test_description_case_insensitive(self):
        """
        normalize_description strips stopwords + punctuation, so:
        'Dinner at Marina Bites'  -> 'dinner marina bites'  ('at' is a stopword)
        'dinner - marina bites'   -> 'dinner marina bites'  (hyphen stripped, 'at' absent)
        Both produce the same hash.
        """
        h1 = build_dup_hash('2026-02-08', '3200.0', 'Dev', 'Dinner at Marina Bites')
        h2 = build_dup_hash('2026-02-08', '3200.0', 'Dev', 'dinner - marina bites')
        self.assertEqual(h1, h2)

    def test_payer_case_insensitive(self):
        h1 = build_dup_hash('2026-02-08', '3200.0', 'Dev', 'Dinner')
        h2 = build_dup_hash('2026-02-08', '3200.0', 'dev', 'Dinner')
        self.assertEqual(h1, h2)

    def test_payer_whitespace_stripped(self):
        h1 = build_dup_hash('2026-02-08', '3200.0', 'rohan ', 'Airport cab')
        h2 = build_dup_hash('2026-02-08', '3200.0', 'rohan', 'Airport cab')
        self.assertEqual(h1, h2)

    def test_different_amount_produces_different_hash(self):
        h1 = build_dup_hash('2026-03-11', '2400.0', 'Aisha', 'Dinner at Thalassa')
        h2 = build_dup_hash('2026-03-11', '2450.0', 'Rohan', 'Thalassa dinner')
        # Different amounts AND different payers AND different descriptions → different hash
        self.assertNotEqual(h1, h2)

    def test_normalize_description_strips_punctuation_and_stopwords(self):
        """
        'Dinner at Marina Bites' normalizes to 'dinner marina bites'
        (casefold, punctuation stripped, stopword 'at' removed).
        'dinner  marina bites' normalizes to 'dinner marina bites' too.
        """
        self.assertEqual(
            normalize_description('Dinner at Marina Bites'),
            'dinner marina bites',
        )
        self.assertEqual(
            normalize_description('dinner - marina bites'),
            'dinner marina bites',
        )

    def test_normalize_name(self):
        self.assertEqual(normalize_name('Priya S'), 'priya s')
        self.assertEqual(normalize_name('rohan '), 'rohan')


class DetectExactDuplicateUnitTest(TestCase):
    """Unit tests for detect_exact_duplicate — pure function using seen_hashes dict."""

    def test_first_occurrence_not_flagged(self):
        seen = {}
        row = {'date': '2026-02-08', 'amount': '3200.0', 'paid_by': 'Dev', 'description': 'Dinner at Marina Bites'}
        result = detect_exact_duplicate(row, seen)
        self.assertIsNone(result)
        # detect_exact_duplicate is now READ-ONLY; run_import registers the hash
        self.assertEqual(len(seen), 0)

    def test_second_occurrence_flagged(self):
        row1 = {'date': '2026-02-08', 'amount': '3200.0', 'paid_by': 'Dev', 'description': 'Dinner at Marina Bites'}
        row2 = {'date': '2026-02-08', 'amount': '3200.0', 'paid_by': 'Dev', 'description': 'dinner - marina bites'}

        # Simulate run_import registering the first row's hash
        seen_hashes = {}
        h = build_dup_hash(row1['date'], row1['amount'], row1['paid_by'], row1['description'])
        seen_hashes[h] = 5  # first row number

        # Detect second — should fire because hashes match
        result = detect_exact_duplicate(row2, seen_hashes)
        self.assertIsInstance(result, AnomalySpec)
        self.assertEqual(result.problem_type, 'exact_duplicate')
        self.assertEqual(result.status, 'auto_resolved')
        self.assertIn('dropped', result.action_taken)

    def test_conflicting_amounts_not_flagged_as_duplicate(self):
        """Thalassa rows: same date, similar description, BUT different payer AND different amount — different hash."""
        seen = {}
        row1 = {'date': '2026-03-11', 'amount': '2400.0', 'paid_by': 'Aisha', 'description': 'Dinner at Thalassa'}
        row2 = {'date': '2026-03-11', 'amount': '2450.0', 'paid_by': 'Rohan', 'description': 'Thalassa dinner'}

        seen_hashes = {}
        h1 = build_dup_hash(row1['date'], row1['amount'], row1['paid_by'], row1['description'])
        seen_hashes[h1] = 24

        result = detect_exact_duplicate(row2, seen_hashes)
        self.assertIsNone(result)  # NOT a duplicate — different payer+amount


class ExactDuplicateIntegrationTest(TestCase):
    """
    Integration test: run_import on a small in-memory CSV fixture containing
    the exact duplicate pair from the real CSV (rows 5 and 6).

    Uses a real DB (TestCase) but writes a temp CSV file.
    """

    def setUp(self):
        import os, tempfile
        self.dev = User.objects.create_user(username='Dev', email='dev@test.com', password='pass1234!')
        self.aisha = User.objects.create_user(username='Aisha', email='aisha@test.com', password='pass1234!')
        self.rohan = User.objects.create_user(username='Rohan', email='rohan@test.com', password='pass1234!')
        self.priya = User.objects.create_user(username='Priya', email='priya@test.com', password='pass1234!')
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        today = timezone.now().date()
        for user in [self.dev, self.aisha, self.rohan, self.priya]:
            Membership.objects.create(user=user, group=self.group, joined_on=today)

        # Write a tiny CSV with just the duplicate pair
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8'
        )
        self.tmpfile.write(
            'date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n'
            '2026-02-08,Dinner at Marina Bites,Dev,3200.0,INR,equal,Aisha;Rohan;Priya;Dev,,Dev visiting\n'
            '2026-02-08,dinner - marina bites,Dev,3200.0,INR,equal,Aisha;Rohan;Priya;Dev,,\n'
        )
        self.tmpfile.close()
        self.csv_path = self.tmpfile.name

    def tearDown(self):
        import os
        os.unlink(self.csv_path)

    def test_only_one_expense_created(self):
        """Two duplicate rows → one Expense written, one skipped."""
        from core.importer import run_import
        result = run_import(self.csv_path, self.group, self.aisha)

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.imported_rows, 1)
        self.assertEqual(Expense.objects.count(), 1)

    def test_duplicate_anomaly_logged(self):
        """The skipped row must produce an ImportAnomaly with problem_type=exact_duplicate."""
        from core.importer import run_import
        run_import(self.csv_path, self.group, self.aisha)

        anomalies = ImportAnomaly.objects.filter(problem_type='exact_duplicate')
        self.assertEqual(anomalies.count(), 1)
        anomaly = anomalies.first()
        self.assertEqual(anomaly.status, 'auto_resolved')
        self.assertIn('dropped', anomaly.action_taken)
        self.assertEqual(anomaly.row_number, 2)  # second row (1-indexed in our CSV)

    def test_first_row_kept_not_second(self):
        """The kept expense should match the first row's description."""
        from core.importer import run_import
        run_import(self.csv_path, self.group, self.aisha)

        expense = Expense.objects.first()
        self.assertEqual(expense.description, 'Dinner at Marina Bites')  # first row

    def test_splits_written_for_kept_row(self):
        """ExpenseSplit rows created for the kept expense."""
        from core.importer import run_import
        from core.models import ExpenseSplit
        run_import(self.csv_path, self.group, self.aisha)

        expense = Expense.objects.first()
        self.assertEqual(expense.splits.count(), 4)  # 4 participants
        self.assertEqual(
            sum(s.share_amount for s in expense.splits.all()),
            Decimal('3200.00'),
        )
