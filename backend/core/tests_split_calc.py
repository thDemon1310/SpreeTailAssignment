"""
Unit tests for core.split_calc — pure function, no DB, no Django client.

Run with:
    python manage.py test core.tests_split_calc --verbosity=2

All tests must pass BEFORE split_calc is wired to any API view.
Rounding policy: ROUND_HALF_UP to 2dp; remainder (total - sum(others)) assigned
to payer's share. See DECISIONS.md [2026-07-11].
"""

from decimal import Decimal
from django.test import SimpleTestCase

from core.split_calc import calculate_splits, SplitCalcError


class EqualSplitTest(SimpleTestCase):
    """equal — divide total evenly among all participants."""

    def test_equal_three_way_exact(self):
        """₹300 among 3 people divides cleanly."""
        result = calculate_splits(
            total=Decimal('300.00'),
            split_type='equal',
            participant_ids=[1, 2, 3],
            paid_by_id=1,
            split_details={},
        )
        self.assertEqual(result, {1: Decimal('100.00'), 2: Decimal('100.00'), 3: Decimal('100.00')})

    def test_equal_three_way_remainder_to_payer(self):
        """
        ₹100 ÷ 3 = 33.33 each → sum = 99.99 → 1 paisa short.
        Payer (id=1) absorbs the remainder: their share becomes 33.34.
        This is the documented rounding policy (DECISIONS.md [2026-07-11]).
        """
        result = calculate_splits(
            total=Decimal('100.00'),
            split_type='equal',
            participant_ids=[1, 2, 3],
            paid_by_id=1,
            split_details={},
        )
        self.assertEqual(result[2], Decimal('33.33'))
        self.assertEqual(result[3], Decimal('33.33'))
        self.assertEqual(result[1], Decimal('33.34'))  # payer absorbs remainder
        # Critical: splits must sum exactly to total
        self.assertEqual(sum(result.values()), Decimal('100.00'))

    def test_equal_two_way_odd_paisa(self):
        """₹101.01 ÷ 2 = 50.505 → rounds to 50.51 each → sum = 101.02 (1 over).
        Payer gets 50.50, other gets 50.51, sum = 101.01. Remainder is negative,
        so payer's share is reduced by 1 paisa.
        """
        result = calculate_splits(
            total=Decimal('101.01'),
            split_type='equal',
            participant_ids=[1, 2],
            paid_by_id=1,
            split_details={},
        )
        self.assertEqual(sum(result.values()), Decimal('101.01'))

    def test_equal_single_person(self):
        """One person — they pay the whole thing."""
        result = calculate_splits(
            total=Decimal('500.00'),
            split_type='equal',
            participant_ids=[1],
            paid_by_id=1,
            split_details={},
        )
        self.assertEqual(result, {1: Decimal('500.00')})
        self.assertEqual(sum(result.values()), Decimal('500.00'))

    def test_equal_precision_amount(self):
        """
        ₹899.995 (the CSV anomaly row) — total must be Decimal, already
        at 3dp before this function is called. split_calc rounds the output
        to 2dp per policy. 899.995 ÷ 3 = 299.998... → ROUND_HALF_UP → 300.00.
        """
        result = calculate_splits(
            total=Decimal('899.995'),
            split_type='equal',
            participant_ids=[1, 2, 3],
            paid_by_id=1,
            split_details={},
        )
        self.assertEqual(sum(result.values()), Decimal('899.995'))

    def test_equal_rejects_empty_participants(self):
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('100.00'),
                split_type='equal',
                participant_ids=[],
                paid_by_id=1,
                split_details={},
            )

    def test_equal_rejects_negative_total(self):
        """Negative totals are not this function's job — caller must handle refunds."""
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('-50.00'),
                split_type='equal',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={},
            )

    def test_equal_rejects_zero_total(self):
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('0.00'),
                split_type='equal',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={},
            )

    def test_equal_paid_by_not_in_participants_is_ok(self):
        """
        The payer might not be splitting the cost (e.g. they paid for others
        as a favour but don't owe a share). Function must not crash.
        Remainder still goes to paid_by even if they're not a participant —
        but in this case sum already equals total so no adjustment needed.
        """
        result = calculate_splits(
            total=Decimal('200.00'),
            split_type='equal',
            participant_ids=[2, 4],
            paid_by_id=1,
            split_details={},
        )
        self.assertNotIn(1, result)
        self.assertEqual(sum(result.values()), Decimal('200.00'))


