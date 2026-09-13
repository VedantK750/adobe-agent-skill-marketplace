"""Shared helpers for every skill in the brand-ai-readiness-audit marketplace.

Design notes
------------
* Analysis skills never touch the network. They read the snapshot written by
  site-acquisition and emit a findings fragment. This keeps every analyser a
  pure function of stored evidence, which is what makes runs deterministic.
* Nothing here raises on missing optional data. A check that cannot be
  evaluated must return an `inconclusive` record, never a guess.
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------- constants

SEVERITIES = ["critical", "high", "medium", "low"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# Below this many sampled items a whole-site proportion is not evidence, it is
# noise: "most pages lack X" off a sample of two says nothing about the site.
# Checks phrased as a site-wide proportion require at least this denominator to
# fire; under it they record `inconclusive`. Per-type checks with their own
# gating (e.g. product coverage) set their own floors.
MIN_SAMPLE = 4

# Below this denominator a percentage misleads more than it informs:
# "1/1 article pages affected (100.0%)" is arithmetically true and rhetorically
# false. Evidence under it is stated as a plain count instead.
MIN_DENOMINATOR_FOR_PCT = 4

# The smallest sample a claim *about the site* may generalise from.
#
# Most checks are phrased as site-wide absences -- "no structured data
# anywhere", "pages declare no main landmark", "every page is a dead end". Such
# a claim is only as good as its denominator, and below three pages there is no
# "anywhere": the sentence has the grammar of a site-wide defect but the
# evidence of a single page.
#
# Small crawls are common and legitimate -- a bot filter serves the home page
# and refuses the rest, a sitemap is unreadable, or the site really is tiny --
# which is precisely why the floor is needed rather than assumed away. Measured
# on a 43-site live corpus, an ungated run turned one-page crawls of a
# placeholder page and of a plain-HTML blog into nine and ten findings
# respectively, three of them `high`, none supported by what was observed.
#
# Exempt checks are listed in SMALL_SAMPLE_EXEMPT below.
MIN_SITE_CLAIM_SAMPLE = 3

# Checks the floor does not apply to. Kept as one list, in one place, for the
# same reason severity is computed once in the orchestrator: a policy applied
# per call site drifts, and the next check added silently inherits whatever the
# author happened to think that day. A reviewer can read the entire exemption
# policy here in one screen.
#
# A check earns an exemption by being one of exactly two things.
SMALL_SAMPLE_EXEMPT = {
    # 1. ORIGIN-LEVEL -- a property of the host, or of one file at one
    #    well-known path. How many pages we went on to sample has no bearing on
    #    whether robots.txt carries a Disallow, or whether the host answered at
    #    all. Several of these are also the *reason* the sample is small, so
    #    gating them would suppress precisely the finding that explains the run.
    "ACC-NO-RESPONSE",
    "ACC-AI-CRAWLER-BLOCKED",
    "ACC-BLANKET-DISALLOW",
    "ACC-NO-ROBOTS",
    "ACC-NO-SITEMAP",
    "ACC-SITEMAP-NOT-ENUMERABLE",
    "FP-LASTMOD-UNIFORM",
    "EC-SINGLE-SOURCE-CLAIMS",

    # 2. DIRECTLY OBSERVED -- the defect was seen in a specific page's own
    #    markup, headers or response, and the finding names that page. "This
    #    JSON-LD block does not parse" is a fact about the block, not an
    #    inference about the site, so it is as true at n=1 as at n=100. Gating
    #    these would trade a false positive for a miss, which is not a trade the
    #    rubric rewards.
    "ACC-BROKEN-PAGES",
    "ACC-REDIRECT-CHAINS",
    "ACC-SNIPPET-SUPPRESSED",
    "MR-RENDER-GAP",
    "MR-EMPTY-SHELL",
    "MR-FACTS-IN-IMAGES",
    "MR-MULTI-H1",
    "MR-IFRAME-CONTENT",
    "SD-INVALID-JSON",
    "SD-INCOMPLETE-PROPS",
    "SD-TEXT-CONFLICT",
    "AE-THIN-CONTENT",
    "AE-DUPLICATE-TITLES",
    "EN-HEAVY-PAGES",
    "EN-SLOW-RESPONSE",
    "EN-AUTOPLAY-MEDIA",
    "EN-INTERRUPTIONS",
    "EN-CONSENT-BLOCKS-CONTENT",
    "FP-STALE-COPYRIGHT",
    "FP-STALE-YEAR-HEADINGS",
    "EC-INCONSISTENT-SELF-DESCRIPTION",
}

BOILERPLATE_TAGS = ["script", "style", "noscript", "template", "svg", "iframe"]
CHROME_TAGS = ["nav", "header", "footer", "aside", "form"]

# Page types the classifier can assign. Checks gate on these.
PAGE_TYPES = [
    "home", "product", "category", "article", "documentation",
    "contact", "about", "legal", "listing", "other",
]

SITE_TYPES = [
    "ecommerce", "local-business", "software", "publisher",
    "documentation", "portfolio", "unknown",
]


# ---------------------------------------------------------------- snapshot

def snapshot_path(workdir):
    return os.path.join(workdir, "snapshot.json")


def load_snapshot(workdir):
    path = snapshot_path(workdir)
    if not os.path.exists(path):
        raise SystemExit(
            "snapshot.json not found in %s. Run site-acquisition first." % workdir
        )
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_snapshot(workdir, snapshot):
    os.makedirs(workdir, exist_ok=True)
    with open(snapshot_path(workdir), "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, sort_keys=True)


def pages_of_type(snapshot, *types):
    """Pages whose classified type is any of `types`."""
    wanted = set(types)
    return [p for p in snapshot.get("pages", []) if p.get("page_type") in wanted]


def ok_pages(snapshot):
    """Pages that were fetched successfully and carry real HTML content.

    Soft-404s (200 responses that are really error pages) are excluded: their
    markup is not content to audit, and they frequently carry a correct
    noindex, which would otherwise be mis-reported as a suppressed-snippet
    defect. Every content check builds on this, so excluding them here fixes
    the whole class of false positives at once.
    """
    return [
        p for p in snapshot.get("pages", [])
        if p.get("status") == 200 and p.get("raw_html")
        and not p.get("soft_404")
    ]


# ---------------------------------------------------------------- fragments

class Fragment:
    """Accumulates one skill's output, then writes it as JSON.

    A skill emits three kinds of record and all three matter:
      finding        - a defect, with evidence and prevalence
      not_applicable - the check ran and correctly did not apply here
      inconclusive   - the check could not be evaluated on this run
    Recording the last two is what lets an evaluator distinguish a check
    that stayed silent on purpose from one that simply missed something.
    """

    def __init__(self, skill_id, snapshot=None):
        self.skill_id = skill_id
        self.findings = []
        self.not_applicable = []
        self.inconclusive = []
        # How many content pages this run actually observed. The small-sample
        # gate keys off this rather than off each finding's own prevalence
        # denominator, because those denominators are not comparable: some
        # checks count pages, some count images or headings, and site-level
        # checks use 1/1 to mean "one site" rather than "one page". Gating on
        # the finding's own `sampled` would read that 1/1 as a one-page crawl
        # and silently disable every site-level check at any crawl size.
        self.pages_sampled = None if snapshot is None else len(ok_pages(snapshot))

    def finding(self, check_id, title, category, mechanism, evidence,
                impact, affected=0, sampled=0, page_importance="normal",
                confidence="high", affected_urls=None, action=None,
                min_sample=None):
        """Record a defect.

        `impact` is the mechanism impact class, one of:
          blocking  - breaks the pipeline outright
          degrading - the fact exists but is hard to reach or extract
          weakening - a trust or quality signal is absent
        Final severity is computed centrally by the orchestrator from
        impact x prevalence x page importance, then adjusted for confidence.

        A finding whose sample is below MIN_SITE_CLAIM_SAMPLE is recorded as
        `inconclusive` instead of asserted: a site-wide claim drawn from one
        page is not evidence, it is a guess wearing the grammar of a defect.
        Checks in SMALL_SAMPLE_EXEMPT are not gated; `min_sample` overrides both
        for a check that needs its own floor.

        The gate lives here, once, for the same reason severity is computed once
        in the orchestrator: applied per check it would drift, and a check added
        later would silently miss it.
        """
        if min_sample is not None:
            floor = min_sample
        elif check_id in SMALL_SAMPLE_EXEMPT:
            # No floor at all, not a floor of one: an origin that answered
            # nothing has zero content pages, and ACC-NO-RESPONSE is exactly the
            # finding that has to survive that. Directly-observed checks are
            # safe at zero too -- they only fire on something they saw.
            floor = 0
        else:
            floor = MIN_SITE_CLAIM_SAMPLE

        # Fall back to the finding's own denominator only when the fragment was
        # built without a snapshot (unit tests construct one directly).
        observed = self.pages_sampled if self.pages_sampled is not None else sampled
        if observed < floor:
            self.unknown(
                check_id,
                "Only %d content page(s) were retrieved. This check states a "
                "property of the site as a whole, which needs at least %d to "
                "distinguish from a property of a single page; not asserted on "
                "this evidence." % (observed, floor))
            return

        self.findings.append({
            "check_id": check_id,
            "skill": self.skill_id,
            "title": title,
            "category": category,
            "mechanism": mechanism,
            "evidence": evidence,
            "impact": impact,
            "page_importance": page_importance,
            "confidence": confidence,
            "prevalence": {"affected": affected, "sampled": sampled},
            "affected_urls": sorted(affected_urls or [])[:10],
            "suggested_action": action or {},
        })

    def na(self, check_id, reason):
        self.not_applicable.append({"check_id": check_id, "reason": reason})

    def unknown(self, check_id, reason):
        self.inconclusive.append({"check_id": check_id, "reason": reason})

    def write(self, workdir):
        os.makedirs(os.path.join(workdir, "fragments"), exist_ok=True)
        path = os.path.join(workdir, "fragments", "%s.json" % self.skill_id)
        payload = {
            "skill": self.skill_id,
            "findings": self.findings,
            "not_applicable": self.not_applicable,
            "inconclusive": self.inconclusive,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        sys.stderr.write(
            "[%s] %d findings, %d n/a, %d inconclusive -> %s\n"
            % (self.skill_id, len(self.findings), len(self.not_applicable),
               len(self.inconclusive), path)
        )
        return path


def load_fragments(workdir):
    d = os.path.join(workdir, "fragments")
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if name.endswith(".json"):
            with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
    return out


# ---------------------------------------------------------------- parsing

def soup(html):
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception:
        return BeautifulSoup(html or "", "html.parser")


def visible_text(html):
    """Text a naive extractor would see. Strips scripts, styles and markup."""
    return visible_text_from(soup(html))


def main_text(html):
    """Text with obvious site chrome removed, approximating the body copy."""
    return main_text_from(soup(html))


def both_texts(html):
    """(visible_text, main_text) from a SINGLE parse of the document.

    The two differ only in how much chrome they remove, so parsing twice to
    produce them is pure waste -- and not cheap waste: a crawler parsed each
    page four times (metadata, visible text, main text, links), which on
    multi-megabyte documents dominated the whole audit's runtime. One storefront
    spent 674 seconds and kept zero pages.

    Capping the document before parsing looked like the fix and was not: it cut
    real `<h1>`, `<main>` and JSON-LD off the end of large pages, and the checks
    that read those fields roughly doubled their firing rate. Parsing once costs
    the same reduction with no truncation and no fidelity lost.
    """
    return both_texts_from(soup(html))


def both_texts_from(s):
    """both_texts over an already-parsed soup. DESTRUCTIVE to that soup.

    Callers must finish every other read of `s` before calling this: it strips
    tags out of the tree in place, so anything asking afterwards whether the
    page has a <script>, an <iframe> or a <nav> gets the wrong answer.
    """
    # Order matters: both texts strip the same boilerplate, so do it once, take
    # the wider text, then narrow the SAME tree down to the body copy.
    for tag in s(BOILERPLATE_TAGS):
        tag.decompose()
    visible = normalise_ws(s.get_text(" "))
    main = s.find("main") or s.find(attrs={"role": "main"}) or s.find("article")
    if main is not None:
        return visible, normalise_ws(main.get_text(" "))
    for tag in s(CHROME_TAGS):
        tag.decompose()
    return visible, normalise_ws(s.get_text(" "))


def visible_text_from(s):
    """visible_text over an already-parsed soup. Destructive to that soup."""
    for tag in s(BOILERPLATE_TAGS):
        tag.decompose()
    return normalise_ws(s.get_text(" "))


def main_text_from(s):
    """main_text over an already-parsed soup. Destructive to that soup."""
    for tag in s(BOILERPLATE_TAGS):
        tag.decompose()
    main = s.find("main") or s.find(attrs={"role": "main"}) or s.find("article")
    if main is not None:
        return normalise_ws(main.get_text(" "))
    for tag in s(CHROME_TAGS):
        tag.decompose()
    return normalise_ws(s.get_text(" "))


def normalise_ws(text):
    return re.sub(r"\s+", " ", text or "").strip()


def word_count(text):
    return len(re.findall(r"[A-Za-z0-9'&-]+", text or ""))


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text or "")
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------- reporting

def pct(part, whole):
    if not whole:
        return 0.0
    return round(100.0 * part / float(whole), 1)


def article_for(word):
    """"an Article" / "a Product". Schema type names are interpolated into
    reader-facing steps, so a fixed "a" produced "Emit a Article node" on every
    article page in the corpus. Sounded, not spelled: an acronym like `FAQPage`
    is read letter by letter."""
    if not word:
        return "a"
    first = word[0].upper()
    if word[:2].isupper():          # FAQPage, HowTo-style acronym openings
        return ("an %s" if first in "AEFHILMNORSX" else "a %s") % word
    return ("an %s" if first in "AEIOU" else "a %s") % word


def plural(n, singular, plural_form=None):
    """"1 page" / "2 pages". Evidence is read by non-experts, and "1 headings
    across 1 pages" reads as a machine talking to itself, which costs the
    finding credibility it has otherwise earned."""
    word = singular if n == 1 else (plural_form or singular + "s")
    return "%d %s" % (n, word)


def ratio_evidence(noun, affected, sampled, detail=""):
    """Prevalence as evidence a reader can weigh.

    A percentage is only informative once the denominator can carry one.
    "1/1 article pages affected (100.0%)" is arithmetically true and rhetorically
    false: it reads as a sweeping statistical claim when the finding rests on a
    single page, and a reader who notices discounts the rest of the report.
    Below a meaningful denominator, state the count plainly and let the number
    speak for itself.
    """
    if sampled < MIN_DENOMINATOR_FOR_PCT:
        if affected == sampled:
            base = "%s affected (every one sampled)." % plural(affected, noun[:-1]
                                                               if noun.endswith("s")
                                                               else noun)
        else:
            base = "%d of %s affected." % (affected, plural(sampled, noun[:-1]
                                                            if noun.endswith("s")
                                                            else noun))
    else:
        base = "%d/%d %s affected (%s%%)." % (
            affected, sampled, noun, pct(affected, sampled))
    return (base + " " + detail).strip()


def parse_args(skill_id):
    """Every analysis script takes one argument: the working directory."""
    import argparse
    ap = argparse.ArgumentParser(prog=skill_id)
    ap.add_argument("--workdir", required=True,
                    help="Directory holding snapshot.json; fragments are written here.")
    return ap.parse_args()
