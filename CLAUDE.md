# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A web platform for **Northern Star Engineering** (fire & safety company, Surat) — a **"Blinkit for
fire safety"** covering four instant-response services: **AMC** (Annual Maintenance Contracts),
**emergency response**, **on-demand extinguisher refilling**, and **fire NOC assistance**. Three
surfaces in one Flask app: a public marketing/intake site, a customer portal, and a staff ops console
— plus **Tara**, an OpenRouter-backed AI assistant. The name means "star" in Sanskrit, fitting the North Star brand identity and the company tagline **"Enlightening Safety"**.

**"Blinkit" is an internal concept shorthand only — never put the competitor brand name in
customer-facing copy** (templates, AI replies). It was removed from the hero, footer, and home
subtitle on request; describe the idea in NSE's own words ("fast, all-in-one fire safety") instead.

## Commands

```bash
.venv/bin/python run.py        # run dev server → http://127.0.0.1:5055 (PORT env overrides)
.venv/bin/python seed.py       # (re)seed demo plans, staff, and a demo customer+contract

# After any schema change to nse/models.py (no migrations — db.create_all only adds tables):
rm nse_amc.db && .venv/bin/python seed.py

# Smoke-test routes without a browser (curl is in /usr/bin on macOS):
/usr/bin/curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5055/
```

There is no build step, test suite, or linter. Verify changes by running the server and exercising
routes. The **Claude preview pane cannot run this app**: the project lives under `~/Downloads`,
which macOS TCC blocks — the sandbox gets "Operation not permitted" on every project file and cannot
read `.venv`. Always use the Bash-run server. `run.py` prepends venv `site-packages` to `sys.path`,
so it also boots under system Python (`/usr/bin/python3 run.py`) — the `.claude/launch.json` uses
`/usr/bin/python3` for exactly this reason (the preview tool's sandbox also can't read `.venv`).

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
(company branding from config, unread-notification count, `AI_ENABLED`), defines the `datefmt` filter,
`rupees` filter, and `upload_url` filter, and calls `db.create_all()` on startup (no migrations —
schema changes to `models.py` require deleting `nse_amc.db` and re-seeding).

**Blueprints** (`nse/blueprints/`), each owning one surface:
- `public.py` — unauthenticated: home, plans, apply, **refill**, emergency, noc, **about**, enquiry, faq. Forms
  write `Contract` (status `pending`), `RefillOrder` (+`RefillItem` line items), `ServiceRequest`, or
  `Enquiry` rows. Applicants/bookers are linked to an existing customer `User` by phone when one exists.
  **AMC apply auto-quotes:** when a plan is selected, the apply POST also auto-creates a `ServiceQuotation`
  (status `sent`, QUO number assigned, one line item from the plan price + 18% GST) linked to the new
  contract. The confirmation page shows the QUO reference and prompts the customer to log in and respond.
- `auth.py` — customers log in by **phone + OTP** (`/auth/otp/request` → `/auth/otp/verify`, creates the
  `User` on first verify); staff log in by **email + password** (`/auth/staff`). `_home_for(user)`
  routes to portal vs ops console by role.
- `portal.py` (`/portal`) — customer views; every handler checks `contract.customer_id == current_user.id`.
- `admin.py` (`/ops`) — staff console. Key flow: `activate_contract` creates/links the customer account
  and **auto-generates the year's `Visit` rows** evenly spaced from the start date. Visit edits handle
  photo/report uploads and notify the customer on completion. Also manages `RefillOrder`s
  (`/ops/refills`, `/ops/refill/<id>`): set status/ETA/scheduled-date/final-amount/payment, notifying
  the customer.
- `chat.py` (`/chat/ask`) — JSON endpoint for the AI widget.

**Roles & access:** `User.role` is `customer` / `technician` / `admin`. Decorators in `nse/utils.py`
(`customer_required`, `staff_required`, `admin_required`) gate handlers. `is_staff` = technician or admin.

**Template layout** (`nse/templates/`): `base.html` + `_macros.html` + `_chat_widget.html` at the
root; subdirs `public/`, `portal/`, `admin/` mirror the blueprints. `auth/` holds login screens.
All templates extend `base.html`; portal and admin templates also lean on `_macros.html` for
`status_badge`, `refill_badge`, and the `field()` form helper.

