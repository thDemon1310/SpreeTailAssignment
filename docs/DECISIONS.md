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
