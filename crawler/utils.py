"""
utils.py — domain helpers, ad/junk filtering, diverse link sampling.
"""

from __future__ import annotations

import math
from collections import defaultdict
from urllib.parse import urlparse, urljoin

AD_DOMAINS: frozenset[str] = frozenset(
    [
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "adservice.google.com",
        "adsystem.com",
        "adnxs.com",
        "ads.yahoo.com",
        "ad.doubleclick.net",
        "pagead2.googlesyndication.com",
        "adform.net",
        "advertising.com",
        "rubiconproject.com",
        "openx.net",
        "pubmatic.com",
        "criteo.com",
        "taboola.com",
        "outbrain.com",
        "moatads.com",
        "amazon-adsystem.com",
        "scorecardresearch.com",
        "pixel.facebook.com",
        "connect.facebook.net",
    ]
)

JUNK_SCHEMES: tuple[str, ...] = ("mailto:", "tel:", "javascript:", "sms:", "fax:")


def get_domain(url: str) -> str:
    return urlparse(url).netloc


def is_same_domain(url: str, domain: str) -> bool:
    return urlparse(url).netloc == domain


def is_ad_domain(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    for bad in AD_DOMAINS:
        if netloc == bad or netloc.endswith("." + bad):
            return True
    return False


def is_junk_scheme(url: str) -> bool:
    stripped = url.strip()
    if stripped.startswith("#"):
        return True
    for scheme in JUNK_SCHEMES:
        if stripped.lower().startswith(scheme):
            return True
    return False


def normalise_href(href: str, base_url: str) -> str | None:
    """Resolve relative href against base_url; return None if malformed."""
    try:
        return urljoin(base_url, href.strip())
    except Exception:
        return None


def normalise_url(url: str) -> str:
    """
    Canonical form for deduplication:
    - lowercase scheme and host
    - strip trailing slash from path (except bare root '/')
    - preserve query string and port
    """
    try:
        p = urlparse(url)
        path = p.path.rstrip("/") or "/"
        return p._replace(
            scheme=p.scheme.lower(),
            netloc=p.netloc.lower(),
            path=path,
        ).geturl()
    except Exception:
        return url


def _path_prefix(url: str) -> str:
    """Return first non-empty path segment, used for stratification."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[0] if parts else ""


def diverse_link_sample(
    hrefs: list[str],
    base_url: str,
    base_domain: str,
    max_links: int = 300,
) -> list[str]:
    """
    Return up to max_links same-domain hrefs, deduplicated and stratified by
    first URL path segment so diverse site sections are represented.

    Params
    ------
    hrefs       : raw href strings from the page (may be relative)
    base_url    : page URL used to resolve relative hrefs
    base_domain : only keep links matching this netloc
    max_links   : cap on returned list length
    """
    seen: set[str] = set()
    buckets: dict[str, list[str]] = defaultdict(list)

    for raw in hrefs:
        if is_junk_scheme(raw):
            continue
        url = normalise_href(raw, base_url)
        if url is None:
            continue
        if is_ad_domain(url):
            continue
        # strip fragment then normalise before deduplication
        clean = normalise_url(url.split("#")[0])
        if not is_same_domain(clean, base_domain):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        buckets[_path_prefix(clean)].append(clean)

    if not buckets:
        return []

    # Round-robin across buckets until we have enough links
    result: list[str] = []
    bucket_lists = list(buckets.values())
    indices = [0] * len(bucket_lists)
    rounds = math.ceil(max_links / max(len(bucket_lists), 1))

    for _ in range(rounds):
        for i, lst in enumerate(bucket_lists):
            if len(result) >= max_links:
                break
            if indices[i] < len(lst):
                result.append(lst[indices[i]])
                indices[i] += 1
        if len(result) >= max_links:
            break

    return result[:max_links]
