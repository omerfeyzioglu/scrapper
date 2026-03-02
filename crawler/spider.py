"""
spider.py — Scrapy domain spider: crawl, extract, validate, emit JSONL records.

Usage:
    scrapy runspider crawler/spider.py -a site=https://example.com -a max_pages=200 -O out.jsonl
"""

from __future__ import annotations

import logging
import os
import sys

# Allow `scrapy runspider crawler/spider.py` to resolve the `crawler` package
# regardless of where the command is run from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import deque
from typing import Generator

import scrapy
from scrapy.http import Response

from crawler import extract, llm, spec_store
from urllib.parse import urlparse

from crawler.utils import (
    diverse_link_sample,
    get_domain,
    is_ad_domain,
    is_junk_scheme,
    is_same_domain,
    normalise_href,
    normalise_url,
    path_prefix,
)

log = logging.getLogger(__name__)

VALIDATION_WINDOW = 10   # pages tracked per prefix for title-missing check
REPAIR_COOLDOWN   = 20   # minimum pages between consecutive repairs (per prefix)

NON_HTML_EXTENSIONS = frozenset({
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".gz", ".tar",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".mp3", ".avi", ".mov", ".wmv",
    ".exe", ".dmg", ".pkg",
})

_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
}


def _non_html_content_type(url: str) -> str | None:
    """Return guessed MIME type if URL has a non-HTML extension, else None."""
    ext = urlparse(url).path.lower().rsplit(".", 1)
    if len(ext) == 2:
        dot_ext = "." + ext[1]
        if dot_ext in NON_HTML_EXTENSIONS:
            return _EXT_TO_MIME.get(dot_ext, "application/octet-stream")
    return None


