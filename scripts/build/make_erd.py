#!/usr/bin/env python3
"""
Generate the MoMo SMS ERD as .drawio (editable), .svg and .png from a single
schema definition, so the three can never drift apart.

Crow's-foot notation. PK/FK/UK marked. Junction tables highlighted.
"""
import html
import subprocess
import xml.sax.saxutils as sx
from pathlib import Path

REPO = Path("/Users/mac/Desktop/Database_Design_and_Implementation")
DOCS = REPO / "docs"
TMP = Path(__file__).parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# ---------------------------------------------------------------------------
# Schema definition: (name, x, y, width, kind, [(key, column, type), ...])
# key: PK | FK | PFK (both) | UK | ''
# kind: entity | junction | lookup
# ---------------------------------------------------------------------------
ROW_H = 21
HEAD_H = 34
TITLE_H = 0

TABLES = [
    ("transaction_categories", 1120, 70, 400, "lookup", [
        ("PK", "category_id",   "SMALLINT UNSIGNED"),
        ("UK", "category_code", "VARCHAR(40)"),
        ("UK", "category_name", "VARCHAR(80)"),
        ("",   "direction",     "ENUM(credit/debit/neutral)"),
        ("",   "description",   "VARCHAR(255)"),
        ("",   "is_active",     "BOOLEAN"),
        ("",   "created_at",    "DATETIME"),
    ]),
    ("users", 40, 455, 390, "entity", [
        ("PK", "user_id",        "INT UNSIGNED"),
        ("",   "full_name",      "VARCHAR(120)"),
        ("UK", "phone_number",   "VARCHAR(16)"),
        ("",   "user_type",      "ENUM(customer/merchant/agent/bank/system)"),
        ("",   "national_id",    "VARCHAR(32)  NULL"),
        ("",   "account_status", "ENUM(active/suspended/closed)"),
        ("",   "first_seen_at",  "DATETIME"),
        ("",   "created_at",     "DATETIME"),
        ("",   "updated_at",     "DATETIME"),
    ]),
    ("transaction_participants", 580, 480, 380, "junction", [
        ("PK",  "participation_id", "BIGINT UNSIGNED"),
        ("FK",  "transaction_id",   "BIGINT UNSIGNED"),
        ("FK",  "user_id",          "INT UNSIGNED"),
        ("",    "role",             "ENUM(sender/receiver)"),
        ("",    "party_label",      "VARCHAR(120) NULL"),
        ("",    "created_at",       "DATETIME"),
    ]),
    ("transactions", 1110, 430, 420, "entity", [
        ("PK", "transaction_id",   "BIGINT UNSIGNED"),
        ("UK", "external_txn_ref", "VARCHAR(40)"),
        ("FK", "category_id",      "SMALLINT UNSIGNED"),
        ("",   "amount",           "DECIMAL(15,2)"),
        ("",   "fee",              "DECIMAL(15,2)"),
        ("",   "balance_after",    "DECIMAL(15,2) NULL"),
        ("",   "currency",         "CHAR(3)"),
        ("",   "transaction_date", "DATETIME"),
        ("",   "status",           "ENUM(pending/completed/failed/reversed)"),
        ("",   "channel",          "ENUM(sms/ussd/app/api)"),
        ("",   "raw_sms_body",     "TEXT"),
        ("UK", "sms_hash",         "CHAR(64)"),
        ("",   "processed_at",     "DATETIME"),
        ("",   "created_at",       "DATETIME"),
        ("",   "updated_at",       "DATETIME"),
    ]),
    ("transaction_tags", 1680, 480, 370, "junction", [
        ("PFK", "transaction_id", "BIGINT UNSIGNED"),
        ("PFK", "tag_id",         "SMALLINT UNSIGNED"),
        ("",    "confidence",     "DECIMAL(3,2)"),
        ("",    "tagged_by",      "ENUM(etl/analyst/rule_engine)"),
        ("",    "tagged_at",      "DATETIME"),
    ]),
    ("tags", 2200, 490, 350, "lookup", [
        ("PK", "tag_id",      "SMALLINT UNSIGNED"),
        ("UK", "tag_name",    "VARCHAR(50)"),
        ("",   "tag_type",    "ENUM(analytics/data_quality/user_defined)"),
        ("",   "description", "VARCHAR(255) NULL"),
        ("",   "created_at",  "DATETIME"),
    ]),
    ("system_logs", 1110, 900, 420, "entity", [
        ("PK", "log_id",           "BIGINT UNSIGNED"),
        ("FK", "transaction_id",   "BIGINT UNSIGNED NULL"),
        ("",   "stage",            "ENUM(parse/clean/categorize/load/export/audit)"),
        ("",   "log_level",        "ENUM(DEBUG/INFO/WARNING/ERROR/CRITICAL)"),
        ("",   "message",          "VARCHAR(500)"),
        ("",   "source_file",      "VARCHAR(255) NULL"),
        ("",   "record_ref",       "VARCHAR(100) NULL"),
        ("",   "records_affected", "INT UNSIGNED"),
        ("",   "created_at",       "DATETIME"),
    ]),
]

