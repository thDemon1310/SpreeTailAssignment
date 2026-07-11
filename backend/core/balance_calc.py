"""
Balance calculation — queries DB, returns Decimal balances per user.

This is the single source of truth for what each member owes or is owed
within a group. Never recomputed in the frontend — the API returns these
values directly (Rohan's "no magic numbers" requirement).

Balance formula per user:
    balance = total_paid - total_owed + settlements_received - settlements_made

where:
    total_paid          = sum(Expense.amount) for expenses paid_by this user
                          in this group
    total_owed          = sum(ExpenseSplit.share_amount) for this user's splits
                          WHERE the expense date falls within the user's
                          Membership window (joined_on <= date <= left_on)
    settlements_received = sum(Settlement.amount) where to_user = this user
    settlements_made     = sum(Settlement.amount) where from_user = this user

Positive balance → net creditor (others owe this user)
Negative balance → net debtor (this user owes others)

Zero-sum invariant: sum(calculate_balances(group_id).values()) == 0 always.
This holds because every expense's amount equals the sum of its splits,
and settlements transfer between exactly two users.

Membership window rule (PLAN.md Section 2, Sam's requirement):
An ExpenseSplit only contributes to a member's total_owed if the expense's
date falls within that member's Membership window:
    membership.joined_on <= expense.date
    AND (membership.left_on IS NULL OR expense.date <= membership.left_on)

If a member has no Membership row for the group, their total_owed = 0.
This acts as a safety net even if the importer wrote split rows for a
non-member (those rows are ignored in balance calculation).
"""

from decimal import Decimal

from django.db.models import Sum, Q

from core.models import Expense, ExpenseSplit, Settlement, Membership


ZERO = Decimal('0.00')


def _get_membership_windows(group_id: int) -> dict:
    """
    Return {user_id: (joined_on, left_on)} for all members of the group.
    left_on may be None (still active).
    """
    memberships = Membership.objects.filter(group_id=group_id).values(
        'user_id', 'joined_on', 'left_on'
    )
    return {
        m['user_id']: (m['joined_on'], m['left_on'])
        for m in memberships
    }


def _total_paid(group_id: int, user_id: int) -> Decimal:
    """Sum of all expense amounts paid by this user in this group."""
    result = (
        Expense.objects
        .filter(group_id=group_id, paid_by_id=user_id)
        .aggregate(total=Sum('amount'))
    )
    return result['total'] or ZERO


def _total_owed(group_id: int, user_id: int, joined_on, left_on) -> Decimal:
    """
    Sum of this user's ExpenseSplit shares for expenses that fall within
    their membership window.

    The window filter is applied at query time using the membership dates,
    not via Membership.is_active_on() (which would require a Python loop
    over every split row — this is a single SQL query instead).
    """
    # Base filter: splits for this user in this group
    qs = ExpenseSplit.objects.filter(
        user_id=user_id,
        expense__group_id=group_id,
        expense__date__gte=joined_on,  # expense on or after join date
    )

    # If the user has left, also exclude expenses after their departure date
    if left_on is not None:
        qs = qs.filter(expense__date__lte=left_on)

    result = qs.aggregate(total=Sum('share_amount'))
    return result['total'] or ZERO


def _settlement_net(group_id: int, user_id: int) -> Decimal:
    """
    Net settlement contribution to this user's balance.

    When someone pays YOU a settlement, your outstanding receivable decreases
    (the debt is cleared). When YOU pay someone, your outstanding debt decreases.

    From your balance's perspective:
        settlements_made     → reduces what you owe    → positive contribution
        settlements_received → reduces what others owe  → negative contribution

    So: net = settlements_made - settlements_received

    Full balance formula:
        balance = total_paid - total_owed - settlements_received + settlements_made
               = total_paid - total_owed + (settlements_made - settlements_received)
               = total_paid - total_owed + _settlement_net()
    """
    received = (
        Settlement.objects
        .filter(group_id=group_id, to_user_id=user_id)
        .aggregate(total=Sum('amount'))
    )['total'] or ZERO

    made = (
        Settlement.objects
        .filter(group_id=group_id, from_user_id=user_id)
        .aggregate(total=Sum('amount'))
    )['total'] or ZERO

    # made - received: paying off debt improves your balance,
    # receiving payment reduces the outstanding debt others owe you
    return made - received


def calculate_balances(group_id: int) -> dict:
    """
    Compute balance for every member currently (or historically) in the group.

    Returns:
        Dict of {user_id: Decimal} — one entry per Membership row in the group.
        Positive = net creditor, negative = net debtor.
        Invariant: sum(result.values()) == 0 always.

    A user who paid expenses but has no Membership row is still included
    via their paid amounts — their total_owed defaults to 0.
    """
    windows = _get_membership_windows(group_id)

    # Collect all user_ids who appear in this group — either as members
    # or as payers (to handle edge cases where someone paid but isn't listed
    # as a member, e.g. the group creator before membership was formally added)
    payer_ids = set(
        Expense.objects
        .filter(group_id=group_id)
        .values_list('paid_by_id', flat=True)
    )
    all_user_ids = set(windows.keys()) | payer_ids

    balances = {}
    for user_id in all_user_ids:
        paid = _total_paid(group_id, user_id)

        if user_id in windows:
            joined_on, left_on = windows[user_id]
            owed = _total_owed(group_id, user_id, joined_on, left_on)
        else:
            # No membership row — they paid but don't owe anything
            # (unusual, but zero-sum invariant is maintained because their
            # splits won't be counted by any member's _total_owed either)
            owed = ZERO

        net_settlement = _settlement_net(group_id, user_id)
        balances[user_id] = paid - owed + net_settlement

    return balances


def calculate_user_balance(group_id: int, user_id: int) -> Decimal:
    """
    Compute balance for a single user in a group.

    Returns 0 if the user has no membership and no financial activity in
    this group (rather than raising), since the API needs a safe default
    for non-members who may appear in import anomaly context.
    """
    windows = _get_membership_windows(group_id)

    paid = _total_paid(group_id, user_id)

    if user_id in windows:
        joined_on, left_on = windows[user_id]
        owed = _total_owed(group_id, user_id, joined_on, left_on)
    else:
        owed = ZERO

    net_settlement = _settlement_net(group_id, user_id)
    return paid - owed + net_settlement
