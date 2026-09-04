#!/usr/bin/env python3
"""Step two of the pipeline: once a machine is inside, can it read the page?

Every check here answers the same question in a different way: is the
substance present as text in what a non-browser client receives, or does it
only exist for a human looking at a rendered screen?
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

SKILL = "machine-readability"

# Facts that are commonly locked into images and matter to an assistant.
FACT_WORDS = re.compile(
    r"\b(price|pricing|cost|from \$|hours|opening|timings|phone|call|email|"
    r"address|menu|spec|specification|dimensions|warranty|plan|tier)\b", re.I)

DECORATIVE_HINT = re.compile(
    r"(icon|logo|sprite|spacer|bg|background|divider|arrow|chevron|pattern)",
    re.I)


def render_gap(page):
    """Fraction of text that exists only after JavaScript runs."""
    raw = A.word_count(page.get("text") or "")
    rendered = A.word_count(page.get("rendered_text") or "")
    if rendered == 0:
        return None
    if rendered <= raw:
        return 0.0
    return (rendered - raw) / float(rendered)


def run(workdir):
    snap = A.load_snapshot(workdir)
    f = A.Fragment(SKILL)
    pages = A.ok_pages(snap)

    if not pages:
        f.unknown("MR-ALL", "No HTML pages available in the snapshot.")
        f.write(workdir)
        return

    # -- 1. JS render gap ----------------------------------------------------
    if snap.get("render_mode") != "headless":
        # Say *why* rendering did not happen. "No browser installed" and "the
        # auditor chose --no-render" are different facts, and reporting the
        # first when the second is true reads as the tool being unable to tell
        # a missing capability from a disabled one. The static-HTML proxy
        # (MR-EMPTY-SHELL) runs regardless and catches the worst offenders.
        reason = {
            "browser-absent":
                "No headless browser is installed on this machine, so raw and "
                "rendered text could not be compared. Install Playwright to "
                "evaluate this check.",
            "disabled-by-flag":
                "Headless rendering was disabled for this run (--no-render), so "
                "raw and rendered text were not compared. Re-run with rendering "
                "enabled on a machine that has Playwright to evaluate this check.",
            "launch-failed":
                "A headless browser is installed but failed to launch on this "
                "run, so raw and rendered text could not be compared.",
        }.get(snap.get("render_status"),
              "Rendered DOM was unavailable on this run, so raw and rendered "
              "text could not be compared.")
        f.unknown(
            "MR-RENDER-GAP",
            reason + " A static-HTML proxy check was run instead "
                     "(MR-EMPTY-SHELL).")
    else:
        rendered_pages = [p for p in pages if p.get("rendered_text")]
        gapped = [(p, g) for p in rendered_pages
                  for g in [render_gap(p)] if g is not None and g > 0.30]
        if gapped:
            worst = max(g for _, g in gapped)
            f.finding(
                "MR-RENDER-GAP",
                "Substantial page content exists only after JavaScript runs",
                "discoverability",
                "Many retrieval fetchers read the HTML the server returns and "
                "do not execute JavaScript. Content injected client-side is "
                "invisible to them, so a page that looks complete on screen "
                "arrives at the model nearly empty.",
                A.ratio_evidence(
                    "rendered pages", len(gapped), len(rendered_pages),
                    "Worst page hides %.0f%% of its text behind JS." % (worst * 100)),
                impact="blocking", affected=len(gapped), sampled=len(rendered_pages),
                page_importance="critical",
                affected_urls=[p["final_url"] for p, _ in gapped],
                action={
                    "summary": "Server-render or pre-render the primary content "
                               "so it is present in the initial HTML response.",
                    "effort": "high",
                    "steps": [
                        "Identify which content blocks are missing from the raw "
                        "HTML on the listed pages.",
                        "Move primary content to server-side rendering, static "
                        "generation, or pre-rendering for bots.",
                        "Keep client-side rendering for genuinely interactive "
                        "widgets only.",
                        "Verify with `curl -s URL | grep` for a distinctive "
                        "sentence from the body copy.",
                    ],
                    "expected_impact": "The body copy becomes available to every "
                                       "fetcher, not only to browsers.",
                    "verification": "Re-run the audit; render gap falls below 30%.",
                })
        else:
            f.na("MR-RENDER-GAP",
                 "Raw and rendered text agree within tolerance on all "
                 "%d rendered pages." % len(rendered_pages))

    # -- 2. Empty-shell proxy (works without a browser) ----------------------
    # A genuine client-rendered shell returns almost nothing in the raw HTML:
    # little body text, many scripts, AND few links, because the navigation is
    # injected client-side too. That last condition is what separates a real
    # SPA shell from a perfectly server-rendered index or listing page, which
    # is legitimately text-light but link-rich. Page types where thin prose is
    # expected (legal indexes, listings, contact) are excluded outright, so a
    # short legal landing page is never mistaken for an empty application shell.
    THIN_OK = ("legal", "listing", "category", "contact")
    shells = [p for p in pages
              if p.get("page_type") not in THIN_OK
              and A.word_count(p.get("body_text") or "") < 60
              and p.get("scripts", 0) >= 5
              and p.get("internal_links", 0) < 5]
    if shells:
        f.finding(
            "MR-EMPTY-SHELL",
            "Pages return almost no body text in the raw HTML response",
            "discoverability",
            "A response carrying many script tags but little text is the "
            "signature of a client-rendered application shell. A fetcher that "
            "does not execute scripts receives no substance to extract or quote.",
            A.ratio_evidence(
                "HTML pages", len(shells), len(pages),
                "Each has under 60 words of body text with 5 or more scripts."),
            impact="blocking", affected=len(shells), sampled=len(pages),
            page_importance="critical", confidence="medium",
            affected_urls=[p["final_url"] for p in shells],
            action={
                "summary": "Deliver the main content in the server response for "
                           "these routes.",
                "effort": "high",
                "steps": ["Confirm with `curl -s URL` that the body copy is absent.",
                          "Enable server-side rendering or static generation for "
                          "these routes."],
                "expected_impact": "Content becomes extractable without a browser.",
                "verification": "Raw HTML contains the body copy; check clears.",
            })
    else:
        f.na("MR-EMPTY-SHELL",
             "All pages return meaningful body text in the raw response.")

    # -- 3. Facts locked in images ------------------------------------------
    offenders, total_imgs = [], 0
    for p in pages:
        imgs = p.get("images") or []
        total_imgs += len(imgs)
        text = p.get("body_text") or ""
        fact_imgs = [i for i in imgs
                     if FACT_WORDS.search((i.get("src") or ""))
                     and not (i.get("alt") or "").strip()]
        if fact_imgs and A.word_count(text) < 250:
            offenders.append(p)
    if offenders:
        f.finding(
            "MR-FACTS-IN-IMAGES",
            "Fact-bearing images carry no alt text on text-sparse pages",
            "discoverability",
            "A price list, spec table or opening-hours panel rendered as an "
            "image is invisible to text extraction. With no alt text and little "
            "surrounding copy, the fact simply does not exist for the machine.",
            A.ratio_evidence("HTML pages", len(offenders), len(pages),
                             "Images named for pricing, hours or specs lack alt "
                             "text and the page carries under 250 words."),
            impact="degrading", affected=len(offenders), sampled=len(pages),
            confidence="medium",
            affected_urls=[p["final_url"] for p in offenders],
            action={
                "summary": "Restate every fact currently carried only by an "
                           "image as real HTML text.",
                "effort": "medium",
                "steps": [
                    "Replace image-rendered price lists and spec sheets with "
                    "HTML tables holding the same values.",
                    "Give every content-bearing image descriptive alt text "
                    "stating the fact it conveys.",
                    "Keep images as visual reinforcement, not as the sole carrier.",
                ],
                "expected_impact": "Facts become extractable and quotable.",
                "verification": "Re-run the audit; the check clears.",
            })
    else:
        f.na("MR-FACTS-IN-IMAGES",
             "No text-sparse pages depend on unlabelled fact-bearing images.")

    # -- 4. Missing alt text generally --------------------------------------
    content_imgs, missing_alt = 0, 0
    for p in pages:
        for i in p.get("images") or []:
            src = i.get("src") or ""
            if DECORATIVE_HINT.search(src):
                continue
            content_imgs += 1
            if i.get("alt") is None or not (i.get("alt") or "").strip():
                missing_alt += 1
    if content_imgs >= 10 and missing_alt / float(content_imgs) > 0.4:
        f.finding(
            "MR-ALT-COVERAGE",
            "Most content images have no alt text",
            "discoverability",
            "Alt text is the only textual representation of an image available "
            "to an extractor. Without it the visual content contributes nothing "
            "to what a machine understands the page to be about.",
            A.ratio_evidence("content images", missing_alt, content_imgs),
            impact="weakening", affected=missing_alt, sampled=content_imgs,
            action={
                "summary": "Add descriptive alt text to content images; leave it "
                           "empty only for genuinely decorative ones.",
                "effort": "medium",
                "steps": ["Write alt text that states what the image shows, not "
                          "its filename.",
                          "Use alt=\"\" for decoration so extractors skip it "
                          "deliberately."],
                "expected_impact": "Image-borne meaning becomes machine-visible.",
                "verification": "Alt coverage exceeds 60% of content images.",
            })
    elif content_imgs < 10:
        f.na("MR-ALT-COVERAGE",
             "Too few content images (%d) to assess coverage reliably."
             % content_imgs)
    else:
        f.na("MR-ALT-COVERAGE",
             "Alt text present on %d/%d content images."
             % (content_imgs - missing_alt, content_imgs))

    # -- 5. Heading semantics -----------------------------------------------
    no_h1 = [p for p in pages if not p.get("h1")]
    multi_h1 = [p for p in pages if len(p.get("h1") or []) > 1]
    if len(no_h1) > len(pages) * 0.3:
        f.finding(
            "MR-NO-H1",
            "Many pages have no H1 heading",
            "discoverability",
            "The H1 is the strongest in-page statement of what a document is "
            "about. Without it, chunking and topic assignment fall back to the "
            "title tag or to guesswork over body text.",
            A.ratio_evidence("HTML pages", len(no_h1), len(pages)),
            impact="weakening", affected=len(no_h1), sampled=len(pages),
            affected_urls=[p["final_url"] for p in no_h1],
            action={
                "summary": "Give every page exactly one H1 stating its subject.",
                "effort": "low",
                "steps": ["Add a single descriptive H1 per template.",
                          "Do not use the site name as the H1 on interior pages."],
                "expected_impact": "Clearer topic assignment per document.",
                "verification": "Every crawled page reports one H1.",
            })
    else:
        f.na("MR-NO-H1", "H1 present on %d/%d pages."
             % (len(pages) - len(no_h1), len(pages)))

    if len(multi_h1) > len(pages) * 0.3:
        f.finding(
            "MR-MULTI-H1",
            "Many pages declare multiple H1 headings",
            "discoverability",
            "Several competing top-level headings make the document's primary "
            "subject ambiguous, which weakens chunk-to-topic assignment.",
            A.ratio_evidence("HTML pages", len(multi_h1), len(pages)),
            impact="weakening", affected=len(multi_h1), sampled=len(pages),
            confidence="medium",
            affected_urls=[p["final_url"] for p in multi_h1],
            action={
                "summary": "Demote secondary H1 elements to H2.",
                "effort": "low",
                "steps": ["Keep one H1 per page and rank the rest beneath it."],
                "expected_impact": "Unambiguous document subject.",
                "verification": "One H1 per page.",
            })
    else:
        f.na("MR-MULTI-H1", "Heading hierarchy has a single H1 on most pages.")

    # -- 6. Landmark structure ----------------------------------------------
    no_main = [p for p in pages if not p.get("has_main")]
    if len(no_main) > len(pages) * 0.6:
        f.finding(
            "MR-NO-MAIN-LANDMARK",
            "Pages provide no main content landmark",
            "discoverability",
            "Without a <main> element or role=\"main\", an extractor cannot "
            "separate body copy from navigation and footer boilerplate, so "
            "chunks are diluted with repeated site furniture.",
            A.ratio_evidence("HTML pages", len(no_main), len(pages)),
            impact="weakening", affected=len(no_main), sampled=len(pages),
            action={
                "summary": "Wrap the unique page content in a <main> element.",
                "effort": "low",
                "steps": ["Add <main> around body content in each template.",
                          "Use <nav>, <header> and <footer> for chrome."],
                "expected_impact": "Cleaner extraction with less boilerplate "
                                   "diluting each chunk.",
                "verification": "Main landmark present on most pages.",
            })
    else:
        f.na("MR-NO-MAIN-LANDMARK", "Main landmark present on most pages.")

    # -- 7. Content trapped in iframes --------------------------------------
    heavy_iframe = [p for p in pages
                    if len(p.get("iframes") or []) > 0
                    and A.word_count(p.get("body_text") or "") < 150]
    if heavy_iframe:
        f.finding(
            "MR-IFRAME-CONTENT",
            "Text-sparse pages appear to carry their content inside iframes",
            "discoverability",
            "Iframe content belongs to a different document. Extractors "
            "generally do not follow it, so the substance is attributed "
            "elsewhere or lost entirely.",
            A.ratio_evidence("HTML pages", len(heavy_iframe), len(pages),
                             "Under 150 words of own text alongside embedded frames."),
            impact="degrading", affected=len(heavy_iframe), sampled=len(pages),
            confidence="medium",
            affected_urls=[p["final_url"] for p in heavy_iframe],
            action={
                "summary": "Move substantive content into the host page and keep "
                           "iframes for third-party widgets only.",
                "effort": "medium",
                "steps": ["Inline the text currently delivered by the frame.",
                          "Where a widget must stay, add a text summary beside it."],
                "expected_impact": "Content is attributed to the page that shows it.",
                "verification": "Own-text word count rises above 150.",
            })
    else:
        f.na("MR-IFRAME-CONTENT", "No text-sparse iframe-dependent pages found.")

    f.write(workdir)


if __name__ == "__main__":
    run(A.parse_args(SKILL).workdir)
