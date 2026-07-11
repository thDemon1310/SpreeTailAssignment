"""
Unit tests for core.balance_calc — DB required (uses Django TestCase).

Run with:
    python manage.py test core.tests_balance_calc --verbosity=2

Tests must pass BEFORE balance_calc is wired to any API view.

Balance formula per user in a group:
    balance = total_paid - total_owed + settlements_received - settlements_made

where:
    total_paid  = sum(Expense.amount) for expenses paid_by this user in this group
    total_owed  = sum(ExpenseSplit.share_amount) for this user's splits, BUT ONLY
                  for expenses whose date falls within this user's Membership window
                  (joined_on <= expense.date, and left_on is NULL or expense.date <= left_on)
    settlements = Settlement rows in this group involving this user

Positive balance → net creditor (others owe this user)
Negative balance → net debtor (this user owes others)

Rounding: ROUND_HALF_UP to 2dp, payer absorbs remainder — per SCOPE.md #12
and DECISIONS.md [2026-07-11]. The balance_calc itself works with already-stored
Decimal values from ExpenseSplit rows; it does not re-run split_calc.
"""

from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.contrib.auth import get_user_model

from core.models import Group, Membership, Expense, ExpenseSplit, Settlement
from core.balance_calc import calculate_balances, calculate_user_balance

User = get_user_model()


class BalanceCalcSimpleTest(TestCase):
    """Basic two-person balance scenarios."""

    def setUp(self):
        self.aisha = User.objects.create_user('aisha', 'a@example.com', 'pw')
        self.rohan = User.objects.create_user('rohan', 'r@example.com', 'pw')

        self.group = Group.objects.create(name='The Flat', created_by=self.aisha)
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=date(2026, 1, 1))
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=date(2026, 1, 1))

    def _make_expense(self, paid_by, amount, expense_date, splits):
        """Helper: create an Expense + its ExpenseSplit rows directly (bypasses API)."""
        exp = Expense.objects.create(
            group=self.group,
            paid_by=paid_by,
            description='Test expense',
            amount=Decimal(str(amount)),
            date=expense_date,
            split_type='equal',
        )
        for user, share in splits.items():
            ExpenseSplit.objects.create(expense=exp, user=user, share_amount=Decimal(str(share)))
        return exp

    def test_one_expense_equal_split(self):
        """
        Aisha pays ₹200, split equally. Each owes ₹100.
        Aisha's balance = 200 paid - 100 owed = +100 (Rohan owes her)
        Rohan's balance = 0 paid - 100 owed = -100 (he owes Aisha)
        """
        self._make_expense(
            paid_by=self.aisha,
            amount='200.00',
            expense_date=date(2026, 2, 1),
            splits={self.aisha: '100.00', self.rohan: '100.00'},
        )
        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.aisha.id], Decimal('100.00'))
        self.assertEqual(balances[self.rohan.id], Decimal('-100.00'))

    def test_two_expenses_different_payers(self):
        """
        Aisha pays ₹200 (each owes 100), Rohan pays ₹100 (each owes 50).
        Aisha: paid 200 - owed 150 (100+50) = +50
        Rohan: paid 100 - owed 150 (100+50) = -50
        (Rohan owes 100 from Aisha's expense + 50 from his own = 150 total owed)
        Sum of all balances should be 0 (zero-sum property).
        """
        self._make_expense(self.aisha, '200.00', date(2026, 2, 1),
                           {self.aisha: '100.00', self.rohan: '100.00'})
        self._make_expense(self.rohan, '100.00', date(2026, 2, 5),
                           {self.aisha: '50.00', self.rohan: '50.00'})
        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.aisha.id], Decimal('50.00'))
        self.assertEqual(balances[self.rohan.id], Decimal('-50.00'))
        # Zero-sum: positive balances equal negative balances across the group
        self.assertEqual(sum(balances.values()), Decimal('0.00'))

    def test_zero_sum_invariant_always_holds(self):
        """
        The sum of all balances in a group is always 0.
        Money paid out = money owed back, in total.
        """
        self._make_expense(self.aisha, '350.00', date(2026, 2, 10),
                           {self.aisha: '175.00', self.rohan: '175.00'})
        balances = calculate_balances(self.group.id)
        self.assertEqual(sum(balances.values()), Decimal('0.00'))

    def test_calculate_user_balance_matches_group_balance(self):
        """calculate_user_balance returns the same value as the corresponding entry in calculate_balances."""
        self._make_expense(self.aisha, '200.00', date(2026, 2, 1),
                           {self.aisha: '100.00', self.rohan: '100.00'})
        balances = calculate_balances(self.group.id)
        self.assertEqual(
            calculate_user_balance(self.group.id, self.aisha.id),
            balances[self.aisha.id],
        )

    def test_no_expenses_all_balances_zero(self):
        """Empty group has all-zero balances."""
        balances = calculate_balances(self.group.id)
        for uid, bal in balances.items():
            self.assertEqual(bal, Decimal('0.00'))


