# V.A.U.L.T — Survival Inventory Manager

> **V.A.U.L.T**: Verified Assets, Usage, Lots and Tracking.

## What this is

Self-hosted web app to track food, water, supplies, medications, ammunition and
preparedness gear. It runs fully offline on a LAN. It is **not tied to any machine**:
run it on a laptop, a server or a Raspberry Pi. Nothing deploys itself to the Pi; the
Pi is the *lightest* machine it must still be able to run on when needed
(target: Pi Zero 2 W; the original Pi Zero should work, just slower).

The data is sensitive (medications, ammunition). **Never expose the app directly
to the internet.** If remote access is needed, use a VPN (e.g. WireGuard).

## Priorities (in this order)

1. **Light**: minimal RAM/CPU, so it also fits a Pi. Only two long-running processes: the app and PostgreSQL.
2. **Functional**: fast stock in/out, expiry visibility, low-stock alerts.
3. **Offline-first**: no internet needed at runtime (no CDNs, no external APIs).
4. **Maintainable**: few dependencies, obvious code, real tests.

## Stack

| Concern            | Choice                                                         |
|--------------------|----------------------------------------------------------------|
| Language           | Python (`requires-python` in `pyproject.toml`; see Deploy for the Pi) |
| Web framework      | Django (latest LTS), server-rendered templates + HTMX          |
| CSS                | Tailwind v4 standalone CLI (no Node); built CSS is committed; `stone-*` is re-tinted green in `tailwind/input.css`; charts are plain CSS |
| Auth               | Django auth; whole site login-required (`LoginRequiredMiddleware`) |
| Database           | PostgreSQL, psycopg 3 (sync; no async needed here)             |
| App server         | gunicorn (1 worker, 2 threads) + WhiteNoise for static files   |
| Settings           | django-environ (`.env` + real env vars; env vars win)          |
| Dependency manager | Poetry 2.x (`package-mode = false`)                            |
| Task runner        | poethepoet as a Poetry plugin (`poetry <task>`)                |
| Lint + format      | Ruff                                                           |
| Tests              | pytest, pytest-django, pytest-cov, pytest-random-order         |
| Test data          | factory-boy, Faker (dev only), freezegun                       |
| Test database      | Testcontainers (real PostgreSQL)                               |

Tooling (Ruff, poe, pytest setup, EditorConfig, Dependabot, CI, commit
style) is deliberately copied from `github.com/buguno/fastapi-template`. Keep it
consistent with that template unless there is a Django-specific reason.

Dev-only dependencies live in the Poetry `dev` group and are not needed to run the app anywhere.

## Runtime budget (so it still runs on a Raspberry Pi)

- No Redis, Celery, Docker or Node needed to run it, and no scheduler: nothing runs periodically. Anything time-based
  (expiry, low stock, kit status) is derived from the data when a page is rendered.
- PostgreSQL is tuned for ~512 MB RAM. Starting point for `postgresql.conf`
  (adjust with measurements, keep `fsync` on):
  `max_connections = 20`, `shared_buffers = 32MB`, `work_mem = 2MB`,
  `maintenance_work_mem = 16MB`, `effective_cache_size = 128MB`.
- Django: `CONN_MAX_AGE = 60`, no connection pooler, `DEBUG = False` in production.
- Avoid heavy dependencies (pandas, numpy, DRF, Celery, etc.) without discussing first.
  When suggesting a new dependency, state its RAM cost and whether wheels exist for ARM.
- Paginate every list view, use `select_related`/`prefetch_related`, watch for N+1.
- Use a decent SD card or SSD; avoid chatty writes (no per-request logging to disk).

## Project structure

