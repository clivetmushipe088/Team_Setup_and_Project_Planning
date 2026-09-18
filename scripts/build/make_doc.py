#!/usr/bin/env python3
"""
Build docs/database_design_document.html and print it to PDF.

The data dictionary is generated from information_schema, so it is guaranteed
to describe the database that actually exists rather than what the author
remembers writing.
"""
import html
import subprocess
from pathlib import Path

# Resolved from this file's location (scripts/build/), not hardcoded, so the
# script works from any clone and from any working directory.
REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
MYSQL = "/opt/homebrew/bin/mysql"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DB = "momo_sms_db"

E = html.escape


def q(sql):
    r = subprocess.run([MYSQL, "-u", "root", "-B", DB], input=sql,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, check=True)
    lines = [l for l in r.stdout.strip().split("\n") if l]
    if not lines:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


TABLE_ORDER = [
    ("users", "Core entity",
     "Every party that can appear in a MoMo transaction: customers, merchants "
     "behind a payment code, mobile-money agents, partner banks, and the MTN "
     "system account used for airtime."),
    ("transaction_categories", "Lookup",
     "The transaction taxonomy. Seeded from the canonical category list in "
     "etl/config.py so the database and the Python pipeline cannot drift apart."),
    ("transactions", "Core entity",
     "The central fact table: one row per MoMo SMS that represents a financial "
     "event. Holds no sender/receiver columns by design."),
    ("transaction_participants", "Junction (M:N)",
     "Resolves users M:N transactions. Each row links one user to one "
     "transaction in a specific role."),
    ("tags", "Lookup",
     "Reusable labels: analytics buckets, data-quality flags, spending themes."),
    ("transaction_tags", "Junction (M:N)",
     "Resolves transactions M:N tags. Composite primary key, and carries the "
     "relationship's own attributes."),
    ("system_logs", "Core entity",
     "Operational audit trail for the ETL pipeline and for changes made to "
     "stored transactions."),
]

SCREENS = DOCS / "screenshots"


def img(name, caption, num):
    return (f'<figure class="shot">'
            f'<img src="screenshots/{name}" alt="{E(caption)}">'
            f'<figcaption><b>Figure {num}.</b> {E(caption)}</figcaption>'
            f'</figure>')


def data_dictionary():
    # COLUMN_KEY='MUL' only means "first column of a non-unique index" - it does
    # NOT mean foreign key. Derive the real FKs from the referential metadata,
    # or ordinary indexed columns get mislabelled as FKs.
    fk_cols = {
        (r["TABLE_NAME"], r["COLUMN_NAME"])
        for r in q(f"""SELECT TABLE_NAME, COLUMN_NAME
                       FROM information_schema.KEY_COLUMN_USAGE
                       WHERE TABLE_SCHEMA='{DB}'
                         AND REFERENCED_TABLE_NAME IS NOT NULL;""")
    }
    # Columns carrying a UNIQUE constraint, including composite ones.
    uniq_cols = {
        (r["TABLE_NAME"], r["COLUMN_NAME"])
        for r in q(f"""SELECT s.TABLE_NAME, s.COLUMN_NAME
                       FROM information_schema.STATISTICS s
                       WHERE s.TABLE_SCHEMA='{DB}' AND s.NON_UNIQUE=0
                         AND s.INDEX_NAME <> 'PRIMARY';""")
    }

    out = []
    for tname, kind, purpose in TABLE_ORDER:
        cols = q(f"""SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY,
                            COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
                     FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA='{DB}' AND TABLE_NAME='{tname}'
                     ORDER BY ORDINAL_POSITION;""")
        rows = q(f"SELECT COUNT(*) c FROM {tname};")[0]["c"]

        body = []
        for c in cols:
            col = c["COLUMN_NAME"]
            is_pk = c["COLUMN_KEY"] == "PRI"
            is_fk = (tname, col) in fk_cols
            is_uk = (tname, col) in uniq_cols
            if is_pk and is_fk:
                k = "PFK"          # composite PK member that is also an FK
            elif is_pk:
                k = "PK"
            elif is_fk:
                k = "FK"
            elif is_uk:
                k = "UK"
            else:
                k = ""
            nullable = "NULL" if c["IS_NULLABLE"] == "YES" else "NOT NULL"
            default = c["COLUMN_DEFAULT"]
            if default in (None, "NULL"):
                default = "n/a"
            else:
                default = E(default)
            extra = c["EXTRA"] or ""
            if "auto_increment" in extra:
                default = "AUTO_INCREMENT"
            body.append(
                f'<tr>'
                f'<td class="key">{k}</td>'
                f'<td class="col"><code>{E(c["COLUMN_NAME"])}</code></td>'
                f'<td class="type"><code>{E(c["COLUMN_TYPE"])}</code></td>'
                f'<td class="nul">{nullable}</td>'
                f'<td class="def">{default}</td>'
                f'<td class="desc">{E(c["COLUMN_COMMENT"])}</td>'
                f'</tr>')

        badge_cls = ("junction" if "Junction" in kind
                     else "lookup" if kind == "Lookup" else "entity")
        out.append(f"""
<div class="dict-table">
  <h3><code>{tname}</code> <span class="badge {badge_cls}">{E(kind)}</span>
      <span class="rowcount">{rows} rows seeded</span></h3>
  <p class="purpose">{E(purpose)}</p>
  <table class="dict">
    <thead><tr>
      <th>Key</th><th>Column</th><th>Type</th><th>Null</th>
      <th>Default</th><th>Description</th>
    </tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</div>""")
    return "\n".join(out)


