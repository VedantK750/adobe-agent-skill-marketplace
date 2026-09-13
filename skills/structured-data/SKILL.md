---
name: structured-data
description: Checks schema.org structured data for presence, parse validity, coverage per page type, type correctness, entity-graph completeness including Organization sameAs, and conflicts between markup values and the visible page. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Structured Data

## When to use
After `site-acquisition`. Reads `snapshot.json`; never touches the network.

## Inputs
- `--workdir DIR` (required) — a directory holding `snapshot.json`.
  No other input. The skill is a pure function of that file.

## The mechanism
Structured data is the only channel that states a fact in a form requiring no
inference. Without it, every attribute — price, hours, author, rating — must
be recovered from prose, and an uncertain inference is more often dropped
than risked. Markup that is present but invalid is worse than absent, because
it looks correct in a source review while delivering nothing.

## Checks
- `SD-ABSENT` — no JSON-LD, microdata or RDFa anywhere.
- `SD-INVALID-JSON` — blocks that fail to parse and are discarded wholesale.
- `SD-COVERAGE-<PAGETYPE>` — coverage measured per page type and reported as
  a ratio, gated so it only runs where that page type exists.
- `SD-INCOMPLETE-PROPS` — declared types missing their required properties.
- `SD-NO-ORGANIZATION` — no machine-readable entity for facts to attach to.
- `SD-NO-SAMEAS` — no explicit link between this site and external profiles
  describing the same entity.
- `SD-TEXT-CONFLICT` — markup price disagreeing with the rendered price. An
  unusual check and a strong one: a consumer repeating a price the visitor
  never sees is worse than one stating nothing.

## Avoiding false positives
Coverage checks are gated on page type via `EXPECTED` in `scripts/analyze.py`.
Where a page type is absent from the site, the check emits `not_applicable`
with the reason rather than firing. Extend `EXPECTED` to add a page type —
do not remove the gate.

## Procedure
1. Load `snapshot.json` and take the successfully fetched HTML pages.
2. Parse every JSON-LD block, plus microdata and RDFa flags, per page.
   Record blocks that fail to parse: they are discarded wholesale by
   consumers, so an invalid block is worse than an absent one.
3. Flatten `@graph` and array forms into a flat list of typed nodes, so a
   site nesting its entities is measured the same as one that does not.
4. Group pages by classified page type and compute coverage per type against
   `EXPECTED` — the type-to-schema map. Types absent from the site emit
   `not_applicable` rather than firing.
5. Check declared types for their required properties, and the entity graph
   for an `Organization`/`LocalBusiness` node and its `sameAs` links.
6. Compare markup values against the visible text for the same fact, with
   currency and full decimal matched, so a matching price cannot read as a
   conflict.
7. Write the fragment. Severity is not assigned here: the orchestrator
   computes it from impact, prevalence and confidence.

Run: `python3 scripts/analyze.py --workdir DIR`

## Output
`fragments/structured-data.json` — findings, `not_applicable` and
`inconclusive` records for the orchestrator to compose.
