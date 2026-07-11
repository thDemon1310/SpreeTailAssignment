# TODO

Status key: `[ ]` not started · `[~]` in progress · `[x]` done (one-line note required)
`GATE` items may only be checked by the human. Gemini stops and waits at every GATE — see GEMINI.md Section 1.

## Phase 0 — Setup
- [x] Django project + DRF + Postgres connection, `.env` config — Django 6.0.7 project in `backend/` with DRF+SimpleJWT+CORS, Postgres connected via `.env`, migrations applied, server boots on :8000
- [x] React (Vite) scaffold, basic routing — Vite+React in `frontend/`, react-router-dom with 6 routes (dashboard/groups/expenses/balances/settle/import), JWT auth context, axios client with token refresh, premium dark-mode design system, sidebar layout
- [x] **GATE 0:** human confirms environment runs locally end to end (empty app, but boots) before any models are written — ✅ confirmed 2026-07-10

## Phase 1 — Core models & auth
- [x] `User` (or extend Django's), auth endpoints (register/login/token) — custom User via AbstractUser in `core` app, register/me views, JWT token endpoints, 8 tests passing
- [x] `Group`, `Membership` (`joined_on`, `left_on` nullable) models + migrations — Group with M2M through Membership, UniqueConstraint, `is_active_on()` helper, DB reset for AUTH_USER_MODEL fix, migration 0002 applied
- [x] Group CRUD API (create group, add/remove member with dates) — GroupListCreate, GroupDetail, add_member, update_or_remove_member views + 10 new tests (18 total) all passing
- [x] `Expense`, `ExpenseSplit`, `Settlement` models + migrations — Expense with FX fields (original_amount, exchange_rate, currency), 4 split types, ExpenseSplit with UniqueConstraint, Settlement separate from Expense, ImportBatch + ImportAnomaly with 18 problem types and 3 statuses, migration 0003 applied
- [x] **GATE 1:** human reviews schema against PLAN.md Section 3 policies before any split logic is written. Any schema deviation from PLAN.md gets a DECISIONS.md entry first.

## Phase 2 — Expense logic
- [x] Split calculation as a standalone pure function, covering equal/unequal/percentage/share — `core/split_calc.py`, pure Decimal math, ROUND_HALF_UP, payer absorbs remainder (DECISIONS.md [2026-07-11]), 22 unit tests passing, no DB access, not yet wired to any view
- [x] Balance calculation function: per-group and per-person, excluding expenses outside a member's `Membership` window by date — `core/balance_calc.py`, SQL-level membership window filter, zero-sum invariant guaranteed, settlement formula corrected (made-received not received-made), 15 tests passing
- [x] Rounding policy applied consistently in both functions above — ROUND_HALF_UP to 2dp in split_calc (SCOPE.md #12), balance_calc sums stored Decimal values without re-rounding; DECISIONS.md [2026-07-11] cited
- [x] Expense create/list/detail API using the tested split function — `ExpenseCreateSerializer` calls `calculate_splits`, writes Expense + ExpenseSplit atomically via `transaction.atomic()`; `expense_list_create` (GET/POST) + `expense_detail` (GET/DELETE) views; nested under `/api/groups/<id>/expenses/`; 24 API-level tests all passing (79 total)
- [ ] Settlement create/list API, folded into balance calc
- [ ] **GATE 2:** human hand-checks one manual balance calculation against the test output before import work begins

## Phase 3 — CSV Import Pipeline
Import `expenses_export.csv` exactly as given, no manual edits to the file. For every anomaly: a named detection method, a defined `ImportAnomaly` storage shape, a defined fallback for uncertain cases (see GEMINI.md Section 5). Ask the human before finalizing any policy not already fixed in PLAN.md Section 3.

- [ ] **Exact duplicate expense** ("Dinner at Marina Bites" / "dinner - marina bites", 2026-02-08, Dev, 3200 INR): Detection — hash on (date, amount, paid_by normalized, description normalized via casefold+strip+punctuation removal); exact hash match = duplicate. Storage — log both rows, mark which was kept. Fallback — none needed, this is a high-confidence rule; if hash collision logic ever flags something ambiguous, downgrade it to the "possible duplicate" path below instead of auto-resolving.
- [ ] **Non-standard precision amount** (Cylinder refill, 899.995): Detection — any amount with >2 decimal places. Storage — original raw value + rounded value both kept in ImportAnomaly. Fallback — apply the project rounding policy (from DECISIONS.md), never truncate silently.
- [ ] **Inconsistent payer name casing/format** ("priya", "Priya S", "rohan "): Detection — normalize (strip + casefold) then compare to known member names; exact match after normalization = auto-map. Below a defined similarity threshold = unmatched. Storage — raw string + matched member id (nullable). Fallback — unmatched goes to a manual-mapping queue in the import report; never auto-create a new member from a fuzzy guess.
- [ ] **Missing paid_by** (House cleaning supplies, 2026-02-22): Detection — null/blank field. Storage — full row preserved verbatim in ImportAnomaly with status "blocked." Fallback — this row is excluded from balance calculation entirely until a human assigns a payer through the UI; it must never default to anyone.
- [ ] **Settlement logged as an expense** ("Rohan paid Aisha back", 2026-02-25, 5000 INR, blank split_type, single-person split_with): Detection — split_type blank AND split_with has exactly one person AND description matches a settlement-like pattern (heuristic, list your actual pattern in DECISIONS.md). Storage — routed to `Settlement`, original row referenced by id for audit. Fallback — low-confidence matches go to manual review, not auto-routed.
- [ ] **Percentages not summing to 100%** (Pizza Friday, 30+30+30+20=110%): Detection — sum split_details percentages, compare to 100 with a small float tolerance. Storage — raw percentages + sum + normalized percentages if normalization is the chosen policy. Fallback — per PLAN.md policy; whichever is chosen, the discrepancy must appear in the import report, not just be silently absorbed.
- [ ] **Foreign currency rows** (Goa villa 540 USD, Beach shack 84 USD, Parasailing 150 USD, Parasailing refund -30 USD): Detection — currency != INR. Storage — original_amount, original_currency, exchange_rate, converted_amount all stored per row, never just the converted number. Fallback — n/a, this always needs conversion; missing-currency rows are a separate item below.
- [ ] **Non-member in split_with** (Parasailing includes "Dev's friend Kabir"): Detection — any name in split_with that doesn't resolve to a current `Membership`. Storage — unresolved name kept raw in ImportAnomaly. Fallback — per PLAN.md's guest-vs-exclude policy; whichever chosen, document the redistribution math for the remaining members' shares.
- [ ] **Same expense, conflicting amounts, two different loggers** ("Dinner at Thalassa" Aisha/2400 vs "Thalassa dinner" Rohan/2450, same date): Detection — same date + similar description (fuzzy match, not exact) + different payer + different amount. Storage — both rows kept, flagged as a linked pair. Fallback — NEVER auto-merge or average; both go to manual review, no exceptions even though the duplicate-exact-match rule above exists — this is deliberately a different, lower-confidence path.
- [ ] **Negative amount** (Parasailing refund, -30 USD): Detection — amount < 0. Storage — flagged with the refund-vs-error question explicit in the anomaly record. Fallback — per PLAN.md policy (default: treat as refund, reduce payer's effective outlay), but must appear in the import report either way.
- [ ] **Corrupted/implausible date** (Airport cab, `2014-03-01`): Detection — date outside a defined sane window (e.g. Jan 2026–Jun 2026 for this dataset). Storage — raw date kept, not overwritten. Fallback — row excluded from balance calc until a human corrects the date through the UI; never auto-corrected to a guessed date.
- [ ] **Missing currency** (Groceries DMart 2026-03-15): Detection — blank currency field. Storage — raw row kept. Fallback — per PLAN.md policy (default: assume INR since it's the dataset's dominant currency), but this must be a visible flag in the import report, not a silent default.
- [ ] **Zero-amount expense flagged by its own note as a stale duplicate** (Dinner order Swiggy, amount 0, "counted twice earlier - fixing later"): Detection — amount == 0. Storage — raw row kept with note text captured. Fallback — exclude from balance calc by default, flagged for human confirmation, not deleted outright (Meera's requirement: nothing is deleted without approval).
- [ ] **Ambiguous date format** (Deep cleaning service, `2026-05-04`, note questions April 5 vs May 4): Detection — flag any date where the note text or surrounding context casts doubt (this one is text-signaled, not purely structural — say explicitly in DECISIONS.md how you're catching it). Storage — raw date kept. Fallback — excluded from balance calc pending human resolution, same as the corrupted-date case.
- [ ] **Stale member in split_with after they left** (Groceries BigBasket 2026-04-02 includes Meera, who left end of March): Detection — cross-reference each split_with name against `Membership.left_on` relative to the expense date. Storage — original split_with list preserved, resolved list stored separately. Fallback — exclude the stale member's share and redistribute per the chosen redistribution rule (must match the rule used for the Kabir case for consistency — same policy, same DECISIONS.md entry).
- [ ] **split_type says "equal" but split_details has explicit shares attached** (Furniture for common room, 2026-04-18): Detection — split_type == "equal" AND split_details is non-empty. Storage — both fields kept raw. Fallback — flag regardless of which field you trust; state in DECISIONS.md which one wins and why.
- [ ] **Expense that's really a transfer/deposit, not a shared cost** (Sam deposit share, 2026-04-08, single-person split_with): Detection — same heuristic family as the settlement-detection item above; note explicitly whether this one trips the same rule or needs its own. Storage/fallback — same as the settlement item.
- [ ] Full re-read of the raw file for anything not on this list (whitespace, encoding, silent case variants) — this list is what was found on first pass, not a guarantee of completeness; log anything new as a new TODO item, do not fix it inline without logging it first.
- [ ] Generate the Import Report as a real artifact from an actual run against the actual file — not written up from memory of what should happen.
- [ ] Every anomaly + resolution logged into SCOPE.md's table as it's handled, using the Section 4 template — not batched at the end.
- [ ] **GATE 3:** human reviews the full import report line by line against the CSV before the frontend import screen is built.

## Phase 4 — Frontend
- [ ] Login/auth flow
- [ ] Group view: members with join/leave dates, expense list
- [ ] Add expense form supporting all 4 split types
- [ ] Balance summary — Aisha's "one number per person" view
- [ ] Balance drill-down showing the underlying ExpenseSplit/Settlement rows behind each number — Rohan's "no magic numbers" view; this must query real rows, not recompute in the frontend
- [ ] Settle-up flow
- [ ] Import report screen (trigger import, show anomaly table + resolutions, nothing pre-applied silently)
- [ ] **GATE 4:** human walks through the full UI once, end to end, before deploy

## Phase 5 — Optional AI/LLM feature (bonus — do not start until Phases 0–4 are done and gated)
- [ ] One isolated LLM integration (e.g. free-text entry → structured expense suggestion, human still confirms before it's saved). Core flows must work with zero dependency on this.

## Phase 6 — Deploy & wrap-up
- [ ] Deploy backend + Postgres
- [ ] Deploy frontend, wired to deployed backend
- [ ] Smoke test the deployed URL end-to-end: login → create group → import CSV → view balances → settle
- [ ] Finalize README.md, DECISIONS.md, SCOPE.md — pull AI_USAGE.md from AI_ACTIONS_LOG.md, human edits for honesty and completeness, especially the 3+ required "AI got it wrong" examples
- [ ] **GATE 5 (final):** human manually traces one member's full balance by hand from the raw CSV and confirms it matches the deployed app exactly. Do not submit until this passes. If it doesn't, the bug gets fixed and the trace repeated — do not adjust the trace to match the app.
