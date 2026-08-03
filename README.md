# Build Steward

A calm, budget-first personal finance tracker for a single user, running locally.
Inspired by EveryDollar in spirit — clean and friendly — but with looser category
budgets and overshoot alerts rather than strict zero-based budgeting. All amounts
are INR (₹).

Steward tracks budgets, transactions (with splits & transfers), recurring bills,
sinking funds, and investments (mutual funds, gold, FD/RD deposits, EPF, US stock),
plus net-worth trends, reports, and an Indian capital-gains / 80C tax report.

## Stack

- **Backend:** Python 3.11+, Flask (app-factory + blueprints), SQLAlchemy, SQLite
  (`instance/steward.db`), Flask-Migrate/Alembic, APScheduler.
- **Frontend:** Jinja2 + htmx + Alpine.js + Tailwind CSS + ApexCharts. No Node build
  step — Tailwind is compiled with the standalone CLI binary, and htmx/Alpine/ApexCharts
  are vendored into `app/static/vendor/` so the UI works offline.
- **Money:** every amount and unit is an exact `Decimal` (stored as text; aggregated in
  Python, never in SQL). All dates are IST.

Everything works fully offline except the price-refresh jobs; a failed fetch never
breaks the UI (the last-known price and its "as of" time are kept).

## Setup

```bash
# 1. Create a virtualenv and install dependencies
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

# 2. Point Flask at the app
export FLASK_APP=wsgi.py            # Windows (Git Bash): same; PowerShell: $env:FLASK_APP="wsgi.py"

# 3. Create the database schema (migrations)
flask db upgrade

# 4. Load realistic sample data (accounts, two months of budgets & transactions,
#    a mutual fund with SIP history, gold, an FD & RD, EPF entries, snapshots…)
flask seed

# 5. Run
flask run                          # http://127.0.0.1:5000
```

`flask reset-db` drops, recreates, and re-seeds in one step (handy during development).

### Importing transactions from bank SMS (Android)

**SMS imports** in the nav reads bank alerts via Termux:API and queues them for review.
Nothing is ever posted automatically — a misparse costs one dismissal, never a wrong
figure in the accounts.

Setup: install the **Termux:API** app, `pkg install termux-api`, then grant it the SMS
permission (Android may need this done manually under Settings → Apps → Termux:API →
Permissions). Then open **Accounts** and fill in **Bank SMS digits** for each account —
the trailing digits it appears as in alerts, comma-separated. An HDFC savings account
quoted as both `A/c XX4458` and `Card x8876` takes `4458, 8876`, so card spends land on
the right account.

Scans run three ways, all sharing one "last scanned" timestamp shown on the page: when
the launcher starts, from the **Scan now** button, and daily at 22:00 IST.

Guards worth knowing:

- **The first scan imports nothing.** It plants a watermark at "now", so enabling the
  feature never drags in old messages or duplicates what you already entered by hand.
  Only SMS arriving afterwards are considered.
- **Re-scanning is a no-op.** The whole inbox is re-read each time; the watermark plus a
  unique hash per message mean each one is considered exactly once.
- **Money moving between your own accounts becomes one transfer**, not an expense plus an
  income, which would inflate both sides of the budget.
- **Likely duplicates are flagged** — a matching amount on the same account within three
  days shows a warning instead of silently double-counting.
- Categories are pre-filled from payee memory, so a merchant you've categorised before
  comes back with the same category.

Banks are recognised by name in the sender ID (senders vary: `VM-HDFCBK`, `AD-HDFCBK`).
Currently HDFC, Pluxee and RNSB, in `services/sms_parse.py` — add one by writing patterns
and appending to `PARSERS`. Every pattern is tested against real message text in
`tests/test_sms_parse.py`; if a bank changes its wording, that's where it will fail.

### Backup & restore

**Settings → Backup & restore**. "Download backup" gives you a byte-exact SQLite
snapshot (taken with SQLite's online backup API, so it is safe and consistent even
while the app is serving). Restore uploads one back.