```
.
├── .github/
│   ├── dependabot.yml           # weekly pip updates (America/Sao_Paulo)
│   └── workflows/               # pipeline.yaml (lint + tests + CSS freshness), docker.yaml (image to ghcr.io on v* tags)
├── config/                      # settings.py, urls.py, wsgi.py
├── apps/
│   ├── core/                    # app-agnostic base: TimestampedModel, DomainError, error middleware,
│   │                            #   login/logout, settings page + UserProfile (theme, language, read_only),
│   │                            #   HTMX helper, form mixin, nav template tag
│   ├── inventory/               # Item, Category, Location, Batch, StockMovement, dashboard, shopping list, stock count,
│   │                            #   CSV import (imports.py), insights (insights.py)
│   ├── medications/             # one-to-one extension of Item (Medication)
│   ├── ammunition/              # one-to-one extension of Item (Ammunition) + AmmunitionUsage log
│   ├── kits/                    # Kit (bound to a Location) + KitItem checklist, status vs. stock
│   └── autonomy/                # Household (single row) + food/water autonomy calculator
│       └── <each app>: models.py, services.py, views.py, forms.py, urls.py, exceptions.py
├── templates/                   # base.html, partials/ (shared), error.html, per-app folders
├── static/
│   ├── css/tailwind.css         # built, committed
│   └── js/                      # htmx.min.js, app.js, theme.js (all vendored)
├── tailwind/input.css           # Tailwind source (components live here); outside static/ on purpose
│                                #   so collectstatic does not try to post-process it
├── gunicorn.conf.py             # production server settings (`poetry prod`)
├── Dockerfile, docker-entrypoint.sh, .dockerignore   # container image (gunicorn; optional RUN_MIGRATIONS=1)
├── locale/pt_BR/                # django.po + compiled django.mo (both committed)
├── tests/                       # mirrors apps/; __init__.py in every directory
├── bin/                         # Tailwind standalone binary (gitignored, dev only)
├── compose.yaml                 # dev-only PostgreSQL (use your own PostgreSQL to run the app for real)
├── manage.py
├── pyproject.toml
├── .editorconfig
└── .env.example
```

## Architecture

Dependency direction is one-way: `views → services → models`. Nothing imports upward.
Apps depend on `core`, never the other way around. Domain apps may depend on `inventory`.

- **Views**: thin. Validate with forms, call a service, render or redirect. No business rules.
- **Services** (`services.py`): plain functions holding business rules. They take plain
  arguments, return model instances and raise domain exceptions. **They never import
  from `django.http` or touch `request`**, so they are testable without the test client.
- **Domain exceptions**: HTTP-agnostic `DomainError` subclasses (see `exceptions.py`).
  A single middleware (`process_exception`) maps them to status codes and renders an
  HTMX-friendly error partial. Views have no `try/except` for business errors.
  `core` knows nothing about other apps: each app registers its errors in its `registry.py`
  with `register_error_status(Error, HTTPStatus.X)`. Unregistered errors become 400.
- **Models**: persistence and DB constraints only (`CheckConstraint`, unique constraints).
- Whenever a new model is added, make sure its app is in `INSTALLED_APPS` and that a migration is created and reviewed.

## Domain rules

- **Item**: what exists (e.g. "Rice 1kg", "Dipyrone 500mg", "9mm FMJ 124gr").
- **Batch**: a physical lot with quantity, expiry date and Location. Stock = sum of batches.
- **StockMovement**: every entry, exit and adjustment. It is the audit trail.
- A batch quantity changes **only** through an `inventory.services` function that creates the
  `StockMovement` inside `transaction.atomic()` using `select_for_update()`. Never edit quantity directly.
- DB-level `CheckConstraint`: quantity >= 0.
- Quantities are `Decimal` with an explicit unit. Never `float`.
- Consumption follows **FEFO** (first expired, first out): soonest `expires_at` first (no expiry last), then the
  oldest `packaged_at` (or `produced_at` when bought already packed), then `id`. So with equal expiry, or none at
  all, the oldest-packaged batch always goes first, but a real earlier expiry still wins over an older packaging.
- Taking stock out (`inventory.services.remove_stock`) is automatic FEFO across all locations **except reserved ones**
  by default; the Remove form has an optional "Take from" location (only locations that hold the item, with their
  totals) that limits FEFO to that location and may be a reserved one. Apps reserve locations with
  `inventory.extensions.register_reserved_locations(source)` in its `registry.py`; `kits` reserves every kit's
  location, so an automatic exit never empties a go-bag. When the automatic exit falls short only because the rest is
  in kits, the error says how much. `suggest_batch` and the item page's "Use first" card follow the same rule.
