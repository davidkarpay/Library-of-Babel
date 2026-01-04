# Hierarchical Language Modeling with Dynamic Concept Compression

**Authors:** Xingwei Qu, 

**Source:** [HuggingFace](https://huggingface.co/papers/2512.24617) | [arXiv](https://arxiv.org/abs/2512.24617)

**Published:** 2026-01-03

**Organization:** Hugging Face

## Summary

- DLCM learns variable‑length “concepts” on the fly, moving computation from dense token streams to a compact latent space where reasoning is cheaper and more focused.
- A new compression‑aware scaling law separates token‑level capacity, concept‑level reasoning capacity, and compression ratio, allowing principled FLOP allocation across the hierarchy.
- The decoupled μP parametrization lets hyperparameters transfer zero‑shot across model widths and compression settings, stabilizing training of heterogeneous architectures.
- In experiments (R = 4, ~4 tokens per concept) DLCM redirects about one‑third of inference FLOPs to a higher‑capacity reasoning backbone, yielding ~+2.7 % average gains on 12 zero‑shot tasks at equal compute.

## Abstract

Large Language Models (LLMs) apply uniform computation to all tokens, despite language exhibiting highly non-uniform information density. This token-uniform regime wastes capacity on locally predictable spans while under-allocating computation to semantically critical transitions. We propose Dynamic Large Concept Models (DLCM), a hierarchical language modeling framework that learns semantic boundaries from latent representations and shifts computation from tokens to a compressed concept space where reasoning is more efficient. DLCM discovers variable-length concepts end-to-end without relying on predefined linguistic units. Hierarchical compression fundamentally changes scaling behavior. We introduce the first compression-aware scaling law, which disentangles token-level capacity, concept-level reasoning capacity, and compression ratio, enabling principled compute allocation under fixed FLOPs. To stably train this heterogeneous architecture, we further develop a decoupled μP parametrization that supports zero-shot hyperparameter transfer across widths and compression regimes. At a practical setting (R=4, corresponding to an average of four tokens per concept), DLCM reallocates roughly one-third of inference compute into a higher-capacity reasoning backbone, achieving a +2.69\% average improvement across 12 zero-shot benchmarks under matched inference FLOPs.

---

*Topics: nlp, efficiency*
*Difficulty: advanced*
*Upvotes: 32*