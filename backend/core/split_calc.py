"""
Split calculation — pure function, no DB access.

This is the single source of truth for how expense totals are divided
among participants. All four split types pass through here. The caller
(serializer or importer) is responsible for pre-validating the expense
before calling this function.

Rounding policy (DECISIONS.md [2026-07-11]):
  - Round each share ROUND_HALF_UP to 2 decimal places (SCOPE.md #12).
  - After rounding, compute remainder = total - sum(all_shares).
  - Assign the remainder to the payer's share.
  - This guarantees: sum(splits.values()) == total, always.
  - If the payer is not in participant_ids, the remainder is dropped into
    a special payer-only key so the invariant still holds.

Usage:
    from core.split_calc import calculate_splits, SplitCalcError
    from decimal import Decimal

    splits = calculate_splits(
        total=Decimal('300.00'),
        split_type='equal',
        participant_ids=[1, 2, 3],
        paid_by_id=1,
        split_details={},
    )
    # → {1: Decimal('100.00'), 2: Decimal('100.00'), 3: Decimal('100.00')}
"""

from decimal import Decimal, ROUND_HALF_UP


PAISA = Decimal('0.01')  # smallest unit — 2dp throughout
PERCENTAGE_TOLERANCE = Decimal('0.01')  # allow up to 0.01% float drift in percentages

VALID_SPLIT_TYPES = {'equal', 'unequal', 'percentage', 'shares'}


class SplitCalcError(ValueError):
    """
    Raised when inputs to calculate_splits are invalid.

    Always a caller mistake — never catch this silently. The caller
    (API view or importer) should surface the message to the user.
    """


def _round(value: Decimal) -> Decimal:
    """Round a Decimal to 2dp using ROUND_HALF_UP (SCOPE.md #12)."""
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def _apply_remainder(shares: dict, total: Decimal, paid_by_id: int) -> dict:
    """
    Adjust the payer's share so that sum(shares.values()) == total exactly.

    Per DECISIONS.md [2026-07-11]: the payer absorbs the rounding remainder.
    If the payer is not in shares (they paid on behalf of others but don't
    owe a share themselves), add them with just the remainder as their entry
    so the invariant sum == total still holds.
    """
    current_sum = sum(shares.values())
    remainder = total - current_sum  # can be positive, negative, or zero
    if remainder == Decimal('0'):
        return shares

    result = dict(shares)
    if paid_by_id in result:
        result[paid_by_id] = result[paid_by_id] + remainder
    else:
        # Payer is not splitting the expense (paid for others only).
        # Still assign remainder to them to preserve the sum == total invariant.
        result[paid_by_id] = remainder
    return result


def _validate_common(total: Decimal, participant_ids: list, split_type: str) -> None:
    """Shared validation for all split types."""
    if split_type not in VALID_SPLIT_TYPES:
        raise SplitCalcError(
            f"Unknown split_type '{split_type}'. Must be one of: {sorted(VALID_SPLIT_TYPES)}"
        )
    if total <= Decimal('0'):
        raise SplitCalcError(
            f"total must be positive, got {total}. Refunds and zero-amount expenses "
            "must be handled before calling calculate_splits."
        )
    if not participant_ids:
        raise SplitCalcError("participant_ids must not be empty.")


def _split_equal(total: Decimal, participant_ids: list, paid_by_id: int) -> dict:
    """Divide total evenly. Remainder goes to payer."""
    n = len(participant_ids)
    base_share = _round(total / Decimal(n))
    shares = {uid: base_share for uid in participant_ids}
    return _apply_remainder(shares, total, paid_by_id)


def _split_unequal(
    total: Decimal,
    participant_ids: list,
    paid_by_id: int,
    split_details: dict,
) -> dict:
    """
    Explicit INR amounts per participant. Each amount is rounded to 2dp.
    Remainder (from rounding) goes to payer.
    """
    detail_ids = set(split_details.keys())
    participant_set = set(participant_ids)

    missing = participant_set - detail_ids
    if missing:
        raise SplitCalcError(
            f"split_details is missing amounts for participant_ids: {sorted(missing)}"
        )
    extra = detail_ids - participant_set
    if extra:
        raise SplitCalcError(
            f"split_details contains user_ids not in participant_ids: {sorted(extra)}"
        )

    shares = {uid: _round(Decimal(str(split_details[uid]))) for uid in participant_ids}
    return _apply_remainder(shares, total, paid_by_id)


