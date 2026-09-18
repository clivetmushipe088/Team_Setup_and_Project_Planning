#!/usr/bin/env python3
"""
Render genuine MySQL output as terminal screenshots.

Parses the project's .sql files, runs each labelled block against the live
database, captures the real stdout/stderr, and renders it as a PNG via
headless Chrome. Nothing here is mocked - every byte shown came from MySQL.
"""
import html
import re
import subprocess
import tempfile
import sys
from pathlib import Path

# Resolved from this file's location (scripts/build/), not hardcoded, so the
# script works from any clone and from any working directory.
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "screenshots"
# Scratch HTML goes to the system temp dir. Writing it next to this
# script would leave 23 build artifacts inside the repo.
TMP = Path(tempfile.mkdtemp(prefix="momo-shots-"))
MYSQL = "/opt/homebrew/bin/mysql"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DB = "momo_sms_db"

OUT.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)

TERMINAL_CSS = """
:root {
  --bg: #12131a; --chrome: #23252f; --fg: #e6e7ec; --muted: #9aa0b0;
  --prompt: #6ee7a8; --sql: #8ab4ff; --err: #ff8a8a; --ok: #6ee7a8;
  --border: #343747; --title: #c9ccd8;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 26px; background: #0a0b10;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.window {
  background: var(--bg); border-radius: 10px; overflow: hidden;
  border: 1px solid var(--border); box-shadow: 0 10px 34px rgba(0,0,0,.55);
}
.titlebar {
  background: var(--chrome); padding: 9px 14px; display: flex;
  align-items: center; gap: 8px; border-bottom: 1px solid var(--border);
}
.dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
.r { background: #ff5f57; } .y { background: #febc2e; } .g { background: #28c840; }
.title {
  margin-left: 10px; color: var(--title); font-size: 12.5px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; letter-spacing: .2px;
}
.caption {
  color: var(--muted); font-size: 12px; margin-left: auto;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
pre {
  margin: 0; padding: 16px 18px; color: var(--fg); background: var(--bg);
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12.5px; line-height: 1.5; white-space: pre; tab-size: 4;
}
.prompt { color: var(--prompt); font-weight: 600; }
.sql    { color: var(--sql); }
.err    { color: var(--err); font-weight: 600; }
.ok     { color: var(--ok); }
.cmt    { color: var(--muted); font-style: italic; }
"""


def colourise(text: str) -> str:
    """Wrap recognised line kinds in colour spans. Input is already escaped."""
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("mysql&gt;") or stripped.startswith("$ "):
            # prompt line: colour the prompt, then the statement
            if stripped.startswith("$ "):
                out.append(f'<span class="prompt">$</span><span class="sql">{line[1:]}</span>')
            else:
                idx = line.index("mysql&gt;") + len("mysql&gt;")
                out.append(f'<span class="prompt">{line[:idx]}</span>'
                           f'<span class="sql">{line[idx:]}</span>')
        elif stripped.startswith("-&gt;"):
            out.append(f'<span class="sql">{line}</span>')
        elif stripped.startswith("ERROR"):
            out.append(f'<span class="err">{line}</span>')
        elif stripped.startswith("--"):
            out.append(f'<span class="cmt">{line}</span>')
        else:
            out.append(line)
    return "\n".join(out)


def render(name: str, title: str, caption: str, body: str, width: int | None = None):
    esc = html.escape(body)

    lines_list = body.split("\n")
    longest = max((len(l) for l in lines_list), default=80)

    # Box-drawn result tables must never wrap or the columns break. Free text
    # (error messages, EXPLAIN trees) may wrap, which keeps the image readable
    # instead of 4000px wide.
    has_table = any(l.startswith(("+--", "| ")) for l in lines_list)
    wrap = longest > 175 and not has_table

    if width is None:
        # 12.5px SF Mono is ~7.55px per character.
        title_w = int((len(title) + len(caption) + 14) * 7.8) + 80
        if wrap:
            width = 1500
        else:
            width = max(980, min(int(longest * 7.55) + 90, 2400))
        width = max(width, min(title_w, 1500))

    wrap_css = ("white-space: pre-wrap; overflow-wrap: anywhere;"
                if wrap else "white-space: pre;")
    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{TERMINAL_CSS}</style></head>