**Domain model** (`nse/models.py`): `Contract` is the spine — it has `Visit`s (each with `VisitPhoto`s
and a service-report file path), `Equipment` (each with `RefillRecord`s), and `Quotation`s (with
`QuotationItem`s). `ServiceRequest` is the standalone emergency/NOC channel (works without a contract).
`RefillOrder` (+`RefillItem`) is the standalone **on-demand extinguisher refilling** channel (also no
contract needed) — `reference` `RF-00001`, `summary`/`total_units` helpers, surfaced in the customer
portal and the Ops Console. `FormAttachment` holds photos and documents uploaded at form-submission
time (ref_type: `contract` / `service_request` / `refill_order`; attachment_type: `photo` / `document`).
`Contract.voice_note` and `ServiceRequest.voice_note` store speech-to-text transcripts from the apply
and NOC forms. `ServiceRequest.noc_document_path` holds the uploaded old NOC for renewals.
Several models expose computed helpers used directly in templates — e.g. `Contract.reference`
(`AMC-00001`), `Contract.completed_visits`/`next_visit`, `Equipment.refill_status`
(`ok`/`due_soon`/`overdue`) and `days_to_refill`, `Quotation.total`. After changing an equipment's
refill dates, call `recompute_next_refill()` so the derived `next_refill_date` stays correct.

**AI** (`nse/ai.py`): the assistant is named **Tara** ("star" in Sanskrit — fits the North Star brand and the "Enlightening Safety" tagline). `ask(messages)` prepends a system prompt with company + AMC + **refilling** + NOC +
emergency facts (sourced from the brochure, the Maintenance SOP, and northernstarengineering.com) and
calls OpenRouter. The prompt enforces a **tidy reply format**: one-line answer, then 2-5 short `- `
bullets, `**bold**` figures, <~90 words. The chat widget (`_chat_widget.html`) renders that small
markdown subset (`**bold**`, `-`/`•` bullets, line breaks) via a safe in-JS `renderMd()` (HTML-escaped
first). If `OPENROUTER_API_KEY` is unset or starts with `PLACEHOLDER`, or the call fails, it returns a
canned fallback reply rather than erroring — the chat never hard-fails. Model is `OPENROUTER_MODEL`
(default `anthropic/claude-haiku-4.5`). Note: OpenRouter slugs are current-gen — the older
`anthropic/claude-3.5-sonnet` 404s with "No endpoints found"; verify a slug exists via
`GET https://openrouter.ai/api/v1/models` before setting it.

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
`COMPANY_TAGLINE`, `EMERGENCY_HOTLINE` (toll-free, used in `tel:` links — the top emergency strip was removed; hotline still appears in footer and hero CTA),
`COMPANY_PHONE` (direct line), `COMPANY_EMAIL`, `COMPANY_ADDRESS`. To change any of these, edit `.env`
(not the templates). When adding a new branding field, add it in three places: `config.py`, the
`inject_globals` context processor, and `.env`/`.env.example`.

**Branding assets:** the logo is the company's **official artwork**. `nse/static/img/logo-full.png` is
the full stacked logo (navy-circle + white-star + orbit emblem *above* the "NORTHERN STAR ENGINEERING"
wordmark). `nse/static/img/logo-emblem.png` is the round emblem cropped out of it with a **transparent
background** (outer white flood-filled away via Pillow, while the white star *inside* the circle is
preserved) — this is what renders in the nav, footer, chat-widget header, and favicon (via
`url_for('static', ...)`), because those sit on the dark canvas and a white-box PNG would look wrong.
The earlier hand-built `logo-emblem.svg` recreation is kept in the folder but no longer referenced. If a
new official logo is dropped in, re-crop the emblem the same way (Pillow isn't a runtime dep — it was
pip-installed into `.venv` just for this). Company facts/stats on the home page and in the AI prompt are
sourced from the live site northernstarengineering.com.

## Styling / theme

The app uses a **light theme by default** — **navy brand + warm off-white canvas + amber CTAs**, with **red reserved for emergency/danger only**. Design language inspired by the "Premise — Maintenance Made Transparent" Behance reference: warm backgrounds, amber/orange primary actions, service category tiles, status timelines, and priority-border cards. Users can switch to **dark mode** via a floating pill (bottom-left) or the moon icon in the nav; preference persisted in `localStorage` (`nse-theme`). Anti-FOUC script before Tailwind CDN.

