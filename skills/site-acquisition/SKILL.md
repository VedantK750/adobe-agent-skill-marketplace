---
name: site-acquisition
description: Crawls a website read-only and produces the shared evidence snapshot every other audit skill reads, then reports access-layer problems - robots.txt blocking AI crawlers, missing or broken sitemaps, error status codes, redirect chains, noindex/nosnippet suppression and missing canonicals. Use as the first step of a brand AI-readiness audit, before any content analysis.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Site Acquisition

## When to use
First step of every audit. Produces `snapshot.json`; nothing else in the
marketplace touches the network.

## Inputs
- `url` (required), `workdir` (required), `max_pages` (default 40),
  `--no-render` to skip headless rendering.

## What it checks
Step one of the pipeline: can a machine get in at all? A failure here makes
every later check moot, so these findings carry blocking impact.

- `ACC-AI-CRAWLER-BLOCKED` — robots.txt disallows GPTBot, ClaudeBot,
  PerplexityBot, CCBot, Google-Extended and similar. Frequently a copied
  default rather than a decision, and invisible to anyone browsing the site.
- `ACC-BLANKET-DISALLOW` — wildcard root disallow, often a staging rule
  deployed to production.
- `ACC-NO-ROBOTS` / `ACC-NO-SITEMAP` — discovery left to link-following alone.
- `ACC-BROKEN-PAGES` / `ACC-REDIRECT-CHAINS` — wasted crawl budget, broken paths.
- `ACC-SNIPPET-SUPPRESSED` — `noindex`, `nosnippet` or `max-snippet:0`. The
  second and third permit indexing but forbid quotation, so the page can rank
  and still never be citable.
- `ACC-CANONICAL-MISSING` — duplicate variants competing as separate documents.

## Procedure
1. Fetch and parse robots.txt. Obey it for our own agent, and separately
   record which AI agents it excludes.
2. Discover URLs: sitemap first, then breadth-first from the home page.
   Deterministic ordering, so repeat runs sample the same pages.
3. Fetch each URL once with a politeness delay. GET only.
4. Extract per-page metadata: title, description, canonical, robots
   directives, headings with ids, images with alt, JSON-LD blocks, iframes,
   link counts, raw text and body text.
5. Render with Playwright if installed. If it is absent, record
   `render_mode: static-only` — do not guess at rendered content.
6. Classify site type and page type (`scripts/classify.py`) and write both
   into the snapshot.
7. Run `scripts/analyze.py` to emit the access-layer findings.

## Why classification matters
Every downstream check is gated on page type. Reporting "no Product schema"
on an about page is the commonest way an audit loses credibility, and gating
here is what prevents it. See `references/classification.md`.

## Safety
GET only. No POST, no form submission, no authenticated areas, no cookies
carried across hosts, no rate abuse. Crawl is capped at `max_pages` with a
wall-clock budget; on timeout it stops and reports what it gathered.

## Output
`snapshot.json` in the workdir, plus `fragments/site-acquisition.json`.
