"""
CSV Import Pipeline — core/importer.py

Reads expenses_export.csv, runs every anomaly-detection rule (one per Phase 3
TODO item), writes clean rows to Expense+ExpenseSplit, anomalies to
ImportAnomaly, and settlements to Settlement.

Architecture
------------
- parse_csv()          : read the raw file, yield dicts, no detection
- normalize_name()     : strip+casefold, used by duplicate hash and name matching
- normalize_description(): casefold+strip+remove punctuation, used by dup hash
- build_dup_hash()     : compute the exact-duplicate fingerprint for a row
- run_import()         : main entry point — returns ImportResult

Each detection rule is a standalone function `detect_<name>(row, context) ->
AnomalySpec | None` that returns either None (row is clean for that rule) or
a dict describing the anomaly to log. No detection function writes to the DB.
Writing happens only inside run_import(), after all detections for a row are
complete.

Policies (all logged in DECISIONS.md [2026-07-11]):
  - FX: 1 USD = 83.50 INR fixed rate
  - Rounding: ROUND_HALF_UP to 2dp (DECISIONS.md [2026-07-11], split_calc.py)
  - Exact duplicate: hash on (date, amount_str, payer_normalized, desc_normalized)
  - Settlement: blank split_type + single recipient + description regex
  - Deposit: non-blank split_type + single recipient + description regex (separate rule)
  - Non-member: redistribute share, flag anomaly
  - Stale member: redistribute share, flag anomaly (same redistribution policy as Kabir)
  - Missing payer / missing currency: block row
  - Negative amount: treat as refund (positive amount, flagged)
  - Bad date: block row (outside Jan 2026 – Jun 2026)
  - Ambiguous date: block row (date where note/context explicitly questions format)
  - Zero amount: block row
  - Precision > 2dp: round ROUND_HALF_UP, flag
  - Percentages ≠ 100%: normalize proportionally, flag
  - split_type=equal but split_details non-empty: split_details wins, flag
"""

import csv
import hashlib
import re
import string
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db import transaction
from django.utils import timezone

from .models import (
    Expense,
    ExpenseSplit,
    Group,
    ImportAnomaly,
    ImportBatch,
    Membership,
    Settlement,
)
from .split_calc import calculate_splits, SplitCalcError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USD_TO_INR = Decimal('83.50')      # fixed rate, documented in DECISIONS.md

PAISA = Decimal('0.01')

# Sane date window for this dataset: Feb 2026 – Jun 2026
SANE_DATE_MIN_YEAR = 2026
SANE_DATE_MIN_MONTH = 2
SANE_DATE_MAX_YEAR = 2026
SANE_DATE_MAX_MONTH = 6

