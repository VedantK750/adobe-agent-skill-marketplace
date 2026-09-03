#!/usr/bin/env python3
"""The second half of the problem: the visitor arrived, do they stay?

The framing that keeps these checks from drifting into generic usability
review: a visitor referred by an assistant lands on a deep page, holding a
specific question, with no prior relationship to the brand and no patience.
Every check below asks whether that particular visitor can orient, get an
answer, and find a next step.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

SKILL = "engagement-audit"

CTA_RE = re.compile(
    r"\b(contact us|get in touch|book|buy|shop now|start|sign up|subscribe|"
    r"request a demo|get a quote|enquire|call us|download|learn more|"
    r"add to (?:cart|bag|basket))\b", re.I)
CONSENT_RE = re.compile(
    r"\b(cookie|consent|gdpr|we use cookies|accept all|manage preferences)\b", re.I)
INTERRUPT_RE = re.compile(
    r"\b(subscribe to our newsletter|sign up for our|join our mailing list|"
    r"before you go|don't leave|exit-intent|modal|popup|pop-up)\b", re.I)
SEARCH_RE = re.compile(
    r'(?is)<input[^>]*type\s*=\s*["\']search["\']|role\s*=\s*["\']search["\']|'
    r'name\s*=\s*["\']q["\']|placeholder\s*=\s*["\'][^"\']*search')
AUTOPLAY_RE = re.compile(r"(?is)<(?:video|audio)[^>]*\bautoplay\b")

HEAVY_BYTES = 2_500_000
SLOW_MS = 2500


def run(workdir):
    snap = A.load_snapshot(workdir)
    f = A.Fragment(SKILL)
    pages = A.ok_pages(snap)

    if not pages:
        f.unknown("EN-ALL", "No HTML pages available in the snapshot.")
        f.write(workdir)
        return

    # Pages an assistant would plausibly send someone to.
    landing = [p for p in pages
               if p.get("page_type") in ("home", "product", "article",
                                         "documentation", "contact", "about")]
    landing = landing or pages

    # -- 1. Mobile viewport --------------------------------------------------
    no_viewport = [p for p in pages if not p.get("viewport")]
    if len(no_viewport) > len(pages) * 0.3:
        f.finding(
            "EN-NO-VIEWPORT",
            "Pages declare no mobile viewport",
            "engagement",
            "Assistant referrals arrive disproportionately on phones. Without a "
            "viewport declaration the page renders at desktop width and is "
            "zoomed out to illegibility, which produces an immediate bounce "
            "before any content is read.",
            A.ratio_evidence("HTML pages", len(no_viewport), len(pages)),
            impact="degrading", affected=len(no_viewport), sampled=len(pages),
            page_importance="high",
            affected_urls=[p["final_url"] for p in no_viewport],
            action={
                "summary": "Add a responsive viewport meta tag to every template.",
                "effort": "low",
                "steps": ["Add the viewport meta tag to the base template.",
                          "Verify body text renders at 16px or larger on mobile.",
                          "Check tap targets are at least 44px."],
                "example": '<meta name="viewport" content="width=device-width, '
                           'initial-scale=1">',
                "expected_impact": "Mobile arrivals can read the page without "
                                   "zooming.",
                "verification": "Viewport present on all pages.",
            })
    else:
        f.na("EN-NO-VIEWPORT", "Viewport declared on most pages.")

    # -- 2. Page weight ------------------------------------------------------
    heavy = [p for p in landing if p.get("bytes", 0) > HEAVY_BYTES]
    if heavy:
        f.finding(
            "EN-HEAVY-PAGES",
            "Landing pages ship very large HTML payloads",
            "engagement",
            "A visitor who arrived from an assistant has no loyalty and a "
            "specific question. Every second before content appears converts "
            "part of that traffic into a bounce, and the bounce happens before "
            "the answer is ever seen.",
            A.ratio_evidence("landing-candidate pages", len(heavy), len(landing),
                             "Largest: %.1f MB." % (max(p["bytes"] for p in heavy) / 1e6)),
            impact="degrading", affected=len(heavy), sampled=len(landing),
            confidence="medium",
            affected_urls=[p["final_url"] for p in heavy],
            action={
                "summary": "Reduce payload on the pages most likely to receive "
                           "referrals.",
                "effort": "medium",
                "steps": ["Compress and lazy-load below-the-fold images.",
                          "Defer non-critical scripts.",
                          "Inline critical CSS and load the rest asynchronously."],
                "expected_impact": "Content appears sooner, retaining impatient "
                                   "arrivals.",
                "verification": "Landing pages fall below 2.5 MB.",
            })
    else:
        f.na("EN-HEAVY-PAGES", "No landing-candidate page exceeds 2.5 MB.")

    slow = [p for p in landing if p.get("elapsed_ms", 0) > SLOW_MS]
    if slow:
        f.finding(
            "EN-SLOW-RESPONSE",
            "Server response times are slow on landing pages",
            "engagement",
            "Slow first-byte time delays everything downstream and also limits "
            "how much of the site a crawler will fetch in one pass, so it "
            "damages engagement and discoverability together.",
            A.ratio_evidence("landing-candidate pages", len(slow), len(landing),
                             "Slowest observed: %d ms." % max(
                                 p["elapsed_ms"] for p in slow)),
            impact="weakening", affected=len(slow), sampled=len(landing),
            confidence="medium",
            affected_urls=[p["final_url"] for p in slow],
            action={
                "summary": "Investigate and reduce server response time.",
                "effort": "medium",
                "steps": ["Add full-page caching or a CDN for anonymous traffic.",
                          "Profile slow database queries on these routes."],
                "expected_impact": "Faster first byte for visitors and crawlers.",
                "verification": "Response times fall below 2.5 s.",
            })
    else:
        f.na("EN-SLOW-RESPONSE", "Response times within tolerance.")

    # -- 3. Dead-end pages ---------------------------------------------------
    dead_ends = [p for p in landing if p.get("internal_links", 0) < 3]
    if dead_ends:
        f.finding(
            "EN-DEAD-END-PAGES",
            "Landing pages offer almost no onward links",
            "engagement",
            "A visitor arriving mid-funnel has not seen the home page and has "
            "no mental model of the site. A page with no onward links answers "
            "one question and then ends the session, forfeiting every "
            "subsequent step.",
            A.ratio_evidence("landing-candidate pages", len(dead_ends),
                             len(landing), "Fewer than three internal links each."),
            impact="degrading", affected=len(dead_ends), sampled=len(landing),
            affected_urls=[p["final_url"] for p in dead_ends],
            action={
                "summary": "Add contextual onward links and a clear next step to "
                           "every content page.",
                "effort": "medium",
                "steps": [
                    "Link to the two or three most relevant related pages from "
                    "within the body copy.",
                    "Add a related-content block at the end of each page.",
                    "Ensure primary navigation is reachable from every page.",
                ],
                "expected_impact": "Deep arrivals continue into a second and "
                                   "third page instead of leaving.",
                "verification": "All landing pages carry three or more internal "
                                "links.",
            })
    else:
        f.na("EN-DEAD-END-PAGES", "Landing pages offer onward navigation.")

    # -- 4. Orientation ------------------------------------------------------
    # Either a navigation landmark or breadcrumbs give a deep arrival somewhere
    # to orient from. Breadcrumbs alone are orientation, so a page that has them
    # is not a finding even without a <nav> element — counting it as one was a
    # false positive on sites that navigate purely by breadcrumb trail.
    no_nav = [p for p in landing
              if not p.get("has_nav") and not p.get("has_breadcrumb")]
    if len(no_nav) > len(landing) * 0.4:
        f.finding(
            "EN-NO-ORIENTATION",
            "Pages provide no navigation landmark for orientation",
            "engagement",
            "Someone who lands deep in the site needs to know where they are "
            "and what else exists. Without navigation or breadcrumbs the page "
            "is an island, and the visitor cannot tell whether the rest of the "
            "site is worth exploring.",
            A.ratio_evidence("landing-candidate pages", len(no_nav), len(landing)),
            impact="weakening", affected=len(no_nav), sampled=len(landing),
            affected_urls=[p["final_url"] for p in no_nav],
            action={
                "summary": "Add persistent navigation and breadcrumbs to every "
                           "template.",
                "effort": "low",
                "steps": ["Include a <nav> landmark on all pages.",
                          "Add breadcrumbs showing the path from home.",
                          "Mark breadcrumbs up with BreadcrumbList JSON-LD."],
                "expected_impact": "Deep arrivals orient and explore.",
                "verification": "Navigation present on most pages.",
            })
    else:
        f.na("EN-NO-ORIENTATION", "Navigation landmark present on most pages.")

    # -- 5. Call to action ---------------------------------------------------
    convertible = [p for p in landing
                   if p.get("page_type") in ("home", "product", "contact", "about")]
    if convertible:
        no_cta = [p for p in convertible
                  if not CTA_RE.search(p.get("body_text") or "")]
        if no_cta:
            f.finding(
                "EN-NO-CTA",
                "Conversion-relevant pages state no clear next action",
                "engagement",
                "A visitor whose question has just been answered is at peak "
                "intent. With no explicit next step on the page, that intent "
                "expires where it stands.",
                A.ratio_evidence("conversion-relevant pages", len(no_cta),
                                 len(convertible)),
                impact="degrading", affected=len(no_cta), sampled=len(convertible),
                confidence="medium",
                affected_urls=[p["final_url"] for p in no_cta],
                action={
                    "summary": "Give each page one primary, explicit call to "
                               "action in text.",
                    "effort": "low",
                    "steps": ["Name the action concretely rather than using "
                              "'learn more'.",
                              "Keep one primary action per page.",
                              "Place it where the answer finishes, not only in "
                              "the header."],
                    "expected_impact": "Intent converts at the moment it peaks.",
                    "verification": "Every conversion page states an action.",
                })
        else:
            f.na("EN-NO-CTA", "Conversion-relevant pages state a next action.")
    else:
        f.na("EN-NO-CTA", "No conversion-relevant page types detected.")

    # -- 6. Arrival interruptions -------------------------------------------
    autoplay = [p for p in pages if AUTOPLAY_RE.search(p.get("raw_html") or "")]
    if autoplay:
        f.finding(
            "EN-AUTOPLAY-MEDIA",
            "Pages autoplay video or audio on arrival",
            "engagement",
            "Unrequested sound or motion on arrival is among the most reliable "
            "causes of an immediate back-navigation, particularly on mobile "
            "where the visitor may be in company.",
            A.ratio_evidence("HTML pages", len(autoplay), len(pages)),
            impact="degrading", affected=len(autoplay), sampled=len(pages),
            affected_urls=[p["final_url"] for p in autoplay],
            action={
                "summary": "Remove autoplay, or mute it and require a click.",
                "effort": "low",
                "steps": ["Drop the autoplay attribute.",
                          "If motion is needed for design, keep it muted and "
                          "respect prefers-reduced-motion."],
                "expected_impact": "Removes a common immediate-bounce trigger.",
                "verification": "No autoplay attributes remain.",
            })
    else:
        f.na("EN-AUTOPLAY-MEDIA", "No autoplaying media detected.")

    interrupts = [p for p in landing
                  if INTERRUPT_RE.search(p.get("body_text") or "")]
    if len(interrupts) > len(landing) * 0.5:
        f.finding(
            "EN-INTERRUPTIONS",
            "Newsletter or exit-intent interruption copy appears site-wide",
            "engagement",
            "A first-time arrival referred for a specific question is asked to "
            "subscribe before receiving any value. Interruptions placed before "
            "the answer convert poorly and increase immediate bounces.",
            A.ratio_evidence("landing-candidate pages", len(interrupts),
                             len(landing)),
            impact="weakening", affected=len(interrupts), sampled=len(landing),
            confidence="low",
            affected_urls=[p["final_url"] for p in interrupts],
            action={
                "summary": "Delay subscription prompts until after the visitor "
                           "has read the content.",
                "effort": "low",
                "steps": ["Trigger prompts on scroll depth or second page view, "
                          "not on arrival.",
                          "Prefer an inline block over a blocking overlay."],
                "expected_impact": "The answer is delivered before anything is "
                                   "asked in return.",
                "verification": "No arrival-time interruption on landing pages.",
            })
    else:
        f.na("EN-INTERRUPTIONS", "No site-wide arrival interruption pattern found.")

    # -- 7. Consent handling -------------------------------------------------
    consent = [p for p in landing if CONSENT_RE.search(p.get("body_text") or "")]
    thin_behind_consent = [p for p in consent
                           if A.word_count(p.get("body_text") or "") < 200]
    if thin_behind_consent:
        f.finding(
            "EN-CONSENT-BLOCKS-CONTENT",
            "Consent notices dominate pages that carry little other text",
            "engagement",
            "When the consent notice is most of what the page contains, both a "
            "visitor and an extractor receive the notice rather than the "
            "content. This harms engagement and discoverability at once.",
            A.ratio_evidence("landing-candidate pages", len(thin_behind_consent),
                             len(landing),
                             "Consent language present with under 200 words of "
                             "other body text."),
            impact="degrading", affected=len(thin_behind_consent),
            sampled=len(landing), confidence="medium",
            affected_urls=[p["final_url"] for p in thin_behind_consent],
            action={
                "summary": "Serve full page content alongside the consent "
                           "notice rather than behind it.",
                "effort": "medium",
                "steps": ["Render content in the initial HTML regardless of "
                          "consent state.",
                          "Use a non-blocking banner rather than a full overlay.",
                          "Gate only the tracking scripts, never the content."],
                "expected_impact": "Content reaches both visitors and extractors.",
                "verification": "Body text present independent of consent state.",
            })
    else:
        f.na("EN-CONSENT-BLOCKS-CONTENT",
             "No pages appear to be dominated by consent copy.")

    # -- 8. On-site search ---------------------------------------------------
    if len(pages) >= 15:
        has_search = any(SEARCH_RE.search(p.get("raw_html") or "") for p in pages)
        if not has_search:
            f.finding(
                "EN-NO-SITE-SEARCH",
                "A large site offers no on-site search",
                "engagement",
                "When the landing page does not quite answer the question, "
                "search is the visitor's only recovery path. Without it the "
                "alternative to browsing blindly is leaving.",
                "Crawled %d pages; no search input or search landmark found."
                % len(pages),
                impact="weakening", affected=1, sampled=1, confidence="medium",
                action={
                    "summary": "Add on-site search reachable from every page.",
                    "effort": "medium",
                    "steps": ["Place a search input in the header.",
                              "Ensure result URLs are shareable."],
                    "expected_impact": "Near-miss arrivals recover instead of "
                                       "bouncing.",
                    "verification": "Search available site-wide.",
                })
        else:
            f.na("EN-NO-SITE-SEARCH", "On-site search is present.")
    else:
        f.na("EN-NO-SITE-SEARCH",
             "Site has fewer than 15 crawled pages; search is not yet material.")

    f.write(workdir)


if __name__ == "__main__":
    run(A.parse_args(SKILL).workdir)
