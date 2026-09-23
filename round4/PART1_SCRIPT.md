# Part 1 script — methodology (≤ 3:00)

Every file named here is **inside the submitted zip**, so a judge can open it.
Line numbers verified against the submitted package.

Screen: editor, repo open, one file at a time. Narration ~430 words — read at a
normal pace, don't rush. Timings are cumulative.

---

## 0:00 – 0:25 · The frame

**SHOW:** `references/failure-modes.md` — scroll so the table at line 12 fills
the screen.

> "We went looking for what separates sites AI assistants cite from ones they
> ignore. Every difference we could reproduce fell into one of three stages:
> the crawler has to be **let in**, it has to be able to **read** the page, and
> it has to be able to **pick out a fact**. Fail any stage and the page doesn't
> exist for that system — even though a human sees it fine.
>
> This file is the spine of the whole marketplace. Every row ties an observable
> signal to the mechanism that makes it matter, and to the check that detects
> it. Nothing is written against a string we saw on one site — that's what
> makes it generalise."

---

## 0:25 – 0:45 · The decomposition

**SHOW:** `marketplace.json` — whole file fits on screen.

> "Eight skills, exactly one entrypoint. They map onto those stages:
> `site-acquisition` is 'let in', `machine-readability` is 'can it be read',
> `answer-extractability` is 'can a fact be quoted'. The orchestrator composes
> them — and it reads this manifest to know what to run, so it isn't a
> hardcoded call graph."

---

## 0:45 – 1:20 · The hardest part: not crying wolf

**SHOW:** `skills/site-acquisition/scripts/classify.py` — line 114
(`classify_page`), then line 196 (`classify_site`).

> "The thing we spent most effort on isn't detection, it's *restraint*. Every
> check declares the page types it applies to. 'No Product schema' is a real
> finding on a product page and a false positive on a blog post, so pages are
> classified before any check runs."

**SHOW:** `lib/auditlib.py` — line 44, then line 51.

> "Same for the *size* of the evidence. A site-wide claim needs at least three
> content pages, or it records `inconclusive` instead of asserting — because
> 'no structured data anywhere' off a one-page crawl isn't a finding, it's a
> guess. Two kinds of check are exempt, and they're listed in one place with
> the reason: claims about the origin, like robots.txt, and defects we directly
> observed on a named page."

---

## 1:20 – 1:55 · Severity

**SHOW:** `skills/audit-orchestrator/scripts/compose_report.py` — line 22, then
34–35, then **line 76** (hold on this one).

> "Severity isn't hand-set. It's computed from the *mechanism impact*:
> blocking, degrading, or weakening. Prevalence only shifts it when the
> denominator can carry a ratio — one-of-one is a single fact, not a hundred
> percent. Modifiers can raise severity by at most one level, and confidence
> only ever lowers it.
>
> This line is the rule that keeps the scale meaningful: **only `blocking`
> impact can ever be critical.** Everything that merely degrades a signal caps
> at high, however widespread. Across an eight-hundred-site run, critical came
> out at two percent of all findings.
>
> And it's computed centrally, never by the skill that raised the finding —
> otherwise the scale drifts across eight skills."

**SHOW (briefly):** `skills/audit-orchestrator/references/severity-model.md`.

---

## 1:55 – 2:30 · Fixes

**SHOW:** `skills/site-acquisition/scripts/analyze.py` — line 183, scroll
through to 213 so mechanism → evidence → steps → verification are all visible.

> "This is the finding you'll see in the live run. Notice what a finding
> carries: a **mechanism** — *why* it breaks retrieval, not just what's
> missing; the **evidence** we observed; the **steps** to change; and a
> **verification** line, so you can confirm the fix worked. A fix that can't be
> traced to a mechanism is a guess, so mechanism is a required field.
>
> Ordering is severity first, then *ascending effort* — so among equally severe
> findings, the cheapest fix comes first."

**SHOW:** `compose_report.py` line 106 and 150, then line 323.

> "Beyond the defects, we suggest improvements where nothing is broken. Those
> are selected against what the site turned out to be — a payments site gets
> the one about exposing returns, shipping and price validity as data; a
> documentation site never sees it."

---

## 2:30 – 3:00 · Why we trust it

**SHOW:** `tests/` — the file list, then `tests/corpus-d2c.txt` scrolling.

> "Three suites ship with it. Fixtures assert both directions of every check —
> it must fire on the broken site and stay silent on the clean one. A
> compliance gate checks the package mechanically, including proving
> recommend-only from source: it walks the syntax tree of every script and
> fails on any write request.
>
> And a live suite runs the audit over roughly eight hundred real sites and
> reports a **firing rate per check** — because a check that fires on
> everything is worse than useless. That's how we found and fixed seven classes
> of false positive that every fixture had passed."

---

## Screen-capture checklist

| Order | File (all inside the zip) | Show |
|---|---|---|
| 1 | `references/failure-modes.md` | the signal/mechanism/check table, line 12 |
| 2 | `marketplace.json` | whole file — 8 skills, one entrypoint |
| 3 | `skills/site-acquisition/scripts/classify.py` | lines 114 and 196 |
| 4 | `lib/auditlib.py` | lines 44 and 51 |
| 5 | `skills/audit-orchestrator/scripts/compose_report.py` | 22, 34–35, **76** |
| 6 | `skills/audit-orchestrator/references/severity-model.md` | brief |
| 7 | `skills/site-acquisition/scripts/analyze.py` | 183 → 213 |
| 8 | `skills/audit-orchestrator/scripts/compose_report.py` | 106, 150, 323 |
| 9 | `tests/` + `tests/corpus-d2c.txt` | file list, then scroll the corpus |

## Cuts if you run long

Drop in this order — each is self-contained:
1. `severity-model.md` (item 6) — the code already made the point
2. The proactive-recommendation part (item 8)
3. `classify_site` at line 196 — keep `classify_page` at 114

## Do not say

- Don't claim the audit found razorpay blocking AI assistants. Only ByteSpider
  is blocked; ClaudeBot and ChatGPT are explicitly allowed. That's Part 2's
  honest story, and Part 1 shouldn't set up a claim Part 2 corrects.
- Don't describe checks or thresholds that aren't in the zip. Every number in
  this script is in a file a judge can open.