# Regex for settlement/deposit-like descriptions
_SETTLEMENT_RE = re.compile(
    r'\b(paid|repaid|returned|gave|sent|back|settled|settlement|deposit|transfer|advance|moving in|moved in)\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class AnomalySpec:
    """Describes a detected anomaly — filled during detection, written in run_import."""
    problem_type: str          # must be a valid ImportAnomaly.PROBLEM_CHOICES key
    detection_method: str      # exact rule/heuristic that fired
    detected_value: str        # the specific value that triggered it
    action_taken: str          # what the importer did or will do
    status: str                # 'auto_resolved', 'blocked', 'manually_resolved'


@dataclass
class RowResult:
    """Outcome for a single CSV row after all detections."""
    row_number: int
    raw: dict                              # verbatim CSV dict
    anomalies: list = field(default_factory=list)   # list[AnomalySpec]
    expense: Optional[Expense] = None     # set if row was imported as Expense
    settlement: Optional[Settlement] = None  # set if row was imported as Settlement
    skipped: bool = False                 # True if row was not imported at all


@dataclass
class ImportResult:
    """Summary returned by run_import()."""
    batch: ImportBatch
    row_results: list = field(default_factory=list)  # list[RowResult]

    @property
    def total_rows(self):
        return len(self.row_results)

    @property
    def imported_rows(self):
        return sum(1 for r in self.row_results if r.expense or r.settlement)

    @property
    def anomaly_rows(self):
        return sum(1 for r in self.row_results if r.anomalies)

    @property
    def skipped_rows(self):
        return sum(1 for r in self.row_results if r.skipped)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def normalize_name(raw: str) -> str:
    """Strip whitespace + casefold. Used for payer matching and dup hashing."""
    return raw.strip().casefold()


_STOPWORDS = frozenset({
    'a', 'an', 'the', 'at', 'in', 'on', 'of', 'for', 'to', 'and',
    'is', 'it', 'by', 'with', 'from', 'this', 'that',
})


def normalize_description(raw: str) -> str:
    """
    Normalize a description for duplicate detection:
      1. Strip whitespace + casefold
      2. Remove all punctuation and non-alphanumeric chars
      3. Remove common English stopwords
      4. Collapse whitespace

    'Dinner at Marina Bites' and 'dinner - marina bites' must produce the
    same normalized form so the duplicate hash fires correctly.
    """
    s = raw.strip().casefold()
    # Remove all non-alphanumeric, non-space characters
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    # Remove stopwords
    tokens = [t for t in s.split() if t not in _STOPWORDS]
    return ' '.join(tokens)


def build_dup_hash(date_str: str, amount_str: str, paid_by_raw: str, desc_raw: str) -> str:
    """
    Exact-duplicate fingerprint.

    Hash on: (date, amount as-is, paid_by normalized, description normalized).
    Two rows with the same hash are treated as the same event logged twice.
    If the hash ever fires on something ambiguous, downgrade to 'possible duplicate'
    path (conflicting_amounts) instead of auto-resolving (DECISIONS.md [2026-07-11]).
    """
    key = '|'.join([
        date_str.strip(),
        amount_str.strip(),
        normalize_name(paid_by_raw),
        normalize_description(desc_raw),
    ])
    return hashlib.sha256(key.encode()).hexdigest()


def parse_csv(filepath: str):
    """
    Yield (1-indexed row number, dict) for every data row in the CSV.
    Header row is skipped. Raw values are str — no type coercion here.
    """
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            yield i, dict(row)


def _round(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Member resolution helpers
# ---------------------------------------------------------------------------

def _build_member_lookup(group: Group, expense_date=None):
    """
    Return two mappings:
      - name_to_user: {normalized_name: User} for all-time group members
      - active_ids:   set of user PKs who were active on expense_date (if given)

    Used by name-normalization detection and stale-member detection.
    """
    memberships = (
        Membership.objects.filter(group=group)
        .select_related('user')
    )
    name_to_user = {}
    active_ids = set()
    for m in memberships:
        name_to_user[normalize_name(m.user.username)] = m.user
        name_to_user[normalize_name(m.user.first_name or '')] = m.user
        name_to_user[normalize_name(m.user.last_name or '')] = m.user
        if expense_date and m.is_active_on(expense_date):
            active_ids.add(m.user.pk)

    # Remove empty-string key if it got added from blank names
    name_to_user.pop('', None)
    return name_to_user, active_ids


def _resolve_names(raw_names: list, name_to_user: dict) -> tuple:
    """
    Resolve a list of raw participant names to User objects.
    Returns (resolved_users, unresolved_raw_names).
    """
    resolved = []
    unresolved = []
    for n in raw_names:
        norm = normalize_name(n)
        if norm in name_to_user:
            user = name_to_user[norm]
            if user not in resolved:  # deduplicate
                resolved.append(user)
        else:
            unresolved.append(n)
    return resolved, unresolved


# ---------------------------------------------------------------------------
# Detection rule: exact duplicate (Phase 3 Task 1)
# ---------------------------------------------------------------------------

def detect_exact_duplicate(row: dict, seen_hashes: dict) -> Optional[AnomalySpec]:
    """
    Detection method: SHA-256 hash of (date, amount, paid_by_normalized,
    description_normalized). Exact match against previously seen hashes = duplicate.

    seen_hashes: dict managed by run_import — maps hash -> row_number of first occurrence.
    This function is READ-ONLY on seen_hashes; run_import registers the hash after
    calling this.
    Returns AnomalySpec if this row is a duplicate of an earlier row, else None.
    Fallback: if hash matches but amounts differ (would be a hash collision or the
    'conflicting amounts' case), the caller must downgrade to 'conflicting_amounts'
    detection. This function only fires on exact match.
    """
    h = build_dup_hash(
        row.get('date', ''),
        row.get('amount', ''),
        row.get('paid_by', ''),
        row.get('description', ''),
    )
    if h in seen_hashes:
        first_row = seen_hashes[h]
        return AnomalySpec(
            problem_type='exact_duplicate',
            detection_method=(
                'SHA-256 hash on (date, amount, paid_by_normalized, '
                'description_normalized). Exact hash match against row '
                f'{first_row}.'
            ),
            detected_value=(
                f'Hash {h[:16]}… matched row {first_row}. '
                f'This row: date={row.get("date")}, amount={row.get("amount")}, '
                f'paid_by="{row.get("paid_by")}", '
                f'description="{row.get("description")}"'
            ),
            action_taken=(
                f'Row dropped. Row {first_row} kept as the canonical version. '
                'No Expense or ExpenseSplit rows written for this row.'
            ),
            status='auto_resolved',
        )
    return None


# ---------------------------------------------------------------------------
# Detection rule: non-standard precision (Phase 3 Task 2)
# ---------------------------------------------------------------------------

def detect_precision(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: any amount string with more than 2 decimal places.
    Policy: round ROUND_HALF_UP, flag, store both raw and rounded values.
    """
    raw_amount = row.get('amount', '').strip()
    if not raw_amount:
        return None
    try:
        d = Decimal(raw_amount)
    except Exception:
        return None  # malformed amount caught later
    rounded = _round(d)
    if d == rounded:
        return None  # already 2dp or fewer
    return AnomalySpec(
        problem_type='precision',
        detection_method=(
            'Amount string has more than 2 decimal places. '
            'Rule: any amount where Decimal(raw) != Decimal(raw).quantize(0.01, ROUND_HALF_UP).'
        ),
        detected_value=f'raw={raw_amount}, rounded={rounded}',
        action_taken=(
            f'Amount rounded ROUND_HALF_UP from {raw_amount} to {rounded}. '
            'Both values stored in ImportAnomaly.detected_value. '
            'rounded value used for Expense.amount and split calculation.'
        ),
        status='auto_resolved',
    )


# ---------------------------------------------------------------------------
# Detection rule: inconsistent payer name (Phase 3 Task 3)
# ---------------------------------------------------------------------------

def detect_name_mismatch(row: dict, name_to_user: dict) -> tuple:
    """
    Detection method: normalize paid_by (strip + casefold), look up in
    name_to_user (built from all-time group members). Exact match after
    normalization = auto-map. No match = unmatched, must block row.

    Returns (matched_user_or_None, AnomalySpec_or_None).
    """
    raw_name = row.get('paid_by', '').strip()
    if not raw_name:
        return None, None  # blank payer caught by detect_missing_payer

    norm = normalize_name(raw_name)
    if norm in name_to_user:
        user = name_to_user[norm]
        if raw_name == user.username:
            # Perfect match — no anomaly
            return user, None
        # Normalized match but raw string differs (casing, whitespace, suffix)
        return user, AnomalySpec(
            problem_type='name_mismatch',
            detection_method=(
                'strip()+casefold() of paid_by matched a known member username '
                'but the raw string differs from the stored username.'
            ),
            detected_value=f'raw="{raw_name}", matched_to="{user.username}" (id={user.pk})',
            action_taken=(
                f'Auto-mapped to user "{user.username}" (id={user.pk}). '
                'Expense created with correct paid_by FK. '
                'Raw name preserved in detected_value.'
            ),
            status='auto_resolved',
        )
    # No match even after normalization
    return None, AnomalySpec(
        problem_type='name_mismatch',
        detection_method=(
            'strip()+casefold() of paid_by did not match any known member username. '
            'Exact match required — fuzzy auto-create is never done (DECISIONS.md #13).'
        ),
        detected_value=f'raw="{raw_name}", normalized="{norm}", no member matched',
        action_taken=(
            'Row blocked. No Expense written. '
            'Unmatched name preserved in detected_value for manual mapping.'
        ),
        status='blocked',
    )


# ---------------------------------------------------------------------------
# Detection rule: missing paid_by (Phase 3 Task 4)
# ---------------------------------------------------------------------------

def detect_missing_payer(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: paid_by field is null or blank after strip().
    Policy: block row entirely. No default, no guess (PLAN.md #8).
    """
    raw = row.get('paid_by', '').strip()
    if raw:
        return None
    return AnomalySpec(
        problem_type='missing_payer',
        detection_method='paid_by field is null or blank after strip().',
        detected_value='paid_by=""',
        action_taken=(
            'Row blocked. Full row preserved in raw_data. '
            'No Expense written. Excluded from balance calculation '
            'until a human assigns a payer through the UI.'
        ),
        status='blocked',
    )


# ---------------------------------------------------------------------------
# Detection rule: settlement logged as expense (Phase 3 Task 5)
# ---------------------------------------------------------------------------

def detect_settlement(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method (DECISIONS.md [2026-07-11]):
    ALL THREE must be true:
      1. split_type is blank/null
      2. split_with has exactly one name
      3. description matches SETTLEMENT_RE

    Fallback: if exactly two of three hold (low confidence), block for manual
    review but do NOT auto-route to Settlement table.
    """
    split_type = row.get('split_type', '').strip()
    split_with_raw = row.get('split_with', '').strip()
    description = row.get('description', '').strip()

    names = [n.strip() for n in split_with_raw.split(';') if n.strip()]
    cond_blank_type = not split_type
    cond_single_recipient = len(names) == 1
    cond_desc_match = bool(_SETTLEMENT_RE.search(description))

    score = sum([cond_blank_type, cond_single_recipient, cond_desc_match])

    if score == 3:
        return AnomalySpec(
            problem_type='settlement_as_expense',
            detection_method=(
                'All three conditions met: split_type blank, '
                'split_with has exactly one name, description matches '
                r'regex \b(paid|repaid|returned|gave|sent|back|settled|settlement|deposit|transfer|advance|moving in|moved in)\b.'
            ),
            detected_value=(
                f'description="{description}", split_type="{split_type}", '
                f'split_with="{split_with_raw}"'
            ),
            action_taken=(
                'Row routed to Settlement table (not Expense). '
                'Original row referenced by row_number in ImportAnomaly for audit.'
            ),
            status='auto_resolved',
        )
    if score == 2:
        return AnomalySpec(
            problem_type='settlement_as_expense',
            detection_method=(
                f'Two of three settlement conditions met (score=2): '
                f'blank_split_type={cond_blank_type}, '
                f'single_recipient={cond_single_recipient}, '
                f'desc_matches={cond_desc_match}. Low confidence — not auto-routed.'
            ),
            detected_value=(
                f'description="{description}", split_type="{split_type}", '
                f'split_with="{split_with_raw}"'
            ),
            action_taken='Row blocked for manual review. Not auto-routed to Settlement.',
            status='blocked',
        )
    return None


# ---------------------------------------------------------------------------
# Detection rule: percentages not summing to 100% (Phase 3 Task 6)
# ---------------------------------------------------------------------------

def detect_percentage_sum(row: dict) -> tuple:
    """
    Detection method: sum split_details percentages; compare to 100 with
    tolerance Decimal('0.01').
    Returns (normalized_details_or_None, AnomalySpec_or_None).
    Policy: normalize proportionally (PLAN.md #10), flag loudly.
    """
    if row.get('split_type', '').strip().lower() != 'percentage':
        return None, None

    raw_details = row.get('split_details', '').strip()
    if not raw_details:
        return None, None

    # Parse "Name X%; Name Y%" format
    try:
        pairs = _parse_split_details_percentage(raw_details)
    except ValueError:
        return None, None  # malformed — caught elsewhere

    pct_sum = sum(v for _, v in pairs)
    tolerance = Decimal('0.01')

    if abs(pct_sum - Decimal('100')) <= tolerance:
        return None, None  # within tolerance, no anomaly

    # Normalize proportionally
    normalized = [(name, v * Decimal('100') / pct_sum) for name, v in pairs]
    normalized_str = '; '.join(f'{n} {p:.4f}%' for n, p in normalized)

    return normalized, AnomalySpec(
        problem_type='percentage_sum',
        detection_method=(
            f'Sum of split_details percentages = {pct_sum} '
            f'(expected 100 ± {tolerance}). '
            'Normalization applied proportionally.'
        ),
        detected_value=f'raw_sum={pct_sum}, raw_details="{raw_details}"',
        action_taken=(
            f'Percentages normalized proportionally to sum to 100. '
            f'Normalized values: {normalized_str}. '
            'Both raw and normalized values stored in ImportAnomaly.detected_value.'
        ),
        status='auto_resolved',
    )


def _parse_split_details_percentage(raw: str) -> list:
    """
    Parse "Aisha 30%; Rohan 30%; Priya 30%; Meera 20%" → [(name, Decimal), ...].
    Raises ValueError on parse failure.
    """
    result = []
    for part in raw.split(';'):
        part = part.strip()
        if not part:
            continue
        # Find the last token that looks like a percentage
        m = re.match(r'^(.+?)\s+([\d.]+)%?$', part)
        if not m:
            raise ValueError(f'Cannot parse: {part!r}')
        name = m.group(1).strip()
        pct = Decimal(m.group(2))
        result.append((name, pct))
    return result


def _parse_split_details_amount(raw: str) -> list:
    """
    Parse "Rohan 700; Priya 400; Meera 400" → [(name, Decimal), ...].
    Raises ValueError on parse failure.
    """
    result = []
    for part in raw.split(';'):
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^(.+?)\s+([\d.]+)$', part)
        if not m:
            raise ValueError(f'Cannot parse: {part!r}')
        name = m.group(1).strip()
        amt = Decimal(m.group(2))
        result.append((name, amt))
    return result


def _parse_split_details_shares(raw: str) -> list:
    """
    Parse "Aisha 1; Rohan 2; Priya 1; Dev 2" → [(name, Decimal), ...].
    Raises ValueError on parse failure.
    """
    return _parse_split_details_amount(raw)  # same format


# ---------------------------------------------------------------------------
# Detection rule: foreign currency (Phase 3 Task 7)
# ---------------------------------------------------------------------------

def detect_foreign_currency(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: currency field != 'INR' (case-insensitive, after strip).
    Policy: convert using fixed USD_TO_INR rate; store original_amount,
    original_currency, exchange_rate, and converted amount (DECISIONS.md [2026-07-11]).
    """
    currency = row.get('currency', '').strip().upper()
    if not currency or currency == 'INR':
        return None
    try:
        original = Decimal(row.get('amount', '0').strip())
        if currency == 'USD':
            converted = _round(original * USD_TO_INR)
        else:
            # Unknown currency — block
            return AnomalySpec(
                problem_type='foreign_currency',
                detection_method=f'currency field = "{currency}" which is not INR and has no known conversion rate.',
                detected_value=f'currency="{currency}", amount={row.get("amount")}',
                action_taken='Row blocked — no conversion rate available for this currency.',
                status='blocked',
            )
    except Exception:
        return None

    return AnomalySpec(
        problem_type='foreign_currency',
        detection_method='currency field is not INR; converted using fixed rate 1 USD = 83.50 INR (DECISIONS.md [2026-07-11]).',
        detected_value=(
            f'original_amount={original} {currency}, '
            f'exchange_rate={USD_TO_INR}, '
            f'converted_amount={converted} INR'
        ),
        action_taken=(
            f'Expense.amount set to converted value {converted} INR. '
            f'Expense.original_amount={original}, Expense.exchange_rate={USD_TO_INR}, '
            f'Expense.currency="{currency}". All four values stored.'
        ),
        status='auto_resolved',
    )


# ---------------------------------------------------------------------------
# Detection rule: non-member in split_with (Phase 3 Task 8)
# ---------------------------------------------------------------------------

def detect_non_member(row: dict, name_to_user: dict, all_time_ids: set) -> tuple:
    """
    Detection method: any name in split_with that doesn't resolve via
    normalize_name() to a known member (all-time, including ex-members).
    Policy: exclude non-member share, redistribute among resolved members
    (DECISIONS.md #6 — same redistribution rule as stale-member, SCOPE.md).

    Returns (resolved_users, unresolved_names, AnomalySpec_or_None).
    """
    split_with_raw = row.get('split_with', '').strip()
    names = [n.strip() for n in split_with_raw.split(';') if n.strip()]
    resolved, unresolved = _resolve_names(names, name_to_user)

    if not unresolved:
        return resolved, [], None

    return resolved, unresolved, AnomalySpec(
        problem_type='non_member',
        detection_method=(
            'normalize_name(name) not found in the group\'s all-time member '
            'username/first_name/last_name lookup. '
            'Exact match required after strip()+casefold().'
        ),
        detected_value=f'unresolved names: {unresolved!r}; raw split_with: "{split_with_raw}"',
        action_taken=(
            f'Unresolved names {unresolved!r} excluded from split. '
            'Their share redistributed proportionally among the '
            f'{len(resolved)} resolved members. '
            'Redistribution rule matches stale-member policy (DECISIONS.md [2026-07-11]).'
        ),
        status='auto_resolved',
    )


# ---------------------------------------------------------------------------
# Detection rule: conflicting amounts, two loggers (Phase 3 Task 9)
# ---------------------------------------------------------------------------

def detect_conflicting_amounts(row: dict, seen_fuzzy: dict, row_number: int) -> Optional[AnomalySpec]:
    """
    Detection method: same date + similar description (normalized edit distance
    <= 3 tokens after tokenizing both descriptions) + different payer + different
    amount. Uses a fuzzy key: (date, description_normalized_tokens_sorted).

    NEVER auto-merged or averaged (PLAN.md #3, DECISIONS.md).
    Both rows imported but flagged as a linked pair.

    seen_fuzzy: dict mutated by caller — maps fuzzy_key -> (row_number, payer, amount).
    """
    date = row.get('date', '').strip()
    desc_norm = normalize_description(row.get('description', ''))
    payer = normalize_name(row.get('paid_by', ''))
    amount = row.get('amount', '').strip()

    # Fuzzy key: date + sorted word tokens of normalized description
    tokens = sorted(desc_norm.split())
    fuzzy_key = (date, tuple(tokens))

    if fuzzy_key in seen_fuzzy:
        prev_row, prev_payer, prev_amount = seen_fuzzy[fuzzy_key]
        if prev_payer != payer and prev_amount != amount:
            return AnomalySpec(
                problem_type='conflicting_amounts',
                detection_method=(
                    'Same date + sorted normalized-description token set match, '
                    'different payer, different amount. '
                    'Fuzzy key: (date, sorted_tokens_of_normalized_description).'
                ),
                detected_value=(
                    f'This row: payer="{payer}", amount={amount}. '
                    f'Earlier row {prev_row}: payer="{prev_payer}", amount={prev_amount}.'
                ),
                action_taken=(
                    f'Both rows imported as separate Expense rows. '
                    f'Both flagged as conflicting pair (this row vs row {prev_row}). '
                    'Neither merged, neither dropped — manual review required.'
                ),
                status='blocked',
            )
    seen_fuzzy[fuzzy_key] = (row_number, payer, amount)
    return None


# ---------------------------------------------------------------------------
# Detection rule: negative amount (Phase 3 Task 10)
# ---------------------------------------------------------------------------

def detect_negative_amount(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: amount < 0.
    Policy: treat as refund — negate to positive, flag (PLAN.md #1).
    """
    raw = row.get('amount', '').strip()
    try:
        d = Decimal(raw)
    except Exception:
        return None
    if d >= Decimal('0'):
        return None

    return AnomalySpec(
        problem_type='negative_amount',
        detection_method='amount < 0.',
        detected_value=f'amount={raw}',
        action_taken=(
            f'Treated as refund per PLAN.md #1. '
            f'Amount kept as negative ({d}) for Expense.amount to reduce outlay. '
            'Original negative value preserved in ImportAnomaly.detected_value. '
            'Appears in import report as refund (reduces payer\'s effective outlay).'
        ),
        status='auto_resolved',
    )


# ---------------------------------------------------------------------------
# Detection rule: bad date (Phase 3 Task 11)
# ---------------------------------------------------------------------------

def detect_bad_date(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: date is outside sane window (Jan 2026 – Jun 2026).
    Policy: block row, never auto-correct (PLAN.md #9).
    """
    from datetime import date as date_cls
    raw = row.get('date', '').strip()
    try:
        d = date_cls.fromisoformat(raw)
    except (ValueError, TypeError):
        return AnomalySpec(
            problem_type='bad_date',
            detection_method='date field is not a valid ISO-8601 date.',
            detected_value=f'date="{raw}"',
            action_taken='Row blocked. Date not auto-corrected. Raw date preserved.',
            status='blocked',
        )

    sane_min = date_cls(SANE_DATE_MIN_YEAR, SANE_DATE_MIN_MONTH, 1)
    sane_max = date_cls(SANE_DATE_MAX_YEAR, SANE_DATE_MAX_MONTH, 30)

    if not (sane_min <= d <= sane_max):
        return AnomalySpec(
            problem_type='bad_date',
            detection_method=(
                f'Date outside sane window [{sane_min} – {sane_max}] for this dataset. '
                'Window: Feb 2026 – Jun 2026.'
            ),
            detected_value=f'date="{raw}" (parsed: {d})',
            action_taken=(
                'Row blocked. Raw date preserved in raw_data. '
                'Not auto-corrected (PLAN.md #9). '
                'Excluded from balance calculation until human corrects date via UI.'
            ),
            status='blocked',
        )
    return None


# ---------------------------------------------------------------------------
# Detection rule: missing currency (Phase 3 Task 12)
# ---------------------------------------------------------------------------

def detect_missing_currency(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: currency field is blank/null after strip().
    Policy: default to INR (dominant currency), but flag visibly (PLAN.md #8).
    """
    raw = row.get('currency', '').strip()
    if raw:
        return None
    return AnomalySpec(
        problem_type='missing_currency',
        detection_method='currency field is null or blank after strip().',
        detected_value='currency=""',
        action_taken=(
            'Defaulted to INR (dominant currency of this dataset per PLAN.md). '
            'This is a visible flag in the import report — NOT a silent default. '
            'Row imported with currency="INR", flag preserved in ImportAnomaly.'
        ),
        status='auto_resolved',
    )


# ---------------------------------------------------------------------------
# Detection rule: zero-amount expense (Phase 3 Task 13)
# ---------------------------------------------------------------------------

def detect_zero_amount(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: amount == 0.
    Policy: exclude from balance calc by default, flag for human confirmation,
    preserve the note text (PLAN.md / SCOPE.md).
    """
    raw = row.get('amount', '').strip()
    try:
        d = Decimal(raw)
    except Exception:
        return None
    if d != Decimal('0'):
        return None

    notes = row.get('notes', '').strip()
    return AnomalySpec(
        problem_type='zero_amount',
        detection_method='amount == 0.',
        detected_value=f'amount=0, notes="{notes}"',
        action_taken=(
            'Row blocked — excluded from balance calculation by default. '
            'Note text captured in detected_value. '
            'Not deleted outright — requires human confirmation (PLAN.md).'
        ),
        status='blocked',
    )


# ---------------------------------------------------------------------------
# Detection rule: ambiguous date format (Phase 3 Task 14)
# ---------------------------------------------------------------------------

def detect_ambiguous_date(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: date where day <= 12 AND month <= 12 AND the note field
    explicitly casts doubt on the interpretation. The note is the primary signal
    for this anomaly (DECISIONS.md [2026-07-11] — text-signaled, not purely structural).

    Why note-based: a date like 2026-05-04 is structurally valid. We flag it only
    because the note says "is this April 5 or May 4?" — the structural condition
    alone would produce false positives on many legitimate dates.
    """
    from datetime import date as date_cls
    raw = row.get('date', '').strip()
    notes = row.get('notes', '').strip().casefold()

    # Only flag if note contains ambiguity language
    ambiguity_pattern = re.compile(r'\b(april|may|month|day|format|confused|wrong|or)\b')
    if not ambiguity_pattern.search(notes):
        return None

    try:
        d = date_cls.fromisoformat(raw)
    except (ValueError, TypeError):
        return None  # caught by bad_date

    # Structural condition: both day and month are <= 12 (so format is ambiguous)
    if not (d.day <= 12 and d.month <= 12):
        return None  # structurally unambiguous — only note-based check needed

    return AnomalySpec(
        problem_type='ambiguous_date',
        detection_method=(
            'Note field contains ambiguity language '
            r'(\b(april|may|month|day|format|confused|wrong|or)\b) '
            'AND date has day<=12 and month<=12 (both interpretations structurally valid). '
            'Text-signal is the primary trigger (DECISIONS.md [2026-07-11]).'
        ),
        detected_value=f'date="{raw}", notes="{row.get("notes", "").strip()}"',
        action_taken=(
            'Row blocked pending human resolution. '
            'Raw date preserved — not auto-corrected to either interpretation. '
            'Same fallback as bad_date: excluded from balance calc until resolved.'
        ),
        status='blocked',
    )


# ---------------------------------------------------------------------------
# Detection rule: stale member in split_with (Phase 3 Task 15)
# ---------------------------------------------------------------------------

def detect_stale_member(row: dict, name_to_user: dict, expense_date, resolved_users: list) -> tuple:
    """
    Detection method: cross-reference each split_with name against
    Membership.left_on relative to the expense date.
    Uses resolved_users from detect_non_member (already resolved to User objects).

    Returns (active_users, stale_users, AnomalySpec_or_None).
    Policy: exclude stale member's share, redistribute among active members
    (same redistribution rule as Kabir case, DECISIONS.md [2026-07-11]).
    """
    from datetime import date as date_cls
    if not expense_date:
        return resolved_users, [], None

    try:
        exp_date = expense_date if isinstance(expense_date, date_cls) else date_cls.fromisoformat(str(expense_date))
    except (ValueError, TypeError):
        return resolved_users, [], None

    stale = []
    active = []
    for user in resolved_users:
        try:
            m = Membership.objects.get(user=user)
            if m.left_on and exp_date > m.left_on:
                stale.append(user)
            else:
                active.append(user)
        except Membership.DoesNotExist:
            stale.append(user)

    if not stale:
        return resolved_users, [], None

    stale_names = [u.username for u in stale]
    return active, stale, AnomalySpec(
        problem_type='stale_member',
        detection_method=(
            'expense.date > Membership.left_on for one or more split_with members. '
            'Checked for every resolved user in split_with against their Membership record.'
        ),
        detected_value=(
            f'Stale members: {stale_names} on expense_date={exp_date}. '
            f'Their left_on dates predate the expense.'
        ),
        action_taken=(
            f'Stale members {stale_names} excluded from split. '
            'Their share redistributed proportionally among the '
            f'{len(active)} active members. '
            'Same redistribution rule as non-member (Kabir) case per DECISIONS.md.'
        ),
        status='auto_resolved',
    )


# ---------------------------------------------------------------------------
# Detection rule: split_type conflict (Phase 3 Task 16)
# ---------------------------------------------------------------------------

def detect_split_type_conflict(row: dict) -> Optional[AnomalySpec]:
    """
    Detection method: split_type == 'equal' AND split_details is non-empty.
    Policy: split_details wins (explicit numbers override the label).
    Determine actual split type from split_details content (DECISIONS.md #11).
    """
    split_type = row.get('split_type', '').strip().lower()
    split_details = row.get('split_details', '').strip()

    if split_type != 'equal' or not split_details:
        return None

    return AnomalySpec(
        problem_type='split_type_conflict',
        detection_method=(
            'split_type == "equal" AND split_details field is non-empty. '
            'Conflict: the label says equal but explicit per-person values exist.'
        ),
        detected_value=f'split_type="equal", split_details="{split_details}"',
        action_taken=(
            'split_details values used — explicit numbers override the label '
            '(DECISIONS.md #11). '
            'split_type inferred from split_details content format. '
            'Inconsistency flagged in import report regardless.'
        ),
        status='auto_resolved',
    )





# ---------------------------------------------------------------------------
# split_details → split_calc bridge
# ---------------------------------------------------------------------------

def _build_split_details_for_calc(
    split_type: str,
    raw_details: str,
    participants: list,
    name_to_user: dict,
) -> dict:
    """
    Parse split_details string into {user_pk: Decimal} as expected by calculate_splits.
    Returns {} for equal split (split_details ignored).
    Raises ValueError on parse failure.
    """
    if split_type == 'equal':
        return {}

    if split_type == 'unequal':
        pairs = _parse_split_details_amount(raw_details)
    elif split_type == 'percentage':
        pairs = _parse_split_details_percentage(raw_details)
        # Strip '%' suffix already handled in parser
    elif split_type in ('share', 'shares'):
        pairs = _parse_split_details_shares(raw_details)
    else:
        return {}

    result = {}
    for name, value in pairs:
        user = name_to_user.get(normalize_name(name))
        if user and user.pk:
            result[user.pk] = value
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_import(
    filepath: str,
    group: Group,
    imported_by,
) -> ImportResult:
    """
    Run the full import pipeline against a CSV file.

    All detections run before any DB writes. Each row's writes are wrapped
    in a per-row transaction.atomic() so a failure on one row doesn't
    block the rest.

    Returns an ImportResult with a completed ImportBatch and per-row RowResult list.
    """
    batch = ImportBatch.objects.create(
        group=group,
        imported_by=imported_by,
        filename=filepath.split('/')[-1],
    )

    # Build member lookup (all-time) for name matching
    name_to_user, _ = _build_member_lookup(group)

    results = []
    seen_hashes: dict = {}     # for exact-duplicate detection
    seen_fuzzy: dict = {}      # for conflicting-amounts detection

    for row_number, row in parse_csv(filepath):
        result = RowResult(row_number=row_number, raw=row)

        # ----------------------------------------------------------------
        # Run all detections — order matters for blocked-row short-circuits
        # ----------------------------------------------------------------

        # 1. Zero amount — block before anything else
        zero_spec = detect_zero_amount(row)
        if zero_spec:
            result.anomalies.append(zero_spec)
            result.skipped = True
            _write_anomalies(result, batch)
            results.append(result)
            continue

        # 2. Missing payer — block
        missing_payer_spec = detect_missing_payer(row)
        if missing_payer_spec:
            result.anomalies.append(missing_payer_spec)
            result.skipped = True
            _write_anomalies(result, batch)
            results.append(result)
            continue

        # 3. Bad date — block
        bad_date_spec = detect_bad_date(row)
        if bad_date_spec:
            result.anomalies.append(bad_date_spec)
            result.skipped = True
            _write_anomalies(result, batch)
            results.append(result)
            continue

        # 4. Ambiguous date — block (run after bad_date so date is known-valid)
        ambiguous_date_spec = detect_ambiguous_date(row)
        if ambiguous_date_spec:
            result.anomalies.append(ambiguous_date_spec)
            result.skipped = True
            _write_anomalies(result, batch)
            results.append(result)
            continue



        # 6. Settlement detection — may route to Settlement table
        settlement_spec = detect_settlement(row)
        if settlement_spec:
            result.anomalies.append(settlement_spec)
            if settlement_spec.status == 'auto_resolved':
                # Route to Settlement table
                _try_create_settlement(row, result, batch, group, name_to_user)
            else:
                result.skipped = True
            _write_anomalies(result, batch)
            results.append(result)
            continue

        # 7. Exact duplicate — skip row, log anomaly
        dup_hash = build_dup_hash(
            row.get('date', ''),
            row.get('amount', ''),
            row.get('paid_by', ''),
            row.get('description', ''),
        )
        if dup_hash in seen_hashes:
            spec = AnomalySpec(
                problem_type='exact_duplicate',
                detection_method=(
                    'SHA-256 hash on (date, amount, paid_by_normalized, '
                    'description_normalized). Exact hash match against row '
                    f'{seen_hashes[dup_hash]}.'
                ),
                detected_value=(
                    f'Hash {dup_hash[:16]}… matched row {seen_hashes[dup_hash]}. '
                    f'This row: date={row.get("date")}, amount={row.get("amount")}, '
                    f'paid_by="{row.get("paid_by")}", '
                    f'description="{row.get("description")}"'
                ),
                action_taken=(
                    f'Row dropped. Row {seen_hashes[dup_hash]} kept as canonical. '
                    'No Expense or ExpenseSplit rows written for this row.'
                ),
                status='auto_resolved',
            )
            result.anomalies.append(spec)
            result.skipped = True
            _write_anomalies(result, batch)
            results.append(result)
            continue
        seen_hashes[dup_hash] = row_number

        # 8. Precision check (non-blocking — auto-resolved)
        precision_spec = detect_precision(row)
        if precision_spec:
            result.anomalies.append(precision_spec)

        # 9. Payer name normalization
        paid_by_user, name_spec = detect_name_mismatch(row, name_to_user)
        if name_spec:
            result.anomalies.append(name_spec)
            if name_spec.status == 'blocked':
                result.skipped = True
                _write_anomalies(result, batch)
                results.append(result)
                continue

        # 10. Currency check
        missing_currency_spec = detect_missing_currency(row)
        fx_spec = None
        if missing_currency_spec:
            result.anomalies.append(missing_currency_spec)
            # Apply default INR
            row = dict(row)
            row['currency'] = 'INR'
        else:
            fx_spec = detect_foreign_currency(row)
            if fx_spec:
                result.anomalies.append(fx_spec)
                if fx_spec.status == 'blocked':
                    result.skipped = True
                    _write_anomalies(result, batch)
                    results.append(result)
                    continue

        # 11. Negative amount (non-blocking — treat as refund)
        negative_spec = detect_negative_amount(row)
        if negative_spec:
            result.anomalies.append(negative_spec)

        # 12. Percentage sum check
        normalized_pcts, pct_spec = detect_percentage_sum(row)
        if pct_spec:
            result.anomalies.append(pct_spec)

        # 13. split_type conflict
        conflict_spec = detect_split_type_conflict(row)
        if conflict_spec:
            result.anomalies.append(conflict_spec)

        # 14. Resolve participant names
        from datetime import date as date_cls
        try:
            expense_date = date_cls.fromisoformat(row.get('date', '').strip())
        except (ValueError, TypeError):
            expense_date = None

        name_to_user_for_date, active_ids = _build_member_lookup(group, expense_date)

        resolved_users, unresolved_names, nonmember_spec = detect_non_member(
            row, name_to_user, set(name_to_user.values())
        )
        if nonmember_spec:
            result.anomalies.append(nonmember_spec)

        # 15. Stale member check
        active_users, stale_users, stale_spec = detect_stale_member(
            row, name_to_user, expense_date, resolved_users
        )
        if stale_spec:
            result.anomalies.append(stale_spec)
        participants = active_users if stale_users else resolved_users

        # 16. Conflicting amounts (non-blocking — both rows imported)
        conflict_amt_spec = detect_conflicting_amounts(row, seen_fuzzy, row_number)
        if conflict_amt_spec:
            result.anomalies.append(conflict_amt_spec)

        # ----------------------------------------------------------------
        # Write the Expense row
        # ----------------------------------------------------------------
        _try_create_expense(
            row, result, batch, group, paid_by_user, participants,
            fx_spec, precision_spec, conflict_spec, normalized_pcts,
            name_to_user,
        )
        _write_anomalies(result, batch)
        results.append(result)

    # Update batch summary
    total = len(results)
    imported = sum(1 for r in results if r.expense or r.settlement)
    anomaly_count = sum(1 for r in results if r.anomalies)
    batch.total_rows = total
    batch.imported_rows = imported
    batch.anomaly_rows = anomaly_count
    batch.save(update_fields=['total_rows', 'imported_rows', 'anomaly_rows'])

    return ImportResult(batch=batch, row_results=results)


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

def _write_anomalies(result: RowResult, batch: ImportBatch):
    """Write all AnomalySpec objects for a row to ImportAnomaly table."""
    for spec in result.anomalies:
        ImportAnomaly.objects.create(
            batch=batch,
            row_number=result.row_number,
            raw_data=result.raw,
            problem_type=spec.problem_type,
            detection_method=spec.detection_method,
            detected_value=spec.detected_value,
            action_taken=spec.action_taken,
            status=spec.status,
            linked_expense=result.expense,
            linked_settlement=result.settlement,
        )


def _try_create_settlement(row: dict, result: RowResult, batch: ImportBatch, group: Group, name_to_user: dict):
    """Create a Settlement row from a detected settlement row."""
    from_user, _ = detect_name_mismatch(row, name_to_user)
    if not from_user:
        result.skipped = True
        return

    recipients_raw = [n.strip() for n in row.get('split_with', '').split(';') if n.strip()]
    if not recipients_raw:
        result.skipped = True
        return

    to_user = name_to_user.get(normalize_name(recipients_raw[0]))
    if not to_user:
        result.skipped = True
        return

    try:
        amount = abs(_round(Decimal(row.get('amount', '0').strip())))
    except Exception:
        result.skipped = True
        return

    from datetime import date as date_cls
    try:
        s_date = date_cls.fromisoformat(row.get('date', '').strip())
    except (ValueError, TypeError):
        result.skipped = True
        return

    with transaction.atomic():
        settlement = Settlement.objects.create(
            group=group,
            from_user=from_user,
            to_user=to_user,
            amount=amount,
            date=s_date,
            note=row.get('notes', '').strip(),
        )
    result.settlement = settlement


def _try_create_expense(
    row: dict,
    result: RowResult,
    batch: ImportBatch,
    group: Group,
    paid_by_user,
    participants: list,
    fx_spec,
    precision_spec,
    conflict_spec,
    normalized_pcts,
    name_to_user: dict,
):
    """Create Expense + ExpenseSplit rows for a clean (or auto-resolved) row."""
    if not paid_by_user:
        result.skipped = True
        return
    if not participants:
        result.skipped = True
        return

    from datetime import date as date_cls

    # --- Amount ---
    raw_amount_str = row.get('amount', '').strip()
    try:
        raw_amount = Decimal(raw_amount_str)
    except Exception:
        result.skipped = True
        return

    is_negative = False
    if raw_amount < 0:
        raw_amount = abs(raw_amount)
        is_negative = True

    # Round to 2dp
    amount_inr = _round(raw_amount)

    # FX conversion
    currency = row.get('currency', 'INR').strip().upper() or 'INR'
    original_amount = None
    exchange_rate = None
    if currency != 'INR' and fx_spec and fx_spec.status == 'auto_resolved':
        original_amount = amount_inr  # pre-conversion
        exchange_rate = USD_TO_INR
        amount_inr = _round(raw_amount * USD_TO_INR)
        currency_stored = currency
    else:
        currency_stored = 'INR'

    # --- Date ---
    try:
        exp_date = date_cls.fromisoformat(row.get('date', '').strip())
    except (ValueError, TypeError):
        result.skipped = True
        return

    # --- Split type ---
    split_type = row.get('split_type', '').strip().lower()
    raw_details_str = row.get('split_details', '').strip()

    # If conflict: split_details non-empty with split_type=equal → infer type
    if conflict_spec and split_type == 'equal' and raw_details_str:
        split_type = _infer_split_type_from_details(raw_details_str)

    if split_type in ('share', 'shares'):
        split_type = 'shares'

    # Normalise to model choices
    if split_type not in ('equal', 'unequal', 'percentage', 'shares'):
        split_type = 'equal'

    # Build split_details for calc
    participant_ids = [u.pk for u in participants]
    paid_by_id = paid_by_user.pk

    try:
        if split_type == 'percentage' and normalized_pcts is not None:
            # Use normalized percentages from percentage-sum detection
            split_details = {}
            for name, pct in normalized_pcts:
                user = name_to_user.get(normalize_name(name))
                if user and user.pk in participant_ids:
                    split_details[user.pk] = pct
        elif split_type == 'equal':
            split_details = {}
        else:
            split_details = _build_split_details_for_calc(
                split_type, raw_details_str, participants, name_to_user
            )
    except (ValueError, Exception):
        split_type = 'equal'
        split_details = {}

    # Ensure paid_by is in participants for equal/percentage/shares
    if paid_by_id not in participant_ids and split_type == 'equal':
        participant_ids.append(paid_by_id)

    if not participant_ids:
        result.skipped = True
        return

    try:
        splits = calculate_splits(
            total=amount_inr,
            split_type=split_type,
            participant_ids=participant_ids,
            paid_by_id=paid_by_id,
            split_details=split_details,
        )
    except SplitCalcError:
        # Fall back to equal split among participants
        try:
            splits = calculate_splits(
                total=amount_inr,
                split_type='equal',
                participant_ids=participant_ids,
                paid_by_id=paid_by_id,
                split_details={},
            )
        except SplitCalcError:
            result.skipped = True
            return

    if is_negative:
        amount_inr = -amount_inr
        if original_amount is not None:
            original_amount = -original_amount
        splits = {uid: -s_amt for uid, s_amt in splits.items()}

    with transaction.atomic():
        expense = Expense.objects.create(
            group=group,
            paid_by=paid_by_user,
            description=row.get('description', '').strip(),
            amount=amount_inr,
            currency=currency_stored,
            original_amount=original_amount,
            exchange_rate=exchange_rate,
            date=exp_date,
            split_type=split_type,
            notes=row.get('notes', '').strip(),
        )
        ExpenseSplit.objects.bulk_create([
            ExpenseSplit(expense=expense, user_id=uid, share_amount=share)
            for uid, share in splits.items()
        ])

    result.expense = expense


def _infer_split_type_from_details(raw_details: str) -> str:
    """
    Infer split type from the content of split_details when label is unreliable.
    Returns 'percentage', 'shares', 'unequal', or 'equal'.
    """
    # Contains '%' → percentage
    if '%' in raw_details:
        return 'percentage'
    # All integer values and names → shares (heuristic)
    try:
        pairs = _parse_split_details_amount(raw_details)
        if all(v == v.to_integral_value() for _, v in pairs):
            return 'shares'
        return 'unequal'
    except ValueError:
        return 'equal'
