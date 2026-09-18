#!/usr/bin/env python3
"""
Generate the system architecture diagram as .drawio (editable), .svg and .png
from a single definition, so the three cannot drift apart.

Replaces the Week 1 diagram, which showed SQLite as the datastore and a
hand-written dashboard served by `python -m http.server`. Neither is true any
more: the database is MySQL and the dashboard is generated from it.
"""
import subprocess
import tempfile
import xml.sax.saxutils as sx
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs" / "architecture"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CANVAS_W, CANVAS_H = 1980, 1100

C = {
    "text": "#1A1F2B", "muted": "#5A6479", "line": "#44506A",
    "border": "#2E3A4F", "fill": "#FFFFFF",
    "group": "#F5F7FA", "group_border": "#C9D0DB",
    "store": "#40546E", "gen": "#7A4A2E", "gen_fill": "#FFF8F2",
    "bonus_border": "#9AA0B0",
}

# name: (x, y, w, h, kind, title, subtitle)
#   kind: proc | doc | store | group | note | gen | bonus
NODES = [
    ("etlgroup", 300, 96, 880, 190, "group", "ETL  ·  etl/run.py", ""),
    ("xml",       40, 143, 210, 96, "doc", "modified_sms_v2.xml",
     "data/raw/  ·  25 SMS records"),
    ("parse",    322, 152, 196, 74, "proc", "parse_xml.py", "read SMS records"),
    ("clean",    534, 152, 196, 74, "proc", "clean_normalize.py",
     "amounts, dates, 07→+250"),
    ("categ",    746, 152, 196, 74, "proc", "categorize.py",
     "10 category codes"),
    ("load",     958, 152, 202, 74, "proc", "load_db.py", "insert, dedupe"),

    ("mysql",   1310, 138, 250, 118, "store", "MySQL  ·  momo_sms_db",
     "7 tables · 3 views · 5 triggers"),

    ("logs",     322, 336, 420, 76, "note", "system_logs  +  data/logs/",
     "stage, event_type, level, ip_address"),

    ("views",   1300, 318, 270, 96, "proc", "Reporting views",
     "v_daily_summary · v_category_totals\nv_transaction_summary (PII masked)"),

    ("mkdash",  1270, 470, 330, 78, "gen", "make_dashboard.py",
     "queries the database"),
    ("dashhtml",1270, 606, 330, 92, "doc", "dashboard.html",
     "data/processed/ · self-contained"),
    ("browser", 1320, 762, 230, 70, "proc", "Browser", "opens the file directly"),

    ("api",     1660, 318, 280, 96, "bonus", "FastAPI  ·  api/",
     "/transactions  /analytics\nreads via momo_app (no DELETE)"),

    ("buildgrp",  40, 900, 1540, 162, "group",
     "Build-time  ·  scripts/build/   ·   documentation is generated, not hand-written", ""),
    ("mkerd",     70, 962, 300, 74, "gen", "make_erd.py",
     "→ docs/erd_diagram.drawio/.svg/.png"),
    ("mkshots",  390, 962, 300, 74, "gen", "make_screenshots.py",
     "runs every .sql, captures real output"),
    ("mkjson",   710, 962, 300, 74, "gen", "make_json.py",
     "→ examples/json_schemas.json"),
    ("mkdoc",   1030, 962, 300, 74, "gen", "make_doc.py",
     "→ database_design_document.pdf"),
    ("mkarch",  1350, 962, 210, 74, "gen", "make_architecture.py",
     "→ this diagram"),
]

# (from, from_side, to, to_side, label, dashed)
EDGES = [
    ("xml",   "right",  "parse",  "left",  "", False),
    ("parse", "right",  "clean",  "left",  "", False),
    ("clean", "right",  "categ",  "left",  "", False),
    ("categ", "right",  "load",   "left",  "", False),
    ("load",  "right",  "mysql",  "left",  "INSERT", False),
    ("parse", "bottom", "logs",   "top",   "errors", True),
    ("mysql", "bottom", "views",  "top",   "", False),
    ("views", "bottom", "mkdash", "top",   "SELECT", False),
    ("mkdash","bottom", "dashhtml","top",  "writes", False),
    ("dashhtml","bottom","browser","top",  "", False),
    ("views", "right",  "api",    "left",  "SELECT", True),
]

N = {n[0]: n for n in NODES}


def box(name):
    _, x, y, w, h, *_ = N[name]
    return x, y, w, h


