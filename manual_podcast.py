#!/usr/bin/env python3
"""
manual_podcast.py

Manually import a podcast episode by pasting transcript text.
Useful when RSS feed doesn't include transcript or for episodes
without transcripts available.

Usage:
    python manual_podcast.py <episode_url>
    python manual_podcast.py <rss_feed_url> --episode 0

Examples:
    python manual_podcast.py "https://podcast.example.com/ep123"
    python manual_podcast.py "https://changelog.com/podcast/feed" --episode 0
"""

import argparse
import json
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime

try:
    import feedparser
except ImportError:
    feedparser = None

from llm_client import LLMClient
from library import generate_site

BASE_DIR = Path(__file__).parent
PODCASTS_DIR = BASE_DIR / "podcasts"
METADATA_DIR = BASE_DIR / "metadata"


def sanitize_filename(title: str) -> str:
    """Create a URL-safe filename from title."""
    title = title.lower()
    title = re.sub(r'[^\w\s-]', '', title)
    title = re.sub(r'[-\s]+', '-', title)
    return title.strip('-')[:100]


def generate_id(url: str) -> str:
    """Generate a unique ID from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def parse_manual_transcript(text: str, avg_duration: float = 3.0) -> list:
    """
    Parse manually pasted transcript into segment format.
    Assumes plain text, creates artificial segments.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    segments = []
    current_time = 0.0

    for sentence in sentences:
        if sentence.strip():
            segments.append({
                "text": sentence.strip(),
                "start": current_time,
                "duration": avg_duration
            })
            current_time += avg_duration

    return segments


def chunk_into_sections(segments: list, target_duration: float = 180.0) -> list:
    """Group transcript segments into larger sections."""
    if not segments:
        return []

    sections = []
    current_section = []
    current_duration = 0.0
    section_start = 0.0

    for segment in segments:
        current_section.append(segment)
        current_duration += segment.get("duration", 3.0)

        if current_duration >= target_duration:
            sections.append({
                "start": section_start,
                "end": section_start + current_duration,
                "text": " ".join(s["text"] for s in current_section)
            })
            section_start += current_duration
            current_section = []
            current_duration = 0.0

    # Add remaining
    if current_section:
        sections.append({
            "start": section_start,
            "end": section_start + current_duration,
            "text": " ".join(s["text"] for s in current_section)
        })

    return sections


def analyze_section(section_text: str, llm: LLMClient) -> dict:
    """Generate title and description for a section."""
    prompt = f"""Given this podcast transcript section, generate:
1. A concise title (3-7 words)
2. A one-sentence description

Transcript section:
{section_text[:2000]}

Format your response as:
TITLE: <title>
DESCRIPTION: <description>"""

    response = llm.generate(prompt, timeout=30)

    title = "Discussion"
    description = ""

    for line in response.split("\n"):
        if line.startswith("TITLE:"):
            title = line[6:].strip()
        elif line.startswith("DESCRIPTION:"):
            description = line[12:].strip()

    return {"title": title, "description": description}


def generate_summary(full_text: str, llm: LLMClient) -> list:
    """Generate bullet-point summary of the episode."""
    prompt = f"""Summarize the key insights from this podcast transcript in 4-6 bullet points.
Each bullet should be a complete, standalone insight (one sentence).
Focus on actionable takeaways and key learnings.

Transcript:
{full_text[:8000]}

Format: Return ONLY the bullet points, one per line, starting with -"""

    response = llm.generate(prompt, timeout=60)
    bullets = [line.strip().lstrip('- ').lstrip('• ') for line in response.split('\n') if line.strip().startswith(('-', '•'))]
    return bullets[:6] if bullets else ["Podcast episode content"]


