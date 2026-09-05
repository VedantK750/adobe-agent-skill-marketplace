#!/usr/bin/env python3
"""Step three of the pipeline: can a clear fact be quoted out of a chunk?

Retrieval fetches a fragment of a page, not the page. A passage that only
makes sense after reading the two paragraphs above it cannot be quoted, even
when it is well written and perfectly crawlable. These checks measure whether
the prose survives being cut out of context.
"""

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))
import auditlib as A  # noqa: E402

SKILL = "answer-extractability"

QUESTION_HEADING = re.compile(
    r"^(what|why|how|when|where|who|which|can|does|do|is|are|should)\b.*\??$",
    re.I)

# Sentence openers that depend on an antecedent established elsewhere.
DANGLING_OPENER = re.compile(
    r"^(it|this|that|these|those|they|he|she|there|such|its|their|here)\b", re.I)

DEFINITION = re.compile(
    r"\b\w[\w '&-]{1,60}\s+(?:is|are|was|were)\s+(?:a|an|the)\s+\w+", re.I)

STOPWORDS = set("""the a an and or of to in for with on at by from as is are was
were be been it its this that these those our we you your they their he she
his her not no but if then than so such very more most can will would should
about into over under after before between during all any each other some""".split())


def chunk_paragraphs(text, target=90):
    """Approximate retrieval chunks: consecutive sentences up to ~90 words."""
    out, cur, n = [], [], 0
    for s in A.sentences(text):
        w = A.word_count(s)
        if n + w > target and cur:
            out.append(" ".join(cur))
            cur, n = [], 0
        cur.append(s)
        n += w
    if cur:
        out.append(" ".join(cur))
    return out


# Host labels that are never the brand: common subdomains and TLD-ish parts.
NON_BRAND_HOST = {
    "www", "docs", "doc", "blog", "shop", "store", "app", "apps", "help",
    "support", "developer", "developers", "api", "kb", "news", "en", "us",
    "web", "portal", "account", "my", "go", "get", "learn", "community",
    "com", "org", "net", "io", "co", "gov", "edu", "info", "biz",
}


def brand_tokens(snap):
    """Best guess at the brand name, from host and a representative title.

    Returns (tokens, source) where source is:
      "host"  - a distinctive host label was found (e.g. `python` from
                `docs.python.org`). This is a reliable anchor.
      "title" - only title tokens were available; the host was uninformative
                (a bare TLD label, or all-common words). Findings built on this
                must be phrased as a hypothesis, not a fact, because the guess
                can be wrong on an unseen site.
      "none"  - nothing usable; the caller reports inconclusive.

    The host label is chosen carefully: `docs.python.org` must yield `python`,
    not `docs`, or entity-restatement fires a false positive on the entire
    documentation of a site whose name it never actually looked for.
    """
    host = (snap.get("site") or "").lower()
    labels = [l for l in host.split(".") if l]
    brand_label = None
    for l in labels:
        if l not in NON_BRAND_HOST and not re.fullmatch(r"[a-z]{2}", l):
            brand_label = l
            break
    toks = {brand_label} if brand_label else set()
    source = "host" if brand_label else "none"

    title = None
    for p in snap.get("pages", []):
        if p.get("page_type") == "home" and p.get("title"):
            title = p["title"]
            break
    if title is None:
        for p in snap.get("pages", []):
            if p.get("title"):
                title = p["title"]
                break
    if title:
        parts = re.split(r"[|\-–—:·]", title)
        # The brand is usually the shortest, most-repeated segment of a title;
        # take tokens from the first and last segments, which is where it sits.
        for t in re.findall(r"[A-Za-z]{3,}", (parts[-1] + " " + parts[0])):
            if t.lower() not in STOPWORDS:
                toks.add(t.lower())
                if source == "none":
                    source = "title"
    return {t for t in toks if len(t) >= 3}, source