<body><div class="window">
  <div class="titlebar">
    <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
    <span class="title">{html.escape(title)}</span>
    <span class="caption">{html.escape(caption)}</span>
  </div>
  <pre style="{wrap_css}">{colourise(esc)}</pre>
</div></body></html>"""

    hp = TMP / f"{name}.html"
    hp.write_text(page, encoding="utf-8")

    # Estimate height from content so nothing is clipped. Wrapped lines occupy
    # more than one row, so account for the extra.
    if wrap:
        per_row = max(1, int((width - 56) / 7.55))
        lines = sum(max(1, -(-len(l) // per_row)) for l in lines_list)
    else:
        lines = len(lines_list)
    height = 26 * 2 + 40 + int(lines * 18.8) + 46

    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
         f"--screenshot={OUT / (name + '.png')}",
         f"--window-size={width},{height}",
         "--default-background-color=00000000",
         "--force-device-scale-factor=2",
         hp.as_uri()],
        check=True, capture_output=True,
    )
    print(f"  wrote {name}.png  ({lines} lines)")


# Label columns emitted purely to caption a result set; they add no information
# to a screenshot and are collapsed into a plain heading line.
LABEL_COLS = {"rule_test", "query_label", "step", "crud_operation",
              "demo", "account", "data_source", "summary", "verification_step"}
BORDER = re.compile(r"^\+[-+]+\+$")
BOXED = re.compile(r"^\|\s*(.*?)\s*\|$")


def clean_mysql_output(text: str) -> str:
    """Collapse mysql's caption tables into plain headings, keeping real results.

    A `SELECT 'heading' AS query_label;` renders as a five-line, single-column
    table: border / column name / border / value / border. That is pure noise in
    a screenshot, so it is replaced by the value on its own line.
    """
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if BORDER.match(lines[i]) and i + 2 < len(lines):
            head = BOXED.match(lines[i + 1])
            # Single-column table (no internal pipe) whose column is a caption.
            if (head and "|" not in head.group(1)
                    and head.group(1).strip() in LABEL_COLS
                    and BORDER.match(lines[i + 2])):
                j = i + 3
                values = []
                while j < len(lines) and not BORDER.match(lines[j]):
                    cell = BOXED.match(lines[j])
                    values.append(cell.group(1).strip() if cell else lines[j])
                    j += 1
                out.extend(v for v in values if v)
                i = j + 1          # skip the closing border too
                continue
        out.append(lines[i])
        i += 1
    # Squash runs of blank lines left behind.
    cleaned = []
    for l in out:
        if l.strip() == "" and cleaned and cleaned[-1].strip() == "":
            continue
        cleaned.append(l)
    return "\n".join(cleaned).strip()


def run_sql(sql: str, force: bool = False, user: str = "root",
            pw: str | None = None, clean: bool = True) -> str:
    cmd = [MYSQL, "-u", user]
    if pw:
        cmd.append(f"-p{pw}")
    cmd += ["--table"]
    if force:
        cmd.append("--force")
    # stderr MUST merge into stdout so ERROR lines interleave with the
    # statement that produced them, rather than all clustering at the end.
    r = subprocess.run(cmd, input=sql, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    text = "\n".join(
        l for l in (r.stdout or "").split("\n")
        if not l.startswith("mysql: [Warning] Using a password")
    ).rstrip()
    return clean_mysql_output(text) if clean else text


def wrap_sql_display(sql: str) -> str:
    """Format a SQL statement as if typed at the mysql> prompt."""
    lines = [l for l in sql.strip().split("\n")]
    out = []
    for i, l in enumerate(lines):
        out.append(("mysql> " if i == 0 else "    -> ") + l)
    return "\n".join(out)


def parse_blocks(path: Path, marker: str):
    """Split a .sql file into (number, title, sql_body) blocks."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^-- {marker} (\d+) - (.+?)$(.*?)(?=^-- {marker} \d+ -|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(text):
        yield int(m.group(1)), m.group(2).strip(), m.group(3)


