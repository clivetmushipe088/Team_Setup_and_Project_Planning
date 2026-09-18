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
├── database/               # MySQL schema, queries, CRUD and rule tests
├── examples/               # JSON schemas and API response examples
├── data/
│   ├── raw/                # modified_sms_v2.xml (committed); other exports ignored
│   ├── processed/          # dashboard.json, dashboard.html (generated)
│   └── logs/               # etl.log, dead_letter/
├── docs/                   # ERD, SQL→JSON mapping, screenshots
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

## Setup

```bash
# Build the schema and load seed data (drops and recreates momo_sms_db)
mysql -u root -p < database/database_setup.sql

# Run the demonstration queries
mysql -u root -p --table < database/sample_queries.sql

# Run the CRUD tests (restores the baseline when finished)
mysql -u root -p --table < database/crud_tests.sql

# Run the security rule tests
# --force is REQUIRED: every numbered statement is designed to fail, and
# without it the client stops at the first rejection
mysql -u root -p --table --force < database/security_rules_demo.sql
```

The setup script is idempotent — it drops and recreates the database, so it is
safe to re-run.

| Object | Count |
|---|---|
| Base tables | 7 |
| Views | 3 |
| Foreign keys | 6 |
| CHECK constraints | 13 |
| Triggers | 5 |
| Indexes | 23 (incl. one InnoDB FULLTEXT) |

### Seed data

| Table | Rows |
|---|---|
| `transaction_categories` | 10 |
| `users` | 27 |
| `tags` | 10 |
| `transactions` | 32 |
| `transaction_participants` | 64 |
| `transaction_tags` | 28 |
| `system_logs` | 18 |

25 of the 32 transactions are derived from the course dataset at
[`data/raw/modified_sms_v2.xml`](data/raw/modified_sms_v2.xml) — real amounts,
dates, phone numbers, merchant codes and SMS bodies. The remaining 7 are
synthetic and labelled as such in the script, covering the five categories the
sample does not exercise (`CASH_IN`, `CASH_OUT`, `BANK_DEPOSIT`,
`UTILITY_PAYMENT`, `INTERNATIONAL_IN`, `REVERSAL`) so every category and every
constraint keeps test coverage. No real customer data is in this repository.

## Security and accuracy rules

Thirteen rules are enforced by the engine rather than by convention. A
documented rule is a suggestion; an enforced rule is a guarantee.

| # | Rule | Mechanism | Why | Error |
|---|---|---|---|---|
| 1 | No duplicate SMS | `UNIQUE(sms_hash)` | Makes re-running the ETL idempotent instead of double-counting revenue | `1062` |
| 2–3 | Amount must be > 0 | `CHECK` | A parser bug storing 0 or a negative silently corrupts every total | `3819` |
| 4 | Valid MSISDN format | `CHECK ... REGEXP` | Unnormalised numbers create duplicate customers. Applies only when a number is present | `3819` |
| 5 | No orphan transactions | `FOREIGN KEY` | A transaction with no valid category is invisible to every report | `1452` |
| 6 | Lookup rows protected | `ON DELETE RESTRICT` | Financial history must never be orphaned | `1451` |
| 7 | No self-transfers | `TRIGGER` | Wash-trading pattern; spans two rows so `CHECK` cannot express it | `1644` |
| 8 | No future-dated rows | `TRIGGER` | Timezone bugs and tampering; `NOW()` is ineligible for `CHECK` | `1644` |
| 9 | One sender per transaction | `UNIQUE(transaction_id, role)` | Stops a parser bug attaching three senders | `1062` |
| 10 | Confidence within [0,1] | `CHECK` | A score above 1.0 breaks every weighted calculation | `3819` |
| 11 | Mandatory audit trail | `AFTER UPDATE TRIGGER` | Amount changes are logged whether the editor wants it or not | — |
| 12 | Phone-number masking | `VIEW v_transaction_summary` | PII exposure becomes impossible by construction, not by policy | — |
| 13 | Least privilege | `GRANT` | `momo_app` cannot `DELETE` or `DROP`; bounds SQL-injection blast radius | `1142` |

Every rule is demonstrated against the live engine in
[`database/security_rules_demo.sql`](database/security_rules_demo.sql), with
captured output in [`docs/screenshots/`](docs/screenshots/).

Rules 7 and 8 are triggers rather than CHECK constraints for a reason worth
stating: rule 7 spans two rows, and rule 8 needs `NOW()`, which is
non-deterministic. A CHECK constraint can do neither.

### Normalisation before validation