class MembershipWindowExclusionTest(TestCase):
    """
    The key correctness test: expenses outside a member's Membership window
    must NOT count toward that member's balance.

    This directly implements Sam's requirement: "I only want to owe for
    expenses that happened while I was actually in the flat."
    """

    def setUp(self):
        self.aisha = User.objects.create_user('aisha', 'a@example.com', 'pw')
        self.rohan = User.objects.create_user('rohan', 'r@example.com', 'pw')
        self.meera = User.objects.create_user('meera', 'm@example.com', 'pw')

        self.group = Group.objects.create(name='The Flat', created_by=self.aisha)
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=date(2026, 1, 1))
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=date(2026, 1, 1))
        # Meera joined Feb 1, left March 31
        Membership.objects.create(
            user=self.meera,
            group=self.group,
            joined_on=date(2026, 2, 1),
            left_on=date(2026, 3, 31),
        )

    def _make_expense(self, paid_by, amount, expense_date, splits):
        exp = Expense.objects.create(
            group=self.group,
            paid_by=paid_by,
            description='Test expense',
            amount=Decimal(str(amount)),
            date=expense_date,
            split_type='equal',
        )
        for user, share in splits.items():
            ExpenseSplit.objects.create(expense=exp, user=user, share_amount=Decimal(str(share)))
        return exp

    def test_expense_before_join_excluded(self):
        """
        Expense on Jan 15 — Meera hadn't joined yet (joined Feb 1).
        Even if an ExpenseSplit row exists for Meera on that expense,
        it must NOT count toward her balance.
        """
        # Jan 15 expense — before Meera's joined_on of Feb 1
        self._make_expense(
            paid_by=self.aisha,
            amount='300.00',
            expense_date=date(2026, 1, 15),
            splits={self.aisha: '100.00', self.rohan: '100.00', self.meera: '100.00'},
        )
        balances = calculate_balances(self.group.id)
        # Meera's split for this expense must be excluded (she wasn't a member yet)
        # So Meera's total_owed = 0, balance = 0
        self.assertEqual(balances[self.meera.id], Decimal('0.00'))
        # Aisha paid 300, her own owed share = 100 (within her window)
        # The 100 that Meera would have owed is excluded — it doesn't count for anyone
        # So Aisha balance = 300 paid - 100 owed = +200
        self.assertEqual(balances[self.aisha.id], Decimal('200.00'))

    def test_expense_after_left_excluded(self):
        """
        Expense on April 5 — Meera had left on March 31.
        Her split on that expense must NOT count toward her balance.
        """
        self._make_expense(
            paid_by=self.aisha,
            amount='300.00',
            expense_date=date(2026, 4, 5),
            splits={self.aisha: '100.00', self.rohan: '100.00', self.meera: '100.00'},
        )
        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.meera.id], Decimal('0.00'))

    def test_expense_within_window_included(self):
        """
        Expense on Feb 15 — within Meera's membership window.
        Her split must be included.
        """
        self._make_expense(
            paid_by=self.aisha,
            amount='300.00',
            expense_date=date(2026, 2, 15),
            splits={self.aisha: '100.00', self.rohan: '100.00', self.meera: '100.00'},
        )
        balances = calculate_balances(self.group.id)
        # Meera owes her share: total_owed = 100, total_paid = 0 → balance = -100
        self.assertEqual(balances[self.meera.id], Decimal('-100.00'))

    def test_expense_on_join_date_included(self):
        """Boundary: expense on the exact join date must be included."""
        self._make_expense(
            paid_by=self.aisha,
            amount='200.00',
            expense_date=date(2026, 2, 1),  # exactly joined_on
            splits={self.aisha: '100.00', self.meera: '100.00'},
        )
        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.meera.id], Decimal('-100.00'))

    def test_expense_on_left_date_included(self):
        """Boundary: expense on the exact left_on date must be included."""
        self._make_expense(
            paid_by=self.aisha,
            amount='200.00',
            expense_date=date(2026, 3, 31),  # exactly left_on
            splits={self.aisha: '100.00', self.meera: '100.00'},
        )
        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.meera.id], Decimal('-100.00'))

    def test_user_with_no_membership_in_group_raises(self):
        """
        Asking for a user who has no Membership row in this group should
        return 0 balance (not raise) — they may appear in split rows from
        import anomalies but have no stake in the group.
        """
        outsider = User.objects.create_user('outsider', 'o@example.com', 'pw')
        balance = calculate_user_balance(self.group.id, outsider.id)
        self.assertEqual(balance, Decimal('0.00'))


