# Part 1 — methodology · speaking script (≤ 3:00)

Plain and direct, the way you would explain the project to a panel. Read the
**SAY** blocks as written.

**413 spoken words — about 2:45 at a normal pace, 2:57 unhurried.** If you
speak slowly, drop the first cut-list item before you start rather than
rushing the last section.

**Setup:** editor, large font, file tree visible. Open all eight tabs before
recording so you are switching, not searching.

---

## ① 0:00 – 0:25 · Where the checks came from

**SHOW** `references/failure-modes.md`, table at **line 12** filling the screen.

> **SAY:**
> "We looked at a large number of websites to see which ones AI assistants
> quote and which ones they ignore.
>
> The differences fell into three stages. First, whether the crawler is allowed
> in. Second, whether it can read the page. Third, whether it can find the
> specific fact someone asked for. If any stage fails, the page is effectively
> invisible to that system, even though a person can read it normally.
>
> This file records all of that. Each row is a signal we can measure, the
> mechanism it affects, and the check that detects it."

---

## ② 0:25 – 0:40 · Why eight skills

**SHOW** `marketplace.json` — whole file.

> **SAY:**
> "That is why the marketplace has eight skills rather than one. Each skill
> covers one concern. The orchestrator reads this manifest to decide which
> skills to run."

---

## ③ 0:40 – 1:10 · Avoiding false positives

**SHOW** `classify.py` at **line 114**.

> **SAY:**
> "Our main difficulty was avoiding false positives. Reporting missing Product
> schema on a blog post would be incorrect. So every check declares which page
> types it applies to, and we classify each page before any check runs."

**SHOW** `lib/auditlib.py` at **line 44**.

> **SAY:**
> "We apply the same rule to sample size. If we have only one page, we cannot
> say the whole site has no structured data. Any claim about the whole site
> needs at least three pages. Below that, the check reports inconclusive."

---

## ④ 1:10 – 1:50 · How severity is decided

**SHOW** `compose_report.py` — **line 22**, then **34**, then scroll to
**line 76** and stop there.

> **SAY:**
> "No severity is set manually. It is derived from what the problem does:
> whether it blocks retrieval, degrades it, or weakens a signal.
>
> Prevalence only affects severity when the sample is large enough to support
> a ratio. One out of one is not a hundred percent.
>
> This line is the key rule. Only a problem that blocks retrieval can be
> critical. Everything else is capped at high. Across about eight hundred
> sites, critical findings were two percent of the total."

---

## ⑤ 1:50 – 2:20 · How the fixes were derived

**SHOW** `skills/machine-readability/scripts/analyze.py` at **line 181**,
scroll slowly to **line 202**.

> **SAY:**
> "This is the check that fires in the demonstration. Each finding carries four
> things: the mechanism, explaining why it breaks retrieval rather than just
> what is missing; the evidence we observed; the steps to fix it; and how to
> verify the fix worked.
>
> Findings are sorted by severity, then by effort. Among equally severe
> findings, the least expensive fix comes first."

---

## ⑥ 2:20 – 2:45 · How we tested it

**SHOW** the `tests/` folder, then open `tests/corpus-d2c.txt` and scroll it.

> **SAY:**
> "Three test suites are included. The fixture tests check both directions:
> each check must fire on a deliberately broken site and stay silent on a clean
> one.
>
> The second runs the audit across about eight hundred real websites and
> reports how often each check fires. A check that fires on every site is not
> useful. This is how we identified and corrected seven false positives."

---

# Tabs to open before recording

| # | File | Line |
|---|---|---|
| 1 | `references/failure-modes.md` | 12 |
| 2 | `marketplace.json` | — |
| 3 | `skills/site-acquisition/scripts/classify.py` | 114 |
| 4 | `lib/auditlib.py` | 44 |
| 5 | `skills/audit-orchestrator/scripts/compose_report.py` | 22 → 34 → **76** |
| 6 | `skills/machine-readability/scripts/analyze.py` | 181 → 202 |
| 7 | `tests/` folder | — |
| 8 | `tests/corpus-d2c.txt` | scroll |

# What Part 1 is scored on, and where it is covered

- **Signal discovery** → ① `failure-modes.md`, ③ `classify.py` + `auditlib.py`
- **Severity logic** → ④ `compose_report.py` lines 22, 34, 76
- **Fix derivation and prioritisation** → ⑤ `analyze.py` 181–202

Every file is in the submitted zip. Every line number checked against it.

# If you run long

Cut in this order — each stands alone:

1. The `auditlib.py` paragraph in ③
2. The last paragraph of ⑥
3. Section ② — the manifest appears in Part 2 anyway

# Do not say

- Do not say the site is invisible to all AI. The empty-shell finding means a
  fetcher that does not run JavaScript sees no text. Some assistants do render.
- Do not cite a number or file that is not in the zip.
- Do not say "eight hundred sites" unless `tests/corpus-d2c.txt` is on screen.