TBL = {t[0]: t for t in TABLES}


def height(name):
    return HEAD_H + len(TBL[name][5]) * ROW_H


def box(name):
    _, x, y, w, _, cols = TBL[name]
    return x, y, w, height(name)


# ---------------------------------------------------------------------------
# Relationships: (from_table, from_side, to_table, to_side, from_card, to_card,
#                 label, on_delete)
# card: '1' or 'M'
# ---------------------------------------------------------------------------
RELS = [
    ("transaction_categories", "bottom", "transactions", "top", "1", "M",
     "classifies", "RESTRICT"),
    ("users", "right", "transaction_participants", "left", "1", "M",
     "participates as", "RESTRICT"),
    ("transactions", "left", "transaction_participants", "right", "1", "M",
     "has parties", "CASCADE"),
    ("transactions", "right", "transaction_tags", "left", "1", "M",
     "carries", "CASCADE"),
    ("tags", "left", "transaction_tags", "right", "1", "M",
     "applied to", "CASCADE"),
    ("transactions", "bottom", "system_logs", "top", "1", "M",
     "logged by", "SET NULL"),
]

CANVAS_W, CANVAS_H = 2660, 1230

# --------------------------------------------------------------------------
# Colours - professional, print-safe, readable in greyscale
# --------------------------------------------------------------------------
C = {
    "entity_head": "#2E3A4F",
    "lookup_head": "#40546E",
    "junction_head": "#7A4A2E",
    "body": "#FFFFFF",
    "alt": "#F7F8FA",
    "border": "#2E3A4F",
    "junction_border": "#7A4A2E",
    "text": "#1A1F2B",
    "type": "#5A6479",
    "key": "#9A6B00",
    "line": "#44506A",
    "label": "#3C4659",
}


def head_fill(kind):
    return {"entity": C["entity_head"], "lookup": C["lookup_head"],
            "junction": C["junction_head"]}[kind]


def border_of(kind):
    return C["junction_border"] if kind == "junction" else C["border"]


# ===========================================================================
# SVG generation
# ===========================================================================
def anchor(name, side):
    x, y, w, h = box(name)
    return {
        "left":   (x, y + h / 2),
        "right":  (x + w, y + h / 2),
        "top":    (x + w / 2, y),
        "bottom": (x + w / 2, y + h),
    }[side]


def crowsfoot(px, py, side, size=13):
    """Three-pronged 'many' marker pointing into the table at (px,py)."""
    d = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}[side]
    # base point sits `size` away from the table edge, outside it
    bx, by = px + d[0] * size, py + d[1] * size
    spread = 8
    if d[0]:  # horizontal
        pts = [(px, py - spread), (px, py), (px, py + spread)]
    else:     # vertical
        pts = [(px - spread, py), (px, py), (px + spread, py)]
    return "".join(
        f'<line x1="{bx:.1f}" y1="{by:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
        f'stroke="{C["line"]}" stroke-width="1.6" stroke-linecap="round"/>'
        for ex, ey in pts
    )


def one_tick(px, py, side, size=13):
    """Single perpendicular bar = the 'one' end."""
    d = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}[side]
    bx, by = px + d[0] * size, py + d[1] * size
    if d[0]:
        return (f'<line x1="{bx:.1f}" y1="{by-8:.1f}" x2="{bx:.1f}" y2="{by+8:.1f}" '
                f'stroke="{C["line"]}" stroke-width="1.8" stroke-linecap="round"/>')
    return (f'<line x1="{bx-8:.1f}" y1="{by:.1f}" x2="{bx+8:.1f}" y2="{by:.1f}" '
            f'stroke="{C["line"]}" stroke-width="1.8" stroke-linecap="round"/>')