def extract_facets(full_text: str, llm: LLMClient) -> dict:
    """Extract topic, format, and difficulty facets."""
    prompt = f"""Analyze this podcast transcript and classify it.

Transcript excerpt:
{full_text[:3000]}

Classify into:
TOPICS (pick 1-3): security, programming, ai-ml, entrepreneurship, devops, databases, web-development, career, other
FORMAT (pick 1): interview, deep-dive, news, tutorial, panel, other
DIFFICULTY (pick 1): beginner, intermediate, advanced

Format response as:
TOPICS: topic1, topic2
FORMAT: format
DIFFICULTY: difficulty"""

    response = llm.generate(prompt, timeout=30)

    facets = {
        "topics": ["other"],
        "format": "interview",
        "difficulty": "intermediate"
    }

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("TOPICS:"):
            topics = [t.strip().lower() for t in line[7:].split(",")]
            valid_topics = ["security", "programming", "ai-ml", "entrepreneurship",
                          "devops", "databases", "web-development", "career", "other"]
            facets["topics"] = [t for t in topics if t in valid_topics] or ["other"]
        elif line.startswith("FORMAT:"):
            fmt = line[7:].strip().lower()
            valid_formats = ["interview", "deep-dive", "news", "tutorial", "panel", "other"]
            facets["format"] = fmt if fmt in valid_formats else "interview"
        elif line.startswith("DIFFICULTY:"):
            diff = line[11:].strip().lower()
            valid_diffs = ["beginner", "intermediate", "advanced"]
            facets["difficulty"] = diff if diff in valid_diffs else "intermediate"

    return facets


def generate_title(full_text: str, llm: LLMClient) -> str:
    """Generate a descriptive title for the episode."""
    prompt = f"""Generate a descriptive title for this podcast episode (5-12 words).
The title should capture the main topic or theme discussed.

Transcript excerpt:
{full_text[:1500]}

Return ONLY the title, nothing else."""

    response = llm.generate(prompt, timeout=30)
    return response.strip().strip('"')[:150] or "Podcast Episode"


def get_episode_from_rss(feed_url: str, episode_index: int = 0) -> dict:
    """Get episode info from RSS feed."""
    if not feedparser:
        print("Error: feedparser required. Install with: pip install feedparser")
        sys.exit(1)

    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        print(f"Error: Could not parse RSS feed: {feed.bozo_exception}")
        sys.exit(1)

    if not feed.entries:
        print("No episodes found in feed")
        sys.exit(1)

    if episode_index >= len(feed.entries):
        print(f"Episode index {episode_index} out of range (feed has {len(feed.entries)} episodes)")
        sys.exit(1)

    entry = feed.entries[episode_index]

    # Extract episode info
    episode = {
        "title": entry.get("title", "Unknown Episode"),
        "url": entry.get("link", ""),
        "published": entry.get("published", ""),
        "show": {
            "name": feed.feed.get("title", "Unknown Show"),
            "url": feed.feed.get("link", ""),
            "feed_url": feed_url
        }
    }

    # Parse audio URL
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("audio/"):
            episode["audio_url"] = enc.get("href", "")
            break

    # Parse published date
    if entry.get("published_parsed"):
        from time import mktime
        episode["published_date"] = datetime.fromtimestamp(mktime(entry.published_parsed)).strftime("%Y-%m-%d")
    else:
        episode["published_date"] = datetime.now().strftime("%Y-%m-%d")

    return episode


