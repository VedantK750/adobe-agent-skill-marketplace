# Brand AI-Readiness Audit — Agent Skill Marketplace

Point it at any website. It audits the site read-only and emits one structured
report of what is hurting the brand's **AI discoverability** (getting found and
cited) and its **on-site engagement** (keeping the visitor who arrives), each
finding with evidence, a severity, and a prioritized fix.

```bash
python3 skills/audit-orchestrator/scripts/run_audit.py \
  --url https://example.com --workdir ./audit-run --markdown
```

Writes `audit-report.json` (validated against `report.schema.json`) and, with
`--markdown`, a readable `audit-report.md`.

Needs Python 3.8+, `requests` and `beautifulsoup4`. `lxml`, `jsonschema` and
`playwright` are optional; the audit degrades honestly without them.

---

## The eight skills

| Skill | Concern |
|---|---|
| **audit-orchestrator** *(entrypoint)* | Runs the pipeline, computes severity, de-duplicates, validates, emits the report |
| **site-acquisition** | Can a crawler get in? robots.txt, AI-agent exclusion, sitemap, status codes, redirects, canonicals, snippet suppression. Produces the snapshot and classifies the site |
| **machine-readability** | Is the content readable as text? JS render gaps, facts locked in images, heading and landmark semantics, iframe-trapped content |
| **structured-data** | Are facts stated explicitly and validly? Presence, parse validity, per-type coverage, required properties, entity graph, markup-versus-text conflicts |
| **answer-extractability** | Can a fact be quoted from one retrieved chunk? Chunk self-containment, question/answer blocks, entity restatement, definitions, anchors, thin and duplicate pages |
| **entity-corroboration** | Does the wider web agree, and is identity unambiguous? External profiles, sameAs, NAP consistency, single-source claims, name collisions |
| **freshness-provenance** | Is it current and attributable? Dates, undated time-sensitive claims, stale years, lastmod honesty, authorship |
| **engagement-audit** | Does the arriving visitor stay? Viewport, weight, dead ends, orientation, calls to action, interruptions, consent, search |

Each owns a distinct failure mechanism, so the split is separation of concerns
rather than padding. `structured-data` and `answer-extractability` are kept
apart deliberately: flawless JSON-LD alongside prose that cannot be quoted out
of context is a common combination.

## How the entrypoint composes them

1. **Acquire** — `site-acquisition` writes `snapshot.json`. If this fails the
   pipeline stops; everything else depends on it.
2. **Analyse** — each skill reads that snapshot and writes a fragment to
   `fragments/`. Fragments carry *candidate* findings with an impact class,
   prevalence and confidence, but no severity. A skill that fails is recorded
   and skipped, so one broken analyser degrades the report rather than losing it.
3. **Compose** — `compose_report.py` computes severity centrally (the model is
   in `skills/audit-orchestrator/references/severity-model.md`), collapses
   findings sharing a root cause, assigns `F-NNN` ids deterministically, sorts
   by severity then ascending effort, and selects the proactive
   recommendations that apply to this site.
4. **Validate** — `validate_report.py` checks the report against the schema plus
   the cross-field consistency the schema cannot express.

The skills run are read from `marketplace.json`, not hardcoded: adding or
removing one changes the pipeline with no code change. Severity is never
assigned by the skill that raised the finding, or the scale drifts between
skills and the report stops being reproducible.

---

## Design

**Crawl once, analyse many.** The site is fetched exactly once; every analyser
is a pure function over the stored snapshot. That is what makes runs
deterministic and keeps the audit inside its runtime budget.

**Conditional checks, not universal ones.** Site and page type are classified
before any check runs, and checks declare the page types they apply to. "No
Product schema" is a real finding on a product page and a false positive on a
blog post. The same applies to the *size* of the evidence: a site-wide claim
needs at least three content pages, or it records `inconclusive` instead of
asserting. Origin-level checks (robots.txt, the sitemap) and directly-observed
defects are exempt, and say why in `lib/auditlib.py`.

**Mechanism-first.** Every finding states *why* the defect breaks retrieval or
engagement. A fix not traceable to a mechanism is a guess.

**Representative sampling.** Sitemap URLs are interleaved across sections so one
`/legal/` partition cannot monopolise the budget, a per-type quota stops one
template dominating, and redirect targets are de-duplicated by final URL so a
page reached under several aliases never inflates a prevalence ratio.

## Report shape

Every field the brief requires, plus the ones that carry the reasoning:
`mechanism`, `prevalence`, `confidence`, per-finding `verification`, and
`proactive_recommendations` selected against what the site actually is.

`not_applicable` and `inconclusive` matter as much as the findings: they
distinguish a check that stayed silent on purpose from one that missed
something.

## Guardrails

Recommend-only — nothing here alters a live site. GET only: no POST, no forms,
no authenticated areas. robots.txt is fetched first and obeyed, each URL is
fetched once with a politeness delay, and the crawl is bounded by page count
and a wall-clock budget.

Degradation is deliberate. Without a headless browser the render-gap check
reports `inconclusive` and a static proxy check runs instead; without a search
tool the off-site checks report `inconclusive` and write a query worklist.
Neither guesses — an unverified assertion is a worse failure than an honest gap.

---

## Testing

```bash
python3 tests/run_tests.py         # fixtures: are the checks correct?
python3 tests/check_compliance.py  # is the package brief-compliant?
python3 tests/live_suite.py        # live corpus: do the checks generalise?
```

**Fixtures** serve three synthetic sites over real HTTP and assert both
directions of every check: `badsite` must trip each one, `goodsite` must stay
silent, `conflictsite` exercises markup-versus-text disagreement. Plus the
structural invariants the schema cannot express, and byte-identical reports
across repeat runs.

**The live suite** is what fixtures cannot be: sites nobody here designed. It
audits a corpus of real sites and asserts twelve invariants that hold on *any*
site — schema-valid report, inside the five-minute budget, no analyser crashed,
every `affected_url` actually fetched, `critical` reserved for pipeline
blockers. It also reports a **firing rate per check across the corpus**, which
is what surfaces false positives: a check firing on nearly every site is not
diagnostic, and one firing nowhere is untested. Median crawl depth is printed
alongside, because a shallow crawl lowers every rate at once and mimics a
detection improvement.

Two corpora ship: `tests/corpus.txt` (mixed, quick) and `tests/corpus-d2c.txt`
(~900 direct-to-consumer candidates plus a control group). Probe first, since
brands fold and rebrand:

```bash
python3 tests/probe_corpus.py
python3 tests/live_suite.py --corpus tests/corpus-d2c.live.txt --workers 8
```

**Compliance** is checked, not eyeballed. The recommend-only guarantee is
verified *from source*: the checker walks the AST of every shipped script and
fails on any write request, shell escape, or `subprocess` use outside the
orchestrator. `make_submission.py` runs it and refuses to build a failing zip.

---

## Layout

```
marketplace.json          manifest; exactly one entrypoint
report.schema.json        the report contract
references/               failure-modes.md — shared signal/mechanism table
lib/auditlib.py           shared snapshot IO, extraction, fragment helpers
skills/<skill>/           SKILL.md + scripts/ + references/
tests/                    fixtures, live suite, compliance gate, corpora
make_submission.py        builds and verifies the submission zip
```

`lib/auditlib.py` is shared at marketplace level rather than duplicated into
eight skill folders; the manifest stays self-contained either way.

## Extending it

Add a check via `references/failure-modes.md`: state the mechanism first, gate
it on page type, give it an impact class rather than a severity, set a minimum
denominator, and write its `not_applicable` reason. A check that cannot explain
its own silence is not finished.
