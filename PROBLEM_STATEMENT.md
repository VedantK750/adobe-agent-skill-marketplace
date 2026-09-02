# Adobe University Hackathon 2026 — Round 3

**Build the Agent Skill Marketplace**

> This file consolidates two source documents into one reference:
> 1. The official Round 3 problem statement (pasted by the user).
> 2. `Adobe-Hackathon-Round3-Plan.pdf` — a detailed solution design & implementation plan already drafted for this round.
>
> Keep this file updated as the project evolves; treat it as the single source of truth for "what are we building and why."

---

## Part A — Official Problem Statement

### Builds on Round 2

Round 2 tested reasoning on paper: why a brand is invisible / stale / bouncing in AI apps, and what to do about it.

Round 3 tests whether you can encode that reasoning into **reusable agent skills**, so that a general AI agent, pointed at any website, can **audit it automatically** — detecting the problems that hurt both its **AI discoverability** (getting found and cited) and its **on-site engagement** (keeping the visitor once they arrive) — and produce a report of findings plus suggested actions to fix them.

### How to approach it — learn from the wild

No test sites are provided. Part of the challenge is field research: go find real websites that AI assistants cite well versus ones they ignore or misrepresent, and work out what makes the difference. Distil those learnings — the concrete, repeatable signals that separate cited from uncited (the Round-2 failure modes) — into the skill, each with **evidence** and a **severity**.

Sites studied are not used in grading and won't be asked about. The skill is judged **only** on how well it generalizes to unseen sites.

> **Design for patterns, not fit-to-examples.** Evaluation is on unseen websites — focus on discovering repeatable root causes, not memorizing specific site characteristics.

---

### 1. What you submit

A single **Agent Skill Marketplace**: a package containing one or more skills, each authored in the standard **Agent Skills (agentskills.io)** format (a `SKILL.md` with YAML frontmatter + instructions, optional bundled `scripts/` and `references/`), tied together by a **marketplace manifest** (`marketplace.json`) and **exactly one designated entrypoint skill** that receives the audit request and emits the final report.

- Decomposing reasoning into multiple focused skills (one per concern) is the point of the marketplace format, and is **rewarded** in the rubric.
- A marketplace with only one skill is accepted as a **floor** — valid, but not the target.

Given a website, the marketplace's entrypoint skill audits it and produces an **audit report** containing:

- **Problems found** — issues hurting AI discoverability and on-site engagement (Round-2 failure modes), each with evidence and severity.
- **Suggested actions** — what to change and how to fix each problem, prioritized. May go beyond detected problems: proactive improvements even where no explicit defect was found.

#### Recommend-only

No skill in the marketplace modifies a live website — audit and report only. Suggested actions are recommendations, not applied changes. **No destructive, authenticated, or site-altering actions.**

#### Sample audit report schema (floor, not ceiling — extra fields allowed)

```json
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "summary": {
    "total_findings": 6,
    "critical": 1,
    "high": 2,
    "medium": 3
  },
  "findings": [
    {
      "id": "F-001",
      "title": "No JSON-LD structured data on product pages",
      "severity": "high",
      "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
      "suggested_action": {
        "summary": "Add Product/Offer JSON-LD to every product page.",
        "priority": "high"
      }
    }
  ]
}
```

**Required per finding:** `id`, `title`, `severity`, `evidence`, `suggested_action`.
**Required summary metadata:** `site`, `audited_at`, counts-by-severity.

#### Example layout (illustrative — any structure is fine as long as the rules hold)

```
brand-ai-readiness-audit/           <- marketplace root (this is what you zip)
  marketplace.json                  <- manifest: lists skills + the entrypoint
  skills/
    audit-orchestrator/             <- entrypoint: composes the others, emits the final report
      SKILL.md
      scripts/
      references/
    crawl-render-audit/
      SKILL.md
    freshness-corroboration/
      SKILL.md
    engagement-audit/
      SKILL.md
  README.md
```

### Marketplace rules

`agentskills.io` defines the single-skill `SKILL.md` format but **not** a multi-skill marketplace format — the manifest below is this contest's own lightweight convention. Every skill folder must still independently satisfy the official agentskills.io spec.

- Every skill folder listed in the marketplace must contain a valid `SKILL.md` per the agentskills.io spec (name, description, etc.). Optional sanity check: `skills-ref validate ./skill-folder`.
- The marketplace root must include a top-level `marketplace.json`, listing every skill and marking **exactly one** as the entrypoint. The entrypoint composes the outputs of the other skills into the single audit report.