def main():
    parser = argparse.ArgumentParser(
        description="Manually import a podcast episode by pasting transcript",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("url", help="Episode URL or RSS feed URL")
    parser.add_argument("--episode", type=int, default=0,
                       help="Episode index if URL is an RSS feed (0 = latest)")
    parser.add_argument("--show-name", help="Override show name")
    parser.add_argument("--episode-title", help="Override episode title")
    args = parser.parse_args()

    # Determine if URL is RSS feed or episode page
    episode_info = None
    url = args.url

    if any(x in url.lower() for x in ["/feed", "/rss", ".xml", "feed="]):
        print(f"Detected RSS feed, fetching episode {args.episode}...")
        episode_info = get_episode_from_rss(url, args.episode)
        print(f"Episode: {episode_info['title']}")
        print(f"Show: {episode_info['show']['name']}")
        url = episode_info.get("url", url)

    # Override with CLI args
    if args.show_name and episode_info:
        episode_info["show"]["name"] = args.show_name
    if args.episode_title and episode_info:
        episode_info["title"] = args.episode_title

    print("\n" + "="*50)
    print("Paste the transcript text below.")
    print("When done, press Enter twice (empty line) to finish.")
    print("="*50 + "\n")

    lines = []
    empty_count = 0

    while True:
        try:
            line = input()
            if line == "":
                empty_count += 1
                if empty_count >= 2:
                    break
                lines.append("")
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break

    transcript_text = "\n".join(lines).strip()

    if not transcript_text:
        print("No transcript provided. Aborting.")
        sys.exit(1)

    print(f"\nReceived {len(transcript_text)} characters of transcript.")

    # Parse into segments
    segments = parse_manual_transcript(transcript_text)
    print(f"Created {len(segments)} segments.")

    # Initialize LLM
    llm = LLMClient()

    # Chunk into sections
    print("Analyzing transcript sections...")
    section_chunks = chunk_into_sections(segments)

    sections = []
    for i, chunk in enumerate(section_chunks):
        print(f"  Analyzing section {i+1}/{len(section_chunks)}...")
        analysis = analyze_section(chunk["text"], llm)
        sections.append({
            "start": int(chunk["start"]),
            "end": int(chunk["end"]),
            "title": analysis["title"],
            "description": analysis["description"]
        })

    # Generate full text for analysis
    full_text = " ".join(s["text"] for s in segments)

    # Generate title if not provided
    if episode_info:
        title = episode_info.get("title", "")
    else:
        title = args.episode_title

    if not title:
        print("Generating title...")
        title = generate_title(full_text, llm)

    print("Generating summary...")
    summary = generate_summary(full_text, llm)

    print("Extracting facets...")
    facets = extract_facets(full_text, llm)

    # Build metadata
    episode_id = generate_id(url)
    slug = sanitize_filename(title)

    # Estimate duration from segments
    total_duration = sum(s.get("duration", 3.0) for s in segments)

    metadata = {
        "id": episode_id,
        "content_type": "podcast",
        "title": title,
        "url": url,
        "audio_url": episode_info.get("audio_url", "") if episode_info else "",
        "slug": slug,
        "show": episode_info.get("show", {
            "name": args.show_name or "Unknown Show",
            "slug": sanitize_filename(args.show_name or "unknown-show"),
            "feed_url": ""
        }) if episode_info else {
            "name": args.show_name or "Unknown Show",
            "slug": sanitize_filename(args.show_name or "unknown-show"),
            "feed_url": ""
        },
        "duration_seconds": int(total_duration),
        "published_date": episode_info.get("published_date", datetime.now().strftime("%Y-%m-%d")) if episode_info else datetime.now().strftime("%Y-%m-%d"),
        "added_date": datetime.now().strftime("%Y-%m-%d"),
        "transcript_source": "manual",
        "facets": facets,
        "summary": summary,
        "sections": sections
    }

    # Add show slug
    if "show" in metadata:
        metadata["show"]["slug"] = sanitize_filename(metadata["show"]["name"])

    # Create directories
    PODCASTS_DIR.mkdir(exist_ok=True)
    METADATA_DIR.mkdir(exist_ok=True)

    # Write markdown
    md_path = PODCASTS_DIR / f"{slug}.md"
    print(f"Writing markdown to {md_path.name}...")

    md_content = f"# {title}\n\n"
    md_content += f"**Show:** {metadata['show']['name']}\n"
    md_content += f"**Published:** {metadata['published_date']}\n\n"
    md_content += "---\n\n"

    for section in sections:
        h = section["start"] // 3600
        m = (section["start"] % 3600) // 60
        s = section["start"] % 60
        timestamp = f"{h:02d}:{m:02d}:{s:02d}"
        md_content += f"## [{timestamp}] {section['title']}\n\n"
        if section.get("description"):
            md_content += f"*{section['description']}*\n\n"

    md_content += "---\n\n## Full Transcript\n\n"
    md_content += transcript_text

    md_path.write_text(md_content, encoding="utf-8")

    # Write metadata
    json_path = METADATA_DIR / f"{slug}.json"
    print(f"Writing metadata to {json_path.name}...")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("\nRegenerating site...")
    generate_site()

    print(f"\nDone! Added: {title}")
    print(f"Slug: {slug}")


if __name__ == "__main__":
    main()
