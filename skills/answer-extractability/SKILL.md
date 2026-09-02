---
name: answer-extractability
description: Checks whether a clear, self-contained fact can be quoted out of a single retrieved passage - question headings answered directly beneath them, passages that survive being cut from their context, entity restatement, definitional sentences, stable heading anchors, thin and duplicate pages. Use as part of a brand AI-readiness audit, after site-acquisition has produced the evidence snapshot.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Answer Extractability

## When to use
After `site-acquisition`. Reads `snapshot.json`; never touches the network.

## The mechanism
Step three of the pipeline, and the one most audits skip. Retrieval returns a
fragment of a page, not the page. A passage that only makes sense after
reading the two paragraphs above it cannot be quoted as an answer, however
well written and however crawlable. A site can pass every other check in this
marketplace and still never be cited, because nothing on it is quotable in
isolation.

## Checks
- `AE-CHUNK-DEPENDENCE` — passages opening with an unresolved pronoun.
  "It offers 24/7 support" loses its subject the moment it is separated from
  the paragraph that named the subject.
- `AE-QUESTION-NOT-ANSWERED` — question-shaped headings followed by preamble
  rather than a direct answer. A question heading plus a short answer is the
  most quotable structure on the web: the heading supplies the query match,
  the sentence supplies the citable text.
- `AE-NO-HEADING-ANCHORS` — no stable ids, so a citation can only point at
  the whole page rather than the answering section.
- `AE-ENTITY-NOT-RESTATED` — the brand is named in the title and never again,
  so a mid-page chunk cannot be attributed to it.
- `AE-NO-DEFINITION` — no plain "X is a Y that does Z" sentence on the home
  page, which is what answers the most common entry-point question.
- `AE-THIN-CONTENT`, `AE-DUPLICATE-TITLES`, `AE-NO-META-DESCRIPTION`.

## Method
Body text is split into approximate 90-word retrieval chunks and each is
judged as if it stood alone. Legal and listing pages are excluded — prose
quality is not what those pages are for.

## Avoiding false positives
Every check requires a minimum denominator: 120+ words of body text per page,
three or more sections before anchors are assessed, five or more titled pages
before duplicates are reported. Where the site is too small or too sparse to
judge, the check reports `not_applicable` or `inconclusive` rather than firing.

## Run
`python3 scripts/analyze.py --workdir DIR`

## Output
`fragments/answer-extractability.json`.