def anchor(name, side):
    x, y, w, h = box(name)
    return {"left": (x, y + h / 2), "right": (x + w, y + h / 2),
            "top": (x + w / 2, y), "bottom": (x + w / 2, y + h)}[side]


# ===========================================================================
# SVG
# ===========================================================================
def svg_node(n):
    name, x, y, w, h, kind, title, sub = n
    out = []
    if kind == "group":
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" '
                   f'fill="{C["group"]}" stroke="{C["group_border"]}" '
                   f'stroke-width="1.6"/>')
        out.append(f'<text x="{x+16}" y="{y+26}" font-size="14" font-weight="700" '
                   f'fill="{C["muted"]}">{sx.escape(title)}</text>')
        return "".join(out)

    fill, stroke, tcol, dash = C["fill"], C["border"], C["text"], ""
    if kind == "store":
        fill, tcol = C["store"], "#FFFFFF"
    elif kind == "gen":
        fill, stroke = C["gen_fill"], C["gen"]
    elif kind == "note":
        dash = ' stroke-dasharray="6 4"'
    elif kind == "bonus":
        stroke, dash = C["bonus_border"], ' stroke-dasharray="6 4"'

    if kind == "doc":
        # document shape: wavy bottom edge
        out.append(f'<path d="M{x},{y} h{w} v{h-16} '
                   f'q{-w*0.25},14 {-w*0.5},0 q{-w*0.25},-14 {-w*0.5},0 z" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    elif kind == "store":
        out.append(f'<path d="M{x},{y+14} a{w/2},14 0 0 1 {w},0 v{h-28} '
                   f'a{w/2},14 0 0 1 {-w},0 z" fill="{fill}" stroke="{stroke}" '
                   f'stroke-width="2"/>')
        out.append(f'<path d="M{x},{y+14} a{w/2},14 0 0 0 {w},0" fill="none" '
                   f'stroke="#FFFFFF" stroke-opacity="0.45" stroke-width="1.5"/>')
    else:
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>')

    cx = x + w / 2
    ty = y + (46 if kind == "store" else 28)
    out.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="13.5" '
               f'font-weight="700" fill="{tcol}">{sx.escape(title)}</text>')
    scol = "#D7DCE5" if kind == "store" else C["muted"]
    for i, line in enumerate(sub.split("\n")) if sub else []:
        out.append(f'<text x="{cx}" y="{ty+18+i*14}" text-anchor="middle" '
                   f'font-size="10.8" fill="{scol}">{sx.escape(line)}</text>')
    return "".join(out)


def svg_edge(e):
    a, aside, b, bside, label, dashed = e
    ax, ay = anchor(a, aside)
    bx, by = anchor(b, bside)
    d = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}
    g = 8
    sx1, sy1 = ax + d[aside][0] * g, ay + d[aside][1] * g
    sx2, sy2 = bx + d[bside][0] * g, by + d[bside][1] * g

    if aside in ("left", "right") and bside in ("left", "right"):
        mx = (sx1 + sx2) / 2
        path = f"M{sx1},{sy1} L{mx},{sy1} L{mx},{sy2} L{sx2},{sy2}"
        lx, ly = mx, min(sy1, sy2) - 9
    elif aside in ("top", "bottom") and bside in ("top", "bottom"):
        my = (sy1 + sy2) / 2
        path = f"M{sx1},{sy1} L{sx1},{my} L{sx2},{my} L{sx2},{sy2}"
        lx, ly = (sx1 + sx2) / 2, my - 7
    else:
        path = f"M{sx1},{sy1} L{sx2},{sy1} L{sx2},{sy2}"
        lx, ly = (sx1 + sx2) / 2, sy1 - 9

    da = ' stroke-dasharray="6 4"' if dashed else ""
    out = [f'<path d="{path}" fill="none" stroke="{C["line"]}" stroke-width="1.7" '
           f'marker-end="url(#arrow)"{da}/>']
    if label:
        wpx = len(label) * 6.4 + 14
        out.append(f'<rect x="{lx-wpx/2:.1f}" y="{ly-11:.1f}" width="{wpx:.1f}" '
                   f'height="16" rx="4" fill="#FFFFFF" stroke="none"/>')
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                   f'font-size="10.5" font-weight="600" fill="{C["muted"]}">'
                   f'{sx.escape(label)}</text>')
    return "".join(out)


