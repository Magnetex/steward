---
name: session-summary
description: >
  Produce a compact, structured handoff summary of the current conversation so
  the work can continue in a fresh session with minimal context. Use when the
  user asks to summarize the chat, hand off, "reduce the context window", start
  a new conversation, or capture where things stand. Output is a copy-pasteable
  block the user can drop into a new chat, with the immediate next step (the last
  message) preserved.
---

# Session Summary (handoff)

Goal: let a new session (or teammate) **resume the work without re-reading the
whole chat.** Optimize for "what do I need to know to continue," not a transcript.
Be concrete — real paths, commands, versions, decisions. Cut chatter, dead ends,
and anything the codebase or project memory already records (unless it informs a
decision). Convert relative dates to absolute.

## What to capture (in this order)

1. **Goal** — one line: what we're building/doing and where (repo path / URL).
2. **Environment & stack** — language/framework versions, key tools, how it runs.
   Only what a continuer needs; skip the obvious.
3. **Current status** — one line: done / in-progress / blocked, plus a health
   signal (tests passing? build green?).
4. **What's done** — the meaningful units delivered (features/phases), terse.
5. **What's pending / next** — the backlog, most important first. End with the
   single next action.
6. **Key decisions & gotchas** — the *non-obvious* things that would cost the next
   session time to rediscover: chosen approaches and why, traps, environment
   quirks, "don't do X because Y." This is the highest-value section.
7. **How to run & verify** — exact commands to install, migrate/seed, run, and
   test. Include the reliable verification path if the usual one is flaky.
8. **Immediate context (keep the last message)** — reproduce the essence of the
   most recent message/turn verbatim-enough that the next session knows the exact
   state and the immediate next step. If the user says "keep the last message,"
   include it faithfully, not just a paraphrase.

## Rules

- **Dense and scannable.** Prefer short bullets and small tables over prose. Aim
  for one to two screens; a handoff nobody reads is worthless.
- **Concrete over vague.** "`flask db upgrade && flask seed`; serve on :5055" beats
  "set up the database and run it."
- **Say the truth about state.** If tests fail or a step was skipped, note it.
- **Don't duplicate durable memory.** If the project has persistent memory/notes
  that auto-load, point to them and focus the summary on session narrative +
  current state + next step.
- **No secrets.** Never include credentials, tokens, or private data.

## Output

- Deliver the summary **in chat inside one fenced block** so the user can copy it
  straight into a new conversation.
- If useful (and the user wants a saved copy), also write it to a file in the repo
  (e.g. `SESSION_SUMMARY.md`) and say where.
- Title it with the project name + "handoff/summary" and a date.

## Skeleton

```
# <Project> — Session handoff (<YYYY-MM-DD>)

**Goal:** <one line + path/URL>
**Stack:** <versions/tools, how it runs>
**Status:** <done/in-progress/blocked> · <tests/build health>

## Done
- …

## Next (most important first)
- …
- ➡️ Next action: <the one thing to do next>

## Key decisions & gotchas
- <non-obvious thing> — <why / what to avoid>

## Run & verify
- install / migrate / seed / run / test commands
- reliable verification path (esp. if the normal one is flaky)

## Immediate context (last message)
<faithful reproduction of the most recent turn / current state>
```
