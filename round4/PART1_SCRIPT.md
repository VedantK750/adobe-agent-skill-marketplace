# Part 1 — methodology · speaking script (≤ 3:00)

Written to be **said out loud**, not read off a page. Contractions, short
sentences, the odd aside — say it the way you'd explain it to another
developer looking over your shoulder.

If you fluff a line, keep going. A small stumble sounds more real than a
perfect read.

**424 spoken words — about 2:49 at a normal pace.** That is inside the cap but
not by much. If you speak slowly or pause a lot between tabs, drop the first
item on the cut list before you start rather than rushing at the end.

**Setup:** editor, big font, file tree visible. Open all eight tabs *before*
recording so you're switching, not hunting.

---

## ① 0:00 – 0:25 · Where the checks came from

**SHOW** `references/failure-modes.md`, table at **line 12** filling the screen.

> **SAY:**
> "We started by looking at a lot of websites. Which ones do AI assistants
> quote, and which ones do they skip?
>
> Almost everything came down to three things. Can the crawler get in. Can it
> read the page. Can it find the fact someone asked about. Break any one and
> the page may as well not exist, even though you and I can see it fine.
>
> So this file is the backbone. Every row is a signal we can measure, what it
> breaks, and the check that catches it."

---

## ② 0:25 – 0:40 · Why eight skills

**SHOW** `marketplace.json` — whole file.

> **SAY:**
> "That's why it's eight skills, not one big one — they line up with those
> stages. And the orchestrator works out what to run by reading this file."

---

## ③ 0:40 – 1:10 · The bit we got wrong first

**SHOW** `classify.py` at **line 114**.

> **SAY:**
> "Honestly, the hard part wasn't finding problems. It was not crying wolf.
>
> Early on we'd flag 'no Product schema' on a blog post, which is nonsense. So
> now every check declares which page types it applies to, and we classify each
> page before anything runs."

**SHOW** `lib/auditlib.py` at **line 44**.

> **SAY:**
> "Same for how much we've seen. If we only got one page, we're not going to
> tell you the whole site has no structured data. We don't know that. So a
> claim about the site needs three pages, or it comes back inconclusive."

---

## ④ 1:10 – 1:50 · How we decide what's serious

**SHOW** `compose_report.py` — **line 22**, then **34**, then scroll to
**line 76** and stop there.

> **SAY:**
> "Nothing here has a severity typed in by hand. It comes from what the
> problem does — block retrieval, degrade it, or just weaken a signal.
>
> And prevalence only moves it when there's enough to divide by. One out of one
> isn't a hundred percent. It's one page.
>
> This line's the important one. Only something that genuinely blocks retrieval
> can be critical. Everything else tops out at high, however many pages it's
> on. Across about eight hundred sites, critical came out at two percent."

---

## ⑤ 1:50 – 2:20 · Where the fixes come from

**SHOW** `skills/machine-readability/scripts/analyze.py` at **line 181**,
scroll slowly to **line 202**.

> **SAY:**
> "This is the check that fires in the demo you're about to see. Look at what
> it carries. A mechanism — why this breaks things, not just that something's
> missing. The evidence. The steps to fix it. And how to confirm it worked.
>
> We sort by severity, then effort. So if two things are equally bad, the cheap
> one comes first."

---

## ⑥ 2:20 – 2:45 · How we know it isn't nonsense

**SHOW** the `tests/` folder, then open `tests/corpus-d2c.txt` and scroll it.

> **SAY:**
> "Three test suites ship with it. The fixtures check both directions — fire on
> the broken site, stay quiet on the clean one.
>
> And this one runs the audit across about eight hundred real websites and
> tells us how often each check fires. Because a check that goes off everywhere
> isn't telling you anything. It's how we caught seven false positives our own
> tests were happily passing."

---

# Tabs to open before you record

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

# Covers the three things Part 1 is scored on

- **Signal discovery** → ① `failure-modes.md`, and ③ `classify.py` +
  `auditlib.py`
- **Severity logic** → ④ `compose_report.py` lines 22, 34, 76
- **Fix derivation and prioritisation** → ⑤ `analyze.py` 181–202

Every file is in the submitted zip. Every line number checked against it.

# If you overrun

Cut in this order — each stands alone:

1. The `auditlib.py` paragraph in ③
2. The last paragraph of ⑥ (the eight-hundred-site suite)
3. Section ② — the manifest shows up in Part 2 anyway

# Don't say

- Don't say the site is invisible to all AI. The empty-shell finding means a
  fetcher that doesn't run JavaScript sees no text. Some assistants do render.
  Say what the evidence says and nothing more.
- Don't cite a number or a file that isn't in the zip.
- Don't say "eight hundred sites" unless `tests/corpus-d2c.txt` is on screen.
