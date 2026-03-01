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
from crawler.utils import (
    diverse_link_sample,
    get_domain,
    is_ad_domain,
    is_junk_scheme,
    is_same_domain,
    normalise_href,
    normalise_url,
)

log = logging.getLogger(__name__)

VALIDATION_WINDOW = 10   # pages tracked for title-missing check
REPAIR_COOLDOWN   = 20   # minimum pages between consecutive repairs


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

    def __init__(self, site: str, max_pages: int = 200, **kwargs):
        super().__init__(**kwargs)
        self.start_url: str = site.rstrip("/")
        self.domain: str = get_domain(self.start_url)
        self.max_pages: int = int(max_pages)

        self.visited: set[str] = {normalise_url(self.start_url)}
        self.pages_emitted: int = 0

        # rolling window for title-missing tracking
        self._title_window: deque[bool] = deque(maxlen=VALIDATION_WINDOW)
        self._pages_since_repair: int = 999

        # load or generate spec
        self.spec = spec_store.load_spec(self.domain)
        if self.spec is None:
            log.info("No cached spec for %s — will generate after first page", self.domain)

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
            yield scrapy.Request(
                clean,
                callback=self.parse,
                errback=self.handle_error,
            )

    # --------------------------------------------------------- spec lifecycle

    def _ensure_spec(self, response: Response) -> None:
        """Generate spec from this response if we don't have one yet."""
        if self.spec is not None:
            return
        html = response.text
        snippet = extract.html_snippet_for_llm(html)
        raw_hrefs = response.css("a::attr(href)").getall()
        href_sample = diverse_link_sample(
            raw_hrefs, base_url=response.url, base_domain=self.domain
        )
        self.spec = llm.generate_spec(self.domain, response.url, snippet, href_sample)
        spec_store.save_spec(self.domain, self.spec)

    def _maybe_repair(self, response: Response, reason: str) -> None:
        if self._pages_since_repair < REPAIR_COOLDOWN:
            return
        log.warning("Triggering spec repair for %s: %s", self.domain, reason)
        html = response.text
        snippet = extract.html_snippet_for_llm(html)
        raw_hrefs = response.css("a::attr(href)").getall()
        href_sample = diverse_link_sample(
            raw_hrefs, base_url=response.url, base_domain=self.domain
        )
        self.spec = llm.repair_spec(
            self.domain, self.spec, reason, response.url, snippet, href_sample
        )
        spec_store.save_spec(self.domain, self.spec)
        self._pages_since_repair = 0

    def _validate(self, data: dict, response: Response) -> None:
        """Check extraction quality; trigger repair if clearly broken."""
        flags: list[str] = []
        text = data.get("extracted_text", "")
        ld = data.get("link_density", 0.0)

        if data.get("title") and len(text) < 200:
            flags.append("title present but extracted_text < 200 chars")

        if ld > 0.35:
            flags.append(f"link density too high ({ld:.2f})")

        if extract.is_boilerplate_heavy(text):
            flags.append("boilerplate-heavy text")

        self._title_window.append(bool(data.get("title")))
        if (
            len(self._title_window) == VALIDATION_WINDOW
            and sum(self._title_window) == 0
        ):
            flags.append("title missing across last 10 pages")

        if len(flags) >= 2:
            self._maybe_repair(response, "; ".join(flags))

    # ----------------------------------------------------------------- parse

    def parse(self, response: Response):
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

        # 3. Ensure we have a spec
        self._ensure_spec(response)

        # 4. Extract
        data = extract.extract_page(response.text, final_url, self.spec, self.domain)
        self._pages_since_repair += 1

        # 5. Validate (may trigger repair)
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

        # 7. Follow links
        if not self._over_limit():
            yield from self._enqueue_links(response)