```json
{
  "name": "brand-ai-readiness-audit",
  "version": "1.0.0",
  "skills": [
    { "id": "audit-orchestrator", "path": "skills/audit-orchestrator", "entrypoint": true },
    { "id": "crawl-render-audit", "path": "skills/crawl-render-audit" },
    { "id": "freshness-corroboration", "path": "skills/freshness-corroboration" },
    { "id": "engagement-audit", "path": "skills/engagement-audit" }
  ]
}
```

### SKILL.md format (for each skill in the marketplace)

```markdown
---
name: brand-ai-readiness-audit
description: Audit a website for AI-discoverability and on-site-engagement
problems — crawlability, JS-render gaps, missing/invalid structured data,
facts locked in non-text, stale or uncorroborated facts, entity ambiguity,
weak on-site orientation / no context retention — and produce a report of
findings plus prioritized, actionable fixes. Use when diagnosing why a brand
is missing or misrepresented in AI assistants, or why visitors who arrive
don't engage.
license: <your choice>
---
# Brand AI-Readiness Audit (discoverability + engagement)
## When to use
## Inputs (e.g. a URL / domain)
## Procedure (numbered, deterministic steps)
## Output (an audit report against a fixed schema: findings + suggested actions)
```

Keep each `SKILL.md` lean — push detailed checklists to `references/` and executable checks to `scripts/` (progressive disclosure). Declare any allowed-tools. Narrowly-scoped skills (one concern each) compose more cleanly under the entrypoint than one skill that tries to do everything.

---

### 2. What the marketplace must do

**Detect** — cover both halves of the Round-2 problem, reasoning from how these systems actually work (see Appendix below):

- **Off-site discoverability** — why the brand isn't found or cited by AI assistants.
- **On-site engagement** — why visitors who do arrive don't stay.

Working out the specific, concrete checks that surface each of these is part of the task — no checklist is provided.

**Report** — for each problem found: evidence, severity, and a suggested action (what to change and how), prioritized by impact. Suggested actions may go beyond problems found — proactive improvements that strengthen AI discoverability or engagement even absent an explicit defect.

→ emit a single audit report (fixed schema): findings + suggested actions.

---

### 3. How submissions are evaluated

Evaluators assess the **submitted marketplace itself** — skills' instructions, checks, logic, and composition by the entrypoint — **not** any single report it happens to produce. They look for:

- **What problems it's built to identify** — right checks, real causes, evidence, no false positives?
- **How it addresses them** — fixes correct, specific, mechanism-sound, and actually resolve the problems found?
- **How the marketplace is composed** — genuine separation of concerns vs. padding? (A single well-built skill is not penalized for not decomposing.)
- **Beyond-defect improvements** — does it recommend actions that genuinely strengthen how the brand is found, cited, and experienced?
- **Generalization** — tested by construction (no example sites given during the task).

### 4. Rubric

| Criterion | Looking for |
|---|---|
| Detection accuracy | Correctly identifies real problems (evidence-backed) across both discoverability and engagement, with few misses and few false positives |
| Suggested-action quality | Fixes correctly targeted, mechanism-sound, prioritized; beyond-problem suggestions relevant and non-obvious |
| Output design | Entrypoint emits a clear, structured, actionable report (evidence + severity + prioritized actions) a non-expert could act on |
| Skill-format & engineering hygiene | Each skill folder agentskills.io compliant; manifest well-formed with exactly one entrypoint; deterministic; safe |
| Marketplace composition | Decomposition reflects genuine separation of concerns, cleanly composed by entrypoint — not padding; a single well-built skill scores fully here too |
| Generalization | Works on unseen sites — tested by construction |

### 5. Scope & guardrails

- **Recommend-only** — audits and reports; never alters a live site; runs read-only in a sandbox.
- No destructive, authenticated-area, or rate-abusing actions. **Respect robots.txt.**
- Each skill portable (agentskills.io format is provider-neutral) and declares its tool needs; manifest is self-contained — no external service needed to resolve it.
- **Submission zip: ≤ 50 MB** (no pre-trained model weights).
- **Audit runtime: < 5 minutes** on a standard machine for a typical website.

### 6. Logistics