**Nav tagline**: "Enlightening Safety" (not the old "Maintenance · Refilling · Emergency" — changed on request). **No top emergency strip** — removed; the hotline still appears in the footer and in hero CTAs.

**Hero** (`home.html`): Full-viewport split two-column layout. Left: amber badge pill "India's First Fire Safety Platform" + headline **"Fire Safety, reinvented."** (amber accent on "reinvented.") + subtitle "India's first digital platform..." + 3 CTAs (amber/outline/emergency-pulse) + **animated stat counters** (600+, 700+, 7+, NBC·BIS·IS·NFPA counting up via JS IntersectionObserver). Right (desktop only): upgraded SaaS-style glass dashboard with 8 widgets: header bar (NSE Platform · LIVE), KPI strip (AMC Status/Compliance 98%/Emergency Online), contract block with animated compliance ring SVG + visit progress bar, Upcoming Inspection, QR Asset Tracking, Fire Extinguishers, Last Inspection Report, Service Requests. Two floating mini-badges (Team Dispatched, Refill Booked). **Video background** (`<video id="heroBgVid">`): loads `nse/static/video/hero.mp4` (autoplay, muted, loop, playsinline). File is **not committed** — drop a free stock MP4 (e.g. Mixkit "Aerial view glass corporate buildings at night" ID 49845, downloaded manually from mixkit.co) into `nse/static/video/hero.mp4`. On `canplaythrough`, JS fades it in to 42% opacity (2s transition) and deepens the gradient overlay; if the file is absent nothing breaks — canvas stays as background. **Canvas background** (`#heroCanvas`, z-index 0 behind video): 56-particle network with connection lines + amber radar sweep + 12-second cinematic phase cycle (calm → alert red pulse → resolve green pulse). Canvas dims to 35% opacity once video is playing (stays as particle overlay on top of footage). **Floating live notifications** (`#h-notifs`, bottom-left, desktop only): 6 notification types cycling every 3.5s with slide-in/fade-out CSS transitions. **Entrance animation**: 6 elements stagger in with `.ha.in` CSS transition class added by JS (260ms → 960ms delays). **`{% block scripts %}`** at bottom of file contains 5 JS functions (video handler, canvas, entrance, notifications, counters). Inline `<style>` block in hero section holds all hero-specific CSS classes (`.ha`, `.hb-*`, `.h-dash-*`, `.ldot`, `.cring`, etc.) to avoid polluting base.html. IMPORTANT: CSS IDs like `{#h-notifs}` in `<style>` blocks trigger Jinja comment errors — always add a space: `{ #h-notifs { ... } }`.

