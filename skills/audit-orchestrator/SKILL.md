---
name: audit-orchestrator
description: Entrypoint for the brand-ai-readiness-audit marketplace. Given a website URL, runs the acquisition and analysis skills, composes their findings into one schema-valid audit report of AI-discoverability and on-site-engagement problems with evidence, severity and prioritized fixes. Use when asked to audit a site for why it is missing, stale or misrepresented in AI assistants, or why visitors who arrive do not engage.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Audit Orchestrator (entrypoint)

## When to use
The user supplies a website URL or domain and wants to know what is hurting
its AI discoverability or on-site engagement, and what to do about it. This
is the only skill in the marketplace invoked directly; it composes the others.

## Inputs
- `url` (required): the site to audit, e.g. `https://example.com`.
- `max_pages` (optional, default 40): crawl cap.
- `workdir` (optional, default `./audit-run`): where evidence and the report
  are written.

## Guarantees
Recommend-only. Nothing in this marketplace modifies the target site. All
requests are GET, robots.txt is obeyed, authenticated and state-changing
areas are never touched, and every URL is fetched exactly once.

## Procedure

1. **Acquire.** Run `site-acquisition` to produce `snapshot.json`. Every later
   step reads that file; none of them touches the network. If acquisition
   fails, stop and report why — the rest of the pipeline has no input.

2. **Analyse.** Run each analysis skill against the snapshot. Each writes a
   findings fragment to `workdir/fragments/`. Run them in this order:
   `site-acquisition` (its `analyze.py` turns crawl evidence into findings),
   `machine-readability`, `structured-data`, `answer-extractability`,
   `entity-corroboration`, `freshness-provenance`, `engagement-audit`.
   The set of skills run is taken from `marketplace.json`, not hardcoded:
   `run_audit.py` reads the manifest and runs exactly the skills it declares,
   in this order, so adding or removing a skill in the manifest changes the
   pipeline with no code change. A skill that fails is recorded and skipped;
   the pipeline continues so one broken analyser degrades the report rather
   than losing it.

3. **Corroborate (needs search).** `entity-corroboration` writes
   `corroboration_targets.json`. If a search tool is available, run those
   queries, collect the URLs of results that genuinely refer to this brand,
   write `{"urls": [...]}` to a file, set `AUDIT_SEARCH_RESULTS` to its path
   and re-run that skill. Without search, its off-site checks stay
   `inconclusive` — never assert corroboration that was not verified.

4. **Compose.** Run `scripts/compose_report.py`. It computes severity
   centrally (see `references/severity-model.md`), de-duplicates findings that
   share a root cause, assigns `F-NNN` ids in deterministic order, and selects
   the proactive recommendations that apply to this site.

5. **Validate.** Run `scripts/validate_report.py`. Do not present a report that
   fails validation; fix the fragment that caused it and recompose.
   `run_audit.py` enforces this: on a validation failure it still writes the
   report — that is the artefact needed to diagnose the problem — but exits
   with status 2, so a caller checking only the return code cannot ship an
   invalid report believing it passed.

6. **Present.** Emit the JSON report. Add `--markdown` for a human-readable
   version. Lead with the critical and high findings and their fixes.

## Running it

```bash
python3 skills/audit-orchestrator/scripts/run_audit.py \
  --url https://example.com --workdir ./audit-run --markdown
```

Individual stages, if running them by hand:

```bash
python3 skills/site-acquisition/scripts/crawl.py --url URL --workdir DIR
python3 skills/<skill>/scripts/analyze.py --workdir DIR
python3 skills/audit-orchestrator/scripts/compose_report.py --workdir DIR --out DIR/audit-report.json
python3 skills/audit-orchestrator/scripts/validate_report.py --report DIR/audit-report.json
```

## Output
A single JSON report validated against `report.schema.json`. Required fields
per finding: `id`, `title`, `severity`, `evidence`, `suggested_action`.
Required summary metadata: `site`, `audited_at`, counts by severity.

Beyond the floor, the report carries `mechanism` (why the defect breaks
retrieval), `prevalence`, `confidence`, `proactive_recommendations`, and two
arrays that matter as much as the findings themselves:

- `not_applicable` — the check ran and correctly did not apply to this site.
- `inconclusive` — the check could not be evaluated on this run.

Recording both is what distinguishes a check that stayed silent deliberately
from one that missed something. Never delete them to make a report look cleaner.

`proactive_recommendations` are the improvements worth making where no defect
was found, and they are selected against what the site turned out to be rather
than appended as a fixed list — a documentation site is not told to mark up
offers, a site with no video is not told to publish transcripts. Their ids are
stable across reports, so gaps in the sequence are expected and meaningful.

## Interpreting severity
`critical` is reserved for defects that break the retrieval pipeline outright:
the origin does not answer, the crawler is refused entry, or the content is
unreadable once inside. Everything that degrades or weakens a signal caps at
`high`, however widespread. See `references/severity-model.md`.

## When the sample is small
A crawl that returns only a page or two is common and legitimate — a bot filter
serves the home page and refuses the rest, or the site really is that small.
Checks that state a property of the whole site do not assert on that evidence;
they record `inconclusive` with the page count. Expect a short report with a
full `inconclusive` list in that case, and read it as "not enough was seen",
not as "the site is clean". `audit_meta.pages_crawled` is the number to check
first.
