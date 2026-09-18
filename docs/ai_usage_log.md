# AI Usage Log

This log records where AI tools helped with the project.

## Best-practice guidance

Before and during implementation, Claude Code was asked what the accepted
practice is for each design decision below. Every recommendation was reviewed
before being adopted, and the one marked *tested* was verified against the
running server rather than taken on trust.

| Date | Topic | AI tool | Guidance taken, and what was done with it |
|------|-------|---------|-------------------------------------------|
| 2026-09-18 | MySQL data types for money | Claude Code (Anthropic) | Store currency as `DECIMAL(15,2)`, never `FLOAT` or `DOUBLE`, because binary floating point cannot represent every two-decimal value exactly and the error compounds in a stored balance. Applied to `amount`, `fee` and `balance_after`, and carried into the JSON layer, where amounts serialise as decimal strings rather than JSON numbers. |
| 2026-09-18 | Storage engine and character set | Claude Code (Anthropic) | Use InnoDB rather than MyISAM, since only InnoDB enforces foreign keys and supports transactions, and `utf8mb4` rather than `utf8`, since the latter is a three-byte subset that cannot hold every character an SMS body may contain. Both set explicitly on every table. |
| 2026-09-18 | CHECK constraints versus triggers | Claude Code (Anthropic) | A CHECK constraint can only see the row being written and cannot call non-deterministic functions such as `NOW()`. Rules that span rows (no self-transfer) or depend on the current time (no future-dated rows) therefore have to be triggers. Split the thirteen rules accordingly: eleven CHECKs, the rest as triggers. |
| 2026-09-18 | Trigger and constraint evaluation order (**tested**) | Claude Code (Anthropic) | Advice was that MySQL runs `BEFORE INSERT` triggers before evaluating CHECK constraints, which would let a trigger normalise `07…` numbers to E.164 before a strict pattern check sees them. Rather than assume it, a throwaway table was built and the insert run: the value was normalised and accepted. That result is what allowed the strict phone constraint to be kept. |
| 2026-09-18 | Index strategy | Claude Code (Anthropic) | A composite index already serves queries on its leftmost column, so a separate single-column index on that column is redundant write overhead. The standalone index on `transactions.category_id` was dropped in favour of `idx_txn_cat_date(category_id, transaction_date)`, and `EXPLAIN` was run to confirm the optimiser chooses it. Also advised using an InnoDB `FULLTEXT` index for message search instead of `LIKE '%…%'`, which cannot use an index at all. |
| 2026-09-18 | Referential actions | Claude Code (Anthropic) | `ON DELETE` should be chosen per relationship rather than applied uniformly: `RESTRICT` where deleting the parent would orphan financial history, `CASCADE` where the child row is meaningless alone, and `SET NULL` where the child must outlive the parent. Used for categories and users, junction rows, and audit logs respectively. |
| 2026-09-18 | Database security practices | Claude Code (Anthropic) | Applications should never connect as `root`; privileges should be the minimum the application needs; and PII should be masked by a view so that an endpoint cannot leak what it was never served. Produced the `momo_app` and `momo_readonly` accounts and the masking in `v_transaction_summary`, then confirmed by connecting as each account that `DELETE`, `DROP` and reads of the base `users` table are refused. |
| 2026-09-18 | Relational normalisation | Claude Code (Anthropic) | A many-to-many relationship should be resolved with a junction table, and attributes belonging to the relationship rather than to either entity belong on that table. Used for `transaction_participants` (carrying `role`) and `transaction_tags` (carrying `confidence` and `tagged_by`), keeping the model in third normal form. |
| 2026-09-18 | Python file and path handling | Claude Code (Anthropic) | Scripts should resolve paths from `Path(__file__).resolve().parents[…]` rather than hardcoding an absolute path, and should write scratch files to `tempfile` rather than beside themselves. Both practices were adopted after a generated scratch file was committed by mistake; the build scripts now run from any clone and leave no artefacts. |
| 2026-09-18 | Python database access | Claude Code (Anthropic) | Use a driver with a dictionary cursor so rows are addressed by column name, read credentials from the environment rather than from source, and let the database enforce integrity instead of re-checking it in Python. `api/db.py` was rewritten to PyMySQL on that basis, defaulting to the least-privilege `momo_app` account. |
| 2026-09-18 | JSON serialisation of relational data | Claude Code (Anthropic) | Foreign keys should serialise as the nested object rather than a bare id, junction tables should not be exposed as resources, `DATETIME` should carry an explicit UTC offset because MySQL stores none, and nullable columns should be typed `["type","null"]` rather than omitted. All applied in `examples/json_schemas.json`. |

## Work produced

| Date | Task | AI tool | What the AI helped with |
|------|------|---------|-------------------------|
| 2026-09-17 | Architecture diagram | Claude Code (Anthropic) | Created the first draw.io diagram with PNG and SVG exports, and the architecture section of the README |
| 2026-09-18 | ERD | Claude Code (Anthropic) | Generated `docs/erd_diagram.drawio`, `.svg` and `.png` from a single schema definition in `scripts/build/make_erd.py`, and wrote the ERD and relationship sections of the README |
| 2026-09-18 | MySQL schema | Claude Code (Anthropic) | Wrote `database/database_setup.sql` with the DDL, 13 CHECK constraints, 6 foreign keys, 23 indexes, 5 triggers, 3 views and least-privilege grants, then ran it against local MySQL 9.7.1 and iterated until it completed with no errors |
| 2026-09-18 | Seed data | Claude Code (Anthropic) | Derived 25 of the 32 seeded transactions from the course dataset `data/raw/modified_sms_v2.xml`, extracting party names from the SMS bodies; wrote the 7 synthetic rows that cover the categories the sample does not exercise |
| 2026-09-18 | Query and test scripts | Claude Code (Anthropic) | Wrote `sample_queries.sql`, `crud_tests.sql` and `security_rules_demo.sql`, ran them all, and captured the real terminal output into `docs/screenshots/` |
| 2026-09-18 | JSON data modelling | Claude Code (Anthropic) | Authored the draft-07 schemas in `scripts/build/make_json.py` and wrote the generator that produces every example by querying the live database; updated `docs/sql_to_json_mapping.md` |
| 2026-09-18 | Design document | Claude Code (Anthropic) | Built `docs/database_design_document.pdf` with `scripts/build/make_doc.py`; the data dictionary is generated from `information_schema` rather than written by hand, and every screenshot is captured output from a live run |
| 2026-09-18 | Architecture diagram redraw | Claude Code (Anthropic) | Rewrote `docs/architecture/system_architecture.*` with `scripts/build/make_architecture.py`; the first version showed SQLite and a hand-written dashboard, both of which had since been replaced |

## Verification

All SQL in this repository was executed against a local MySQL 9.7.1 instance
before being committed. Every screenshot in `docs/screenshots/` is captured
output from a real run; no results were written by hand or reconstructed from
memory. The design decisions and their justifications were reviewed and are my
own.
