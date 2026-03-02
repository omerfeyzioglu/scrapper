"""
extract.py — HTML extraction using a site-specific spec.
"""

from __future__ import annotations

import re
from typing import Any

from parsel import Selector

from crawler.utils import is_ad_domain, is_junk_scheme, is_same_domain, normalise_href

_BOILERPLATE_PATTERNS = re.compile(
    r"\b(cookie policy|privacy policy|all rights reserved|subscribe to|"
    r"sign up for|follow us on|share this|terms of use|terms and conditions)\b",
    re.IGNORECASE,
)

TEXT_LIMIT = 50_000

# HTML snippet size for LLM (spec generation/repair). Larger pages get better selector hints.
LLM_HTML_BYTES = 40_000


def _trim_html(html: str, target_bytes: int = LLM_HTML_BYTES) -> str:
    """Return a leading slice of HTML suitable for sending to the LLM."""
    encoded = html.encode("utf-8", errors="replace")
    return encoded[:target_bytes].decode("utf-8", errors="replace")


def _text_len(sel: Selector) -> int:
    return len(" ".join(sel.css("*::text").getall()).strip())


def _link_density(sel: Selector) -> float:
    total = _text_len(sel)
    if total == 0:
        return 0.0
    link_text = len(" ".join(sel.css("a::text").getall()).strip())
    return link_text / total


def _is_nav_like(sel: Selector) -> bool:
    """True if the node looks like a navigation block rather than content."""
    tag = sel.root.tag if hasattr(sel, "root") else ""
    classes = " ".join(sel.root.get("class", "").split()).lower() if hasattr(sel, "root") else ""
    nav_hints = {"nav", "menu", "sidebar", "header", "footer", "breadcrumb"}
    if tag in nav_hints:
        return True
    for hint in nav_hints:
        if hint in classes:
            return True
    return False


def _score(sel: Selector) -> float:
    tlen = _text_len(sel)
    ld = _link_density(sel)
    nav_penalty = 5_000 if _is_nav_like(sel) else 0
    return tlen * max(0, 1 - ld * 2) - nav_penalty


_ALWAYS_DROP = ("script", "style", "noscript", "template", "svg")


def drop_noise(sel: Selector, drop_selectors: list[str]) -> None:
    """Remove noisy nodes from the selector tree in-place.

    Always drops <script>, <style>, <noscript> etc. regardless of spec,
    then applies the caller-supplied drop_selectors.
    """
    for tag in _ALWAYS_DROP:
        for node in sel.css(tag):
            try:
                node.root.getparent().remove(node.root)
            except Exception:
                pass
    for css in drop_selectors:
        for node in sel.css(css):
            try:
                node.root.getparent().remove(node.root)
            except Exception:
                pass


def _auto_detect_block(sel: Selector) -> Selector | None:
    """
    Pure-heuristic fallback: score every structural block element and return
    the one with the most content-like text. Used when spec selectors match nothing.
    """
    best: Selector | None = None
    best_score = -1
    for tag in ("article", "main", "section", "div"):
        for candidate in sel.css(tag):
            if _text_len(candidate) < 100:
                continue
            s = _score(candidate)
            if s > best_score:
                best_score = s
                best = candidate
    return best


def _collect_content_blocks(sel: Selector, content_selectors: list[str]) -> list[Selector]:
    """Return ALL elements matching any of the content_selectors.

    If no selector matches, fall back to auto-detect (single best block).
    This allows list-style pages (quotes, products, news cards) to include
    every item, not just the highest-scoring one.
    """
    seen_ids: set[int] = set()
    blocks: list[Selector] = []

    for css in content_selectors:
        for candidate in sel.css(css):
            node_id = id(candidate.root)
            if node_id not in seen_ids:
                seen_ids.add(node_id)
                blocks.append(candidate)

    if not blocks:
        fallback = _auto_detect_block(sel)
        if fallback is not None:
            blocks = [fallback]

    return blocks


