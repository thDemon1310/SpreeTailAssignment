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

## [2026-07-11] Decision: Settlement/Deposit detection heuristic (import pipeline)
**Options considered:**
A. Blank split_type AND single name in split_with AND description regex match.
B. Any row with a single split_with recipient, regardless of split_type.
C. Pure description regex, no structural check.
**Chosen:** A — all three conditions must hold simultaneously for auto-routing.
**Why:** Option B would misclassify normal single-person expenses. The three-way conjunction is high-confidence: (1) split_type blank signals the logger didn't know what category it was; (2) single recipient is structurally different from a shared expense; (3) description regex `r'\b(paid|repaid|returned|gave|sent|back|settled|settlement|deposit|transfer|advance|moving in|moved in)\b'` (case-insensitive) catches common payment/deposit language. All three failing means not auto-routed.
**Fallback:** If two conditions hold but not three (low-confidence), route to `blocked` anomaly (`settlement_as_expense`) for manual review, do not auto-route. This gracefully catches deposits (which usually have `split_type="equal"`, so they score 2/3: single recipient + desc match) and blocks them.
**Tradeoff accepted:** Rows that are clearly settlements but miss the description pattern go to manual review instead of being auto-routed. Better than auto-routing something that isn't a settlement. Deposits also require manual review rather than auto-routing, which is correct since they might require manual confirmation.
**Reversible?** Yes — detection is isolated to the importer.

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
**Tradeoff accepted:** If a date is structurally ambiguous but the user didn't write a note questioning it, we blindly accept the ISO-8601 interpretation. This is acceptable because without a note, there is no signal of error. Note that this rule's blind spot ONLY applies to dates that are both structurally ambiguous AND within the plausible date range — structurally clear dates (like 13th) or out-of-range dates (like 2014) are caught by other rules (like Task 11), not this one.
**Reversible?** Yes, the date can be edited in the UI to the correct interpretation.