def build_svg():
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" '
         f'height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
         f'font-family="Helvetica,Arial,sans-serif">',
         f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
         f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         f'<path d="M0,1 L9,5 L0,9 z" fill="{C["line"]}"/></marker></defs>',
         f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#FFFFFF"/>',
         '<text x="44" y="48" font-size="26" font-weight="700" fill="#1A1F2B">'
         'MoMo SMS Analytics &#183; System Architecture</text>',
         '<text x="44" y="74" font-size="13" fill="#5A6479">'
         'Python + SQL &#183; MySQL 8.0+ / InnoDB &#183; Clive Tanaka Mushipe</text>']

    for n in NODES:
        if n[5] == "group":
            p.append(svg_node(n))
    for e in EDGES:
        p.append(svg_edge(e))
    for n in NODES:
        if n[5] != "group":
            p.append(svg_node(n))

    # legend
    lx, ly = 1660, 470
    p.append(f'<rect x="{lx}" y="{ly}" width="280" height="300" rx="8" '
             f'fill="#FAFBFC" stroke="{C["group_border"]}" stroke-width="1.5"/>')
    p.append(f'<text x="{lx+16}" y="{ly+26}" font-size="13.5" font-weight="700" '
             f'fill="{C["text"]}">Legend</text>')
    items = [(C["fill"], C["border"], "solid", "Runtime component"),
             (C["store"], C["store"], "solid", "Datastore"),
             (C["gen_fill"], C["gen"], "solid", "Generator script"),
             (C["fill"], C["bonus_border"], "dash", "Optional / bonus"),
             (C["fill"], C["border"], "dash", "Error path")]
    yy = ly + 52
    for fill, stroke, style in [(i[0], i[1], i[2]) for i in items]:
        pass
    for i, (fill, stroke, style, text) in enumerate(items):
        da = ' stroke-dasharray="4 3"' if style == "dash" else ""
        p.append(f'<rect x="{lx+18}" y="{yy-11}" width="26" height="15" rx="3" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.6"{da}/>')
        p.append(f'<text x="{lx+54}" y="{yy}" font-size="11" fill="#3C4659">'
                 f'{sx.escape(text)}</text>')
        yy += 26

    yy += 10
    note = ["There is no hand-written frontend.",
            "The dashboard is generated from the",
            "database by a Python script, so the",
            "source of this project stays Python",
            "and SQL only. Generated artefacts are",
            "marked linguist-generated so they do",
            "not distort the language statistics."]
    for i, line in enumerate(note):
        p.append(f'<text x="{lx+18}" y="{yy+i*15}" font-size="10.5" '
                 f'fill="{C["muted"]}">{sx.escape(line)}</text>')

    p.append('</svg>')
    return "\n".join(p)


# ===========================================================================
# draw.io
# ===========================================================================
STYLE = {
    "proc": "rounded=1;arcSize=8;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
            "strokeColor=#2E3A4F;fontColor=#1A1F2B;fontFamily=Helvetica;",
    "doc": "shape=document;boundedLbl=1;size=0.15;whiteSpace=wrap;html=1;"
           "fillColor=#FFFFFF;strokeColor=#2E3A4F;fontColor=#1A1F2B;fontFamily=Helvetica;",
    "store": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=12;whiteSpace=wrap;"
             "html=1;fillColor=#40546E;strokeColor=#2E3A4F;fontColor=#FFFFFF;fontFamily=Helvetica;",
    "note": "rounded=1;arcSize=8;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
            "strokeColor=#2E3A4F;fontColor=#1A1F2B;fontFamily=Helvetica;dashed=1;",
    "gen": "rounded=1;arcSize=8;whiteSpace=wrap;html=1;fillColor=#FFF8F2;"
           "strokeColor=#7A4A2E;fontColor=#1A1F2B;fontFamily=Helvetica;",
    "bonus": "rounded=1;arcSize=8;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
             "strokeColor=#9AA0B0;fontColor=#1A1F2B;fontFamily=Helvetica;dashed=1;",
    "group": "rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor=#F5F7FA;"
             "strokeColor=#C9D0DB;fontColor=#5A6479;fontFamily=Helvetica;"
             "verticalAlign=top;align=left;spacingLeft=12;spacingTop=4;",
}


