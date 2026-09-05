# Marketplace Quality Index (MQI: 0–100)

> [!CAUTION]
> **FOR INTERNAL TEAM BENCHMARKING ONLY — DO NOT SUBMIT FOR HACKATHON.**
> This benchmarking suite evaluates the detection accuracy, crawl representativeness, causal mechanism soundness, and remediation quality of our audit marketplace against real websites. It is an internal development and testing tool.

---

## 1. Executive Overview

The **Marketplace Quality Index (MQI)** is an objective, 6-pillar scoring system (0–100) designed to measure how well the Brand AI-Readiness Audit performs on real-world e-commerce stores.

$$\text{MQI} = \text{Precision (25)} + \text{Causal Mechanism (20)} + \text{Crawl Entropy (15)} + \text{Severity Calibration (15)} + \text{Remediation Depth (15)} + \text{Orthogonality (10)}$$

### Quality Tiers:
- 🏆 **90–100 (Elite)**: Production-ready audit; zero false alarms, multi-type crawl entropy, all 6 remediation artifacts generated.
- ✨ **80–89 (High Quality)**: Strong audit; sound causal reasoning, diverse crawl, dynamic remediations.
- ⚠️ **65–79 (Moderate)**: Passable audit, but suffers from low entropy, shallow remediation, or missing causal mechanisms.
- ❌ **< 65 (Sub-optimal)**: Shallow crawl, ungrounded findings, or severity inflation.

---

## 2. The 6 Pillars of MQI

### Pillar 1: Grounded Precision (25 Points)
- Every finding's `affected_urls` must map directly to crawled pages in `snapshot.json`.
- Penalizes known false-positive failure modes (e.g. flagging product pages for undated prices in prose, or stale copyright when modern years exist in the DOM).

### Pillar 2: Causal Mechanism Soundness (20 Points)
- Audits must explain **why** an issue causes AI assistants (ChatGPT, Perplexity, Google AI Overviews) or human users to fail.
- Checks for core AI failure concepts: RAG chunking, vector embedding fragmentation, pronoun ambiguity, schema entity recognition, and citation anchor mechanics.

### Pillar 3: Crawl Entropy & Diversity (15 Points)
- Measures crawl diversity across 6 distinct page types (`home`, `product`, `category`, `about`, `legal`, `article`) using normalized Shannon Entropy:
  $$H = -\sum_{i} p_i \ln(p_i)$$
- Normalized: $\hat{H} = \frac{H}{\ln(6)}$. Points awarded: $\hat{H} \times 15$.
- A site crawling only product pages receives $< 4$ points. A balanced multi-type crawl receives $12–15$ points.

### Pillar 4: Severity Calibration & Anti-Inflation (15 Points)
- Guards against inflating minor cosmetic defects into "Critical" blockers.
- Only true existential blockers (`ACC-AI-CRAWLER-BLOCKED`, `ACC-BLANKET-DISALLOW`, `MR-EMPTY-SHELL`, `ACC-NO-RESPONSE`) are permitted to be `critical`.
- Deductions: -4.0 pts per non-blocker labeled Critical; -2.0 pts for minor features inflated to High.

### Pillar 5: Actionability & Remediation Depth (15 Points)
- Evaluates the production-readiness of generated remediation artifacts in `workdir/remediation/`:
  - `1_rag_passage_rewrites.md` (3 pts): Noun-anchored RAG passages without dangling pronouns.
  - `2_brand_definition_anchor.html` (3 pts): 1-sentence Knowledge Graph hero tag.
  - `3_merchant_transparency.jsonld` (3 pts): Dynamic Merchant Transparency schema (price, currency, returns, shipping).
  - `4_citation_anchor_patch.js` (2 pts): Deep-link citation anchor generator script.
  - `5_persona_constraint_matrix.html` (2 pts): Appendix E decision table.
  - `llms.txt` (2 pts): Standard LLM discovery manifest.

### Pillar 6: Root-Cause Orthogonality (10 Points)
- Measures deduplication ratio ($Unique\ Check\ IDs / Total\ Findings$).
- Prevents 1 underlying defect from spawning 5 duplicate findings across the report.

---

## 3. CLI Usage

Run directly using Python 3:

```bash
# 1. Evaluate a single audit run:
python3 benchmark/mqi.py --workdir audit-thewholetruthfoods.com

# 2. Side-by-side comparison arena (Run A vs Run B):
python3 benchmark/mqi.py --compare audit-mokobara.com audit-mokobara.com-v2

# 3. View leaderboard across all audits in repository:
python3 benchmark/mqi.py --leaderboard

# 4. Output raw JSON for programmatic analysis or CI:
python3 benchmark/mqi.py --workdir audit-mokobara.com-v2 --json
```
