# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A web platform for **Northern Star Engineering** (fire & safety company, Surat) covering **Annual
Maintenance Contracts (AMC)**. Three surfaces in one Flask app: a public marketing/intake site, a
customer portal, and a staff ops console — plus an OpenRouter-backed AI Q&A widget.

## Commands

```bash
.venv/bin/python run.py        # run dev server -> http://127.0.0.1:5055 (PORT env overrides)
.venv/bin/python seed.py       # (re)seed demo plans, staff, and a demo customer+contract
```

There is no build step, test suite, or linter configured. Verify changes by running the server and
exercising routes with `curl` against `127.0.0.1:5055` (the preview MCP sandbox cannot read `.venv`).

Demo logins (created by `seed.py`): admin `admin@northernstar.example`/`admin123`,
technician `tech@northernstar.example`/`tech123`, customer phone `9876543210` (dev OTP is printed on
the verify screen).

## Environment constraints (important — these shaped the stack)

- **No Node.js / npm / Homebrew / Docker** on this machine. Only Python 3.9, pip, git, sqlite3. Do not
  reach for a JS toolchain; this is intentionally a Python/Flask app.
- **System LibreSSL has no `hashlib.scrypt`.** Werkzeug password hashing must use
  `method="pbkdf2:sha256"` (see `User.set_password` in `nse/models.py`). The default scrypt crashes.
- **Port 5000 is occupied by macOS AirPlay** — hence port 5055.
- Tailwind is loaded via CDN in `base.html`; there is no CSS build.

## Architecture

App-factory pattern. `nse/__init__.py` builds the app, registers blueprints, injects template globals
(company branding from config, unread-notification count, `AI_ENABLED`), defines the `datefmt` filter
and `rupees` filter, and calls `db.create_all()` on startup (no migrations — schema changes to
`models.py` require deleting `nse_amc.db` and re-seeding).

**Blueprints** (`nse/blueprints/`), each owning one surface:
- `public.py` — unauthenticated: home, plans, apply, emergency, noc, enquiry, faq. Forms write
  `Contract` (status `pending`), `ServiceRequest`, or `Enquiry` rows. Applicants are linked to an
  existing customer `User` by phone when one exists.
- `auth.py` — customers log in by **phone + OTP** (`/auth/otp/request` → `/auth/otp/verify`, creates the
  `User` on first verify); staff log in by **email + password** (`/auth/staff`). `_home_for(user)`
  routes to portal vs ops console by role.
- `portal.py` (`/portal`) — customer views; every handler checks `contract.customer_id == current_user.id`.
- `admin.py` (`/ops`) — staff console. Key flow: `activate_contract` creates/links the customer account
  and **auto-generates the year's `Visit` rows** evenly spaced from the start date. Visit edits handle
  photo/report uploads and notify the customer on completion.
- `chat.py` (`/chat/ask`) — JSON endpoint for the AI widget.

**Roles & access:** `User.role` is `customer` / `technician` / `admin`. Decorators in `nse/utils.py`
(`customer_required`, `staff_required`, `admin_required`) gate handlers. `is_staff` = technician or admin.

**Domain model** (`nse/models.py`): `Contract` is the spine — it has `Visit`s (each with `VisitPhoto`s
and a service-report file path), `Equipment` (each with `RefillRecord`s), and `Quotation`s (with
`QuotationItem`s). `ServiceRequest` is the standalone emergency/NOC channel (works without a contract).
Several models expose computed helpers used directly in templates — e.g. `Contract.reference`
(`AMC-00001`), `Contract.completed_visits`/`next_visit`, `Equipment.refill_status`
(`ok`/`due_soon`/`overdue`) and `days_to_refill`, `Quotation.total`. After changing an equipment's
refill dates, call `recompute_next_refill()` so the derived `next_refill_date` stays correct.

**AI** (`nse/ai.py`): `ask(messages)` prepends a system prompt with Northern Star's company + AMC facts
(sourced from northernstarengineering.com) and calls OpenRouter. If `OPENROUTER_API_KEY` is unset or
starts with `PLACEHOLDER`, or the call fails, it returns a canned fallback reply rather than erroring —
the chat never hard-fails. Model is `OPENROUTER_MODEL` (default `anthropic/claude-haiku-4.5`). Note:
OpenRouter slugs are current-gen — the older `anthropic/claude-3.5-sonnet` 404s with "No endpoints
found"; verify a slug exists via `GET https://openrouter.ai/api/v1/models` before setting it.

**Uploads (dual backend):** `save_upload` (in `utils.py`) has two backends chosen at runtime. When
`BLOB_READ_WRITE_TOKEN` is set (production on Vercel), it uploads to **Vercel Blob** via REST and returns
an absolute `https://` URL; otherwise (local dev) it writes under `nse/static/uploads/<subdir>/` and
returns a path relative to `static/`. Whatever it returns is stored on the model (`VisitPhoto.file_path`,
`Visit.service_report_path`). Templates **must not** call `url_for('static', ...)` on these directly —
use the `upload_url` Jinja filter (`p.file_path|upload_url`), which returns absolute URLs as-is and
resolves relative paths against `static/`. The report-download route (`portal.report`) likewise redirects
to the Blob URL when the stored path is absolute, else falls back to `send_from_directory`.