Restore replaces *everything*, so it asks twice and snapshots the database it is about
to overwrite to `instance/steward-replaced-<timestamp>.db` first — a mistaken restore is
recoverable. Uploads are validated before anything is touched: wrong magic bytes, a
failed `PRAGMA integrity_check`, or a SQLite file that isn't a Steward database is
rejected with the live data untouched. Restart the app afterwards.

On a phone this is the only thing standing between you and total loss, since the
database lives in Termux's private storage. Download a backup somewhere off the device
(Drive, Syncthing, USB) on a schedule you'll actually keep.

There is also a CLI form, used by the Termux launcher (see below):

```bash
flask backup /sdcard/Steward/backup --keep 14
```

It writes one dated file per day (`steward-2026-08-02.db`), so running it repeatedly
overwrites the day's file rather than piling up, and prunes to the newest `--keep`.
Despite the name, `/sdcard` is **internal shared storage** on every Android phone —
not a physical card — so this works without one.

### Starting a real ledger

`flask seed` is sample data — useful for seeing every screen populated, useless once you
want to track your own money. To wipe it and begin for real:

```bash
flask fresh-db
```

That drops everything and recreates the schema with **only** the default categories
(11 expense, 3 income, 5 savings) — no accounts, transactions or holdings. Add
`--no-categories` for a completely bare database, or `--yes` to skip the confirmation
prompt. Then add your accounts with their real opening balances and start logging.

### Rebuilding the stylesheet

The compiled CSS (`app/static/css/app.css`) is checked in. If you change templates or
`app/static/css/input.css`, recompile with the standalone binary:

```bash
./tools/tailwindcss.exe -c tailwind.config.js -i app/static/css/input.css -o app/static/css/app.css --minify
```