def extract_tables(sel: Selector, table_selector: str, max_tables: int = 10, max_rows: int = 50) -> list[dict]:
    tables: list[dict] = []
    for table in sel.css(table_selector or "table")[:max_tables]:
        headers = [th.css("::text").get("").strip() for th in table.css("th")]
        all_trs = table.css("tr")
        data_trs = all_trs
        # If no <th> found, treat the first <tr>'s <td> cells as headers
        if not headers and all_trs:
            headers = [td.css("::text").get("").strip() for td in all_trs[0].css("td")]
            data_trs = all_trs[1:]  # skip the header row from data rows
        rows: list[list[str]] = []
        for tr in data_trs[:max_rows]:
            cells = [td.css("::text").get("").strip() for td in tr.css("td")]
            if cells:
                rows.append(cells)
        tables.append({"headers": headers, "rows": rows})
    return tables


def extract_links(
    sel: Selector,
    base_url: str,
    domain: str,
    max_links: int = 500,
) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in sel.css("a::attr(href)").getall():
        if is_junk_scheme(href):
            continue
        url = normalise_href(href, base_url)
        if url is None:
            continue
        if is_ad_domain(url):
            continue
        clean = url.split("#")[0].rstrip("/") or url
        if not is_same_domain(clean, domain):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        links.append(clean)
        if len(links) >= max_links:
            break
    return links


def _clean_title(title: str) -> str:
    """Strip site-name suffixes appended after common separator patterns."""
    for sep in (" | ", " – ", " — ", " - ", " :: "):
        if sep in title:
            return title.split(sep)[0].strip()
    return title.strip()


def extract_page(html: str, url: str, spec: dict, domain: str) -> dict[str, Any]:
    """
    Parse *html* using *spec* and return a dict of extracted fields.
    Collects ALL matching content blocks so list pages emit every item.
    """
    sel = Selector(text=html)

    # 1. Drop noisy sections
    drop_noise(sel, spec.get("drop_selectors", []))

    # 2. Collect ALL matching content blocks
    blocks = _collect_content_blocks(sel, spec.get("content_selectors", []))

    # 3. Title
    fields = spec.get("fields", {})
    title = ""
    if fields.get("title_selector"):
        ts = fields["title_selector"]
        if "::" not in ts:
            ts = ts + "::text"
        title = " ".join(sel.css(ts).getall()).strip()
    if not title:
        raw_title = sel.css("title::text").get("").strip()
        title = _clean_title(raw_title)

    # 4. Date
    date = ""
    if fields.get("date_selector"):
        ds = fields["date_selector"]
        if "::" not in ds:
            ds = ds + "::text"
        date = " ".join(sel.css(ds).getall()).strip()

    # 5. Text: join ALL blocks with blank lines between them
    if blocks:
        parts = []
        for b in blocks:
            raw = " ".join(b.css("*::text").getall())
            cleaned = re.sub(r"\s+", " ", raw).strip()
            if cleaned:
                parts.append(cleaned)
        extracted_text = "\n\n".join(parts)[:TEXT_LIMIT]
        ld = sum(_link_density(b) for b in blocks) / len(blocks)
        primary = blocks[0]
    else:
        body_nodes = sel.css("body")
        primary = body_nodes[0] if body_nodes else sel
        raw_text = " ".join(primary.css("*::text").getall())
        extracted_text = re.sub(r"\s+", " ", raw_text).strip()[:TEXT_LIMIT]
        ld = _link_density(primary)

    # 7. Tables
    tables = extract_tables(primary, fields.get("table_selector", "table"))

    # 8. Content links
    content_links = extract_links(primary, url, domain, max_links=500)

    # 9. All links on full page
    all_links = extract_links(sel, url, domain, max_links=500)

    return {
        "title": title,
        "date": date,
        "extracted_text": extracted_text,
        "link_density": ld,
        "tables": tables,
        "content_links_sample": content_links,
        "all_links_sample": all_links,
    }


def is_boilerplate_heavy(text: str) -> bool:
    """True if the extracted text is dominated by boilerplate phrases."""
    matches = len(_BOILERPLATE_PATTERNS.findall(text))
    words = max(len(text.split()), 1)
    return (matches / words) > 0.05


def html_snippet_for_llm(html: str) -> str:
    return _trim_html(html, target_bytes=LLM_HTML_BYTES)
