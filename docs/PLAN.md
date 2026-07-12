# Spreetail Assignment — Your Plan


## 1. Stack (lock this in, don't let the AI wander)
- **Backend:** Django + Django REST Framework, PostgreSQL (relational, required)
- **Frontend:** React (Vite), fetch/axios to DRF endpoints
- **Auth:** Django's built-in auth + DRF TokenAuth or simple JWT (djangorestframework-simplejwt) — don't overbuild this
- **Deploy:** Render or Railway for backend+Postgres, Vercel/Netlify for frontend (both have free tiers, fast to deploy). Pick one, don't shop around on day 2.
- **LLM/AI integration hook:** the assignment JD mentions LLM/AI API integration as a core skill area, but the assignment brief doesn't strictly require it in the product. Add ONE small genuine use: e.g. "paste a receipt description, LLM extracts amount/description/split suggestion" as an optional add-on. Don't let this eat day 2 — it's a bonus, not the core deliverable.

## 2. Data model — decide this before importing anything
- `User` (flatmate)
- `Group` (e.g. "The Flat")
- `Membership` (user, group, `joined_on`, `left_on` nullable) — **this is the key table**. It's how you answer Sam's and Meera's questions: an expense only affects a member's balance if the expense date falls within their membership window.
- `Expense` (group, paid_by, amount, currency, original_amount, exchange_rate, date, description, split_type, created_at, is_settlement bool)
- `ExpenseSplit` (expense, user, share_amount) — always store the computed per-person amount, never recompute on the fly for display. This is what answers Rohan's "no magic numbers" request — every balance must be traceable to rows in this table.
- `Settlement` (from_user, to_user, amount, date, note) — separate from Expense, not a hack inside it
- `ImportBatch` / `ImportAnomaly` (row reference, problem type, detected value, action taken, resolved_by, resolved_at) — this table IS your import report and half of SCOPE.md

## 3. Policies you must decide NOW (write these into DECISIONS.md as you go, don't retrofit at the end)
Pick an answer for each — there's no single correct one, but you must be consistent and able to justify it:
1. **Negative amounts** — refund (reduces payer's outlay) vs error (reject). Recommendation: treat as refund, reduce the expense amount, flag in import report.
2. **Duplicate expenses (identical)** — e.g. same dinner logged twice verbatim. Recommendation: hash on (date, amount, paid_by, description-normalized) → auto-flag, keep first, log dropped duplicate.
3. **Same expense, different amounts** — two people log "same" dinner with different totals. This is NOT a safe auto-merge. Recommendation: import both as separate line items but flag as "possible duplicate — needs human review," don't guess which is correct.
4. **Settlement logged as expense** — row where split_type is blank/description says "paid X back." Recommendation: detect via heuristic (single recipient in split_with, description pattern, or split_type empty) → import into `Settlement` table, not `Expense`.
5. **Currency conversion** — USD rows. You need a rate. Recommendation: use a fixed documented rate (state it, e.g. "1 USD = 83 INR, rate as of [date], not live-fetched" — simpler and defensible in the live session) OR call a free FX API once at import time and store the rate used per-expense (better if you want the AI-integration point). Either is fine — just document it and store `exchange_rate` + `original_amount` on every converted expense so nothing is silently lossy.
6. **Non-member in split (Kabir)** — someone in `split_with` who isn't a group member. Recommendation: don't silently drop him or silently add him as a real member. Either (a) exclude his share and redistribute among real members, flagging this, or (b) auto-create him as a lightweight "guest" record excluded from ongoing balances. Pick one, document why.
7. **Stale membership in split_with** (e.g. Meera listed in an April expense after she left) — cross-check split_with against `Membership` windows at import time. Recommendation: flag and exclude her from that specific split, redistribute her share, log it.
8. **Missing paid_by** — reject the row into a "needs manual resolution" queue, do not guess. This directly satisfies Meera's request ("I want to approve anything the app deletes or changes").
8b. **Missing currency** — default to INR (the dataset's dominant currency) but flag visibly in the import report. This is a low-risk inference, unlike missing payer.
9. **Ambiguous/impossible dates** (2014 typo, 05-04 ambiguity) — flag any date outside a sane range (e.g. before Feb 2026 or after your data window) and any date where day/month are both ≤12 as ambiguous. Don't auto-correct — surface it for approval.
10. **Percentages that don't sum to 100%** — reject or normalize? Recommendation: detect, normalize proportionally, and flag loudly that you did so — don't silently accept a 110% split.
11. **Conflicting split_type vs split_details** (says "equal" but has explicit shares attached) — split_details present should win if type says equal but data suggests otherwise; flag as an inconsistency regardless of which way you resolve it.
12. **Rounding** (899.995) — decide a rounding policy (e.g. round to nearest paisa/2dp using banker's rounding or standard half-up) and apply it consistently everywhere balances are computed, not just at import.
13. **Fuzzy name matching** ("Priya", "priya", "Priya S", "rohan ") — normalize (trim, casefold) at import; if a name doesn't confidently match an existing member, flag for manual mapping rather than silently creating a new user.

## 4. Two-day timeline
**Day 1**
- Scaffold Django + DRF project, models, migrations, admin registration
- Auth working (register/login/token)
- Group + Membership CRUD APIs
- Expense + Split CRUD APIs (all split types: equal, unequal, percentage, share)
- Balance calculation logic (respecting membership windows) — write this as a standalone testable function first, wire to API second
- Settlement recording API
- Start React scaffold, wire login

**Day 2**
- Build the CSV import pipeline: parse → detect anomalies per policy list above → write to `ImportAnomaly` → apply resolutions → generate import report
- React: group view, expense list, add expense (all split types), balance summary, settle-up screen, import report screen
- Deploy both sides, smoke test on the live URL
- Write SCOPE.md, DECISIONS.md, AI_USAGE.md, README.md from your running log (see GEMINI.md workflow — don't write these from memory at 11pm, they should already exist incrementally)
- Do a full manual balance trace for at least one person by hand and check it against the app, before you submit — this is literally in the eval rubric

## 5. Non-negotiable discipline
- **Real commit history.** Commit after every working unit (model, endpoint, component), not one bulk commit.
- **Read every diff Gemini produces before accepting it.** You will be asked to justify any line, live, with no warning.
- **Keep AI_USAGE.md updated as you go** — the three "AI got it wrong" examples are easiest to capture in the moment (e.g. AI silently averaged the two conflicting Thalassa dinner rows instead of flagging them — catch it, note it).

## 6. How to use the other two files
- `GEMINI.md` → put this in your project root; it's the operating contract for Gemini CLI (how it should behave, not what to build).
- `TODO.md` → give this to Gemini CLI as the actual task list, seeded with the anomaly catalogue I found in your CSV. Tell it to update this file as it works.