class DomainSpider(scrapy.Spider):
    name = "domain"
    custom_settings = {
        "HTTPCACHE_ENABLED": False,
        "ROBOTSTXT_OBEY": True,
        "REDIRECT_ENABLED": True,
        "REDIRECT_MAX_TIMES": 5,
        "LOG_LEVEL": "INFO",
        "CONCURRENT_REQUESTS": 8,
        "DOWNLOAD_DELAY": 0.25,
        "AUTOTHROTTLE_ENABLED": True,
    }

    # ------------------------------------------------------------------ init

    def __init__(self, site: str, max_pages: int = None, **kwargs):
        super().__init__(**kwargs)
        self.start_url: str = site.rstrip("/")
        self.domain: str = get_domain(self.start_url)
        self.max_pages: int | None = int(max_pages) if max_pages is not None else None

        self.visited: set[str] = {normalise_url(self.start_url)}
        self.pages_emitted: int = 0

        # Per-prefix spec state
        # spec cache is loaded lazily from disk in _get_spec()
        self._spec_cache: dict[str, dict] = {}          # prefix → spec (in-memory)

        # Per-prefix validation windows: prefix → deque of bool (title present?)
        self._title_windows: dict[str, deque] = {}

        # Per-prefix repair cooldowns: prefix → pages since last repair
        self._pages_since_repair: dict[str, int] = {}

        # URLs to re-crawl after a spec repair (excluded from max_pages cap)
        self._retry_urls: set[str] = set()

    # --------------------------------------------------------- start_requests

    async def start(self):
        yield scrapy.Request(
            self.start_url,
            callback=self.parse,
            errback=self.handle_error,
            dont_filter=True,
        )

    def handle_error(self, failure):
        log.error("Request failed: %s", failure)

    # --------------------------------------------------------------- helpers

    def _over_limit(self) -> bool:
        if self.max_pages is None:
            return False
        return self.pages_emitted >= self.max_pages

    def _enqueue_links(self, response: Response) -> Generator:
        """Yield new Requests for same-domain links found on this page."""
        if self._over_limit():
            return

        raw_hrefs = response.css("a::attr(href)").getall()
        sampled = diverse_link_sample(
            raw_hrefs,
            base_url=response.url,
            base_domain=self.domain,
        )

        for url in sampled:
            if self._over_limit():
                break
            clean = normalise_url(url.split("#")[0])
            if clean in self.visited:
                continue
            self.visited.add(clean)

            # Emit asset record immediately for known non-HTML file types
            guessed_mime = _non_html_content_type(clean)
            if guessed_mime is not None:
                yield {
                    "type": "asset",
                    "url": clean,
                    "final_url": clean,
                    "status": None,
                    "content_type": guessed_mime,
                }
                continue

            yield scrapy.Request(
                clean,
                callback=self.parse,
                errback=self.handle_error,
            )

    # --------------------------------------------------------- spec lifecycle

    def _get_prefix(self, url: str) -> str:
        """Return the path prefix used as page-type key."""
        return path_prefix(url)

    def _get_spec(self, url: str) -> dict | None:
        """
        Return in-memory spec for this URL's prefix, loading from disk on first
        access. Returns None if no spec exists yet for this prefix.
        """
        prefix = self._get_prefix(url)
        if prefix not in self._spec_cache:
            cached = spec_store.load_spec(self.domain, prefix)
            if cached is not None:
                self._spec_cache[prefix] = cached
            else:
                return None
        return self._spec_cache.get(prefix)

    def _set_spec(self, url: str, spec: dict) -> None:
        """Persist spec for this URL's prefix (disk + memory)."""
        prefix = self._get_prefix(url)
        self._spec_cache[prefix] = spec
        spec_store.save_spec(self.domain, prefix, spec)

    def _ensure_spec(self, response: Response) -> None:
        """Generate spec from this response if we don't have one for its prefix."""
        if self._get_spec(response.url) is not None:
            return
        prefix = self._get_prefix(response.url)
        html = response.text
        snippet = extract.html_snippet_for_llm(html)
        raw_hrefs = response.css("a::attr(href)").getall()
        href_sample = diverse_link_sample(
            raw_hrefs, base_url=response.url, base_domain=self.domain
        )
        spec = llm.generate_spec(
            self.domain, prefix, response.url, snippet, href_sample
        )
        self._set_spec(response.url, spec)

    def _maybe_repair(self, response: Response, reason: str) -> None:
        """
        Attempt spec repair for this page's prefix.

        Cooldown is tracked per prefix so a broken ilan spec doesn't block
        repair of a broken eskiler spec.
        After repair (or if in cooldown), the page URL is added to _retry_urls
        so it can be re-crawled with the fresh spec.
        """
        prefix = self._get_prefix(response.url)
        since = self._pages_since_repair.get(prefix, REPAIR_COOLDOWN + 1)

        # Always queue for retry regardless of cooldown
        self._retry_urls.add(response.url)

        if since < REPAIR_COOLDOWN:
            log.info(
                "Spec repair for %s [prefix=%r] skipped (cooldown %d/%d); "
                "page queued for retry.",
                self.domain, prefix, since, REPAIR_COOLDOWN,
            )
            return

        log.warning(
            "Triggering spec repair for %s [prefix=%r]: %s",
            self.domain, prefix, reason,
        )
        current_spec = self._get_spec(response.url) or {}
        html = response.text
        snippet = extract.html_snippet_for_llm(html)
        raw_hrefs = response.css("a::attr(href)").getall()
        href_sample = diverse_link_sample(
            raw_hrefs, base_url=response.url, base_domain=self.domain
        )
        new_spec = llm.repair_spec(
            self.domain, prefix, current_spec, reason,
            response.url, snippet, href_sample,
        )
        self._set_spec(response.url, new_spec)
        self._pages_since_repair[prefix] = 0
        log.info(
            "Spec repaired for %s [prefix=%r]; page queued for retry.",
            self.domain, prefix,
        )

    def _validate(self, data: dict, response: Response) -> None:
        """Check extraction quality per prefix; trigger repair if clearly broken."""
        prefix = self._get_prefix(response.url)

        # Increment per-prefix cooldown counter
        self._pages_since_repair[prefix] = (
            self._pages_since_repair.get(prefix, REPAIR_COOLDOWN + 1) + 1
        )

        flags: list[str] = []
        text = data.get("extracted_text", "")

        if data.get("title") and len(text) < 200:
            flags.append("title present but extracted_text < 200 chars")

        if extract.is_boilerplate_heavy(text):
            flags.append("boilerplate-heavy text")

        # Per-prefix title window
        if prefix not in self._title_windows:
            self._title_windows[prefix] = deque(maxlen=VALIDATION_WINDOW)
        window = self._title_windows[prefix]
        window.append(bool(data.get("title")))
        if len(window) == VALIDATION_WINDOW and sum(window) == 0:
            flags.append("title missing across last 10 pages")

        if len(flags) >= 2:
            self._maybe_repair(response, "; ".join(flags))

    # ----------------------------------------------------------------- parse

    def parse(self, response: Response):
        # Hard stop: drop in-flight responses once the cap is reached
        if self._over_limit():
            return

        final_url = response.url
        original_url = response.request.url

        # 1. External redirect check
        final_domain = get_domain(final_url)
        if final_domain != self.domain:
            yield {
                "type": "external_redirect",
                "url": original_url,
                "final_url": final_url,
                "status": response.status,
            }
            return

        # 2. Non-HTML asset
        content_type = response.headers.get("Content-Type", b"").decode("utf-8", errors="replace")
        if "text/html" not in content_type:
            yield {
                "type": "asset",
                "url": original_url,
                "final_url": final_url,
                "status": response.status,
                "content_type": content_type.split(";")[0].strip(),
            }
            return

        # 3. Ensure we have a spec for this page's prefix
        self._ensure_spec(response)

        # 4. Extract using per-prefix spec (fallback to default if still None)
        spec = self._get_spec(final_url) or {}
        data = extract.extract_page(response.text, final_url, spec, self.domain)

        # 5. Validate (may trigger per-prefix repair + retry queue)
        self._validate(data, response)

        # 6. Emit HTML record
        self.pages_emitted += 1
        yield {
            "type": "html",
            "url": original_url,
            "final_url": final_url,
            "status": response.status,
            "title": data["title"],
            "date": data["date"],
            "extracted_text": data["extracted_text"],
            "tables": data["tables"],
            "content_links_sample": data["content_links_sample"],
            "all_links_sample": data["all_links_sample"],
        }

        # 7. Follow links (normal BFS)
        if not self._over_limit():
            yield from self._enqueue_links(response)

    def closed(self, reason: str):
        """Called by Scrapy when the spider finishes. Re-crawl any queued retry URLs."""
        if self._retry_urls:
            log.info(
                "Spider closing: %d retry URL(s) queued after spec repairs — "
                "re-run crawl or use --set RETRY_URLS=... to process them.",
                len(self._retry_urls),
            )
            for url in sorted(self._retry_urls):
                log.info("  Pending retry: %s", url)
