#!/usr/bin/env python3
"""Classify site type and page type.

This is the anti-false-positive mechanism for the whole marketplace. Checks
declare the page types they apply to; anything else is recorded as
`not_applicable` rather than fired. Flagging "no Product schema" on a blog
post is the commonest way an audit loses credibility, and gating here is what
prevents it.

Classification uses signals that generalise: declared schema.org types, URL
shape, and page-structure evidence. It deliberately avoids any string tied to
a particular site or CMS.
"""

import json
import re

# --- signals ---------------------------------------------------------------

URL_HINTS = [
    ("product", r"/(product|products|item|items|p|shop|store|buy|sku)(/|$)"),
    ("category", r"/(category|categories|collection|collections|c|catalog|shop)(/|$)"),
    ("article", r"/(blog|news|article|articles|post|posts|insights|stories|press)(/|$)"),
    # Date-based permalinks (/2026/04/slug, /2026/04/12/slug) are the
    # near-universal blog and news post shape. A year alone is an archive
    # listing, so require a further slug or day/slug segment before calling it
    # an article. This is a structural pattern, not a site-specific string.
    ("article", r"/(19|20)\d{2}/\d{1,2}/[^/]+"),
    ("article", r"/(19|20)\d{2}/[a-z][^/]{2,}"),
    ("documentation", r"/(docs|doc|documentation|guide|guides|manual|api|reference|kb|help|support)(/|$)"),
    ("contact", r"/(contact|contact-us|get-in-touch|locations?|book|appointment|enquiry)(/|$)"),
    ("about", r"/(about|about-us|team|company|who-we-are|our-story|careers)(/|$)"),
    ("legal", r"/(privacy|terms|legal|cookie|disclaimer|refund|shipping-policy|gdpr)(/|$)"),
]

SCHEMA_TO_PAGE = {
    "product": "product",
    "offer": "product",
    "itemlist": "category",
    "collectionpage": "category",
    "article": "article",
    "newsarticle": "article",
    "blogposting": "article",
    "techarticle": "documentation",
    "howto": "documentation",
    "faqpage": "documentation",
    "contactpage": "contact",
    "aboutpage": "about",
}

PRICE_RE = re.compile(
    r"(?:[$£€₹¥]|USD|EUR|GBP|INR|AUD|CAD)\s?\d[\d,]*(?:\.\d{2})?", re.I)
CART_RE = re.compile(
    r"\b(add to (?:cart|bag|basket)|buy now|checkout|in stock|out of stock)\b", re.I)
BOOKING_RE = re.compile(
    r"\b(book (?:a|an|now)|make an appointment|opening hours|find us|call us)\b", re.I)
DOC_RE = re.compile(
    r"\b(installation|configuration|parameters?|endpoint|returns?:|deprecated|changelog)\b", re.I)


def declared_types(page):
    """schema.org @type values declared on the page, lowercased."""
    out = []
    for raw in page.get("jsonld_raw", []) or []:
        try:
            data = json.loads(raw)
        except Exception:
            found = re.findall(r'"@type"\s*:\s*"([^"]+)"', raw or "")
            out.extend(t.lower() for t in found)
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, str):
                    out.append(t.lower())
                elif isinstance(t, list):
                    out.extend(str(x).lower() for x in t)
                stack.extend(v for v in node.values()
                             if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node)
    return out


def guess_type_from_url(url, base=None):
    """Cheap page-type guess from the URL alone, before anything is fetched.

    Used by the crawler to steer its frontier away from sections that are
    already saturated (a sitemap full of /legal/ URLs, say) without paying to
    fetch each one first. It only knows what the URL reveals, so it returns
    None when the path is uninformative; the crawler treats that as "unknown"
    and lets it through. The authoritative type is still assigned by
    classify_page after the page is fetched.
    """
    from urllib.parse import urlparse
    p = urlparse(url if url.startswith("http") else "https://" + url)
    path = p.path or "/"
    if path in ("", "/"):
        return "home"
    seg = [s for s in path.split("/") if s]
    if seg and re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", seg[0]):
        seg = seg[1:]
        if not seg:
            return "home"
        path = "/" + "/".join(seg)
    for label, pattern in URL_HINTS:
        if re.search(pattern, path):
            return label
    return None