Rule 4 would reject the course dataset outright — it stores numbers as
`0781234567`, not E.164. Rather than relax the constraint, a `BEFORE INSERT`
trigger rewrites local numbers to `+250…` first. MySQL evaluates `BEFORE INSERT`
triggers *before* CHECK constraints, so the constraint sees the normalised
value:

```sql
INSERT INTO users (party_ref, phone_number, full_name, user_type)
VALUES ('+250781234567', '0781234567', 'Alice', 'customer');
-- stored as +250781234567
```

The strict guarantee survives, raw source data loads without preprocessing, and
one subscriber cannot be stored twice under two spellings.

## Views

| View | Purpose |
|---|---|
| `v_transaction_summary` | Privacy-safe ledger — phone numbers masked to `+250788****045`, falling back to `party_ref` for merchant tills that have no number |
| `v_category_totals` | Per-category aggregates |
| `v_daily_summary` | Daily volume and fees split by credit/debit, for the dashboard time series |

---

## JSON data modelling

[`examples/json_schemas.json`](examples/json_schemas.json) holds JSON Schema
(draft-07) definitions for every entity plus worked API examples. Every example
is generated by querying the live database, so they are genuine serialisations
rather than hand-written approximations that drift from the schema.

- [`examples/complete_transaction.json`](examples/complete_transaction.json) —
  the complex nested object: one response drawing on all seven tables.
- [`docs/sql_to_json_mapping.md`](docs/sql_to_json_mapping.md) — the full
  column-by-column mapping.

### Type conversion

| MySQL | JSON | Reason |
|---|---|---|
| `DECIMAL(15,2)` | decimal **string** | IEEE-754 doubles cannot hold every 2-decimal value exactly; a rounding error in a balance compounds silently |
| `DATETIME` | ISO-8601 `+02:00` | MySQL stores no timezone, so the API attaches Africa/Kigali |
| `ENUM` | `string` | Constrained by a JSON Schema `enum` with identical members |
| `NULL` | `null` | Typed `["<type>","null"]` rather than omitted, so a client can tell "absent from the SMS" from "not requested" |

### Structural decisions

**Foreign keys become objects, not ids.** `category_id` never appears in a
response — the nested `category` object replaces it, so a client renders a
transaction from one request instead of two.

**Junction tables disappear, but their attributes survive.** Neither junction is
a top-level resource. They become the nested `participants` and `tags` arrays,
and the attributes stored *on* the relationship travel inside those items:
`role`, `confidence`, `tagged_by`.

That last point is the one worth being able to explain: `confidence` belongs to
neither the transaction nor the tag. It exists only because the two are linked.
That is exactly why the relationship needs its own table in SQL — and its own
position in the JSON.

### Parties with no phone number

Inside `participants[]` the displayable identifier is called **`masked_ref`**,
not `phone_number`, because for a merchant till it holds a code:

```json
{ "role": "sender",   "party_ref": "+250789876543",
  "masked_ref": "+250789****543",          "has_msisdn": true  }

{ "role": "receiver", "party_ref": "MTN:MoMoPay:Kigali_Mart",
  "masked_ref": "MTN:MoMoPay:Kigali_Mart", "has_msisdn": false }
```

A field whose name lies about its contents is worse than a slightly longer name,
and the naming matches the `sender_ref_masked` / `receiver_ref_masked` columns
of `v_transaction_summary` — so the API and the database agree on what an
unprivileged caller may see. A till code identifies a shop rather than a person,
so falling back to it is safe rather than a leak.

### Regenerating

```bash
python3 scripts/build/make_json.py
```

Requires the database to exist — that dependency is deliberate.

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
# 1. Database — see Setup above for the full set of scripts
mysql -u root -p < database/database_setup.sql

# 2. Python side
pip install -r requirements.txt
python3 -m pytest           # run the tests
```

A 25-record sample dataset is committed at
[`data/raw/modified_sms_v2.xml`](data/raw/modified_sms_v2.xml), so the schema and
ETL can be run without sourcing the full export separately.

### What is not wired up yet

| Component | State |
|---|---|
| MySQL schema | complete — constraints, indexes, triggers, views, seed data |
| Sample queries, CRUD and rule tests | complete, with captured output |
| JSON schemas and SQL→JSON mapping | complete, generated from the live database |
| `etl/` pipeline | scaffolding — `python3 etl/run.py` does not populate the database yet |
| `api/` endpoints | scaffolding — `api/db.py` connects to MySQL, but the routes return empty responses |
| Dashboard | not built — will be generated, see [Dashboard](#dashboard) |

Next milestone: wire `parse → clean → categorize → load → export` into the
schema so the ETL can ingest the sample dataset.