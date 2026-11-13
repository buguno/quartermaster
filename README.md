<p align="center">
  <img src="docs/logo.png" alt="V.A.U.L.T logo" width="220">
</p>

<h1 align="center">V.A.U.L.T</h1>

<p align="center"><strong>V</strong>erified <strong>A</strong>ssets, <strong>U</strong>sage, <strong>L</strong>ots and <strong>T</strong>racking</p>

A self-hosted inventory manager for **food, water, supplies, medications, ammunition and preparedness gear**.
It tracks what you have, where it is, when it expires and how long it will last, and it tells you when something needs attention.

- **Runs offline on your own network.** No internet is needed at runtime: no CDNs, no external APIs, no accounts.
- **Light.** Two long-running processes, the app and PostgreSQL. It is built to still run on a Raspberry Pi (target: Pi Zero 2 W), but it is **not tied to any machine**: run it on a laptop, a server or a Pi.
- **Sensitive data.** Medications and ammunition are in here. **Never expose it directly to the internet.** If you need remote access, use a VPN such as WireGuard.

Interface languages: **Português (Brasil)** (default) and **English (US)**. Light and dark themes.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Core concepts](#core-concepts)
3. [How stock works](#how-stock-works)
4. [A tour of the interface](#a-tour-of-the-interface)
5. [Users, settings and backups](#users-settings-and-backups)
6. [Architecture](#architecture)
7. [Project structure](#project-structure)
8. [Getting started (development)](#getting-started-development)
9. [Configuration](#configuration)
10. [Commands](#commands)
11. [Testing](#testing)
12. [Front end](#front-end)
13. [Translations](#translations)
14. [Running it for real](#running-it-for-real)
15. [Security notes](#security-notes)
16. [Continuous integration](#continuous-integration)
17. [Conventions and contributing](#conventions-and-contributing)
18. [Status, limitations and ideas](#status-limitations-and-ideas)
19. [License](#license)

---

## What it does

| Area | What you get |
| --- | --- |
| **Items and stock** | Items grouped in categories, stored in locations, held in batches with quantity, expiry, packaging/manufacture date and lot code. Fast stock in, stock out, count adjustment and transfer between locations. Every change is logged with who did it. |
| **FEFO** | "First expired, first out". Taking stock out always uses the batch that expires first, then the oldest packaged. You can also choose a location to take from. |
| **Alerts as notifications** | A bell in the menu with a counter, plus a page that lists expired or expiring batches, items below their minimum stock and kits that are incomplete or hold expired items. They clear themselves when you fix the cause. |
| **Dashboard** | A greeting with a one-line summary, totals, what is expiring, what is below minimum, kits status, autonomy rings and bars per category. |
| **Shopping list** | Everything below its minimum stock with the amount to buy and a price estimate. Prints cleanly. |
| **Insights** | Forecast (how many days each item lasts at its recent pace), stock value per category, and activity (movement mix, who recorded, most used items and a 12-week heat map). |
| **Stock count** | Count a location's shelves, type the numbers, and only the batches that differ are adjusted and logged. |
| **CSV import** | Load a first inventory (or a big shopping trip) from a spreadsheet, all or nothing. |
| **Prices** | An optional unit cost on every entry, averaged into the batch, so the stock has a value. |
| **Medications** | Active ingredient, strength and pharmaceutical form on top of a normal item. Expiry comes from the batches. |
| **Ammunition** | Caliber, bullet weight, bullet type and manufacturer. Rounds on hand per caliber. A usage log (training, match, rotation) that takes rounds from a lot you choose and writes the stock exit for you. |
| **Kits** | Go-bags and first-aid kits as checklists tied to a location. Shows what is missing, expired or expiring, and whether the kit is ready. |
| **Autonomy** | How many days your food (by calories) and water (by liters) last for your household, ignoring expired stock, with a "what if" simulation for other numbers. |
| **Long-term storage** | Packaging date, manufacture date and a per-item shelf life that suggests the expiry. Built for things like vacuum-sealed grains that last decades. |
| **History** | Searchable log of every movement (entry, exit, adjustment, transfer) with the user who made it. |
| **Export** | CSV of the current stock. |
| **Backup** | Encrypted export and import of all data from the Settings page. |
| **Accounts** | Login required everywhere. Each user chooses theme (light, dark, system) and language, and can change their own password. Accounts can be **read-only** (look, never change). |

---

## Core concepts

| Concept | Meaning |
| --- | --- |
| **Item** | *What exists*: "Rice 1 kg", "Dipyrone 500 mg", "9 mm FMJ 124 gr". Has a name, category, unit, minimum stock, optional shelf life, calories per unit and a "counts as drinking water" flag. |
| **Category** | A flat label for items (Food, Water, Hygiene...). No hierarchy. |
| **Location** | *Where it is*: "Pantry", "Basement", "Go-bag 1". Flat, no hierarchy. |
| **Batch** | A physical lot of one item in one location: quantity, expiry date, manufacture date, packaging date, lot code. **Stock of an item is the sum of its batches.** Optionally carries a unit cost. |
| **Stock movement** | One row for every entry, exit, adjustment and transfer, with the quantity change, a reason and the user. This is the audit trail. |
| **Medication** | One-to-one extension of an item with medication details. |
| **Ammunition** | One-to-one extension of an item with firearm ammunition details. |
| **Ammunition usage** | A log entry for rounds used from one lot, linked to the stock exit it caused. |
| **Kit** | A checklist (item + required quantity) bound to exactly one location. |
| **Household** | A single row with how many people, calories per person per day and liters of water per person per day. Drives the autonomy calculation. |
| **User profile** | Per-user preferences (theme and language) and the read-only flag. |

### Units

Quantities are always `Decimal` (never floating point) with an explicit unit chosen from a fixed list, grouped in the
form:

- **Count:** unit, pair, dozen, kit, box, pack, bag, roll, can, bottle, jar, vial, sachet, cartridge
- **Medication:** tablet, capsule, ampoule, blister pack, drop, dose, international unit (IU)
- **Mass:** microgram, milligram, carat, gram, ounce, troy ounce, kilogram
- **Volume:** milliliter, liter
- **Length:** centimeter, meter

Each unit has a short symbol that is translated (for example the box shows "cx" in Portuguese and "box" in English).
The system never converts between units, and never adds quantities of different items together. An item can only use one unit, and the unit is locked as soon as the item has batches.

---

## How stock works

### The rules

- A batch quantity changes **only** through a function in `inventory.services` that also creates the stock movement, inside one database transaction with row locks. Quantities are never edited directly (the quantity is read-only in the admin too).
- The database refuses a negative quantity, a zero stock movement and impossible dates.
- Batches that reach zero are kept, so the history stays whole.
- Deleting an item, category or location that is in use is refused with a clear message.

### Entering stock

You give the item, location, quantity and, optionally, the packaging date, manufacture date, expiry date, lot code, **unit cost** and a reason. The system adds to an existing batch only if **item, location, expiry, manufacture date, packaging date and lot code are all the same**; otherwise it starts a new batch. If you leave the expiry empty and the item has a shelf life, the expiry is suggested as *packaging date + shelf life* (or manufacture date when there is no packaging date).
An expiry you type always wins.

### Taking stock out (FEFO)

Stock out is **automatic FEFO** by default, across all locations **except kits**, and can span several batches:

1. soonest expiry first (batches that never expire go last);
2. then the **oldest packaging date** (or manufacture date if the batch was bought already packed);
3. then the oldest record.

So with the same expiry, or no expiry at all, the oldest-packaged batch always goes first, while a genuinely earlier expiry still beats an older packaging.

The exit form also has **"Take from"**: pick a location that holds the item and FEFO is applied only inside it. If that location does not hold enough, the exit fails instead of borrowing from elsewhere. If the total is not enough, nothing is changed.

**Kits are protected.** The location of a kit is skipped by the automatic exit, so using up the pantry never empties a go-bag by accident. Batches held in a kit are marked **In a kit** on the item page, and the "Use first" card shows the next batch the automatic exit would really take. When the automatic exit falls short only because the rest is in kits, the error says how much is there. To use kit stock on purpose, choose the kit's location in **Take from**.

### Adjusting and transferring

- **Adjust:** set a batch to the counted quantity. The difference is recorded as an adjustment.
- **Transfer:** move part or all of a batch to another location. The batch keeps its identity (expiry, dates, lot code) and merges into a matching batch at the destination. Two movements are written, one negative and one positive.

### Dates and shelf life

- Batches may have a **manufacture date** and a **packaging date**. Use packaging for things you packed yourself (vacuum-sealed rice and beans, for example) and manufacture for products you bought.
- Items may have a **shelf life in months** (240 = 20 years). It is only a suggestion, never a guarantee.
- Validations: no future dates, manufacture is not after packaging, and the expiry is not before either of them. The database enforces the same order.
- The batch table shows the date and the age ("Packaged 05/09/2023, 3 years and 2 months ago").

### Alerts and notifications

Alerts are **derived from the current data on every request** and are never stored, so there is nothing to dismiss and nothing can go stale:

- Expired batches (red) and batches expiring within `EXPIRY_WARNING_DAYS` (default 90, yellow).
- Items whose total stock is below their minimum (red when it is zero, yellow otherwise).
- Kits that are incomplete, or that hold expired or expiring items.

The menu bell shows the count. Apps contribute their own alerts through a small registry
(see [Architecture](#architecture)).

### Prices and stock value

An entry can carry a **unit cost** (price paid per unit). It is blended into the batch as a weighted average, so buying 10 at 2 on top of 30 at 4 leaves a batch costing 3.50. An entry without a price never lowers the known cost, and a transfer carries the cost to the destination. The currency symbol is `CURRENCY_SYMBOL` (default `R$`); there is one currency and no conversion. Batches without a cost are left out of the value and counted on the Insights page.

### Shopping list

`/shopping/` lists every item below its minimum stock and how much to buy to reach it. The estimate uses the last known unit cost of each item. Use **Print** for a paper copy (the menu and buttons disappear and the light theme is used).

### Insights

`/insights/` has three tabs, all worked out from the movement history when the page opens (nothing is stored):

- **Forecast:** days of stock left per item, at the pace of the last 90 days (or since the item first moved, when that is shorter, never less than a week). Ammunition usage counts as use. Items nobody has used are left out because there is nothing to project.
- **Value:** what the batches with a price cost, in total and per category.
- **Activity:** share of entries, exits, adjustments and transfers in the last 30 days, who recorded the most movements, the items with most exits, and a heat map of the last 12 weeks.

### Counting the shelf

`/count/` is for checking the system against the real shelf. Choose a location, type what you actually count for each batch (empty fields are left alone) and apply. Only the batches whose number differs are adjusted, each one as an *adjustment* movement with the reason "Physical count" (or your own) and your name. It works in pages of 50 batches.

### Importing from CSV

`/import/` loads stock from a CSV file. Download the template and fill one row per entry:

| Column | |
| --- | --- |
| `item`, `category`, `location`, `quantity` | Required. Items, categories and locations that do not exist are created. |
| `unit` | A unit code (`un`, `kg`, `l`, `ml`, `box`, `tablet`, ...). Empty means unit; an existing item keeps its own unit and a different one is refused. |
| `expires_at`, `packaged_at`, `produced_at` | Optional dates, `2027-06-30` or `30/06/2027`. |
| `lot_code`, `unit_cost` | Optional. |

Commas or semicolons both work, decimals may use a comma, and Windows-1252 files (common from Brazilian spreadsheets) are read correctly. **All or nothing:** every row is checked first (up to 10 problems are reported, each with its line number), and the rows are saved in one transaction. Each row goes through the normal stock-in rules, so it is logged as an entry with the reason "CSV import". The limits are 2000 rows and 1 MB.

### Medications

An item becomes a medication when you add its details (from the **Item type** menu on the item page, or through **Medications > New medication**, which creates item and details together). Strength is a value plus a unit (mg, mcg, g, mL, IU, %, mg/mL) and must be filled in **both or neither**. There are 14 pharmaceutical forms from tablet to eye drops. Expiry lives on the batches, so the medication list shows stock and next expiry like any item.

### Ammunition

An ammunition item has caliber, bullet weight (in grains), bullet type and manufacturer. The **manufacturer lot is the batch lot code**, and **rounds on hand is the item's stock**, so ammunition items must be counted in *unit* or *cartridge*. The Ammunition page shows rounds on hand per caliber and a filterable list.

**Record usage** takes a lot you choose (not FEFO, because ammunition usually has no expiry and the lot matters), a number of rounds, a reason (training, match or rotation), a date and notes. It removes the rounds from that lot and writes the stock exit linked to the usage, in one transaction. You cannot use more rounds than the lot holds. The **Usage history** page filters by reason and shows the total rounds in the filter.

### Kits

A kit owns one location (created from the kit's name unless you pick a free one) and a list of items with required quantities. A line is **complete** when the *usable* (not expired) stock **at that location** reaches the required quantity. A kit is **ready** when every line is complete and nothing in it is expired. Expiring stock is flagged but does not block "ready". To complete a kit, transfer stock into its location.

A kit's location is skipped by automatic exits (see [Taking stock out](#taking-stock-out-fefo)). You can still take from it by choosing it in **Take from**, and the notifications tell you when a kit becomes incomplete. On the kit page, **Print** gives a clean checklist with a box to tick for each line.

### Autonomy

On the **Autonomy** page:

- **Food days** = usable calories ÷ (people × calories per person per day), over items that have *calories per unit*.
- **Water days** = usable liters ÷ (people × liters per person per day), over items marked *counts as drinking water* (only items measured in liters or milliliters can be marked).
- **Overall autonomy** is the smaller of the two.
- **Expired batches are never counted**, and the page says when expired stock was left out.
- Defaults are 1 person, 2000 kcal and 3 L per person per day, and you edit them on the page.
- **What if...** (on the same page) recomputes everything for other numbers, such as 4 people, without saving anything.
- The dashboard shows three rings (overall, food, water). A full ring is 30 days; the ring is red under a week.

To make an item count, edit it and fill in its calories per unit (food), or tick *counts as drinking water*.

---

## A tour of the interface

The menu on the left (a drawer on small screens) is grouped into *Overview*, *Stock* and *Manage*. The top bar has a search box for items, a **+** quick-add menu and the notification bell. At the bottom of the menu, a card tells you whether anything needs attention.

| Page | URL | What it is for |
| --- | --- | --- |
| Dashboard | `/` | Totals, expiring and low stock lists, kits summary, categories. |
| Insights | `/insights/` | Forecast, value and activity. |
| Shopping list | `/shopping/` | What to buy. Printable. |
| Notifications | `/notifications/` | Everything that needs attention. |
| Items | `/items/` | Search and filter; open an item to enter, take out, adjust or transfer stock. |
| Kits | `/kits/` | Checklists for go-bags and first-aid kits. |
| Medications | `/medications/` | Items that have medication details. |
| Ammunition | `/ammunition/` | Rounds per caliber, list, usage history. |
| Autonomy | `/autonomy/` | Days of food and water. |
| Stock count | `/count/` | Check a location against the shelf. |
| Import CSV | `/import/` | Load stock from a spreadsheet. |
| Categories | `/categories/` | Create, rename and delete categories. |
| Locations | `/locations/` | Create, rename and delete locations. |
| Movements | `/movements/` | Read-only history of every stock movement. |

At the bottom: your name (a link to **Settings**), **Admin** (staff only) and the red **Log out** button.

Other URLs: `/login/`, `/logout/`, `/settings/`, `/export/stock.csv`, `/import/template.csv`, `/admin/`.

On the item page, **Add stock** and **Remove stock** update the page in place (HTMX). Each batch has **Transfer** and
**Adjust** buttons that open a dialog. Items that are not yet a medication or ammunition have an **Item type** menu to add those details.

The Django admin at `/admin/` is available to staff users. Stock movements and ammunition usage are read-only there and batch quantities cannot be edited.

---

## Users, settings and backups

### Accounts

Every page requires a login (Django's `LoginRequiredMiddleware`), so new pages are private by default. There is no public sign-up: accounts are created by an administrator.

**The first account** is created from the browser, with no command: while no user exists the site redirects to a one-time setup page that asks for the setup code printed in the server terminal, a username and a password. See [First user](#first-user) for the details. That account is a superuser.

**More accounts** are created in the Django admin (`/admin/`, linked as **Admin** at the bottom of the menu):

1. Open **Authentication and Authorization > Users > Add user** (in Portuguese: *Autenticação e autorização > Usuários > Adicionar usuário*), type a username and a password, and save.
2. On the next screen, tick **Staff status** if the person should be able to open the admin, and **Superuser status** if they should also manage backups. Leave both off for a regular user.

| Kind of user | What they can do |
| --- | --- |
| **Regular** | Use the whole app: see and change items, stock, kits, notifications and autonomy, and their own settings. |
| **Staff** | The same, plus open the admin (limited to the permissions they are given there). |
| **Superuser** | Everything, including managing users in the admin and exporting or restoring backups. |

There are no per-feature permissions: every signed-in user can see and change all of the inventory data, and only the backup is restricted to superusers. The exception is the **read-only** flag.

**Read-only accounts.** In the admin, open the user and tick **Read-only account** in the *User profile* section at the bottom. That user can look at every page but cannot change anything: any change is refused with a 403 and a clear message, and the buttons that would only fail are hidden. They can still change their own theme, language and password, and sign out. The flag does not apply to superusers, so nobody can lock themselves out of the admin.

**Passwords.** Each user changes their own in **Settings**. There is no "forgot password" email, because the system is offline. A superuser can set a new password for anyone in the admin (open the user and use the *this form* link next to the password), or from the command line:

```bash
poetry run python manage.py changepassword <username>
```

**If you lose access** and no superuser can sign in, run `poetry run python manage.py createsuperuser` to make a new one. If every user is deleted, the site goes back to the setup page and asks for the setup code again.

### Settings (`/settings/`)

- **Appearance:** *follow the system*, *light* or *dark*. The preview is instant and saved per user.
- **Language:** Português or English. It is saved per user and wins over the browser language.
- **Change password:** old password, new password and confirmation, with Django's password validators. You stay logged in afterwards.

The login page has its own language selector and theme button because there is no user yet. A signed-in user's saved preferences always win.

### Backup and restore (superusers only)

Everything is on the Settings page. Backups are made **on demand**, not on a schedule.

- **Export:** type a passphrase twice (at least 8 characters, no line breaks) and download one encrypted file.
- **Restore:** upload the file, type the passphrase and tick the confirmation. It **replaces all current data** (items, batches, kits, users, preferences) in a single transaction, or changes nothing if something is wrong, and signs everyone out.
- **How it works:** the data goes through Django's `dumpdata`/`loaddata` with natural keys, so it is independent of the database and works on another machine. It is encrypted with GnuPG (symmetric, AES-256) and a passphrase that is **never stored**: lose it and the backup cannot be opened. The result is a standard `.gpg` file that `gpg --decrypt` can open anywhere.
- **Requirements:** `gpg` must be installed (`apt install gnupg`, `brew install gnupg`, ...).
- **Compatibility:** a backup only restores on an installation with the same migration state, that is, the same version of the system. Files that are not backups, wrong passphrases, tampered files and damaged data are all rejected without touching the current data.
- Copy the encrypted file off the device yourself.

---

## Architecture

### Stack

| Concern | Choice |
| --- | --- |
| Language | Python 3.14 (`requires-python >=3.14`) |
| Web framework | Django 6.1, server-rendered templates, **HTMX** for in-place updates |
| Database | PostgreSQL, psycopg 3 (synchronous) |
| App server | gunicorn (1 worker, 2 threads) and WhiteNoise for static files |
| Settings | django-environ (`.env` file and real environment variables; the environment wins) |
| CSS | Tailwind v4 standalone CLI (no Node). The built CSS is committed. |
| JavaScript | HTMX plus two small scripts (`app.js`, `theme.js`), all vendored locally |
| Dependency manager | Poetry 2.x (`package-mode = false`) |
| Task runner | poethepoet as a Poetry plugin (`poetry <task>`) |
| Lint and format | Ruff |
| Tests | pytest, pytest-django, pytest-cov, pytest-random-order, factory-boy, Faker, freezegun, Testcontainers |
| Typing (dev only) | `django-stubs`, so Pylance/pyright understand models, querysets and forms (pick the Poetry interpreter in your editor) |
| Backup encryption | GnuPG (external program) |

Runtime dependencies are only `django`, `psycopg[binary]`, `django-environ`, `gunicorn` and `whitenoise`.

### Layers

Dependencies point one way: **views → services → models**. Nothing imports upward.

- **Views** are thin: validate with a form, call a service, render or redirect. No business rules.
- **Services** (`services.py`) are plain functions with the business rules. They take plain arguments, return model instances and raise domain exceptions. They never import `django.http` or touch `request`.
- **Models** hold persistence and database constraints only (`CheckConstraint`, unique constraints).
- **Domain errors** are HTTP-agnostic `DomainError` subclasses. One middleware maps them to a status code and renders an HTMX-friendly error partial, so views have no `try/except` for business errors.

Apps depend on `core`, never the other way around. Domain apps may depend on `inventory`.

### Apps

| App | Responsibility |
| --- | --- |
| `core` | App-agnostic base: `TimestampedModel`, `DomainError`, error middleware, user profile and preferences, login/logout, settings page, notifications, encrypted backup, HTMX helper, form mixin, template tags. |
| `inventory` | Item, Category, Location, Batch, StockMovement, FEFO services, dashboard, items/locations/categories screens, shopping list, stock count, CSV import (`imports.py`) and export, insights (`insights.py`), expiry and stock alerts. |
| `medications` | `Medication`, one-to-one with `Item`. |
| `ammunition` | `Ammunition` (one-to-one with `Item`) and `AmmunitionUsage`. |
| `kits` | `Kit` and `KitItem`, status against stock, dashboard summary, kit alerts. |
| `autonomy` | `Household`, the food and water autonomy calculation, the "what if" simulation and the dashboard rings. |

Each app follows the same layout: `models.py`, `services.py`, `views.py`, `forms.py`, `urls.py`, `exceptions.py`,
`admin.py`, `apps.py`, an optional `registry.py` (hooks go there), and migrations.

### Plug-in points (so apps do not import each other)

`core` and `inventory` know nothing about the apps built on top of them. Apps register themselves in
`AppConfig.ready()`:

| Hook | Where | Used for |
| --- | --- | --- |
| `register_error_status(Error, HTTPStatus.X)` | `core.middleware` | Which status code a domain error becomes (unregistered errors are 400). |
| `register_alert_source(AlertSource(count, alerts))` | `core.alerts` | Contribute notifications and the menu badge count. |
| `register_item_extension(ItemExtension(panel, attach))` | `inventory.extensions` | Show a panel on the item page and an "add details" link (medications, ammunition). |
| `register_dashboard_widget(widget)` | `inventory.extensions` | Add a section to the dashboard (kits, autonomy). |
| `register_reserved_locations(source)` | `inventory.extensions` | Locations the automatic exit must skip (the locations of kits). |

### Request flow

Middleware, in order: security, WhiteNoise, sessions, locale, common, CSRF, authentication, **user preferences** (applies the saved language and exposes the profile), **login required**, messages, clickjacking, and the **domain error** mapper.

### Front-end approach

Pages are rendered on the server. HTMX swaps the stock panel after an entry, exit, adjustment or transfer, and `static/js/app.js` lets validation (422) and rule (409) responses be swapped in. Modals use the native `<dialog>` element. The sidebar drawer, dropdown menu and language selector are a few lines of plain JavaScript.

The look is a floating glass sidebar and top bar over a soft green gradient, in light and dark. The gray scale is overridden in `tailwind/input.css` with a slightly green tint, so every `stone-*` class picks it up. Charts (donuts, bars, the heat map) are plain CSS: no charting library. Printing is handled with Tailwind's `print:` variants, and `app.js` switches to the light theme while printing. Accounts marked read-only get `data-readonly` on `<html>`, and a CSS rule hides POST forms and anything marked `data-write`.

---

## Project structure

```bash
.
├── .github/
│   ├── dependabot.yml           # weekly pip updates (America/Sao_Paulo)
│   └── workflows/               # pipeline.yaml (CI) and docker.yaml (image to ghcr.io)
├── config/                      # settings.py, urls.py, wsgi.py, asgi.py
├── apps/
│   ├── core/                    # base, profile, settings page, notifications, backup
│   ├── inventory/               # items, batches, movements, FEFO, dashboard
│   ├── medications/             # medication details
│   ├── ammunition/              # ammunition details and usage log
│   ├── kits/                    # kit checklists
│   └── autonomy/                # household and autonomy calculator
├── templates/                   # base.html, shared partials/, error pages, one folder per app
├── static/
│   ├── css/tailwind.css         # built and committed
│   ├── img/                     # logo and favicons (icon.png, favicon.ico, apple-touch-icon.png)
│   └── js/                      # htmx.min.js, app.js, theme.js (vendored)
├── tailwind/input.css           # Tailwind source; outside static/ on purpose
├── locale/pt_BR/                # django.po and compiled django.mo (both committed)
├── tests/                       # mirrors apps/
├── bin/                         # Tailwind binary (git-ignored, dev only)
├── gunicorn.conf.py             # production server settings
├── Dockerfile                   # container image that runs the app with gunicorn
├── docker-entrypoint.sh         # optional migrations, then starts the app
├── .dockerignore                # keeps tests, .env and local files out of the image
├── compose.yaml                 # PostgreSQL for development
├── manage.py
├── pyproject.toml
├── CLAUDE.md                    # working notes for AI assistants and contributors
└── .env.example
```

---

## Getting started (development)

You need Python 3.14, [Poetry](https://python-poetry.org/) 2.x and Docker (for the database and the tests).

```bash
# 1. Install the Poetry task plugin once (quotes are mandatory on zsh)
pipx inject poetry "poethepoet[poetry_plugin]"

# 2. Install dependencies
poetry install

# 3. Configure
cp .env.example .env            # then change SECRET_KEY

# 4. Start PostgreSQL (port 5432 on 127.0.0.1)
docker compose up -d --wait

# 5. Create the tables
poetry migrate

# 6. Run
poetry serve                    # http://localhost:8000
```

Open the address in a browser. With no users yet it takes you to the first-time setup page (see [First user](#first-user)). Then create a category, a location and an item, and register the first entry on the item page.

> If your shell has `VIRTUAL_ENV` set to another project, `poetry run` may use the wrong environment. Run
> `unset VIRTUAL_ENV` or open a fresh terminal.

`docker compose down` stops the database and keeps the data; `docker compose down -v` deletes it.

### First user

You do not need a command to create the first user. While **no user exists**, every page redirects to **`/setup/`**, where you choose a username and a password and are signed in straight away. Nothing else exists to log in with, and the page closes itself for good as soon as that first user exists (afterwards `/setup/` just sends you to the login).

To stop a stranger on your network from claiming the system before you do, the setup page asks for a **setup code**. The server prints it in the terminal where it is running, the first time anyone opens the site while there are no users:

```bash
============================================================
V.A.U.L.T first-time setup
No users exist yet. Open http://192.168.1.10:8000/setup/ and enter this code:

    K6MP-TBUD-5DNB

============================================================
```

- The code is derived from your `SECRET_KEY`, so every server process agrees on it and nothing is stored. It stays the same on every restart until the first user exists; change the `SECRET_KEY` and the code changes too.
- Typing it is forgiving: lowercase, no dashes and extra spaces all work.
- The password is checked with the project's password validators, so weak passwords are refused.
- The account is created as a superuser (it can use the admin and the backup).
- If you would rather use the command line, `poetry run python manage.py createsuperuser` still works as always. Other users are created in the admin (see [Accounts](#accounts)).

### Rebuilding the CSS

Only needed when you change classes in templates or Python files. Download the Tailwind standalone binary for your system from the [tailwindlabs/tailwindcss releases](https://github.com/tailwindlabs/tailwindcss/releases) (the project uses **v4.3.4**) into `bin/tailwindcss`, make it executable, then:

```bash
poetry css            # build static/css/tailwind.css
poetry css-watch      # rebuild on change
poetry css-check      # fail if the committed CSS is stale (CI runs this)
```

Commit the rebuilt `static/css/tailwind.css`.

---

## Configuration

Settings come from `.env` and real environment variables (**environment variables win**).

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `SECRET_KEY` | yes | | Django secret key. Use a long random value in production. |
| `ALLOWED_HOSTS` | yes | | Comma-separated host names the site answers to, e.g. `localhost,192.168.1.10`. |
| `DATABASE_URL` | yes | | e.g. `postgres://user:password@host:5432/dbname`. |
| `ENVIRONMENT` | no | `development` | `development` turns `DEBUG` on. **Any other value runs in production mode** (`DEBUG` off, hashed and compressed static files). |
| `EXPIRY_WARNING_DAYS` | no | `90` | How many days ahead a batch counts as "expiring soon". |
| `CURRENCY_SYMBOL` | no | `R$` | Shown next to prices and values (one currency, no conversion). |
| `GUNICORN_BIND` | no | `0.0.0.0:8000` | Address for `poetry prod`. |
| `GUNICORN_WORKERS` | no | `1` | Gunicorn worker processes. |
| `GUNICORN_THREADS` | no | `2` | Threads per worker. |
| `GUNICORN_TIMEOUT` | no | `30` | Worker timeout in seconds. |
| `GUNICORN_LOG_LEVEL` | no | `info` | Gunicorn log level. |
| `RUN_MIGRATIONS` | no | `0` | Docker image only: set to `1` to run `migrate` every time the container starts. |

Fixed in `config/settings.py`: time zone `America/Sao_Paulo`, default language `pt-br`, database connections kept
for 60 seconds (`CONN_MAX_AGE = 60`), no connection pooler.

`.env` is git-ignored; `.env.example` is committed. Never commit real credentials.

---

## Commands

Tasks live in `[tool.poe.tasks]` and run as native Poetry commands (`poetry <task>`).

| Command | What it does |
| --- | --- |
| `poetry install` | Install all dependencies (development). |
| `poetry serve` | Django development server on `0.0.0.0:8000`. |
| `poetry prod` | gunicorn with `gunicorn.conf.py`. |
| `poetry collectstatic` | Gather static files for production (once per release). |
| `poetry migrate` / `poetry makemigrations` | Apply / create migrations. Review every generated migration. |
| `poetry lint` | `ruff check`. |
| `poetry format` | `ruff check --fix`, then `ruff format`. |
| `poetry test` | Lint, then pytest, then the HTML coverage report. Extra arguments are accepted. |
| `poetry coverage` | Rebuild the HTML coverage report from the last run. |
| `poetry css` / `css-watch` / `css-check` | Tailwind build, watch and freshness check. |
| `poetry messages` | Extract translatable strings into `locale/pt_BR`. |
| `poetry compilemessages` | Compile the `.po` file into `.mo`. |
| `poetry backup` | Development-only plain `pg_dump` with a timestamp. The app has its own encrypted backup. |

---

## Testing

```bash
poetry test                          # lint, tests, coverage report
poetry test tests/kits               # a subset (extra arguments go to pytest)
```

- Tests run against **real PostgreSQL** through **Testcontainers** (PostgreSQL 17), never SQLite, so Docker must be running. A session-scoped fixture starts the container and points Django at it before the test database is created.
- Tests run in **random order**, with coverage and per-test contexts. The coverage target is **100%** of statements and branches.
- Layout mirrors the apps: `tests/<app>/test_services.py` for business rules, `test_views.py` for HTTP behavior. Factories use `factory.Factory` with `Sequence` for unique fields; persistence is the fixture's job.
- **freezegun** pins the date wherever expiry and alert windows matter.
- Backup tests use the real `gpg`; they are skipped on machines without it.
- Every new rule gets a test: FEFO selection, stock balance, alert windows, constraint violations.
- Do not run the test suite on a Raspberry Pi.

---

## Front end

- **Tailwind v4** with the standalone CLI: no Node. Reusable pieces (`card`, `input`, `btn-primary`, `btn-secondary`, `btn-danger`, `badge`, `modal`, `checkbox`) are defined in `tailwind/input.css`.
- **Theme:** class-based dark mode. For signed-in users the saved choice is rendered into `<html data-theme>` and applied before the first paint; anonymous visitors use `localStorage` and the system setting.
- **HTMX** (v2.0.4) is vendored in `static/js/`. Nothing is loaded from a CDN.
- `tailwind/input.css` lives outside `static/` so `collectstatic` does not try to process it.
- Static files are served by WhiteNoise. In production they are fingerprinted and pre-compressed.

---

## Translations

- Code, identifiers and docs are in **English**. The user interface is **Portuguese (Brazil)** and **English (US)**.
- The English text in the source is the message id, so US English needs no catalog; only `locale/pt_BR` exists.
- A signed-in user's saved language wins; otherwise the language cookie, then the browser's `Accept-Language`, then `pt-br`.
- Wrap every user-visible string: `gettext_lazy` at import time, `gettext` inside functions, `{% trans %}` in templates, and `pgettext_lazy('unit symbol', ...)` for unit symbols. Never hardcode a date format: use `SHORT_DATE_FORMAT` or a translatable format string.
- Workflow for new strings: `poetry messages`, fill the empty `msgstr` entries in `locale/pt_BR/LC_MESSAGES/django.po` (and remove any `#, fuzzy` guesses), then `poetry compilemessages`. Commit the `.po` and the `.mo`.
- `tests/core/test_i18n.py` fails on untranslated entries, lost `%(placeholders)s`, or a stale `.mo`.

---

## Running it for real

Nothing is deployed or started for you. You run it by hand, on any machine you like. It runs on Linux and macOS; on Windows use WSL or Docker.

### Requirements

- PostgreSQL (the OS package, or any server reachable through `DATABASE_URL`). Docker is not required.
- `gnupg`, for backups.
- Python 3.14. The `requires-python` is `>=3.14`; a Pi OS that ships an older Python needs 3.14 installed on the side (pyenv or uv), or the requirement lowered after testing (Django 6.x itself supports Python 3.12 and newer).

### Steps for a release

```bash
poetry install --only main
export ENVIRONMENT=production SECRET_KEY='a-long-random-value' \
       ALLOWED_HOSTS='vault.local,192.168.1.10' \
       DATABASE_URL='postgres://user:password@localhost:5432/vault'
poetry migrate
poetry collectstatic
poetry prod
```

- With `ENVIRONMENT=production`, Django runs with `DEBUG` off and WhiteNoise serves fingerprinted, pre-compressed static files, so **`collectstatic` must run before the first start of each release**.
- You can put the variables in a `.env` file instead of exporting them.
- Create your first user by opening the site: it leads to the setup page, which asks for the code printed in the terminal where gunicorn runs (see [First user](#first-user)). `poetry run python manage.py createsuperuser` works too.
- To upgrade: export a backup from the Settings page, pull the new version, then repeat the steps above.
- If Poetry is too heavy on the target machine, export requirements with `poetry-plugin-export` and install with pip.

### Docker

A `Dockerfile` builds an image that runs the app with gunicorn, so you can run it on any machine that has Docker, Raspberry Pi included. It does **not** include PostgreSQL: point `DATABASE_URL` at a database the container can reach.

You can build the image yourself, or pull the published one from the GitHub Container Registry when the project publishes it (see [Continuous integration](#continuous-integration)): `docker pull ghcr.io/<owner>/vault:latest`. It is built for `linux/amd64` and `linux/arm64` (a 64-bit Raspberry Pi), and it contains no secrets: everything is configured at run time.

```bash
docker build -t vault .

docker run -d --name vault -p 8000:8000 \
  -e SECRET_KEY='a-long-random-value' \
  -e ALLOWED_HOSTS='localhost,192.168.1.10' \
  -e DATABASE_URL='postgres://user:password@db-host:5432/vault' \
  -e RUN_MIGRATIONS=1 \
  vault

docker logs vault      # the first-time setup code is printed here
```

- **Database:** the container needs to reach it by name or address. **`localhost` inside the container is the container itself, not your machine**, so a `DATABASE_URL` that says `localhost` fails with `Connection refused`. Use one of these instead:
  - With the development `compose.yaml` running: add `--network vault_default` to `docker run` and use `db` as the host: `postgres://vault:vault@db:5432/vault`.
  - A PostgreSQL on the Docker host: use `host.docker.internal` as the host (Docker Desktop on macOS and Windows has it; on Linux add `--add-host=host.docker.internal:host-gateway`). That PostgreSQL must accept connections from outside `127.0.0.1`; the development `compose.yaml` publishes its port on `127.0.0.1` only, so use the network option above for it.
  - A PostgreSQL on another machine: its address or name.
- **Environment file:** do not pass your development `.env` with `--env-file`. Docker keeps the quotes around values literally, so `ENVIRONMENT="development"` becomes the text `"development"` (not development) and `ALLOWED_HOSTS` and `DATABASE_URL` break. Write a separate file without quotes, one `NAME=value` per line, and keep it out of git.
- **Migrations:** `RUN_MIGRATIONS=1` applies them on every start. It is off by default, so you decide when the schema changes; run them once by hand with `docker run --rm ... vault python manage.py migrate`.
- **First user:** the setup code is printed to the container's output, so read it with `docker logs vault` (see [First user](#first-user)).
- **What is inside:** `python:3.14-slim`, only the runtime dependencies (no Poetry, no test tools), `gnupg` for backups, and static files already collected, so nothing has to run before the first start. It runs as a non-root user (uid 1000), and its health check is a TCP connection to port 8000. The image is about 330 MB.
- **State:** the container keeps no data. Everything is in PostgreSQL, so you can recreate the container freely. Backups are downloaded from the Settings page as before.
- **Configuration:** it is the same environment variables as everywhere else (`ENVIRONMENT` is already `production` in the image), and the `GUNICORN_*` variables work too. Never put real secrets in the image or in a committed file: pass them at run time or through an env file (`--env-file`).
- **Upgrading:** export a backup, `git pull`, `docker build -t vault .`, then start the new container with `RUN_MIGRATIONS=1`.
- **Raspberry Pi:** Docker pulls the image variant for your CPU, so the same Dockerfile builds on a 64-bit Pi. Build on the Pi itself, or with `docker buildx --platform linux/arm64`.

### gunicorn

`gunicorn.conf.py` is tuned to be light: **1 worker and 2 threads** (`gthread`), the worker is recycled every ~1000 requests so memory cannot creep up, heartbeat files go to `/dev/shm` when available, there is **no access log** (no chatty writes on an SD card) and errors go to stderr. Use the `GUNICORN_*` variables to scale it up on a bigger machine.

### Raspberry Pi notes

- Install PostgreSQL from the OS package manager (no Docker, no Redis, no Celery, no Node).
- A starting point for `postgresql.conf` on about 512 MB of RAM (adjust with measurements and keep `fsync` on): `max_connections = 20`, `shared_buffers = 32MB`, `work_mem = 2MB`, `maintenance_work_mem = 16MB`, `effective_cache_size = 128MB`.
- Use a decent SD card or an SSD.
- Nothing runs periodically: alerts, kit status and autonomy are computed when a page is rendered, and no timers or extra services are used. If you want the app to start on boot or restart after a crash, set that up on your side.
- Dev-only packages are not installed with `poetry install --only main`.

### Network

It serves plain HTTP on your LAN, so cookies are not marked `Secure`. Put it behind a VPN for access from outside, and never forward its port to the internet.

---

## Security notes

- Medication and ammunition data is sensitive. **Do not expose the app to the internet.** Use a VPN (WireGuard, for example) for remote access.
- Every page needs a login. Passwords use Django's hashers and validators. Until the first user exists the whole site only offers the setup page, protected by a code printed in the server terminal (derived from `SECRET_KEY`, never stored); after that the page is closed for good. Keep `SECRET_KEY` secret: it also derives that code. State-changing actions are POST-only with CSRF protection.
- Backups are superuser-only and encrypted with a passphrase you choose and that is never stored. Treat the file and the passphrase as you would the data.
- `SECRET_KEY` and database credentials come from the environment. Never commit a real `.env`.
- Restoring a backup replaces all data and logs everyone out. Export first.

---

## Continuous integration

`.github/workflows/pipeline.yaml` runs on every push and pull request: checkout, Python 3.14, Poetry and the poe plugin, `poetry install`, the Tailwind freshness check (`poetry css-check`, binary pinned to v4.3.4) and `poetry test`.
Docker is available on the runner, so Testcontainers provides the database. The environment values there are plain literals (never real credentials); `DATABASE_URL` only needs to be a valid URL because the tests start their own database. Dependabot opens weekly updates for pip.

`.github/workflows/docker.yaml` builds the image for `linux/amd64` and `linux/arm64` and publishes it to **GitHub Container Registry** (`ghcr.io/<owner>/<repo>`) when you push a version tag such as `v1.2.0` (tags `1.2.0`, `1.2` and `latest`), or when you run it by hand from the Actions tab (tag `edge`). It logs in with the built-in `GITHUB_TOKEN`, so no secret needs to be created. New packages start private: change the visibility under the package's settings on GitHub if you want others to pull it without logging in.

---

## Conventions and contributing

- **Plan big things first**, prefer the simplest solution that runs well on a small machine, and run `poetry test` after changing business logic.
- **Dependencies:** few and light. Before adding one, state its RAM cost, size and whether wheels exist for ARM. Avoid heavy ones (pandas, numpy, DRF, Celery, ...).
- **Lists** are paginated, use `select_related` / `prefetch_related`, and watch for N+1 queries. Avoid chatty writes.
- **Quantities** are `Decimal` with a unit, never `float`. **Timestamps** are timezone-aware. Use `HTTPStatus` constants, not raw integers. Put type hints on service functions.
- **Migrations:** never edit one that was already applied; create a new one and review every generated migration.
- **Ruff:** line length 79, single quotes, `preview = true`, rules `I, F, E, W, PL, PT, DJ`, migrations excluded. EditorConfig: 4 spaces, LF, UTF-8.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/), lowercase, with a verb in the gerund, for example `feat(inventory): adding batch model` or `fix(core): fixing alert window calculation`. Use `chore(deps):` or `build(deps):` for dependency changes.
- Whenever you add a model, make sure its app is in `INSTALLED_APPS` and that a migration exists.
- `CLAUDE.md` holds the same project notes in a form meant for AI assistants.

---

## Status, limitations and ideas

All planned features are implemented, with 100% test coverage. Known limits and open ideas:

- **QR-code labels** for shelves, bags and kits are not built; it is undecided whether they are worth it.
- **No automatic kit completion.** To complete a kit you transfer stock into its location by hand.
- **One currency.** Prices have a single symbol and no conversion. There is no barcode scanning.
- **The forecast is a straight line.** It assumes the recent pace continues; it does not know about seasons or one-off events.
- **Read-only is all or nothing.** There are no per-feature roles.
- **Locations and categories are flat** (no hierarchy), and **units are a fixed list**.
- Shelf life is a suggestion for the expiry, not a guarantee of quality.
- The backup holds the data in memory while it works, which is fine at household scale. It requires `gpg` and the same version of the system on both sides.
- The unit symbol of a cartridge reads "cartucho" in the singular next to any quantity.
- Windows is not supported natively because of gunicorn.

---

## License

Released under the [MIT License](LICENSE).
