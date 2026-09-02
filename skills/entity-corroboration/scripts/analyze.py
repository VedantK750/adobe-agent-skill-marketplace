#!/usr/bin/env python3
"""Off-site agreement and entity ambiguity.

Two mechanisms from the appendix: a claim repeated across many independent
sources is treated as more reliable than one that exists in a single place;
and entities sharing a name are conflated unless something distinguishes them.

Off-site verification needs a search capability. This script performs the
on-site half deterministically and writes a `corroboration_targets.json`
worklist that the skill's agent-facing procedure completes with WebSearch. If
no search is available the affected checks report `inconclusive` rather than
asserting anything unverified.
"""

import json
import os
import re
import sys
import urllib.parse as up

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

SKILL = "entity-corroboration"

SOCIAL = re.compile(
    r"(linkedin\.com|twitter\.com|x\.com|facebook\.com|instagram\.com|"
    r"youtube\.com|github\.com|crunchbase\.com|wikidata\.org|wikipedia\.org|"
    r"g\.page|goo\.gl/maps|maps\.google|yelp\.com|trustpilot\.com)", re.I)

PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
POSTCODE_HINT = re.compile(
    r"\b(\d{5,6}|[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2})\b")
ADDRESS_HINT = re.compile(
    r"\b(street|road|avenue|lane|sector|floor|suite|block|building|plot|"
    r"st\.|rd\.|ave\.)\b", re.I)


def canonical_claims(snap):
    """The facts a corroboration search should try to verify."""
    claims = {}
    home = next((p for p in snap.get("pages", [])
                 if p.get("page_type") == "home"), None)
    about = next((p for p in snap.get("pages", [])
                  if p.get("page_type") == "about"), None)
    contact = next((p for p in snap.get("pages", [])
                    if p.get("page_type") == "contact"), None)

    if home:
        claims["name"] = (home.get("og_title") or home.get("title") or "").strip()
        claims["description"] = (home.get("meta_description") or "").strip()
    claims["site_type"] = snap.get("site_type")

    text = " ".join(filter(None, [
        (contact or {}).get("body_text", ""),
        (home or {}).get("body_text", ""),
        (about or {}).get("body_text", ""),
    ]))[:8000]

    phones = [p.strip() for p in PHONE.findall(text)]
    claims["phones"] = sorted({re.sub(r"[^\d+]", "", p) for p in phones
                               if len(re.sub(r"[^\d]", "", p)) >= 9})[:5]
    claims["has_address_signal"] = bool(
        ADDRESS_HINT.search(text) and POSTCODE_HINT.search(text))
    return claims


