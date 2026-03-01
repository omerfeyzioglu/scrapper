"""
inspect_output.py — pretty-print a .jsonl crawler output file.

Usage:
    python inspect_output.py out.jsonl
    python inspect_output.py out_resmi.jsonl
"""

import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main(path: str) -> None:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        print("No records found.")
        return

    # ── Summary ──────────────────────────────────────────────────────────────
    type_counts: dict[str, int] = {}
    for r in records:
        t = r.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    html_records = [r for r in records if r.get("type") == "html"]
    text_lengths  = [len(r.get("extracted_text", "")) for r in html_records]
    titled        = sum(1 for r in html_records if r.get("title"))
    dated         = sum(1 for r in html_records if r.get("date"))
    empty_text    = sum(1 for t in text_lengths if t < 200)

    print("=" * 60)
    print(f"FILE   : {path}")
    print(f"TOTAL  : {len(records)} records")
    print(f"TYPES  : {type_counts}")
    if html_records:
        avg_len = sum(text_lengths) // len(text_lengths)
        print(f"HTML   : {len(html_records)} pages | avg text {avg_len:,} chars "
              f"| titled {titled}/{len(html_records)} "
              f"| dated {dated}/{len(html_records)} "
              f"| short-text (<200) {empty_text}")
    print("=" * 60)
    print()

    # ── Per-record detail ────────────────────────────────────────────────────
    for i, r in enumerate(records):
        rtype = r.get("type", "unknown")
        print(f"[{i+1:>3}] {rtype.upper():<20}  status={r.get('status')}")
        print(f"       url       : {str(r.get('url', ''))[:90]}")

        final = r.get("final_url", "")
        if final and final != r.get("url"):
            print(f"       final_url : {str(final)[:90]}")

        if rtype == "html":
            title  = r.get("title", "")
            date   = r.get("date", "")
            txt    = r.get("extracted_text", "")
            tbls   = r.get("tables", [])
            clinks = r.get("content_links_sample", [])
            alinks = r.get("all_links_sample", [])

            print(f"       title     : {title[:80] or '(missing)'}")
            print(f"       date      : {date or '(missing)'}")
            print(f"       text_len  : {len(txt):,}  |  content_links={len(clinks)}  all_links={len(alinks)}")
            print(f"       text      : {txt[:200]}")
            if tbls:
                print(f"       tables    : {len(tbls)}")
                for ti, tbl in enumerate(tbls):
                    print(f"         [{ti}] headers={tbl.get('headers')}  rows={len(tbl.get('rows', []))}")
            if alinks:
                print(f"       links     : {alinks[:4]}")

        elif rtype == "asset":
            print(f"       ctype     : {r.get('content_type', '')}")

        elif rtype == "external_redirect":
            print(f"       redirected to different domain: {str(final)[:90]}")

        else:
            print(f"       (unknown record type)")

        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_output.py <output.jsonl>")
        sys.exit(1)
    main(sys.argv[1])
