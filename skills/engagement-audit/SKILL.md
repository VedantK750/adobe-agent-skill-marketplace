---
name: engagement-audit
description: Checks whether a visitor referred by an AI assistant, arriving deep in the site with a specific question, can orient and stay - mobile viewport, page weight and response time, dead-end pages with no onward path, navigation and breadcrumbs, clear calls to action, autoplay and interruption patterns, consent notices that crowd out content, and on-site search. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Engagement Audit

## When to use
After `site-acquisition`. Reads `snapshot.json`; never touches the network.

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

## Run
`python3 scripts/analyze.py --workdir DIR`

## Safety
Recommend-only: this skill reports, it never changes the audited site. It is a
pure function of `snapshot.json` — it opens no network connection at all, so it
cannot issue a request of any kind, authenticated or otherwise. It writes only
its own fragment inside the working directory.

## Output
`fragments/engagement-audit.json`.
