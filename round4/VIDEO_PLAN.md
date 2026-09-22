# Round 4 video plan — TransformerBusters

Hard cap 5:00. Part 1 ≤ 3:00 (methodology), Part 2 ≤ 2:00 (live run).
Rubric: Reasoning 35 / Live behaviour 35 / Reproducibility 30.

**The one rule that outranks everything:** every claim in Part 1 must point at
a file in the submitted package. Narration that is not traceable to code earns
nothing. Every anchor below is a real line in the Round 3 submission.

---

## Part 1 — Methodology (≤ 3:00)

Screen: editor with the repo open. Open each file as you name it.

### 1. How the signals were discovered (~60s)

Frame it as the retrieval pipeline, because that is how the code is organised:
a crawler has to be **let in**, then **read the page**, then **pick out a
fact**. Fail any step and the page does not exist for that system.

> "We studied sites assistants cite well against ones they ignore, and every
> difference we could reproduce landed in one of three stages. So the
> marketplace is eight skills, one per stage of that pipeline."

**Open `references/failure-modes.md`** — the signal → mechanism → check table.
Say: each row ties an observable signal to the mechanism that makes it matter.
Nothing is written against a string seen on one site; that is what makes it
generalise.

**Open `marketplace.json`** — eight skills, exactly one entrypoint. Point out
`skills/site-acquisition` (let in), `machine-readability` (read), and
`answer-extractability` (quote a fact) as the three stages.

Strongest single point to make here — false positives:

- `skills/site-acquisition/scripts/classify.py:114` `classify_page` and `:196`
  `classify_site`. Every check declares the page types it applies to. "No
  Product schema" is a real finding on a product page and a false positive on
  a blog post.
- `lib/auditlib.py:44` `MIN_SITE_CLAIM_SAMPLE = 3` and `:51`
  `SMALL_SAMPLE_EXEMPT`. A site-wide claim needs at least three pages of
  evidence or it records `inconclusive` instead of asserting. Origin-level and
  directly-observed checks are exempt, listed in one place with the reason.

> "A check that fires on everything is worse than useless, so the gating is
> the part we spent the most time on."

### 2. How severities are assigned (~60s)

**Open `skills/audit-orchestrator/references/severity-model.md`**, then
**`skills/audit-orchestrator/scripts/compose_report.py:38`** `compute_severity`.

Three things to say, all visible on screen:

- `:22` — severity starts from the **mechanism impact**, not from a hand-set
  number: `blocking → critical`, `degrading → high`, `weakening → medium`.
- `:34` `MIN_DENOMINATOR = 5` — prevalence only shifts severity when the
  denominator can support a ratio; 1-of-1 is one fact, not 100%.
  `:35` `MAX_UPWARD_SHIFT = 1` — modifiers can raise severity by at most one
  level, and confidence only ever lowers it.
- `:76` — the rule that keeps the top of the scale meaningful:
  **only `blocking` impact can ever be `critical`.** Everything that merely
  degrades a signal caps at `high`, however widespread.

> "Severity is computed centrally, never by the skill that raised the finding
> — otherwise the scale drifts between eight skills and the report stops being
> reproducible."

Evidence it is calibrated: across a 797-site run, `critical` was 2% of all
findings and every one was a genuine pipeline blocker.

### 3. How the fixes were derived (~50s)

**Open `skills/site-acquisition/scripts/analyze.py:183`** — the finding the
live run is about to produce. Show that the finding object carries, together:

- `mechanism` (`:186`) — *why* it breaks retrieval, not just what is missing
- `evidence` — the observed fact
- `action.steps` (`:195`) — what to change
- `action.verification` (`:213`) — how to confirm the fix worked

> "A fix that cannot be traced to a mechanism is a guess, so the mechanism is a
> required field on every finding."

Prioritisation: `compose_report.py` sorts by severity, then by **ascending
effort** — so among equally severe items the cheapest fix comes first.

Beyond-the-defects advice: **`compose_report.py:106`** `proactive_context` and
**`:150`** `select_proactive`. Recommendations are chosen against what the site
turned out to be. Show **`:323`** `P-011` (commerce terms as data — returns,
shipping, price validity) and say a documentation site never receives it.

### 4. One line on rigour (~10s)

> "116 fixture assertions, 63 mechanically-checked brief requirements, and a
> live suite that runs the audit over ~800 real sites and reports a firing rate
> per check — which is how we found and fixed seven false-positive classes."

---

## Part 2 — Live run (≤ 2:00)

**Unseen site: `https://razorpay.com/`** — not in either corpus, and it has a
`critical` finding you can corroborate on camera in ten seconds.

Say the harness and model out loud early — it is a scored line:

> "This is Claude Code driving Claude Opus 5, invoking the Round 3 entrypoint
> skill. Nothing here is hardcoded — the agent reads `marketplace.json`, finds
> the entrypoint, and runs what its SKILL.md documents."

### Shot list

1. **Type the URL on camera.** Paste the prompt from
   `REPLAY_TransformerBusters.txt` step 2. Must be continuous from here —
   trimming idle wait is allowed, splicing is not.
2. **Let the agent work.** Show it reading `marketplace.json`, opening
   `skills/audit-orchestrator/SKILL.md`, and running `run_audit.py`. Let the
   per-skill progress lines scroll — that is the eight skills composing.
3. **Drill into the critical finding.** `ACC-AI-CRAWLER-BLOCKED`, evidence:
   *"robots.txt disallows all paths for: Bytespider."*
   **Then open `https://razorpay.com/robots.txt` in a browser** and point at
   the `User-agent: Bytespider` / `Disallow: /` lines. Verified live, on
   camera. This is the strongest ten seconds in the video.
4. **Show prioritisation.** Scroll the report: critical first, then high, and
   within a severity the cheapest fix first. Read out the fix steps and the
   verification line for that finding.
5. **Close on reproducibility.** Point at `./audit-run/audit-report.json` and
   say the same command is step 2 of `REPLAY_TransformerBusters.txt`, and that
   analysis is a pure function of the crawl snapshot.

### If you want a second site

`https://www.postman.com/` is the other half of the story: 9 pages that serve
~101 KB of HTML and yield **one word** of readable text — `MR-EMPTY-SHELL`,
also `critical`. "A human sees a full page; a machine that does not run
JavaScript sees nothing." Only include it if Part 2 is comfortably under 2:00.

---

## Pre-flight checklist

- [ ] `python3 round4/check_replay.py` passes (fills the harness version)
- [ ] `AGENT_HARNESS` in the manifest matches what you say on camera
- [ ] `LLM_MODEL` matches the model actually driving the session
- [ ] The URL typed on camera is in `TEST_SITE_URLS`
- [ ] Part 1 ≤ 3:00, Part 2 ≤ 2:00, total ≤ 5:00
- [ ] Engine untouched since Round 3 — do not edit any file under `skills/`,
      `lib/` or `references/` while recording