def svg_table(name):
    tname, x, y, w, kind, cols = TBL[name]
    h = height(name)
    b = border_of(kind)
    out = [f'<g>']
    # shadow + frame
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" '
               f'fill="{C["body"]}" stroke="{b}" stroke-width="2"/>')
    # header
    out.append(f'<path d="M{x},{y+7} a7,7 0 0 1 7,-7 h{w-14} a7,7 0 0 1 7,7 '
               f'v{HEAD_H-7} h{-w} z" fill="{head_fill(kind)}"/>')
    label = tname
    out.append(f'<text x="{x+14}" y="{y+22}" font-family="Helvetica,Arial,sans-serif" '
               f'font-size="15" font-weight="700" fill="#FFFFFF">{sx.escape(label)}</text>')
    if kind == "junction":
        out.append(f'<text x="{x+w-14}" y="{y+22}" text-anchor="end" '
                   f'font-family="Helvetica,Arial,sans-serif" font-size="10.5" '
                   f'font-weight="700" fill="#F2C9A8" letter-spacing="0.6">JUNCTION</text>')
    # rows
    for i, (key, col, typ) in enumerate(cols):
        ry = y + HEAD_H + i * ROW_H
        if i % 2 == 1:
            out.append(f'<rect x="{x+2}" y="{ry}" width="{w-4}" height="{ROW_H}" '
                       f'fill="{C["alt"]}"/>')
        # key badge
        if key:
            out.append(f'<text x="{x+12}" y="{ry+14.5}" font-family="Helvetica,Arial,sans-serif" '
                       f'font-size="9.5" font-weight="700" fill="{C["key"]}">{key}</text>')
        weight = "700" if "PK" in key or key == "PFK" else "400"
        deco = ' text-decoration="underline"' if ("PK" in key) else ""
        out.append(f'<text x="{x+46}" y="{ry+14.5}" font-family="Helvetica,Arial,sans-serif" '
                   f'font-size="11.5" font-weight="{weight}" fill="{C["text"]}"{deco}>'
                   f'{sx.escape(col)}</text>')
        out.append(f'<text x="{x+w-12}" y="{ry+14.5}" text-anchor="end" '
                   f'font-family="Helvetica,Arial,sans-serif" font-size="9.8" '
                   f'fill="{C["type"]}">{sx.escape(typ)}</text>')
    out.append('</g>')
    return "".join(out)


def svg_rel(rel):
    a, aside, bt, bside, acard, bcard, label, ondel = rel
    ax, ay = anchor(a, aside)
    bx, by = anchor(bt, bside)
    gap = 13
    da = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}[aside]
    db = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}[bside]
    sx1, sy1 = ax + da[0] * gap, ay + da[1] * gap
    sx2, sy2 = bx + db[0] * gap, by + db[1] * gap

    # orthogonal routing through the midpoint
    if aside in ("left", "right") and bside in ("left", "right"):
        mx = (sx1 + sx2) / 2
        path = f"M{sx1},{sy1} L{mx},{sy1} L{mx},{sy2} L{sx2},{sy2}"
        lx, ly = mx, (sy1 + sy2) / 2 - 8
    elif aside in ("top", "bottom") and bside in ("top", "bottom"):
        my = (sy1 + sy2) / 2
        path = f"M{sx1},{sy1} L{sx1},{my} L{sx2},{my} L{sx2},{sy2}"
        lx, ly = (sx1 + sx2) / 2, my - 8
    else:
        path = f"M{sx1},{sy1} L{sx2},{sy1} L{sx2},{sy2}"
        lx, ly = sx2, sy1 - 8

    out = [f'<path d="{path}" fill="none" stroke="{C["line"]}" stroke-width="1.6"/>']
    out.append(crowsfoot(ax, ay, aside) if acard == "M" else one_tick(ax, ay, aside))
    out.append(crowsfoot(bx, by, bside) if bcard == "M" else one_tick(bx, by, bside))

    text = f"{acard} : {bcard}"
    tw = max(len(label), len(text)) * 6.2 + 18
    out.append(f'<rect x="{lx-tw/2:.1f}" y="{ly-13:.1f}" width="{tw:.1f}" height="30" '
               f'rx="5" fill="#FFFFFF" stroke="#D5DAE3" stroke-width="1"/>')
    out.append(f'<text x="{lx:.1f}" y="{ly-1:.1f}" text-anchor="middle" '
               f'font-family="Helvetica,Arial,sans-serif" font-size="10.5" '
               f'font-weight="700" fill="{C["label"]}">{sx.escape(text)}</text>')
    out.append(f'<text x="{lx:.1f}" y="{ly+11:.1f}" text-anchor="middle" '
               f'font-family="Helvetica,Arial,sans-serif" font-size="9.2" '
               f'fill="{C["type"]}">{sx.escape(label)}</text>')
    return "".join(out)


