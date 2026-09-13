# Brand AI-Readiness Audit — Agent Skill Marketplace

Point it at any website. It audits the site read-only and emits one
structured report of what is hurting the brand's **AI discoverability**
(getting found and cited) and its **on-site engagement** (keeping the visitor
who arrives), each finding with evidence, a severity, and a prioritized fix.

```bash
python3 skills/audit-orchestrator/scripts/run_audit.py \
  --url https://example.com --workdir ./audit-run --markdown
```

Outputs `audit-report.json` (validated against `report.schema.json`) and,
with `--markdown`, a human-readable `audit-report.md`.

Requires Python 3.8+, `requests` and `beautifulsoup4`. `lxml`, `jsonschema`
and `playwright` are optional and the audit degrades cleanly without them.

---

## Design in three decisions

**Crawl once, analyse many.** `site-acquisition` visits the site and writes a
canonical evidence snapshot. Every analysis skill reads that snapshot and
never touches the network. Each analyser becomes a pure function over stored
evidence, which makes runs deterministic; the target site is fetched exactly
once regardless of how many concerns are checked; and the whole audit fits
comfortably inside the runtime budget because network time is paid once.

**Conditional checks, not universal ones.** Site type and page type are
classified before any check runs, and checks declare the page types they
apply to. "No Product schema" is a real finding on a product detail page and
a false positive on a blog post. Skipped checks are recorded in
`not_applicable` with the reason, so a reader can see the check ran and chose
to stay silent. This is the main lever on both false positives and
generalisation to unseen sites.

The same principle applies to the *size* of the evidence, not only its type. A
check phrased as a site-wide absence — "no structured data anywhere", "every
page is a dead end" — is only as good as its denominator, so below three
content pages it records `inconclusive` instead of asserting. Small crawls are
common and legitimate: a bot filter serves the home page and refuses the rest,
or the site really is tiny. Two kinds of check are exempt and say why in
`lib/auditlib.py`: claims about the *origin* (robots.txt, the sitemap, whether
the host answered), and defects *directly observed* on a named page. Both are
as true at one page as at a hundred, so gating them would trade a false
positive for a miss.

**Mechanism-first findings.** Every finding carries a `mechanism` field
stating *why* the defect breaks retrieval or engagement, not merely that
something is missing. A fix that is not traceable to a mechanism is a guess.

Advice is gated on the same evidence as the findings. The proactive
recommendations — the improvements worth making where no defect was detected —
are selected against what the site actually turned out to be, not appended as a
fixed list. A documentation site is not told to mark up offers and reviews; a
site with no video is not told to publish transcripts; a two-page brochure is
not lectured about a site-wide prose pattern. Instead each gets the advice that
answers the questions its visitors actually ask: commerce terms and review
markup for a storefront, version-pinning for documentation, author identities
for a publisher, hours and service area for a place-based business. Irrelevant
advice costs exactly what a false positive costs — it teaches the reader to
skim the section. Ids are stable across reports, so a suppressed recommendation
leaves a gap rather than renumbering the rest.

Underpinning all three is a **representative sample**. Conditional checks are
only as good as the pages they see, so the crawler works to sample the whole
site rather than one corner of it: sitemap URLs are interleaved across sections
(a partition that is entirely `/legal/` cannot monopolise the budget), a
per-type quota caps how many pages of each type are kept — tighter for
low-value boilerplate — and a URL whose type is already saturated is skipped
before it is fetched. Redirect targets are de-duplicated by final URL so one
page reached under several aliases is never counted twice in a prevalence
ratio. Home detection survives locale redirects (`/` → `/in`, `/en-us`). Links
are extracted with a parser rather than a pattern, so unquoted attributes
(`<a href=/foo>`, valid HTML5) and markup split across lines still yield a
frontier — a regex here fails silently, ending the crawl at the seed page and
leaving a report that looks thin rather than broken. Each page is parsed
**once** and everything is derived from that single tree; parsing it per
concern instead put a multi-megabyte document through four full parses and cost
one storefront 674 seconds for nothing. The size cap bounds what reaches the
snapshot file, never what is analysed — truncating before parsing cuts real
`<h1>`, `<main>` and JSON-LD off long pages, and a page is not less well built
because it is long. See
`skills/site-acquisition/references/classification.md`.

**Determinism is a property of the analysis, not a hope.** The audit is a pure
function of the evidence snapshot: given the same `snapshot.json`, the report is
byte-identical, every time — verified by running the full analysis ten times
over a fixed snapshot and hashing the result (one distinct hash). Nothing in the
analysis depends on wall-clock time, dict ordering or set iteration. The only
thing that can move a report between two live runs is the network itself — a
page that times out on one run, or genuinely responds slower — and the crawler
is hardened against both: transient fetch errors are retried so one flaky
request cannot collapse a crawl, and timing-derived checks (slow-response) fire
only on systemic slowness, never on a single jittery fetch, and keep volatile
measurements out of their reason strings.

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

