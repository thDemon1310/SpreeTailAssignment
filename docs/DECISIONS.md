## 2026-07-11 Decision: Reset dev DB after AUTH_USER_MODEL ordering mistake
### comit : 8a110a07
**Options considered:**
A. Reset the local Postgres DB and regenerate migrations cleanly
B. Hand-write a data migration to swap admin's User FK to the new model in place
**Chosen:** A — reset the DB
**Why:** No real data existed yet (pre-import, day 1), so a clean reset is faster and
lower-risk than surgically rewriting Django's own admin/auth migrations, which is
fragile and easy to get subtly wrong.
**Tradeoff accepted:** would NOT choose this once real data exists (post-import) —
at that point option B or a proper data migration becomes mandatory. Noting this now
so it isn't repeated as a reflex later in the project.
**Reversible?** yes, trivially, since it happened before any data existed.

**Update 2026-07-11:** The original reset (logged above) did not actually fix
the root cause — AUTH_USER_MODEL was reset in the DB but not confirmed set in
settings.py before the following migrate. Lesson for this project: "reset the
DB" is not itself a fix, only a precondition; the actual fix is ensuring
AUTH_USER_MODEL is correct *before* the reset's migrate runs.

## 2026-07-11 Decision: changing the model because limit hit
You're taking over this project from Claude Opus 4.6 mid-way through. Before writing anything:

1. Read GEMINI.md in the project root — that's your operating contract (gates, commit discipline, test-first rule, log formats). Follow it exactly, don't relax it because you're new to this session.
2. Read TODO.md — note we just completed Phase 1 Task 4 and are sitting at GATE 1 (schema review), which the human has now completed. Confirm with me that Phase 1 is fully checked off before you start Phase 2 Task 1.
3. Read PLAN.md Section 3 (the anomaly policies) and DECISIONS.md — these are binding, not suggestions. Don't re-derive or second-guess decisions already logged there.
4. Read core/models.py and core/tests.py as they currently exist — match existing code style and conventions (naming, docstring density, test structure) rather than introducing your own.
5. Read AI_ACTIONS_LOG.md, especially the two migration-ordering entries — this shows the kind of mistake that's already happened once in this project (root-cause vs. symptom fixes). Don't repeat that pattern.

Once you've confirmed all of that, start Phase 2 Task 1: the split calculation function (equal/unequal/percentage/share) as a standalone, unit-tested pure function — tests written and passing BEFORE it's wired to any API view, per GEMINI.md Section 3. Do not skip straight to the view.

Stop and ask me before making any judgment call not already covered by PLAN.md or DECISIONS.md — especially anything touching rounding, since that policy needs to be nailed down here and applied consistently for the rest of the project.

## [2026-07-11] Decision: Rounding remainder assignment in split_calc
**Options considered:**
A. Assign the 1-paisa remainder to the payer's own share (payer absorbs rounding)
B. Assign the remainder to the first person in the split list (arbitrary but deterministic)
**Chosen:** A — remainder goes to the payer
**Why:** SCOPE.md #12 already mandates ROUND_HALF_UP to 2dp everywhere. That rule alone does not guarantee sum(splits) == total — e.g. ₹100 ÷ 3 = ₹33.33 × 3 = ₹99.99 (1 paisa short). Someone must absorb the difference. The payer is the natural absorber: they already handled the money, they can see their own payment vs. their share in the UI, and "payer gets the rounding difference" is a one-sentence explanation that anyone can verify by hand. No new concept introduced.
**Tradeoff accepted:** The payer's share will occasionally differ by ±1 paisa from a pure equal/percentage/share calculation. This is visible in ExpenseSplit rows if you look at them directly. It is NOT a bug — it is the documented policy. Anyone hand-tracing a balance must account for this.
**Reversible?** Yes — the adjustment is isolated to split_calc.py. Changing it would require recomputing all existing ExpenseSplit rows, which is a data migration, so treat it as irreversible once real data exists.

## [2026-07-11]  3 failures. Diagnosing root causes 
### Failure 1 —  test_two_expenses_different_payers :  Rohan balance = -50  but expected  +50 
- The settlement formula was wrong on first write ( received - made  instead of  made - received ). Caught by 3 failing tests, root cause diagnosed, fixed — not patched
  around. Logged in AI_ACTIONS_LOG.md.