- Batches carry optional `produced_at` (manufactured) and `packaged_at` (packed by you, e.g. vacuum-sealed grains
  that last 20 years). They are part of a batch's identity: `add_stock` only merges into a batch with the same item,
  location, expiry, both dates and lot code. Order is enforced by CheckConstraints and `validate_dates` (no future
  dates, manufacture <= packaging <= expiry).
- `Item.shelf_life_months` (e.g. 240) suggests the expiry: when an entry has no expiry, it is packaging (or
  manufacture) date + shelf life. A typed expiry always wins. It is a suggestion, not a guarantee.
- `Batch.unit_cost` (optional, per unit, 4 decimals, >= 0) is the price paid. `add_stock(unit_cost=...)` blends it into
  the batch as a weighted average (an entry without cost never lowers the known one) and `transfer_stock` carries it
  to the destination. It is not part of the batch identity. One currency, `CURRENCY_SYMBOL` (default `R$`), shown by
  the `money` template filter.
- `inventory.services.shopping_list()`: items below minimum, amount missing, estimate = missing x last known unit cost.
- `inventory.services.apply_count`/`parse_counts` (stock count page, `count_<batch id>` fields): adjusts only the
  batches whose counted quantity differs, one `ADJUSTMENT` each, in one transaction.
- `inventory.imports.import_stock` (CSV): columns `item, category, location, quantity` (required), `unit` (code),
  `expires_at, packaged_at, produced_at` (ISO or dd/mm/yyyy), `lot_code, unit_cost`; comma or semicolon, UTF-8 or
  Windows-1252. Everything is parsed and checked first (max 10 problems reported, with line numbers), then saved in one
  transaction through `add_stock`. Limits: 2000 rows, 1 MB.
- `inventory.insights` (Insights page, all derived, nothing stored): `consumption_forecast` (exits over the last 90 days,
  or since the item first moved, never under 7 days), `stock_value`, `daily_activity` (12-week heat map),
  `movement_mix`, `busiest_users`, `most_used_items`.
- Alerts are in-app notifications (menu bell + `/notifications/`), derived on every request, never stored: expiring
  or expired batches (window `EXPIRY_WARNING_DAYS`, default 90), items below minimum stock, kits that are incomplete,
  expired or expiring. They clear when the cause is fixed. Apps contribute via
  `apps.core.alerts.register_alert_source(AlertSource(count, alerts))` in its `registry.py`; `core` imports none.
  Cost: a few small queries per page for the menu badge.
- Backup (Settings page, superusers only): export/import of **all** data as one GnuPG-encrypted file
  (`apps/core/backup.py`). Data goes through Django `dumpdata`/`loaddata` (natural keys, so it is database
  independent and works on another machine); encryption is symmetric AES-256 with a passphrase typed each time and
  never stored; requires `gpg` installed (`apt install gnupg`). Restore replaces everything in one transaction, signs
  everyone out, and refuses backups from a different migration state (same version on both sides). The file opens with
  plain `gpg --decrypt`.
- Medications: active ingredient, strength (value + unit, both or neither), form; expiry is on the batches.
- Ammunition: caliber, bullet weight (grains), bullet type, manufacturer. The manufacturer lot is `Batch.lot_code`
  and rounds on hand is the item's stock, so the item must be counted in `un` or `cartridge`.
  Using ammunition (`ammunition.services.record_usage`) removes rounds from a **chosen lot** (not FEFO) through
  `inventory.services.remove_from_batch` and writes an `AmmunitionUsage` (reason: training, match, rotation)
  linked to that `StockMovement`, in one transaction.
