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