(Download the binary once from the Tailwind releases page if it isn't present.)

## Price data & background jobs

All prices are free and need no API keys. The UI always reads from the `PriceCache`
table; only the refresh jobs/buttons touch the network. Every fetch uses a 10s timeout,
retries once, and on failure keeps the cached value.

| Source        | Where from                                                        |
|---------------|-------------------------------------------------------------------|
| MF NAVs       | `api.mfapi.in/mf/{scheme_code}` (per-scheme daily NAV + history)   |
| Gold (₹/gram) | Yahoo `GC=F` (USD/oz) × `USDINR=X` ÷ 31.1035; manual override in Settings takes precedence |
| US stock      | Yahoo chart API by ticker (converted to INR via USDINR)          |

**APScheduler** runs inside the app and refreshes automatically (IST):

- **21:30** — mutual fund NAVs (published after market close)
- **08:00** — gold, USD→INR, and stock prices
- **06:00** — materialize due recurring rules
- **23:00** — record a net-worth snapshot
- **07:15 & 20:15** — sweep maturity / overshoot alerts

Trigger the same logic manually:

```bash
flask refresh-prices     # MF NAVs, gold, USDINR, stock — prints per-instrument status
flask run-recurring      # process due recurring rules (auto-create + remind-only)
flask snapshot           # record a net-worth snapshot now
```

There's also a **Refresh prices now** button in Settings (per-instrument success/failure),
and per-tab refresh buttons on the Investments page. A "Snapshot now" button lives on the
Net worth page.

## Domain rules worth knowing

- **Salary rule:** income dated in the last *N* days of a month (N = the
  `salary_rule_window` setting, default 7) is assigned to *next* month's budget. The
  transaction keeps its real date; only the budget month shifts, and it's overridable per
  transaction.
- **Budgets** reset monthly and do not roll over. "Copy last month" seeds a new month.
- **Overshoot alerts:** a category turns amber at ≥80% of its plan and red past 100%
  (with a toast and a bell alert).
- **Funds** are envelope-style accounts; money moves in via transfers and out via expenses.
  Transfers never count as income or expense in budget math.
- **Tax** rates live in Settings (seeded with current Indian defaults) and are fully
  editable. The Tax page is a report, not tax advice.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

The suite focuses on the money math that must be exact: Indian number formatting,
Decimal storage round-trips, account balances, the salary rule, split sums, budget
aggregation & overshoot, the recurring scheduler, FD/RD/EPF calculators, XIRR, gold/stock
valuation, FIFO capital gains, and 80C.

## Project layout

```
app/
  __init__.py          app factory, template filters, context processors
  models.py            all SQLAlchemy models (one migration covers the schema)
  money.py             Decimal type + ₹ formatting
  timeutil.py          IST date helpers (months, financial year, salary window)
  scheduler.py         APScheduler jobs
  cli.py               flask init-db / reset-db / seed / refresh-prices / run-recurring / snapshot
  blueprints/          one per section (dashboard, transactions, budgets, …)
  services/            all money math & aggregation (never in templates)
  templates/  static/  Jinja + vendored JS/CSS + PWA manifest/service worker
migrations/            Alembic
tests/                 pytest
```

## PWA

A web-app manifest and a minimal service worker (static-asset caching) are included, so
the app can be installed via "Add to Home Screen". Full offline mode is not a goal.

## Using it on your phone

**Build Steward has no login screen.** Anyone who can reach the URL has full read/write
access to every account, transaction and holding. So: never put it on a public URL
(ngrok, a Cloudflare tunnel, a VPS) as-is. Both options below keep it on a private
network instead.

### Option A — same Wi-Fi (5 minutes, PC must be awake)

```powershell
.\tools\serve-lan.ps1            # binds 0.0.0.0:5055, prints your LAN URL
```

Then open `http://<your-pc-ip>:5055` on the phone. Two one-time Windows chores, both
from an **admin** PowerShell:

```powershell
Set-NetConnectionProfile -InterfaceAlias 'Wi-Fi' -NetworkCategory Private
New-NetFirewallRule -DisplayName 'Build Steward' -Direction Inbound -Protocol TCP -LocalPort 5055 -Action Allow -Profile Private
```

Caveats: only works at home, the PC must be on, and because `http://` on a LAN IP is not
a "secure origin" the **service worker won't register** — "Add to Home Screen" gives you
a shortcut, not a real installed PWA.

### Option B — on the phone itself, via Termux (Android only)

Runs the whole app on the phone: offline, no server anywhere, no monthly cost. Because
`http://localhost` **is** a secure origin, the service worker registers and the app
installs as a genuine PWA — standalone window, home-screen icon, no browser chrome.

Install [Termux](https://f-droid.org/packages/com.termux/) from **F-Droid or GitHub —
not the Play Store**, whose build is deprecated and can't reach current package repos.
The **Termux:Widget** addon (same source) is worth grabbing too.

```bash
pkg update && pkg upgrade -y
pkg install python git -y

git clone <your-repo-url> steward && cd steward
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export FLASK_APP=wsgi.py
flask db upgrade        # then: flask seed   (sample data)
python wsgi.py          # serves http://localhost:5055
```

Then open `http://localhost:5055` in Chrome → menu → **Install app**.

Four things to know:

- **Your database does not travel through git.** `instance/` and `*.db` are ignored, by
  design — financial data does not belong in a repo, private or not. To carry your real
  ledger across, copy `instance/steward.db` (~200 KB) over by USB, Syncthing or Drive
  and drop it in `instance/` *instead of* running `flask seed`.
- **Every dependency is pure Python**, so `pip install` needs no compiler and no
  build tools. (`yfinance` used to be the exception — it pulled in pandas and numpy for
  a single price lookup, which is slow and often fails to build on Android. It was
  replaced with a plain `requests` call to the same Yahoo endpoint.)
- **No Tailwind needed.** `app/static/css/app.css` is committed; the standalone binary is
  gitignored and is a Windows executable anyway. Only recompile if you edit templates.
- **Back the database up.** It lives in Termux's private storage, so uninstalling Termux
  or losing the phone destroys it. Run `termux-setup-storage` and copy it to `/sdcard`
  on a schedule.

To keep it alive in the background, exempt Termux from battery optimisation and use
`termux-wake-lock`. Better for battery: don't — put a Termux:Widget launcher on the home
screen and start it on demand. The scheduler jobs are idempotent catch-up work, so they
simply run at next launch (the one exception is the 23:00 net-worth snapshot, which is
silently missed on days the app never runs).

### Launching it with one tap

Typing `cd steward && . .venv/bin/activate && ... && python wsgi.py` every time gets old
fast. [`tools/termux-start.sh`](tools/termux-start.sh) does all of that in one script —
wire it up once as a **Termux:Widget** shortcut and starting the server becomes a single
home-screen tap.

1. Install **[Termux:Widget](https://f-droid.org/packages/com.termux.widget/)** — same
   source as Termux itself (F-Droid or GitHub), not the Play Store.
2. `chmod +x ~/steward/tools/termux-start.sh`
3. `mkdir -p ~/.shortcuts && ln -s ~/steward/tools/termux-start.sh ~/.shortcuts/steward.sh`
   — a symlink, so `git pull` keeps it current with no re-linking.
4. Long-press an empty spot on the home screen → **Widgets** → **Termux:Widget** → drag
   the single-shortcut style onto the home screen → pick `steward.sh` when prompted.

Tapping it opens Termux and starts the server. On its own it stops there — Termux has no
way to hand off to another app by itself, so the addon **Termux:API** is what does that
handoff:

5. Install **[Termux:API](https://f-droid.org/packages/com.termux.api/)** (same source),
   then `pkg install termux-api`.

With that installed, the script polls the port and fires Android's "open URL" intent the
moment the server answers — which opens the **installed Steward app itself**, standalone
window and all, not a browser tab, because the PWA is registered as that URL's handler.
Skip step 5 and it falls back to printing the URL for you to open by hand.

The script refuses to start a second copy if one's already running, so double-tapping is
harmless — tapping it again while the server's already up just re-opens the app. The real
switch is off: closing that Termux session kills the server, since nothing here manages
it as a background service.

**Every launch also writes a backup** to `/sdcard/Steward/backup`, keeping the newest 14.
That folder is internal shared storage, outside Termux's private directory, so it
survives uninstalling Termux and other apps can see it — point Drive or Syncthing at it
and backups leave the device on their own. Run `termux-setup-storage` once to grant the
permission; without it the launcher just says so and starts the server anyway. Note this
only runs when you tap the launcher, so a week without opening the app is a week without
a new backup — and `/sdcard` is the same physical device, so it does not protect against
losing the phone until something syncs it off.

If your launcher's long-press menu doesn't offer "Widgets" the same way, Termux:Widget's
[own docs](https://github.com/termux/termux-widget) cover the alternative "dynamic
shortcuts" method, which pins a real launcher icon instead of a widget.

### Routes that were considered and dropped

**Tailscale** (would give access from anywhere, over real HTTPS, with no firewall
changes) — rejected because the installed client is signed into a **company** tailnet.
Putting personal finances on a work tailnet exposes them to devices and admins outside
your control. Viable later only under a separate personal Tailscale account.

**Packaging as an Android APK** (Chaquopy embeds CPython, Flask runs on `127.0.0.1`
inside the app, a WebView renders it) — technically sound, and cheaper than it looks
and the dependency tree is now pure Python. Dropped as too large for now: it needs
a full Android toolchain, and turns every update into a rebuild-and-sideload. Termux
above gets most of the same benefit for a fraction of the work.

**Any public URL** (ngrok, Cloudflare tunnel, a VPS) — not viable until the app grows a
login and CSRF protection. See the warning at the top of this section.