- **Format:** take-home — building and testing a skill doesn't fit a proctored hour.
- **AI assistance is allowed** in Round 3 — building agent tooling with an agent is the intended, realistic skill.
- **Works on unseen sites** — generalization tested by construction.

**Submission:** a zip of the marketplace root directory (containing `marketplace.json` and every skill folder), with a short `README.md` at the root describing what each skill does and how the entrypoint composes them.

---

### Appendix — Background Concepts (from Round 2)

General ideas behind why AI assistants find, trust, and repeat some content and not others. Describes *how these systems behave* — not what to do about any particular site. Working out the checks and fixes is the task.

**A. How search visibility works (the basics).**
Search engines, and increasingly AI assistants, discover content the same basic way: a crawler visits a page, reads what's there, and stores it so it can be found later. Three things must succeed in order: (1) the crawler is let in, (2) it can read what's on the page, (3) it can pick out the specific fact someone is looking for. If any one step fails, the page is invisible to the machine — even if plainly visible to a human.

**B. How assistants like ChatGPT use sources.**
Many assistants search, fetch pages, and build answers from what those pages say, sometimes linking back. What ends up in the answer depends on what the assistant can find and use at that moment — pages that get picked tend to be easy to reach, easy to read, and easy to quote a clear fact from. If nothing about a brand is easy to reach/read/quote, it won't make it into the answer.

**C. How machines "read" a page.**
A page that looks complete to a person isn't always complete to a machine. Some content is only assembled after page load, or lives in a form a simple reader can't interpret. The more explicitly and unambiguously a fact is stated in plain, readable text, the more likely a machine extracts it correctly; the more it's implied, buried, or locked inside something non-textual, the more likely it's missed.

**D. Why agreement across the web matters.**
Machines treat a fact as more trustworthy when many independent places say the same thing. A claim living in only one spot is fragile; repeated consistently across unrelated sources, it's far more likely to be believed and repeated. Related problem: mistaken identity — when several entities share a name, a system can conflate them unless something clearly distinguishes one from the others. How a brand is described across the *wider* web — not just its own pages — shapes what assistants say about it.

**E. Personalization and prior context.**
Assistants can draw on context they already hold about a person — earlier messages, past questions, stated preferences, location, other signals — and tailor what they surface. Two people asking the same question can get different brands, framing, or emphasis: part of the answer depends on who's asking, not just what content exists.

**F. Why machines drop content from emails.**
Inbox AI summaries are built from message text. When the real substance isn't available as readable text (e.g., carried by something a summarizer can't read, or buried under low-value filler), the summary has little to work with and the important part can disappear.

---

## Part B — Solution Design & Detailed Implementation Plan
### (from `Adobe-Hackathon-Round3-Plan.pdf`)

> This is a complete plan for Round 3: solution concept, architecture, specific checks per skill, report schema, engineering approach, day-by-day build schedule, testing strategy, and risk management — written so the work can be executed step-by-step without further design decisions.

### 1. Solution concept

Most entries will converge on the same shape: a single skill that crawls a site, runs a fixed checklist, and prints whatever is missing. That approach loses marks on two rubric lines:
- **False positives** — a checklist applied without regard to site type flags absence of product markup on a blog.
- **Poor generalization** — a checklist built from a handful of studied sites encodes those sites, not the underlying mechanism.

This plan differs in three deliberate ways, each aimed at a specific rubric criterion:

**1.1 Crawl once, analyse many**
A single acquisition skill visits the site and writes a canonical **evidence snapshot** to disk. Every analysis skill then reads that snapshot instead of touching the network again.
- Genuine separation of concerns — each analyser is a pure function over stored evidence.
- Determinism — two runs over the same snapshot produce identical findings.
- Politeness — each page fetched exactly once.
- Runtime budget — network time paid once, not once per concern.

**1.2 Conditional checks rather than universal ones**
Before any check runs, the acquisition skill classifies the site (ecommerce, local business, software/SaaS, publisher, documentation, portfolio) and classifies each crawled page (home, product, category, article, documentation, contact, about, legal). Checks declare which page types they apply to and are skipped elsewhere, with the skip recorded explicitly in the report.
- Largest lever on **detection-accuracy** (rewards few false positives as heavily as few misses).
- Also what makes the marketplace **generalize** — logic adapts to the site in front of it rather than assuming the shape of researched sites.

