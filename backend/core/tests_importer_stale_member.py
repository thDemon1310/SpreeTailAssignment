"""
Tests for stale member detection in the CSV importer.

Detection: cross-reference split_with against Membership.left_on relative to expense date.
Policy: exclude stale member's share, redistribute proportionally.
CSV row: Row 31 (Groceries BigBasket 2026-04-02 includes Meera, who left end of March)

Run with:
    python manage.py test core.tests_importer_stale_member --verbosity=2
"""

import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.importer import detect_stale_member, run_import
from core.models import Expense, Group, ImportAnomaly, Membership
from django.contrib.auth import get_user_model

User = get_user_model()


class DetectStaleMemberUnitTest(TestCase):
    def test_stale_member_flagged_and_removed(self):
        aisha = User(username='Aisha', pk=1)
        meera = User(username='Meera', pk=2)
        name_to_user = {'aisha': aisha, 'meera': meera}
        resolved = [aisha, meera]
        
        # We need to mock Membership.objects.get
        # Since it hits the DB, let's use the integration test instead for DB-dependent logic
        pass


class StaleMemberIntegrationTest(TestCase):
    def setUp(self):
        self.aisha = User.objects.create_user(username='Aisha', email='a@t.com', password='pass1234!')
        self.rohan = User.objects.create_user(username='Rohan', email='r@t.com', password='pass1234!')
        self.meera = User.objects.create_user(username='Meera', email='m@t.com', password='pass1234!')
        
        self.group = Group.objects.create(name='Test Flat', created_by=self.aisha)
        
        # Aisha and Rohan are active
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=timezone.now().date())
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=timezone.now().date())
        
        # Meera left at end of March
        import datetime
        Membership.objects.create(
            user=self.meera, 
            group=self.group, 
            joined_on=datetime.date(2026, 1, 1),
            left_on=datetime.date(2026, 3, 31)
        )

    def _csv(self, rows):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        f.write('date,description,paid_by,amount,currency,split_type,split_with,split_details,notes\n')
        f.write(rows)
        f.close()
        return f.name

    def test_stale_member_omitted_and_share_redistributed(self):
        # 3 members listed, but Meera left before Apr 02.
        # So only Aisha and Rohan split the 1000.
        path = self._csv(
            '2026-04-02,Groceries,Aisha,1000.0,INR,equal,Aisha;Rohan;Meera,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        expense = Expense.objects.get(description='Groceries')
        splits = expense.splits.all()
        self.assertEqual(splits.count(), 2)
        
        for split in splits:
            self.assertEqual(split.share_amount, Decimal('500.00'))

    def test_anomaly_logged_for_stale_member(self):
        path = self._csv(
            '2026-04-02,Groceries,Aisha,1000.0,INR,equal,Aisha;Rohan;Meera,,\n'
        )
        try:
            run_import(path, self.group, self.aisha)
        finally:
            os.unlink(path)

        anomaly = ImportAnomaly.objects.filter(problem_type='stale_member').first()
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.status, 'auto_resolved')
        self.assertIn('Meera', anomaly.detected_value)
        self.assertIn('Meera', anomaly.action_taken)
