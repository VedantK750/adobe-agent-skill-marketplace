# Severity model

Severity is computed centrally in `compose_report.py`, never assigned by the
skill that raised the finding. Two reasons: the scale would drift between
skills, and a report whose severities were improvised is not reproducible.

## Inputs

Each skill supplies three things and lets the orchestrator do the rest.

**1. Mechanism impact** — how the defect breaks the pipeline.

| Impact | Meaning | Base severity |
|---|---|---|
| `blocking` | Breaks the pipeline outright. Crawler refused, or content unreadable once inside. | critical |
| `degrading` | The fact exists but is hard to reach, extract or trust. | high |
| `weakening` | A quality or trust signal is absent. | medium |

**2. Prevalence** — affected over sampled, for the page type the check applies to.

Applied only when the denominator is at least 5. A site-level singleton
(1 of 1) is not "100% prevalent"; it is one fact about the site. Treating it
as universal inflated severity badly in early testing — a missing sitemap was
scoring critical.

- share >= 0.8: +1 level
- share <= 0.2: -1 level

**3. Page importance** — `critical`, `high`, `normal` or `low`. Home and
primary conversion pages outrank deep archive pages. +1 or -1 level.

## Adjustment

**Confidence** only ever lowers severity. A heuristic result should not
outrank a directly observed one.

- `medium`: -1 level
- `low`: -2 levels

**Upward shifts are capped at one level** in total. Without the cap, a
high-importance finding at full prevalence jumped two levels and everything
collected at the top of the scale.

## The critical rule

`critical` is reserved for `blocking` impact. Nothing that degrades or
weakens a signal reaches it, however widespread.

This is the rule that keeps the top of the scale meaningful. A reader
scanning for what to fix first should find only the things that stop the
site being read at all: robots.txt refusing AI crawlers, content that exists
only after JavaScript runs, pages that forbid quotation. A missing meta
description is a real problem and it is not the same kind of problem.

## Worked examples

| Finding | Impact | Prevalence | Importance | Confidence | Result |
|---|---|---|---|---|---|
| robots.txt blocks GPTBot | blocking | 40/40 | critical | high | critical (capped +1 from critical) |
| No JSON-LD on product pages | degrading | 12/12 | high | high | high (would be critical; capped by the rule) |
| No meta description | weakening | 30/40 | normal | high | medium |
| Newsletter interruption copy | weakening | 8/10 | normal | low | low |
| Missing sitemap | degrading | 1/1 | normal | high | high (no prevalence bump: denominator < 5) |

## Priority

`suggested_action.priority` is set equal to the computed severity, so the fix
list and the finding list cannot disagree. Findings are ordered by severity,
then by ascending effort, then by check id — so among equally severe items,
the cheapest fix comes first, and the ordering is stable across runs.
