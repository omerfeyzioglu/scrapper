"""
report.py — Convert any crawler .jsonl output into a clean HTML report.

Usage:
    python report.py out.jsonl
    python report.py out_resmi.jsonl           -> opens out_resmi.html
    python report.py out.jsonl -o report.html  -> custom output path
"""

import argparse
import html
import json
import os
import sys
import webbrowser
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _e(text) -> str:
    """HTML-escape and convert to string."""
    return html.escape(str(text or ""), quote=True)


def _badge(rtype: str) -> str:
    colours = {
        "html":              "#2563eb",
        "external_redirect": "#d97706",
        "asset":             "#7c3aed",
    }
    bg = colours.get(rtype, "#6b7280")
    return f'<span class="badge" style="background:{bg}">{_e(rtype.upper())}</span>'


def _row(label: str, value: str, mono: bool = False) -> str:
    cls = ' class="mono"' if mono else ""
    return f'<tr><th>{_e(label)}</th><td{cls}>{value}</td></tr>'


def _collapsible(label: str, content: str, open_: bool = False) -> str:
    attr = " open" if open_ else ""
    return (
        f'<details{attr}><summary>{_e(label)}</summary>'
        f'<pre class="pre-wrap">{_e(content)}</pre></details>'
    )


# ── record renderers ──────────────────────────────────────────────────────────

def _render_html_record(i: int, r: dict) -> str:
    title  = r.get("title", "")
    date   = r.get("date", "")
    txt    = r.get("extracted_text", "")
    tbls   = r.get("tables", [])
    clinks = r.get("content_links_sample", [])
    alinks = r.get("all_links_sample", [])

    rows = [
        _row("URL",    f'<a href="{_e(r.get("url",""))}" target="_blank">{_e(r.get("url",""))}</a>'),
        _row("Status", _e(r.get("status"))),
        _row("Title",  _e(title) or "<em>(missing)</em>"),
        _row("Date",   _e(date)  or "<em>(missing)</em>"),
        _row("Text length", f"{len(txt):,} chars"),
        _row("Links", f"content {len(clinks)} &nbsp;|&nbsp; all {len(alinks)}"),
    ]
    detail_parts = []
    if txt:
        detail_parts.append(_collapsible(f"Extracted text ({len(txt):,} chars)", txt))
    if tbls:
        tbl_summary = "\n\n".join(
            f"Table {ti+1}\n  headers: {t.get('headers')}\n  rows: {t.get('rows')}"
            for ti, t in enumerate(tbls)
        )
        detail_parts.append(_collapsible(f"Tables ({len(tbls)})", tbl_summary))
    if alinks:
        detail_parts.append(_collapsible(f"All links sample ({len(alinks)})", "\n".join(alinks)))

    return _card(i, "html", r.get("status"), rows, detail_parts)


def _render_redirect_record(i: int, r: dict) -> str:
    rows = [
        _row("From",   f'<a href="{_e(r.get("url",""))}" target="_blank">{_e(r.get("url",""))}</a>'),
        _row("To",     f'<a href="{_e(r.get("final_url",""))}" target="_blank">{_e(r.get("final_url",""))}</a>'),
        _row("Status", _e(r.get("status"))),
    ]
    return _card(i, "external_redirect", r.get("status"), rows, [])


def _render_asset_record(i: int, r: dict) -> str:
    rows = [
        _row("URL",          f'<a href="{_e(r.get("url",""))}" target="_blank">{_e(r.get("url",""))}</a>'),
        _row("Status",       _e(r.get("status"))),
        _row("Content-Type", _e(r.get("content_type", ""))),
    ]
    return _card(i, "asset", r.get("status"), rows, [])


def _render_unknown_record(i: int, r: dict) -> str:
    rows = [_row("Raw", "")]
    return _card(i, r.get("type", "unknown"), None, rows,
                 [_collapsible("Raw JSON", json.dumps(r, ensure_ascii=False, indent=2))])


def _card(i: int, rtype: str, status, rows: list[str], details: list[str]) -> str:
    rows_html    = "".join(rows)
    details_html = "".join(details)
    return f"""
<div class="card" id="r{i}">
  <div class="card-header">
    <span class="card-num">#{i}</span>
    {_badge(rtype)}
    <span class="card-status">HTTP {_e(status)}</span>
  </div>
  <table class="info-table">{rows_html}</table>
  {details_html}
</div>"""


# ── summary bar ──────────────────────────────────────────────────────────────

