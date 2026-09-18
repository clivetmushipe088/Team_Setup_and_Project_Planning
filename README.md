# MoMo SMS Analytics

**Team name:** Solo: Clive Mushipe

## Project description

MoMo SMS Analytics is a full-stack application that turns raw MTN Mobile Money (MoMo) SMS messages into insights. The system:

1. **Processes** an XML export of MoMo SMS messages.
2. **Cleans and normalizes** amounts, dates and phone numbers.
3. **Categorizes** each message into a transaction type (incoming money, payments to code holders, transfers to mobile numbers, bank deposits, airtime and bill payments, agent withdrawals, and more).
4. **Stores** the cleaned transactions in a relational MySQL database.
5. **Visualizes** the data in a web dashboard with charts and tables.

The project covers backend data processing, database management and frontend development.

> **Current scope.** The source of this project is deliberately **Python and SQL
> only**. The dashboard is not hand-written HTML/CSS/JS — it is *generated* from
> the database by a script in `scripts/build/`, the same way the ERD is. See
> [Dashboard](#dashboard) below.

## Team members

| Name | Email | Responsibilities |
|------|-------|------------------|
| Clive Tanaka Mushipe | c.mushipe@alustudent.com | ETL pipeline, database, frontend, documentation |

## System architecture

![System architecture](docs/architecture/system_architecture.png)

Diagram link (draw.io): [open the diagram](https://app.diagrams.net/#Uhttps%3A%2F%2Fraw.githubusercontent.com%2Fclivetmushipe088%2FDatabase_Design_and_Implementation%2Fmain%2Fdocs%2Farchitecture%2Fsystem_architecture.drawio)

The XML file goes through the ETL steps (parse, clean, categorize, load, export). The data is saved in MySQL and summarized into `dashboard.json`. The dashboard reads that JSON through a simple web server, or the FastAPI endpoints (bonus).

> The architecture diagram above still shows SQLite, from the Week 1 scaffold.
> It is redrawn when the ETL is wired to MySQL.

## Scrum board

Board link: [MoMo SMS Analytics Scrum Board](https://github.com/users/clivetmushipe088/projects/2)

Columns: Todo, In Progress, Done.

## Project structure

```
.
├── README.md
├── .env.example
├── requirements.txt
├── data/
│   ├── raw/                # momo.xml goes here (git-ignored)
│   ├── processed/          # dashboard.json
│   └── logs/               # etl.log, dead_letter/
├── docs/                   # architecture diagram, ERD
├── etl/                    # parse -> clean -> categorize -> load -> export
├── api/                    # FastAPI app (bonus)
├── scripts/
│   └── build/              # regenerates the ERD and other docs
└── tests/                  # unit tests
```

---

# Database design

The database is the foundation the ETL pipeline loads into and the dashboard
reads from. It is implemented in MySQL 8.0+ (InnoDB, utf8mb4).

## Entity Relationship Diagram

![ERD](docs/erd_diagram.png)

Editable source: [`docs/erd_diagram.drawio`](docs/erd_diagram.drawio) (opens in
[diagrams.net](https://app.diagrams.net/)).

## Schema overview

Seven tables — four core entities, two junction tables and a lookup.

| Table | Role | Purpose |
|---|---|---|
| `users` | Entity | Every party in a transaction: customers, merchants, agents, banks, the MTN system account |
| `transaction_categories` | Lookup | The transaction taxonomy, seeded from `CATEGORIES` in [etl/config.py](etl/config.py) |
| `transactions` | Entity | The fact table — one row per financial SMS |
| `transaction_participants` | **Junction** | Resolves `users` M:N `transactions`, qualified by role |
| `tags` | Lookup | Analytics buckets, data-quality flags, spending themes |
| `transaction_tags` | **Junction** | Resolves `transactions` M:N `tags`, with confidence and provenance |
| `system_logs` | Entity | ETL audit trail, including messages that never became transactions |

## Relationships

| Relationship | Cardinality | Implemented by |
|---|---|---|
| `transaction_categories` → `transactions` | 1 : M | `transactions.category_id` |
| `users` ↔ `transactions` | **M : N** | `transaction_participants` (junction) |
| `transactions` ↔ `tags` | **M : N** | `transaction_tags` (junction) |
| `transactions` → `system_logs` | 1 : M | `system_logs.transaction_id` (nullable) |

### Why a participants junction instead of sender/receiver columns

A MoMo SMS does not describe a tidy pair of customers. An airtime purchase has
no human counterparty; a bank deposit's counterparty is an institution; a failed
message may name nobody. With `sender_id` and `receiver_id` columns, one of the
two is perpetually NULL, and *"show me everything user X did"* becomes
`WHERE sender_id = X OR receiver_id = X` — a predicate no single index can
serve. The junction makes each participation one row, one index entry, one
uniform query, and leaves room for a third role later without a migration.

### Identifying parties that have no phone number

The sample dataset in [`data/raw/modified_sms_v2.xml`](data/raw/) shows that not
every counterparty is a phone subscriber:

```xml
<sms id="2" transaction_type="payment" amount="2000" sender="0789876543"
     receiver="MTN:MoMoPay:Kigali_Mart" date="2024-01-04 10:30:00" .../>
```

A merchant till (`MTN:MoMoPay:Kigali_Mart`) and a service endpoint
(`MTN:Airtime`) have no MSISDN at all, and the subscriber numbers that *are*
present use the local `07XXXXXXXX` form rather than E.164. A `users` table keyed
on a mandatory, strictly-formatted phone number cannot store this data.

So `users` is keyed on **`party_ref`** — a canonical identifier that is always
present and unique, holding either the normalised MSISDN or the service code.
`phone_number` becomes a *nullable* secondary attribute that must still be valid
E.164 when it is present:

| Party | `party_ref` | `phone_number` | `user_type` |
|---|---|---|---|
| A customer | `+250789876543` | `+250789876543` | `customer` |
| A merchant till | `MTN:MoMoPay:Kigali_Mart` | `NULL` | `merchant` |
| Airtime service | `MTN:Airtime` | `NULL` | `system` |

This keeps the accuracy guarantee — a phone number, if stored, is well-formed —
without making it impossible to record the half of the dataset that has no phone
number. Local `07…` numbers are normalised to `+250…` on the way in, so the same
subscriber cannot be stored twice under two formats.

### Regenerating the diagram

```bash
python3 scripts/build/make_erd.py
```

The `.drawio`, `.svg` and `.png` are all generated from a single schema
definition at the top of that script, so the three cannot drift apart.

---

## Dashboard

There is no hand-written frontend in this repository, and that is deliberate.

The Week 1 scaffold had an `index.html`, a `chart_handler.js` and a
`styles.css` — 824 bytes between them, none of it doing anything beyond a
`console.log`. Three languages and three files to maintain, for a page that
could not render until the database existed.

Instead the dashboard is **generated**, the same way the ERD is:

```
database  ──>  scripts/build/make_dashboard.py  ──>  data/processed/dashboard.html
```

One self-contained HTML file with its CSS and chart data inlined, written by a
Python script that queries the database directly. The benefits are the ones that
matter for a project this size:

- **The source stays Python and SQL.** No HTML, CSS or JavaScript is maintained
  by hand, so there is nothing to keep in sync with the schema.
- **It cannot go stale.** The ERD already works this way — regenerate and the
  output matches the schema by construction.
- **No web server needed.** A single file opens straight in a browser.

`.gitattributes` marks the generated output `linguist-generated`, so committed
artefacts do not misrepresent the repository's language breakdown on GitHub.

> **Status:** not built yet. It comes after the ETL can populate the database —
> there is no point rendering a chart that has nothing to plot.

---

## Getting started

```bash
pip install -r requirements.txt
python3 -m pytest           # run the tests
```

A 25-record sample dataset is committed at
[`data/raw/modified_sms_v2.xml`](data/raw/modified_sms_v2.xml), so the schema and
ETL can be run without sourcing the full export separately.

### What is not wired up yet

| Component | State |
|---|---|
| MySQL schema | complete |
| `etl/` pipeline | scaffolding — `python3 etl/run.py` does not populate the database yet |
| `api/` endpoints | scaffolding — return empty responses |
| Dashboard | not built — will be generated, see [Dashboard](#dashboard) |

Next milestone: wire `parse → clean → categorize → load → export` into the
schema so the ETL can ingest the sample dataset.