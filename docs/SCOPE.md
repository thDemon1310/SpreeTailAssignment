# SCOPE.md — Anomaly Register + Schema Notes

## Anomaly Table

Kept live as import pipeline is built. One row per anomaly type per GEMINI.md Section 4.

| # | Anomaly | Detection method | Rows affected | Policy applied | Reversible in UI? |
|---|---------|-----------------|---------------|----------------|-------------------|
| 1 | Exact duplicate expense | SHA-256 hash on (date, amount, paid_by_normalized, description_normalized with stopwords+punctuation stripped). Exact hash match = duplicate. | Row 6 (dinner - marina bites = dup of row 5) | Second occurrence dropped, first kept, anomaly logged as `auto_resolved`. | No — cannot un-import a dropped row without re-running import. |
| 2 | Non-standard precision amount | `Decimal(raw) != Decimal(raw).quantize(0.01, ROUND_HALF_UP)` — any amount with >2dp. | Row 10 (Cylinder refill, 899.995) | Round ROUND_HALF_UP to 2dp; store raw + rounded in ImportAnomaly.detected_value; rounded value used for Expense.amount and splits. | No — amount stored at 2dp. Original preserved in ImportAnomaly. |
| 3 | Inconsistent payer name casing/format | normalize_name(paid_by) = strip+casefold; exact match in member lookup. Mismatch but match-after-normalize = auto_resolved. No match = blocked. | Row 9 (priya→Priya auto), Row 11 (Priya S→blocked), Row 27 (rohan →Rohan auto) | Auto-map if unique match after normalization; block if no match — never fuzzy-create. | blocked rows: yes via manual-mapping UI. auto-resolved rows: no. |
| 4 | Missing paid_by | paid_by is null or blank after strip(). | Row 13 (House cleaning supplies) | Block row entirely. No Expense written. Human must assign payer via UI before row enters balance calc. | Yes — human can assign payer via UI. |
| 5 | Settlement/Deposit logged as expense | All three: split_type blank + single recipient in split_with + description matches `\b(paid|repaid|returned|gave|sent|back|settled|settlement|deposit|transfer|advance|moving in|moved in)\b`. Two-of-three = blocked. | Row 14 (Rohan paid Aisha back), Row 38 (Sam deposit share - scores 2/3) | Auto-route to Settlement table (not Expense) if 3/3. Fallback: 2/3 conditions = blocked for manual review. | No — Settlement row created. Human cannot revert without deleting the Settlement row directly. |
| 6 | Percentages not summing to 100% | Sum split_details percentages; compare to 100 ± 0.01. | Row 15 (Pizza Friday 30+30+30+20=110%) | Normalize proportionally; store raw sum + normalized values in ImportAnomaly. Expense created with normalized percentages. | No — normalized values stored. Original preserved in ImportAnomaly. |
| 7 | Foreign currency row | currency != 'INR' (after strip+upper). | Rows 20, 21, 23, 26 (USD rows: Goa villa, Beach shack, Parasailing, Parasailing refund) | Convert using fixed rate 1 USD = 83.50 INR. Store original_amount, exchange_rate, currency, converted amount. All four fields stored on Expense row. | No — conversion rate is fixed. Re-import needed to change rate. |
| 8 | Non-member in split_with | normalize_name(name) not in all-time group member lookup after strip+casefold. | Row 23 (Dev's friend Kabir) | Exclude non-member from split; redistribute their share proportionally among resolved members. Raw name stored in ImportAnomaly. | No — Kabir's share already redistributed on Expense row. |
| 9 | Same expense, conflicting amounts, two loggers | Same date + sorted normalized-description token set match + different payer + different amount. | Rows 24+25 (Thalassa dinner, Aisha ₹2400 vs Rohan ₹2450) | Both rows imported as separate Expenses. Both flagged as conflicting pair (status=blocked). Neither merged, neither dropped — manual review required. | Yes — human can delete either row via UI. |
| 10 | Negative amount | amount < 0. | Row 26 (Parasailing refund, -30 USD) | Treat as refund: negate to positive, flag in import report. Reduces payer's effective outlay. | No — stored as positive amount. Original negative value in ImportAnomaly. |
| 11 | Corrupted/implausible date | Date outside sane window Feb 2026 – Jun 2026 (inclusive). | Row 27 (Airport cab, 2014-03-01) | Block row. Raw date preserved. Excluded from balance calc until human corrects date via UI. | Yes — human can correct date via UI. |
| 12 | Missing currency | currency field blank/null after strip(). | Row 28 (Groceries DMart 2026-03-15) | Default to INR (dominant dataset currency). Visible flag in import report — NOT silent. | No — INR applied. Original blank preserved in ImportAnomaly. |
| 13 | Zero-amount expense | amount == 0. | Row 31 (Dinner order Swiggy, "counted twice earlier") | Block row. Note text captured. Excluded from balance calc. Not deleted — requires human confirmation. | Yes — human can confirm/delete via UI. |
| 14 | Ambiguous date format | Note field contains ambiguity language (`\b(april|may|month|day|format|confused|wrong|or)\b`) AND date has day≤12 and month≤12 (both interpretations structurally valid). Text-signal is primary trigger. | Row 34 (Deep cleaning service, 2026-05-04, note questions April 5 or May 4) | Block row. Raw date preserved. Excluded from balance calc until human resolves. | Yes — human can confirm date via UI. |
| 15 | Stale member in split_with after left_on | expense.date > Membership.left_on for any resolved split_with member. | Row 36 (Groceries BigBasket 2026-04-02 includes Meera, who left end of March) | Exclude stale member from split; redistribute their share proportionally among active members. Same redistribution rule as Kabir (anomaly #8). | No — split already computed without stale member. |
| 16 | split_type=equal but split_details non-empty | split_type == 'equal' AND split_details is non-empty. | Row 42 (Furniture for common room — says equal but has per-person shares) | split_details wins (explicit numbers override label, DECISIONS.md #11). Infer actual type from split_details format. Flag inconsistency in report. | No — split already computed from split_details. |

---

## Schema Notes

Schema is defined in [`core/models.py`](../backend/core/models.py).

### `core_user` (User)
Extends Django's `AbstractUser`. Fields inherited: `username`, `email`, `password`, `first_name`, `last_name`. No additional fields added yet. Using `AUTH_USER_MODEL = 'core.User'` lets us add fields in future migrations without pain.

### `core_group` (Group)
A shared-expense household/trip group. `created_by` is FK to User (the person who created it). Members are tracked via `Membership`, not a direct M2M, because we need join/leave dates per member — a plain M2M cannot carry that data.

### `core_membership` (Membership)
**The key table.** One row per (user, group) pair. `joined_on` is required; `left_on` is nullable (null = still active). Unique constraint on (user, group) ensures one active membership per person per group. The `is_active_on(date)` helper answers "was this person a member when this expense happened?" — used by balance_calc and the importer's stale-member check. Every balance calculation filters through this table.

### `core_expense` (Expense)
One row per shared expense. `amount` is always in INR (converted from original currency if needed). `original_amount` and `exchange_rate` store the pre-conversion values so nothing is lossy. `split_type` is one of equal/unequal/percentage/shares — determines how `ExpenseSplit` rows were computed but is never re-used to recompute (splits are stored, not recomputed).

### `core_expense_split` (ExpenseSplit)
**The source of truth for balances.** One row per (expense, user) pair. `share_amount` is the computed per-person share in INR, rounded ROUND_HALF_UP to 2dp with the payer absorbing the rounding remainder. Every balance number visible on screen must be traceable to rows in this table — no recomputing at display time (Rohan's "no magic numbers" requirement).

### `core_settlement` (Settlement)
A one-to-one payment between two users — separate from Expense. Stored here instead of in Expense because a settlement must NOT be split among everyone in the group; it is a direct debt clearance between exactly two people. `from_user` is the debtor paying, `to_user` is the creditor receiving.

### `core_import_batch` (ImportBatch)
One row per CSV import run. Links all anomalies and imported expenses back to a single operation for audit trail. `total_rows`, `imported_rows`, `anomaly_rows` are summary counters updated at the end of `run_import()`.

### `core_import_anomaly` (ImportAnomaly)
**This table IS the import report.** One row per detected anomaly per CSV row. Fields: `row_number` (1-indexed), `raw_data` (verbatim CSV row as JSON), `problem_type` (one of 18 choices), `detection_method` (exact rule/heuristic), `detected_value` (the triggering value), `action_taken` (what the importer did), `status` (auto_resolved / blocked / manually_resolved), `linked_expense` and `linked_settlement` (nullable FKs for traceability). A row can have multiple anomaly entries (e.g. foreign currency + name mismatch on the same row).

---

## Policies (summary — full entries in DECISIONS.md)

1. Negative amounts → refund (positive amount), flagged
2. Exact duplicates → auto-drop second, keep first
3. Same expense, different amounts → both imported, both flagged
4. Settlement disguised as expense → route to Settlement table
5. Currency conversion → fixed rate 1 USD = 83.50 INR; store all four fields
6. Kabir (non-member) → exclude + redistribute, same rule as stale member
7. Stale member → exclude + redistribute, based on Membership.left_on
8. Missing payer/currency → block (payer) or default+flag (currency)
9. Bad/ambiguous dates → block, never auto-correct
10. Percentages over 100% → normalize proportionally, flag loudly
11. split_type vs split_details conflict → split_details wins
12. Rounding → ROUND_HALF_UP 2dp everywhere, payer absorbs remainder
13. Messy names → normalize exact-match; no fuzzy-auto-create