def classify_page(page, base=None):
    from urllib.parse import urlparse
    url = (page.get("final_url") or page.get("url") or "").lower()
    req = (page.get("url") or "").lower()
    path = urlparse(url).path or "/"

    # Home detection has to survive geo/locale redirects. A site whose root
    # redirects "/" -> "/in" or "/en-us" still has the home page there, and
    # matching only path=="/" on the *final* URL would misfile it as "other",
    # which then suppresses every home-gated check. So treat as home: the bare
    # root, a request URL that was the crawl seed root, or a final path that is
    # just a short locale segment.
    if path in ("", "/"):
        return "home"
    if base is not None:
        b = urlparse(base if base.startswith("http") else "https://" + base)
        base_path = (b.path or "/").rstrip("/")
        if req.rstrip("/") == (b.scheme + "://" + b.netloc + base_path).lower() \
                and base_path in ("", "/"):
            return "home"
    seg = [s for s in path.split("/") if s]
    if len(seg) == 1 and re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", seg[0]):
        return "home"

    # 1. Declared schema type is the strongest available signal.
    for t in declared_types(page):
        base = t.split("/")[-1]
        if base in SCHEMA_TO_PAGE:
            return SCHEMA_TO_PAGE[base]

    # 2. URL shape.
    url_guess = None
    for label, pattern in URL_HINTS:
        if re.search(pattern, path):
            url_guess = label
            break

    text = (page.get("body_text") or page.get("text") or "")[:6000]
    headings = page.get("headings") or []
    h2_count = sum(1 for h in headings if h.get("level") == 2)

    # 3. Structural evidence, used to confirm or override a weak URL guess.
    has_price = bool(PRICE_RE.search(text))
    has_cart = bool(CART_RE.search(text))
    link_density = page.get("internal_links", 0)

    if url_guess in ("product", "category"):
        # Many links plus repeated prices reads as a listing, not a detail page.
        if link_density > 40 and has_price and not has_cart:
            return "category"
        if has_cart or (has_price and h2_count <= 12):
            return "product"
        return url_guess
    if url_guess:
        return url_guess

    # 4. Fall back to content shape when the URL is uninformative.
    if has_cart and has_price:
        return "product"
    if DOC_RE.search(text) and h2_count >= 3:
        return "documentation"
    if BOOKING_RE.search(text):
        return "contact"
    if link_density > 45 and len(text) < 2500:
        return "listing"
    return "other"


def classify_site(pages):
    if not pages:
        return "unknown"
    types = [p.get("page_type") for p in pages]
    all_types = []
    for p in pages:
        all_types.extend(declared_types(p))
    joined = " ".join(all_types)
    text = " ".join((p.get("body_text") or "")[:2000] for p in pages[:12])

    n = float(len(pages))
    product_share = types.count("product") / n
    article_share = types.count("article") / n
    doc_share = types.count("documentation") / n

    # The classified page-type distribution is the most reliable signal, so it
    # is weighed before any loose text match. Strong ecommerce evidence is
    # actual product pages or declared Product/Offer schema. Cart language on
    # its own is treated as corroborating only, and never overrides a site that
    # is clearly article- or documentation-led: "in stock" appears in plenty of
    # recipe and blog prose, and letting it alone declare a store mis-typed
    # publishers as ecommerce.
    strong_ecom = product_share >= 0.15 or "product" in joined or "offer" in joined
    cart_hits = len(CART_RE.findall(text))
    if strong_ecom:
        return "ecommerce"
    if doc_share >= 0.3:
        return "documentation"
    if article_share >= 0.4:
        return "publisher"
    if "localbusiness" in joined or "restaurant" in joined or "medicalbusiness" in joined:
        return "local-business"
    # Cart language only counts when the site is not article-led and the signal
    # is more than a single incidental phrase.
    if cart_hits >= 2 and article_share < 0.3:
        return "ecommerce"
    if re.search(r"\b(pricing|free trial|sign up|api|integrations?|saas)\b",
                 text, re.I):
        return "software"
    if BOOKING_RE.search(text):
        return "local-business"
    if article_share >= 0.25:
        return "publisher"
    if len(pages) <= 6:
        return "portfolio"
    return "unknown"


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
    import auditlib as A
    snap = A.load_snapshot(sys.argv[1])
    for p in snap["pages"]:
        print("%-14s %s" % (p.get("page_type"), p.get("final_url")))
    print("site_type:", snap.get("site_type"))