**1.3 Mechanism-first findings**
Every finding carries an explicit statement of the *mechanism* by which the defect breaks retrieval or engagement — not merely "this is absent." Mirrors the Round-2 appendix's own framing: crawler admitted → page readable → fact extractable → claim corroborated. Demonstrates encoded reasoning rather than a transcribed checklist.

---

### 2. Marketplace architecture

**Eight skills**, each owning one concern, composed by a single entrypoint. Decomposition maps one-to-one onto distinct failure mechanisms from the Round-2 appendix — defensible as separation of concerns, not padding.

```
brand-ai-readiness-audit/
  marketplace.json
  README.md
  report.schema.json
  skills/
    audit-orchestrator/      <- entrypoint
      SKILL.md
      scripts/  references/
    site-acquisition/        <- crawl, render, snapshot, classify
    machine-readability/
    structured-data/
    answer-extractability/
    entity-corroboration/
    freshness-provenance/
    engagement-audit/
  tests/
    fixtures/
```

| Skill | Concern it owns | Appendix basis |
|---|---|---|
| site-acquisition | Can a crawler reach the page at all, and what is on it? Produces the shared evidence snapshot. | A |
| machine-readability | Once inside, is the content actually readable as text by a non-browser client? | A, C |
| structured-data | Are the key facts marked up explicitly, validly and consistently with the visible page? | C |
| answer-extractability | Can a clear, self-contained fact be quoted out of a single retrieved chunk? | B |
| entity-corroboration | Does the wider web repeat the same facts, and is the brand identity unambiguous? | D |
| freshness-provenance | Is the content current, dated honestly and attributable to someone? | D |
| engagement-audit | Does a visitor arriving mid-funnel from an assistant orient, get an answer, and continue? | E |
| audit-orchestrator | Composition, de-duplication, severity assignment, prioritisation, schema-valid report. | — |

> If a leaner package is preferred, `freshness-provenance` can be folded into `entity-corroboration` without much loss (both concern trust signals). `structured-data` and `answer-extractability` should **not** be merged — they fail independently and often in opposite directions (a site can carry flawless JSON-LD while its prose remains impossible to quote out of context).

**2.1 Manifest**

```json
{
  "name": "brand-ai-readiness-audit",
  "version": "1.0.0",
  "skills": [
    { "id": "audit-orchestrator", "path": "skills/audit-orchestrator", "entrypoint": true },
    { "id": "site-acquisition", "path": "skills/site-acquisition" },
    { "id": "machine-readability", "path": "skills/machine-readability" },
    { "id": "structured-data", "path": "skills/structured-data" },
    { "id": "answer-extractability", "path": "skills/answer-extractability" },
    { "id": "entity-corroboration", "path": "skills/entity-corroboration" },
    { "id": "freshness-provenance", "path": "skills/freshness-provenance" },
    { "id": "engagement-audit", "path": "skills/engagement-audit" }
  ]
}
```

**2.2 How the entrypoint composes the others**

The orchestrator runs a fixed pipeline:
1. Invoke `site-acquisition` to produce the snapshot.
2. Invoke each analysis skill in a defined order; each reads the snapshot and emits a fragment file of candidate findings in a shared internal format.
3. Merge fragments: de-duplicate findings describing the same root cause reached by different routes, assign final severities via the documented model, allocate identifiers deterministically, sort suggested actions by impact vs. effort, append proactive recommendations, validate the assembled document against `report.schema.json` before emitting.
4. If a skill fails or its inputs are unavailable, its checks are recorded as **inconclusive**, never silently dropped.

---

### 3. What each skill checks

*(Working out these checks is stated in the brief as part of the task — this section is the substantive core of the plan. Every check is written against a mechanism, never against a string or layout observed on a particular site.)*

**3.1 site-acquisition**
- `robots.txt`: fetch, parse and honour it; report parse errors and overly broad disallow rules.
- AI-crawler user-agent rules specifically. Blocks on GPTBot, ClaudeBot, PerplexityBot, CCBot or Google-Extended are a frequent and near-invisible cause of total absence from assistant answers — worth a **critical** finding.
- `sitemap.xml` discovery, validity, coverage against discovered URLs, and `lastmod` values.
- HTTP status codes, redirect chains and loops, mixed http/https, trailing-slash duplication, and soft-404 pages that return 200 with error content.
- Canonical tags: presence, self-consistency, cross-domain canonicals, conflicts between canonical and sitemap.
- Robots meta and `X-Robots-Tag` headers, including `noindex`, `nosnippet`, `noarchive` and restrictive `max-snippet` values that prevent quotation even when indexing is permitted.
- Raw HTML capture and, where a headless browser is available, rendered DOM capture.
- Site-type and page-type classification, written to the snapshot for downstream gating.
- **Crawl policy:** sitemap first, then breadth-first from home page, capped at ~40 pages with a per-type quota so no single template dominates the sample; fixed politeness delay; deterministic URL ordering so repeat runs sample identically.

