---
name: structured-data
description: Checks schema.org structured data for presence, parse validity, coverage per page type, type correctness, entity-graph completeness including Organization sameAs, and conflicts between markup values and the visible page. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Structured Data

## When to use
After `site-acquisition`. Reads `snapshot.json`; never touches the network.

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

## Run
`python3 scripts/analyze.py --workdir DIR`

## Safety
Recommend-only: this skill reports, it never changes the audited site. It is a
pure function of `snapshot.json` — it opens no network connection at all, so it
cannot issue a request of any kind, authenticated or otherwise. It writes only
its own fragment inside the working directory.

## Output
`fragments/structured-data.json`.