## [2026-07-12] Decision: split_type says "equal" but split_details exists
**Options considered:**
A. Trust split_type ("equal") and ignore split_details.
B. Trust split_details (explicit shares) and infer split_type from the format.
**Chosen:** B — split_details wins, flag anomaly as auto_resolved.
**Why:** A user taking the time to explicitly type out shares (e.g. `Aisha:1000; Rohan:2000`) is high-intent data. `split_type="equal"` is often a careless default from a dropdown or copy-paste. Explicit numbers override the label.
**Inference logic:** When split_details wins, the actual type is inferred as follows:
  - If it contains `%`, infer `percentage`.
  - If it parses cleanly and EVERY value is an integer (e.g., `Aisha 40; Rohan 60`), infer `shares`. (Note: this means `40; 60` is treated as a 40:60 ratio, not absolute unequal amounts. If they were meant as absolute amounts, it's mathematically equivalent anyway once normalized to the expense total).
  - If it parses cleanly and ANY value has a fractional part (e.g., `Aisha 10.50`), infer `unequal`.
  - If it fails to parse, fallback to `equal`.
**Tradeoff accepted:** If someone meant "equal" and copy-pasted leftover `split_details` by accident, we will incorrectly apply an unequal split. However, this is visible in the UI and can be manually corrected.
**Reversible?** Yes, the expense can be edited via the UI to an equal split.

## [2026-07-12] Decision: Generic vs Per-Type Anomaly Resolution API
**Options considered:** 
A. Generic endpoint (`POST /anomalies/{id}/resolve/`) handling "apply" and "discard" actions globally.
B. Per-type resolution endpoints (e.g. `POST /anomalies/{id}/resolve_bad_date/`) with specific validation schemas.
**Chosen:** Option A (Generic endpoint).
**Why:** All blocked anomaly types reduce to the same functional shape: the human supplies missing or corrected fields, and the row either proceeds to creation or gets discarded. A single endpoint can route the payload through specific validation checks based on `problem_type` without the routing overhead of many distinct endpoints, accommodating the strict time constraints.
**Tradeoff accepted:** The generic endpoint pushes schema validation logic into the view layer rather than leaning on strict per-type Django REST Framework serializers. We lose self-documenting API schemas (like Swagger/OpenAPI) for the specific `corrected_data` shapes required by each anomaly.
**Reversible?** Yes — we can later split the generic endpoint into individual ones or introduce polymorphic DRF serializers without changing the underlying `ImportAnomaly` database model.

## [2026-07-16] Decision: Global reactive refresh trigger for stale frontend data
**Options considered:**
A. Add manual refetch function calls to each page on mount and route navigation events.
B. Move to a data-fetching library (like React Query or SWR) that handles caching and automatic invalidation.
C. Implement a global `refreshTrigger` state counter in `AuthContext` with mutation-based invalidation.
**Chosen:** C — Global `refreshTrigger` counter.
**Why:** Option A is fragile and leads to repetitive one-off refetch calls that are hard to maintain. Option B would require a significant rewrite of the app's data-fetching codebase (currently written in simple `useEffect` hooks calling Axios directly), which violates the "not a rewrite" rule. Option C is a robust, lightweight, and systemic pattern that integrates cleanly into the existing context: any page can subscribe to the trigger in its `useEffect` dependency array, and any mutation triggers a state update that reactively refreshes all active consumers.
**Tradeoff accepted:** Every subscribed page refetches its data on any mutation, even if the mutation didn't affect its specific domain (e.g., adding an expense in group A fetches groups list in Settle page). However, given the lightweight nature of our endpoints, this overhead is negligible.
**Reversible?** Yes — since components still use standard Axios calls inside `useEffect`, transitioning to React Query later would only require replacing the hooks without changing the component template structure.

## [2026-07-16] Decision: UI button styling fixes
**Options considered:**
A. Hand-write page-specific button styling classes in local CSS files for GroupsPage and ImportPage.
B. Write inline style properties directly on the buttons in JSX.
C. Define global `.btn.primary` and `.btn.secondary` classes in `index.css` matching established designs, and apply standard HTML file input styles.
**Chosen:** C — Global button classes in `index.css` and custom `::file-selector-button` styles.
**Why:** The app's existing pages (`ExpensesPage`, `SettlePage`, `ImportPage`) use a combination of classes like `btn primary`, `btn secondary`, `btn-primary`, and `btn-secondary`, but the corresponding styles were not defined globally. Option C implements these classes in `index.css` systematically to match the visual styling (colors, transitions, border radii) already established on pages like `ExpensesPage` (e.g. `#4f46e5` for primary buttons), ensuring consistency across all pages and resolving all unstyled buttons simultaneously.
**Tradeoff accepted:** None. This consolidates button styling into the main stylesheet rather than polluting local component CSS files.
**Reversible?** Yes, by modifying `index.css`.

## [2026-07-16] Decision: High-contrast card text colors
**Options considered:**
A. Add page-specific overrides in `GroupsPage.css`, `ExpensesPage.css`, and `BalancesPage.css` for every heading, cell, and text element on the page.
B. Modify the white card backgrounds to dark backgrounds (matching the body background).
C. Add a global text color inheritance rule for white card container classes in `index.css` to set the default text to a dark charcoal color `#1f2937`.
**Chosen:** C — Global text color override for white card classes.
**Why:** Option A is highly repetitive, prone to bugs (missing elements), and hard to maintain. Option B would require changing the layout's color scheme which was previously established. Option C solves the contrast issue systematically: by setting `color: #1f2937` on all white card classes (`.group-sidebar`, `.group-card`, `.expenses-section`, `.form-card`, `.group-selector`, `.balances-summary`, `.drill-down-card`), all nested text elements (headers, paragraphs, table rows) automatically inherit high-contrast dark text, while any custom colored indicators (like red/green balance values) remain unaffected.
**Tradeoff accepted:** None.
**Reversible?** Yes, by editing `index.css`.

## [2026-07-16] Decision: ExpensesPage form-card width overflow fix
**Options considered:**
A. Use a smaller font size or padding for input fields on the page.
B. Set form inputs to `width: 100%` and `max-width: 100%`, and stack form rows vertically using a responsive media query for narrow viewports.
**Chosen:** B — Flexible inputs with responsive stacking.
**Why:** Option A does not prevent overflow on small screen sizes. Option B ensures input fields size themselves relative to their flex parent without exceeding card boundaries, and stacks them vertically on screen widths <= 600px, creating a clean mobile-friendly layout.
**Tradeoff accepted:** Form fields stack on narrow screens, changing from horizontal to vertical. This is standard and expected responsive design behavior.
**Reversible?** Yes.

## [2026-07-16] Decision: Direct-add user search dropdown over invite-and-accept flow
**Options considered:**
A. Implement a full user invitation and acceptance system (with notifications, group invites table, and join status approvals).
B. Replace the exact username input with a searchable live-filtering autocomplete dropdown directly adding selected users to the group.
**Chosen:** Option B (Direct-add with searchable autocomplete).
**Why:** The assignment's core requirement is supporting "membership changes over time" (which our `joined_on`/`left_on` fields on `Membership` already handle perfectly). Introducing a full user invitation/acceptance flow requires creating several new database tables, notification models, approval APIs, and complex UI overlay panels. Given the tight schedule before Phase 6 deployment, Option B provides the desired searchable user lookup functionality while utilizing direct CRUD actions, matching the established user-experience pattern of the project.
**Tradeoff accepted:** Users are added immediately to groups by any active group member, rather than receiving an invitation to join.
**Reversible?** Yes — we can later swap the backend `members/` POST handler to create an invite record instead of a direct `Membership` row, and display invites in a notification panel.