**3.2 machine-readability**
- **Render gap** (headline check): compare visible text extracted from raw HTML against text from the rendered DOM, report the difference as a percentage per page, name which content blocks exist only after JavaScript executes. Any assistant fetching without executing scripts sees only the raw version.
- Facts locked in non-text: pricing, specifications, hours or contact details present only inside images; content-bearing images with absent or decorative alt text; text rendered into canvas; SVG without title or accessible text; key content available only as a PDF.
- Semantic structure: missing or multiple `h1` elements, heading hierarchy skips, absence of landmark elements, pages where main content is indistinguishable from navigation.
- Content behind interaction: accordions, tabs or modals whose contents aren't in the initial markup; infinite scroll without paginated fallback; iframe-embedded substance.
- Text-to-markup ratio and boilerplate dominance, indicating pages whose extractable substance is thin relative to navigation furniture.

**3.3 structured-data**
- Presence and format of JSON-LD, microdata and RDFa across each page type.
- Validity rather than mere presence: does the JSON parse, are required properties for the declared type present, are enumerated values legal, are dates well formed.
- Coverage ratio computed per page type, so the finding reads as a proportion rather than a binary and carries prevalence evidence.
- Type correctness — e.g. a service business declaring `Product`, or an article declaring `WebPage` where `Article` carries far more usable properties.
- Entity graph coherence: stable `@id` values, cross-references between `Organization`, `WebSite`, `Product` and `Article` nodes, and a `sameAs` array on the `Organization` node.
- Conflict between markup and visible text (e.g. a price or rating in JSON-LD that disagrees with the rendered page) — a strong trust signal to check and an unusual finding to surface.
- Breadcrumb, FAQ, HowTo, LocalBusiness and Offer markup where the page type warrants it.

**3.4 answer-extractability** — *the main point of differentiation; addresses the step most entrants will skip: a retrieval system fetches a chunk of a page out of context and must be able to quote a clear fact from it.*
- Question-shaped headings answered directly in the first one or two sentences beneath them, rather than after several paragraphs of preamble.
- Chunk self-containment: paragraphs relying on unresolved pronouns or antecedents established elsewhere on the page. A sentence beginning with an unbound "it" is unquotable once separated from its section.
- Entity restatement: whether the brand/product name recurs through the body rather than appearing once in the title.
- Presence of definitional sentences of the form "X is a Y that does Z" for the core entities the site is about.
- Specifications, comparisons and figures expressed as HTML tables or lists rather than as running prose or images.
- Stable `id` attributes on headings, permitting an assistant to deep-link a citation to the exact section.
- Title and meta description quality; near-duplicate pages competing to answer the same question; thin pages below a usable word count.
- Whether operational facts such as pricing, hours, coverage area and contact details appear as literal text somewhere on the site.

**3.5 entity-corroboration**
- Extract the brand's canonical claims from its own pages: legal/trading name, category, location, founding date, leadership, principal offering.
- Search off-site for independent repetition of each claim, count distinct domains carrying it. Claims appearing on only one domain are fragile and should be flagged as such.
- Name-collision detection: identify other entities sharing the brand name, assess whether disambiguating context (category, location, `sameAs` links) exists that a system could use to tell them apart.
- Consistency of name, address and phone across the site and across external listings found.
- Whether `sameAs` targets actually resolve and actually refer to the same entity.
- Presence in structured public references such as Wikidata, and in recognised industry directories appropriate to the detected site type.

**3.6 freshness-provenance**
- `datePublished`/`dateModified` presence, plausibility, and agreement with sitemap `lastmod` values; `lastmod` values that update on every crawl for every page are a **negative** signal, not positive.
- Stale surface markers: copyright years, year strings in headings, references to superseded versions or past events written in present tense.
- Undated pages that make time-sensitive claims (pricing, availability).
- Dead or redirecting outbound links, and citation density on pages making factual claims.
- Author attribution, credentials and an about page establishing who is speaking.

