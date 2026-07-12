# Import Report
**File:** data/expenses_export.csv
**Total rows processed:** 42
**Rows successfully imported (or auto-resolved):** 33
**Rows with anomalies:** 20

## Anomalies
### Row 5: exact_duplicate (auto_resolved)
- **Detection Method:** SHA-256 hash on (date, amount, paid_by_normalized, description_normalized). Exact hash match against row 4.
- **Detected Value:** Hash 2d55a4e68e2fa235… matched row 4. This row: date=2026-02-08, amount=3200.0, paid_by="Dev", description="dinner - marina bites"
- **Action Taken:** Row dropped. Row 4 kept as canonical. No Expense or ExpenseSplit rows written for this row.

### Row 8: name_mismatch (auto_resolved)
- **Detection Method:** strip()+casefold() of paid_by matched a known member username but the raw string differs from the stored username.
- **Detected Value:** raw="priya", matched_to="Priya" (id=3)
- **Action Taken:** Auto-mapped to user "Priya" (id=3). Expense created with correct paid_by FK. Raw name preserved in detected_value.

### Row 9: precision (auto_resolved)
- **Detection Method:** Amount string has more than 2 decimal places. Rule: any amount where Decimal(raw) != Decimal(raw).quantize(0.01, ROUND_HALF_UP).
- **Detected Value:** raw=899.995, rounded=900.00
- **Action Taken:** Amount rounded ROUND_HALF_UP from 899.995 to 900.00. Both values stored in ImportAnomaly.detected_value. rounded value used for Expense.amount and split calculation.

