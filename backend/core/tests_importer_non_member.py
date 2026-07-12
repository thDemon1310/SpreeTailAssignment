"""
Tests for non-member detection in the CSV importer.

Detection: any name in split_with that doesn't resolve to a known member.
Policy: exclude non-member share, redistribute among resolved members (Phase 3 Task 8).
CSV row: Row 23 — Parasailing (includes "Dev's friend Kabir")

Run with:
    python manage.py test core.tests_importer_non_member --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_non_member, run_import
from core.models import Expense, ExpenseSplit, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectNonMemberUnitTest(TestCase):
    def setUp(self):
        self.aisha = User(username='Aisha')
        self.dev = User(username='Dev')
        self.name_to_user = {
            'aisha': self.aisha,
            'dev': self.dev
        }
        self.all_time_ids = {self.aisha.pk, self.dev.pk}

    def test_all_members_resolved(self):
        row = {'split_with': 'Aisha; Dev'}
        resolved, unresolved, spec = detect_non_member(row, self.name_to_user, self.all_time_ids)
        self.assertEqual(len(resolved), 2)
        self.assertEqual(len(unresolved), 0)
        self.assertIsNone(spec)

    def test_unresolved_member_flagged(self):
        row = {'split_with': 'Aisha; Dev; Dev\'s friend Kabir'}
        resolved, unresolved, spec = detect_non_member(row, self.name_to_user, self.all_time_ids)
        self.assertEqual(len(resolved), 2)
        self.assertEqual(len(unresolved), 1)
        self.assertIn("Dev's friend Kabir", unresolved)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.problem_type, 'non_member')
        self.assertEqual(spec.status, 'auto_resolved')
        self.assertIn("Dev's friend Kabir", spec.detected_value)


class NonMemberIntegrationTest(TestCase):
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

    def test_unresolved_name_omitted_from_splits_and_redistributed(self):
        # 4 members + 1 non-member, split equal. Total = 100.
        # Should redistribute 100 equally among 4 valid members = 25 each.
        path = self._csv(
            '2026-03-11,Parasailing,Dev,100.0,INR,equal,Aisha;Rohan;Priya;Dev;Kabir,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expense = Expense.objects.get(description='Parasailing')
        splits = expense.splits.all()
        self.assertEqual(splits.count(), 4)
        
        for split in splits:
            self.assertEqual(split.share_amount, Decimal('25.00'))

    def test_anomaly_logged_for_non_member(self):
        path = self._csv(
            '2026-03-11,Parasailing,Dev,100.0,INR,equal,Aisha;Rohan;Priya;Dev;Kabir,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        anomaly = ImportAnomaly.objects.filter(problem_type='non_member').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')
        self.assertIn('Kabir', anomaly.detected_value)