def _split_percentage(
    total: Decimal,
    participant_ids: list,
    paid_by_id: int,
    split_details: dict,
) -> dict:
    """
    Percentage per participant. Must sum to 100 (within PERCENTAGE_TOLERANCE).
    Normalization of over-100% inputs is the importer's responsibility (SCOPE.md #10).
    Remainder goes to payer.
    """
    detail_ids = set(split_details.keys())
    participant_set = set(participant_ids)

    missing = participant_set - detail_ids
    if missing:
        raise SplitCalcError(
            f"split_details is missing percentages for participant_ids: {sorted(missing)}"
        )
    extra = detail_ids - participant_set
    if extra:
        raise SplitCalcError(
            f"split_details contains user_ids not in participant_ids: {sorted(extra)}"
        )

    for uid, pct in split_details.items():
        pct_d = Decimal(str(pct))
        if pct_d < Decimal('0'):
            raise SplitCalcError(
                f"Percentage for user {uid} is negative ({pct_d}). All percentages must be ≥ 0."
            )

    pct_sum = sum(Decimal(str(split_details[uid])) for uid in participant_ids)
    if abs(pct_sum - Decimal('100')) > PERCENTAGE_TOLERANCE:
        raise SplitCalcError(
            f"Percentages sum to {pct_sum}, expected 100 (±{PERCENTAGE_TOLERANCE}). "
            "Normalize percentages before calling calculate_splits."
        )

    shares = {
        uid: _round(total * Decimal(str(split_details[uid])) / Decimal('100'))
        for uid in participant_ids
    }
    return _apply_remainder(shares, total, paid_by_id)


def _split_shares(
    total: Decimal,
    participant_ids: list,
    paid_by_id: int,
    split_details: dict,
) -> dict:
    """
    Integer (or fractional) share counts per participant. Each person's amount
    = total × (their_shares / total_shares), rounded. Remainder to payer.
    """
    detail_ids = set(split_details.keys())
    participant_set = set(participant_ids)

    missing = participant_set - detail_ids
    if missing:
        raise SplitCalcError(
            f"split_details is missing share counts for participant_ids: {sorted(missing)}"
        )
    extra = detail_ids - participant_set
    if extra:
        raise SplitCalcError(
            f"split_details contains user_ids not in participant_ids: {sorted(extra)}"
        )

    for uid, sh in split_details.items():
        sh_d = Decimal(str(sh))
        if sh_d <= Decimal('0'):
            raise SplitCalcError(
                f"Share count for user {uid} is {sh_d}. All share counts must be > 0."
            )

    total_shares = sum(Decimal(str(split_details[uid])) for uid in participant_ids)

    shares = {
        uid: _round(total * Decimal(str(split_details[uid])) / total_shares)
        for uid in participant_ids
    }
    return _apply_remainder(shares, total, paid_by_id)


def calculate_splits(
    total: Decimal,
    split_type: str,
    participant_ids: list,
    paid_by_id: int,
    split_details: dict,
) -> dict:
    """
    Compute per-person share amounts for an expense.

    Args:
        total:           Expense amount in INR. Must be > 0.
        split_type:      One of 'equal', 'unequal', 'percentage', 'shares'.
        participant_ids: List of user PKs who share this expense. Must be non-empty.
        paid_by_id:      PK of the user who paid. Used to assign rounding remainder.
        split_details:   Dict of {user_pk: value} — meaning depends on split_type:
                           equal:      ignored (pass {})
                           unequal:    {pk: INR_amount_as_Decimal}
                           percentage: {pk: percentage_0_to_100_as_Decimal}
                           shares:     {pk: share_count_as_Decimal}

    Returns:
        Dict of {user_pk: Decimal} — each value rounded to 2dp.
        Invariant: sum(result.values()) == total (guaranteed by remainder assignment).

    Raises:
        SplitCalcError: on any invalid input. Never catches silently.
    """
    _validate_common(total, participant_ids, split_type)

    if split_type == 'equal':
        return _split_equal(total, participant_ids, paid_by_id)
    elif split_type == 'unequal':
        return _split_unequal(total, participant_ids, paid_by_id, split_details)
    elif split_type == 'percentage':
        return _split_percentage(total, participant_ids, paid_by_id, split_details)
    elif split_type == 'shares':
        return _split_shares(total, participant_ids, paid_by_id, split_details)
