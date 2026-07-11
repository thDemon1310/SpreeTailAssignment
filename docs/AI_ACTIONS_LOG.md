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
