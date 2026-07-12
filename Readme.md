# Spreetail Expense Splitter

## Project Overview
This application is a shared expense splitting platform designed for flatmates and group trips. It allows users to track expenses, calculate individual balances, record settlements, and import expense histories from CSV files. 

Core Features:
- Group Management: Users can create expense groups and add members directly via username or email.
- Expense Splits: Supports equal, unequal, percentage, and share-based calculations.
- Balance Summaries: Displays a zero-sum, trace-ready matrix of who owes whom how much, ensuring all calculations are fully transparent.
- Settle-up: Allows direct recording of settlements between two users to clear debts.
- CSV Import Pipeline: Parses raw CSV expense exports, detects 16 distinct anomaly types, and runs a manual resolution dashboard to review and resolve blocked entries.

## Tech Stack
- Backend: Django 6.0.7, Django REST Framework, PostgreSQL. JWT authentication is handled via SimpleJWT.
- Frontend: React (Vite-scaffolded), React Router DOM v7, Axios client with automatic 401 token refresh interceptors.
- Deployment: Render for backend hosting (with Gunicorn and WhiteNoise static asset serving), Vercel for frontend hosting, and Railway for PostgreSQL database.

## Architecture
The database schema is designed to enforce transparency and date-based membership window logic:
- User: Custom model inheriting from Django's AbstractUser.
- Group: Represents a household or trip containing multiple members.
- Membership: Represents the membership window of a user in a group. Stores joined_on and left_on (nullable) dates. Zero-sum balances are calculated at the database level by filtering expense dates to fall within a member's active membership window.
- Expense: Represents a shared cost, storing currency, amount in INR, original converted amount, exchange rate, and split type.
- ExpenseSplit: Stores the computed share amount per user. It is the final source of truth for balance summaries, satisfying the requirement that all balances are traceable to stored records.
- Settlement: Represents direct debt clearance payments between exactly two users.
- ImportBatch: Grouping identifier for CSV import runs.
- ImportAnomaly: Stores rows flagged by the anomaly detection pipeline, documenting problem type, raw data as JSON, detection rule, action taken, and resolution status.

## CSV Import and Anomaly Handling
The import pipeline processes rows from a CSV export. When anomalies are encountered, the importer categorizes them into 16 types and applies specific policies:
1. Exact duplicate expense: Drops the duplicate row and logs it.
2. Non-standard precision amount: Rounds the amount using ROUND_HALF_UP to 2 decimal places and stores original and rounded values.
3. Inconsistent casing/format: Normalizes casing and maps to users; blocks if no match is found.
4. Missing paid_by: Blocks the row from importing, requiring manual payer mapping.
5. Settlement logged as expense: Auto-routes to the Settlement table if all 3 criteria are met; blocks for manual review if 2 of 3 criteria are met.
6. Percentages not summing to 100%: Normalizes percentages proportionally, flags the discrepancy, and imports.
7. Foreign currency row: Converts USD to INR at a fixed rate of 83.50, storing the original amount and rate.
8. Non-member in split_with: Excludes the non-member and redistributes the share proportionally among the active members.
9. Conflicting amounts: Imports both rows as separate expenses and flags them as a conflicting pair for manual review.
10. Negative amount: Treats the row as a refund, reducing the payer's outlay.
11. Corrupted/implausible date: Blocks rows with dates outside the Feb-Jun 2026 window.
12. Missing currency: Defaults the currency to INR and flags it.
13. Zero-amount expense: Blocks the row and captures any attached notes.
14. Ambiguous date format: Blocks the row if the date format is ambiguous and the note field signals confusion.
15. Stale member in split_with: Excludes the member and redistributes their share if the expense occurred after they left the group.
16. split_type vs split_details conflict: Trust split_details over equal split type, inferring the true split type.

Blocked anomalies require manual review via the frontend dashboard. The user must correct missing/corrupted data or discard the row. Discarding a blocked row marks the anomaly resolved but writes no Expense or Settlement record.

## Key Design Decisions
- Local PostgreSQL: Configured local PostgreSQL rather than running database engines inside Docker containers to keep development environments simple and avoid networking overhead.
- Rounding Remainder: Standard rounding (ROUND_HALF_UP) can result in a 1-paisa remainder (e.g. splitting 100 INR three ways). The payer absorbs this remainder because they managed the cash and can easily reconcile it on their statement.
- Generic Resolution API: Implemented a single generic resolve endpoint (/api/groups/{id}/anomalies/{id}/resolve/) routing payloads by problem_type rather than building individual views per anomaly type. This reduces routing overhead and keeps database transactions atomic.
- Missing Currency Default: Dominant currency in the dataset is INR, so missing currency rows default to INR and generate a warning rather than blocking imports.
- Strict Payer Validation: Missing payers are blocked. Payer mapping directly affects financial responsibility and cannot be guessed.

## Local Setup - Backend
- Prerequisites: Python 3.10+ and a running local PostgreSQL instance.

Steps:
1. Clone the repository and navigate to the root directory.
2. Create and activate a virtual environment:
   python -m venv venv
   source venv/bin/activate
3. Install the dependencies:
   pip install -r requirements.txt
4. Copy the environment template and configure local variables:
   cp .env.example .env
   Configure SECRET_KEY, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, and DB_PORT in the .env file.
5. Apply database migrations:
   python manage.py migrate
6. Create an admin superuser:
   python manage.py createsuperuser
7. Launch the development server:
   python manage.py runserver

## Local Setup - Frontend
- Prerequisites: Node.js (v18+) and npm.

Steps:
1. Navigate to the frontend directory:
   cd frontend
2. Install npm dependencies:
   npm install
3. Create a local environment file and define the API base URL:
   echo "VITE_API_URL=http://localhost:8000/api" > .env.local
4. Run the Vite development server:
   npm run dev

## Environment Variables
- Backend (.env):
  - SECRET_KEY: Secret string used for cryptographic signing.
  - DEBUG: Boolean toggle for Django debug mode.
  - ALLOWED_HOSTS: Comma-separated list of hostnames allowed to access the server.
  - DATABASE_URL: Full connection URL for PostgreSQL (Railway connection URL in production).
  - DB_NAME: Database name.
  - DB_USER: Database username.
  - DB_PASSWORD: Database password.
  - DB_HOST: Database host address.
  - DB_PORT: Database port number.
  - CORS_ALLOWED_ORIGINS: Permitted cross-origin endpoints.
  - USD_TO_INR: Fallback currency exchange rate.
- Frontend (.env.local):
  - VITE_API_URL: API base URL pointing to the Django backend.

## Deployment
- Production configurations pull all secrets and credentials dynamically from the hosting environment. 
- Django static files are compressed and served via WhiteNoise.
- Database connections in production are configured dynamically via DATABASE_URL on Railway.
- Build commands for Render are scripted in backend/build.sh.

## Known Limitations / Out of Scope
- Phase 5 LLM feature (receipt parser/expense suggestion) was deferred and is not implemented.
- Manual editing of calculated splits is not supported; incorrect expenses must be deleted and re-created to keep database sums consistent.
- CSV duplicates are permanently ignored at import time; they cannot be un-imported without purging the imported batch.
- Exchange rates are locked at code level (1 USD = 83.50 INR) and cannot be adjusted on a per-expense basis at runtime.

## AI-Assisted Development Note
This application was built in collaboration with AI coding assistants under a strict operating contract (GEMINI.md). Every significant architecture decision, API resolution logic, and bug fix was logged transparently in docs/AI_ACTIONS_LOG.md to ensure the engineer of record can explain and re-derive all codebase modifications.
