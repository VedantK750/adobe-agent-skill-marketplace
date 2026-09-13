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

# - signals

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

    # 1. Declared schema type is the strongest available signal — but only for
    # types that state what the page IS. FAQPage and HowTo are routinely
    # embedded as *enhancements* on a commerce page (a product detail page
    # carrying an FAQ block to win a rich result), so treating them as the
    # page's identity misreads product pages as documentation. quince.com does
    # exactly this: its product pages declare FAQPage, and every product check
    # fell silent while documentation checks fired on pages that are not docs.
    # A defining type wins outright; a supporting type is held back and used
    # only if nothing stronger identifies the page.
    SUPPORTING = {"faqpage", "howto"}
    supporting_guess = None
    for t in declared_types(page):
        base = t.split("/")[-1]
        if base not in SCHEMA_TO_PAGE:
            continue
        if base in SUPPORTING:
            if supporting_guess is None:
                supporting_guess = SCHEMA_TO_PAGE[base]
            continue
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
    # Commerce evidence outranks a merely supporting FAQ/HowTo block: a page
    # with an add-to-cart control and a price is a product page regardless of
    # the FAQ it also carries.
    if has_cart and has_price:
        return "product"
    if supporting_guess:
        return supporting_guess
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
    # Only pages we could actually read inform the site type. If every page we
    # hold is an error/blocked response (a site that 403s our crawler, as many
    # large consumer sites do) or a soft-404, there is no evidence to classify
    # from — the honest answer is `unknown`, never `portfolio`. The old
    # `len(pages) <= 6 -> portfolio` fallback fired on a single 403 page and
    # mislabelled a Fortune-500 site as a portfolio.
    readable = [p for p in pages
                if p.get("status") == 200 and p.get("raw_html")
                and not p.get("soft_404")]
    if not readable:
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

    # Strong ecommerce evidence is a real SHARE of product pages or Product/
    # Offer schema on a meaningful fraction of pages — never a single Product
    # node. A news site that carries one Product node (a book review, a
    # "recommended" widget) is not a store: The Guardian declares a lone
    # Product among ten NewsArticles, and the old `"product" in joined` test
    # flipped it to ecommerce. Count how many pages actually declare Product/
    # Offer and require prevalence, and let article/doc dominance win first.
    pages_with_product = 0
    for p in pages:
        dts = declared_types(p)
        if any(t in ("product", "offer") for t in dts):
            pages_with_product += 1
    product_schema_share = pages_with_product / n
    strong_ecom = product_share >= 0.15 or product_schema_share >= 0.2
    cart_hits = len(CART_RE.findall(text))
    # Article- or documentation-dominant sites are classified as such even if a
    # stray Product node is present, so a lone shop widget cannot override a
    # clearly editorial or documentation site.
    article_dominant = article_share >= 0.4
    doc_dominant_early = doc_share >= 0.3
    if strong_ecom and not article_dominant and not doc_dominant_early:
        return "ecommerce"
    # Documentation wins on a real share of doc pages OR a dominant doc + other
    # mix, because doc sites often leave many pages unclassified ("other") while
    # still being unmistakably documentation. A quarter of the sample as docs,
    # with docs being the largest *classified* type, is enough.
    doc_dominant = doc_share >= 0.3 or (
        doc_share >= 0.2 and types.count("documentation") >= max(
            types.count("product"), types.count("article"),
            types.count("category")))
    if doc_dominant:
        return "documentation"
    if article_share >= 0.4:
        return "publisher"
    if "localbusiness" in joined or "restaurant" in joined or "medicalbusiness" in joined:
        return "local-business"
    # Cart language only counts when the site is not article-led and the signal
    # is more than a single incidental phrase.
    if cart_hits >= 2 and article_share < 0.3:
        return "ecommerce"
    # SaaS/software requires CONVERGING signals, not one word. "api" alone
    # appears on nearly every technical or documentation site, and matching it
    # mislabelled the Python docs and Project Gutenberg as software. Demand at
    # least two distinct product-led SaaS markers (a pricing/trial/subscription
    # signal AND an integrations/API/platform signal), so incidental vocabulary
    # on a docs or publisher site no longer tips the classification.
    saas_signals = 0
    if re.search(r"\b(free trial|start free|sign up free|pricing plans?|"
                 r"subscription|per month|/mo\b|per seat|per user)\b", text, re.I):
        saas_signals += 1
    if re.search(r"\b(integrations?|sdk|rest api|api key|dashboard|"
                 r"single sign-on|sso|deploy|workspace)\b", text, re.I):
        saas_signals += 1
    if re.search(r"\b(saas|platform as a service|cloud platform)\b", text, re.I):
        saas_signals += 2
    if saas_signals >= 2 and article_share < 0.3 and doc_share < 0.3:
        return "software"
    if BOOKING_RE.search(text):
        return "local-business"
    if article_share >= 0.25:
        return "publisher"
    # A documentation-leaning site that fell through (many docs but also many
    # 'other' index pages) is still better called documentation than unknown.
    if types.count("documentation") >= 2 and types.count("documentation") >= \
            types.count("article"):
        return "documentation"
    # Publisher fallback keyed on the host/base path, not per-post URLs. A blog
    # or news site whose posts use bare-slug or dated permalinks that the page
    # classifier files as `category`/`other` (Mozilla's blog does exactly this)
    # would otherwise fall through to `unknown`. A host or root path named
    # `blog`/`news` is a strong, general publisher signal independent of how
    # individual post URLs happen to be shaped, so lean publisher when the
    # sample is also content-shaped (not an app shell): several category/other
    # pages and at least one real article or dated page seen.
    from urllib.parse import urlparse
    first = urlparse(pages[0].get("final_url") or pages[0].get("url") or "")
    host_path = (first.netloc + " " + first.path).lower()
    bloggish = re.search(r"\b(blog|news|magazine|journal|press)\b", host_path)
    # News/editorial sites also reveal themselves by the shape of their content
    # URLs across the crawl: /topics/, /series/, /story/, /article/, a dated
    # permalink. ProPublica files posts under /topics and /series, which the
    # page classifier calls `category`, leaving article_share low — so look for
    # these editorial path segments among the readable pages too.
    editorial_re = re.compile(
        r"/(topics?|series|story|stories|article|articles|feature|features|"
        r"investigations?|reports?|news)/", re.I)
    editorial_urls = sum(
        1 for p in readable
        if editorial_re.search(urlparse(p.get("final_url") or "").path)
        or re.search(r"/(19|20)\d{2}/", urlparse(p.get("final_url") or "").path))
    editorial = editorial_urls >= max(3, int(0.3 * len(readable)))
    content_shaped = (types.count("category") + types.count("other")
                      + types.count("article")) >= max(3, int(0.5 * len(pages)))
    if (bloggish or editorial) and content_shaped and product_share < 0.15:
        return "publisher"
    # Portfolio only when we actually read a small site, not when a large site
    # merely blocked most of the crawl. Keyed on readable pages, not total.
    if len(readable) <= 6:
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