class UnequalSplitTest(SimpleTestCase):
    """unequal — split_details provides exact INR amounts per participant."""

    def test_unequal_basic(self):
        result = calculate_splits(
            total=Decimal('500.00'),
            split_type='unequal',
            participant_ids=[1, 2, 3],
            paid_by_id=1,
            split_details={1: Decimal('200.00'), 2: Decimal('150.00'), 3: Decimal('150.00')},
        )
        self.assertEqual(result, {
            1: Decimal('200.00'),
            2: Decimal('150.00'),
            3: Decimal('150.00'),
        })
        self.assertEqual(sum(result.values()), Decimal('500.00'))

    def test_unequal_rounding_applied(self):
        """
        split_details amounts are rounded to 2dp if they come in with more
        precision. ₹33.335 → ROUND_HALF_UP → ₹33.34. Remainder still
        goes to payer.
        """
        result = calculate_splits(
            total=Decimal('100.00'),
            split_type='unequal',
            participant_ids=[1, 2, 3],
            paid_by_id=1,
            split_details={
                1: Decimal('33.335'),
                2: Decimal('33.335'),
                3: Decimal('33.330'),
            },
        )
        self.assertEqual(sum(result.values()), Decimal('100.00'))

    def test_unequal_rejects_missing_participant(self):
        """split_details must have an entry for every participant_id."""
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('300.00'),
                split_type='unequal',
                participant_ids=[1, 2, 3],
                paid_by_id=1,
                split_details={1: Decimal('150.00'), 2: Decimal('150.00')},
                # 3 is missing
            )

    def test_unequal_rejects_extra_participant_in_details(self):
        """split_details must not contain user_ids not in participant_ids."""
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('300.00'),
                split_type='unequal',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={1: Decimal('150.00'), 2: Decimal('100.00'), 99: Decimal('50.00')},
            )


class PercentageSplitTest(SimpleTestCase):
    """percentage — split_details provides percentage (0-100) per participant."""

    def test_percentage_exact(self):
        result = calculate_splits(
            total=Decimal('1000.00'),
            split_type='percentage',
            participant_ids=[1, 2],
            paid_by_id=1,
            split_details={1: Decimal('60'), 2: Decimal('40')},
        )
        self.assertEqual(result, {1: Decimal('600.00'), 2: Decimal('400.00')})
        self.assertEqual(sum(result.values()), Decimal('1000.00'))

    def test_percentage_rounding_remainder_to_payer(self):
        """
        30/30/30/20 = 110% — normalized to ~27.27/27.27/27.27/18.18 per SCOPE.md #10.
        But split_calc itself accepts already-normalized percentages. This test
        checks that after percentage × total + ROUND_HALF_UP + remainder-to-payer,
        the sum is always exactly total.
        """
        # 1/3 each — percentages won't round cleanly
        result = calculate_splits(
            total=Decimal('100.00'),
            split_type='percentage',
            participant_ids=[1, 2, 3],
            paid_by_id=1,
            split_details={
                1: Decimal('33.3333'),
                2: Decimal('33.3333'),
                3: Decimal('33.3334'),
            },
        )
        self.assertEqual(sum(result.values()), Decimal('100.00'))

    def test_percentage_sum_not_100_raises(self):
        """
        If percentages don't sum to 100 (within a small tolerance), raise.
        Normalization is the importer's job (SCOPE.md #10). split_calc only
        accepts already-valid percentages.
        """
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('1000.00'),
                split_type='percentage',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={1: Decimal('60'), 2: Decimal('60')},  # sums to 120
            )

    def test_percentage_rejects_negative_percentage(self):
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('100.00'),
                split_type='percentage',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={1: Decimal('110'), 2: Decimal('-10')},
            )


class SharesSplitTest(SimpleTestCase):
    """shares — split_details provides integer share count per participant."""

    def test_shares_basic(self):
        """2 shares vs 1 share → 2:1 split."""
        result = calculate_splits(
            total=Decimal('300.00'),
            split_type='shares',
            participant_ids=[1, 2],
            paid_by_id=1,
            split_details={1: Decimal('2'), 2: Decimal('1')},
        )
        self.assertEqual(result, {1: Decimal('200.00'), 2: Decimal('100.00')})
        self.assertEqual(sum(result.values()), Decimal('300.00'))

    def test_shares_remainder_to_payer(self):
        """
        ₹100 split 1:1:1 via shares (each gets 1 share of 3 total) =
        identical to equal split — remainder goes to payer.
        """
        result = calculate_splits(
            total=Decimal('100.00'),
            split_type='shares',
            participant_ids=[1, 2, 3],
            paid_by_id=1,
            split_details={1: Decimal('1'), 2: Decimal('1'), 3: Decimal('1')},
        )
        self.assertEqual(sum(result.values()), Decimal('100.00'))
        # Payer (id=1) gets the remainder — their share is 33.34, others 33.33
        self.assertEqual(result[2], Decimal('33.33'))
        self.assertEqual(result[3], Decimal('33.33'))
        self.assertEqual(result[1], Decimal('33.34'))

    def test_shares_rejects_zero_shares(self):
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('100.00'),
                split_type='shares',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={1: Decimal('0'), 2: Decimal('0')},
            )

    def test_shares_rejects_negative_shares(self):
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('100.00'),
                split_type='shares',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={1: Decimal('-1'), 2: Decimal('2')},
            )


class InvalidSplitTypeTest(SimpleTestCase):
    """Passing an unknown split_type must fail loudly."""

    def test_unknown_split_type_raises(self):
        with self.assertRaises(SplitCalcError):
            calculate_splits(
                total=Decimal('100.00'),
                split_type='magic',
                participant_ids=[1, 2],
                paid_by_id=1,
                split_details={},
            )
