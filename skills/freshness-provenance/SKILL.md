---
name: freshness-provenance
description: Checks whether content is current, honestly dated and attributable - machine-readable publication dates, undated time-sensitive claims like prices and hours, stale copyright years and year-stamped headings, sitemap lastmod honesty, and author attribution. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Freshness and Provenance

## When to use
After `site-acquisition`. Reads `snapshot.json`; never touches the network.

## The mechanism
Recency and attribution are among the few quality signals available without
reading the content. An undated page cannot be preferred over an older
competitor and cannot be ruled out as stale either, so it tends to be passed
over when a current answer is wanted. Attribution works the same way:
content traceable to a named, credentialed person outranks anonymous copy.

## Checks
- `FP-NO-DATES` — articles and documentation with no `datePublished` or
  `dateModified`.
- `FP-UNDATED-TIME-SENSITIVE` — prices, plans, hours or version numbers
  stated with no date, risking a superseded figure being repeated as current.
- `FP-STALE-COPYRIGHT` — a footer year well in the past, appearing on every
  page. Treat it as a symptom and check what else has not been reviewed since.
- `FP-LASTMOD-UNIFORM` — every sitemap entry sharing one date, which means
  the value reflects the build rather than the content. Once the signal is
  known to be unreliable it stops being used, so genuinely updated pages lose
  the benefit of having been updated.
- `FP-STALE-YEAR-HEADINGS` — headings naming years now well past.
- `FP-NO-AUTHOR` — articles with no author in markup or byline.

## Avoiding false positives
Date checks run only on `article` and `documentation` page types; a contact
page needs no publication date. Copyright and year checks allow a one-year
grace period. Uniform-lastmod requires more than eight entries before firing.

## Run
`python3 scripts/analyze.py --workdir DIR`

## Output
`fragments/freshness-provenance.json`.
