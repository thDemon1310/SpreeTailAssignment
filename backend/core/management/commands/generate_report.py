import json
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.importer import run_import
from core.models import Group, ImportAnomaly, Membership
import datetime

User = get_user_model()

class Command(BaseCommand):
    help = 'Runs the CSV importer and generates a markdown report'

    def handle(self, *args, **options):
        # Setup data
        aisha, _ = User.objects.get_or_create(username='Aisha', defaults={'email': 'a@t.com', 'password': 'pass'})
        rohan, _ = User.objects.get_or_create(username='Rohan', defaults={'email': 'r@t.com', 'password': 'pass'})
        priya, _ = User.objects.get_or_create(username='Priya', defaults={'email': 'p@t.com', 'password': 'pass'})
        dev, _ = User.objects.get_or_create(username='Dev', defaults={'email': 'd@t.com', 'password': 'pass'})
        meera, _ = User.objects.get_or_create(username='Meera', defaults={'email': 'm@t.com', 'password': 'pass'})
        sam, _ = User.objects.get_or_create(username='Sam', defaults={'email': 's@t.com', 'password': 'pass'})
        
        group, _ = Group.objects.get_or_create(name='Test Flat', defaults={'created_by': aisha})
        
        today = datetime.date(2026, 1, 1) # join date before all expenses
        Membership.objects.get_or_create(user=aisha, group=group, defaults={'joined_on': today})
        Membership.objects.get_or_create(user=rohan, group=group, defaults={'joined_on': today})
        Membership.objects.get_or_create(user=priya, group=group, defaults={'joined_on': today})
        Membership.objects.get_or_create(user=dev, group=group, defaults={'joined_on': today})
        Membership.objects.get_or_create(user=meera, group=group, defaults={'joined_on': today, 'left_on': datetime.date(2026, 3, 31)})
        Membership.objects.get_or_create(user=sam, group=group, defaults={'joined_on': datetime.date(2026, 4, 1)})

        csv_path = 'data/expenses_export.csv'
        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f"File not found: {csv_path}"))
            return

        result = run_import(csv_path, group, aisha)
        
        # Generate markdown report
        report = []
        report.append("# Import Report")
        report.append(f"**File:** {csv_path}")
        report.append(f"**Total rows processed:** {result.batch.total_rows}")
        report.append(f"**Rows successfully imported (or auto-resolved):** {result.batch.imported_rows}")
        report.append(f"**Rows with anomalies:** {result.batch.anomaly_rows}")
        report.append("\n## Anomalies")
        
        anomalies = ImportAnomaly.objects.filter(batch=result.batch).order_by('row_number', 'id')
        
        for a in anomalies:
            report.append(f"### Row {a.row_number}: {a.problem_type} ({a.status})")
            report.append(f"- **Detection Method:** {a.detection_method}")
            report.append(f"- **Detected Value:** {a.detected_value}")
            report.append(f"- **Action Taken:** {a.action_taken}")
            # Try parsing raw data for display
            try:
                raw = json.loads(a.raw_data)
                raw_str = ', '.join([f"{k}: {v}" for k, v in raw.items() if v])
                report.append(f"- **Raw Row:** `{raw_str}`")
            except Exception:
                pass
            report.append("")

        with open('ImportReport.md', 'w') as f:
            f.write('\n'.join(report))
            
        self.stdout.write(self.style.SUCCESS("Generated ImportReport.md"))
