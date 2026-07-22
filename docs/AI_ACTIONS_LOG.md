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

## [2026-07-11] Phase 2 Task 4: Expense create/list/detail API
**Asked for:** Wire the tested `calculate_splits` pure function to real API endpoints — create, list, and detail for expenses, all scoped to a group.
**Produced:** Four new serializers in `core/serializers.py`: `ExpenseSplitSerializer` (read-only per-person share), `ExpenseSerializer` (full detail with nested splits), `ExpenseListSerializer` (lightweight list without splits), `ExpenseCreateSerializer` (validates input, calls `calculate_splits`, saves `Expense` + all `ExpenseSplit` rows in a single `transaction.atomic()` block — if split_calc raises `SplitCalcError`, nothing is written). Two new views in `core/views.py`: `expense_list_create` (GET lists expenses, POST creates via serializer) and `expense_detail` (GET returns full detail, DELETE cascades to splits). URLs mounted at `/api/groups/<id>/expenses/` and `/api/groups/<id>/expenses/<id>/`. `core/tests_expenses.py` — 24 API-level tests: equal/unequal/percentage/shares split types each verified (share amounts checked, sum invariant checked), access control (unauthenticated → 401, non-member → 403), validation errors (negative/zero amount, unknown paid_by, unknown participant, bad split_type, percentages summing wrong) all → 400 with nothing written, list vs detail payload difference verified, cascade delete verified. 79 total tests all passing.
**Human caught wrong / had to redirect?** No.

## [2026-07-12] Phase 4 Task: Fix ResolutionInputs crash on missing_payer
**Asked for:** Diagnose and fix Uncaught TypeError reading "id" in ResolutionInputs map.
**Produced:** Fixed `ImportPage.jsx` component to correctly map member attributes.
**Human caught wrong / had to redirect?** Yes — the UI crashed due to wrong data shape assumptions. Root cause: the `ResolutionInputs` component mapped the `members` array (passed down from `selectedGroup.memberships`) but incorrectly expected a nested `m.user` object (`m.user.id`, `m.user.username`). The backend API correctly returns a flat structure (`m.user_id`, `m.username`). This was a case of (a): the UI component wrongly assumed a nested shape. Fix: Updated all instances of `m.user.id` and `m.user.username` in `ResolutionInputs` to `m.user_id` and `m.username`.

## [2026-07-12] Phase 4 Task: Import UI Improvements
**Asked for:** UI improvements for file preview step and anomaly review screen without changing backend import logic.
**Produced:** Added a distinct Preview step before anomaly review by decoupling the UI states (`previewMode`). Implemented local `FileReader` to show CSV raw data table before confirmation. Grouped anomaly summary counts at the top. Added filtering by anomaly problem type/status. Replaced JSON dump with a mini table mapping CSV headers to extracted data. Added a CSS flash animation for resolution feedback. Renamed Upload button to "Analyze CSV" and added "Confirm Import" flow.
**Human caught wrong / had to redirect?** No.

