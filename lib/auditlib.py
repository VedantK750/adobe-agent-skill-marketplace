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

# schema.org Organization subtypes. An Organization node is very often declared
# as a SUBTYPE rather than the bare parent term: D2C brands on Shopify emit
# `OnlineStore` (Ruggable does), publishers emit `NewsMediaOrganization`,
# clinics emit `MedicalBusiness`. Matching only the literal strings
# "Organization"/"LocalBusiness" reported "no Organization node anywhere on the
# site" for sites that declare a perfectly valid one — a high-severity false
# positive that an author can see is wrong at a glance, which discredits the
# whole report. Subtype-awareness lives here, once, so every skill that asks
# "does this site declare a machine-readable identity?" answers it the same way.
#
# The list is the schema.org Organization subtree plus the LocalBusiness
# subtree, which is itself an Organization subtype. Suffix rules below catch
# the long tail (every `*Business`, `*Store`, `*Shop`, `*Agency`, ...) so an
# unlisted subtype still resolves correctly.
ORG_TYPES = {
    "organization", "localbusiness", "corporation", "onlinestore",
    "onlinebusiness", "ngo", "educationalorganization", "governmentorganization",
    "medicalorganization", "newsmediaorganization", "performinggroup",
    "sportsorganization", "sportsteam", "airline", "consortium",
    "librarysystem", "researchorganization", "fundingscheme", "cooperative",
    "politicalparty", "collegeoruniversity", "school", "elementaryschool",
    "highschool", "middleschool", "preschool", "dentist", "physician",
    "hospital", "pharmacy", "veterinarycare", "restaurant", "hotel",
    "lodgingbusiness", "store", "shop", "bakery", "brewery", "winery",
    "searchrescueorganization", "workersunion", "project", "fundingagency",
}

# Suffixes that are only ever used by Organization subtypes in schema.org.
ORG_TYPE_SUFFIXES = (
    "business", "store", "shop", "agency", "organization", "corporation",
    "school", "university", "clinic", "dealer", "rental", "service",
)
# Terms ending in an ORG_TYPE_SUFFIX that are NOT organizations. `Service` in
# particular is an intangible (a described offering), not the provider.
NON_ORG_TYPES = {"service", "financialproduct", "foodservice", "taxiservice",
                 "broadcastservice", "webapi", "governmentservice", "service"}


def is_org_type(type_name):
    """True when a schema.org @type denotes an Organization (any subtype).

    Case- and URL-insensitive: accepts "Organization", "organization" and
    "https://schema.org/OnlineStore" alike, because all three appear in the
    wild and a node is no less valid for being written as a full URL.
    """
    t = (type_name or "").strip().lower().rstrip("/")
    if "/" in t:
        t = t.rsplit("/", 1)[-1]
    if not t or t in NON_ORG_TYPES:
        return False
    if t in ORG_TYPES:
        return True
    return t.endswith(ORG_TYPE_SUFFIXES)


def any_org_type(type_names):
    """True when any @type in an iterable denotes an Organization subtype."""
    return any(is_org_type(t) for t in (type_names or []))


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

    def __init__(self, skill_id):
        self.skill_id = skill_id
        self.findings = []
        self.not_applicable = []
        self.inconclusive = []

    def finding(self, check_id, title, category, mechanism, evidence,
                impact, affected=0, sampled=0, page_importance="normal",
                confidence="high", affected_urls=None, action=None):
        """Record a defect.

        `impact` is the mechanism impact class, one of:
          blocking  - breaks the pipeline outright
          degrading - the fact exists but is hard to reach or extract
          weakening - a trust or quality signal is absent
        Final severity is computed centrally by the orchestrator from
        impact x prevalence x page importance, then adjusted for confidence.
        """
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
    s = soup(html)
    for tag in s(BOILERPLATE_TAGS):
        tag.decompose()
    return normalise_ws(s.get_text(" "))


def main_text(html):
    """Text with obvious site chrome removed, approximating the body copy."""
    s = soup(html)
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


def ratio_evidence(noun, affected, sampled, detail=""):
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
