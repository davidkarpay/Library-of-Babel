#!/usr/bin/env python3
"""
prompt_builder.py

Generate powerful prompts from selected library content.
Combines transcript excerpts with AI synthesis to create targeted prompts.

Usage:
    from prompt_builder import PromptBuilder

    builder = PromptBuilder()

    # Build a task prompt
    prompt = builder.build_prompt(
        goal="Implement secure Kubernetes deployment",
        prompt_type="task",
        video_slugs=["kubernetes-security-best-practices", "zero-trust-containers"]
    )

    # Build a learning prompt
    prompt = builder.build_prompt(
        goal="Understand container security fundamentals",
        prompt_type="learning",
        video_slugs=["container-security-intro"]
    )

Environment Variables:
    OLLAMA_URL - Ollama server URL
    OLLAMA_MODEL - Model to use
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from llm_client import LLMClient


# === Configuration ===
BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"


# === Prompt Templates ===

LEARNING_TEMPLATE = """You are creating a comprehensive learning guide.

Goal: {goal}

Source Materials:
{content}

Create a learning prompt that:
1. Introduces the key concepts progressively
2. Highlights important definitions and terms
3. Includes practical examples from the source material
4. Suggests exercises or reflection questions
5. References specific sections for deeper study

Format the prompt to be used with an AI assistant for self-directed learning."""

TASK_TEMPLATE = """You are creating an implementation-focused prompt.

Goal: {goal}

Source Materials:
{content}

Create a task prompt that:
1. Clearly defines the objective and success criteria
2. Lists prerequisites and dependencies
3. Provides step-by-step implementation guidance from the sources
4. Includes code patterns or examples mentioned in the materials
5. Addresses potential pitfalls and best practices

Format the prompt to guide an AI assistant in completing the task."""

RESEARCH_TEMPLATE = """You are creating a research exploration prompt.

Goal: {goal}

Source Materials:
{content}

Create a research prompt that:
1. Frames the key questions to investigate
2. Summarizes existing knowledge from the sources
3. Identifies gaps or areas needing deeper exploration
4. Suggests related topics and connections
5. Provides a structured approach to the research

Format the prompt to guide an AI assistant in comprehensive research."""


class PromptBuilder:
    """Build prompts from library content."""

    def __init__(self, llm: LLMClient = None):
        """Initialize the prompt builder."""
        self.llm = llm or LLMClient()
        self.templates = {
            "learning": LEARNING_TEMPLATE,
            "task": TASK_TEMPLATE,
            "research": RESEARCH_TEMPLATE
        }

    def load_transcript(self, slug: str) -> Optional[str]:
        """Load a transcript by slug."""
        path = TRANSCRIPTS_DIR / f"{slug}.md"
        if path.exists():
            return path.read_text()
        return None

    def load_metadata(self, slug: str) -> Optional[dict]:
        """Load metadata by slug."""
        path = METADATA_DIR / f"{slug}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def extract_section(self, transcript: str, start: int, end: int) -> str:
        """
        Extract content between timestamps.

        Looks for timestamp markers like [00:05:30] in the transcript.
        """
        lines = transcript.split('\n')
        result_lines = []
        in_section = False

        for line in lines:
            # Look for timestamp markers
            ts_match = re.search(r'\[(\d{2}):(\d{2}):(\d{2})\]', line)
            if ts_match:
                h, m, s = int(ts_match.group(1)), int(ts_match.group(2)), int(ts_match.group(3))
                timestamp = h * 3600 + m * 60 + s

                if timestamp >= start and timestamp < end:
                    in_section = True
                elif timestamp >= end:
                    in_section = False

            if in_section:
                result_lines.append(line)

        return '\n'.join(result_lines)

    def format_content(self, slug: str, sections: list = None, max_chars: int = 15000) -> str:
        """
        Format video content for prompt inclusion.

        Args:
            slug: Video slug
            sections: Optional list of {"start": int, "end": int} to extract
            max_chars: Maximum characters to include

        Returns:
            Formatted content string
        """
        meta = self.load_metadata(slug)
        transcript = self.load_transcript(slug)

        if not meta or not transcript:
            return f"[Video not found: {slug}]"

        title = meta.get("title", slug)
        summary = meta.get("summary", [])

        content_parts = [f"### {title}"]

        if summary:
            content_parts.append("\nKey Points:")
            for point in summary[:5]:
                content_parts.append(f"- {point}")

        if sections:
            content_parts.append("\nRelevant Sections:")
            for sec in sections:
                excerpt = self.extract_section(
                    transcript,
                    sec.get("start", 0),
                    sec.get("end", 180)
                )
                if excerpt:
                    content_parts.append(excerpt[:3000])
        else:
            # Include beginning of transcript
            clean_transcript = self._clean_transcript(transcript)
            content_parts.append("\nTranscript Excerpt:")
            content_parts.append(clean_transcript[:max_chars // 2])

        result = '\n'.join(content_parts)
        return result[:max_chars]

    def _clean_transcript(self, transcript: str) -> str:
        """Clean markdown formatting from transcript."""
        text = transcript
        # Remove markdown headers
        text = re.sub(r'^#+\s+.*$', '', text, flags=re.MULTILINE)
        # Remove links
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Collapse whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def build_prompt(
        self,
        goal: str,
        prompt_type: str = "task",
        video_slugs: list = None,
        sections_map: dict = None,
        max_context: int = 30000
    ) -> dict:
        """
        Build a prompt from selected library content.

        Args:
            goal: What the user wants to achieve
            prompt_type: "learning", "task", or "research"
            video_slugs: List of video slugs to include
            sections_map: Optional dict mapping slug -> list of {"start": int, "end": int}
            max_context: Maximum context characters

        Returns:
            {
                "prompt": "Generated prompt text",
                "sources": [list of video slugs used],
                "context_chars": int
            }
        """
        if prompt_type not in self.templates:
            prompt_type = "task"

        video_slugs = video_slugs or []
        sections_map = sections_map or {}

        # Gather content from each video
        content_parts = []
        chars_per_video = max_context // max(len(video_slugs), 1)

        for slug in video_slugs:
            sections = sections_map.get(slug)
            content = self.format_content(slug, sections, chars_per_video)
            content_parts.append(content)

        combined_content = "\n\n---\n\n".join(content_parts)

        # Get the appropriate template
        template = self.templates[prompt_type]

        # Generate the prompt using LLM
        synthesis_prompt = template.format(goal=goal, content=combined_content)

        generated_prompt = self.llm.generate(
            synthesis_prompt,
            system="You are an expert prompt engineer. Create clear, actionable prompts.",
            timeout=120
        )

        # Fallback if LLM fails
        if not generated_prompt:
            generated_prompt = f"""Goal: {goal}

