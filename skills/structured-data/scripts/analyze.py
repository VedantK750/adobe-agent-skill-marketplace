#!/usr/bin/env python3
"""Structured data: are the key facts stated explicitly and validly?

Coverage is always reported per page type, never site-wide, and every check
is gated on the page types where the markup is genuinely expected. Flagging
missing Product markup on an about page is the classic false positive this
skill is built to avoid.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

SKILL = "structured-data"

# Page type -> (expected schema types, required properties for the main type).
# A product page on a SaaS/software site legitimately declares
# SoftwareApplication or Service rather than Product, so those satisfy the
# product-coverage check too; flagging "no Product markup" on a software
# pricing page is a false positive this map is written to avoid.
EXPECTED = {
    "product": (["product", "softwareapplication", "webapplication", "service"],
                ["name"]),
    "article": (["article", "newsarticle", "blogposting"],
                ["headline", "datepublished"]),
    "documentation": (["techarticle", "howto", "faqpage", "article"], ["name"]),
    "contact": (["localbusiness", "organization", "contactpage"], ["name"]),
    "home": (["organization", "website", "localbusiness"], ["name"]),
}

# Required properties depend on which type actually satisfied coverage. A
# Product needs offers; a SoftwareApplication does not, so requiring offers of
# everything on a product-typed page would mis-flag valid SaaS markup.
REQUIRED_BY_TYPE = {
    "product": ["name", "offers"],
    "softwareapplication": ["name"],
    "webapplication": ["name"],
    "service": ["name"],
    "article": ["headline", "datepublished"],
    "newsarticle": ["headline", "datepublished"],
    "blogposting": ["headline", "datepublished"],
}

# Visible prices, captured *with* their currency symbol so a conflict is only
# ever declared within one currency. Comparing a markup price in USD against a
# shipping surcharge printed in EUR would otherwise manufacture a phantom
# conflict. The symbol is normalised to an ISO-ish code for comparison.
PRICE_RE = re.compile(r"([$£€₹¥])\s?(\d[\d,]*(?:\.\d{1,2})?)")

_SYMBOL_TO_CODE = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR", "¥": "JPY"}


def _norm_amount(raw):
    """Normalise a price string to a canonical numeric string, or None.

    "1,299.00" -> "1299", "19.99" -> "19.99", "19.90" -> "19.9", "19.00" ->
    "19". Trailing-zero-only fractions collapse so "19.00" and "19" compare
    equal, but "19.99" and "19.00" stay distinct — the integer-only comparison
    this replaces treated those as equal and missed real conflicts.
    """
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        val = float(m.group(0))
    except ValueError:
        return None
    # Canonical form: drop an all-zero fractional part, else keep significant.
    if val == int(val):
        return str(int(val))
    return ("%.2f" % val).rstrip("0").rstrip(".")


def parse_nodes(page):
    """Every JSON-LD node on the page, plus genuine parse errors.

    A block that does not close cleanly (last non-space char is not } or ]) is
    treated as *truncated by capture*, not invalid markup, and is skipped
    rather than reported — capturing a snapshot must never manufacture an
    SD-INVALID-JSON finding. Blocks that fail only on stray control characters
    are retried once with those stripped, since a raw newline inside a string
    is a common, harmless authoring slip that consumers tolerate.
    """
    nodes, errors = [], []
    for raw in page.get("jsonld_raw", []) or []:
        text = (raw or "").strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception as exc:
            if text[-1:] not in ("}", "]"):
                continue  # truncated at capture, not a real error
            try:
                data = json.loads(re.sub(r"[\x00-\x1f]+", " ", text))
            except Exception:
                errors.append(str(exc)[:120])
                continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "@type" in node:
                    nodes.append(node)
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
    return nodes, errors


def types_of(node):
    t = node.get("@type")
    if isinstance(t, str):
        return [t.lower()]
    if isinstance(t, list):
        return [str(x).lower() for x in t]
    return []


def run(workdir):
    snap = A.load_snapshot(workdir)
    f = A.Fragment(SKILL, snapshot=snap)
    pages = A.ok_pages(snap)

    if not pages:
        f.unknown("SD-ALL", "No HTML pages available in the snapshot.")
        f.write(workdir)
        return

    parsed = {}
    for p in pages:
        parsed[p["final_url"]] = parse_nodes(p)

    # -- 1. Any structured data at all --------------------------------------
    with_sd = [p for p in pages
               if parsed[p["final_url"]][0] or p.get("has_microdata")]
    if not with_sd:
        f.finding(
            "SD-ABSENT",
            "No structured data anywhere on the site",
            "discoverability",
            "Structured data is the only channel that states a fact in a form "
            "requiring no inference. Without it every attribute — price, hours, "
            "author, rating — must be guessed from prose, and guesses are "
            "frequently dropped rather than risked.",
            "Crawled %d pages; none contain JSON-LD, microdata or RDFa." % len(pages),
            impact="degrading", affected=len(pages), sampled=len(pages),
            page_importance="critical",
            affected_urls=[p["final_url"] for p in pages],
            action={
                "summary": "Add JSON-LD to every template, starting with "
                           "Organization on the home page.",
                "effort": "medium",
                "steps": [
                    "Add an Organization (or LocalBusiness) node on the home "
                    "page with name, url, logo, description and sameAs.",
                    "Add the type matching each template: Product on product "
                    "pages, Article on posts, FAQPage where questions are answered.",
                    "Emit as JSON-LD in a script tag rather than inline microdata.",
                    "Validate against schema.org before deploying.",
                ],
                "example": '<script type="application/ld+json">\n'
                           '{"@context":"https://schema.org","@type":"Organization",\n'
                           ' "name":"Example","url":"https://example.com",\n'
                           ' "sameAs":["https://linkedin.com/company/example"]}\n'
                           '</script>',
                "expected_impact": "Key attributes become directly readable "
                                   "rather than inferred.",
                "verification": "Re-run the audit; SD-ABSENT clears.",
            })
        f.write(workdir)
        return

    # -- 2. Invalid JSON-LD --------------------------------------------------
    broken = [p for p in pages if parsed[p["final_url"]][1]]
    if broken:
        f.finding(
            "SD-INVALID-JSON",
            "JSON-LD blocks fail to parse",
            "discoverability",
            "Malformed JSON-LD is discarded wholesale. The markup is present, "
            "so the problem is invisible in the page source review, yet the "
            "consumer receives nothing at all from that block.",
            A.ratio_evidence("HTML pages", len(broken), len(pages),
                             "First error: %s" % parsed[broken[0]["final_url"]][1][0]),
            impact="degrading", affected=len(broken), sampled=len(pages),
            affected_urls=[p["final_url"] for p in broken],
            action={
                "summary": "Fix the malformed JSON-LD blocks and validate on build.",
                "effort": "low",
                "steps": ["Serialise markup with a JSON library rather than "
                          "string templates.",
                          "Escape quotes in values taken from the CMS.",
                          "Add a build-time JSON-LD validation step."],
                "expected_impact": "Existing markup starts being consumed.",
                "verification": "All JSON-LD blocks parse; check clears.",
            })
    else:
        f.na("SD-INVALID-JSON", "All JSON-LD blocks parse cleanly.")

    # -- 3. Coverage per page type, gated ------------------------------------
    for ptype, (expected_types, required) in EXPECTED.items():
        group = [p for p in pages if p.get("page_type") == ptype]
        check_id = "SD-COVERAGE-%s" % ptype.upper()
        if not group:
            f.na(check_id, "No %s pages detected on this site." % ptype)
            continue

        uncovered = []
        for p in group:
            nodes = parsed[p["final_url"]][0]
            have = {t for n in nodes for t in types_of(n)}
            if not (have & set(expected_types)):
                uncovered.append(p)

        if uncovered:
            f.finding(
                check_id,
                "No %s structured data on %s pages"
                % ("/".join(expected_types[:2]), ptype),
                "discoverability",
                "On %s pages the defining attributes are exactly what a user "
                "asks about. Declaring the matching schema.org type is what "
                "lets those attributes be read as data instead of inferred "
                "from surrounding prose." % ptype,
                A.ratio_evidence("%s pages" % ptype, len(uncovered), len(group),
                                 "Expected one of: %s." % ", ".join(expected_types)),
                impact="degrading", affected=len(uncovered), sampled=len(group),
                page_importance="high" if ptype in ("product", "home") else "normal",
                affected_urls=[p["final_url"] for p in uncovered],
                action={
                    "summary": "Add %s JSON-LD to every %s page."
                               % (expected_types[0].title(), ptype),
                    "priority_hint": "high",
                    "effort": "medium",
                    "steps": [
                        "Emit %s node on the %s template."
                        % (A.article_for(expected_types[0].title()), ptype),
                        "Populate the required properties: %s."
                        % ", ".join(required),
                        "Source values from the same data the page renders so "
                        "markup and visible text cannot drift apart.",
                    ],
                    "expected_impact": "Attributes on these pages become "
                                       "directly extractable.",
                    "verification": "Re-run the audit; %s reports full coverage."
                                    % check_id,
                })
        else:
            f.na(check_id, "All %d %s pages carry the expected type."
                 % (len(group), ptype))

    # -- 4. Required properties missing --------------------------------------
    incomplete = []
    for p in pages:
        ptype = p.get("page_type")
        if ptype not in EXPECTED:
            continue
        expected_types, default_required = EXPECTED[ptype]
        for node in parsed[p["final_url"]][0]:
            matched = set(types_of(node)) & set(expected_types)
            if matched:
                # Required properties follow the *actual* type that satisfied
                # coverage, not the page type, so a SoftwareApplication is not
                # judged against Product's `offers` requirement.
                required = REQUIRED_BY_TYPE.get(
                    sorted(matched)[0], default_required)
                lowered = {k.lower() for k in node.keys()}
                if any(r not in lowered for r in required):
                    incomplete.append((p, node))
                break
    if incomplete:
        f.finding(
            "SD-INCOMPLETE-PROPS",
            "Structured data omits required properties",
            "discoverability",
            "A node missing its required properties is often rejected as "
            "incomplete, so the markup delivers none of the benefit it appears "
            "to provide.",
            A.ratio_evidence("typed pages", len(incomplete), len(pages),
                             "Example missing set on %s."
                             % incomplete[0][0]["final_url"]),
            impact="degrading", affected=len(incomplete), sampled=len(pages),
            affected_urls=[p["final_url"] for p, _ in incomplete],
            action={
                "summary": "Populate the required properties for each declared type.",
                "effort": "low",
                "steps": ["Product requires name and offers (with price and "
                          "priceCurrency).",
                          "Article requires headline and datePublished.",
                          "Fill values from the CMS rather than hard-coding."],
                "expected_impact": "Markup validates and is consumed.",
                "verification": "Check clears on re-run.",
            })
    else:
        f.na("SD-INCOMPLETE-PROPS",
             "Declared nodes carry their required properties.")

    # -- 5. Organization identity and sameAs ---------------------------------
    org_nodes = [n for p in pages for n in parsed[p["final_url"]][0]
                 if set(types_of(n)) & {"organization", "localbusiness", "corporation"}]
    if not org_nodes:
        f.finding(
            "SD-NO-ORGANIZATION",
            "No Organization or LocalBusiness node anywhere on the site",
            "discoverability",
            "The Organization node is what ties a site to a real-world entity. "
            "Without it the brand has no machine-readable identity to attach "
            "facts to, which makes it easy to confuse with similarly named "
            "entities elsewhere.",
            "Crawled %d pages; no Organization/LocalBusiness node found." % len(pages),
            impact="degrading", affected=1, sampled=1, page_importance="high",
            action={
                "summary": "Publish an Organization node on the home page with "
                           "a complete sameAs array.",
                "effort": "low",
                "steps": ["Add Organization (or LocalBusiness for a physical "
                          "location) with name, url, logo and description.",
                          "List every official profile in sameAs: LinkedIn, "
                          "Crunchbase, Wikidata, industry directories.",
                          "Give it a stable @id and reference that @id from "
                          "other nodes."],
                "expected_impact": "The brand gains a resolvable machine identity.",
                "verification": "SD-NO-ORGANIZATION clears.",
            })
    else:
        has_sameas = any("sameas" in {k.lower() for k in n} for n in org_nodes)
        if not has_sameas:
            f.finding(
                "SD-NO-SAMEAS",
                "Organization node declares no sameAs links",
                "discoverability",
                "sameAs is the explicit statement that this site and a set of "
                "external profiles describe the same entity. Without it, "
                "corroborating evidence found elsewhere may not be connected "
                "back to this brand.",
                "Organization node present but carries no sameAs property.",
                impact="weakening", affected=1, sampled=1,
                action={
                    "summary": "Add a sameAs array listing every official "
                               "external profile.",
                    "effort": "low",
                    "steps": ["Include social profiles, Wikidata, Crunchbase and "
                              "authoritative directory listings.",
                              "Use only profiles the brand genuinely controls or "
                              "is the subject of."],
                    "expected_impact": "External mentions are attributed to the "
                                       "right entity.",
                    "verification": "SD-NO-SAMEAS clears.",
                })
        else:
            f.na("SD-NO-SAMEAS", "Organization node declares sameAs links.")

    # -- 6. Markup contradicting visible text --------------------------------
    # A conflict is only declared when the markup states a price and the visible
    # page shows a *different* price in the *same currency*. Two guards prevent
    # false positives that the earlier integer-only comparison allowed:
    #   * full decimal value is compared, so 19.99 != 19.00 is caught, while
    #     19.00 == 19 is not treated as a discrepancy;
    #   * prices are grouped by currency, so a USD offer is never compared
    #     against a EUR figure elsewhere on the page.
    conflicts = []
    for p in pages:
        if p.get("page_type") != "product":
            continue
        # Map currency code -> set of canonical visible amounts.
        visible = {}
        for sym, amt in PRICE_RE.findall(p.get("body_text") or ""):
            code = _SYMBOL_TO_CODE.get(sym)
            norm = _norm_amount(amt)
            if code and norm is not None:
                visible.setdefault(code, set()).add(norm)
        if not visible:
            continue
        for node in parsed[p["final_url"]][0]:
            offers = node.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list):
                continue
            hit = False
            for off in offers:
                if not isinstance(off, dict):
                    continue
                mprice = _norm_amount(off.get("price"))
                if mprice is None:
                    continue
                mcode = str(off.get("priceCurrency", "")).upper() or None
                # Compare only within a currency we can see on the page. If the
                # markup currency is unknown, fall back to any visible currency
                # that has exactly one price (unambiguous), else skip rather
                # than risk a phantom conflict.
                if mcode and mcode in visible:
                    candidates = visible[mcode]
                elif not mcode and len(visible) == 1:
                    candidates = next(iter(visible.values()))
                else:
                    continue
                if mprice not in candidates:
                    shown = sorted(candidates)[:3]
                    label = ("%s %s" % (mcode or "", mprice)).strip()
                    conflicts.append((p, label, shown))
                    hit = True
                    break
            if hit:
                break
    if conflicts:
        f.finding(
            "SD-TEXT-CONFLICT",
            "Structured data price disagrees with the visible page",
            "discoverability",
            "When markup and rendered text state different values, the "
            "discrepancy undermines trust in the markup generally, and an "
            "assistant may repeat a price the visitor never sees — which is "
            "worse than stating nothing.",
            A.ratio_evidence(
                "product pages", len(conflicts), len(
                    [p for p in pages if p.get("page_type") == "product"]),
                "Example: markup says %s, page shows %s."
                % (conflicts[0][1], ", ".join(conflicts[0][2]))),
            impact="degrading", affected=len(conflicts), sampled=len(pages),
            confidence="medium",
            affected_urls=[p["final_url"] for p, _, _ in conflicts],
            action={
                "summary": "Generate markup and visible text from one source of "
                           "truth so they cannot diverge.",
                "effort": "medium",
                "steps": ["Render the JSON-LD from the same data object that "
                          "renders the page.",
                          "Include currency and validity dates on every offer.",
                          "Add a build check comparing markup price to rendered "
                          "price."],
                "expected_impact": "Quoted attributes match what visitors see.",
                "verification": "SD-TEXT-CONFLICT clears.",
            })
    else:
        f.na("SD-TEXT-CONFLICT",
             "No price disagreement detected between markup and visible text.")

    f.write(workdir)


if __name__ == "__main__":
    run(A.parse_args(SKILL).workdir)
