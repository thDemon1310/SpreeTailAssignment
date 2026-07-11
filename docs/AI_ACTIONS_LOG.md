# AI Actions Log

## [2026-07-10] Phase 0 Task 1: Django project + DRF + Postgres connection, `.env` config
**Asked for:** Set up Django project with DRF, SimpleJWT, CORS headers, and PostgreSQL connection, all configured via `.env`.
**Produced:** `backend/` directory with Django 6.0.7 project (`spreetail_backend`), `settings.py` reading all config from `.env` via python-dotenv, PostgreSQL database `spreetail` connected and migrations applied, DRF with JWT auth configured, CORS allowing Vite dev server on :5173, `requirements.txt` frozen. Server boots clean on :8000.
**Human caught wrong / had to redirect?** No.

## [2026-07-10] Phase 0 Task 2: React (Vite) scaffold, basic routing
**Asked for:** Scaffold a React frontend with Vite, set up routing for all app pages, auth context, and API client.
**Produced:** `frontend/` with Vite+React, `react-router-dom` with 6 protected routes behind sidebar layout + 2 public auth routes. Auth context with JWT token storage in localStorage. Axios API client with automatic token attach and 401 refresh interceptor. Premium dark-mode design system (`index.css`) with HSL tokens, Outfit+Inter fonts, glassmorphism auth cards. Placeholder pages for groups/expenses/balances/settle/import. SEO meta tags in `index.html`.
**Human caught wrong / had to redirect?** No.

## [2026-07-11] Phase 1 Task 1: User model + auth endpoints
**Asked for:** Custom User model and auth endpoints (register/login/token/me).
**Produced:** `core` app with custom `User` extending `AbstractUser`, `AUTH_USER_MODEL = 'core.User'` in settings, `RegisterSerializer` with password validation, `RegisterView` (public), `MeView` (authenticated), wired at `/api/auth/register/` and `/api/auth/me/`. JWT endpoints at `/api/token/` and `/api/token/refresh/`. 8 tests covering register success/duplicate/weak-password, token obtain/wrong-password/refresh, me auth/unauth — all passing.
**Human caught wrong / had to redirect?** No.

## 2026-07-11 Custom User model setup
**Asked for:** custom User model (AbstractUser) + register/login/token endpoints
**Produced:** working core app, serializers, views — but ran `python manage.py migrate`
during Phase 0 scaffolding before AUTH_USER_MODEL was set to the custom model, so
admin.0001_initial and other initial migrations were generated against auth.User.
**Human caught wrong / had to redirect?** yes — swapping AUTH_USER_MODEL after the
initial migrate left the DB referencing the wrong User table. Caught when
`makemigrations core` conflicted with existing admin migrations. Fixed by resetting
the local dev database and regenerating migrations in the correct order (custom User
model set BEFORE first migrate). No data was lost since this was pre-import.

## 2026-07-11 Correction to earlier entry: AUTH_USER_MODEL fix was incomplete
The "reset the DB" fix logged earlier did not actually resolve the root cause.
`showmigrations` later showed core.0001_initial still unapplied while
admin/auth/contenttypes were fully applied — meaning AUTH_USER_MODEL was not
set BEFORE the first migrate ran, so Django still had admin.0001_initial
depending on auth.User instead of core.User. Root cause confirmed via
`showmigrations`, not guessed. Real fix: drop DB, confirm AUTH_USER_MODEL is
set in settings.py first, THEN run migrate once, so Django's own dependency
graph orders core.0001_initial correctly. This is the second time this
surfaced — the first "fix" treated the symptom, not the cause.

## [2026-07-11] Phase 1 Task 2: Group + Membership models
**Asked for:** Group and Membership models with join/leave dates.
**Produced:** Group model with M2M through Membership, `is_active_on()` helper, UniqueConstraint (one membership per user per group), admin registration with inline editing. DB reset was needed due to AUTH_USER_MODEL inconsistency (documented above). Migration 0002 applied.
**Human caught wrong / had to redirect?** No — the DB reset was a direct fix for the root cause, not a workaround.