Each maps to a distinct failure mechanism, so the decomposition is separation
of concerns rather than padding. `structured-data` and `answer-extractability`
are deliberately kept apart: they fail independently and often in opposite
directions — flawless JSON-LD alongside prose that cannot be quoted out of
context is a common and important combination.

---

## How the entrypoint composes them

1. **Acquire** — `site-acquisition` writes `snapshot.json`. If this fails the
   pipeline stops; everything else depends on it.
2. **Analyse** — each analysis skill reads the snapshot and writes a fragment
   to `fragments/`. Fragments hold *candidate* findings with an impact class,
   prevalence and confidence, but no severity. A skill that fails is recorded
   and skipped, so one broken analyser degrades the report rather than losing it.
3. **Compose** — `compose_report.py` computes severity centrally (see
   `skills/audit-orchestrator/references/severity-model.md`), collapses
   findings that share a root cause, assigns `F-NNN` ids in deterministic
   order, sorts by severity then ascending effort, and selects the proactive
   recommendations that apply to this site.
4. **Validate** — `validate_report.py` checks the report against the schema,
   including cross-field consistency the schema cannot express. It uses
   `jsonschema` when installed and a built-in check when not.

Severity is never assigned by the skill that raised the finding. The scale
would drift between skills and the report would not be reproducible.

---

## Report shape

Every field the brief requires, plus extensions that carry the reasoning:

- `mechanism` — why this breaks retrieval or engagement
- `prevalence` — affected over sampled, for the relevant page type
- `confidence` — and it only ever lowers severity, never raises it
- `verification` — how to confirm the fix worked, per finding
- `proactive_recommendations` — improvements beyond the detected defects,
  selected against what the site actually is
- `not_applicable` — checks that ran and correctly did not apply
- `inconclusive` — checks that could not be evaluated on this run

The last two matter as much as the findings. They are what distinguishes a
check that stayed silent on purpose from one that missed something, and they
are the evidence that the audit is not simply reporting everything it can
think of.

---

## Guardrails

Recommend-only: nothing in this marketplace alters a live site. GET requests
only — no POST, no form submission, no authenticated areas, no state-changing
requests. robots.txt is fetched first and obeyed. Each URL is fetched exactly
once with a politeness delay. The crawl is capped by page count and by a
wall-clock budget; on timeout it stops and reports what it gathered.

Degradation is deliberate. Without a headless browser the render-gap check
reports `inconclusive` and a static-HTML proxy check runs instead. Without a
search tool the off-site corroboration checks report `inconclusive` and write
a query worklist. Neither guesses. An unverified assertion is a worse failure
than an honest gap.

---

## Testing

```bash
python3 tests/run_tests.py
```

The suite serves three synthetic sites over real HTTP and audits each end to
end, asserting **both directions** of every check it exercises:

- `tests/fixtures/badsite` deliberately breaks a range of checks (AI crawler
  blocked, JS application shell, duplicate H1s, dangling chunks, image-locked
  facts, stale copyright). Each must fire.
- `tests/fixtures/goodsite` is a clean local business. The negative assertion
  is the one that matters: it produces **zero findings**. A check that fires on
  everything is worse than useless, so the clean site staying silent is the
  strongest evidence the marketplace avoids false positives.
- `tests/fixtures/conflictsite` states one price in JSON-LD and a different
  one in visible text, exercising the `SD-TEXT-CONFLICT` check specifically.

It also asserts the structural invariants the JSON schema cannot express
(severity counts match the findings, action priority equals finding severity,
ids are ordered) and that two audits of the same site produce byte-identical
reports apart from the timestamp. To audit one fixture by hand instead:

```bash
python3 -m http.server 8899 --directory tests/fixtures/badsite &
python3 skills/audit-orchestrator/scripts/run_audit.py \
  --url http://127.0.0.1:8899/ --workdir /tmp/bad --no-render
```

### Generalisation: the live corpus suite

Fixtures prove the checks are *correct* against ground truth we control. They
cannot prove the checks *generalise*, because a fixture is by definition a site
we designed. That is what `tests/live_suite.py` is for:

```bash
python3 tests/live_suite.py                 # the full corpus
python3 tests/live_suite.py --limit 8       # smoke run
```

It audits a corpus of real sites — `tests/corpus.txt`, spanning documentation,
SaaS, publishers, ecommerce, nonprofit, plain-HTML blogs and deliberately
awkward markup — and asserts twelve invariants that must hold on *any* site,
none of which reference any site's content. Among them: a schema-valid report
is produced; the audit finishes inside the brief's five-minute budget; no
analyser crashed; **every `affected_url` was actually fetched**, so no finding
can cite a page that was never seen; `critical` is reserved for the
pipeline-breaking blockers; and no unrendered format placeholder reaches
reader-facing text. Nothing is fitted to the corpus, so sites can be swapped
freely.

Its second output is the one no single-site run can produce: a **firing rate
per check across the corpus**. A check that fires on nearly every site is a
detection defect either way — if the finding is real everywhere it is not
diagnostic, and if it is not, it is a false positive with wide reach. A check
that never fires anywhere is untested surface area. Both lists are printed and
written to `SUMMARY.md`.

