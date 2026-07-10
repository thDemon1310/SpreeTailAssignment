# Operating Contract for Gemini CLI on this project

You are working alongside a human engineer who is the engineer of record and will be evaluated live, with no notice, on any line in this repo. Your job is to move fast AND leave the human able to re-derive and re-explain everything. This contract is not a style guide — it is enforced. Do not skip sections because a task "seems simple."

## 1. Core loop (hard gate version)
1. Work only from `TODO.md`. Never invent scope outside it — if you think something's missing, add it as a new item and flag it, don't just do it.
2. One task at a time. Mark `[~]` before starting, `[x]` plus a one-line note of what you *actually* built (not a restatement of the task) when done.
3. **Every phase in TODO.md ends in a GATE.** A gate is a checkbox that only the human may tick. You must stop, summarize what you built and why, and wait. Do not start the next phase's first task on your own initiative, even if it looks obvious. This is the single most important rule in this file — agents that skip gates are the reason this contract exists.
4. One task = one commit. Never combine two TODO items into a single commit, even if they're related and even if you're moving fast. If you catch yourself about to do this, stop and commit what you have first. Commit message format: `type: what changed` (e.g. `feat(import): detect duplicate expenses by normalized hash`), not `update` or `wip`.
5. If a task is ambiguous, or you're about to make a judgment call not already covered by `PLAN.md` or a prior `DECISIONS.md` entry, STOP and ask. Do not proceed on your best guess. "I'll pick a reasonable default and mention it" is not acceptable for anything touching money, dates, or membership — those get a decision log entry and, if not already policy, human sign-off first.

## 2. When something breaks (this section did not exist before — follow it)
- **Migration/build/test failure:** do not "work around" it by changing the model or test to make the error go away. Diagnose the actual cause, fix the root issue, note in your commit message what broke and why.
- **External dependency down (FX API, deploy platform, etc.):** do not silently swap in a hardcoded fallback and continue as if nothing happened. Flag it to the human, propose the fallback, wait for a yes.
- **You realize a completed, committed task was wrong:** do not quietly patch it in the next commit. Add an explicit entry to `DECISIONS.md` under a "Corrections" heading: what was wrong, why, what changed. This is required input for `AI_USAGE.md` later — do not make the human dig commit history for it.
- **You're not sure if something counts as an anomaly:** default to treating it as one. Under-flagging is the failure mode this whole assignment is designed to catch.

## 3. Test-first requirement (non-negotiable, not "as time allows")
Split calculation and balance calculation are the two things the human will be asked to hand-trace live. Before either is wired to an API endpoint:
- Write unit tests covering: each split type (equal/unequal/percentage/share), a membership-window exclusion case, and a rounding edge case.
- Only after those pass do you wire the function to a view.
Do not reorder this. "I'll add tests after" on this specific logic is a rule violation, not a scheduling choice.

## 4. Required log formats — use these templates exactly, every entry

### DECISIONS.md — one entry per decision, this exact shape:
```
## [date] Decision: <short title>
**Options considered:** A, B, C (one line each on what each would mean)
**Chosen:** which one
**Why:** the actual reasoning, not "seemed best"
**Tradeoff accepted:** what you're giving up by not picking the others
**Reversible?** yes/no — if a live-session change request would touch this, say so
```
Thin entries ("chose equal split because it's simpler") will fail the live session. If you can't fill every field honestly, the decision isn't finished yet — ask the human.

### SCOPE.md — anomaly table, one row per anomaly type, kept live as you work:
```
| # | Anomaly | Detection method | Rows affected | Policy applied | Reversible in UI? |
```
Plus a schema section (link to models file + a plain-English paragraph per table explaining why it's shaped that way — the "why" is what gets asked live, not just the DDL).

### AI_ACTIONS_LOG.md — append after any non-trivial generation:
```
## [date] <task>
**Asked for:** ...
**Produced:** ...
**Human caught wrong / had to redirect?** yes/no — if yes, what and how it was fixed
```
Do not skip the "wrong" field even when the answer is "no" — the human needs an honest running tally, not just the wins, to write `AI_USAGE.md`'s required 3+ failure examples truthfully.

## 5. Anomaly handling depth
For every anomaly in TODO.md Phase 3, "detect it" means: a named detection method (exact rule, threshold, or heuristic — not "look for weird ones"), a defined storage shape in `ImportAnomaly`, and a defined fallback for the case where detection is uncertain. If any of those three is missing from your implementation, the task is not done — go back and fill the gap before checking it off. TODO.md now specifies the required depth per item; match it, don't simplify it.

## 6. Definition of done, project-wide
A task is only `[x]` if: it's tested (where Section 3 applies), it's committed on its own, it's logged where a log applies, and you could explain it cold to the human in one sentence without re-reading your own code. If any of those isn't true, it's still `[~]`.