**3.7 engagement-audit** — *framing that keeps this from drifting into generic usability review: a visitor referred by an assistant arrives mid-funnel, on a deep page, holding a specific question, with no brand loyalty and low patience.*
- Does the landing page answer the likely arrival intent above the fold, or open with an undifferentiated hero and defer the substance.
- Time to first meaningful content, render-blocking resource weight, and layout shift — proxies for the bounce that precedes any engagement at all.
- Interruptions on arrival: interstitials, cookie walls that block content rather than sit beside it, forced registration, autoplaying media, aggressive exit handlers.
- Orientation: breadcrumbs, clear indication of where in the site the visitor has landed, an evident next step.
- Internal linking: dead-end pages with no onward path, orphan pages reachable only from the sitemap, link density on high-value pages.
- Call-to-action presence, clarity and singularity on pages likely to receive assistant referrals.
- Mobile viewport configuration, tap-target sizing and font legibility.
- Context continuity: whether anchored deep links land on the correct section, whether filter/search state survives navigation, whether an on-site search exists for visitors whose question wasn't answered by the landing page.

---

### 4. Report design

Schema keeps every field the brief requires and extends it. Extensions accrue marks on output-design and suggested-action criteria since they carry mechanism, prevalence and verification.

```json
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "audit_meta": {
    "pages_crawled": 34,
    "render_mode": "headless" | "static-only",
    "robots_respected": true,
    "site_type": "ecommerce",
    "skills_run": ["structured-data", "engagement-audit", "..."]
  },
  "summary": { "total_findings": 6, "critical": 1, "high": 2, "medium": 3 },
  "findings": [
    {
      "id": "F-001",
      "check_id": "SD-COVERAGE-PRODUCT",
      "title": "No JSON-LD structured data on product pages",
      "severity": "high",
      "confidence": "high",
      "category": "discoverability",
      "mechanism": "Assistants read price and availability from Product/Offer markup. Without it the fact must be inferred from prose and is usually dropped.",
      "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
      "affected_urls": ["/p/one", "/p/two"],
      "prevalence": { "affected": 12, "sampled": 12 },
      "suggested_action": {
        "summary": "Add Product/Offer JSON-LD to every product page.",
        "priority": "high",
        "effort": "medium",
        "steps": ["...", "..."],
        "example": "...",
        "expected_impact": "...",
        "verification": "Re-run audit; SD-COVERAGE-PRODUCT should report 12/12."
      }
    }
  ],
  "proactive_recommendations": ["..."],
  "not_applicable": [{ "check_id": "...", "reason": "no product pages" }],
  "inconclusive": [{ "check_id": "...", "reason": "render unavailable" }]
}
```

> The `not_applicable` and `inconclusive` arrays are deliberate: they demonstrate that a check *ran* and chose not to fire — exactly the evidence an evaluator needs to credit the marketplace with avoiding false positives rather than simply having missed something.

**4.1 Severity model**

Severity must be computed, not improvised, or the output ceases to be deterministic. Document the model in `references/severity-model.md` and implement it in code. Severity is a function of three inputs, then adjusted for confidence:
- **Mechanism impact:** does the defect break the pipeline outright (crawler blocked, content unreadable), degrade it (fact present but hard to extract), or weaken it at the margin (trust signal absent)?
- **Prevalence:** proportion of sampled pages of the relevant type affected.
- **Page importance:** home and primary conversion pages weigh more than deep archive pages.
- A finding derived from a heuristic rather than direct observation is **downgraded one level** and marked with lower confidence.

> Publishing this matrix in `references/` makes the severity column auditable — worth more to an evaluator than any individual severity call.

---

### 5. Proactive recommendations

Rubric awards marks for suggestions beyond detected defects — must be specific and mechanism-linked, not generic best-practice filler. Recommended standing set:

- Publish an `llms.txt` file and a machine-readable canonical facts page, giving assistants a single authoritative source for the brand's core claims.
- Adopt an **answer-block pattern** site-wide: question-shaped heading → direct ~40-word answer → supporting detail. Single highest-yield structural change for citation.
- Add stable `id` anchors to every heading so a citation can point at a section rather than a page.
- Restate the entity name within each section so chunks remain intelligible when retrieved in isolation.
- Build an entity home page carrying a complete `sameAs` graph, and establish a Wikidata presence to anchor identity.
- Replace image-rendered specification sheets, price lists and charts with HTML tables carrying the same values.
- Publish transcripts for video and audio content, converting non-text substance into extractable text.
- Run a corroboration programme: get the same canonical facts published on independent domains, since a claim living in one place is treated as fragile.
- Maintain a changelog and honest `dateModified` values, giving a defensible freshness signal.
- Add comparison, alternatives and glossary pages, which are disproportionately retrieved because they answer the comparative questions users actually ask.
- From Appendix F: place the substance of outbound email in front-loaded readable text rather than in images or beneath filler, so inbox summarisers retain it.