## ⚠ Agent execution terminated due to error.
Error ID: 61c6ad39-b9d1-4f28-90dc-199983f25775-391
- The previous session crashed mid-edit to TODO.md, right after marking Phase 2
  Task 4 in-progress. Before continuing: re-read TODO.md and confirm its current
  state is coherent (no duplicate/corrupted entries from the crash). Re-read
  core/models.py, the split calculation function, and its tests to confirm the
  last commit is what you're building on top of — don't assume the in-progress
  marker means real work was done. Then proceed with Phase 2 Task 4: Expense
  create/list/detail API wired to the tested split function.

## [2026-07-11] Decision: Defer Phase 2 Task 5 (Settlement create/list API)
**Options considered:** A. Build it before Phase 3. B. Defer it — human explicitly directed to Phase 3 after GATE 2 approval.
**Chosen:** B — deferred by human instruction at GATE 2 approval.
**Why:** Human owner of the project explicitly said "GATE 2 approved. Continue to Phase 3." Task 5 remains `[ ]` in TODO.md and must be completed before GATE 5 (final). Balance calculation already works at the DB/function level; the API wrapper is not required for the import pipeline.
**Tradeoff accepted:** Settlement create/list API is not accessible via REST until Phase 2 Task 5 is re-addressed. The balance_calc function already reads Settlement rows, so imported settlements will count in balances correctly.
**Reversible?** Yes — Task 5 is still in TODO.md.

## [2026-07-11] Decision: Settlement detection heuristic (import pipeline)
**Options considered:**
A. Blank split_type AND single name in split_with AND description regex match.
B. Any row with a single split_with recipient, regardless of split_type.
C. Pure description regex, no structural check.
**Chosen:** A — all three conditions must hold simultaneously.
**Why:** Option B would misclassify "Sam deposit share" (row 38) which has split_type=equal and is a deposit, not a settlement. Option C alone has too many false positives. The three-way conjunction is high-confidence: (1) split_type blank signals the logger didn't know what category it was; (2) single recipient is structurally different from a shared expense; (3) description regex `r'\b(paid|repaid|returned|gave|sent|back|settled|settlement)\b'` (case-insensitive) catches common payment language. All three failing means not auto-routed.
**Settlement description regex:** `re.search(r'\b(paid|repaid|returned|gave|sent|back|settled|settlement)\b', description, re.IGNORECASE)` — match on whole words only to avoid false hits on e.g. "backdrop."
**Fallback:** If two conditions hold but not three (low-confidence), route to `blocked` anomaly for human review, do not auto-route.
**Tradeoff accepted:** Rows that are clearly settlements but miss the description pattern go to manual review instead of being auto-routed. Better than auto-routing something that isn't a settlement.
**Reversible?** Yes — detection is isolated to the importer.

## [2026-07-11] Decision: Deposit/transfer detection heuristic (import pipeline)
**Options considered:**
A. Reuse settlement detection rule (same TODO item says "note explicitly whether this trips the same rule").
B. Separate rule: split_type non-blank AND single name in split_with AND description regex.
**Chosen:** B — separate rule. Row 38 "Sam deposit share" has split_type=equal (not blank), so it does NOT trip the settlement rule (which requires blank split_type). It needs its own detection.
**Deposit description regex:** `re.search(r'\b(deposit|transfer|advance|moving in|moved in)\b', description, re.IGNORECASE)`.
**Additional structural signal:** single name in split_with (one-to-one payment, not a group split).
**Storage/fallback:** Same as settlement item — routed to `blocked` anomaly, action_taken = "flagged as possible deposit/transfer", status = "blocked". Linked to no expense until human confirms.
**Tradeoff accepted:** A legitimate one-person expense (e.g. paying someone back for a personal item) could trip this if the description contains "deposit." That is acceptable — the flag goes to human review, not silent discard.
**Reversible?** Yes.

## [2026-07-11] Decision: FX conversion rate for USD rows
**Options considered:** A. Live FX API call at import time. B. Fixed documented rate stated up front.
**Chosen:** B — fixed rate. 1 USD = 83.50 INR (mid-market rate circa March 2026 Goa trip).
**Why:** PLAN.md Section 3 policy #5 explicitly recommends this: "simpler and defensible in the live session." A live API adds a dependency that can fail and produces different numbers on re-import. The fixed rate is stated here and stored in `exchange_rate` on every converted row, so nothing is ever lossy or unreproducible.
**Rate stored as:** Decimal('83.50') in every ExpenseSplit row for USD expenses.
**Tradeoff accepted:** Rate may differ from the actual rate on that day. That is acceptable — the rate is documented and any discrepancy is visible in the import report.
**Reversible?** Yes — rate is stored per-row, so future re-import with a different rate only requires changing this one constant and re-running.