The defects this catches are the ones fixtures cannot, because they only appear
against markup nobody on the team wrote:

| Class | Example |
|---|---|
| A check measuring a proxy, not its mechanism | `EN-AUTOPLAY-MEDIA` fired on *muted* autoplay — which cannot produce the unrequested sound its mechanism describes, and is muted precisely because browsers require it |
| A check reading the wrong view of the page | `EN-NO-CTA` searched chrome-stripped text, missing "Add to cart" inside `<form>` on roughly half of all storefronts |
| Infrastructure counted as content | `MR-IFRAME-CONTENT` was tripped mostly by tag-manager frames, making it a detector for "uses analytics" |
| Absent evidence read as negative evidence | A site-wide claim asserted from a one-page crawl; "no definition" asserted on a page too sparse to read |
| Silent extraction failure | A regex over `href="..."` returned zero links for valid unquoted attributes, capping those sites at one page with no error |
| Cost that only shows at scale | Each page was parsed four times, which on multi-megabyte documents exceeded the runtime budget outright |

Several are specific to commerce markup — muted hero video, tag-manager
iframes, form-wrapped cart buttons, client-rendered storefronts — which is why
`corpus-d2c.txt` exists alongside the general one. None of them is visible on a
site you designed yourself.

### Read crawl depth before believing any rate

The suite reports median pages crawled next to every firing rate and warns when
depth collapses, because depth is the confounder under every aggregate here.
Nearly every check generalises from a page sample and stays silent below three
pages, so a shallow crawl lowers rates across the board and reads as a
detection improvement. It also moves site type: with only a home page sampled
there is no product evidence, so storefronts classify as `unknown`.

Depth collapses for mundane reasons — repeated runs against the same corpus
draw rate limiting from shared CDNs, which shows up as robots.txt answering
403, 429 or 420. Rule depth out before concluding anything about a check.

Two corpora ship. `tests/corpus.txt` is a compact mixed set for quick runs.
`tests/corpus-d2c.txt` is a ~900-entry set weighted toward direct-to-consumer
brands — the site shape this audit is most often pointed at, and where product
schema, faceted navigation, JS storefronts, review widgets and consent banners
all interact — grouped by segment so the firing-rate table can be read per
segment. A check that fires on every storefront and no documentation site is
measuring page type, not defect, and only a control group shows that.

Candidate lists go stale as brands fold and rebrand, and a dead host costs the
suite three retries before it learns anything. Probe first:

```bash
python3 tests/probe_corpus.py --in  tests/corpus-d2c.txt \
                              --out tests/corpus-d2c.live.txt
python3 tests/live_suite.py --corpus tests/corpus-d2c.live.txt \
                            --workers 8 --max-pages 10
```

### Brief compliance

```bash
python3 tests/check_compliance.py
```

The rubric has two halves. One is judgement — are the checks right, are the
fixes mechanism-sound — and no script can score that. The other is mechanical:
exactly one entrypoint, every skill folder agentskills.io compliant with the
brief's named sections, the report schema floor, recommend-only, inside the
size and runtime budgets. Those are checked rather than eyeballed.

The recommend-only guarantee in particular is *verified from source* rather
than asserted: the checker walks the AST of every shipped script and fails on
any `post`/`put`/`delete`/`patch` call, any shell escape, and any use of
`subprocess` outside the orchestrator. `make_submission.py` runs this check and
refuses to build a zip that fails it.

---

## Layout

```
marketplace.json          manifest; exactly one entrypoint
report.schema.json        the report contract
references/               failure-modes.md — the shared signal/mechanism table
lib/auditlib.py           shared snapshot IO, extraction and fragment helpers
skills/<skill>/
  SKILL.md                agentskills.io compliant
  scripts/                executable checks
  references/             detailed models and checklists
tests/fixtures/           broken and clean sites
tests/run_tests.py        fixture suite: are the checks correct?
tests/live_suite.py       live corpus suite: do they generalise?
tests/check_compliance.py brief-compliance gate: is the package well-formed?
tests/probe_corpus.py     corpus maintenance: which candidate hosts still answer
tests/corpus.txt          the mixed corpus, one URL per line
tests/corpus-d2c.txt      ~900 D2C-weighted candidates, grouped by segment
make_submission.py        builds and verifies the submission zip
```

`make_submission.py` writes the zip and then re-opens it to check it against
`marketplace.json`: every listed skill ships a `SKILL.md`, every shipped
`SKILL.md` is listed, each has YAML frontmatter whose `name` matches its
manifest id, exactly one skill is the entrypoint, and the archive is inside the
size limit. A rename that updated the folder but not the manifest fails the
build rather than reaching a grader.

`lib/auditlib.py` is a marketplace-level shared module. Duplicating it into
eight skill folders would be worse engineering than the small coupling it
introduces, and the manifest remains self-contained: no external service is
needed to resolve anything.

## Extending it

Add a check by following `references/failure-modes.md`: state the mechanism
first, gate it on page type, give it an impact class rather than a severity,
set a minimum denominator, and write its `not_applicable` reason. A check
that cannot explain its own silence is not finished.
