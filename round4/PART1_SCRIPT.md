# Part 1 — methodology · final script (≤ 3:00)

Read the **SAY** blocks aloud as written. Word count is measured, not
estimated: **419 spoken words** — 2:47 at a normal pace, 2:59 unhurried.
That leaves room for pauses and switching tabs.

Every file is inside the submitted zip. Every line number verified against the
package.

**Setup:** editor open, large font, file tree visible. Open all eight files as
tabs *before* recording so you switch instantly.

---

## ① 0:00 – 0:22 · What we looked for

**SHOW** `references/failure-modes.md`, table at **line 12** filling the screen.

> **SAY:**
> "We looked at what separates websites AI assistants cite from ones they
> ignore. Every difference we could reproduce fell into three stages.
>
> The crawler has to be let in. It has to read the page. And it has to pick out
> a fact. Fail any one, and the page doesn't exist for that system — though a
> human sees it perfectly.
>
> This file is the spine — every row ties a signal we can observe to the
> mechanism that makes it matter, and the check that finds it."

---

## ② 0:22 – 0:38 · How it's split

**SHOW** `marketplace.json` — whole file.

> **SAY:**
> "Hence eight skills, one entrypoint, mapped onto those stages. The
> orchestrator reads this manifest to decide what to run — it's not a hardcoded
> call graph."

---

## ③ 0:38 – 1:08 · The part that took longest

**SHOW** `classify.py` at **line 114**.

> **SAY:**
> "The hard part wasn't detection. It was restraint. Every check declares which
> page types it applies to. 'No Product schema' is a real finding on a product
> page and a false positive on a blog post."

**SHOW** `lib/auditlib.py` at **line 44**.

> **SAY:**
> "Same for how much evidence we have. A claim about the whole site needs three
> content pages, or it records 'inconclusive' instead of asserting. 'No
> structured data anywhere' off a one-page crawl isn't a finding — it's a
> guess."

---

## ④ 1:08 – 1:48 · How severity is decided

**SHOW** `compose_report.py` — **line 22**, then **34**, then scroll to
**line 76** and stop.

> **SAY:**
> "Severity is never hand-set. It's computed from the mechanism impact —
> blocking, degrading, or weakening.
>
> Prevalence only moves it when the denominator can carry a ratio. One out of
> one is a single fact, not a hundred percent.
>
> And this line keeps the scale meaningful: only a blocking mechanism can ever
> be critical. Anything that merely degrades caps at high, however widespread.
> Across an eight-hundred-site run, critical was two percent of findings."

---

## ⑤ 1:48 – 2:18 · Where the fixes come from

**SHOW** `skills/site-acquisition/scripts/analyze.py` at **line 183**, scroll
slowly to **line 213**.

> **SAY:**
> "This is the check you'll see fire in the live run. Look at what a finding
> carries. A mechanism — why this breaks retrieval, not just what's missing.
> The evidence. The steps to change. And a verification line, so you can
> confirm the fix worked.
>
> Ordering is severity first, then ascending effort — so among equally serious
> findings, the cheapest fix comes first."

---

## ⑥ 2:18 – 2:45 · Why we trust it

**SHOW** the `tests/` folder, then open `tests/corpus-d2c.txt` and scroll.

> **SAY:**
> "Three suites ship with it. Fixtures assert both directions of every check —
> fire on the broken site, stay silent on the clean one. A compliance gate
> proves recommend-only from source: it walks the syntax tree of every script
> and fails on any write request.
>
> And a live suite audits roughly eight hundred real websites, reporting a
> firing rate per check — because a check that fires on everything is worse
> than useless. That's how we found seven classes of false positive our
> fixtures had all passed."

---

# Tab order — open these before recording

| # | File | Line |
|---|---|---|
| 1 | `references/failure-modes.md` | 12 |
| 2 | `marketplace.json` | — |
| 3 | `skills/site-acquisition/scripts/classify.py` | 114 |
| 4 | `lib/auditlib.py` | 44 |
| 5 | `skills/audit-orchestrator/scripts/compose_report.py` | 22 → 34 → **76** |
| 6 | `skills/site-acquisition/scripts/analyze.py` | 183 → 213 |
| 7 | `tests/` folder | — |
| 8 | `tests/corpus-d2c.txt` | scroll |

# If you still run long

Cut in this order — each is self-contained:

1. The second paragraph of ③ (`auditlib.py`, line 44)
2. The last paragraph of ⑥ (the live suite)
3. Section ② entirely — the manifest is visible in Part 2 anyway

# Three things not to say

- **Don't** claim the audit found razorpay blocking AI assistants. Only
  ByteSpider is blocked; ClaudeBot and ChatGPT are explicitly allowed. Part 2
  handles that honestly — don't set up a claim Part 2 has to walk back.
- **Don't** cite any file, threshold or number that isn't in the zip. Every
  figure here is in a file a judge can open.
- **Don't** say "eight hundred sites" while showing anything other than
  `tests/corpus-d2c.txt`.