def build_drawio():
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    cells.append(
        '<mxCell id="title" value="&lt;b&gt;MoMo SMS Analytics - System Architecture&lt;/b&gt;" '
        'style="text;html=1;align=left;verticalAlign=middle;fontSize=22;fontColor=#1A1F2B;'
        'fontFamily=Helvetica;" vertex="1" parent="1">'
        '<mxGeometry x="44" y="24" width="900" height="34" as="geometry"/></mxCell>')
    cells.append(
        '<mxCell id="sub" value="Python + SQL &#183; MySQL 8.0+ / InnoDB &#183; Clive Tanaka Mushipe" '
        'style="text;html=1;align=left;verticalAlign=middle;fontSize=12;fontColor=#5A6479;'
        'fontFamily=Helvetica;" vertex="1" parent="1">'
        '<mxGeometry x="44" y="58" width="900" height="22" as="geometry"/></mxCell>')

    for name, x, y, w, h, kind, title, sub in NODES:
        label = f"<b>{sx.escape(title)}</b>"
        if sub:
            label += "<br/>" + "<br/>".join(
                f'<span style="font-size:10px">{sx.escape(l)}</span>'
                for l in sub.split("\n"))
        # The label is HTML going inside an XML attribute, and that HTML
        # contains its own double quotes (style="..."). sx.escape does not
        # escape quotes by default, so they must be handled explicitly or the
        # attribute terminates early and the file is not well-formed XML.
        label_attr = sx.escape(label, {'"': "&quot;"})
        cells.append(
            f'<mxCell id="{name}" value="{label_attr}" style="{STYLE[kind]}" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')

    ex = {"left": (0, 0.5), "right": (1, 0.5), "top": (0.5, 0), "bottom": (0.5, 1)}
    for i, (a, aside, b, bside, label, dashed) in enumerate(EDGES):
        x1, y1 = ex[aside]
        x2, y2 = ex[bside]
        cells.append(
            f'<mxCell id="e{i}" value="{sx.escape(label)}" '
            f'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=classic;'
            f'strokeColor=#44506A;fontSize=10;fontColor=#5A6479;'
            f'labelBackgroundColor=#FFFFFF;fontFamily=Helvetica;'
            f'{"dashed=1;" if dashed else ""}'
            f'exitX={x1};exitY={y1};exitDx=0;exitDy=0;entryX={x2};entryY={y2};'
            f'entryDx=0;entryDy=0;" edge="1" parent="1" source="{a}" target="{b}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>')

    legend = (
        "LEGEND&#10;&#10;"
        "Solid box      runtime component&#10;"
        "Dark cylinder  datastore&#10;"
        "Orange box     generator script&#10;"
        "Dashed         optional / error path&#10;&#10;"
        "There is no hand-written frontend. The&#10;"
        "dashboard is generated from the database&#10;"
        "by a Python script, so the source of this&#10;"
        "project stays Python and SQL only."
    )
    cells.append(
        f'<mxCell id="legend" value="{legend}" '
        f'style="text;html=1;align=left;verticalAlign=top;spacingLeft=12;spacingTop=8;'
        f'fillColor=#FAFBFC;strokeColor=#C9D0DB;fontSize=11;fontColor=#3C4659;'
        f'fontFamily=Helvetica;whiteSpace=wrap;" vertex="1" parent="1">'
        f'<mxGeometry x="1660" y="470" width="280" height="300" as="geometry"/></mxCell>')

    return ('<mxfile host="app.diagrams.net">\n'
            '  <diagram id="momo-architecture" name="System Architecture">\n'
            f'    <mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" '
            f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="{CANVAS_W}" pageHeight="{CANVAS_H}" math="0" shadow="0">\n'
            '      <root>' + "".join(cells) + '</root>\n'
            '    </mxGraphModel>\n  </diagram>\n</mxfile>\n')


def main():
    DOCS.mkdir(parents=True, exist_ok=True)

    svg = build_svg()
    (DOCS / "system_architecture.svg").write_text(svg, encoding="utf-8")
    print(f"wrote system_architecture.svg ({len(svg)} bytes)")

    dio = build_drawio()
    (DOCS / "system_architecture.drawio").write_text(dio, encoding="utf-8")
    print(f"wrote system_architecture.drawio ({len(dio)} bytes)")

    with tempfile.TemporaryDirectory(prefix="momo-arch-") as tmp:
        holder = Path(tmp) / "holder.html"
        holder.write_text(
            f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<style>html,body{{margin:0;padding:0;background:#fff;}}</style>'
            f'</head><body>{svg}</body></html>', encoding="utf-8")
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
             f"--screenshot={DOCS / 'system_architecture.png'}",
             f"--window-size={CANVAS_W},{CANVAS_H}",
             "--force-device-scale-factor=2", holder.as_uri()],
            check=True, capture_output=True)
    print("wrote system_architecture.png")


if __name__ == "__main__":
    main()