## Root Cause: Stale Test Database Blocking Interactive Prompt

  What happened: Sonnet 4.6 launched three concurrent test runs (tasks 185, 193, 201) against the same Postgres test database  test_spreetail . They were killed mid-execution, leaving the
  test DB behind. Django's test runner, on finding an existing  test_spreetail , prompts interactively: "Type 'yes' to delete...". Since the commands ran non-interactively (piped through
  tail ), nobody answered the prompt and every subsequent test run hung indefinitely waiting for stdin.

  Not the cause: No infinite loops, no network calls, no DB bloat. The actual test execution times are fine (9–13s per module).

## [2026-07-12] Decision: Non-member in split_with (Kabir)
**Options considered:**
A. Auto-create a lightweight "guest" user.
B. Exclude his share and redistribute proportionally among real members.
**Chosen:** B — exclude and redistribute.
**Why:** PLAN.md Section 3 policy #6 allows both, but B prevents the database from accumulating ghost users that break queries or require special filtering everywhere balances are shown. The redistribution is done proportionally using the same split_calc function as normal expenses, keeping it consistent.
**Tradeoff accepted:** The non-member's implicit share is borne by the real members on the expense.
**Reversible?** Yes, by re-running import with a different policy (since raw values are stored).

## [2026-07-12] Decision: Settlement-detection threshold (2-of-3 triggers blocked)
**Options considered:**
A. Ignore rows with only 2 of 3 signals and let them import as normal expenses.
B. Auto-route to Settlement if 2 of 3 signals match (lower the threshold for auto-routing).
C. Block the row for manual review if exactly 2 of 3 match.
**Chosen:** C — block for manual review.
**Why:** A row that matches 2 signals (e.g. single recipient + "paid back" description, but non-blank split_type) is ambiguous. It might be a settlement where the user accidentally left split_type as "equal", or a real deposit/expense with a confusing description. Option A silently imports it as an expense, breaking balances. Option B silently assumes it's a settlement, risking data loss if it was a real expense. Option C forces the human to disambiguate the edge case.
**Tradeoff accepted:** Increased friction during import. The user has to manually review and resolve these ambiguous rows rather than the system handling them automatically. Safe over silent.
**Reversible?** Yes, the detection threshold is isolated to the importer function and can be adjusted on future imports.

## [2026-07-12] Decision: Missing currency default policy
**Options considered:**
A. Block row for manual review (treat identically to missing paid_by).
B. Default to INR (the dominant currency of the dataset).
**Chosen:** B — default to INR but flag visibly in the import report.
**Why:** While missing payer has no reliable default, almost every row in the dataset is in INR. Assuming INR is a low-risk inference rather than a blind guess. Blocking every missing currency row creates unnecessary friction when the inference is highly likely to be correct.
**Tradeoff accepted:** A missing currency that was actually meant to be USD will be incorrectly imported as INR. This is mitigated by ensuring the assumption is flagged visibly in the import report so it can be caught.
**Reversible?** Yes, by manually correcting the currency in the UI or re-importing.

## [2026-07-12] Decision: Ambiguous date detection
**Options considered:**
A. Purely structural: block any date where day <= 12 and month <= 12.
B. Text-signaled: block if structural condition holds AND note explicitly mentions confusion (e.g. "April", "May", "wrong").
**Chosen:** B — Text-signaled structural ambiguity.
**Why:** Option A would produce too many false positives since dates like 04-05 are perfectly valid structurally. We rely on the note field casting doubt on the format, which explicitly flags the ambiguity in the human's mind.
**Tradeoff accepted:** If a date is structurally ambiguous but the user didn't write a note questioning it, we blindly accept the ISO-8601 interpretation. This is acceptable because without a note, there is no signal of error.
**Reversible?** Yes, the date can be edited in the UI to the correct interpretation.

## [2026-07-12] Decision: split_type says "equal" but split_details exists
**Options considered:**
A. Trust split_type ("equal") and ignore split_details.
B. Trust split_details (explicit shares) and infer split_type from the format.
**Chosen:** B — split_details wins, flag anomaly as auto_resolved.
**Why:** A user taking the time to explicitly type out shares (e.g. `Aisha:1000; Rohan:2000`) is high-intent data. `split_type="equal"` is often a careless default from a dropdown or copy-paste. Explicit numbers override the label.
**Tradeoff accepted:** If someone meant "equal" and copy-pasted leftover `split_details` by accident, we will incorrectly apply an unequal split. However, this is visible in the UI and can be manually corrected.
**Reversible?** Yes, the expense can be edited via the UI to an equal split.