def constraints_table():
    checks = q(f"""SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE, tc.TABLE_NAME
                   FROM information_schema.CHECK_CONSTRAINTS cc
                   JOIN information_schema.TABLE_CONSTRAINTS tc
                     ON tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME
                    AND tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA
                   WHERE cc.CONSTRAINT_SCHEMA='{DB}'
                   ORDER BY tc.TABLE_NAME, cc.CONSTRAINT_NAME;""")
    rows = "".join(
        f'<tr><td><code>{E(c["TABLE_NAME"])}</code></td>'
        f'<td><code>{E(c["CONSTRAINT_NAME"])}</code></td>'
        f'<td><code class="small">{E(c["CHECK_CLAUSE"])}</code></td></tr>'
        for c in checks)
    return (f'<table class="grid"><thead><tr><th>Table</th>'
            f'<th>Constraint</th><th>Rule</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def fk_table():
    fks = q(f"""SELECT k.TABLE_NAME, k.COLUMN_NAME, k.CONSTRAINT_NAME,
                       k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME,
                       r.DELETE_RULE, r.UPDATE_RULE
                FROM information_schema.KEY_COLUMN_USAGE k
                JOIN information_schema.REFERENTIAL_CONSTRAINTS r
                  ON r.CONSTRAINT_NAME = k.CONSTRAINT_NAME
                 AND r.CONSTRAINT_SCHEMA = k.TABLE_SCHEMA
                WHERE k.TABLE_SCHEMA='{DB}' AND k.REFERENCED_TABLE_NAME IS NOT NULL
                ORDER BY k.TABLE_NAME;""")
    rows = "".join(
        f'<tr><td><code>{E(f["TABLE_NAME"])}.{E(f["COLUMN_NAME"])}</code></td>'
        f'<td><code>{E(f["REFERENCED_TABLE_NAME"])}.{E(f["REFERENCED_COLUMN_NAME"])}</code></td>'
        f'<td><code>{E(f["DELETE_RULE"])}</code></td>'
        f'<td><code>{E(f["UPDATE_RULE"])}</code></td></tr>'
        for f in fks)
    return (f'<table class="grid"><thead><tr><th>Child column</th>'
            f'<th>References</th><th>ON DELETE</th><th>ON UPDATE</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def index_table():
    idx = q(f"""SELECT TABLE_NAME, INDEX_NAME, INDEX_TYPE, NON_UNIQUE,
                       GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) cols
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA='{DB}'
                GROUP BY TABLE_NAME, INDEX_NAME, INDEX_TYPE, NON_UNIQUE
                ORDER BY TABLE_NAME, INDEX_NAME;""")
    why = {
        "idx_txn_date": "Query 2 (monthly trend) and every date-range filter.",
        "idx_txn_cat_date": "Query 1 and Query 10. Composite: category first, "
                            "then date. Its leftmost prefix also serves plain "
                            "category grouping, so no separate category index "
                            "is kept.",
        "idx_txn_status": "Dashboard filters the ledger by settlement state.",
        "idx_txn_amount": "Query 6, ranking by value.",
        "idx_participants_user_role": "Query 3, walking the junction from the "
                                      "user side filtered by role.",
        "idx_participants_txn": "Query 4, resolving all parties on a transaction.",
        "idx_users_name": "Dashboard search box.",
        "idx_users_type_status": "Segmenting analytics by party type.",
        "idx_logs_level_created": "Query 5, error triage by severity then time.",
        "idx_logs_transaction": "Following the audit trail for one transaction.",
        "idx_txn_tags_tag": "Query 8, reverse lookup on the tag junction.",
        "ftx_txn_body": "Query 7, FULLTEXT search of SMS bodies. Avoids the "
                        "full table scan that LIKE '%...%' forces.",
        "PRIMARY": "Primary key (clustered in InnoDB).",
    }
    rows = ""
    for i in idx:
        kind = ("PRIMARY" if i["INDEX_NAME"] == "PRIMARY"
                else "UNIQUE" if i["NON_UNIQUE"] == "0"
                else i["INDEX_TYPE"])
        reason = why.get(i["INDEX_NAME"], "Enforces a uniqueness constraint.")
        rows += (f'<tr><td><code>{E(i["TABLE_NAME"])}</code></td>'
                 f'<td><code>{E(i["INDEX_NAME"])}</code></td>'
                 f'<td><code class="small">{E(i["cols"])}</code></td>'
                 f'<td>{E(kind)}</td><td class="desc">{E(reason)}</td></tr>')
    return (f'<table class="grid"><thead><tr><th>Table</th><th>Index</th>'
            f'<th>Column(s)</th><th>Type</th><th>Why it exists</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
/* The ERD is a wide landscape diagram; give it a landscape page of its own so
   the attribute lists stay legible in print. */
@page erd { size: A4 landscape; margin: 10mm; }
.erd-page { page: erd; page-break-before: always; page-break-after: always; }
* { box-sizing: border-box; }
body {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 9.6pt; line-height: 1.5; color: #1A1F2B; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
code, pre { font-family: "SF Mono", Menlo, Consolas, monospace; }
code { font-size: 0.92em; background: #F2F4F7; padding: 0.5px 3px; border-radius: 3px; }
code.small { font-size: 0.82em; }
h1, h2, h3, h4 { color: #1F2937; margin: 0 0 .4em; line-height: 1.25; }
h2 {
  font-size: 15pt; margin-top: 1.6em; padding-bottom: 5px;
  border-bottom: 2.2px solid #2E3A4F; page-break-after: avoid;
}
h3 { font-size: 11.5pt; margin-top: 1.25em; page-break-after: avoid; }
h4 { font-size: 10pt; margin-top: 1em; page-break-after: avoid; }
p { margin: 0 0 .65em; }
ul, ol { margin: 0 0 .7em; padding-left: 1.25em; }
li { margin-bottom: .25em; }

/* ---------- cover ---------- */
.cover { height: 252mm; display: flex; flex-direction: column;
         justify-content: center; page-break-after: always; text-align: center; }
.cover .eyebrow { font-size: 10pt; letter-spacing: 2.6px; text-transform: uppercase;
                  color: #6B7280; margin-bottom: 14px; }
.cover h1 { font-size: 27pt; margin-bottom: 8px; letter-spacing: -.4px; }
.cover .sub { font-size: 13pt; color: #40546E; margin-bottom: 34px; font-weight: 500; }
.cover .rule { width: 70px; height: 3.5px; background: #2E3A4F; margin: 0 auto 34px; }
.cover table { margin: 0 auto; border-collapse: collapse; font-size: 10pt; }
.cover td { padding: 5px 16px; text-align: left; }
.cover td.k { color: #6B7280; text-align: right; }
.cover td.v { font-weight: 600; }
.cover .foot { margin-top: 44px; font-size: 8.6pt; color: #9AA0B0; }

/* ---------- toc ---------- */
.toc { page-break-after: always; }
.toc ol { list-style: none; padding: 0; counter-reset: s; }
.toc > ol > li { counter-increment: s; padding: 5px 0;
                 border-bottom: 1px dotted #D5DAE3; font-size: 10pt; }
.toc > ol > li::before { content: counter(s) ".  "; color: #7A8496; font-weight: 700; }

/* ---------- tables ---------- */
table.grid, table.dict { width: 100%; border-collapse: collapse;
                         margin: .5em 0 1em; font-size: 8.4pt; }
table.grid th, table.dict th {
  background: #2E3A4F; color: #fff; text-align: left; padding: 6px 7px;
  font-weight: 600; font-size: 8.2pt;
}
table.grid td, table.dict td {
  padding: 5px 7px; border-bottom: 1px solid #E3E7ED; vertical-align: top;
}
table.grid tr:nth-child(even) td, table.dict tr:nth-child(even) td { background: #F8F9FB; }
table.dict td.key { font-weight: 700; color: #9A6B00; width: 26px; }
table.dict td.col { width: 96px; }
table.dict td.type { width: 112px; }
table.dict td.nul { width: 50px; color: #5A6479; font-size: 7.8pt; }
table.dict td.def { width: 70px; color: #5A6479; font-size: 7.8pt; }
td.desc { color: #3C4659; }
tr { page-break-inside: avoid; }

.dict-table { page-break-inside: avoid; margin-bottom: 1.1em; }
.dict-table h3 { margin-bottom: 2px; }
.purpose { color: #5A6479; font-size: 8.8pt; margin: 0 0 .4em; font-style: italic; }
.badge { font-size: 7.4pt; padding: 2px 7px; border-radius: 9px; color: #fff;
         vertical-align: middle; font-weight: 700; letter-spacing: .3px; }
.badge.entity { background: #2E3A4F; }
.badge.lookup { background: #40546E; }
.badge.junction { background: #7A4A2E; }
.rowcount { font-size: 8pt; color: #6B7280; font-weight: 400; margin-left: 6px; }

/* ---------- figures ---------- */
figure.shot { margin: .7em 0 1.3em; page-break-inside: avoid; }
figure.shot img { width: 100%; border: 1px solid #D5DAE3; border-radius: 5px; display: block; }
figure.shot figcaption { font-size: 8.2pt; color: #5A6479; margin-top: 5px;
                         padding-left: 2px; }
figure.erd { margin: .6em 0 1em; page-break-inside: avoid; }
figure.erd img { width: 100%; border: 1px solid #D5DAE3; border-radius: 5px; }

/* ---------- callouts ---------- */
.note, .warn, .key-point {
  padding: 9px 13px; border-radius: 5px; margin: .7em 0 1em;
  font-size: 9pt; page-break-inside: avoid;
}
.note { background: #F4F7FB; border-left: 3.5px solid #40546E; }
.warn { background: #FFF8F2; border-left: 3.5px solid #7A4A2E; }
.key-point { background: #F6F8F4; border-left: 3.5px solid #4E6B45; }
.note p:last-child, .warn p:last-child, .key-point p:last-child { margin-bottom: 0; }

pre.sql { background: #12131A; color: #E6E7EC; padding: 10px 13px;
          border-radius: 5px; font-size: 8pt; line-height: 1.45;
          overflow-x: hidden; white-space: pre-wrap; page-break-inside: avoid; }
.pagebreak { page-break-before: always; }
.wordcount { font-size: 8pt; color: #9AA0B0; font-style: italic; text-align: right; }
"""


RATIONALE = """
<p>The design starts from one observation about the source data: a MoMo SMS does
not describe a tidy pair of customers. An incoming transfer names a sender and a
receiver; an airtime purchase names only the buyer; a bank deposit names an
institution; a failed message may name nobody at all. Any schema that hard-codes
<code>sender_id</code> and <code>receiver_id</code> onto the transaction row
inherits that irregularity as a column full of NULLs.</p>

<p>So the central decision was to treat participation as a relationship in its
own right. <code>users</code> and <code>transactions</code> stand in a genuine
many-to-many relationship (a user takes part in many transactions, and a
transaction involves several users) and
<code>transaction_participants</code> resolves it, qualifying each link with a
<code>role</code>. This removes the nullable-column problem, lets
&ldquo;everything user X did&rdquo; run as one indexed query instead of a UNION
of two, and leaves room to add a third role later without a migration. A second
many-to-many relationship, between transactions and tags, is resolved by
<code>transaction_tags</code>, whose composite primary key carries the
relationship's own attributes: <code>confidence</code> and
<code>tagged_by</code> belong to neither entity alone.</p>

<p>Categories live in a lookup table rather than an ENUM on the transaction,
because a category carries its own attributes, a balance
<code>direction</code> and a description, and because MTN adds product types
without consulting our schema. Money is <code>DECIMAL(15,2)</code> and never
<code>FLOAT</code>: a rounding error in a stored balance is a defect that
compounds silently. <code>system_logs.transaction_id</code> is deliberately
nullable, because a message that fails during parsing never becomes a
transaction, and that failure is precisely the record an engineer needs.</p>

<p>The second decision came from testing the schema against the real dataset
rather than reasoning about it. The first version keyed <code>users</code> on a
mandatory phone number constrained to E.164, and it could not store a single row
of the course data: subscriber numbers arrive in local <code>07…</code> form, and
about a third of the counterparties are merchant tills or service endpoints with
no number at all. Keying the table on <code>party_ref</code> instead, a
canonical identifier holding either the normalised MSISDN or the service code
makes every party storable, while <code>phone_number</code> becomes a
nullable attribute still validated whenever it is present. A
<code>BEFORE INSERT</code> trigger rewrites <code>07…</code> to <code>+250…</code>
before the constraint is evaluated, so raw source values load unmodified and one
subscriber cannot be stored twice under two spellings. The guarantee is kept and
the data fits; the original design would have required discarding half of it.</p>

<p>Correctness is pushed down into the engine wherever it will go. A
<code>UNIQUE</code> index on the SHA-256 of the message body makes re-running the
ETL idempotent. CHECK constraints reject non-positive amounts and malformed
phone numbers. Rules that span rows or need <code>NOW()</code>, namely no
self-transfers, no future dates and mandatory audit of amount changes, are
triggers, because a CHECK constraint cannot express them. A documented rule is a
suggestion; an enforced rule is a guarantee.</p>
"""


def build():
    rationale_words = len(
        RATIONALE.replace("<code>", "").replace("</code>", "")
        .replace("<p>", "").replace("</p>", "").split())

    q_shots = sorted(SCREENS.glob("query_*.png"))
    q_captions = {
        1: "Query 1: volume and value by transaction category (JOIN, GROUP BY, aggregates).",
        2: "Query 2: monthly trend with conditional SUM splitting money in from money out.",
        3: "Query 3: top senders, reached through the users/transactions junction table.",
        4: "Query 4: full ledger, joining the junction twice to resolve both parties.",
        5: "Query 5: ETL error triage, including failures that never became transactions.",
        6: "Query 6: largest transaction per category using a RANK() window function.",
        7: "Query 7: FULLTEXT search across raw SMS bodies with relevance scoring.",
        8: "Query 8: tag analytics through the second junction, averaging a relationship attribute.",
        9: "Query 9: privacy-safe reporting through the masking view.",
        10: "Query 10: EXPLAIN confirming the optimiser chooses the composite index.",
    }

    # Figures must be numbered in DOCUMENT order, so every figure's HTML is
    # built here in the order it appears, not in the order the f-string below
    # happens to interpolate it.
    fig = [0]

    def nxt():
        fig[0] += 1
        return fig[0]

    erd_fig_no = nxt()                                    # section 2

    security_figs = "".join(img(n, c, nxt()) for n, c in [  # section 8
        ("09_security_constraint_rejections.png",
         "Rules 1-10: every attempted bad write, and the engine refusing it. "
         "Run with mysql --force so execution continues past each rejection."),
        ("10_security_audit_trigger.png",
         "Rule 11: updating an amount writes an audit row into system_logs "
         "automatically. The person making the change cannot opt out."),
        ("11_security_phone_masking.png",
         "Rule 12: the base table holds full phone numbers; the reporting view "
         "exposes only masked ones."),
        ("12_security_grants.png",
         "Rule 13: grants held by the two application accounts. Note the "
         "absence of DELETE and DROP."),
        ("13_security_privilege_enforcement.png",
         "Rule 13 proved rather than asserted: momo_app is refused DELETE and "
         "DROP, and momo_readonly cannot read the users table at all - but can "
         "read the masked view."),
    ])

    query_figs = ""                                        # section 9
    for p in q_shots:
        n = int(p.name.split("_")[1])
        query_figs += img(p.name, q_captions.get(n, p.stem), nxt())

    crud_figs = "".join(img(n, c, nxt()) for n, c in [      # section 10
        ("05_crud_create.png",
         "CREATE - inserting a user, a transaction, both participation rows and "
         "a tag link, then reading the result back fully joined."),
        ("06_crud_read.png",
         "READ - single-record lookup by natural key, a table-wide aggregate, "
         "and a filtered multi-table join."),
        ("07_crud_update.png",
         "UPDATE - correcting an amount and status. Note updated_at advancing "
         "on its own, and the audit trigger logging both changes unprompted."),
        ("08_crud_delete.png",
         "DELETE - ON DELETE CASCADE removes the participation and tag rows, "
         "while ON DELETE SET NULL preserves the audit trail with its pointer "
         "detached. Final row counts confirm the baseline is restored."),
    ])

    schema_figs = "".join(img(n, c, nxt()) for n, c in [    # section 10.1
        ("01_schema_tables.png",
         "All seven base tables plus the two reporting views, created by a "
         "single run of database_setup.sql."),
        ("02_seed_row_counts.png",
         "Seed volumes. The assignment requires at least five rows per main "
         "table; every table exceeds that."),
        ("03_triggers_installed.png",
         "The five triggers enforcing rules that CHECK constraints cannot "
         "express."),
        ("04_indexes.png",
         "Every index in the database, including the InnoDB FULLTEXT index on "
         "raw_sms_body."),
    ])

    explain_fig_no = 6 + len(q_shots)   # Query 10's figure number

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>MoMo SMS Analytics - Database Design Document</title>
<style>{CSS}</style></head>
<body>

<!-- ============================ COVER ============================ -->
<section class="cover">
  <div class="eyebrow">Database Design &amp; Implementation &middot; Week 2</div>
  <h1>MoMo SMS Analytics</h1>
  <div class="sub">Database Design Document</div>
  <div class="rule"></div>
  <table>
    <tr><td class="k">Author</td><td class="v">Clive Tanaka Mushipe</td></tr>
    <tr><td class="k">Email</td><td class="v">c.mushipe@alustudent.com</td></tr>
    <tr><td class="k">Team</td><td class="v">Solo</td></tr>
    <tr><td class="k">Database</td><td class="v">momo_sms_db</td></tr>
    <tr><td class="k">Platform</td><td class="v">MySQL 9.7.1 &middot; InnoDB &middot; utf8mb4</td></tr>
    <tr><td class="k">Repository</td><td class="v">Database_Design_and_Implementation</td></tr>
  </table>
  <div class="foot">
    Every query result and error message reproduced in this document was
    captured from a live run against the database built by
    <code>database/database_setup.sql</code>.
  </div>
</section>

<!-- ============================ TOC ============================ -->
<section class="toc">
  <h2 style="margin-top:0">Contents</h2>
  <ol>
    <li>Introduction and scope</li>
    <li>Entity Relationship Diagram</li>
    <li>Design rationale</li>
    <li>Entities and relationship cardinality</li>
    <li>Data dictionary</li>
    <li>Referential integrity and constraints</li>
    <li>Index strategy</li>
    <li>Security and accuracy rules, with evidence</li>
    <li>Sample queries, with results</li>
    <li>CRUD operation testing</li>
    <li>JSON data modelling and SQL&nbsp;&rarr;&nbsp;JSON mapping</li>
    <li>The dashboard, and why there is no frontend code</li>
    <li>Reproducing this build</li>
  </ol>
</section>

<!-- ============================ 1 ============================ -->
<h2>1. Introduction and scope</h2>
<p>The MoMo SMS Analytics system turns an XML export of MTN Mobile Money SMS
messages into queryable, auditable transaction data. This document specifies the
database that sits at the centre of it: the entity model, the schema as built,
the rules that protect data quality, and evidence that all of it works.</p>

<p>The schema is implemented in <code>database/database_setup.sql</code>, a
single idempotent script that drops and rebuilds the database, creates seven
tables with their constraints, indexes, triggers and views, provisions two
least-privilege accounts, and loads realistic seed data. It runs to completion
with no errors and no warnings.</p>

<div class="note">
<p><b>On the sample data.</b> Twenty-five of the thirty-two seeded transactions
are derived from the course dataset at
<code>data/raw/modified_sms_v2.xml</code>: their amounts, dates, phone numbers,
merchant till codes and SMS bodies are the values in that file, and the party
names were extracted from the message text. The remaining seven are synthetic
and marked as such in the script; they exist to cover the five categories the
sample does not exercise (<code>CASH_IN</code>, <code>CASH_OUT</code>,
<code>BANK_DEPOSIT</code>, <code>UTILITY_PAYMENT</code>,
<code>INTERNATIONAL_IN</code>, <code>REVERSAL</code>) so that every category and
every constraint keeps test coverage. No real customer data appears anywhere in
this repository.</p>
</div>

<div class="key-point">
<p><b>The schema was tested against that dataset, and an early version failed
it.</b> The first design keyed <code>users</code> on a mandatory, strictly
formatted phone number. That schema could not store a single row of the course
data: subscriber numbers arrive as <code>0789876543</code> rather than E.164, and
roughly a third of the counterparties, merchant tills such as
<code>MTN:MoMoPay:Kigali_Mart</code> and service endpoints such as
<code>MTN:Airtime</code>, have no phone number at all. Section 3 explains
the change that fixed it.</p>
</div>

<h3>What was built</h3>
<table class="grid">
<thead><tr><th>Artefact</th><th>Path</th><th>Contents</th></tr></thead>
<tbody>
<tr><td>ERD</td><td><code>docs/erd_diagram.drawio</code> / <code>.svg</code> / <code>.png</code></td>
    <td>Crow's-foot ERD; the <code>.drawio</code> file opens and edits in diagrams.net</td></tr>
<tr><td>Schema</td><td><code>database/database_setup.sql</code></td>
    <td>DDL, constraints, indexes, triggers, views, grants, seed DML</td></tr>
<tr><td>Queries</td><td><code>database/sample_queries.sql</code></td>
    <td>10 queries covering joins, aggregates, a window function and FULLTEXT</td></tr>
<tr><td>CRUD tests</td><td><code>database/crud_tests.sql</code></td>
    <td>Create / Read / Update / Delete with before-and-after state</td></tr>
<tr><td>Rule tests</td><td><code>database/security_rules_demo.sql</code></td>
    <td>13 security and accuracy rules, each demonstrated against the engine</td></tr>
<tr><td>JSON</td><td><code>examples/json_schemas.json</code></td>
    <td>draft-07 schemas plus examples generated from the live database</td></tr>
</tbody></table>

<!-- ============================ 2 ============================ -->
<section class="erd-page">
<h2 style="margin-top:0">2. Entity Relationship Diagram</h2>
<figure class="erd">
  <img src="erd_diagram.png" alt="MoMo SMS Analytics entity relationship diagram">
  <figcaption style="font-size:8.2pt;color:#5A6479;margin-top:5px">
    <b>Figure {erd_fig_no}.</b> Entity relationship diagram, crow's-foot
    notation. Seven tables: four core entities, two junction tables resolving
    the many-to-many relationships, and one lookup. Rendered here on a landscape
    page; for full resolution open <code>docs/erd_diagram.png</code>, or
    <code>docs/erd_diagram.drawio</code> to edit it in diagrams.net.
  </figcaption>
</figure>
</section>

<div class="warn">
<p><b>The two many-to-many relationships.</b> <code>users</code> M:N
<code>transactions</code> is resolved by <code>transaction_participants</code>,
which qualifies every link with a <code>role</code>.
<code>transactions</code> M:N <code>tags</code> is resolved by
<code>transaction_tags</code>, whose composite primary key
<code>(transaction_id, tag_id)</code> also carries the relationship's own
attributes, <code>confidence</code> and <code>tagged_by</code>.</p>
</div>

<!-- ============================ 3 ============================ -->
<h2>3. Design rationale</h2>
{RATIONALE}
<p class="wordcount">{rationale_words} words</p>

<!-- ============================ 4 ============================ -->
<h2 class="pagebreak">4. Entities and relationship cardinality</h2>
<table class="grid">
<thead><tr><th>Relationship</th><th>Card.</th><th>Implemented by</th>
<th>Reading</th></tr></thead>
<tbody>
<tr><td><code>transaction_categories</code> &rarr; <code>transactions</code></td>
    <td><b>1 : M</b></td><td><code>transactions.category_id</code></td>
    <td>One category classifies many transactions; each transaction has exactly one category.</td></tr>
<tr><td><code>users</code> &harr; <code>transactions</code></td>
    <td><b>M : N</b></td>
    <td><code>transaction_participants</code><br><span style="color:#7A4A2E;font-weight:600">junction</span></td>
    <td>A user takes part in many transactions; a transaction involves several users. Each link is qualified by a role.</td></tr>
<tr><td><code>users</code> &rarr; <code>transaction_participants</code></td>
    <td><b>1 : M</b></td><td><code>transaction_participants.user_id</code></td>
    <td>One user has many participation rows.</td></tr>
<tr><td><code>transactions</code> &rarr; <code>transaction_participants</code></td>
    <td><b>1 : M</b></td><td><code>transaction_participants.transaction_id</code></td>
    <td>One transaction has up to two participation rows (one per role).</td></tr>
<tr><td><code>transactions</code> &harr; <code>tags</code></td>
    <td><b>M : N</b></td>
    <td><code>transaction_tags</code><br><span style="color:#7A4A2E;font-weight:600">junction</span></td>
    <td>A transaction carries many tags; a tag is applied to many transactions.</td></tr>
<tr><td><code>transactions</code> &rarr; <code>system_logs</code></td>
    <td><b>1 : M</b></td><td><code>system_logs.transaction_id</code> (nullable)</td>
    <td>One transaction has many log entries. A log entry may belong to none.</td></tr>
</tbody></table>

<div class="key-point">
<p><b>Why the participants junction, and not two columns.</b> With
<code>sender_id</code> and <code>receiver_id</code> on the transaction row, an
airtime purchase leaves <code>receiver_id</code> NULL, a failed message leaves
both NULL, and the question &ldquo;show me everything user&nbsp;X did&rdquo;
becomes <code>WHERE sender_id = X OR receiver_id = X</code>, a predicate
no single index can serve. The junction makes each participation one row, one
index entry, one uniform query. Query&nbsp;3 and Query&nbsp;4 in section&nbsp;9
demonstrate both directions.</p>
</div>

<!-- ============================ 5 ============================ -->
<h2 class="pagebreak">5. Data dictionary</h2>
<p>Generated directly from <code>information_schema</code>, so it describes the
database that actually exists. Every description below is the
<code>COMMENT</code> stored on the column itself, the documentation lives
in the schema, not only in this document.</p>
{data_dictionary()}

<!-- ============================ 6 ============================ -->
<h2 class="pagebreak">6. Referential integrity and constraints</h2>

<h3>6.1 Foreign keys</h3>
<p>The <code>ON DELETE</code> rule differs per relationship, and each choice is
deliberate.</p>
{fk_table()}
<ul>
<li><b>RESTRICT</b> on category and on user: financial history must never be
    orphaned. A category or a customer that has transacted cannot be deleted.</li>
<li><b>CASCADE</b> on the junction rows: a participation row has no meaning
    without its transaction, so it goes when the transaction goes.</li>
<li><b>SET NULL</b> on <code>system_logs</code>: deleting a transaction must not
    destroy the audit trail explaining what happened to it. The log survives with
    its pointer detached.</li>
</ul>

<h3>6.2 CHECK constraints</h3>
{constraints_table()}

<div class="key-point">
<p><b>A conditional constraint is still a guarantee.</b>
<code>chk_users_phone_format</code> reads
<code>phone_number IS NULL OR phone_number REGEXP '^\\+250[0-9]{{9}}$'</code>.
The <code>IS NULL</code> branch is not a loophole: it says that a party may have
no phone number, a merchant till does not, while any number that
<i>is</i> stored must be well formed. The alternative, relaxing the pattern to
accept local <code>07…</code> format as well, would genuinely weaken the rule,
because the same subscriber could then be stored twice under two spellings and
no index could tell that they were the same person.</p>

<p>Normalisation happens before validation rather than instead of it.
<code>trg_users_normalise_input</code> rewrites <code>07…</code> to
<code>+250…</code>, and MySQL evaluates <code>BEFORE INSERT</code> triggers
before CHECK constraints, so the constraint sees the canonical value. Raw source
data loads unmodified and the strict rule still holds.</p>
</div>

<!-- ============================ 7 ============================ -->
<h2 class="pagebreak">7. Index strategy</h2>
<p>Primary keys and UNIQUE constraints create indexes implicitly; the table
below lists everything, with the query each additional index was created to
serve. An index that serves no query is pure write overhead, so each one is
justified.</p>
{index_table()}

<div class="note">
<p><b>A deliberate omission.</b> There is no standalone index on
<code>transactions.category_id</code>. A composite index already serves queries
on its leftmost prefix, so <code>idx_txn_cat_date(category_id,
transaction_date)</code> covers category-only grouping as well as the
category-plus-date range filter. Adding the single-column index would cost
storage and slow every INSERT while buying no read performance. Figure&nbsp;{explain_fig_no}
shows <code>EXPLAIN</code> confirming the optimiser picks the composite index for
a range query.</p>
</div>

<!-- ============================ 8 ============================ -->
<h2 class="pagebreak">8. Security and accuracy rules, with evidence</h2>
<p>Thirteen rules protect the database. Ten of them work by refusing bad writes,
and the screenshots below show the engine actually refusing them, every
error message is real output from
<code>database/security_rules_demo.sql</code>.</p>

<table class="grid">
<thead><tr><th>#</th><th>Rule</th><th>Mechanism</th><th>Threat it addresses</th>
<th>Error</th></tr></thead>
<tbody>
<tr><td>1</td><td>No duplicate SMS</td><td><code>UNIQUE(sms_hash)</code></td>
<td>Re-running the ETL would double-count every transaction and inflate reported revenue.</td><td><code>1062</code></td></tr>
<tr><td>2</td><td>Amount must be positive</td><td><code>CHECK amount &gt; 0</code></td>
<td>A parser bug storing a negative amount silently reduces reported totals.</td><td><code>3819</code></td></tr>
<tr><td>3</td><td>No zero amounts</td><td><code>CHECK amount &gt; 0</code></td>
<td>A failed parse yielding 0 pollutes averages and medians.</td><td><code>3819</code></td></tr>
<tr><td>4</td><td>Valid MSISDN format</td><td><code>CHECK ... REGEXP</code></td>
<td>Unnormalised numbers create duplicate customers and break every per-user aggregate.</td><td><code>3819</code></td></tr>
<tr><td>5</td><td>No orphan transactions</td><td><code>FOREIGN KEY</code></td>
<td>A transaction pointing at a non-existent category is invisible to every report.</td><td><code>1452</code></td></tr>
<tr><td>6</td><td>Lookup rows protected</td><td><code>ON DELETE RESTRICT</code></td>
<td>Deleting a category in use would orphan historical financial records.</td><td><code>1451</code></td></tr>
<tr><td>7</td><td>No self-transfers</td><td><code>TRIGGER</code></td>
<td>A wash-trading / laundering pattern, and a reliable signal of a mis-parsed message. Spans two rows, so no CHECK can express it.</td><td><code>1644</code></td></tr>
<tr><td>8</td><td>No future-dated rows</td><td><code>TRIGGER</code></td>
<td>Timezone bugs, corrupt source dates, deliberate tampering. <code>NOW()</code> is non-deterministic, so CHECK is unavailable.</td><td><code>1644</code></td></tr>
<tr><td>9</td><td>One sender per transaction</td><td><code>UNIQUE(transaction_id, role)</code></td>
<td>Multiple senders make the ledger ambiguous and double-count outbound value.</td><td><code>1062</code></td></tr>
<tr><td>10</td><td>Confidence within [0,1]</td><td><code>CHECK</code></td>
<td>A score above 1.0 breaks every weighted calculation downstream.</td><td><code>3819</code></td></tr>
<tr><td>11</td><td>Mandatory audit trail</td><td><code>AFTER UPDATE TRIGGER</code></td>
<td>Nobody can quietly edit a financial figure; the change is logged whether they want it logged or not.</td><td>n/a</td></tr>
<tr><td>12</td><td>Phone-number masking</td><td><code>VIEW</code></td>
<td>Full MSISDNs are PII. The view makes exposure impossible by construction, not by policy.</td><td>n/a</td></tr>
<tr><td>13</td><td>Least privilege</td><td><code>GRANT</code></td>
<td>Bounds the blast radius of SQL injection: the app account cannot DELETE or DROP anything.</td><td><code>1142</code></td></tr>
</tbody></table>

{security_figs}

<!-- ============================ 9 ============================ -->
<h2 class="pagebreak">9. Sample queries, with results</h2>
<p>Ten queries against the seeded database. Each screenshot shows the statement
as typed and the rows MySQL actually returned.</p>
{query_figs}

<!-- ============================ 10 ============================ -->
<h2 class="pagebreak">10. CRUD operation testing</h2>
<p><code>database/crud_tests.sql</code> exercises all four operations and prints
the state before and after each one, so the effect is visible rather than
asserted. The script restores the database to its seeded baseline when it
finishes.</p>
{crud_figs}

<h3>Schema verification</h3>
{schema_figs}

<!-- ============================ 11 ============================ -->
<h2 class="pagebreak">11. JSON data modelling and SQL &rarr; JSON mapping</h2>
<p>The schemas and worked examples are in
<code>examples/json_schemas.json</code> (JSON Schema draft-07). Every example in
that file was generated by querying the live database, so the examples are
genuine serialisations rather than hand-written approximations that drift from
the schema. The complete mapping is in
<code>docs/sql_to_json_mapping.md</code>; the essentials follow.</p>

<h3>11.1 Type conversion</h3>
<table class="grid">
<thead><tr><th>MySQL</th><th>JSON</th><th>Rule and reason</th></tr></thead>
<tbody>
<tr><td><code>DECIMAL(15,2)</code></td><td><code>string</code></td>
<td><b>Never a JSON number.</b> IEEE-754 doubles cannot represent every
two-decimal value exactly, and a rounding error in a stored balance compounds
silently. <code>"150000.00"</code> round-trips exactly.</td></tr>
<tr><td><code>DATETIME</code></td><td><code>string</code></td>
<td>ISO-8601 with an explicit offset. MySQL <code>DATETIME</code> stores no
timezone, so the API attaches Africa/Kigali: <code>2026-01-12T13:30:00+02:00</code>.</td></tr>
<tr><td><code>ENUM</code></td><td><code>string</code></td>
<td>Constrained by a JSON Schema <code>enum</code> with identical members.</td></tr>
<tr><td><code>BOOLEAN</code></td><td><code>true</code>/<code>false</code></td><td>n/a</td></tr>
<tr><td><code>NULL</code></td><td><code>null</code></td>
<td>Typed <code>["&lt;type&gt;","null"]</code> rather than omitted, so a client can tell
&ldquo;absent from the SMS&rdquo; from &ldquo;not requested&rdquo;.</td></tr>
</tbody></table>

<h3>11.2 Structural rules</h3>
<ul>
<li><b>Foreign keys become objects, not ids.</b> <code>category_id</code> never
appears in a response; the nested <code>category</code> object replaces it, so a
client renders a transaction from one request.</li>
<li><b>Junction tables disappear.</b> Neither junction is a top-level resource.
They become the nested <code>participants</code> and <code>tags</code> arrays,
and the attributes stored <i>on</i> the relationship travel inside those items:
<code>role</code>, <code>confidence</code>, <code>tagged_by</code>.</li>
<li><b>Composite keys dissolve.</b> In <code>transaction_tags</code>,
<code>transaction_id</code> becomes implicit (it is the parent) and
<code>tag_id</code> sits on the item. The composite key has no JSON counterpart.</li>
<li><b>Derived fields are computed at the boundary.</b>
<code>amounts.total</code> is <code>amount + fee</code>, computed on
serialisation rather than stored, so the two cannot drift apart.</li>
</ul>

<div class="key-point">
<p><b>The point worth dwelling on.</b> <code>confidence</code> belongs to neither
the transaction nor the tag. It exists only because the two are linked. That is
exactly why the relationship needs its own table in SQL, and its own
position in the JSON.</p>
</div>

<h3>11.3 The complex nested object</h3>
<p><code>examples.complete_transaction</code> is a single
<code>GET /api/v1/transactions/4</code> response drawing on all seven tables: the
transaction, its category via the FK join, both participants with the role
attribute from the junction, both tags with their relationship attributes, the
raw source message, and the ETL log entries. Abridged:</p>
<pre class="sql">{{
  "transaction_id": 4,
  "reference": "TX76662021704",
  "category": {{ "code": "bank_deposit", "name": "Bank Deposit", "direction": "credit" }},
  "amounts": {{ "principal": "150000.00", "fee": "0.00",
               "balance_after": "234900.00", "total": "150000.00", "currency": "RWF" }},
  "transaction_date": "2026-01-12T13:30:00+02:00",
  "status": "completed",
  "participants": [
    {{ "role": "sender",   "full_name": "Bank of Kigali", "phone_number": "+250788****731" }},
    {{ "role": "receiver", "full_name": "Clive Mushipe",  "phone_number": "+250788****045" }}
  ],
  "tags": [
    {{ "name": "cross_bank", "confidence": "1.00", "tagged_by": "etl" }},
    {{ "name": "high_value", "confidence": "1.00", "tagged_by": "etl" }}
  ],
  "source": {{ "raw_sms_body": "You have received 150000 RWF from Bank of Kigali ...",
              "sms_hash": "df277d1a5b1027bd538106d6d34294dc23ae53a19ec6e3abfa85bc86c7c61e76" }},
  "processing_log": [
    {{ "stage": "load", "level": "INFO",
      "message": "Inserted bank deposit transaction with cross_bank tag." }}
  ]
}}</pre>
<p>The unabridged object is <code>examples/complete_transaction.json</code>.</p>

<h3>11.4 Privacy in the serialisation layer</h3>
<p>Public responses carry masked phone numbers taken from
<code>v_transaction_summary</code>; <code>national_id</code>,
<code>raw_sms_body</code> and <code>sms_hash</code> are omitted entirely. The
masking is produced by the database view, not by application code, an
endpoint cannot leak a number it was never served.</p>

<p>Inside <code>participants[]</code> the displayable identifier is called
<code>masked_ref</code> rather than <code>phone_number</code>, because for a
merchant till it holds a code:</p>

<pre class="sql">{{ "role": "sender",   "party_ref": "+250789876543",
  "masked_ref": "+250789****543",          "has_msisdn": true  }}

{{ "role": "receiver", "party_ref": "MTN:MoMoPay:Kigali_Mart",
  "masked_ref": "MTN:MoMoPay:Kigali_Mart", "has_msisdn": false }}</pre>

<p>Two decisions are worth stating. A field whose name lies about its contents is
worse than a slightly longer name, and the naming matches the
<code>sender_ref_masked</code> / <code>receiver_ref_masked</code> columns of the
view, so the API and the database agree on what an unprivileged caller may see.
And a till code is not personal data, it identifies a shop, not a person
, so falling back to it is safe rather than a leak.</p>

<!-- ============================ 12 ============================ -->
<h2 class="pagebreak">12. The dashboard, and why there is no frontend code</h2>

<p>This repository contains no hand-written HTML, CSS or JavaScript. That is a
decision rather than an omission.</p>

<p>The Week 1 scaffold shipped an <code>index.html</code>, a
<code>chart_handler.js</code> and a <code>styles.css</code>, 824 bytes
between them, none of it doing anything beyond a <code>console.log</code>. Three
languages and three files to maintain, for a page that could not render until
the database existed. Alongside them sat three shell scripts, each a two-line
wrapper around a single <code>python3</code> command, one of which pointed at a
file that does not exist.</p>

<p>All six were removed. The dashboard is instead <i>generated</i>, on the same
principle as the ERD in section 2 and the JSON examples in section 11:</p>

<pre class="sql">database  --&gt;  scripts/build/make_dashboard.py  --&gt;  data/processed/dashboard.html</pre>

<p>One self-contained HTML file with its CSS and chart data inlined, written by
a Python script that queries the database directly. Three consequences follow:</p>

<ul>
<li><b>The source stays Python and SQL.</b> Nothing in another language is
maintained by hand, so nothing has to be kept in sync with the schema.</li>
<li><b>It cannot go stale.</b> Regenerating produces output that matches the
current schema by construction, the same property that makes the data
dictionary in section 5 trustworthy.</li>
<li><b>No web server is needed.</b> A single file opens directly in a
browser.</li>
</ul>

<p>Committing generated HTML would put HTML back into the repository language
statistics and misrepresent what the project is written in, so
<code>.gitattributes</code> marks generated artefacts
<code>linguist-generated</code> and the course dataset
<code>linguist-vendored</code>.</p>

<div class="note">
<p><b>Status.</b> The dashboard is not built yet. It follows the ETL, because
there is no value in rendering a chart that has nothing to plot. The schema,
the views that feed it (<code>v_daily_summary</code>,
<code>v_category_totals</code>) and the JSON contract it will consume are all in
place.</p>
</div>

<!-- ============================ 13 ============================ -->
<h2 class="pagebreak">13. Reproducing this build</h2>
<pre class="sql"># 1. Build the schema and load the seed data
mysql -u root -p &lt; database/database_setup.sql

# 2. Run the sample queries
mysql -u root -p --table &lt; database/sample_queries.sql

# 3. Run the CRUD tests (restores the baseline when it finishes)
mysql -u root -p --table &lt; database/crud_tests.sql

# 4. Run the security rule tests
#    --force is REQUIRED: every numbered statement is designed to fail, and
#    without it the client stops at the first rejection.
mysql -u root -p --table --force &lt; database/security_rules_demo.sql

# 5. Prove the least-privilege grants are enforced, not merely declared
mysql -u momo_app -p -e "USE momo_sms_db; DELETE FROM transactions WHERE transaction_id=1;"
mysql -u momo_readonly -p -e "USE momo_sms_db; SELECT phone_number FROM users LIMIT 1;"</pre>

<div class="warn">
<p><b>On credentials.</b> The passwords in section 6 of
<code>database_setup.sql</code> are development placeholders, committed only so
the script is runnable as coursework. A real deployment reads them from the
environment and never stores them in version control.</p>
</div>

<h3>Repository layout</h3>
<pre class="sql">data/raw/
  modified_sms_v2.xml       the 25-record course dataset (committed)
database/
  database_setup.sql        schema, constraints, indexes, triggers, views, grants, seed data
  sample_queries.sql        10 demonstration queries
  crud_tests.sql            create / read / update / delete with before-and-after state
  security_rules_demo.sql   13 security and accuracy rules tested against the engine
docs/
  erd_diagram.drawio        editable ERD source (diagrams.net)
  erd_diagram.svg / .png    rendered ERD
  sql_to_json_mapping.md    full column-by-column SQL to JSON mapping
  database_design_document.pdf   this document
  screenshots/              captured output, all of it from live runs
examples/
  json_schemas.json         draft-07 schemas + examples generated from the database
  complete_transaction.json the complex nested object on its own
etl/  api/                  Python pipeline and API (still scaffolding)
scripts/build/
  make_erd.py               regenerates the ERD
  make_screenshots.py       runs every .sql file and captures the real output
  make_json.py              regenerates the JSON schemas and examples
  make_doc.py               builds this document</pre>

<p>The source of this project is Python and SQL. There is no hand-written
HTML, CSS or JavaScript: the dashboard is generated (section 13), and
<code>.gitattributes</code> marks generated artefacts <code>linguist-generated</code>
so the repository language breakdown reflects what was actually written.</p>

</body></html>"""

    out_html = DOCS / "database_design_document.html"
    out_html.write_text(doc, encoding="utf-8")
    print(f"wrote {out_html.name}  ({len(doc):,} bytes)")
    print(f"rationale word count: {rationale_words}")

    pdf = DOCS / "database_design_document.pdf"
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", out_html.as_uri()],
        check=True, capture_output=True)
    print(f"wrote {pdf.name}  ({pdf.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()
