---
name: engagement-audit
description: Checks whether a visitor referred by an AI assistant, arriving deep in the site with a specific question, can orient and stay - mobile viewport, page weight and response time, dead-end pages with no onward path, navigation and breadcrumbs, clear calls to action, autoplay and interruption patterns, consent notices that crowd out content, and on-site search. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Engagement Audit

## When to use
After `site-acquisition`. Reads `snapshot.json`; never touches the network.

## Inputs
- `--workdir DIR` (required) — a directory holding `snapshot.json`.
  Page weight and response time are read from what the crawler already
  measured; this skill issues no request of its own.

## The framing
This is the second half of the problem: the visitor arrived, do they stay?

The framing that keeps these checks from drifting into generic usability
review is the specific visitor being modelled — someone referred by an
assistant, landing on a deep page rather than the home page, holding one
specific question, with no prior relationship to the brand and no patience.
Every check asks whether *that* visitor can orient, get an answer, and find a
next step. A check that does not serve that visitor does not belong here.

## Checks
- `EN-NO-VIEWPORT` — assistant referrals skew mobile; without a viewport the
  page renders at desktop width and is bounced before it is read.
- `EN-HEAVY-PAGES` / `EN-SLOW-RESPONSE` — every second before content appears
  converts part of that traffic into a bounce. Slow response also limits how
  much a crawler fetches, so it damages both halves of the problem at once.
- `EN-DEAD-END-PAGES` — a page with no onward links answers one question and
  ends the session.
- `EN-NO-ORIENTATION` — no navigation landmark, so a deep arrival cannot tell
  where they are or whether the rest of the site is worth exploring.
- `EN-NO-CTA` — a visitor whose question was just answered is at peak intent;
  with no stated next step that intent expires where it stands.
- `EN-AUTOPLAY-MEDIA`, `EN-INTERRUPTIONS` — unrequested sound, and
  subscription prompts placed before any value is delivered.
- `EN-CONSENT-BLOCKS-CONTENT` — consent copy dominating pages that carry
  little else, which harms visitors and extractors together.
- `EN-NO-SITE-SEARCH` — no recovery path when the landing page nearly answers
  the question.

## Avoiding false positives
Checks run against landing-candidate page types, not legal or listing pages.
CTA checks run only on conversion-relevant types. Site search is not assessed
below fifteen crawled pages, where it is not yet material. Interruption
detection is marked low confidence because it infers from copy rather than
from observed behaviour, and the severity model downgrades it accordingly.

## Procedure
1. Load `snapshot.json` and select the landing-candidate page types — the
   pages an assistant would plausibly send someone to. Legal and listing
   pages are excluded; nobody is referred to a terms page to get an answer.
2. Check the arrival conditions: viewport declaration, payload size, and
   server response time. Response time fires only where slowness is systemic
   across a meaningful sample, never on a single jittery fetch, so the finding
   is a property of the site rather than of one request.
3. Check whether the visitor can orient: a navigation landmark, breadcrumbs,
   and onward links out of the page they landed on.
4. Check whether intent can be acted on: a stated next action on
   conversion-relevant page types.
5. Check what interrupts: autoplay media, arrival-time subscription prompts,
   and consent copy that dominates pages carrying little else.
6. Check the recovery path — on-site search — but only above fifteen crawled
   pages, below which it is not yet material.
7. Write the fragment with impact classes and confidence. Copy-inferred
   checks are marked low confidence, and the severity model downgrades them.

Run: `python3 scripts/analyze.py --workdir DIR`

## Output
`fragments/engagement-audit.json` — findings, `not_applicable` and
`inconclusive` records for the orchestrator to compose.
