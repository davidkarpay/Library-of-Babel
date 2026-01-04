# DiffThinker: Diffusion‑Based Generative Multimodal Reasoning

**Authors:** Zefeng He, 

**Source:** [HuggingFace](https://huggingface.co/papers/2512.24165) | [arXiv](https://arxiv.org/abs/2512.24165)

**Published:** 2026-01-03

**Organization:** Hugging Face

## Summary

- Reformulates multimodal reasoning as a native image‑to‑image generation task, enabling direct manipulation of visual information instead of indirect text prompts.
- Demonstrates four intrinsic advantages—efficiency, controllability, native parallelism, and seamless collaboration between vision and language modules—leading to more logically consistent and spatially precise outputs.
- Achieves massive performance gains on long‑horizon, vision‑centric tasks (sequential planning, combinatorial optimization, CSP, spatial configuration), surpassing state‑of‑the‑art closed‑source models (e.g., GPT‑5 + 314.2%, Gemini‑3‑Flash + 111.6%).
- Shows that diffusion models can be fine‑tuned or prompted to act as “reasoning engines,” offering a scalable alternative to large language‑only reasoning pipelines.

## Abstract

While recent Multimodal Large Language Models (MLLMs) have attained significant strides in multimodal reasoning, their reasoning processes remain predominantly text-centric, leading to suboptimal performance in complex long-horizon, vision-centric tasks. In this paper, we establish a novel Generative Multimodal Reasoning paradigm and introduce DiffThinker, a diffusion-based reasoning framework. Conceptually, DiffThinker reformulates multimodal reasoning as a native generative image-to-image task, achieving superior logical consistency and spatial precision in vision-centric tasks. We perform a systematic comparison between DiffThinker and MLLMs, providing the first in-depth investigation into the intrinsic characteristics of this paradigm, revealing four core properties: efficiency, controllability, native parallelism, and collaboration. Extensive experiments across four domains (sequential planning, combinatorial optimization, constraint satisfaction, and spatial configuration) demonstrate that DiffThinker significantly outperforms leading closed source models including GPT-5 (+314.2\%) and Gemini-3-Flash (+111.6\%), as well as the fine-tuned Qwen3-VL-32B baseline (+39.0\%), highlighting generative multimodal reasoning as a promising approach for vision-centric reasoning.

---

*Topics: multimodal, computer-vision, efficiency*
*Difficulty: advanced*
*Upvotes: 22*