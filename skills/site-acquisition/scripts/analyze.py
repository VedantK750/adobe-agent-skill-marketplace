#!/usr/bin/env python3
"""Access-layer checks: can a machine get in at all?

This is step one of the appendix pipeline (crawler admitted -> page readable
-> fact extractable). A failure here makes every later check moot, so these
findings carry blocking impact.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

SKILL = "site-acquisition"


def run(workdir):
    snap = A.load_snapshot(workdir)
    f = A.Fragment(SKILL)
    pages = snap.get("pages", [])
    robots = snap.get("robots", {})

    # AI crawler exclusion
    blocked = robots.get("ai_agents_blocked") or []
    if blocked:
        f.finding(
            "ACC-AI-CRAWLER-BLOCKED",
            "robots.txt blocks AI assistant crawlers",
            "discoverability",
            "Assistants that fetch pages live identify with these user agents. "
            "A blanket disallow for them means no page on the site can ever be "
            "retrieved or cited, however good the content is. The site stays "
            "fully visible to humans, which is why this is usually unnoticed.",
            "robots.txt disallows all paths for: %s." % ", ".join(sorted(blocked)),
            impact="blocking", affected=len(pages), sampled=max(len(pages), 1),
            page_importance="critical",
            affected_urls=[robots.get("url", "")],
            action={
                "summary": "Decide deliberately which AI crawlers may read the "
                           "site, and remove the blanket disallow for any you "
                           "want citations from.",
                "effort": "low",
                "steps": [
                    "Open robots.txt and locate the user-agent groups: %s."
                    % ", ".join(sorted(blocked)),
                    "If citation in AI assistants is wanted, remove the "
                    "`Disallow: /` line from those groups, or narrow it to the "
                    "paths that genuinely must stay private.",
                    "Keep the exclusion only where it is a considered licensing "
                    "decision rather than a copied default.",
                    "Leave authenticated, checkout and account paths disallowed "
                    "for every agent.",
                ],
                "example": "User-agent: GPTBot\nDisallow: /account/\nDisallow: /checkout/\nAllow: /",
                "expected_impact": "Pages become eligible for retrieval and "
                                   "citation by assistants that honour these agents.",
                "verification": "Re-run the audit; ACC-AI-CRAWLER-BLOCKED should "
                                "no longer fire.",
            })
    else:
        f.na("ACC-AI-CRAWLER-BLOCKED",
             "No AI-specific user-agent group carries a blanket disallow.")

    if robots.get("blanket_disallow"):
        f.finding(
            "ACC-BLANKET-DISALLOW",
            "robots.txt disallows all crawlers from the entire site",
            "discoverability",
            "A wildcard disallow of the site root removes every page from "
            "search and retrieval systems that honour robots.txt.",
            "robots.txt contains `User-agent: *` with `Disallow: /`.",
            impact="blocking", affected=len(pages), sampled=max(len(pages), 1),
            page_importance="critical", affected_urls=[robots.get("url", "")],
            action={
                "summary": "Restrict the disallow to private paths instead of "
                           "the whole site.",
                "effort": "low",
                "steps": ["Replace `Disallow: /` with specific private paths.",
                          "Confirm the staging-site rule has not been copied "
                          "onto production."],
                "expected_impact": "Restores eligibility for indexing and citation.",
                "verification": "Re-run the audit; ACC-BLANKET-DISALLOW clears.",
            })
    else:
        f.na("ACC-BLANKET-DISALLOW", "No wildcard root disallow present.")

    # A 401/403/429 on /robots.txt means we were REFUSED, not that the file is
    # absent. Reporting "no robots.txt served" for a blocked fetch asserts a
    # fact we could not observe, so those statuses record `inconclusive`.
    #
    # The same reasoning covers TRANSPORT failures. An SSLError, a DNS failure
    # or a timeout means the request never reached the origin at all, so the
    # response says nothing about what the site serves — and the cause is very
    # often on our side of the wire (TLS interception, a sandboxed resolver,
    # an egress proxy). Declaring "No robots.txt served" there states a fact
    # about the site that we did not observe, which is exactly the failure this
    # audit refuses to make. Both go to `inconclusive`, with the reason kept.
    BLOCKED_STATUSES = (401, 403, 429)
    status = robots.get("status")
    unreachable = isinstance(status, str) and status not in ("", "200")
    if not robots.get("present") and (status in BLOCKED_STATUSES or unreachable):
        if unreachable:
            reason = ("GET /robots.txt did not complete (%s), so whether a "
                      "robots.txt is served could not be determined. A "
                      "transport-level failure may originate in the auditing "
                      "environment rather than the site." % status)
        else:
            reason = ("GET /robots.txt returned %s (access denied to this "
                      "crawler), so whether a robots.txt is served could not "
                      "be determined." % status)
        f.unknown("ACC-NO-ROBOTS", reason)
    elif not robots.get("present"):
        f.finding(
            "ACC-NO-ROBOTS",
            "No robots.txt served",
            "discoverability",
            "Without robots.txt crawlers apply their own defaults and the site "
            "loses the chance to advertise its sitemap, which is the cheapest "
            "way to make every page discoverable.",
            "GET /robots.txt returned %s." % robots.get("status"),
            impact="weakening", affected=1, sampled=1, confidence="high",
            action={
                "summary": "Publish a robots.txt that permits crawling and "
                           "declares the sitemap.",
                "effort": "low",
                "steps": ["Serve /robots.txt at the domain root.",
                          "Include a `Sitemap:` line pointing at sitemap.xml."],
                "example": "User-agent: *\nAllow: /\n\nSitemap: https://example.com/sitemap.xml",
                "expected_impact": "Crawlers find every URL rather than only "
                                   "those reachable by following links.",
                "verification": "GET /robots.txt returns 200 with a Sitemap line.",
            })
    else:
        f.na("ACC-NO-ROBOTS", "robots.txt served (HTTP 200).")

    # sitemap
    sm = snap.get("sitemap", {})
    url_count = sm.get("url_count", 0)
    # Same rule as robots: an access-denied sitemap fetch is not evidence the
    # sitemap is missing. If every error we recorded is a block (401/403/429),
    # say so rather than claiming the site publishes no sitemap.
    # Transport failures (SSLError, ConnectionError, Timeout) count as "could
    # not determine" for the same reason as a 401/403/429: the request never
    # reached the origin, so its silence is not evidence about the site.
    sm_errors = " ".join(sm.get("errors") or [])
    sm_refused = re.search(r"->\s*(401|403|429)\b", sm_errors)
    # crawl.py records a sitemap failure as either an HTTP status code or the
    # exception class name. Anything non-numeric is therefore a transport-level
    # failure ("Timeout", "SSLError", "ConnectionError"), which is the general
    # rule rather than a list of names that must be kept in sync.
    sm_unreachable = re.search(r"->\s*[A-Za-z]\w*", sm_errors)
    sm_blocked = (url_count == 0 and not sm.get("found")
                  and (sm_refused or sm_unreachable)
                  and not re.search(r"->\s*(404|410)\b", sm_errors))
    if url_count > 0:
        f.na("ACC-NO-SITEMAP", "Sitemap found with %d URLs." % url_count)
    elif sm_blocked:
        f.unknown(
            "ACC-NO-SITEMAP",
            "Sitemap fetches did not complete (%s), so whether the site "
            "publishes a sitemap could not be determined." % sm_errors[:150])
    elif sm.get("found"):
        # A sitemap file WAS fetched but yielded no usable <url> entries within
        # our budgets (a large sitemap index, a partition cutoff, or a slow
        # tree). Claiming "no sitemap exists" here would be a false positive —
        # the site (e.g. ProPublica's 680 KB index) plainly has one. Report the
        # honest, weaker fact instead: the sitemap is present but was not fully
        # enumerable in this pass. Lower impact and confidence match that.
        f.finding(
            "ACC-SITEMAP-NOT-ENUMERABLE",
            "A sitemap exists but no page URLs could be read from it",
            "discoverability",
            "A sitemap that a consumer cannot parse into individual URLs gives "
            "up much of its value: discovery falls back on internal linking, so "
            "deep or newer pages may be missed even though the sitemap is "
            "present.",
            "Checked %s; a sitemap responded but 0 page URLs were extracted "
            "within budget (large index, partitioned tree, or slow response)."
            % (", ".join(sm.get("checked") or ["/sitemap.xml"]) or "/sitemap.xml"),
            impact="weakening", affected=1, sampled=1, confidence="low",
            action={
                "summary": "Ensure the sitemap (and any child sitemaps) return "
                           "well-formed <url><loc> entries with correct escaping.",
                "effort": "low",
                "steps": [
                    "Confirm each <loc> is a valid, resolvable URL.",
                    "Keep sitemap-index partitions reachable and reasonably sized.",
                    "Validate the sitemap with a standard sitemap checker.",
                ],
                "expected_impact": "Consumers can enumerate every URL directly.",
                "verification": "Re-run the audit; sitemap.url_count is non-zero.",
            })
    else:
        f.finding(
            "ACC-NO-SITEMAP",
            "No usable XML sitemap found",
            "discoverability",
            "Without a sitemap, discovery depends entirely on internal linking. "
            "Pages that are not linked from a crawled page are never found, so "
            "deep and newer content is disproportionately missed.",
            "Checked %s; %s." % (
                ", ".join(sm.get("checked") or ["/sitemap.xml"]) or "/sitemap.xml",
                "; ".join(sm.get("errors") or ["no <url> entries returned"])),
            impact="degrading", affected=1, sampled=1,
            action={
                "summary": "Publish an XML sitemap with accurate lastmod values "
                           "and reference it from robots.txt.",
                "effort": "low",
                "steps": [
                    "Generate sitemap.xml covering every canonical, indexable URL.",
                    "Set lastmod from real content-change dates, not build time.",
                    "Add a Sitemap: line to robots.txt.",
                ],
                "expected_impact": "Complete URL discovery without relying on "
                                   "link depth.",
                "verification": "Re-run the audit; sitemap.url_count is non-zero.",
            })

    # status and redirects
    errors = [p for p in pages if p.get("status") and p["status"] >= 400]
    if errors:
        f.finding(
            "ACC-BROKEN-PAGES",
            "Internally linked pages return error status codes",
            "discoverability",
            "Error pages waste crawl budget and break the link paths that "
            "carry crawlers to deeper content.",
            A.ratio_evidence("crawled pages", len(errors), len(pages),
                             "Codes seen: %s." % sorted({p["status"] for p in errors})),
            impact="degrading", affected=len(errors), sampled=len(pages),
            affected_urls=[p["url"] for p in errors],
            action={
                "summary": "Fix or 301-redirect every internally linked URL that "
                           "returns an error.",
                "effort": "low",
                "steps": ["Repair the source link, or redirect the URL to its "
                          "replacement.",
                          "Return 404 only for URLs that genuinely no longer exist."],
                "expected_impact": "Crawl paths stay intact and budget is spent "
                                   "on real content.",
                "verification": "Re-run the audit; no 4xx/5xx among crawled pages.",
            })
    else:
        f.na("ACC-BROKEN-PAGES", "No 4xx/5xx responses among crawled pages.")

    long_chains = [p for p in pages if len(p.get("redirect_chain") or []) > 2]
    if long_chains:
        f.finding(
            "ACC-REDIRECT-CHAINS",
            "Multi-hop redirect chains on crawled URLs",
            "discoverability",
            "Each hop adds latency and some fetchers stop following after a "
            "small number of redirects, so the destination is never read.",
            A.ratio_evidence("crawled pages", len(long_chains), len(pages),
                             "Longest chain: %d hops." % max(
                                 len(p["redirect_chain"]) for p in long_chains)),
            impact="weakening", affected=len(long_chains), sampled=len(pages),
            affected_urls=[p["url"] for p in long_chains],
            action={
                "summary": "Collapse chains so every source URL redirects once "
                           "to its final destination.",
                "effort": "low",
                "steps": ["Rewrite redirect rules to point directly at the final URL.",
                          "Update internal links to reference the destination."],
                "expected_impact": "Faster, more reliable fetches.",
                "verification": "Re-run the audit; no chain exceeds one hop.",
            })
    else:
        f.na("ACC-REDIRECT-CHAINS", "No multi-hop redirect chains observed.")

    # snippet suppression
    # noindex/nosnippet on legal boilerplate (terms, addenda, cardholder
    # agreements) is deliberate and correct: those thin, near-duplicate pages
    # are meant to stay out of the index. Flagging them as a discoverability
    # defect is a false positive, so pages classified `legal` are excluded here.
    html_pages = A.ok_pages(snap)
    considered = [p for p in html_pages if p.get("page_type") != "legal"]
    excluded_legal = len(html_pages) - len(considered)
    suppressed = []
    for p in considered:
        directives = " ".join(filter(None, [
            (p.get("meta_robots") or ""),
            (p.get("headers", {}) or {}).get("x-robots-tag", ""),
        ])).lower()
        if re.search(r"\b(noindex|nosnippet|none)\b", directives) or \
           re.search(r"max-snippet:\s*0", directives):
            suppressed.append(p)
    if not considered:
        f.na("ACC-SNIPPET-SUPPRESSED",
             "Only legal/boilerplate pages were sampled; suppression on those "
             "is expected and not evaluated.")
    elif suppressed:
        f.finding(
            "ACC-SNIPPET-SUPPRESSED",
            "Pages carry directives that block indexing or quotation",
            "discoverability",
            "noindex removes the page from the index; nosnippet and "
            "max-snippet:0 permit indexing but forbid quoting any text, which "
            "prevents the page being used as a cited source even when it ranks.",
            A.ratio_evidence(
                "non-legal HTML pages", len(suppressed), len(considered),
                ("%d legal page(s) excluded as intentionally noindexed."
                 % excluded_legal) if excluded_legal else ""),
            impact="blocking", affected=len(suppressed), sampled=len(considered),
            affected_urls=[p["final_url"] for p in suppressed],
            action={
                "summary": "Remove noindex/nosnippet from pages that should be "
                           "found and quoted.",
                "effort": "low",
                "steps": ["Audit each listed page and confirm suppression is "
                          "intended.",
                          "Remove the directive where the page is public content.",
                          "Prefer max-snippet:-1 to allow full quotation."],
                "expected_impact": "Pages become quotable, which is a "
                                   "precondition for citation.",
                "verification": "Re-run the audit; ACC-SNIPPET-SUPPRESSED clears.",
            })
    else:
        f.na("ACC-SNIPPET-SUPPRESSED",
             "No indexing or snippet suppression directives found.")

    # canonical
    if html_pages:
        missing = [p for p in html_pages if not p.get("canonical")]
        if len(missing) > len(html_pages) * 0.5:
            f.finding(
                "ACC-CANONICAL-MISSING",
                "Most pages declare no canonical URL",
                "discoverability",
                "Without a canonical, parameter and slash variants of the same "
                "page compete as separate documents, splitting the signals that "
                "would otherwise accumulate on one authoritative URL.",
                A.ratio_evidence("HTML pages", len(missing), len(html_pages)),
                impact="weakening", affected=len(missing), sampled=len(html_pages),
                affected_urls=[p["final_url"] for p in missing],
                action={
                    "summary": "Add a self-referencing canonical link to every page.",
                    "effort": "low",
                    "steps": ["Emit <link rel=\"canonical\"> with the absolute "
                              "preferred URL on every template.",
                              "Ensure the canonical matches the sitemap entry."],
                    "example": '<link rel="canonical" href="https://example.com/page">',
                    "expected_impact": "Duplicate variants consolidate onto one URL.",
                    "verification": "Re-run the audit; canonical coverage above 50%.",
                })
        else:
            f.na("ACC-CANONICAL-MISSING",
                 "Canonical present on %d/%d HTML pages."
                 % (len(html_pages) - len(missing), len(html_pages)))
    else:
        f.unknown("ACC-CANONICAL-MISSING", "No HTML pages were retrieved.")

    f.write(workdir)


if __name__ == "__main__":
    run(A.parse_args(SKILL).workdir)