def run(workdir):
    snap = A.load_snapshot(workdir)
    f = A.Fragment(SKILL)
    pages = A.ok_pages(snap)

    if not pages:
        f.unknown("EC-ALL", "No HTML pages available in the snapshot.")
        f.write(workdir)
        return

    claims = canonical_claims(snap)

    # -- 1. Outbound identity links -----------------------------------------
    # Profiles count whether they are reached by an anchor or declared in
    # Organization.sameAs. Counting only anchors flags sites that have done
    # the work properly in structured data, which is a false positive.
    profiles = set()
    for p in pages:
        candidates = list(p.get("outbound_links") or [])
        for raw in p.get("jsonld_raw") or []:
            try:
                data = json.loads(raw)
            except Exception:
                candidates.extend(re.findall(r'https?://[^"\s\\]+', raw or ""))
                continue
            stack = [data]
            while stack:
                n = stack.pop()
                if isinstance(n, dict):
                    for k, v in n.items():
                        if k.lower() == "sameas":
                            if isinstance(v, str):
                                candidates.append(v)
                            elif isinstance(v, list):
                                candidates.extend(x for x in v if isinstance(x, str))
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(n, list):
                    stack.extend(n)
        for link in candidates:
            m = SOCIAL.search(link)
            if m:
                profiles.add(m.group(1).lower())
    if len(profiles) < 2:
        f.finding(
            "EC-FEW-EXTERNAL-PROFILES",
            "The site links to almost no external profiles",
            "discoverability",
            "External profiles are the paths by which a machine connects this "
            "site to independent descriptions of the same entity. With no such "
            "links, corroborating evidence — if it exists at all — may never be "
            "tied back to this brand.",
            "Distinct external identity platforms linked from the site: %s."
            % (", ".join(sorted(profiles)) or "none"),
            impact="weakening", affected=1, sampled=1,
            action={
                "summary": "Link every official profile from the site and mirror "
                           "the same set in Organization.sameAs.",
                "effort": "low",
                "steps": [
                    "Add footer links to the brand's official profiles.",
                    "List the identical URLs in the Organization sameAs array.",
                    "Claim any authoritative directory listing for the sector "
                    "that is currently unclaimed.",
                ],
                "expected_impact": "External mentions become attributable to "
                                   "this entity.",
                "verification": "Two or more distinct platforms linked.",
            })
    else:
        f.na("EC-FEW-EXTERNAL-PROFILES",
             "Site links to %d external identity platforms." % len(profiles))

    # -- 2. NAP presence and consistency ------------------------------------
    if snap.get("site_type") == "local-business":
        if not claims.get("phones") or not claims.get("has_address_signal"):
            f.finding(
                "EC-NAP-INCOMPLETE",
                "Name, address and phone are not all stated as plain text",
                "discoverability",
                "For a business tied to a place, the address and phone number "
                "are the facts most often asked for and the ones most often "
                "rendered as an image or map embed. Stated inconsistently or "
                "non-textually, they cannot be matched against external "
                "listings, and the entity fails to consolidate.",
                "Phone strings found: %d. Address signal present: %s."
                % (len(claims.get("phones") or []),
                   claims.get("has_address_signal")),
                impact="degrading", affected=1, sampled=1, page_importance="high",
                confidence="medium",
                action={
                    "summary": "State name, address and phone as text on every "
                               "page footer, in one identical format.",
                    "effort": "low",
                    "steps": [
                        "Put NAP in the footer as selectable text, not an image.",
                        "Use byte-identical formatting everywhere it appears.",
                        "Mirror it in LocalBusiness JSON-LD and in every "
                        "external directory listing.",
                    ],
                    "expected_impact": "Listings consolidate onto one entity "
                                       "instead of fragmenting.",
                    "verification": "EC-NAP-INCOMPLETE clears.",
                })
        else:
            f.na("EC-NAP-INCOMPLETE",
                 "Textual phone and address signals present.")
    else:
        f.na("EC-NAP-INCOMPLETE",
             "Site type is %s, not a place-based business."
             % snap.get("site_type"))

    # -- 3. Self-description consistency ------------------------------------
    home = next((p for p in pages if p.get("page_type") == "home"), None)
    if home:
        title = (home.get("title") or "").strip()
        og = (home.get("og_title") or "").strip()
        desc = (home.get("meta_description") or "").strip()
        if title and og and title.lower() != og.lower() and \
                og.lower() not in title.lower() and title.lower() not in og.lower():
            f.finding(
                "EC-INCONSISTENT-SELF-DESCRIPTION",
                "The site describes itself differently in title and Open Graph",
                "discoverability",
                "Different names for the same entity in the same document give "
                "a consumer conflicting evidence about what the brand is called, "
                "which is exactly the ambiguity that causes entities to be "
                "merged or mistaken for one another.",
                "Title: \"%s\". og:title: \"%s\"." % (title[:70], og[:70]),
                impact="weakening", affected=1, sampled=1, confidence="medium",
                affected_urls=[home["final_url"]],
                action={
                    "summary": "Use one canonical brand name in title, og:title "
                               "and Organization.name.",
                    "effort": "low",
                    "steps": ["Pick the exact legal or trading name.",
                              "Apply it identically across all three fields."],
                    "expected_impact": "Consistent naming evidence.",
                    "verification": "The three fields agree.",
                })
        elif not desc:
            f.na("EC-INCONSISTENT-SELF-DESCRIPTION",
                 "Home title and og:title agree; no description to compare.")
        else:
            f.na("EC-INCONSISTENT-SELF-DESCRIPTION",
                 "Self-description is consistent across title fields.")
    else:
        f.unknown("EC-INCONSISTENT-SELF-DESCRIPTION",
                  "Home page was not retrieved.")

    # -- 4. Off-site corroboration: requires search -------------------------
    targets = {
        "site": snap.get("site"),
        "claims": claims,
        "queries": [],
    }
    name = (claims.get("name") or snap.get("site") or "").split("|")[0].strip()
    if name:
        targets["queries"] = [
            '"%s"' % name,
            '"%s" review' % name,
            '"%s" %s' % (name, claims.get("site_type") or ""),
            '%s -site:%s' % (name, snap.get("site")),
        ]
    with open(os.path.join(workdir, "corroboration_targets.json"), "w",
              encoding="utf-8") as fh:
        json.dump(targets, fh, indent=2)

    if os.environ.get("AUDIT_SEARCH_RESULTS"):
        # The agent procedure writes search findings here as JSON.
        try:
            with open(os.environ["AUDIT_SEARCH_RESULTS"], "r",
                      encoding="utf-8") as fh:
                results = json.load(fh)
        except Exception as exc:
            f.unknown("EC-SINGLE-SOURCE-CLAIMS",
                      "Search results file unreadable: %s" % exc)
            results = None
        if results is not None:
            domains = {up.urlparse(u).netloc.lower()
                       for u in results.get("urls", [])}
            domains.discard(snap.get("site", "").lower())
            if len(domains) < 3:
                f.finding(
                    "EC-SINGLE-SOURCE-CLAIMS",
                    "The brand's claims are repeated on very few independent domains",
                    "discoverability",
                    "A fact stated only by the party it benefits is treated as "
                    "fragile. Agreement across unrelated domains is what turns "
                    "a claim into something a system will repeat.",
                    "Independent domains mentioning the brand: %d (%s)."
                    % (len(domains), ", ".join(sorted(domains)[:5]) or "none"),
                    impact="degrading", affected=1, sampled=1,
                    action={
                        "summary": "Get the same canonical facts published on "
                                   "independent domains.",
                        "effort": "high",
                        "steps": [
                            "Write one canonical description and reuse it "
                            "verbatim in every directory, profile and press "
                            "mention.",
                            "Claim listings on the authoritative directories for "
                            "the sector.",
                            "Pursue mentions on domains with no commercial tie "
                            "to the brand.",
                        ],
                        "expected_impact": "Claims move from single-source to "
                                           "corroborated.",
                        "verification": "Independent mentioning domains exceed 3.",
                    })
                if len(domains) >= 3:
                    f.na("EC-SINGLE-SOURCE-CLAIMS", "Corroboration adequate.")
            else:
                f.na("EC-SINGLE-SOURCE-CLAIMS",
                     "%d independent domains mention the brand." % len(domains))
    else:
        f.unknown(
            "EC-SINGLE-SOURCE-CLAIMS",
            "Off-site corroboration requires a search capability, which was "
            "not available on this run. A query worklist has been written to "
            "corroboration_targets.json for the agent procedure to complete.")
        f.unknown(
            "EC-NAME-COLLISION",
            "Entity-ambiguity detection requires a search capability, which "
            "was not available on this run. See corroboration_targets.json.")

    f.write(workdir)


if __name__ == "__main__":
    run(A.parse_args(SKILL).workdir)
