# MoMo SMS Analytics

**Team name:** Solo: Clive Mushipe

## Project description

MoMo SMS Analytics is a full-stack application that turns raw MTN Mobile Money (MoMo) SMS messages into insights. The system:

1. **Processes** an XML export of MoMo SMS messages.
2. **Cleans and normalizes** amounts, dates and phone numbers.
3. **Categorizes** each message into a transaction type (incoming money, payments to code holders, transfers to mobile numbers, bank deposits, airtime and bill payments, agent withdrawals, and more).
4. **Stores** the cleaned transactions in a relational SQLite database.
5. **Visualizes** the data in a web dashboard with charts and tables.

The project covers backend data processing, database management and frontend development.

## Team members

| Name | Email | Responsibilities |
|------|-------|------------------|
| Clive Tanaka Mushipe | c.mushipe@alustudent.com | ETL pipeline, database, frontend, documentation |

## System architecture

![System architecture](docs/architecture/system_architecture.png)

Diagram link (draw.io): [open the diagram](https://app.diagrams.net/#Uhttps%3A%2F%2Fraw.githubusercontent.com%2Fclivetmushipe088%2FDatabase_Design_and_Implementation%2Fmain%2Fdocs%2Farchitecture%2Fsystem_architecture.drawio)

The XML file goes through the ETL steps (parse, clean, categorize, load, export). The data is saved in SQLite and summarized into `dashboard.json`. The dashboard reads that JSON through a simple web server, or the FastAPI endpoints (bonus).

## Scrum board

Board link: [MoMo SMS Analytics Scrum Board](https://github.com/users/clivetmushipe088/projects/2)

Columns: Todo, In Progress, Done.

## Project structure

```
.
├── README.md
├── .env.example
├── requirements.txt
├── index.html              # dashboard page
├── web/                    # styles.css, chart_handler.js, assets/
├── data/
│   ├── raw/                # momo.xml goes here (git-ignored)
│   ├── processed/          # dashboard.json
│   └── logs/               # etl.log, dead_letter/
├── docs/                   # architecture diagram, ERD
├── etl/                    # parse -> clean -> categorize -> load -> export
├── api/                    # FastAPI app (bonus)
├── scripts/                # run_etl.sh, export_json.sh, serve_frontend.sh
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

### Regenerating the diagram

```bash
python3 scripts/build/make_erd.py
```

The `.drawio`, `.svg` and `.png` are all generated from a single schema
definition at the top of that script, so the three cannot drift apart.

---

## Getting started

```bash
pip install -r requirements.txt
scripts/run_etl.sh          # run the ETL (put momo.xml in data/raw/ first)
scripts/serve_frontend.sh   # open http://localhost:8000
python3 -m pytest           # run the tests
```