def extract_statements(block: str) -> str:
    """Strip comment lines and the label SELECT, return the real SQL."""
    body = "\n".join(
        l for l in block.split("\n")
        if not l.strip().startswith("--") and "AS query_label" not in l
    )
    return body.strip()


def main():
    if not Path(CHROME).exists():
        sys.exit("Chrome not found")

    # Reset to a clean baseline first.
    print("Re-seeding database...")
    setup = (REPO / "database" / "database_setup.sql").read_text()
    subprocess.run([MYSQL, "-u", "root"], input=setup, capture_output=True, text=True)

    # ---- 1. Schema verification -------------------------------------------
    print("Schema verification...")
    verify_sql = f"""USE {DB};
SHOW TABLES;
SELECT TABLE_NAME AS 'Table', TABLE_ROWS IS NOT NULL AS ok FROM information_schema.TABLES WHERE TABLE_SCHEMA='{DB}' AND TABLE_TYPE='BASE TABLE';"""
    body = wrap_sql_display(f"USE {DB};\nSHOW TABLES;") + "\n" + run_sql(f"USE {DB};\nSHOW TABLES;")
    render("01_schema_tables", "Terminal - schema verification",
           "database_setup.sql", body)

    counts_sql = """SELECT 'transaction_categories' AS table_name, COUNT(*) AS rows_loaded FROM transaction_categories
UNION ALL SELECT 'users', COUNT(*) FROM users
UNION ALL SELECT 'tags', COUNT(*) FROM tags
UNION ALL SELECT 'transactions', COUNT(*) FROM transactions
UNION ALL SELECT 'transaction_participants', COUNT(*) FROM transaction_participants
UNION ALL SELECT 'transaction_tags', COUNT(*) FROM transaction_tags
UNION ALL SELECT 'system_logs', COUNT(*) FROM system_logs;"""
    body = wrap_sql_display(counts_sql) + "\n" + run_sql(f"USE {DB};\n{counts_sql}")
    render("02_seed_row_counts", "Terminal - seed data row counts",
           "at least 5 rows per table", body)

    trig_sql = """SELECT TRIGGER_NAME, ACTION_TIMING, EVENT_MANIPULATION, EVENT_OBJECT_TABLE
FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='momo_sms_db'
ORDER BY EVENT_OBJECT_TABLE, TRIGGER_NAME;"""
    body = wrap_sql_display(trig_sql) + "\n" + run_sql(f"USE {DB};\n{trig_sql}")
    render("03_triggers_installed", "Terminal - triggers installed",
           "cross-row business rules", body)

    idx_sql = """SELECT DISTINCT TABLE_NAME, INDEX_NAME, INDEX_TYPE, NON_UNIQUE
FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='momo_sms_db'
ORDER BY TABLE_NAME, INDEX_NAME;"""
    body = wrap_sql_display(idx_sql) + "\n" + run_sql(f"USE {DB};\n{idx_sql}")
    render("04_indexes", "Terminal - indexes", "performance optimisation", body)

    # ---- 2. Sample queries -------------------------------------------------
    print("Sample queries...")
    for num, title, block in parse_blocks(REPO / "database" / "sample_queries.sql", "QUERY"):
        sql = extract_statements(block)
        if not sql:
            continue
        # EXPLAIN returns one enormous single-cell row; render it unboxed so
        # the tree can wrap instead of forcing a 4800px-wide image.
        if sql.upper().startswith("EXPLAIN"):
            r = subprocess.run([MYSQL, "-u", "root", "-N", "-B"],
                               input=f"USE {DB};\n{sql}",
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
            out = r.stdout.replace("\\n", "\n").strip()
        else:
            out = run_sql(f"USE {DB};\n{sql}")
        body = wrap_sql_display(sql) + "\n" + out
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40]
        render(f"query_{num:02d}_{slug}", f"Terminal - Query {num}", title, body)

    # ---- 3. CRUD -----------------------------------------------------------
    print("CRUD operations...")
    crud_text = (REPO / "database" / "crud_tests.sql").read_text()
    full = run_sql(crud_text, force=False)
    sections = re.split(r"\n(?=#{16} )", full)
    names = {"C:": ("05_crud_create", "CREATE"), "R:": ("06_crud_read", "READ"),
             "U:": ("07_crud_update", "UPDATE"), "D:": ("08_crud_delete", "DELETE")}
    for sec in sections:
        for key, (fname, label) in names.items():
            if f"# {key}" in sec[:400]:
                render(fname, f"Terminal - CRUD {label}",
                       "crud_tests.sql", sec.strip())
                break

    # ---- 4. Security rules -------------------------------------------------
    print("Security rules...")
    sec_text = (REPO / "database" / "security_rules_demo.sql").read_text()
    sec_out = run_sql(sec_text, force=True)

    # Split into the rejection rules (1-10) and the positive evidence (11-13)
    parts = re.split(r"\n(?=--- RULE )", sec_out)
    reject, positive = [], []
    for p in parts:
        m = re.search(r"RULE (\d+)", p[:300])
        if not m:
            continue
        (reject if int(m.group(1)) <= 10 else positive).append(p.strip())

    if reject:
        render("09_security_constraint_rejections",
               "Terminal - security rules 1-10 (all rejections)",
               "run with mysql --force", "\n".join(reject))
    for p in positive:
        n = int(re.search(r"RULE (\d+)", p[:300]).group(1))
        label = {11: ("10_security_audit_trigger", "automatic audit trail"),
                 12: ("11_security_phone_masking", "PII masking view"),
                 13: ("12_security_grants", "least-privilege grants")}[n]
        render(label[0], f"Terminal - security rule {n}", label[1], p)

    # ---- 5. Live privilege enforcement ------------------------------------
    print("Privilege enforcement...")
    checks = [
        ('mysql -u momo_app -p -e "USE momo_sms_db; DELETE FROM transactions WHERE transaction_id=1;"',
         "momo_app", "ChangeMe_Str0ng!2026", "USE momo_sms_db; DELETE FROM transactions WHERE transaction_id=1;"),
        ('mysql -u momo_app -p -e "USE momo_sms_db; DROP TABLE system_logs;"',
         "momo_app", "ChangeMe_Str0ng!2026", "USE momo_sms_db; DROP TABLE system_logs;"),
        ('mysql -u momo_readonly -p -e "USE momo_sms_db; SELECT phone_number FROM users LIMIT 1;"',
         "momo_readonly", "ReadOnly_Str0ng!2026", "USE momo_sms_db; SELECT phone_number FROM users LIMIT 1;"),
        ('mysql -u momo_readonly -p -e "SELECT sender_name, sender_phone_masked FROM momo_sms_db.v_transaction_summary LIMIT 3;"',
         "momo_readonly", "ReadOnly_Str0ng!2026",
         "SELECT sender_name, sender_phone_masked FROM momo_sms_db.v_transaction_summary LIMIT 3;"),
    ]
    chunks = []
    for display, user, pw, sql in checks:
        out = run_sql(sql, user=user, pw=pw)
        chunks.append(f"$ {display}\n{out}")
    render("13_security_privilege_enforcement",
           "Terminal - least-privilege accounts enforced by the server",
           "ERROR 1142 = access denied", "\n\n".join(chunks))

    print(f"\nDone. {len(list(OUT.glob('*.png')))} screenshots in {OUT}")


if __name__ == "__main__":
    main()