- Kits: a `Kit` owns exactly one `Location` (created from the kit's name unless one is chosen) and a checklist of
  `KitItem(item, required_quantity)`. A line is complete when the usable (non-expired) stock **at that location**
  reaches the required quantity; a kit is *ready* when every line is complete and nothing in it is expired.
  Expiring (within `EXPIRY_WARNING_DAYS`) and expired stock is flagged. `kits.services.kit_statuses` does it in 2 queries.
- Autonomy (`autonomy.services.calculate(household=...)` takes an unsaved household for the "what if" simulation, `sim-` form prefix on `/autonomy/`; the dashboard shows rings through `register_dashboard_widget`): food days = usable kcal ÷ (people × kcal/person/day) over items with
  `Item.kcal_per_unit`; water days = usable liters ÷ (people × L/person/day) over items with `Item.is_water`
  (unit `l` or `ml` only). **Expired batches are never counted.** Overall autonomy is the smaller of the two.
  Defaults come from the single-row `Household` (1 person, 2000 kcal, 3 L), editable on the Autonomy page.
- Read-only accounts: `UserProfile.read_only` (set in the admin, inline on the user). `ReadOnlyMiddleware` (after
  `UserPreferencesMiddleware`) sets `request.read_only` and answers any non-safe request with 403 (`ReadOnlyAccount`),
  except `/settings/`, `/settings/password/`, `/logout/`, `/i18n/setlang/`. Superusers are never read-only. The template
  puts `data-readonly` on `<html>`; CSS hides `form[method=post]:not([data-allow])` and `[data-write]`, so new write
  controls that are not POST forms need `data-write`, and POST forms a read-only user may use need `data-allow`.
- Extension apps (`medications`, `ammunition`) plug into the item page without being imported by `inventory`:
  they call `inventory.extensions.register_item_extension()` in its `registry.py` with a `panel` (HTML shown on
  the item page, or None) and an `attach` link ("Add ... details").
- Timestamps are timezone-aware. `TIME_ZONE = 'America/Sao_Paulo'`.
- UI languages: pt-BR (default) and US English (`en-us`). Code, identifiers and docs are English.
  The English text in the source is the msgid, so `en-us` needs no catalog; only `pt_BR` lives in `locale/`.
  Signed-in users: the language and theme saved in their `UserProfile` (Settings page, `/settings/`) always win;
  `UserPreferencesMiddleware` activates them. Anonymous visitors (login page): `LocaleMiddleware` uses the
  `django_language` cookie (login-page selector, `core:set_language`, login-exempt), then `Accept-Language`, then `pt-br`.
  Theme: `<html data-theme>` carries the saved choice (system/light/dark); anonymous visitors use `localStorage`.
- i18n rules: wrap every user-visible string (`gettext_lazy` at import time, `gettext` inside functions,
  `{% trans %}` in templates). Never hardcode a date format: use `SHORT_DATE_FORMAT`/`SHORT_DATETIME_FORMAT`
  or a translatable format string. Unit symbols use `pgettext_lazy('unit symbol', ...)`.
- Workflow for new strings: `poetry messages`, fill the empty `msgstr` in the `.po`, `poetry compilemessages`,
  commit the `.po` and `.mo`. `tests/core/test_i18n.py` fails on untranslated entries, lost `%(placeholders)s`,
  or a stale `.mo`.

## Commands

Tasks are defined in `[tool.poe.tasks]` with `poetry_command = ''`, so they run as native Poetry commands.
Install the plugin once: `pipx inject poetry "poethepoet[poetry_plugin]"` (quotes are mandatory on zsh).

| Command                    | What it does                                                    |
|----------------------------|-----------------------------------------------------------------|
| `poetry install`           | Install all dependencies (dev machine)                          |
| `poetry serve`             | `manage.py runserver 0.0.0.0:8000` (development)                |
| `poetry prod`              | gunicorn with `gunicorn.conf.py` (1 worker, 2 threads)          |
| `poetry collectstatic`     | Gather static files for WhiteNoise (once per release)           |
| `poetry migrate`           | `manage.py migrate`                                             |
| `poetry makemigrations`    | `manage.py makemigrations`                                      |
| `poetry css`               | Build `static/css/tailwind.css` (`bin/tailwindcss`, gitignored) |
| `poetry css-watch`         | Same, rebuilding on change                                      |
| `poetry messages`          | Extract strings into `locale/pt_BR`                              |
| `poetry compilemessages`   | Compile `.po` into `.mo` (commit both)                          |
| `poetry css-check`         | Fail if the committed CSS is stale (also runs in CI)            |
| `poetry lint`              | `ruff check`                                                    |
| `poetry format`            | `ruff check --fix` then `ruff format`                           |
| `poetry test`              | lint, then pytest, then coverage HTML (accepts extra args)      |
| `poetry coverage`          | Rebuild HTML coverage report from the last run                  |
| `poetry backup`            | Dev-only plain `pg_dump` with timestamp (the app has its own)   |

Dev database: `docker compose up -d --wait` (`compose.yaml`, Postgres only). Download the Tailwind
standalone binary for your OS from the tailwindlabs/tailwindcss releases into `bin/tailwindcss`.
Rebuild and commit the CSS whenever template classes change.

To run it (any machine, Pi included): `poetry install --only main`. If Poetry is too heavy there, export
requirements (`poetry-plugin-export`) and install with pip.

## Testing

- Tests run against **real PostgreSQL** via Testcontainers, never SQLite. Use the same
  major PostgreSQL version as the Pi's OS and update the image tag accordingly.
- Docker is required wherever the tests run (dev machine, CI). Do not run the test suite on a Pi.
- A synchronous, session-scoped container fixture overrides `DATABASES` before pytest-django
  creates the test database.
- `DJANGO_SETTINGS_MODULE` is set in `[tool.pytest.ini_options]`.
- Layout: `tests/<app>/test_services.py` for business rules, `tests/<app>/test_views.py` for HTTP behavior.
- Tests run in random order (`--random-order`) and with `--cov-context=test`.
- Use `factory.Factory` with `Sequence` for unique fields (no random collisions); persistence is the fixture's job.
- Never write passwords or passphrases in tests (secret scanners flag them): `tests/fakes.py` generates them with Faker
  (`PASSWORD`, `NEW_PASSWORD`, `PASSPHRASE`), and the `user` fixture gets a fake username.
- Use freezegun for anything involving expiry dates and alert windows.
- Coverage target is 100% (statements + branches), like the template. If that becomes
  impractical for a specific module, ask before lowering it.
- Every new rule gets a test: FEFO selection, stock balance, alert windows, constraint violations.

## Conventions

- **Plug-in hooks** live in each app's `registry.py` (plain top-level imports and `register_*` calls). `CoreConfig.ready`
  runs `autodiscover_modules('registry')`, so no `AppConfig.ready()` needs function-level imports.
- **Imports go at the top of the file**, never inside functions or classes (also in tests). No `# noqa` to dodge a rule:
  fix the cause (a dataclass for many arguments, a constant for a magic number, a typed helper for a form field).
- **Module-level mutable globals** (registries, caches) sit right below the imports.
- **Parameters:** no bare `*` keyword-only markers; group related optional arguments in a frozen dataclass
  (`EntryDetails`, `UsageDetails`). Required form fields are read with `data['x']` (a missing key is a bug that should
  fail loudly), optional ones with `data.get('x', default)`.
- **Type checking** (Pylance/pyright; `django-stubs` is a dev-only dependency, so select the Poetry interpreter): annotation-only declarations on models for query annotations and
  `_id` attributes (`total: Decimal`, `item_id: int`); `class Meta(TimestampedModel.Meta)`; form fields are retyped with
  `core.forms.field_of(form, name, FieldClass)` instead of mutating `form.fields[...]`; no attributes monkey-patched onto
  model instances (use dataclass rows, template filters or `{% widthratio %}`).
- No separator comments like `# --- Section ---`. No `# noqa`: ruff exceptions go in `pyproject.toml` (`PLR2004` is off for
  `tests/**` because tests compare with literal numbers).

- **Ruff**: `line-length = 79`, single quotes, `preview = true`, `extend-exclude = ['migrations']`,
  rules `I, F, E, W, PL, PT, DJ`.
- **EditorConfig**: 4 spaces, 2 for YAML.
- Type hints on service functions.
- Use `HTTPStatus` constants, not raw integers.
- Never edit a migration that was already applied; create a new one. Review every autogenerated migration.
- `.env` is gitignored; `.env.example` is committed. Never commit real credentials.
- Required env vars: `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_HOSTS`; optional: `ENVIRONMENT` (default `development`), `EXPIRY_WARNING_DAYS` (default `90`), `CURRENCY_SYMBOL` (default `R$`).
- **Commits**: Conventional Commits, lowercase, gerund verb, e.g.
  `feat(inventory): adding batch model` / `fix(core): fixing alert window calculation`.
  Use `chore(deps):` / `build(deps):` for dependency changes.

## CI

`.github/workflows/pipeline.yaml` on every push and PR: checkout, Python, Poetry + poe plugin,
`poetry install`, Tailwind freshness check (`poetry css-check`, binary pinned to v4.3.4), `poetry test`. Use plain literal env values for CI (never production
credentials). `DATABASE_URL` only needs to be a syntactically valid URL there, since
Testcontainers provides the real database.

## Running it (any machine; notes for the Raspberry Pi)

- Nothing starts or deploys by itself: you run it by hand on whichever machine you choose.
- Needs PostgreSQL (the OS package or any server you can reach through `DATABASE_URL`; no Docker required) and
  `gnupg` (for backups). The Postgres tuning below is only for a Pi.
- Python: `requires-python` is `>=3.14`. A Pi OS that ships an older Python needs 3.14 installed on the side
  (pyenv/uv) or the requirement lowered (Django 6.x itself supports 3.12+); test before lowering it.
- gunicorn runs on Linux and macOS. On Windows use WSL or Docker, or `poetry serve` for a quick trial only.
- Steps for a release: `poetry install --only main`, set the environment (`ENVIRONMENT=production`, `SECRET_KEY`,
  `ALLOWED_HOSTS`, `DATABASE_URL`), then `poetry migrate`, `poetry collectstatic` and `poetry prod`.
  With `ENVIRONMENT=production` Django runs with `DEBUG = False` and WhiteNoise serves fingerprinted, pre-compressed
  static files, so `collectstatic` must run before the first start of each release.
- `gunicorn.conf.py`: 1 worker + 2 threads (`gthread`), worker recycled every ~1000 requests, heartbeat files in
  `/dev/shm`, no access log (no chatty SD writes), errors to stderr. Overrides: `GUNICORN_BIND` (default
  `0.0.0.0:8000`), `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT`, `GUNICORN_LOG_LEVEL`.
- First user: no sign-up page and no command needed. `FirstUserSetupMiddleware` redirects every anonymous request to
  `/setup/` **while no user exists** (only `/setup/` and `/i18n/setlang/` stay reachable); the page creates a
  superuser and signs it in. It needs a **setup code** printed to stderr in the server terminal the first time the
  site is opened without users (`services.announce_setup_code`, once per process). The code is derived from
  `SECRET_KEY` (HMAC), so all workers agree and nothing is stored. Once any user exists `/setup/` redirects to the
  login for good. `FIRST_USER_SETUP_ENABLED` (settings) exists only so tests, which mostly run without users, can turn
  the redirect off. `createsuperuser` still works.
- Docker: `docker build -t vault .` then `docker run` with `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`
  (PostgreSQL is not in the image). Multi-stage `python:3.14-slim`, runtime deps only, `gnupg`, static files collected
  at build time, non-root user, TCP health check. `RUN_MIGRATIONS=1` runs `migrate` on start (off by default). The
  first-time setup code appears in `docker logs`.
- Plain HTTP on the LAN: cookies are not marked `Secure`. Reach it from outside only through a VPN.
- Backups are made on demand from the Settings page (see Domain rules). Keep the passphrase somewhere safe and copy
  the encrypted file off the device yourself.
- No timers or extra services are used.

## How to work with me (Claude)

- Before building something big, propose a short plan and wait for confirmation.
- Prefer the simplest solution that runs well on a Pi Zero 2 W.
- Run `poetry test` after changing business logic; do not claim something works without running it.
- If the domain is ambiguous (e.g. how to count ammunition used in a match), ask instead of guessing.
- Never add a dependency without stating its cost (RAM, size, ARM wheel availability).

## Roadmap

1. Project skeleton from the template tooling (pyproject, poe tasks, Ruff, CI, Testcontainers fixtures)
2. `inventory` models, admin and migrations (Item, Category, Location, Batch, StockMovement)
3. Stock in/out services with FEFO, plus tests
4. Dashboard: expiring soon, below minimum, summary per category
5. Fast stock in/out screens with HTMX (mobile-friendly)
6. Medications and ammunition extensions (done)
7. Kits/checklists and autonomy calculator (done)
8. In-app notifications, encrypted backup/restore in Settings, CSV export (done); QR-code labels (undecided)
9. Shopping list, insights, stock count, CSV import, prices, read-only accounts, kit-safe FEFO, autonomy on the dashboard,
   new glass layout, image published to ghcr.io (done)