## [2026-07-12] Phase 4 Task: Deployment Configuration
**Asked for:** Prepare backend for Render and frontend for Vercel, using Railway Postgres.
**Produced:** Added `gunicorn`, `dj-database-url`, `whitenoise` to backend requirements. Updated `settings.py` to securely parse `DATABASE_URL` via `dj_database_url` (with fallback to dev), use `whitenoise` for static files, and dynamically load `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `DEBUG`, and `SECRET_KEY` from environment variables. Created `backend/build.sh` for Render build process. Confirmed `VITE_API_URL` usage in frontend API client.
**Human caught wrong / had to redirect?** No.

## [2026-07-12] Task 1: Add members to a group
**Asked for:** Implement "Add Member" control on the group detail view. Needs username/email lookup and hit the existing Membership model on the backend, handling nonexistent user errors inline.
**Produced:**
- Modified `backend/core/serializers.py` to make `user_id` optional and accept `username` in `AddMemberSerializer`, checking user existence against both username and email (case-insensitive) using `Q`.
- Modified `backend/core/views.py` `add_member` endpoint to dynamically retrieve user by `username`/`email` when `user_id` is not supplied.
- Modified `backend/core/tests.py` to add 3 new API unit tests verifying direct membership addition via username and email, plus error responses.
- Implemented an inline collapsible "Add Member" form inside the selected group detail card in `GroupsPage.jsx`, styled matching the rest of the application via `GroupsPage.css`. Updates local states upon successful membership creation and fetch.
**Human caught wrong / had to redirect?** No.

## [2026-07-12] Task 2: Fix the broken Import preview UI
**Asked for:** Diagnose and fix the broken Import preview step rendering.
**Produced:**
- Corrected line-splitting in `handleFileChange` within `frontend/src/pages/ImportPage.jsx` from `.split('\\n')` to `.split(/\r?\n/)` to properly parse lines and prevent headers from parsing as a single line with empty rows.
**Human caught wrong / had to redirect?** No.

## [2026-07-12] Phase 4 Task: Fix name_mismatch resolution crash
**Asked for:** Diagnose and fix the 400 Bad Request error occurring when applying a resolution for a `name_mismatch` anomaly.
**Produced:**
- Modified `frontend/src/pages/ImportPage.jsx` `ResolutionInputs` component to render the payer select dropdown for `name_mismatch` anomalies, allowing `paid_by_id` to be selected and sent to the backend.
- Modified `backend/core/tests_resolution_api.py` to add `test_apply_name_mismatch` unit test confirming successful resolution of inconsistent payer name anomalies.
**Human caught wrong / had to redirect?** No.

## [2026-07-16] Phase 4 Task: BUG 1 — Home/Dashboard and other pages stale data
**Asked for:** Fix stale frontend pages showing stale state after actions (resolving an anomaly, adding an expense, settling up) by implementing a systemic refetching mechanism.
**Produced:**
- Extended `frontend/src/context/AuthContext.jsx` to fetch and store `user.id` from `/auth/me/` on app initialization and login.
- Exposed a global `refreshTrigger` integer counter and `triggerRefresh()` helper function from `AuthContext`.
- Updated `DashboardPage.jsx` to dynamically fetch group counts, total expenses count, and personal balances ("You Owe", "Owed to You") using parallel requests, reacting to changes in `refreshTrigger` and `user.id`.
- Replaced the dashboard placeholder with a dynamic group balance summary card grid.
- Subscribed `BalancesPage.jsx`, `GroupsPage.jsx`, `ExpensesPage.jsx`, `SettlePage.jsx`, and `ImportPage.jsx` to `refreshTrigger` so they reactive-fetch fresh data on trigger updates while preserving user selection states.
- Integrated `triggerRefresh()` calls into all mutating actions: group creation, membership addition, expense creation, settlement creation, CSV upload, and anomaly resolution.
**Human caught wrong / had to redirect?** Yes — backend `/me/` endpoint was queried as `/api/me/`, causing a 404. Diagnosed the mount point prefix `/api/auth/me/` from `api_urls.py`, and updated all occurrences in `AuthContext.jsx` and `DashboardPage.jsx`. Also, verified that 400 Bad Request responses on `/api/groups/1/members/` are standard input validation errors (user already in group or username non-existent) and not application bugs.

## [2026-07-16] Phase 4 Task: BUG 2 — UI styling fixes
**Asked for:** Fix unstyled buttons on GroupsPage (Create New Group, Add Member) and ImportPage (Analyze CSV, Choose File) to match established design patterns. Also, resolve low-contrast white-card text (e.g. "Flat rent", "Members", "Summary") and ExpensesPage form-card layout overflow.
**Produced:**
- Created global `.btn`, `.btn.primary`, `.btn.secondary`, `.btn-primary`, and `.btn-secondary` classes in `frontend/src/index.css` matching the `#4f46e5` primary theme colors, font styling, padding, transitions, and hover properties found elsewhere in the app.
- Added `className="btn primary"` to the "Analyze CSV" button in `ImportPage.jsx`.
- Styled the custom file upload input (`input[type="file"]`) and its `::file-selector-button` in `ImportPage.css` to match the application's visual aesthetics.
- Added a systematic CSS inheritance rule in `index.css` to override body text-color inheritance for all white-card container classes (making all standard text inherit `#1f2937` instead of near-white, restoring high-contrast legibility).
- Added width and max-width style properties to `input` and `select` elements in `ExpensesPage.css` to keep them bounds-contained inside `.form-group`, and stacked `.form-row` containers vertically on viewports <= 600px via a responsive media query to resolve layout overflow.
**Human caught wrong / had to redirect?** No.