class SettlementTest(TestCase):
    """Settlement rows must reduce outstanding balances correctly."""

    def setUp(self):
        self.aisha = User.objects.create_user('aisha', 'a@example.com', 'pw')
        self.rohan = User.objects.create_user('rohan', 'r@example.com', 'pw')

        self.group = Group.objects.create(name='The Flat', created_by=self.aisha)
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=date(2026, 1, 1))
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=date(2026, 1, 1))

        # Aisha pays ₹200, Rohan owes her ₹100
        exp = Expense.objects.create(
            group=self.group, paid_by=self.aisha, description='Dinner',
            amount=Decimal('200.00'), date=date(2026, 2, 1), split_type='equal',
        )
        ExpenseSplit.objects.create(expense=exp, user=self.aisha, share_amount=Decimal('100.00'))
        ExpenseSplit.objects.create(expense=exp, user=self.rohan, share_amount=Decimal('100.00'))

    def test_settlement_clears_debt(self):
        """
        Rohan pays Aisha ₹100 (full settlement).
        After: Aisha balance = +100 - 100 received = 0; Rohan = -100 + 100 paid = 0.
        """
        Settlement.objects.create(
            group=self.group,
            from_user=self.rohan,
            to_user=self.aisha,
            amount=Decimal('100.00'),
            date=date(2026, 2, 10),
        )
        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.aisha.id], Decimal('0.00'))
        self.assertEqual(balances[self.rohan.id], Decimal('0.00'))

    def test_partial_settlement(self):
        """Rohan pays Aisha ₹60 — partial. Remaining: Rohan still owes ₹40."""
        Settlement.objects.create(
            group=self.group,
            from_user=self.rohan,
            to_user=self.aisha,
            amount=Decimal('60.00'),
            date=date(2026, 2, 10),
        )
        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.aisha.id], Decimal('40.00'))
        self.assertEqual(balances[self.rohan.id], Decimal('-40.00'))
        self.assertEqual(sum(balances.values()), Decimal('0.00'))

    def test_settlement_in_wrong_group_ignored(self):
        """A settlement in a different group must not affect this group's balances."""
        other_group = Group.objects.create(name='Other Group', created_by=self.aisha)
        Settlement.objects.create(
            group=other_group,
            from_user=self.rohan,
            to_user=self.aisha,
            amount=Decimal('100.00'),
            date=date(2026, 2, 10),
        )
        balances = calculate_balances(self.group.id)
        # This group's balances are unaffected
        self.assertEqual(balances[self.aisha.id], Decimal('100.00'))
        self.assertEqual(balances[self.rohan.id], Decimal('-100.00'))


class RoundingInBalanceTest(TestCase):
    """
    Rounding edge cases in balance: ExpenseSplit stores already-rounded Decimal
    values. balance_calc sums them up — no re-rounding happens at balance level.
    Verify the payer's remainder absorption makes the zero-sum property hold.
    """

    def setUp(self):
        self.aisha = User.objects.create_user('aisha', 'a@example.com', 'pw')
        self.rohan = User.objects.create_user('rohan', 'r@example.com', 'pw')
        self.priya = User.objects.create_user('priya', 'p@example.com', 'pw')

        self.group = Group.objects.create(name='The Flat', created_by=self.aisha)
        Membership.objects.create(user=self.aisha, group=self.group, joined_on=date(2026, 1, 1))
        Membership.objects.create(user=self.rohan, group=self.group, joined_on=date(2026, 1, 1))
        Membership.objects.create(user=self.priya, group=self.group, joined_on=date(2026, 1, 1))

    def test_rounding_remainder_in_payer_share_zero_sum(self):
        """
        ₹100 ÷ 3: Aisha pays, payer absorbs remainder → 33.34, 33.33, 33.33.
        Aisha balance = 100 paid - 33.34 owed = +66.66
        Rohan balance = 0 - 33.33 = -33.33
        Priya balance = 0 - 33.33 = -33.33
        Sum = 0. Zero-sum must hold even with rounding remainder.
        """
        exp = Expense.objects.create(
            group=self.group, paid_by=self.aisha, description='Groceries',
            amount=Decimal('100.00'), date=date(2026, 2, 1), split_type='equal',
        )
        # These are exactly the values split_calc would produce
        ExpenseSplit.objects.create(expense=exp, user=self.aisha, share_amount=Decimal('33.34'))
        ExpenseSplit.objects.create(expense=exp, user=self.rohan, share_amount=Decimal('33.33'))
        ExpenseSplit.objects.create(expense=exp, user=self.priya, share_amount=Decimal('33.33'))

        balances = calculate_balances(self.group.id)
        self.assertEqual(balances[self.aisha.id], Decimal('66.66'))
        self.assertEqual(balances[self.rohan.id], Decimal('-33.33'))
        self.assertEqual(balances[self.priya.id], Decimal('-33.33'))
        self.assertEqual(sum(balances.values()), Decimal('0.00'))
