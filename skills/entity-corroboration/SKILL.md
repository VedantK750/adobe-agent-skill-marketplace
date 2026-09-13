---
name: entity-corroboration
description: Checks whether the brand's claims are repeated by independent sources and whether its identity is unambiguous - external profile links, sameAs completeness, name-address-phone consistency, self-description agreement, single-source claims and name collisions with other entities. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write, WebSearch]
---

# Entity Corroboration

## When to use
After `site-acquisition`. The on-site half reads `snapshot.json` only. The
off-site half needs a search capability.

## The mechanism
Two ideas from the background material. A fact repeated consistently across
unrelated sources is treated as far more reliable than one that lives in a
single place — a claim stated only by the party it benefits is fragile. And
when several entities share a name, they are conflated unless something
clearly distinguishes them, so facts get attributed to the wrong organisation.

## Checks
- `EC-FEW-EXTERNAL-PROFILES` — few or no links to external identity
  platforms, counting both anchors and `Organization.sameAs`.
- `EC-NAP-INCOMPLETE` — for place-based businesses, name, address and phone
  not all present as plain text in a consistent format.
- `EC-INCONSISTENT-SELF-DESCRIPTION` — the site names itself differently in
  `title` and `og:title`, supplying conflicting identity evidence.
- `EC-WEAK-IDENTITY-ANCHORING` — no external profiles, no `sameAs` graph, and
  either no `Organization` node or a common-word brand name: a machine has
  almost nothing to disambiguate the entity by. Computed entirely on-site, so
  it fires even when no search capability is available.
- `EC-SINGLE-SOURCE-CLAIMS` — claims repeated on too few independent domains.
  **Requires search.**
- `EC-NAME-COLLISION` — other entities sharing the name, with no
  disambiguating category or location on the site. **Requires search.**

## Two-phase procedure
1. Run `scripts/analyze.py --workdir DIR`. It performs the on-site checks
   deterministically and writes `corroboration_targets.json`: the brand's
   canonical claims plus a query worklist.
2. If a search tool is available, run those queries. Collect the URLs of
   results that genuinely refer to *this* brand — discard same-name entities,
   and note them, since they are the evidence for `EC-NAME-COLLISION`. Write
   `{"urls": [...]}` to a file, set `AUDIT_SEARCH_RESULTS` to its path, and
   re-run the script.

Without search, the two off-site checks report `inconclusive` and say why,
but the on-site checks — including `EC-WEAK-IDENTITY-ANCHORING` — still run and
fire, so the skill is never a silent no-op on a machine that lacks search.
Never assert corroboration that was not actually verified — an unverified
claim of corroboration is a worse failure than an honest gap.

## Judging independence
Count distinct domains, not mentions. Press releases syndicated across many
sites are one source, not many. Domains the brand controls do not count.

## Run
`python3 scripts/analyze.py --workdir DIR`

## Safety
Recommend-only: this skill reports, it never changes the audited site. It reads
`snapshot.json` and, when a search tool is supplied, issues read-only search
queries with a capped query budget. It never fetches authenticated areas,
submits forms, or sends anything but GET/search reads, and writes only inside
the working directory.

## Output
`fragments/entity-corroboration.json` and `corroboration_targets.json`.