Based on the following source materials, help me {goal.lower()}.

{combined_content}

Please provide detailed guidance based on these expert sources."""

        return {
            "prompt": generated_prompt,
            "sources": video_slugs,
            "context_chars": len(combined_content),
            "prompt_type": prompt_type
        }

    def quick_prompt(self, goal: str, search_query: str = None, limit: int = 3) -> dict:
        """
        Build a prompt by auto-searching for relevant videos.

        Args:
            goal: What the user wants to achieve
            search_query: Optional search query (defaults to goal)
            limit: Number of videos to include

        Returns:
            Same as build_prompt()
        """
        import requests

        query = search_query or goal
        server = os.environ.get("LIBRARY_SERVER", "http://localhost:5001")

        try:
            # Search for relevant videos
            response = requests.get(
                f"{server}/api/search",
                params={"q": query, "limit": limit},
                timeout=10
            )
            response.raise_for_status()
            results = response.json().get("results", [])

            if not results:
                return {
                    "prompt": f"No relevant videos found for: {goal}",
                    "sources": [],
                    "context_chars": 0,
                    "prompt_type": "task"
                }

            # Extract slugs
            slugs = [r.get("slug") for r in results if r.get("slug")]

            # Determine prompt type from goal keywords
            prompt_type = "task"
            goal_lower = goal.lower()
            if any(word in goal_lower for word in ["learn", "understand", "explain", "what is"]):
                prompt_type = "learning"
            elif any(word in goal_lower for word in ["research", "explore", "compare", "analyze"]):
                prompt_type = "research"

            return self.build_prompt(goal, prompt_type, slugs)

        except Exception as e:
            return {
                "prompt": f"Error building prompt: {e}",
                "sources": [],
                "context_chars": 0,
                "prompt_type": "task"
            }


# === CLI Interface ===

def main():
    """Interactive prompt builder CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="Build prompts from library content")
    parser.add_argument("goal", nargs="?", help="Goal for the prompt")
    parser.add_argument("--type", choices=["learning", "task", "research"], default="task",
                        help="Type of prompt to generate")
    parser.add_argument("--videos", nargs="+", help="Video slugs to include")
    parser.add_argument("--search", help="Search query for auto-selecting videos")
    parser.add_argument("--limit", type=int, default=3, help="Number of videos for auto-search")

    args = parser.parse_args()

    builder = PromptBuilder()

    if not args.goal:
        # Interactive mode
        print("Prompt Builder - Interactive Mode")
        print("=" * 40)
        print()

        goal = input("What's your goal? ").strip()
        if not goal:
            print("No goal provided. Exiting.")
            return

        print("\nPrompt type:")
        print("  1. Learning (understand concepts)")
        print("  2. Task (implement something)")
        print("  3. Research (explore a topic)")
        choice = input("Select [1-3, default 2]: ").strip() or "2"

        type_map = {"1": "learning", "2": "task", "3": "research"}
        prompt_type = type_map.get(choice, "task")

        print(f"\nSearching for relevant videos...")
        result = builder.quick_prompt(goal, limit=3)

    elif args.videos:
        # Use specified videos
        result = builder.build_prompt(args.goal, args.type, args.videos)

    elif args.search:
        # Search-based
        result = builder.quick_prompt(args.goal, args.search, args.limit)

    else:
        # Auto-search based on goal
        result = builder.quick_prompt(args.goal, limit=args.limit)

    # Display result
    print("\n" + "=" * 60)
    print("GENERATED PROMPT")
    print("=" * 60)
    print()
    print(result.get("prompt", ""))
    print()
    print("-" * 60)
    print(f"Type: {result.get('prompt_type', 'task')}")
    print(f"Sources: {', '.join(result.get('sources', []))}")
    print(f"Context: {result.get('context_chars', 0):,} characters")


if __name__ == "__main__":
    main()
