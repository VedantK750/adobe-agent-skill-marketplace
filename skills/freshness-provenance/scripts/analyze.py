#!/usr/bin/env python3
"""Is the content current, honestly dated and attributable?

Freshness and provenance are trust signals rather than access barriers, so
findings here are mostly weakening impact. The exception is undated
time-sensitive content, which actively risks a stale fact being repeated as
current.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

SKILL = "freshness-provenance"

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})", re.I)
# A time-sensitive *claim*, not merely a word. Bare "hours", "version" or
# "release" occur constantly in ordinary prose ("we talked for 4 hours", "try
# your version") and matching them produced false positives on editorial
# content. Each alternative below requires the operational context that makes
# the value something a reader would need dated: a currency price, a per-period
# price, a rate with a number, a stated pricing tier, opening hours, or a
# numbered software version.
TIME_SENSITIVE = re.compile(
    r"([$£€₹¥]\s?\d"                              # a currency price
    r"|\b\d+(\.\d+)?\s?(%|per cent)\s*(apr|apy|interest|rate)"  # a rate figure
    r"|\bprices?\s+(start|from|at)\b"             # "prices from ..."
    r"|\b(monthly|annual|per month|per year|/mo|/yr)\b.{0,20}[$£€₹¥]?\d"  # per-period price
    r"|\b(pricing|price)\s+(plan|tier|table)\b"  # a pricing plan/tier/table
    r"|\bopen(ing)?\s+hours?\b|\bhours?\s*:\s*\d"  # opening hours
    r"|\bversion\s+\d|\bv\d+\.\d"                 # a numbered version
    r")", re.I)
AUTHOR_HINT = re.compile(r"\b(by|author|written by|reviewed by|posted by)\b", re.I)
DATE_PROPS = ("datepublished", "datemodified", "dateposted")

NOW = datetime.now(timezone.utc)


def jsonld_dates(page):
    out = []
    for raw in page.get("jsonld_raw", []) or []:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = [data]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                for k, v in n.items():
                    if k.lower() in DATE_PROPS and isinstance(v, str):
                        out.append(v)
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(n, list):
                stack.extend(n)
    return out


def run(workdir):
    snap = A.load_snapshot(workdir)
    f = A.Fragment(SKILL)
    pages = A.ok_pages(snap)

    if not pages:
        f.unknown("FP-ALL", "No HTML pages available in the snapshot.")
        f.write(workdir)
        return

    dated_types = ("article", "documentation")
    datable = [p for p in pages if p.get("page_type") in dated_types]

    # -- 1. Missing publication dates on dated content ----------------------
    if datable:
        undated = [p for p in datable if not jsonld_dates(p)]
        if len(undated) > len(datable) * 0.5:
            f.finding(
                "FP-NO-DATES",
                "Articles and documentation carry no machine-readable date",
                "discoverability",
                "Recency is one of the few quality signals available without "
                "reading the content. An undated page cannot be preferred over "
                "an older competitor, and cannot be ruled out as stale either, "
                "so it tends to be passed over when a current answer is wanted.",
                A.ratio_evidence("dated-content pages", len(undated), len(datable),
                                 "No datePublished or dateModified in markup."),
                impact="weakening", affected=len(undated), sampled=len(datable),
                affected_urls=[p["final_url"] for p in undated],
                action={
                    "summary": "Emit datePublished and dateModified in JSON-LD "
                               "and show a visible date.",
                    "effort": "low",
                    "steps": [
                        "Add datePublished and dateModified in ISO-8601 to the "
                        "Article node.",
                        "Show the date visibly near the headline.",
                        "Update dateModified only on genuine content changes.",
                    ],
                    "example": '"datePublished":"2026-03-14",'
                               '"dateModified":"2026-08-02"',
                    "expected_impact": "Recency becomes assessable.",
                    "verification": "Dates present on most content pages.",
                })
        else:
            f.na("FP-NO-DATES", "Most content pages carry machine-readable dates.")
    else:
        f.na("FP-NO-DATES",
             "No article or documentation pages detected on this site.")

    # -- 2. Undated time-sensitive claims -----------------------------------
    # Product pages are deliberately out of scope: a product page stating its
    # current price with no date is the norm on every store, so firing there
    # produces a finding on 100% of a normal ecommerce site — noise, not signal.
    # Price freshness on products is a structured-data concern (priceValidUntil
    # on the Offer), handled there. This check targets prose pages — home,
    # articles, documentation — where an undated price, plan or version claim in
    # running text genuinely risks a superseded figure being repeated.
    TS_SCOPE = ("home", "documentation", "article")
    risky = [p for p in pages
             if TIME_SENSITIVE.search(p.get("body_text") or "")
             and not jsonld_dates(p)
             and p.get("page_type") in TS_SCOPE]
    scope = [p for p in pages if p.get("page_type") in TS_SCOPE]
    if risky and scope:
        f.finding(
            "FP-UNDATED-TIME-SENSITIVE",
            "Pages state time-sensitive facts with no date attached",
            "discoverability",
            "Prices, plans, hours and version numbers change. Without a date a "
            "consumer cannot tell whether the value is current, so a superseded "
            "figure may be repeated as though it still holds.",
            A.ratio_evidence("relevant pages", len(risky), len(scope),
                             "Time-sensitive language present with no "
                             "machine-readable date."),
            impact="degrading", affected=len(risky), sampled=len(scope),
            confidence="medium",
            affected_urls=[p["final_url"] for p in risky],
            action={
                "summary": "Date every page that states a price, plan, hour or "
                           "version.",
                "effort": "low",
                "steps": ["Add dateModified to the page markup.",
                          "Add priceValidUntil to Offer nodes.",
                          "Show a visible 'last updated' line on such pages."],
                "expected_impact": "Current values are distinguishable from "
                                   "superseded ones.",
                "verification": "Check clears on re-run.",
            })
    else:
        f.na("FP-UNDATED-TIME-SENSITIVE",
             "No undated time-sensitive pages detected.")

    # -- 3. Stale copyright --------------------------------------------------
    # A copyright line is very often a range ("© 2001-2024"). What matters is
    # the LATEST year it names, not the first: "2001-2025" on a 2026 run is
    # current, and reading the 2001 as the copyright year would be a false
    # positive. So take the maximum plausible year within the copyright span,
    # tolerant of whatever dash or entity separates a range.
    stale_years = []
    for p in pages:
        m = COPYRIGHT_RE.search(p.get("text") or "")
        if not m:
            continue
        span = (p.get("text") or "")[m.start():m.start() + 40]
        years = [int(y) for y in re.findall(r"\b(20\d{2}|19\d{2})\b", span)
                 if 1990 <= int(y) <= NOW.year + 1]
        if not years:
            continue
        year = max(years)
        if year < NOW.year - 1:
            stale_years.append((p, year))
    if stale_years:
        newest = max(y for _, y in stale_years)
        f.finding(
            "FP-STALE-COPYRIGHT",
            "Footer copyright year is years out of date",
            "discoverability",
            "A visibly outdated copyright line is a cheap, prominent signal "
            "that the site is unmaintained, and it appears on every page. It "
            "invites a consumer to discount otherwise current content.",
            A.ratio_evidence("HTML pages", len(stale_years), len(pages),
                             "Most recent copyright year seen: %d (current year "
                             "%d)." % (newest, NOW.year)),
            impact="weakening", affected=len(stale_years), sampled=len(pages),
            affected_urls=[p["final_url"] for p, _ in stale_years],
            action={
                "summary": "Render the copyright year dynamically.",
                "effort": "low",
                "steps": ["Generate the year at build or request time.",
                          "Treat this as a symptom and check what else has not "
                          "been reviewed since that year."],
                "expected_impact": "Removes a prominent staleness signal.",
                "verification": "Copyright reflects the current year.",
            })
    else:
        f.na("FP-STALE-COPYRIGHT", "No stale copyright year detected.")

    # -- 4. Sitemap lastmod honesty -----------------------------------------
    lastmods = [v for v in (snap.get("sitemap", {}).get("lastmod") or {}).values() if v]
    if lastmods:
        days = set()
        for v in lastmods:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
            if m:
                days.add(m.group(0))
        if len(days) == 1 and len(lastmods) > 8:
            f.finding(
                "FP-LASTMOD-UNIFORM",
                "Every sitemap entry claims the same modification date",
                "discoverability",
                "Identical lastmod values across an entire sitemap indicate the "
                "date reflects the build, not the content. Once the signal is "
                "known to be unreliable it stops being used, so genuinely "
                "updated pages lose the benefit of having been updated.",
                "%d sitemap entries all share lastmod %s."
                % (len(lastmods), sorted(days)[0]),
                impact="weakening", affected=len(lastmods), sampled=len(lastmods),
                confidence="medium",
                action={
                    "summary": "Derive lastmod from real content-change "
                               "timestamps.",
                    "effort": "medium",
                    "steps": ["Store a content-updated timestamp per page in "
                              "the CMS.",
                              "Emit that value, not the deploy time."],
                    "expected_impact": "Freshness signal becomes trustworthy "
                                       "and therefore useful.",
                    "verification": "lastmod values vary across pages.",
                })
        else:
            f.na("FP-LASTMOD-UNIFORM",
                 "Sitemap lastmod values vary across entries.")
    else:
        f.na("FP-LASTMOD-UNIFORM", "No lastmod values available to assess.")

    # -- 5. Author attribution ----------------------------------------------
    articles = [p for p in pages if p.get("page_type") == "article"]
    if articles:
        unattributed = []
        for p in articles:
            text = (p.get("body_text") or "")[:1200]
            has_author_json = any(
                '"author"' in (raw or "").lower()
                for raw in p.get("jsonld_raw") or [])
            if not has_author_json and not AUTHOR_HINT.search(text):
                unattributed.append(p)
        if len(unattributed) > len(articles) * 0.5:
            f.finding(
                "FP-NO-AUTHOR",
                "Articles carry no author attribution",
                "discoverability",
                "Attribution is a provenance signal: content traceable to a "
                "named, credentialed person is weighted more heavily than "
                "anonymous copy, particularly on subjects where expertise "
                "matters.",
                A.ratio_evidence("article pages", len(unattributed), len(articles)),
                impact="weakening", affected=len(unattributed), sampled=len(articles),
                affected_urls=[p["final_url"] for p in unattributed],
                action={
                    "summary": "Attribute every article to a named author with "
                               "an author page.",
                    "effort": "medium",
                    "steps": ["Add a Person author node to Article markup.",
                              "Publish author pages stating relevant credentials.",
                              "Link the author page from every byline."],
                    "expected_impact": "Content gains assessable provenance.",
                    "verification": "Author attribution on most articles.",
                })
        else:
            f.na("FP-NO-AUTHOR", "Most articles carry author attribution.")
    else:
        f.na("FP-NO-AUTHOR", "No article pages detected on this site.")

    # -- 6. Stale year references in headings -------------------------------
    old_year_pages = []
    for p in pages:
        for h in p.get("headings") or []:
            years = [int(y) for y in re.findall(r"\b(20\d{2})\b", h.get("text", ""))]
            if years and max(years) < NOW.year - 1:
                old_year_pages.append(p)
                break
    if old_year_pages:
        f.finding(
            "FP-STALE-YEAR-HEADINGS",
            "Headings reference years that are now well past",
            "discoverability",
            "Year-stamped headings age loudly. A page titled for a past year "
            "reads as superseded even when its substance is still accurate, and "
            "will lose to a competitor whose page names the current year.",
            A.ratio_evidence("HTML pages", len(old_year_pages), len(pages),
                             "Current year is %d." % NOW.year),
            impact="weakening", affected=len(old_year_pages), sampled=len(pages),
            confidence="medium",
            affected_urls=[p["final_url"] for p in old_year_pages],
            action={
                "summary": "Refresh or de-year evergreen pages.",
                "effort": "medium",
                "steps": ["Update the content and the year together.",
                          "For evergreen material, drop the year and rely on "
                          "dateModified instead."],
                "expected_impact": "Removes a visible obsolescence signal.",
                "verification": "No headings reference years before %d."
                                % (NOW.year - 1),
            })
    else:
        f.na("FP-STALE-YEAR-HEADINGS", "No stale year references in headings.")

    f.write(workdir)


if __name__ == "__main__":
    run(A.parse_args(SKILL).workdir)
