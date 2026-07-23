from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models


class User(AbstractUser):
    """
    Custom user extending Django's AbstractUser.

    Using AbstractUser (rather than the default auth.User) so we can add
    fields later without a painful migration. For now it's identical to
    Django's User — username, email, password, first_name, last_name are
    all inherited.
    """

    class Meta:
        db_table = 'core_user'
        ordering = ['username']

    def __str__(self):
        return self.username


class Group(models.Model):
    """
    A shared-expense group (e.g. "The Flat").

    Members are tracked through the Membership through-table so we can
    record join/leave dates per person. This is the key to answering
    "was X a member when this expense happened?"
    """

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_groups',
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='Membership',
        related_name='expense_groups',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_group'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Membership(models.Model):
    """
    Tracks a user's membership in a group with join/leave dates.

    This is the key table per PLAN.md — an expense only affects a member's
    balance if the expense date falls within their membership window
    (joined_on <= expense.date and (left_on is NULL or expense.date <= left_on)).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    joined_on = models.DateField()
    left_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'core_membership'
        # A user can only have one membership per group starting on a given date
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'group', 'joined_on'],
                name='unique_membership_per_group_date',
            ),
        ]
        ordering = ['joined_on']

    def __str__(self):
        status = f"left {self.left_on}" if self.left_on else "active"
        return f"{self.user.username} in {self.group.name} ({status})"

    def is_active_on(self, date):
        """Check if this membership covers a given date."""
        if date < self.joined_on:
            return False
        if self.left_on and date > self.left_on:
            return False
        return True


class Expense(models.Model):
    """
    A shared expense paid by one member.

    Stores both original and converted amounts for foreign currency rows
    (per DECISIONS.md #5). split_type drives how splits are computed;
    the actual per-person amounts are always stored in ExpenseSplit rows
    so balances are traceable to real rows (Rohan's "no magic numbers").
    """

    SPLIT_EQUAL = 'equal'
    SPLIT_UNEQUAL = 'unequal'
    SPLIT_PERCENTAGE = 'percentage'
    SPLIT_SHARES = 'shares'
    SPLIT_TYPE_CHOICES = [
        (SPLIT_EQUAL, 'Equal'),
        (SPLIT_UNEQUAL, 'Unequal'),
        (SPLIT_PERCENTAGE, 'Percentage'),
        (SPLIT_SHARES, 'Shares'),
    ]

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='expenses',
    )
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='expenses_paid',
    )
    description = models.CharField(max_length=500)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='Amount in INR (converted if original was foreign currency)',
    )
    currency = models.CharField(max_length=3, default='INR')
    original_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Original amount before FX conversion (null if already INR)',
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='FX rate used for conversion (null if INR)',
    )
    date = models.DateField()
    split_type = models.CharField(
        max_length=20,
        choices=SPLIT_TYPE_CHOICES,
        default=SPLIT_EQUAL,
    )
    is_settlement = models.BooleanField(
        default=False,
        help_text='True if this was detected as a settlement during import',
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_expense'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.description} — ₹{self.amount} by {self.paid_by.username}"


class ExpenseSplit(models.Model):
    """
    One row per person per expense — the computed per-person share.

    This is the source of truth for balances. Every balance number on screen
    must be traceable back to rows in this table. Never recompute on the fly
    for display (PLAN.md Section 2).
    """

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='splits',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='expense_splits',
    )
    share_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='This user\'s share of the expense in INR',
    )

    class Meta:
        db_table = 'core_expense_split'
        constraints = [
            models.UniqueConstraint(
                fields=['expense', 'user'],
                name='unique_split_per_user_per_expense',
            ),
        ]

    def __str__(self):
        return f"{self.user.username}: ₹{self.share_amount} of {self.expense.description}"


class Settlement(models.Model):
    """
    A payment from one user to another — separate from Expense.

    Per DECISIONS.md #4, settlements are NOT stored as expenses because
    doing so would cause them to be split among everyone, making the
    math wrong for the whole group.
    """

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='settlements',
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='settlements_made',
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='settlements_received',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_settlement'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.from_user.username} → {self.to_user.username}: ₹{self.amount}"


class ImportBatch(models.Model):
    """
    Tracks one CSV import run. Links all anomalies and imported expenses
    back to a single operation for audit trail.
    """

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='import_batches',
    )
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    filename = models.CharField(max_length=255)
    total_rows = models.IntegerField(default=0)
    imported_rows = models.IntegerField(default=0)
    anomaly_rows = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_import_batch'
        ordering = ['-created_at']

    def __str__(self):
        return f"Import {self.filename} ({self.created_at:%Y-%m-%d %H:%M})"


class ImportAnomaly(models.Model):
    """
    One anomaly detected during CSV import.

    This table IS the import report (PLAN.md Section 2). Each row stores
    the raw data, the problem type, the detection method, what action was
    taken, and whether a human has resolved it.
    """

    PROBLEM_CHOICES = [
        ('exact_duplicate', 'Exact duplicate expense'),
        ('precision', 'Non-standard precision amount'),
        ('name_mismatch', 'Inconsistent payer name'),
        ('missing_payer', 'Missing paid_by'),
        ('settlement_as_expense', 'Settlement logged as expense'),
        ('percentage_sum', 'Percentages not summing to 100%'),
        ('foreign_currency', 'Foreign currency row'),
        ('non_member', 'Non-member in split_with'),
        ('conflicting_amounts', 'Same expense, conflicting amounts'),
        ('negative_amount', 'Negative amount'),
        ('bad_date', 'Corrupted/implausible date'),
        ('missing_currency', 'Missing currency'),
        ('zero_amount', 'Zero-amount expense'),
        ('ambiguous_date', 'Ambiguous date format'),
        ('stale_member', 'Stale member after left_on'),
        ('split_type_conflict', 'split_type vs split_details conflict'),
        ('deposit_not_expense', 'Transfer/deposit, not shared cost'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('auto_resolved', 'Auto-resolved by policy'),
        ('blocked', 'Blocked — needs human review'),
        ('manually_resolved', 'Manually resolved by human'),
    ]

    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name='anomalies',
    )
    row_number = models.IntegerField(help_text='1-indexed row in the original CSV')
    raw_data = models.JSONField(help_text='Verbatim row data from CSV')
    problem_type = models.CharField(max_length=30, choices=PROBLEM_CHOICES)
    detection_method = models.TextField(
        help_text='Exact rule/heuristic that flagged this row',
    )
    detected_value = models.TextField(
        blank=True,
        default='',
        help_text='The specific value that triggered the anomaly',
    )
    action_taken = models.TextField(
        blank=True,
        default='',
        help_text='What the importer did (kept, dropped, normalized, blocked, etc.)',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='blocked')
    linked_expense = models.ForeignKey(
        Expense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='import_anomalies',
        help_text='The expense created from this row, if any',
    )
    linked_settlement = models.ForeignKey(
        Settlement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='import_anomalies',
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'core_import_anomaly'
        ordering = ['row_number']
        verbose_name_plural = 'Import anomalies'

    def __str__(self):
        return f"Row {self.row_number}: {self.get_problem_type_display()}"
