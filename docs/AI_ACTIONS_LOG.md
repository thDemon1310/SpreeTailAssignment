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
