# Hypergraph‑Based Memory for Enhanced Multi‑Step RAG

**Authors:** Chulun Zhou, 

**Source:** [HuggingFace](https://huggingface.co/papers/2512.23959) | [arXiv](https://arxiv.org/abs/2512.23959)

**Published:** 2026-01-03

**Organization:** Hugging Face

## Summary

- Conventional RAG memories act as static fact repositories, neglecting the higher‑order relations needed for deep reasoning.
- HGMem models the working memory as a hypergraph where each hyperedge groups related facts, enabling progressive construction of complex relational structures.
- The dynamic hypergraph evolves with each retrieval‑reasoning cycle, producing richer, context‑aware propositions that guide subsequent queries.
- Across several long‑context “global sense‑making” benchmarks, HGMem consistently outperforms strong baselines, reducing reasoning fragmentation and improving answer accuracy.
- The hypergraph module can be integrated into existing multi‑step RAG pipelines with modest computational overhead, acting as a plug‑and‑play upgrade.

## Abstract

Multi-step retrieval-augmented generation (RAG) has become a widely adopted strategy for enhancing large language models (LLMs) on tasks that demand global comprehension and intensive reasoning. Many RAG systems incorporate a working memory module to consolidate retrieved information. However, existing memory designs function primarily as passive storage that accumulates isolated facts for the purpose of condensing the lengthy inputs and generating new sub-queries through deduction. This static nature overlooks the crucial high-order correlations among primitive facts, the compositions of which can often provide stronger guidance for subsequent steps. Therefore, their representational strength and impact on multi-step reasoning and knowledge evolution are limited, resulting in fragmented reasoning and weak global sense-making capacity in extended contexts. We introduce HGMem, a hypergraph-based memory mechanism that extends the concept of memory beyond simple storage into a dynamic, expressive structure for complex reasoning and global understanding. In our approach, memory is represented as a hypergraph whose hyperedges correspond to distinct memory units, enabling the progressive formation of higher-order interactions within memory. This mechanism connects facts and thoughts around the focal problem, evolving into an integrated and situated knowledge structure that provides strong propositions for deeper reasoning in subsequent steps. We evaluate HGMem on several challenging datasets designed for global sense-making. Extensive experiments and in-depth analyses show that our method consistently improves multi-step RAG and substantially outperforms strong baseline systems across diverse tasks.

---

*Topics: nlp, efficiency*
*Difficulty: advanced*
*Upvotes: 73*