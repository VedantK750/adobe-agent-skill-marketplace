# Part 1 — methodology · final script (≤ 3:00)

Read the **SAY** blocks aloud as written. 440 words, which is 3:00 at a normal
pace — don't rush, the timings have slack.

Every file is inside the submitted zip. Every line number verified against the
package.

**Setup:** editor open, large font, file tree visible on the left. Have all
nine files open as tabs beforehand so you switch instantly instead of
navigating.

---

## ① 0:00 – 0:25 · What we were looking for

**SHOW** `references/failure-modes.md`, scrolled so the table at **line 12**
fills the screen.

> **SAY:**
> "We went looking for what separates websites AI assistants cite from ones
> they ignore. And every difference we could actually reproduce fell into one
> of three stages.
>
> The crawler has to be let in. It has to be able to read the page. And it has
> to be able to pick out a fact. Fail any one of those and the page doesn't
> exist for that system — even though a human sees it perfectly.
>
> This file is the spine of the whole marketplace. Every row ties a signal we
> can observe to the mechanism that makes it matter, and to the check that
> detects it."

---

## ② 0:25 – 0:45 · How it's split up

**SHOW** `marketplace.json` — whole file on screen.

> **SAY:**
> "That's why there are eight skills and exactly one entrypoint. They map onto
> those stages — site-acquisition is 'can we get in', machine-readability is
> 'can it be read', answer-extractability is 'can a fact be quoted out of it'.
>
> And the orchestrator reads this manifest to decide what to run. It isn't a
> hardcoded call graph."

---

## ③ 0:45 – 1:20 · The part we spent most time on

**SHOW** `skills/site-acquisition/scripts/classify.py` at **line 114**.

> **SAY:**
> "The hardest part wasn't detection. It was restraint.
>
> Every check declares which page types it applies to. 'No Product schema' is a
> real finding on a product page, and a false positive on a blog post. So we
> classify pages before any check runs."

**SHOW** `lib/auditlib.py` — **line 44**, then scroll to **line 51**.

> **SAY:**
> "And the same idea applies to how much evidence we have. A claim about the
> whole site needs at least three content pages, or it records 'inconclusive'
> instead of asserting — because 'no structured data anywhere' off a one-page
> crawl isn't a finding, it's a guess.
>
> Two kinds of check are exempt, and they're listed in one place with the
> reason: claims about the origin, like robots.txt, and defects we directly
> observed on a named page."

---

## ④ 1:20 – 1:55 · How severity is decided

**SHOW** `skills/audit-orchestrator/scripts/compose_report.py` — **line 22**,
then **34**, then scroll to **line 76** and stop there.

> **SAY:**
> "Severity isn't hand-set anywhere. It's computed from the mechanism impact —
> blocking, degrading, or weakening.
>
> Prevalence only moves it when the denominator can actually carry a ratio. One
> out of one is a single fact, not a hundred percent.
>
> And this line is the rule that keeps the scale meaningful. Only a blocking
> mechanism can ever be critical. Everything that merely degrades a signal caps
> at high, no matter how widespread it is. Across an eight-hundred-site run,
> critical came out at two percent of all findings.
>
> It's computed centrally, never by the skill that raised the finding —
> otherwise the scale drifts across eight different skills."

---

## ⑤ 1:55 – 2:30 · Where the fixes come from

**SHOW** `skills/site-acquisition/scripts/analyze.py` at **line 183**, then
scroll slowly down to **line 213** so the whole block passes through frame.

> **SAY:**
> "This is the check you'll see fire in the live run. Look at what a finding
> carries.
>
> A mechanism — why this breaks retrieval, not just what's missing. The
> evidence we actually observed. The steps to change. And a verification line,
> so you can confirm the fix worked.
>
> A fix that can't be traced back to a mechanism is a guess, so mechanism is a
> required field on every finding.
>
> Ordering is severity first, then ascending effort — so among equally serious
> findings, the cheapest one to fix comes first."

**SHOW** `compose_report.py` **line 150**, then **line 323**.

> **SAY:**
> "We also suggest improvements where nothing is broken — and those are chosen
> against what the site turned out to be. A payments site gets this one, about
> exposing returns and shipping and price validity as data. A documentation
> site never sees it."

---

## ⑥ 2:30 – 3:00 · Why we trust any of it

**SHOW** the `tests/` folder in the file tree, then open `tests/corpus-d2c.txt`
and scroll it so the volume of sites is visible.

> **SAY:**
> "Three test suites ship inside the package.
>
> Fixtures assert both directions of every check — it has to fire on the broken
> site and stay silent on the clean one. A compliance gate checks the package
> mechanically, including proving it's recommend-only straight from the source:
> it walks the syntax tree of every script and fails on any write request.
>
> And a live suite runs the audit across roughly eight hundred real websites and
> reports a firing rate for each check. Because a check that fires on everything
> is worse than useless.
>
> That's how we found and fixed seven separate classes of false positive — every
> one of which our fixtures had happily passed."

---

# Screen-capture order

Open these as tabs before recording, in this order:

| # | File | Line |
|---|---|---|
| 1 | `references/failure-modes.md` | 12 |
| 2 | `marketplace.json` | — |
| 3 | `skills/site-acquisition/scripts/classify.py` | 114 |
| 4 | `lib/auditlib.py` | 44 → 51 |
| 5 | `skills/audit-orchestrator/scripts/compose_report.py` | 22 → 34 → **76** |
| 6 | `skills/site-acquisition/scripts/analyze.py` | 183 → 213 |
| 7 | `skills/audit-orchestrator/scripts/compose_report.py` | 150 → 323 |
| 8 | `tests/` folder | — |
| 9 | `tests/corpus-d2c.txt` | scroll |

# If you run over 3:00

Cut in this order — each is self-contained:

1. The proactive-recommendations lines in ⑤ (`compose_report.py` 150/323)
2. The second half of ③ (`auditlib.py` line 51, the exempt list)
3. The last paragraph of ⑥ (keep the first two sentences)

# Three things not to say

- **Don't** claim the audit found razorpay blocking AI assistants. Only
  ByteSpider is blocked; ClaudeBot and ChatGPT are explicitly allowed. Part 2
  handles that honestly — don't set up a claim Part 2 has to walk back.
- **Don't** mention any file, threshold or number that isn't in the zip. Every
  figure in this script is in a file a judge can open.
- **Don't** say "we tested on 800 sites" while showing a file that isn't the
  corpus. Show `tests/corpus-d2c.txt` when you say it.
