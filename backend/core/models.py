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
        # A user can only have one active membership per group at a time
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'group'],
                name='unique_membership_per_group',
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
