# AI Usage Log

This log records where AI tools helped with the project, as required by the course AI usage policy.

| Date | Task | AI tool | What the AI helped with |
|------|------|---------|-------------------------|
| 2026-09-17 | Architecture diagram | Claude Code (Anthropic) | Created the draw.io diagram with PNG and SVG exports, and the architecture section of the README |
| 2026-09-18 | ERD (Week 2, part 1) | Claude Code (Anthropic) | Generated `docs/erd_diagram.drawio`, `.svg` and `.png` from a single schema definition in `scripts/build/make_erd.py`, and wrote the ERD and relationship sections of the README |
| 2026-09-18 | MySQL schema (Week 2, part 2) | Claude Code (Anthropic) | Wrote `database/database_setup.sql` — DDL, 13 CHECK constraints, 6 foreign keys, 23 indexes, 5 triggers, 3 views and least-privilege grants — then ran it against local MySQL 9.7.1 and iterated until it completed with no errors |
| 2026-09-18 | Seed data | Claude Code (Anthropic) | Derived 25 of the 32 seeded transactions from the course dataset `data/raw/modified_sms_v2.xml`, extracting party names from the SMS bodies; wrote the 7 synthetic rows that cover the categories the sample does not exercise |
| 2026-09-18 | Query and test scripts | Claude Code (Anthropic) | Wrote `sample_queries.sql`, `crud_tests.sql` and `security_rules_demo.sql`, ran them all, and captured the real terminal output into `docs/screenshots/` |