def run(workdir):
    snap = A.load_snapshot(workdir)
    f = A.Fragment(SKILL)
    pages = [p for p in A.ok_pages(snap)
             if p.get("page_type") not in ("legal", "listing")]

    substantive = [p for p in pages
                   if A.word_count(p.get("body_text") or "") >= 120]

    if not substantive:
        f.unknown("AE-ALL",
                  "No page carried 120+ words of extractable body text, so "
                  "prose quality could not be assessed. Resolve the "
                  "machine-readability findings first.")
        f.write(workdir)
        return

    # -- 1. Chunk self-containment ------------------------------------------
    bad_pages, total_chunks, dangling_chunks = [], 0, 0
    for p in substantive:
        chunks = chunk_paragraphs(p.get("body_text") or "")
        if not chunks:
            continue
        dangling = 0
        for c in chunks:
            sents = A.sentences(c)
            if sents and DANGLING_OPENER.match(sents[0]):
                dangling += 1
        total_chunks += len(chunks)
        dangling_chunks += dangling
        if len(chunks) >= 3 and dangling / float(len(chunks)) > 0.35:
            bad_pages.append(p)

    if bad_pages:
        f.finding(
            "AE-CHUNK-DEPENDENCE",
            "Passages open with unresolved references and cannot stand alone",
            "discoverability",
            "Retrieval returns a fragment, not the whole page. A passage "
            "beginning \"It offers 24/7 support\" loses its subject the moment "
            "it is separated from the paragraph that named the subject, so it "
            "cannot be quoted as an answer even when it is the right answer.",
            A.ratio_evidence(
                "substantive pages", len(bad_pages), len(substantive),
                "Across the site %d/%d approximate chunks open with an "
                "unresolved reference." % (dangling_chunks, total_chunks)),
            impact="degrading", affected=len(bad_pages), sampled=len(substantive),
            confidence="medium",
            affected_urls=[p["final_url"] for p in bad_pages],
            action={
                "summary": "Rewrite section openings to name their subject "
                           "explicitly instead of relying on the previous "
                           "paragraph.",
                "effort": "medium",
                "steps": [
                    "Open each section with the entity name rather than a pronoun.",
                    "Repeat the product or brand name at the start of each major "
                    "section, accepting mild redundancy for a human reader.",
                    "Read any single section in isolation and check it still "
                    "identifies what it is about.",
                ],
                "expected_impact": "Individual passages become quotable as "
                                   "standalone answers.",
                "verification": "Re-run the audit; dangling-opener rate falls "
                                "below 35%.",
            })
    else:
        f.na("AE-CHUNK-DEPENDENCE",
             "Most passages name their subject rather than relying on "
             "earlier context.")

    # -- 2. Question headings without a direct answer ------------------------
    q_pages, unanswered = [], []
    for p in substantive:
        qs = [h for h in (p.get("headings") or [])
              if h.get("level", 2) >= 2 and QUESTION_HEADING.match(h.get("text", ""))]
        if not qs:
            continue
        q_pages.append(p)
        text = p.get("body_text") or ""
        for h in qs:
            idx = text.find(h["text"])
            if idx < 0:
                continue
            following = A.sentences(text[idx + len(h["text"]):])[:2]
            if not following:
                continue
            joined = " ".join(following)
            # A direct answer is short and reuses the question's key nouns.
            key = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", h["text"])
                   if w.lower() not in STOPWORDS}
            overlap = key & {w.lower() for w in re.findall(r"[A-Za-z]{4,}", joined)}
            if A.word_count(joined) > 90 or (key and not overlap):
                unanswered.append((p, h["text"]))

    if q_pages and unanswered:
        f.finding(
            "AE-QUESTION-NOT-ANSWERED",
            "Question headings are not answered in the sentences beneath them",
            "discoverability",
            "A question heading followed immediately by a short, direct answer "
            "is the single most quotable structure on the web: the heading "
            "supplies the query match and the sentence supplies the citable "
            "text. When the answer arrives several paragraphs later, the chunk "
            "containing the heading contains no answer to extract.",
            "%d question-shaped headings across %d pages are followed by "
            "preamble rather than a direct answer. Example: \"%s\"."
            % (len(unanswered), len(q_pages), unanswered[0][1][:80]),
            # Prevalence is page-level: how many of the pages that have question
            # headings have at least one unanswered one. Using the heading count
            # as `affected` against a page count as `sampled` produced ratios
            # like 27/12 (affected > sampled), which is nonsensical evidence.
            impact="degrading",
            affected=len({p["final_url"] for p, _ in unanswered}),
            sampled=len(q_pages),
            confidence="medium",
            affected_urls=sorted({p["final_url"] for p, _ in unanswered}),
            action={
                "summary": "Answer each question heading in the first one or two "
                           "sentences, then expand.",
                "effort": "medium",
                "steps": [
                    "Place a 30-50 word direct answer immediately under the "
                    "heading, reusing the heading's key nouns.",
                    "Move context, caveats and background below that answer.",
                    "Keep the answer factual and self-contained so it can be "
                    "quoted verbatim.",
                ],
                "example": "<h2>How long does delivery take?</h2>\n"
                           "<p>Standard delivery takes 3-5 working days within "
                           "the UK. Orders placed before 2pm ship the same day.</p>",
                "expected_impact": "Each section becomes a directly citable "
                                   "answer unit.",
                "verification": "Re-run; the check clears for these headings.",
            })
    elif not q_pages:
        f.na("AE-QUESTION-NOT-ANSWERED",
             "No question-shaped headings found; the answer-block pattern is "
             "raised as a proactive recommendation instead.")
    else:
        f.na("AE-QUESTION-NOT-ANSWERED",
             "Question headings are followed by direct answers.")

    # -- 3. Heading anchors --------------------------------------------------
    anchor_pages = [p for p in substantive
                    if len([h for h in p.get("headings") or []
                            if h.get("level") in (2, 3)]) >= 3]
    no_anchors = [p for p in anchor_pages
                  if not any(h.get("id") for h in p.get("headings") or []
                             if h.get("level") in (2, 3))]
    if anchor_pages and len(no_anchors) > len(anchor_pages) * 0.6:
        f.finding(
            "AE-NO-HEADING-ANCHORS",
            "Section headings carry no id anchors",
            "discoverability",
            "Without stable ids, a citation can only point at the whole page. "
            "Anchors let a source link land on the exact section that answers "
            "the question, which makes the page a more useful and more "
            "frequently chosen citation target.",
            A.ratio_evidence("multi-section pages", len(no_anchors),
                             len(anchor_pages)),
            impact="weakening", affected=len(no_anchors), sampled=len(anchor_pages),
            affected_urls=[p["final_url"] for p in no_anchors],
            action={
                "summary": "Emit a stable slug id on every H2 and H3.",
                "effort": "low",
                "steps": ["Generate ids from heading text at build time.",
                          "Keep ids stable across edits so existing citations "
                          "do not break.",
                          "Expose a visible anchor link for humans too."],
                "example": '<h2 id="delivery-times">How long does delivery take?</h2>',
                "expected_impact": "Citations can deep-link to the answering "
                                   "section.",
                "verification": "Anchors present on most multi-section pages.",
            })
    elif not anchor_pages:
        f.na("AE-NO-HEADING-ANCHORS",
             "No pages carry three or more sections, so anchors are not yet "
             "material.")
    else:
        f.na("AE-NO-HEADING-ANCHORS", "Heading anchors present on most pages.")

    # -- 4. Entity restatement ----------------------------------------------
    brand, brand_source = brand_tokens(snap)
    if brand:
        thin_mention = []
        for p in substantive:
            text = (p.get("body_text") or "").lower()
            words = max(A.word_count(text), 1)
            hits = sum(text.count(b) for b in brand)
            # Roughly one mention per 250 words is a low bar to clear.
            if hits < words / 250.0:
                thin_mention.append(p)
        if len(thin_mention) > len(substantive) * 0.5:
            # When the brand was only inferred from title text (no distinctive
            # host label), the guess can be wrong on an unseen site. Phrase the
            # evidence as an explicit assumption and lower confidence, so a
            # mis-guessed brand reads as a hypothesis rather than a false claim
            # that the site never names itself. The severity model then
            # downgrades it further for the lower confidence.
            assumed = ", ".join(sorted(brand))
            if brand_source == "title":
                detail = ("Assuming the brand is one of {%s} (inferred from the "
                          "page title; host was uninformative), fewer than one "
                          "such mention appears per 250 words." % assumed)
                conf = "low"
            else:
                detail = ("Fewer than one mention of the brand (%s) per 250 "
                          "words." % assumed)
                conf = "medium"
            f.finding(
                "AE-ENTITY-NOT-RESTATED",
                "Body copy rarely names the brand or product it describes",
                "discoverability",
                "A chunk retrieved from the middle of a page carries no title "
                "and no breadcrumb. If the entity is never named in the body, "
                "the passage cannot be attributed to the brand and will not be "
                "used to answer a question about it.",
                A.ratio_evidence("substantive pages", len(thin_mention),
                                 len(substantive), detail),
                impact="weakening", affected=len(thin_mention),
                sampled=len(substantive), confidence=conf,
                affected_urls=[p["final_url"] for p in thin_mention],
                action={
                    "summary": "Name the brand or product at the start of each "
                               "major section.",
                    "effort": "low",
                    "steps": ["Replace generic openings such as \"Our service\" "
                              "with the actual name.",
                              "Aim for at least one explicit mention per section."],
                    "expected_impact": "Passages remain attributable when "
                                       "retrieved in isolation.",
                    "verification": "Mention density rises; check clears.",
                })
        else:
            f.na("AE-ENTITY-NOT-RESTATED",
                 "Brand name recurs through the body copy.")
    else:
        f.unknown("AE-ENTITY-NOT-RESTATED",
                  "Brand name could not be determined from host and home title.")

    # -- 5. Definitional sentence on the home page ---------------------------
    home = [p for p in pages if p.get("page_type") == "home"]
    if home:
        htext = home[0].get("body_text") or ""
        if not DEFINITION.search(htext[:2500]):
            f.finding(
                "AE-NO-DEFINITION",
                "Home page states no plain definition of what the brand is",
                "discoverability",
                "The question \"what is X\" is the most common way a brand is "
                "first surfaced. Answering it requires one explicit sentence of "
                "the form \"X is a Y that does Z\" in readable text. Slogans and "
                "value propositions do not supply it.",
                "No definitional sentence found in the first 2500 characters of "
                "home page body text.",
                impact="degrading", affected=1, sampled=1, page_importance="high",
                confidence="medium",
                affected_urls=[home[0]["final_url"]],
                action={
                    "summary": "Add one plain sentence near the top of the home "
                               "page defining the brand in categorical terms.",
                    "effort": "low",
                    "steps": [
                        "Write it as \"<Brand> is a <category> that <does what> "
                        "for <whom>, based in <where>\".",
                        "Place it in body text, not in an image or a hero "
                        "animation.",
                        "Mirror the same wording in the Organization description "
                        "and in external profiles so corroboration is exact.",
                    ],
                    "expected_impact": "Gives assistants a quotable answer to the "
                                       "most common entry-point question.",
                    "verification": "AE-NO-DEFINITION clears.",
                })
        else:
            f.na("AE-NO-DEFINITION",
                 "Home page contains a definitional sentence.")
    else:
        f.unknown("AE-NO-DEFINITION", "Home page was not retrieved.")

    # -- 6. Thin pages -------------------------------------------------------
    thin = [p for p in pages
            if p.get("page_type") in ("article", "documentation", "product")
            and A.word_count(p.get("body_text") or "") < 120]
    graded = [p for p in pages
              if p.get("page_type") in ("article", "documentation", "product")]
    if graded and thin:
        f.finding(
            "AE-THIN-CONTENT",
            "Content pages carry too little text to answer anything",
            "discoverability",
            "A page with under 120 words offers no passage substantial enough "
            "to retrieve. It occupies a URL without ever becoming a candidate "
            "source.",
            A.ratio_evidence("content pages", len(thin), len(graded)),
            impact="weakening", affected=len(thin), sampled=len(graded),
            affected_urls=[p["final_url"] for p in thin],
            action={
                "summary": "Expand, merge or remove the thin pages.",
                "effort": "medium",
                "steps": ["Expand pages that should answer a real question.",
                          "Merge near-duplicates into one authoritative page.",
                          "Remove pages that exist only for navigation."],
                "expected_impact": "Fewer, stronger candidate sources.",
                "verification": "Thin-page count falls.",
            })
    elif not graded:
        f.na("AE-THIN-CONTENT", "No article, documentation or product pages found.")
    else:
        f.na("AE-THIN-CONTENT", "No thin content pages detected.")

    # -- 7. Duplicate titles -------------------------------------------------
    titles = [(p.get("title") or "").strip().lower() for p in pages if p.get("title")]
    dupes = [t for t, c in Counter(titles).items() if t and c > 1]
    if dupes and len(titles) >= 5:
        affected = [p for p in pages
                    if (p.get("title") or "").strip().lower() in dupes]
        f.finding(
            "AE-DUPLICATE-TITLES",
            "Multiple pages share the same title",
            "discoverability",
            "Identical titles make near-duplicate pages compete to answer the "
            "same question, splitting the evidence for each and leaving none of "
            "them clearly authoritative.",
            A.ratio_evidence("titled pages", len(affected), len(titles),
                             "%d duplicated title values." % len(dupes)),
            impact="weakening", affected=len(affected), sampled=len(titles),
            affected_urls=[p["final_url"] for p in affected],
            action={
                "summary": "Give every page a distinct, descriptive title.",
                "effort": "low",
                "steps": ["Make each title name the specific subject of the page.",
                          "Consolidate genuine duplicates behind one canonical URL."],
                "expected_impact": "One clear candidate per question.",
                "verification": "No duplicated titles among crawled pages.",
            })
    else:
        f.na("AE-DUPLICATE-TITLES", "Page titles are distinct.")

    # -- 8. Missing meta descriptions ---------------------------------------
    no_desc = [p for p in pages if not p.get("meta_description")]
    if len(pages) < A.MIN_SAMPLE:
        f.na("AE-NO-META-DESCRIPTION",
             "Too few pages (%d) to assess description coverage as a proportion."
             % len(pages))
    elif len(no_desc) > len(pages) * 0.5:
        f.finding(
            "AE-NO-META-DESCRIPTION",
            "Most pages have no meta description",
            "discoverability",
            "The meta description is a pre-written one-sentence summary. Where "
            "it is absent a summary is synthesised from whatever text comes "
            "first, which is often navigation or a cookie notice.",
            A.ratio_evidence("HTML pages", len(no_desc), len(pages)),
            impact="weakening", affected=len(no_desc), sampled=len(pages),
            affected_urls=[p["final_url"] for p in no_desc],
            action={
                "summary": "Write a distinct 120-160 character description per page.",
                "effort": "medium",
                "steps": ["Summarise what question the page answers.",
                          "Avoid boilerplate repeated across templates."],
                "expected_impact": "Controlled summary text instead of "
                                   "incidental page furniture.",
                "verification": "Coverage exceeds 50% of pages.",
            })
    else:
        f.na("AE-NO-META-DESCRIPTION", "Meta descriptions present on most pages.")

    f.write(workdir)


if __name__ == "__main__":
    run(A.parse_args(SKILL).workdir)