---

### 6. Engineering approach

**6.1 Stack**
Python 3 with `requests`, `beautifulsoup4`, `lxml` and `jsonschema` as the required dependency set. Playwright optional, used only when already present. No model weights, no large assets — submission sits far below the 50 MB cap.

**6.2 Graceful degradation**
Assume the evaluating machine has no headless browser installed. Every script must run in requests-only mode and mark render-dependent checks as **inconclusive** rather than crashing or guessing. Render capability is detected once in `site-acquisition` and recorded in `audit_meta`, so the report is honest about what it could and could not observe. A marketplace that degrades cleanly outscores one that produces a richer report only under conditions that may not hold.

**6.3 Scripts**

| Script | Skill | Responsibility |
|---|---|---|
| crawl.py | site-acquisition | Fetch, robots, sitemap, status, canonical, snapshot write |
| render.py | site-acquisition | Optional headless capture of rendered DOM |
| classify.py | site-acquisition | Site-type and page-type classification |
| render_gap.py | machine-readability | Raw versus rendered text diff |
| readability.py | machine-readability | Non-text facts, semantics, hidden content |
| extract_sd.py | structured-data | Parse JSON-LD, microdata, RDFa |
| validate_sd.py | structured-data | Validity, coverage, graph, conflicts |
| chunk_quality.py | answer-extractability | Self-containment, answer blocks, anchors |
| corroborate.py | entity-corroboration | Claim extraction, off-site search, collisions |
| freshness.py | freshness-provenance | Dates, staleness, provenance |
| engagement.py | engagement-audit | Arrival intent, friction, orientation, paths |
| compose_report.py | audit-orchestrator | Merge, de-duplicate, severity, ordering |
| validate_report.py | audit-orchestrator | Schema validation before emission |

**6.4 Skill hygiene**
- Keep each `SKILL.md` lean, roughly **150 lines or fewer**, with detailed checklists pushed to `references/` and executable logic pushed to `scripts/` (progressive disclosure).
- Declare allowed-tools explicitly per skill. Only `entity-corroboration` needs web search; the analysis skills need file reading and script execution only.
- State the read-only guardrails inside every `SKILL.md`, not just the README: no POST requests, no authenticated areas, no form submission, robots respected, rate limited, no site modification.
- Validate every skill folder with `skills-ref validate` before packaging.
- Make the manifest self-contained, with no external service required to resolve it.

---

### 7. Field research protocol

The brief makes field research part of the task. Two evenings of structured work is sufficient if recorded systematically rather than absorbed impressionistically.

- Select ~20 sites spanning the site types the classifier recognises, deliberately mixing well-known brands with obscure ones.
- For each site, choose three questions the brand ought to own. Ask each question of two or three assistants with search enabled. Record whether the brand was cited, mentioned without citation, misrepresented, or absent entirely.
- Audit each site by hand and log every candidate signal in a single spreadsheet: **signal, mechanism, observed in cited sites, observed in uncited sites**.
- Keep only signals that **discriminate**. A property shared equally by cited and uncited sites is noise and will produce false positives on unseen sites.
- Distil surviving signals into `references/failure-modes.md` as a table of **signal, mechanism, check identifier, default severity, standard fix**. This file becomes the shared spine of the marketplace, and is strong evidence of rigour if an evaluator opens it.

---

### 8. Build schedule

| Day | Work | Exit condition |
|---|---|---|
| 1 | Field research pass; build the signal spreadsheet; draft `failure-modes.md` | Discriminating signals identified and documented |
| 2 | Repository scaffold, `marketplace.json`, `report.schema.json`, `crawl.py`, `classify.py` | A snapshot can be produced for any URL |
| 3 | `machine-readability` and `structured-data` skills and scripts | Both emit valid finding fragments |
| 4 | `answer-extractability` and `engagement-audit` | Both emit valid finding fragments |
| 5 | `entity-corroboration` and `freshness-provenance` | Off-site search path works and is rate-limited |
| 6 | Orchestrator: merge, de-duplicate, severity model, ordering, schema validation | End-to-end run produces a schema-valid report |
| 7 | Fixtures, false-positive tuning, runs against five unseen sites | No finding survives that a sceptical reader would call spurious |
| 8 | README, SKILL.md polish, `skills-ref validate`, runtime measurement, packaging | Zip built, under 50 MB, audit under five minutes |