## [2026-07-16] Phase 4 Task: Searchable dropdown for adding members
**Asked for:** Replace exact-username member-adding with a searchable live-filtering autocomplete dropdown using a backend search endpoint.
**Produced:**
- Created `UserListView` in `backend/core/views.py` using DRF SearchFilter to search against `username` and `email`.
- Mounted `/api/users/` in `backend/spreetail_backend/api_urls.py`.
- Added unit tests in `UserListViewTest` class within `backend/core/tests.py` to cover listing all users and searching by username/email against paginated API responses.
- Implemented state variables, a debounced query fetcher `useEffect` hook, and click-outside detector event listeners in `frontend/src/pages/GroupsPage.jsx`.
- Replaced the plain text input in the "Add Member" form with the live searchable dropdown displaying matched usernames and emails (filtering out users who are already group members).
- Appended styling rules for the dropdown list, items, hover state, and status message to `frontend/src/pages/GroupsPage.css`.
**Human caught wrong / had to redirect?** Yes — user corrected the initial test case assumption: the test should assert against `results` keys in the response instead of turning off view pagination to match the project's consistent paginated response shape. Test cases were corrected to use `resp.data['results']` accordingly.

## [2026-07-17] Business Rule Correction: Enforce self-payment rules on backend and frontend
**Asked for:** Enforce that a user can only create an expense or settlement with themselves as paid_by / from side. Remove the paid_by dropdown from expense create and from side of settle up, replaced with read-only logged-in user. Validate and reject spoofed payloads on backend with 400 Bad Request. Filter settlement recipient to active members only. Add API tests and update DECISIONS.md.
**Produced:**
- Modified `backend/core/serializers.py` to make `paid_by_id` optional in `ExpenseCreateSerializer`, validate that if provided it must match `request.user.id`, and default it to `request.user.id`.
- Modified `backend/core/views.py` `settlement_list_create` view to reject settlement creations if `from_user_id` is spoofed/mismatched, default it to `request.user.id` when omitted, reject if trying to settle with self, and validate that `to_user_id` is an active member of the group on the settlement date (left_on has not passed).
- Updated `frontend/src/pages/ExpensesPage.jsx` and `frontend/src/pages/SettlePage.jsx` to pull the user object from `useAuth()`, display the payer as read-only text, and submit the payer user ID automatically. Filtered settlement recipient options to active members (`user_id !== user.id && !m.left_on`).
- Added unit tests in `core/tests_expenses.py` and `core/tests_settlement_api.py` verifying that direct API calls attempting to spoof the payer/sender are rejected with a 400 Bad Request, and verifying active membership checks.
- Logged the decision and tradeoffs in `docs/DECISIONS.md`.
**Human caught wrong / had to redirect?** Yes — the settlement page initially threw a `ReferenceError` because the `user` object was not destructured from `useAuth` in `SettlePage.jsx`. This was caught and corrected by adding `user` to the destructuring list.

## [2026-07-22] Leave Group Feature
**Asked for:** Add a backend-enforced leave group endpoint that checks for a zero balance, sets left_on, and prevents leaving on behalf of others. Add frontend button and error handling, tests, and log in DECISIONS.md.
**Produced:**
- Created view `leave_group` in `backend/core/views.py` doing balance validation on `calculate_balances()` and identifying net creditors/debtors, and registered it in `backend/core/urls.py`.
- Wrote API unit tests in `backend/core/tests_leave_group.py` verifying blocked/succeeded scenarios, left_on field setting, access control, and prior expense calculations integrity.
- Destructured `user` from `useAuth` in `frontend/src/pages/GroupsPage.jsx`, added `leaveLoading`/`leaveError` states, and implemented `handleLeaveGroup` handling balance validation messages and redirecting/updating page states.
- Rendered the Actions column with the "Leave Group" button in `members-table` (conditional on the logged-in user's own active membership row).
- Updated styling rules for `.leave-btn` and `.leave-error-banner` in `frontend/src/pages/GroupsPage.css`.
- Documented decisions and tradeoffs in `docs/DECISIONS.md` and updated task status in `TODO.md`.
**Human caught wrong / had to redirect?** No.

## [2026-07-22] BUG 4: Dashboard showing left groups
**Asked for:** Fix stale groups displaying on Dashboard even after the user has left them.
**Produced:**
- Modified `GroupListCreateView` and `GroupDetailView` in `backend/core/views.py` to filter querysets to active memberships only (`memberships__left_on__isnull=True`).
**Human caught wrong / had to redirect?** No.







