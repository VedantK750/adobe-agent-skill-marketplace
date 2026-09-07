# Failure modes: signal, mechanism, check

The shared spine of the marketplace. Each row ties an observable signal to
the mechanism that makes it matter and the check that detects it.

Every entry is written against a mechanism, never against a string or layout
observed on a particular site. That is what makes the checks generalise to
sites nobody involved has seen.

## Off-site discoverability

| Signal | Mechanism | Check | Base |
|---|---|---|---|
| Origin returns no HTTP response at all | Retrieval starts with a successful fetch; nothing downstream can be observed, so every other symptom would be a misdiagnosis | ACC-NO-RESPONSE | blocking |
| robots.txt excludes AI user agents | Assistant fetchers identify as these agents; excluded means never retrievable | ACC-AI-CRAWLER-BLOCKED | blocking |
| Wildcard root disallow | Removes every page from systems honouring robots.txt | ACC-BLANKET-DISALLOW | blocking |
| noindex / nosnippet / max-snippet:0 | Permits indexing, forbids quotation; the page can rank and never be citable | ACC-SNIPPET-SUPPRESSED | blocking |
| No sitemap | Discovery depends on link depth; deep and new pages are missed | ACC-NO-SITEMAP | degrading |
| Text present only after JS | Non-executing fetchers receive an empty document | MR-RENDER-GAP, MR-EMPTY-SHELL | blocking |
| Facts rendered as images | No textual representation exists to extract | MR-FACTS-IN-IMAGES, MR-ALT-COVERAGE | degrading |
| No main landmark | Body copy indistinguishable from boilerplate; chunks diluted | MR-NO-MAIN-LANDMARK | weakening |
| Substance inside a content-bearing iframe | Iframe content belongs to another document and is generally not followed. Tag managers, chat, consent and payment frames are excluded — they hold nothing | MR-IFRAME-CONTENT | degrading |
| No structured data | Attributes must be inferred from prose; uncertain inferences are dropped | SD-ABSENT, SD-COVERAGE-* | degrading |
| Invalid JSON-LD | Discarded wholesale while appearing correct in source review | SD-INVALID-JSON | degrading |
| Markup contradicts visible text | Undermines trust in the markup; risks quoting a price the visitor never sees | SD-TEXT-CONFLICT | degrading |
| Passages depend on prior context | Retrieval returns fragments; a dangling pronoun is unquotable | AE-CHUNK-DEPENDENCE | degrading |
| Question heading, no direct answer | The chunk carrying the query match carries no answer | AE-QUESTION-NOT-ANSWERED | degrading |
| Entity named once, in the title | Mid-page chunks cannot be attributed to the brand | AE-ENTITY-NOT-RESTATED | weakening |
| No definitional sentence | "What is X" has no quotable answer | AE-NO-DEFINITION | degrading |
| No heading anchors | Citations point at pages, not answering sections | AE-NO-HEADING-ANCHORS | weakening |
| Claims on one domain only | Single-source claims are treated as fragile | EC-SINGLE-SOURCE-CLAIMS | degrading |
| Shared name, no disambiguation | Same-named entities are conflated | EC-NAME-COLLISION | degrading |
| No sameAs / external profiles | External evidence cannot be tied back to this entity | EC-FEW-EXTERNAL-PROFILES, SD-NO-SAMEAS | weakening |
| Undated content | Recency unassessable; passed over for current answers | FP-NO-DATES, FP-UNDATED-TIME-SENSITIVE | weakening |
| Uniform sitemap lastmod | Signal known unreliable stops being used at all | FP-LASTMOD-UNIFORM | weakening |

## On-site engagement

Modelled visitor: referred by an assistant, lands deep rather than on the
home page, holds one specific question, has no relationship to the brand and
no patience.

| Signal | Mechanism | Check | Base |
|---|---|---|---|
| No mobile viewport | Referrals skew mobile; desktop-width render bounces before reading | EN-NO-VIEWPORT | degrading |
| Heavy payload / slow response | Each second converts traffic into bounces; also caps crawl depth | EN-HEAVY-PAGES, EN-SLOW-RESPONSE | degrading |
| Fewer than three onward links | Session ends after one answer | EN-DEAD-END-PAGES | degrading |
| No navigation landmark | Deep arrival cannot orient or judge the rest of the site | EN-NO-ORIENTATION | weakening |
| No stated next action | Peak intent expires unconverted | EN-NO-CTA | degrading |
| Autoplay media **with sound** | Reliable immediate-bounce trigger, especially on mobile. Muted autoplay is excluded: it is the standard hero pattern and carries no unrequested sound | EN-AUTOPLAY-MEDIA | degrading |
| Arrival-time subscription prompts | Asks before delivering value to a first-time visitor | EN-INTERRUPTIONS | weakening |
| Consent copy dominates the page | Visitors and extractors both receive the notice, not the content | EN-CONSENT-BLOCKS-CONTENT | degrading |
| No on-site search on a large site | No recovery path from a near-miss landing | EN-NO-SITE-SEARCH | weakening |

## Email (background item F)

Not detectable by crawling a website, so it is carried as proactive
recommendation P-010 rather than as a check: inbox summarisers build from
message text, so substance carried by images or buried beneath filler is
dropped from the summary the recipient reads.

## Writing a check that survives contact with real sites

Every entry above is written against a mechanism. The failure mode that keeps
recurring in practice is subtler: a check whose *implementation* drifts away
from the mechanism its own text claims, and then fires on a pattern that
cannot cause the harm described. Four rules, each learned from a false
positive measured across a live corpus.

**Match the signal the mechanism names, not a proxy for it.** "Unrequested
sound on arrival" means unmuted media. Matching `autoplay` alone flagged the
standard muted hero video — which cannot make a sound, and is muted precisely
because browsers refuse to autoplay anything else. Every firing contradicted
the stated mechanism.

**Search the text a consumer actually sees.** Checks that read chrome-stripped
body text miss anything in a header or a form. A storefront's "Add to cart"
lives inside a `<form>`, so a CTA check reading stripped text reported "no call
to action" on half of all commerce sites.

**Exclude infrastructure before measuring content.** Most iframes on a modern
page are a tag manager, a chat launcher, a consent manager or a payment field,
and none holds substance. Counting them turned a trapped-content check into a
detector for "uses analytics".

**Distinguish absent evidence from negative evidence.** "No definitional
sentence" on a page that yielded twelve words of text is not a finding about
the page's content; it restates a readability failure another check already
owns. Where the evidence is missing, record `inconclusive` and name the check
that owns the real defect.

## Adding a check

1. State the mechanism first. If you cannot explain why it changes what a
   machine can find, read or quote, it is not a check.
2. Choose the page types it applies to and gate it. Ungated checks are how
   false positives get in.
3. Set an impact class, not a severity — the orchestrator computes severity.
4. Decide whether the claim generalises from a page sample. If it does, do
   nothing: the small-sample gate in `lib/auditlib.py` applies by default and
   will hold the check silent until the crawl can support it. If it does not —
   the check reads the origin, or names a defect it directly observed on a
   specific page — add the id to `SMALL_SAMPLE_EXEMPT` with the reason. Getting
   this backwards is how both a false positive and a miss get in, so state
   which of the two kinds it is before writing the check.
5. Write the `not_applicable` reason. A check that cannot explain its own
   silence is not finished.
6. Run `tests/live_suite.py`. A new check that fires on nearly every site in
   the corpus, or on none of it, is not ready — the firing-rate table will say
   which.