---

### 9. Testing strategy

- Build `tests/fixtures` containing synthetic pages that deliberately break each check, paired with clean counterparts. Assert both that the check fires on the broken page and stays silent on the clean one. **Negative assertions matter more than positive ones.**
- Include fixtures for awkward cases: a JavaScript-only page, a page whose JSON-LD contradicts its visible text, a site whose robots.txt blocks only AI crawlers, a single-page application, a site with no sitemap.
- Run the full audit against **five unseen live sites** of different types: a local business, a SaaS product, an ecommerce store, a publisher, and a documentation site.
- Read every finding from those runs and ask whether a sceptical evaluator would call it a false positive. Delete or gate any check that cannot survive that question.
- Run the same site twice and diff the reports. Any difference other than the timestamp indicates non-determinism that must be traced and removed.
- Measure wall-clock runtime on each test site and confirm the five-minute budget holds with margin.

---

### 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Runtime exceeds the five-minute budget on large sites | Hard page cap with per-type quotas, bounded concurrency, per-request timeout, overall wall-clock guard that stops crawling and reports on what was gathered |
| False positives from checks applied to inapplicable page types | Every check declares its applicable page types and is gated on the classifier; skips recorded in `not_applicable` so the evaluator can see the check ran |
| Evaluating machine has no headless browser | Requests-only fallback throughout; render capability detected once and recorded; render-dependent checks marked inconclusive rather than guessed |
| Overfitting to the sites studied during research | Checks written against mechanisms only; no site-specific strings, selectors or thresholds tuned to one example; discriminating-signal filter applied during research |
| Off-site search is slow, rate-limited or unavailable | Cap the number of queries, cache within a run, degrade corroboration checks to inconclusive rather than failing the audit |
| Decomposition read as padding rather than separation of concerns | Each skill maps to a distinct failure mechanism, owns distinct checks, is individually runnable; README states the mapping explicitly |
| Target site treats the audit as abusive traffic | Robots respected, fixed politeness delay, single fetch per URL, identifying user agent, no authenticated or state-changing requests |

---

### 11. Submission checklist

- [ ] Zip of the marketplace root, containing `marketplace.json` and every skill folder.
- [ ] Exactly one skill marked as entrypoint in the manifest.
- [ ] Every skill folder passes `skills-ref validate`.
- [ ] `README.md` at the root describing what each skill does and how the entrypoint composes them.
- [ ] `report.schema.json` present, and the orchestrator validates against it before emitting.
- [ ] Every required field present in each finding: `id`, `title`, `severity`, `evidence`, `suggested_action`; and in the summary: `site`, `audited_at`, counts by severity.
- [ ] Read-only guarantees stated in the README and in each `SKILL.md`.
- [ ] Archive under 50 MB with no model weights.
- [ ] Audit completes in under five minutes on a typical site.
- [ ] Clean run demonstrated on at least one site never used during development.

---

### 12. Summary

The plan converts the Round-2 reasoning into a marketplace of eight narrowly scoped skills sharing a single evidence snapshot, gated by site and page classification, and composed by an orchestrator that emits one schema-valid, mechanism-annotated report. The three design decisions that carry the most weight are: crawling once into a shared snapshot, making every check conditional on page type, and stating the mechanism behind every finding. Together they address the detection-accuracy, generalisation, composition and suggested-action criteria directly, and they are the elements that separate this approach from the checklist-runner most submissions will produce.

---

## Quick-Reference: Next Steps

1. Set up repo scaffold matching the layout in §2 (Part B).
2. Do the field-research pass (§7) — even a lighter version — before writing checks, so signals are evidence-based rather than guessed.
3. Build `site-acquisition` first (everything else depends on its snapshot).
4. Build analysis skills in the suggested day-by-day order (§8).
5. Build the orchestrator + schema validation last, once fragments exist to merge.
6. Test against unseen sites before packaging (§9), and verify the submission checklist (§11).