def build_svg():
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" '
         f'height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
         f'font-family="Helvetica,Arial,sans-serif">']
    p.append(f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#FFFFFF"/>')

    # title block
    p.append('<text x="50" y="46" font-size="26" font-weight="700" fill="#1A1F2B">'
             'MoMo SMS Analytics &#8212; Entity Relationship Diagram</text>')
    p.append('<text x="50" y="72" font-size="13" fill="#5A6479">'
             'MySQL 8.0+ / InnoDB &#183; Crow&#8217;s-foot notation &#183; '
             'Clive Tanaka Mushipe &#183; Week 2</text>')

    for r in RELS:
        p.append(svg_rel(r))
    for t in TABLES:
        p.append(svg_table(t[0]))

    # --- legend ---
    lx, ly = 40, 880
    p.append(f'<rect x="{lx}" y="{ly}" width="400" height="286" rx="8" '
             f'fill="#FAFBFC" stroke="#D5DAE3" stroke-width="1.5"/>')
    p.append(f'<text x="{lx+16}" y="{ly+26}" font-size="13.5" font-weight="700" '
             f'fill="#1A1F2B">Legend</text>')
    items = [
        ("PK", "Primary key (underlined)"),
        ("FK", "Foreign key"),
        ("UK", "Unique key / natural key"),
        ("PFK", "Part of composite PK and a foreign key"),
    ]
    yy = ly + 50
    for k, desc in items:
        p.append(f'<text x="{lx+18}" y="{yy}" font-size="10" font-weight="700" '
                 f'fill="{C["key"]}">{k}</text>')
        p.append(f'<text x="{lx+58}" y="{yy}" font-size="11" fill="#3C4659">{desc}</text>')
        yy += 21

    yy += 6
    p.append(f'<rect x="{lx+18}" y="{yy-10}" width="26" height="13" rx="3" '
             f'fill="{C["junction_head"]}"/>')
    p.append(f'<text x="{lx+54}" y="{yy}" font-size="11" fill="#3C4659">'
             f'Junction table resolving an M:N relationship</text>')
    yy += 22
    p.append(f'<rect x="{lx+18}" y="{yy-10}" width="26" height="13" rx="3" '
             f'fill="{C["entity_head"]}"/>')
    p.append(f'<text x="{lx+54}" y="{yy}" font-size="11" fill="#3C4659">Core entity</text>')
    yy += 22
    p.append(f'<rect x="{lx+18}" y="{yy-10}" width="26" height="13" rx="3" '
             f'fill="{C["lookup_head"]}"/>')
    p.append(f'<text x="{lx+54}" y="{yy}" font-size="11" fill="#3C4659">Lookup table</text>')

    # crow's foot key
    yy += 30
    p.append(f'<line x1="{lx+18}" y1="{yy}" x2="{lx+56}" y2="{yy}" '
             f'stroke="{C["line"]}" stroke-width="1.6"/>')
    p.append(f'<line x1="{lx+56}" y1="{yy-8}" x2="{lx+56}" y2="{yy+8}" '
             f'stroke="{C["line"]}" stroke-width="1.8"/>')
    p.append(f'<text x="{lx+70}" y="{yy+4}" font-size="11" fill="#3C4659">'
             f'&#8220;exactly one&#8221;</text>')
    yy += 26
    p.append(f'<line x1="{lx+18}" y1="{yy}" x2="{lx+56}" y2="{yy}" '
             f'stroke="{C["line"]}" stroke-width="1.6"/>')
    for dy in (-8, 0, 8):
        p.append(f'<line x1="{lx+56}" y1="{yy}" x2="{lx+68}" y2="{yy+dy}" '
                 f'stroke="{C["line"]}" stroke-width="1.6"/>')
    p.append(f'<text x="{lx+82}" y="{yy+4}" font-size="11" fill="#3C4659">'
             f'&#8220;zero or many&#8221;</text>')

    # --- M:N callout ---
    cx, cy = 1900, 880
    p.append(f'<rect x="{cx}" y="{cy}" width="700" height="286" rx="8" '
             f'fill="#FFF8F2" stroke="{C["junction_border"]}" stroke-width="1.5"/>')
    p.append(f'<text x="{cx+18}" y="{cy+28}" font-size="13.5" font-weight="700" '
             f'fill="{C["junction_head"]}">Many-to-many relationships, resolved</text>')
    lines = [
        ("1.  users  M:N  transactions", True),
        ("     A user takes part in many transactions; a transaction involves", False),
        ("     many users (a sender and a receiver). Resolved by", False),
        ("     transaction_participants, which qualifies each link with a role.", False),
        ("", False),
        ("2.  transactions  M:N  tags", True),
        ("     A transaction carries many tags; a tag is applied to many", False),
        ("     transactions. Resolved by transaction_tags, whose composite PK", False),
        ("     (transaction_id, tag_id) also carries the relationship's own", False),
        ("     attributes: confidence and tagged_by.", False),
    ]
    ty = cy + 54
    for text, bold in lines:
        if text:
            p.append(f'<text x="{cx+18}" y="{ty}" font-size="11.5" '
                     f'font-weight="{"700" if bold else "400"}" '
                     f'fill="#3C4659">{sx.escape(text)}</text>')
        ty += 21

    p.append('</svg>')
    return "\n".join(p)


# ===========================================================================
# draw.io generation
# ===========================================================================
def build_drawio():
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    cells.append(
        '<mxCell id="title" value="&lt;b&gt;MoMo SMS Analytics - Entity Relationship Diagram&lt;/b&gt;" '
        'style="text;html=1;align=left;verticalAlign=middle;fontSize=22;fontColor=#1A1F2B;fontFamily=Helvetica;" '
        'vertex="1" parent="1"><mxGeometry x="50" y="20" width="900" height="34" as="geometry"/></mxCell>')
    cells.append(
        '<mxCell id="subtitle" value="MySQL 8.0+ / InnoDB &#183; Crow&#39;s-foot notation &#183; Clive Tanaka Mushipe" '
        'style="text;html=1;align=left;verticalAlign=middle;fontSize=12;fontColor=#5A6479;fontFamily=Helvetica;" '
        'vertex="1" parent="1"><mxGeometry x="50" y="56" width="900" height="22" as="geometry"/></mxCell>')

    for tname, x, y, w, kind, cols in TABLES:
        h = HEAD_H + len(cols) * ROW_H
        hid = f"t_{tname}"
        title = tname + ("  [JUNCTION]" if kind == "junction" else "")
        cells.append(
            f'<mxCell id="{hid}" value="{sx.escape(title)}" '
            f'style="swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;startSize={HEAD_H};'
            f'horizontalStack=0;resizeParent=1;resizeParentMax=0;html=1;verticalAlign=middle;'
            f'align=center;fillColor={head_fill(kind)};fontColor=#FFFFFF;'
            f'strokeColor={border_of(kind)};fontSize=14;fontFamily=Helvetica;swimlaneFillColor=#FFFFFF;" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        for i, (key, col, typ) in enumerate(cols):
            prefix = f"{key}  " if key else ""
            val = f"{prefix}{col} : {typ}"
            bold = ";fontStyle=1" if "PK" in key else ""
            cells.append(
                f'<mxCell id="{hid}_c{i}" value="{sx.escape(val)}" '
                f'style="text;html=1;strokeColor=none;fillColor=none;align=left;'
                f'verticalAlign=middle;spacingLeft=8;spacingRight=6;overflow=hidden;'
                f'fontSize=11;fontColor=#1A1F2B;fontFamily=Helvetica{bold};" '
                f'vertex="1" parent="{hid}">'
                f'<mxGeometry y="{HEAD_H + i*ROW_H}" width="{w}" height="{ROW_H}" as="geometry"/></mxCell>')

    exits = {"left": (0, 0.5), "right": (1, 0.5), "top": (0.5, 0), "bottom": (0.5, 1)}
    for i, (a, aside, bt, bside, acard, bcard, label, ondel) in enumerate(RELS):
        ex, ey = exits[aside]
        nx, ny = exits[bside]
        # ERone / ERmany terminals give true crow's-foot rendering in draw.io
        start = "ERone" if acard == "1" else "ERmany"
        end = "ERone" if bcard == "1" else "ERmany"
        cells.append(
            f'<mxCell id="rel{i}" value="{sx.escape(label + "  (" + acard + ":" + bcard + ")")}" '
            f'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;startArrow={start};'
            f'startFill=0;endArrow={end};endFill=0;strokeColor=#44506A;fontSize=10;'
            f'fontColor=#3C4659;labelBackgroundColor=#FFFFFF;fontFamily=Helvetica;'
            f'exitX={ex};exitY={ey};exitDx=0;exitDy=0;entryX={nx};entryY={ny};entryDx=0;entryDy=0;" '
            f'edge="1" parent="1" source="t_{a}" target="t_{bt}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>')

    note = (
        "M:N RELATIONSHIPS RESOLVED&#10;&#10;"
        "1. users M:N transactions -&gt; transaction_participants&#10;"
        "   A user takes part in many transactions; a transaction&#10;"
        "   involves many users. The junction qualifies each link&#10;"
        "   with a role (sender / receiver).&#10;&#10;"
        "2. transactions M:N tags -&gt; transaction_tags&#10;"
        "   Composite PK (transaction_id, tag_id) plus the&#10;"
        "   relationship's own attributes: confidence, tagged_by."
    )
    cells.append(
        f'<mxCell id="note" value="{note}" '
        f'style="text;html=1;align=left;verticalAlign=top;spacingLeft=12;spacingTop=8;'
        f'fillColor=#FFF8F2;strokeColor=#7A4A2E;fontSize=11;fontColor=#3C4659;'
        f'fontFamily=Helvetica;whiteSpace=wrap;" vertex="1" parent="1">'
        f'<mxGeometry x="1900" y="880" width="700" height="240" as="geometry"/></mxCell>')

    legend = (
        "LEGEND&#10;&#10;"
        "PK   Primary key&#10;"
        "FK   Foreign key&#10;"
        "UK   Unique / natural key&#10;"
        "PFK  Composite PK member that is also a FK&#10;&#10;"
        "Crow's foot = &quot;many&quot;   |   Single bar = &quot;one&quot;"
    )
    cells.append(
        f'<mxCell id="legend" value="{legend}" '
        f'style="text;html=1;align=left;verticalAlign=top;spacingLeft=12;spacingTop=8;'
        f'fillColor=#FAFBFC;strokeColor=#D5DAE3;fontSize=11;fontColor=#3C4659;'
        f'fontFamily=Helvetica;whiteSpace=wrap;" vertex="1" parent="1">'
        f'<mxGeometry x="40" y="880" width="400" height="200" as="geometry"/></mxCell>')

    return (
        '<mxfile host="app.diagrams.net">\n'
        '  <diagram id="momo-erd" name="MoMo SMS ERD">\n'
        f'    <mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" '
        f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{CANVAS_W}" pageHeight="{CANVAS_H}" math="0" shadow="0">\n'
        '      <root>' + "".join(cells) + '</root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>\n'
        '</mxfile>\n'
    )


def main():
    DOCS.mkdir(exist_ok=True)

    svg = build_svg()
    (DOCS / "erd_diagram.svg").write_text(svg, encoding="utf-8")
    print(f"wrote erd_diagram.svg ({len(svg)} bytes)")

    dio = build_drawio()
    (DOCS / "erd_diagram.drawio").write_text(dio, encoding="utf-8")
    print(f"wrote erd_diagram.drawio ({len(dio)} bytes)")

    # PNG via headless Chrome at 2x for a crisp print.
    holder = TMP / "erd_holder.html"
    holder.write_text(
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<style>html,body{{margin:0;padding:0;background:#fff;}}</style></head>'
        f'<body>{svg}</body></html>', encoding="utf-8")
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
         f"--screenshot={DOCS / 'erd_diagram.png'}",
         f"--window-size={CANVAS_W},{CANVAS_H}",
         "--force-device-scale-factor=2", holder.as_uri()],
        check=True, capture_output=True)
    print("wrote erd_diagram.png")


if __name__ == "__main__":
    main()