### Row 10: name_mismatch (blocked)
- **Detection Method:** strip()+casefold() of paid_by did not match any known member username. Exact match required — fuzzy auto-create is never done (DECISIONS.md #13).
- **Detected Value:** raw="Priya S", normalized="priya s", no member matched
- **Action Taken:** Row blocked. No Expense written. Unmatched name preserved in detected_value for manual mapping.

### Row 12: missing_payer (blocked)
- **Detection Method:** paid_by field is null or blank after strip().
- **Detected Value:** paid_by=""
- **Action Taken:** Row blocked. Full row preserved in raw_data. No Expense written. Excluded from balance calculation until a human assigns a payer through the UI.

### Row 13: settlement_as_expense (auto_resolved)
- **Detection Method:** All three conditions met: split_type blank, split_with has exactly one name, description matches regex \b(paid|repaid|returned|gave|sent|back|settled|settlement|deposit|transfer|advance|moving in|moved in)\b.
- **Detected Value:** description="Rohan paid Aisha back", split_type="", split_with="Aisha"
- **Action Taken:** Row routed to Settlement table (not Expense). Original row referenced by row_number in ImportAnomaly for audit.

### Row 14: percentage_sum (auto_resolved)
- **Detection Method:** Sum of split_details percentages = 110 (expected 100 ± 0.01). Normalization applied proportionally.
- **Detected Value:** raw_sum=110, raw_details="Aisha 30%; Rohan 30%; Priya 30%; Meera 20%"
- **Action Taken:** Percentages normalized proportionally to sum to 100. Normalized values: Aisha 27.2727%; Rohan 27.2727%; Priya 27.2727%; Meera 18.1818%. Both raw and normalized values stored in ImportAnomaly.detected_value.

### Row 19: foreign_currency (auto_resolved)
- **Detection Method:** currency field is not INR; converted using fixed rate 1 USD = 83.50 INR (DECISIONS.md [2026-07-11]).
- **Detected Value:** original_amount=540.0 USD, exchange_rate=83.50, converted_amount=45090.00 INR
- **Action Taken:** Expense.amount set to converted value 45090.00 INR. Expense.original_amount=540.0, Expense.exchange_rate=83.50, Expense.currency="USD". All four values stored.

### Row 20: foreign_currency (auto_resolved)
- **Detection Method:** currency field is not INR; converted using fixed rate 1 USD = 83.50 INR (DECISIONS.md [2026-07-11]).
- **Detected Value:** original_amount=84.0 USD, exchange_rate=83.50, converted_amount=7014.00 INR
- **Action Taken:** Expense.amount set to converted value 7014.00 INR. Expense.original_amount=84.0, Expense.exchange_rate=83.50, Expense.currency="USD". All four values stored.

### Row 22: ambiguous_date (blocked)
- **Detection Method:** Note field contains ambiguity language (\b(april|may|month|day|format|confused|wrong|or)\b) AND date has day<=12 and month<=12 (both interpretations structurally valid). Text-signal is the primary trigger (DECISIONS.md [2026-07-11]).
- **Detected Value:** date="2026-03-11", notes="Kabir joined for the day"
- **Action Taken:** Row blocked pending human resolution. Raw date preserved — not auto-corrected to either interpretation. Same fallback as bad_date: excluded from balance calc until resolved.

### Row 24: ambiguous_date (blocked)
- **Detection Method:** Note field contains ambiguity language (\b(april|may|month|day|format|confused|wrong|or)\b) AND date has day<=12 and month<=12 (both interpretations structurally valid). Text-signal is the primary trigger (DECISIONS.md [2026-07-11]).
- **Detected Value:** date="2026-03-11", notes="Aisha also logged this I think hers is wrong"
- **Action Taken:** Row blocked pending human resolution. Raw date preserved — not auto-corrected to either interpretation. Same fallback as bad_date: excluded from balance calc until resolved.

### Row 25: foreign_currency (auto_resolved)
- **Detection Method:** currency field is not INR; converted using fixed rate 1 USD = 83.50 INR (DECISIONS.md [2026-07-11]).
- **Detected Value:** original_amount=-30.0 USD, exchange_rate=83.50, converted_amount=-2505.00 INR
- **Action Taken:** Expense.amount set to converted value -2505.00 INR. Expense.original_amount=-30.0, Expense.exchange_rate=83.50, Expense.currency="USD". All four values stored.

### Row 25: negative_amount (auto_resolved)
- **Detection Method:** amount < 0.
- **Detected Value:** amount=-30.0
- **Action Taken:** Treated as refund per PLAN.md #1. Amount kept as negative (-30.0) for Expense.amount to reduce outlay. Original negative value preserved in ImportAnomaly.detected_value. Appears in import report as refund (reduces payer's effective outlay).

### Row 26: bad_date (blocked)
- **Detection Method:** Date outside sane window [2026-02-01 – 2026-06-30] for this dataset. Window: Feb 2026 – Jun 2026.
- **Detected Value:** date="2014-03-01" (parsed: 2014-03-01)
- **Action Taken:** Row blocked. Raw date preserved in raw_data. Not auto-corrected (PLAN.md #9). Excluded from balance calculation until human corrects date via UI.

### Row 27: missing_currency (auto_resolved)
- **Detection Method:** currency field is null or blank after strip().
- **Detected Value:** currency=""
- **Action Taken:** Defaulted to INR (dominant currency of this dataset per PLAN.md). This is a visible flag in the import report — NOT a silent default. Row imported with currency="INR", flag preserved in ImportAnomaly.

### Row 30: zero_amount (blocked)
- **Detection Method:** amount == 0.
- **Detected Value:** amount=0, notes="counted twice earlier - fixing later"
- **Action Taken:** Row blocked — excluded from balance calculation by default. Note text captured in detected_value. Not deleted outright — requires human confirmation (PLAN.md).

### Row 31: percentage_sum (auto_resolved)
- **Detection Method:** Sum of split_details percentages = 110 (expected 100 ± 0.01). Normalization applied proportionally.
- **Detected Value:** raw_sum=110, raw_details="Aisha 30%; Rohan 30%; Priya 30%; Meera 20%"
- **Action Taken:** Percentages normalized proportionally to sum to 100. Normalized values: Aisha 27.2727%; Rohan 27.2727%; Priya 27.2727%; Meera 18.1818%. Both raw and normalized values stored in ImportAnomaly.detected_value.

### Row 33: ambiguous_date (blocked)
- **Detection Method:** Note field contains ambiguity language (\b(april|may|month|day|format|confused|wrong|or)\b) AND date has day<=12 and month<=12 (both interpretations structurally valid). Text-signal is the primary trigger (DECISIONS.md [2026-07-11]).
- **Detected Value:** date="2026-05-04", notes="is this April 5 or May 4? format is a mess"
- **Action Taken:** Row blocked pending human resolution. Raw date preserved — not auto-corrected to either interpretation. Same fallback as bad_date: excluded from balance calc until resolved.

### Row 35: stale_member (auto_resolved)
- **Detection Method:** expense.date > Membership.left_on for one or more split_with members. Checked for every resolved user in split_with against their Membership record.
- **Detected Value:** Stale members: ['Meera'] on expense_date=2026-04-02. Their left_on dates predate the expense.
- **Action Taken:** Stale members ['Meera'] excluded from split. Their share redistributed proportionally among the 3 active members. Same redistribution rule as non-member (Kabir) case per DECISIONS.md.

### Row 37: settlement_as_expense (blocked)
- **Detection Method:** Two of three settlement conditions met (score=2): blank_split_type=False, single_recipient=True, desc_matches=True. Low confidence — not auto-routed.
- **Detected Value:** description="Sam deposit share", split_type="equal", split_with="Aisha"
- **Action Taken:** Row blocked for manual review. Not auto-routed to Settlement.

### Row 41: split_type_conflict (auto_resolved)
- **Detection Method:** split_type == "equal" AND split_details field is non-empty. Conflict: the label says equal but explicit per-person values exist.
- **Detected Value:** split_type="equal", split_details="Aisha 1; Rohan 1; Priya 1; Sam 1"
- **Action Taken:** split_details values used — explicit numbers override the label (DECISIONS.md #11). split_type inferred from split_details content format. Inconsistency flagged in import report regardless.