**Config** (`nse/config.py`): reads `.env`. Relative SQLite paths are rewritten to absolute against the
project root so the DB location is stable regardless of CWD. Branding/contact strings come from env and
surface app-wide via the context processor in `__init__.py` — `COMPANY_NAME`, `COMPANY_CITY`,
`COMPANY_TAGLINE`, `EMERGENCY_HOTLINE` (toll-free, used in `tel:` links + emergency strip),
`COMPANY_PHONE` (direct line), `COMPANY_EMAIL`, `COMPANY_ADDRESS`. To change any of these, edit `.env`
(not the templates). When adding a new branding field, add it in three places: `config.py`, the
`inject_globals` context processor, and `.env`/`.env.example`.

**Branding assets:** the logo is an SVG recreation of the navy-circle + white-star + orbit emblem at
`nse/static/img/logo-emblem.svg`, referenced in the nav, footer, chat-widget header, and favicon (via
`url_for('static', ...)`). Company facts/stats on the home page and in the AI prompt are sourced from
the live site northernstarengineering.com.

## Styling / theme

The app uses a **dark "Linear-style" design system** (see [BRAND_GUIDELINES.md](BRAND_GUIDELINES.md)).
All theming lives in **`base.html`**, in two places:
1. The Tailwind CDN config exposes clean semantic tokens — `bg-canvas`, `bg-surface-1..4`,
   `text-ink`/`ink-muted`/`ink-subtle`, `bg-primary` (lavender #5e6ad2), `text-danger`, `success`.
   Prefer these tokens in **new** markup.
2. A `<style>` **override block** remaps the older light-theme utility classes (`bg-white`,
   `bg-slate-*`, `bg-navy-*`, `text-star-*`, etc.) that page templates still use onto the dark
   palette, with `!important` (needed to beat the CDN's runtime-injected utilities). This is why
   pages render dark without every template being rewritten.

Consequences to remember: when adding a color utility class that isn't already remapped, either use
a new `surface`/`ink`/`primary` token or add a line to the override block — otherwise it falls
through to Tailwind's light default. Form controls (`input/select/textarea`) are styled globally in
that same block, so individual fields rarely need color classes. Lavender `primary` is reserved for
brand mark / primary CTA / focus / links; red and green are functional-only semantics.

## Conventions

- Templates extend `base.html` and reuse macros from `_macros.html` (`status_badge`, `refill_badge`,
  `field`). The AI chat widget is `_chat_widget.html`, included globally.
- **Jinja string literals cannot contain escaped single quotes** (`\'`). When putting prose with
  apostrophes into `{% set %}` lists (e.g. the FAQ), reword to avoid them — `\'` raises a
  `TemplateSyntaxError`.
- Customer-facing money is rendered with the `rupees` filter (₹ with thousands separators).
- Status strings are lowercase with underscores (`in_progress`); `status_badge` maps them to colors.

## Hooks / automation

A project-level **`Stop` hook keeps this file honest.** `.claude/settings.json` registers
`.claude/hooks/check_claudemd.py`, which runs when a turn ends: it scans the session transcript for
`Edit`/`Write` calls and, if any **source** file (`.py`, `.html`, `.js`, `.css`, `.svg`, …) was edited
*after* the last `CLAUDE.md` edit, it blocks the stop and asks Claude to update `CLAUDE.md` (or state
the change is trivial). It guards on `stop_hook_active`, so it nudges at most once per stop sequence —
no loops. Uses system `python3` (stdlib only; no `.venv` needed). The hook is registered at session
startup, so edits to it take effect next session — verify with `/hooks`.

## Deployment (Vercel)

The app is wired to run as a **Vercel Python serverless function**. Key pieces:
- `api/index.py` exposes the WSGI `app` (via `create_app()`); `vercel.json` routes **all** paths to it
  (`builds` → `@vercel/python` with `includeFiles: "nse/**"` so templates + static get bundled).
- **Database:** SQLite does not persist on Vercel (read-only/ephemeral FS), so production needs a managed
  **Postgres** (Neon etc.) via `DATABASE_URL`. `config.py` normalises `postgres://` → `postgresql://` and,
  for Postgres, sets `SQLALCHEMY_ENGINE_OPTIONS` to `NullPool` + `pool_pre_ping` (serverless workers must
  not hold a pool). `create_app()` runs `db.create_all()` on cold start, so tables self-create; seed once
  by running `seed.py` with `DATABASE_URL` pointed at the remote DB.
- **Uploads:** set `BLOB_READ_WRITE_TOKEN` so `save_upload` uses Vercel Blob (see Uploads above) — the
  local-disk path would be lost between invocations.
- **Env vars:** set `SECRET_KEY`, `DATABASE_URL`, `BLOB_READ_WRITE_TOKEN`, `OPENROUTER_API_KEY`, and the
  `COMPANY_*` overrides in the Vercel dashboard (Project → Settings → Environment Variables). `.env` is
  gitignored and not deployed.
- **Deploy path:** the Vercel CLI needs Node (absent on the dev machine), so deploy via **Git integration**
  — push the repo to GitHub and connect it in Vercel. `psycopg2-binary` is in `requirements.txt` for the
  Postgres driver.

## Known dev-grade pieces (not yet production)

OTP is a dev flow (code shown on screen, not SMS). Payments record cash/online **intent** only — no
gateway. DB is SQLite (swap to Postgres via `DATABASE_URL`). These are deliberate; harden on request.
