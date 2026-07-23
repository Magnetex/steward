# Build Steward — Session handoff (2026-07-22)

**Goal:** Single-user local budgeting + finance app (INR ₹, EveryDollar-inspired). Repo: `C:\tools\budget_tracker-2.0`
**Stack:** Python 3.12 · Flask (app-factory + blueprints) · SQLAlchemy · SQLite `instance/steward.db` · Flask-Migrate/Alembic · APScheduler. Front: Jinja2 + htmx + Alpine.js + Tailwind (standalone `tools/tailwindcss.exe`, no Node) + ApexCharts, vendored. Exact-Decimal money (`app/money.py::DecimalText`, TEXT-stored); IST dates. Durable facts auto-load from `.claude` memory (`budget-tracker-app.md`) — updated this session.
**Status:** ✅ Done & verified · **85 pytest tests pass** · no console errors.

## Done (this session)
- **Recent-payee/amount chips** in the add-transaction form — `/transactions/recents?type=` endpoint (`services/transactions.py::recent_payees/recent_amounts`); tappable chips under Amount & Payee, `en-IN` grouped labels; reuse `pickSuggestion`. Live-verified.
- **Savings type + investment cash-linking** (the big one — fixes a real accounting bug where buying an investment inflated net worth without deducting cash):
  - New `savings` txn type (`Transaction.flow` out/in; `signed_amount`/`all_balances` handle it). Migration `a1b2c3d4e5f6` adds `transaction.flow/invest_kind/invest_ref_id` + `recurring_rule.invest_kind/invest_ref_id`.
  - `services/invest_link.py`: `sync_cash()` / `unlink_cash()` / `sync_deposit_cash()`. MF/Gold buy+sell and FD get an optional **"Paid from"** account → creates a linked `savings` cash txn (tagged `invest_kind`+`invest_ref_id`; blank account = backfill, no cash effect). Sells credit cash (flow=in). **RD → monthly recurring savings rule** (`recurring.materialize_rule()` new).
  - Budget **Savings section** (`budget.compute_savings`/`savings_saved_by_category`; new `savings` category kind). Auto categories 📈 Mutual Funds / 🪙 Gold / 🏦 Deposits (names MUST match `invest_link.SAVINGS_CATEGORIES`; seeded).
  - **Net-worth neutral by construction** — live-verified: funded buy Δ=₹0; backfill (no account) +asset (expected).
  - `tests/test_savings.py` (9 tests).
- **Removed manual Savings from the add form** (user decision): add form has only 3 toggles (expense/income/transfer). Savings is created **only** via Investments "Paid from". Savings rows in the txn list are **read-only** `<a>` links to `/investments/?tab=` (no edit-dispatch, no delete; unlinked/legacy rows inert `#`). Budget Savings section kept but ＋ quick-add removed.

## Next (most important first)
- (Optional, deferred by user) Make the investment↔savings-category link **user-controlled** — recommended: assign a savings category **per holding** (like its `goal` field) so contributions roll up to it; then custom categories (e.g. PPF) become usable. Net worth stays correct (category is just a budget label). User said "just explain, don't build yet."
- Recurring-rules page type dropdown doesn't list "savings" — an RD's auto-rule shows there but can't be re-typed from that form. Minor.
- Older backlog: duplicate-transaction action · mobile/touch row actions (delete 🗑 hover-only) · keyboard-navigable ⋯ menus · chart text/table fallback.
- Rename Investments → Savings: still deferred.
- ➡️ **Next action:** await user direction. Nothing in progress. `flask reset-db` when convenient to clear this session's leftover test savings rows from the dev DB.

## Key decisions & gotchas
- **Savings category = budget label only**, NOT a net-worth factor. Net worth = cash + MF/Gold/Deposit/EPF/Stock buckets, independent of any txn's category. The *structural* investment↔cash link is `invest_kind`+`invest_ref_id` on the savings txn, not the category.
- Savings categories are **auto-labeled by kind** (all MF→"Mutual Funds"); user-created ones (PPF) are referenced by nothing → dead-end unless used as a manual budget goal. PPF is safe to delete (0 usage).
- EPF & US-stock stay **tracking-only** (no cash link — EPF isn't your cash; stock deferred).
- Editing a funded **deposit** with a blank "Paid from" is a no-op (won't silently unlink) — unlink by deleting the deposit.
- **MF holdings render alphabetically** → holding id ≠ render order. Don't infer a holding's id/NAV from the first row (cost time this session).
- Reports/tax/dashboard already type-scope to income/expense, so savings doesn't leak into those totals.
- app.js is a blocking `<head>` script (defines `stewardShell`/`txnForm` before Alpine) — don't defer. Overlays use `:class="{'is-open':open}"` + custom CSS, NOT x-transition. htmx mutations → 204 + `HX-Trigger {steward-refresh, steward-toast}`. **Recompile app.css after any template/CSS edit.** Alembic can't import app code (`env.py render_item` maps DecimalText→sa.String).

## Run & verify
```
export FLASK_APP=wsgi.py
flask db upgrade && flask seed        # or: flask reset-db  (drop+create+seed)
./tools/tailwindcss.exe -c tailwind.config.js -i app/static/css/input.css -o app/static/css/app.css --minify
.venv/Scripts/python -m pytest -q     # 85 passing
```
- Serve: `flask run` (:5055). **Browser screenshots are BROKEN here** — verify via pytest / `get_page_text` / `read_page` / `javascript_tool`.
- Live-verify a preview: `preview_start {name:"steward"}` (launch.json, :5055), then drive the page. A parallel session may also touch `instance/steward.db` — reset with care.

## Immediate context (last message)
User asked "Is this savings category actually used anywhere?" (pointing at PPF in category management). Queried dev DB: Mutual Funds used 6× (4 txns / 2 of them invest-linked + 2 budget lines), Gold 1×, Deposits 3×, **PPF 0 (unused)**. Explained: the 3 built-ins are used only because investment code hard-codes them as the label on the savings cash-out; PPF is referenced by nothing and can't be filled (manual savings entry is gone). Offered to make the link user-controlled (per-holding category, recommended). **User chose "Just explain, don't build yet."** I explained the full linkage (structural link = `invest_kind`/`invest_ref_id`; category = budget label; net worth unaffected), made **no code changes**, and noted PPF is safe to delete. Awaiting next direction.