def _summary(records: list[dict]) -> str:
    total = len(records)
    type_counts: dict[str, int] = {}
    for r in records:
        t = r.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    html_recs = [r for r in records if r.get("type") == "html"]
    texts     = [len(r.get("extracted_text", "")) for r in html_recs]
    titled    = sum(1 for r in html_recs if r.get("title"))
    dated     = sum(1 for r in html_recs if r.get("date"))
    short     = sum(1 for t in texts if t < 200)
    avg       = (sum(texts) // len(texts)) if texts else 0

    type_pills = " ".join(
        f'<span class="pill">{_badge(t)} &times;{n}</span>'
        for t, n in sorted(type_counts.items())
    )
    stats = ""
    if html_recs:
        stats = (
            f'<div class="stat-row">'
            f'<span>avg text <strong>{avg:,}</strong> chars</span>'
            f'<span>titled <strong>{titled}/{len(html_recs)}</strong></span>'
            f'<span>dated <strong>{dated}/{len(html_recs)}</strong></span>'
            f'<span>short (&lt;200) <strong>{short}</strong></span>'
            f'</div>'
        )

    return f"""
<div class="summary">
  <h2>Summary — {total} records</h2>
  <div class="pill-row">{type_pills}</div>
  {stats}
</div>"""


# ── page template ─────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #f1f5f9; color: #1e293b; }
header { background: #1e293b; color: #f8fafc; padding: 16px 24px; }
header h1 { font-size: 1.2rem; font-weight: 600; }
header small { opacity: .7; font-size: .85rem; }
.container { max-width: 960px; margin: 24px auto; padding: 0 16px; }

/* search */
.search-bar { margin-bottom: 16px; }
.search-bar input {
  width: 100%; padding: 10px 14px; border: 1px solid #cbd5e1;
  border-radius: 8px; font-size: 1rem; background: #fff;
}

/* summary */
.summary { background: #fff; border-radius: 10px; padding: 16px 20px;
           margin-bottom: 20px; box-shadow: 0 1px 3px #0001; }
.summary h2 { font-size: 1rem; margin-bottom: 10px; color: #475569; }
.pill-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.pill { display: flex; align-items: center; gap: 6px; }
.stat-row { display: flex; gap: 20px; flex-wrap: wrap; font-size: .9rem; color: #475569; }
.stat-row span { background: #f8fafc; border-radius: 6px; padding: 4px 10px;
                 border: 1px solid #e2e8f0; }

/* cards */
.card { background: #fff; border-radius: 10px; padding: 16px 20px;
        margin-bottom: 14px; box-shadow: 0 1px 3px #0001; }
.card:target { outline: 2px solid #2563eb; }
.card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.card-num { font-size: .85rem; color: #94a3b8; min-width: 28px; }
.card-status { font-size: .85rem; color: #64748b; margin-left: auto; }
.badge { color: #fff; font-size: .72rem; font-weight: 700; padding: 3px 8px;
         border-radius: 4px; letter-spacing: .04em; }

/* info table */
.info-table { width: 100%; border-collapse: collapse; font-size: .88rem;
              margin-bottom: 10px; }
.info-table th { width: 130px; text-align: left; padding: 4px 8px 4px 0;
                 color: #64748b; font-weight: 500; vertical-align: top; white-space: nowrap; }
.info-table td { padding: 4px 0; word-break: break-all; }
.info-table td a { color: #2563eb; text-decoration: none; }
.info-table td a:hover { text-decoration: underline; }
.mono { font-family: monospace; font-size: .82rem; }

/* collapsibles */
details { margin-top: 8px; }
summary { cursor: pointer; font-size: .85rem; color: #2563eb; font-weight: 500;
          padding: 4px 0; user-select: none; }
summary:hover { text-decoration: underline; }
.pre-wrap { white-space: pre-wrap; word-break: break-all; font-size: .8rem;
            background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
            padding: 10px; margin-top: 6px; max-height: 400px; overflow-y: auto;
            line-height: 1.55; }

/* filter hidden */
.hidden { display: none; }
"""

_JS = """
const input = document.getElementById('search');
input.addEventListener('input', () => {
  const q = input.value.toLowerCase();
  document.querySelectorAll('.card').forEach(card => {
    card.classList.toggle('hidden', q && !card.textContent.toLowerCase().includes(q));
  });
});
"""

def _build_html(title: str, summary_html: str, cards_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Crawler Report</h1>
  <small>{_e(title)}</small>
</header>
<div class="container">
  <div class="search-bar">
    <input id="search" type="search" placeholder="Search records by URL, title, text...">
  </div>
  {summary_html}
  {cards_html}
</div>
<script>{_JS}</script>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def build_report(jsonl_path: str, out_path: str | None = None) -> str:
    records = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not out_path:
        out_path = str(Path(jsonl_path).with_suffix(".html"))

    cards = []
    for i, r in enumerate(records, 1):
        rtype = r.get("type", "unknown")
        if rtype == "html":
            cards.append(_render_html_record(i, r))
        elif rtype == "external_redirect":
            cards.append(_render_redirect_record(i, r))
        elif rtype == "asset":
            cards.append(_render_asset_record(i, r))
        else:
            cards.append(_render_unknown_record(i, r))

    page = _build_html(
        title=os.path.basename(jsonl_path),
        summary_html=_summary(records),
        cards_html="\n".join(cards),
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HTML report from crawler JSONL output.")
    parser.add_argument("jsonl", help="Path to .jsonl file")
    parser.add_argument("-o", "--output", help="Output HTML path (default: same name as input)")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser automatically")
    args = parser.parse_args()

    out = build_report(args.jsonl, args.output)
    print(f"Report written: {out}")
    if not args.no_open:
        webbrowser.open(f"file:///{os.path.abspath(out)}")


if __name__ == "__main__":
    main()