## [2026-07-11] Phase 1 Task 3: Group CRUD API
**Asked for:** Create/list/detail/update/delete group, add/remove member with dates.
**Produced:** `GroupListCreateView`, `GroupDetailView`, `add_member`, `update_or_remove_member` views. `GroupCreateSerializer` auto-adds creator as first member. `AddMemberSerializer` and `UpdateMemberSerializer` for membership management. Permission checks (only group members can manage). 10 new tests (5 group CRUD + 5 membership) — 18 total, all passing.
**Human caught wrong / had to redirect?** No.

## [2026-07-11] Phase 1 Task 4: Expense, ExpenseSplit, Settlement, ImportBatch, ImportAnomaly models
**Asked for:** Expense/split/settlement models per PLAN.md Section 2, plus import pipeline models.
**Produced:** Expense model with FX fields (original_amount, exchange_rate, currency), 4 split types enum, is_settlement flag, notes. ExpenseSplit with UniqueConstraint (one split per user per expense). Settlement separate from Expense per DECISIONS.md #4. ImportBatch for audit trail. ImportAnomaly with 18 problem_type choices covering all Phase 3 anomalies, 3 status choices, linked_expense/linked_settlement FKs, resolved_by/at. All registered in admin. Migration 0003 applied. 18 tests still passing.
**Human caught wrong / had to redirect?** No.

## [2026-07-11] Phase 2 Task 1: Split calculation pure function
**Asked for:** Standalone split calc function for all four split types, tests written first (GEMINI.md Sec 3), rounding policy from SCOPE.md #12 applied, remainder decision confirmed by human before writing.
**Produced:** `core/split_calc.py` — `calculate_splits()` pure function (no DB access), `SplitCalcError` for invalid inputs. All four types: equal (total/n, ROUND_HALF_UP each), unequal (explicit INR amounts, rounded), percentage (total × pct/100, tolerance check for sum≠100), shares (total × share/total_shares). Remainder after rounding assigned to payer per DECISIONS.md [2026-07-11]. `core/tests_split_calc.py` — 22 tests written and run to failure first, then implementation written to pass them. 40 total tests all passing.
**Human caught wrong / had to redirect?** No.

## [2026-07-11] Phase 2 Task 2: Balance calculation function
**Asked for:** Per-group and per-user balance function, membership window exclusion, tests first before wiring to a view.
**Produced:** `core/balance_calc.py` — `calculate_balances(group_id)` returns `{user_id: Decimal}`, `calculate_user_balance(group_id, user_id)` returns single Decimal. Membership window filter applied at SQL level (`expense__date__gte=joined_on`, `expense__date__lte=left_on`), not a Python loop. Zero-sum invariant holds. `core/tests_balance_calc.py` — 15 tests: simple balances, zero-sum, membership window (before join, after leave, on both boundaries, no membership), settlement clear/partial/wrong-group, rounding in balance.
**Human caught wrong / had to redirect?** Yes — AI wrote settlement formula as `received - made` (wrong direction). Caught by 3 failing tests. Root cause diagnosed correctly (formula, not the tests). Fix: flipped to `made - received` (paying off debt is positive to your balance; receiving a settlement reduces your outstanding receivable). One test comment also had the wrong expected value for Rohan (described as +50, correct is -50 because he owes his share of both expenses). Both fixed before passing.

## [2026-07-11] Phase 2 Task 3: Rounding policy consistency verified
**Asked for:** Confirm ROUND_HALF_UP applied consistently in both functions.
**Produced:** No new code — verified by inspection and tests. split_calc applies `_round()` (ROUND_HALF_UP, 2dp) to every share. balance_calc sums already-rounded Decimal values from DB (no re-rounding). DECISIONS.md [2026-07-11] is the authoritative reference. 55 total tests all passing.
**Human caught wrong / had to redirect?** No.
