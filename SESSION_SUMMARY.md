# Build Steward — Session handoff (2026-08-03)

**Goal:** Single-user local budgeting/finance app (INR ₹). Repo `C:\tools\budget_tracker-2.0`, pushed to **`github.com/Magnetex/steward`** (private). This session: got it **running on the user's Android phone via Termux**, then built backup/restore and bank-SMS import.
**Stack:** Python 3.12 (3.13 on phone) · Flask app-factory + blueprints · SQLAlchemy · SQLite `instance/steward.db` · Flask-Migrate/Alembic · APScheduler. Front: Jinja2 + htmx + Alpine + Tailwind (standalone `tools/tailwindcss.exe`) + ApexCharts, vendored. Exact-Decimal money (`app/money.py::DecimalText`, TEXT). IST dates.
**Status:** ✅ Live on the phone and in use · **223 pytest green** · migrations at head **`bd91f1133943`** (9 files) · working tree clean, `main` == `origin/main`.

> **Durable facts auto-load from `.claude` memory `budget-tracker-app.md` — READ IT.** Updated this session with the whole Termux deployment section. This file is session narrative + current state only.

## Done (this session)
1. **Deployed to Android via Termux** — runs at `localhost:5055` and installs as a **real PWA** (localhost is a secure origin, so the service worker registers). One-tap **Termux:Widget** launcher (`tools/termux-start.sh`): guards against double-starting a second APScheduler, auto-opens the app via `termux-open-url`, backs up first.
2. **`flask fresh-db`** — wipe + recreate with only the 19 default categories (no sample data), for starting a real ledger. `seed_scaffold()` extracted from `seed_all()`. `reset-db`/`fresh-db` now **stamp Alembic head** (`create_all` built head-schema but left `alembic_version` stale → future "duplicate column" failures).
3. **Backup & restore** — Settings page + `flask backup <dir> --keep 14`. Byte-exact SQLite snapshots via the **online backup API** (safe mid-write), staged through `.part` then moved. Restore validates (magic bytes, `PRAGMA integrity_check`, expected tables) **before** touching anything, and snapshots what it replaces. Daily 21:00 scheduler job + launcher + manual, all recording `last_backup_at`; **stale-backup alert** + Settings status banner.
4. **Bank-SMS import** (`/imports`) — reads the inbox via `termux-sms-list`, parses, queues `PendingImport` rows for review. **Nothing ever auto-posts.** Parsers for **HDFC, Pluxee, RNSB** written against 11 real messages. Scans on launcher start, a Scan-now button, and daily 22:00; one shared "last scanned" timestamp.
5. **Dropped yfinance** → plain `requests` call to Yahoo's chart API (`market._yf_last_price`). Dependency tree is now **pure Python**; `requirements.txt` audited against every import.
6. **Bugs fixed:** dashboard vs `/networth/` disagreeing (dashboard read the last *snapshot*, page valued live) · `NameError` on an empty ledger (`ZERO` import dropped; `gold["value"] or ZERO` short-circuits on seeded data, so every test passed) · Accounts **Edit** button dead (`|tojson` inside a double-quoted `@click`) · duplicate detection comparing money **in SQL** (`DecimalText` is TEXT → `"555" != "555.00"`) · `grocery_wallet` account type folded into `wallet`.

## Next (most important first)
- **Get `/sdcard/Steward/backup` syncing to Drive/Syncthing.** On-device backups survive uninstalling Termux but not losing the phone. The user lost their entire ledger once already.
- **Watch the first real SMS scans** — parsers are proven against 11 samples only. `tests/test_sms_parse.py` is where a wording change will fail.
- Older backlog: keyboard-nav for ⋯ dropdown menus · chart text/table fallback.
- Known-but-deferred: seed places current-month rows on fixed days (`dm(this_m, 12)`), so **early in a month the demo data is future-dated** — inflates "spent" and broke a test once. Only affects `flask seed`.
- ➡️ **Next action:** nothing in progress — awaiting direction. User's last message was "All done".

## Key decisions & gotchas
- **Termux: all three apps from the SAME source, never Google Play.** Needs **Termux** + **Termux:API** (SMS, `termux-open-url`) + **Termux:Widget** (launcher). Android only shares data between identically-signed apps. The **Play build is a different fork** with no Termux:API — it says *"Termux:API is not yet available on Google play"*. Use GitHub releases for all three.
- **Termux:Widget silently ignores symlinks** whose canonical path is outside `~/.shortcuts`/`~/.termux` — it reports the folder *empty*. The shortcut must be a **real file** wrapping the repo script. Needs `chmod 700 -R ~/.shortcuts`. A bad shebang reports `exec(...): No such file or directory` naming the *script*; write it with `$(command -v bash)`.
- **`tzdata` must stay in requirements.txt** — `timeutil.py` builds `ZoneInfo("Asia/Kolkata")` at import. It used to arrive via yfinance→pandas. On Windows it also comes via tzlocal, so **a clean-venv check on Windows does not catch this**.
- **Keep dependencies pure Python** — a C extension fails to build on Termux.
- **Compare money in Python, never SQL** — `DecimalText` is TEXT.
- **Flask `|tojson` emits unescaped double quotes** → use **single-quoted** `@click='openX({{ …|tojson }})'`.
- **First SMS scan imports nothing by design** — plants the watermark so old messages and manually-entered duplicates are never pulled in.
- Self-transfers need **both** accounts' digits registered, else they degrade to a plain expense (double-count risk). Duplicate detection is also off for unregistered accounts.
- Migration autogenerate keeps proposing **spurious FKs on `deposit`/`mf_txn`** — delete them from generated migrations (they exist in the models, just unrecorded in SQLite; adding them forces a batch rebuild).
- **Browser screenshots are broken here** — verify with `get_page_text`/`read_page`/`javascript_tool`.
- Dev DB has verification drift (₹1,10,000 "Croma laptop" expense id 44, closed FD, archived goal). The phone DB is the real one.

## Run & verify
```bash
export FLASK_APP=wsgi.py
pip install -r requirements.txt      # pure Python, no compiler needed
flask db upgrade                     # head bd91f1133943
flask fresh-db                       # real ledger (or `flask seed` for demo data)
./tools/tailwindcss.exe -c tailwind.config.js -i app/static/css/input.css -o app/static/css/app.css --minify
.venv/Scripts/python -m pytest -q    # ~2 min; expect 223 pass
```
- Serve: `preview_start {name:"steward"}` (launch.json, `autoPort: true`) or `python wsgi.py` (reads `$PORT`, default 5055).
- Phone: tap the widget, or `~/steward/tools/termux-start.sh`.
- SMS diagnosis: **`flask sms-doctor`** prints raw `termux-sms-list` output + parsed field names.

## Immediate context (last message)
Everything is set up and working on the phone. The user confirmed **"All done"** after: rebuilding Termux from GitHub APKs (Termux + Termux:API + Termux:Widget), running `termux-setup-storage`, adding their accounts with **Bank SMS digits** (HDFC `4458, 8876` · RNSB `7655` · Pluxee `7803`), and verifying backups land in `/sdcard/Steward/backup`. Their original ledger was **lost** to the Play-Store-Termux reinstall, so they started fresh with `flask fresh-db`. I closed with a recap and one open nudge: **point Drive/Syncthing at the backup folder**. Nothing is in progress; awaiting the user's next request.