All theming lives in **`base.html`**:
1. **`darkMode: 'class'`** in Tailwind CDN config — `dark:` variants work when `dark` class is on `<html>`.
2. **CSS custom properties** (`:root` + `html.dark`) drive all semantic tokens. Components reference vars and auto-flip in dark mode.
3. The Tailwind CDN config defines the palette:
   - **Semantic tokens**: `bg-canvas` (`#faf8f5` warm off-white), `bg-surface-1..4` (warm gray scale), `text-ink`/`ink-muted`/`ink-subtle`/`ink-tertiary`, `hairline`/`hairline-strong`.
   - **Amber accent**: `amber` family (`DEFAULT:#f59e0b`, `hover:#d97706`, `light:#fef3c7`, `dark:#92400e`) — also available as CSS vars `--amber`, `--amber-h`, `--amber-lt`.
   - **Brand**: `bg-primary` (#16235b navy) stays for nav/hero/footer; `text-primary` = navy.
   - **Brand families**: `navy` (50→900). `star` remapped to navy.
4. **Dark mode global overrides** patch common Tailwind utilities via `html.dark .class { !important }`.
5. **Component layer** (prefer over ad-hoc utilities):
   - Buttons: `.btn` + `.btn-primary` (**amber** `#f59e0b`, dark text — changed from navy), `.btn-white`, `.btn-outline` (hero), `.btn-ghost`, `.btn-emergency` (red).
   - Surfaces: `.card`, `.card-hover`, `.eyebrow` (uppercase accent kicker).
   - Hero: `.hero-bg` (navy radial gradient) + `.hero-grid`.
   - Icons/badges: `.icon-chip` / `.icon-chip-soft`, `.num-badge`, `.star-badge`.
   - **Service tiles**: `.service-tile` + `.service-tile-icon` — icon-grid cards (used on home page "What can we help you with?" section). Hover turns border amber and icon bg to amber-light.
   - **Status track**: `.status-track` + `.status-track-step` + `.status-track-dot` (`done`/`active` modifiers) + `.status-track-line` (`done` modifier) — horizontal progress timeline (used on portal contract cards: Applied → Active → Completed).
   - **Filter chips**: `.filter-chip` + `.filter-chip.active` — pill-shaped filter tags (used on ops console dashboard). Active state = amber border + amber-light bg.
   - **Priority cards**: `.priority-card` + `.p-high` (red left border) / `.p-medium` (amber) / `.p-low` (green) / `.p-info` (blue) — request/contract list cards with colored left border indicator.
   - **Form question**: `.form-question` + `.form-question-sub` — large bold heading style for form sections ("What's the issue?").
   - Theme: `.theme-pill`. Animations: `.fade-up` + `.stagger`.

**Dark mode token values**: canvas `#0d1117`, s1 `#161c2d`, s2 `#1c2338`, ink `#dde6f8`. `.btn-primary` is amber in both modes (dark bg = `#d97706`).

**Nav background**: `.nse-nav` = `rgba(250,248,245,0.94)` light / `rgba(13,17,23,0.94)` dark.

**Chat widget** (`_chat_widget.html`): The chatbot is named **Tara** (renamed from Dhruv). Toggle button = navy circle with a gold 4-pointed star SVG + amber notification dot. Panel header = navy gradient with Tara's star avatar + green online dot. Bubble panels use inline `style="background:var(--s1);border:1px solid var(--hair)"` so they auto-flip in dark mode without Tailwind. Input placeholder: "Ask Tara anything…". `ai.py` system prompt and all template references updated to Tara.

**Key separation**: `.btn-primary` (component class) = amber action buttons. `bg-primary` (Tailwind utility) = navy, used for nav/portal links and stays navy. Never mix them.

Consequences: a color utility renders in its natural light Tailwind value unless there's a global dark override. Keep light text (`text-white`) only on dark surfaces. `home.html` / `plans.html` are the richest reference; `_macros.html` keeps `status_badge`/`refill_badge`/`field()`.

**Voice input** (`base.html` global JS + `_macros.html` `voice_note_widget` macro): uses the browser's
built-in **Web Speech API** (`SpeechRecognition` / `webkitSpeechRecognition`). No server-side component
or paid API — transcription runs entirely in the browser, result stored in a `<input type="hidden">` and
posted as plain text. `rec.lang = 'en-IN'` for Indian-accent optimisation. Falls back gracefully (shows
unsupported message) on browsers without speech support. The macro is in `_macros.html`; import it with
`{% from "_macros.html" import voice_note_widget %}`. The `photo_upload_widget` macro similarly renders a
drag-and-drop photo input with thumbnail previews; the global JS in `base.html` handles the preview.

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

A second hook, **`PostToolUse` → `.claude/hooks/compact_on_claudemd.py`** (matcher
`Edit|Write|MultiEdit|NotebookEdit`), fires after every edit and, **only when the edited file is
`CLAUDE.md`**, prints a `{"systemMessage": ...}` reminder to run `/compact` (folding the freshly
updated project state into a compacted context); it stays silent for all other files. Note: hooks
**cannot** invoke `/compact` themselves — no hook event or output field starts a compaction (`PreCompact`
only runs *during* one already in progress), so this hook only surfaces the reminder; the user runs
`/compact`. Same stdlib-`python3` / next-session-activation rules as the Stop hook.

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

## Wave 1 features (added post-launch)

**Service Quotations** (`nse/blueprints/sq.py`, blueprint `sq`, prefix `/ops/sq/`): sales proposals for any service type (AMC/NOC/Refilling/Emergency). Status flow: `draft → sent → viewed → negotiation_requested → accepted / rejected`. Model: `ServiceQuotation` + `ServiceQuotationItem`. PDF generated via xhtml2pdf from `nse/templates/pdf/quotation.html` (matches NSE's real QUO format exactly — GST 24ALQPD0899P1ZD, 19 T&C clauses). Staff creates manually in Ops Console; **AMC apply auto-creates one** (see `public.py` above). Customer views/accepts/negotiates in portal (`/portal/service-quotation/<id>`). The portal dashboard `pending_quotes` banner queries `ServiceQuotation` by both `customer_id` and `customer_phone` (via `sqlalchemy.or_`) so quotes created before the customer's account existed are still surfaced after login.

**Email automation** (`nse/email_service.py` + Flask-Mail): Outlook SMTP (`smtp.office365.com:587`). Config in `config.py` (`MAIL_*`). Set `MAIL_PASSWORD` in `.env` to enable actual sending; `MAIL_SUPPRESS_SEND=true` (default) logs to console only. Templates in `nse/templates/email/` (7 templates). Triggers: quote sent, accepted, negotiation, visit scheduled, visit reminder, feedback request, payment confirmation.

**Post-visit feedback** (`/feedback/<token>`, public — no login): After visit marked completed in Ops Console, `_trigger_feedback()` creates a `VisitFeedback` stub with a unique token and sends the customer a feedback email link. Form captures 5 dimensions (behaviour, quality, punctuality, communication, overall) each rated 1–5. Token stored on `VisitFeedback.token`.

**Technician performance dashboard** (`/ops/technician-performance`): aggregates `VisitFeedback` ratings + on-time completion rate (completed_date ≤ scheduled_date) per technician. Rankings: top 3 shown as leaderboard cards; full table below.

**Customer journey timeline** (`CustomerJourneyEvent` model, `/portal/journey`): audit log of all key events per customer (quote sent, accepted, contract activated, visit scheduled/completed, payment received, feedback given). Written at each trigger point across blueprints.

**New models** (in `nse/models.py`): `ServiceQuotation`, `ServiceQuotationItem`, `VisitFeedback`, `CustomerJourneyEvent`. All new tables added via `db.create_all()` — no migration needed for fresh installs; existing installs must `rm nse_amc.db && seed.py`.

**New dependencies** (in `requirements.txt`): `flask-mail==0.10.0`, `xhtml2pdf==0.2.17`, `reportlab==4.5.1`. Flask-Mail registered on `mail` in `nse/extensions.py`.

## Wave 2 features (added post-Wave 1)

**Visit maintenance checklist** (`VisitChecklistItem` model, `nse/models.py`): new table (safe to add via `db.create_all()` — no DB reset needed). Stores line items per visit with `item` name, `status` (ok/issue/na), `note`, `sort_order`. `Visit.checklist_summary` property returns `{total, ok, issues}`. The admin visit form (`admin/visit.html`) has a dynamic checklist section: 12 standard fire safety items (smoke detectors, hydrant, extinguishers, alarm panel, etc.) as quick-add pills, plus free-add rows. Checklist rows are serialised to JSON and posted as `checklist_items_json`, deserialized server-side in `admin.visit`. Customer portal shows checklist summary per visit in the equipment detail page.

**Equipment detail portal page** (`/portal/equipment/<id>`, `portal.equipment_detail`): shows equipment header (name, type, location, S/N), key dates (installed, last refill, next due, interval), status alerts (overdue/due-soon banners), full refill history, and completed service visits with checklist summaries. Equipment names in the portal contract page now link to this page.

**QR code mobile page** (`/qr`, `public.qr`): auto-detects local network IP via socket, renders a QR code using `qrcodejs` CDN (no install needed). Scan to open app on any phone on the same WiFi. Template: `public/qr.html`.

## Wave 3 features (added post-Wave 2)

**Admin visit calendar** (`/ops/calendar`, `admin.calendar`): monthly calendar grid view of all visits. Navigation arrows (prev/next month). Visits colour-coded by status (blue=scheduled, amber=in_progress, green=completed, grey=cancelled). Click any visit to go to its detail page. List view below the calendar shows all visits for the month. Links added to ops dashboard nav.

**Analytics dashboard** (`/ops/analytics`, `admin.analytics`): KPI cards (active contracts, total customers, visit completion rate, total contract value, open emergencies, overdue equipment, open refills). Bar chart of new contracts per month (last 6 months, pure CSS — no chart library). Quick links to calendar, technician performance, contracts. Links added to ops dashboard nav.

**New model**: `VisitChecklistItem` (Wave 2, in `nse/models.py`). Added to `Visit.checklist_items` relationship and imported in `admin.py`.

## Wave 4 features (quotation ↔ contract interlink + staff notifications)

The AMC apply flow already auto-creates a `ServiceQuotation` (status `sent`) linked to the new
pending `Contract` via `ServiceQuotation.contract_id`. Wave 4 makes that link **govern activation** so
staff cannot activate a contract — or change its price — until the client has accepted the quote.

**Contract↔quote helpers** (`Contract` in `nse/models.py`): a `service_quotations` backref relationship
(`foreign_keys="ServiceQuotation.contract_id"`) plus three properties — `amc_quote` (most recent linked
AMC quote, or None), `can_activate` (True only when there is no AMC quote **or** its status is
`accepted`), and `quote_locked_price` (the accepted quote's pre-GST **subtotal** as an int, else None).
`ServiceQuotation.is_editable` was broadened to `draft` **or** `negotiation_requested` so staff can
revise a quote a client is haggling over.

**Activation gating** (`admin.activate_contract`): rejects the POST with a flash when
`not c.can_activate` (contract stays `pending`); when activating, the price is taken from
`c.quote_locked_price` if present (the form's `price` field is ignored — the figure was fixed in the
quote). The contract template (`admin/contract.html`) reflects this: a colour-coded quote-status banner
with a "Review quotation →" link, then either the activation form (price input **read-only** and pulled
from the quote when locked, otherwise editable for quote-less custom contracts) or a "🔒 Activation
locked" panel when the client hasn't accepted.

**Revise & re-send** (`sq.detail_quotation`, new `revise_send` action): on a `negotiation_requested`
quote the staff `admin/sq_detail.html` page shows editable per-line-item rate inputs; saving updates the
rates, clears `negotiation_note`, sets status back to `sent`, re-emails + notifies the customer, and
logs a journey event. The client then re-accepts, which locks the new price.

**Staff notifications** (`notify_staff(title, body)` in `utils.py`): fans a `Notification` row out to
every admin+technician. Called from `portal.service_quotation_accept` / `_negotiate` so quote responses
surface in the Ops Console. Reuses the existing `Notification` model and the `unread_notifications`
count. A **notification bell** (native `<details>` popup, no JS) lives in the `base.html` nav for all
authenticated users, listing `recent_notifications` (last 8, injected by `inject_globals`) with an
unread badge and a "Mark all read" link (reuses `portal.mark_read`, which is `@login_required` only so
staff can call it). A full **`/ops/notifications`** page (`admin.notifications`, template
`admin/notifications.html`) lists the last 100. The Ops dashboard nav gained a 🔔 Notifications link and
a **Quotations badge** driven by `sq_action_count` (quotes in `negotiation_requested`, or `accepted`
**whose contract is not yet active** — once activated they need nothing more; injected globally for
staff), plus a "⚡ Quotations needing your action" panel (`sq_attention`, same filter, from the
dashboard route) and an awaiting-approval marker on each pending application card.

Note: dynamic Tailwind classes like `bg-{{ qcolor }}-50` work here because the app uses the **Tailwind
Play CDN** (runtime DOM scan), not a build-time purge — the fully-rendered class string is in the HTML.

## Wave 5 features (clickable notifications, PDF fix, on-site updates, rescheduling)

**Clickable notifications.** `Notification` gained a `link` column (where clicking navigates).
`notify(user_id, title, body, link=None)` and `notify_staff(title, body, link=None)` accept it; every
call site now passes a deep link (quote → portal/ops quote page, activation → portal contract, visit
completed/rescheduled → portal pages, etc.). The `base.html` bell renders each item as an `<a>` and the
"View all →" footer points to `admin.notifications` for staff or **`portal.notifications`** (new page,
`portal/notifications.html`) for customers. **Existing DBs need the column** —
`ALTER TABLE notifications ADD COLUMN link VARCHAR(255)` (fresh installs get it from `db.create_all`).
`inject_globals` now guards `current_user` being None so `render_template` works outside a request
(e.g. PDF generation in a job).

**Updates section moved.** The inline "Updates" list was removed from `portal/dashboard.html`; customer
notifications live only under the 🔔 bell (popup + `portal.notifications` page).

**Conditional portal buttons.** `portal.dashboard` passes `has_refills` / `has_emergencies`; the
dashboard hides the **Book refill** / **Emergency** quick-action buttons unless the customer has used
that service.

**Quotation PDF fixes.** (1) The portal "Download PDF" button hit the staff-only `/ops/sq/<id>/pdf`
(→ 403); customers now use **`portal.service_quotation_pdf`** (`/portal/service-quotation/<id>/pdf`,
ownership-checked). (2) The logo didn't embed because xhtml2pdf can't fetch `file://` URLs —
`pdf_generator._link_callback` now resolves `/static/...` URIs to real disk paths and is passed to
`pisa.CreatePDF(link_callback=...)`; the template logo `src` is `/static/img/logo-full.png`.

**Activation price is GST-inclusive.** `Contract.quote_locked_price` now returns the accepted quote's
**grand_total** (was subtotal), so the locked activation price includes GST. The contract template label
reads "🔒 locked, incl. GST" and shows the subtotal + GST% breakdown.

**Tara chatbot icon** redrawn as a friendly robot face (antenna + screen + eyes + smile) in
`_chat_widget.html` (toggle button + header avatar), replacing the 4-point star.

**Technician on-site updates** (`admin/visit.html`): the visit page now has a **payment status** form
(posts to `admin.contract_payment`, which redirects back via `request.referrer`) and a **material
quotations** card (lists `contract.quotations` + "Raise quotation" link to `admin.new_quotation`). All
`@staff_required`, so the assigned technician can update payment and raise quotes on site.

**Visit scheduling & rescheduling.** Activation logs a `contract_activated` journey event and sends the
client an "AMC activated — schedule confirmed" notification (with first-visit date + portal link). Each
visit row on `admin/contract.html` has an inline **date picker** that posts to
**`admin.reschedule_visit`**; the shared helper `_apply_reschedule(v, new_date)` (also used by
`admin.visit`) sets the date, writes a `visit_rescheduled` `CustomerJourneyEvent`, and notifies the
client. So date changes from either the visit page or the contract page are journaled + surfaced to the
customer.

## Wave 6 features (visit quotes from inventory, waiver, FSHCR, mandatory ratings, financials, roadmap, chime)

**New models** (`nse/models.py`): `InventoryItem` (spare-parts catalogue the technician picks from —
name/category/unit/rate/active; seeded in `seed.py` and inserted into existing DBs) and
`HealthCheckReport` (FSHCR). Existing-DB migration adds columns: `quotations.payment_status` /
`payment_date` / `rejection_acknowledged` / `waiver_text`; `visits.customer_approved` / `approved_at`;
`contracts.payment_date`. Fresh installs get these from `db.create_all`; existing DBs need the
`ALTER TABLE`s (run the one-off migration snippet — it's idempotent via `PRAGMA table_info`).

**Visit-linked material quotes** (`Quotation` now has a `visit` backref + `is_paid`). Technician raises
one on the visit page (`admin/visit.html`) from an **inventory picker** (datalist auto-fills the rate;
JS `invFill`/`qcalc`/`addQRow`) → `admin.visit_quotation` builds the `Quotation` (visit_id + contract_id)
and notifies the client. Client approves/declines in `portal/quotation.html`. **Declining requires a
liability waiver** — a modal shows `utils.WAIVER_TEXT`; on confirm (`waiver_accepted=1`)
`portal.quotation_decide` sets `rejection_acknowledged` + stores `waiver_text`, and the next visit
proceeds. Payment per quote is updated by the technician via `admin.quotation_payment`.

**Fire System Health Checkup Report (FSHCR)** mirrors NSE's printed form. Structure lives as constants
on `HealthCheckReport` (`SECTIONS`, `HYDRANT_ITEMS`, `FLOOR_COLUMNS`/`FLOOR_NAMES`, `PARTICULARS`,
`EXTRAS`); all answers serialise to the `data` JSON column (`answers`/`set_answers`). Form
`admin/health_report_form.html` (note: `{% set answers %}` is at **template top level**, not inside a
block, so the scripts block can read it). Floor table is a dynamic JS grid serialised to
`floors_json`. **Scan-and-upload fallback** (`scan_path`) for when the app can't be used on site. Routes:
`admin.health_reports` (list), `admin.health_report` (new/edit, one view, GET+POST), `admin.health_report_pdf`.
Can be **standalone** (non-AMC survey, no contract) or linked to a contract/visit; when `status=completed`
and linked, the client is notified and can download via `portal.health_report_pdf` (shown on
`portal/contract.html`). PDF: `pdf/health_report.html` via `generate_health_report_pdf`.

**Visit completion → branded report + mandatory rating.** On completed, the client gets a 🎉
congratulations notification. `portal/visit.html` shows a congrats banner, a **branded service-report
PDF** (`pdf/service_report.html` via `generate_service_report_pdf` / `portal.service_report_pdf` — header,
checklist, work done, photos), and an **Approve & rate** popup. Rating is compulsory (JS star widget
`nseStar` + `star_rating_inputs` macro, 5 dimensions) → `portal.visit_approve` writes `VisitFeedback`,
sets `Visit.customer_approved`, and notifies the technician + ops console. `generate_service_report_pdf`
and `generate_health_report_pdf` share `_company_ctx()` in `pdf_generator.py`.

**Financial dashboard + roadmap.** `admin.financials` (`/ops/financials`, template `admin/financials.html`)
is contract-wise: the AMC fee (paid y/n + date) plus every approved visit-linked quote (paid y/n + date),
with billed/received/outstanding KPIs. `admin.contract_payment` now stamps `payment_date` + logs a
`payment_received` journey event. **Workflow roadmap** macro `workflow_track` (`_macros.html`, driven by
`Contract.workflow_steps`: Quote → Contract → Visit 1…N, filling as steps complete) shown on
`portal/contract.html`.

**Chime.** Web-Audio two-note chime (`nseChime` in `base.html`, no asset file) fires when a flash uses a
`*_chime` category — the flash block strips the suffix for colour and drops a `[data-nse-chime]` marker
that the bottom-of-`base.html` script detects on load. Used on **client quote/material-quote acceptance**
and **ops contract activation** (`success_chime`). New Ops nav links: 💰 Financials, 🩺 Health Reports.

The quotation PDF (`pdf/quotation.html`) already matches NSE's real QUO format (Wave 1) — left unchanged.

## Post-Wave-6 bug-fixes (patch round)

**Waiver text.** `WAIVER_TEXT` in `utils.py` updated to exact client-approved wording: *"I do not wish to replace the mentioned spare parts/equipments/tools as mentioned by the company and hereby, I take full responsibility if any fire incident happens after this AMC visit, and Northern Star Engineering is not responsible."*

**Future-visit lock.** The admin visit page (`admin/visit.html`) now checks `is_future` (passed from `admin.visit` GET as `v.scheduled_date > date.today()`). When true: the main edit form, material-quotation picker, and checklist are hidden and replaced with a lock banner; only the scheduled-date reschedule and technician assignment remain editable. Prevents any backdating or pre-filling before the visit day arrives.

**Material-quotation PDF.** `Quotation` and `QuotationItem` gained PDF-compatible properties (`items_by_category`, `customer_name/phone/email/address`, `project_name`, `valid_days=30`, `gst_percent=18`, `subtotal`, `gst_amount`, `grand_total`; item aliases `rate`, `unit`, `total`) so the shared `pdf/quotation.html` template renders both `ServiceQuotation` and visit-linked `Quotation` without branching. `generate_material_quotation_pdf(q)` added to `pdf_generator.py`; `portal.quotation_pdf` (`/portal/quotation/<id>/pdf`) serves the client-side download (ownership-checked). A **Download PDF** button appears in `portal/quotation.html`. Also removed `letter-spacing: .03em/.04em` from `pdf/quotation.html` (xhtml2pdf rejects em units).

**Inventory from CSV.** `import_inventory.py` (project root) reads `~/Downloads/Invetory List.csv` and bulk-replaces all `InventoryItem` rows. Run: `.venv/bin/python import_inventory.py`. Imports 1,273 real NSE product codes (Code → hsn, Name → name, Group → category, Unit → unit, Amount → rate). The visit-linked quote picker and the **Service Quotation new form** (`sq_new.html` + `sq.new_quotation`) both now use this inventory via datalist + JS auto-fill (`sqFill`/`invFill` respectively).

**Notification deep links + congratulations chime.** Visit-completion `notify()` call now appends `?chime=1` to the portal visit URL. `base.html` JS extended: `DOMContentLoaded` plays `nseChime()` when `URLSearchParams.get('chime') === '1'` (in addition to the existing flash-based trigger). So clicking the 🎉 congratulations bell notification navigates to the visit page **and** plays the chime automatically.

## Known dev-grade pieces (not yet production)

OTP is a dev flow (code shown on screen, not SMS). Payments record cash/online **intent** only — no
gateway. DB is SQLite (swap to Postgres via `DATABASE_URL`). These are deliberate; harden on request.
