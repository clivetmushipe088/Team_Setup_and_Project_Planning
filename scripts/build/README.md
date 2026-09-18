# Documentation build scripts

These regenerate the Week 2 database deliverables from the live database. They
are build tooling, not part of the application. Nothing in `etl/`, `api/` or
`web/` imports them.

They exist so the deliverables can be rebuilt rather than hand-maintained: the
ERD, the JSON examples and the design document's data dictionary are all
derived from the schema, so they cannot silently drift out of date when the
schema changes.

## Prerequisites

- MySQL running locally, with `momo_sms_db` built by
  `database/database_setup.sql`
- Google Chrome (used headlessly to rasterise SVG and print the PDF)

## Order

```bash
# 0. Build the database first - everything below reads from it
mysql -u root -p < database/database_setup.sql

# 1. ERD: one schema definition -> .drawio + .svg + .png
python3 scripts/build/make_erd.py

# 2. Screenshots: runs every .sql file and captures the real output
python3 scripts/build/make_screenshots.py

# 3. JSON: schemas are authored in the script, examples are queried live
python3 scripts/build/make_json.py

# 4. Design document: data dictionary read from information_schema
python3 scripts/build/make_doc.py
```

Step 4 depends on steps 1 and 2, because the document embeds the ERD and the
screenshots.

## What each produces

| Script | Output |
|---|---|
| `make_erd.py` | `docs/erd_diagram.{drawio,svg,png}` |
| `make_screenshots.py` | `docs/screenshots/*.png` (23 files) |
| `make_json.py` | `examples/json_schemas.json`, `examples/complete_transaction.json` |
| `make_doc.py` | `docs/database_design_document.{html,pdf}` |

## A note on the screenshots

`make_screenshots.py` does not fabricate terminal output. It runs each query
through the `mysql` client, captures stdout and stderr merged (so error
messages interleave with the statements that caused them), and renders that
text into a terminal-styled page which Chrome screenshots. Every character in
`docs/screenshots/` came back from MySQL.
