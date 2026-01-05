#!/usr/bin/env python3
"""
podcast_import.py

Import podcast episodes with transcripts into the learning library.
Fetches episode metadata from RSS feeds and extracts or accepts transcripts.

Usage:
    python podcast_import.py <rss_feed_url>                    # Latest episode
    python podcast_import.py <rss_feed_url> --episode 0        # Specific episode (0=latest)
    python podcast_import.py <rss_feed_url> --list             # List episodes
    python podcast_import.py <rss_feed_url> --dry-run          # Preview only
    python podcast_import.py --url <episode_url> --manual      # Manual transcript

Prerequisites:
    pip install feedparser defusedxml
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests

from llm_client import LLMClient

# Paths
BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
PODCASTS_DIR = BASE_DIR / "podcasts"
PODCASTS_CACHE_DIR = BASE_DIR / "podcasts_cache"

# Ensure directories exist
METADATA_DIR.mkdir(exist_ok=True)
PODCASTS_DIR.mkdir(exist_ok=True)

# Request settings
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Learning-Library-Bot/1.0"
}
REQUEST_DELAY = 1.0

# LLM Prompts (similar to youtube_transcript_to_md.py)
SECTION_PROMPT = """Analyze this podcast transcript section and provide:
1. A short title (3-7 words)
2. A one-sentence description

Format your response exactly as:
TITLE: <title here>
DESCRIPTION: <description here>

Transcript section:
{text}"""

SUMMARY_PROMPT = """Summarize this podcast transcript in 3-5 bullet points.
Each bullet should be one sentence capturing a key insight or topic.
Format: Start each line with "- "

Transcript:
{text}"""

FACETS_PROMPT = """Analyze this podcast episode and categorize it.

Title: {title}
Description: {description}
Transcript excerpt: {excerpt}

Choose ONE topic from: security, programming, ai-ml, entrepreneurship, devops,
                     databases, web-development, career, other
Choose ONE format from: interview, tutorial, deep-dive, news, discussion, other
Choose ONE difficulty from: beginner, intermediate, advanced

Format your response exactly as:
TOPIC: <topic>
FORMAT: <format>
DIFFICULTY: <difficulty>"""


def parse_rss_feed(feed_url: str) -> dict:
    """
    Parse podcast RSS feed and extract show and episode metadata.

    Returns:
        Dict with 'show' info and 'episodes' list
    """
    print(f"Fetching RSS feed: {feed_url}")

    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        print(f"Error parsing RSS feed: {feed.bozo_exception}")
        return {}

    # Extract show-level metadata
    show = {
        "name": feed.feed.get("title", "Unknown Show"),
        "description": feed.feed.get("description", ""),
        "author": feed.feed.get("author", feed.feed.get("itunes_author", "")),
        "url": feed.feed.get("link", ""),
        "feed_url": feed_url,
        "image_url": "",
        "slug": slugify(feed.feed.get("title", "unknown-show"))
    }

    # Try to get show image
    if hasattr(feed.feed, "image") and feed.feed.image:
        show["image_url"] = feed.feed.image.get("href", "")
    elif hasattr(feed.feed, "itunes_image"):
        show["image_url"] = feed.feed.itunes_image.get("href", "")

    # Extract episodes
    episodes = []
    for i, entry in enumerate(feed.entries):
        episode = {
            "index": i,
            "title": entry.get("title", f"Episode {i}"),
            "description": entry.get("summary", entry.get("description", "")),
            "url": entry.get("link", ""),
            "guid": entry.get("id", entry.get("link", "")),
            "published_date": "",
            "duration_seconds": 0,
            "audio_url": "",
            "transcript_url": None
        }

        # Parse published date
        if entry.get("published_parsed"):
            try:
                dt = datetime(*entry.published_parsed[:6])
                episode["published_date"] = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        # Parse duration (itunes:duration can be HH:MM:SS, MM:SS, or seconds)
        duration_str = entry.get("itunes_duration", "")
        if duration_str:
            episode["duration_seconds"] = parse_duration(duration_str)

        # Get audio URL from enclosures
        for enclosure in entry.get("enclosures", []):
            if enclosure.get("type", "").startswith("audio/"):
                episode["audio_url"] = enclosure.get("href", "")
                break

        # Check for transcript link (podcast:transcript tag)
        for link in entry.get("links", []):
            if link.get("rel") == "transcript" or "transcript" in link.get("type", "").lower():
                episode["transcript_url"] = link.get("href")
                break

        # Also check for podcast namespace transcript
        if hasattr(entry, "podcast_transcript"):
            episode["transcript_url"] = entry.podcast_transcript.get("url")

        episodes.append(episode)

    print(f"Found {len(episodes)} episodes from '{show['name']}'")

    return {"show": show, "episodes": episodes}


def parse_duration(duration_str: str) -> int:
    """Parse duration string to seconds. Handles HH:MM:SS, MM:SS, or raw seconds."""
    if not duration_str:
        return 0

    # If it's just a number, assume seconds
    if duration_str.isdigit():
        return int(duration_str)

    parts = duration_str.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(float(duration_str))
    except (ValueError, TypeError):
        return 0


def slugify(text: str) -> str:
    """Create URL-safe slug from text."""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    # Limit length
    return slug[:80] if slug else "untitled"


def generate_episode_id(episode: dict) -> str:
    """Generate unique ID from episode GUID or URL."""
    source = episode.get("guid") or episode.get("url") or episode.get("title", "")
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def fetch_transcript_from_url(url: str) -> str:
    """Fetch transcript from URL (SRT, VTT, or plain text)."""
    if not url:
        return ""

    print(f"  Fetching transcript from: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        content = response.text

        # Check if it's SRT/VTT format and convert to plain text
        if url.endswith(('.srt', '.vtt')) or '-->' in content:
            return parse_srt_vtt(content)

        return content

    except requests.RequestException as e:
        print(f"  Error fetching transcript: {e}")
        return ""


def parse_srt_vtt(content: str) -> str:
    """Parse SRT/VTT subtitle format into plain text."""
    lines = content.split('\n')
    text_lines = []

    for line in lines:
        line = line.strip()
        # Skip empty lines, timestamps, and sequence numbers
        if not line:
            continue
        if '-->' in line:  # Timestamp line
            continue
        if line.isdigit():  # SRT sequence number
            continue
        if line.startswith('WEBVTT'):  # VTT header
            continue
        if line.startswith('NOTE'):  # VTT comment
            continue
        # Remove VTT formatting tags
        line = re.sub(r'<[^>]+>', '', line)
        text_lines.append(line)

    return ' '.join(text_lines)


def prompt_for_transcript() -> str:
    """Prompt user to paste transcript manually."""
    print("\n" + "=" * 60)
    print("MANUAL TRANSCRIPT INPUT")
    print("=" * 60)
    print("Paste the transcript below. When done, enter an empty line or press Ctrl+D:")
    print("-" * 60)

    lines = []
    try:
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
    except EOFError:
        pass

    transcript = '\n'.join(lines)
    print(f"\nReceived {len(transcript)} characters")
    return transcript


def parse_plain_transcript(text: str, avg_wpm: int = 150) -> list:
    """
    Convert plain text transcript to segments with estimated timestamps.

    Args:
        text: Plain text transcript
        avg_wpm: Assumed speaking rate (words per minute)

    Returns:
        List of segments like: [{text, start, duration}, ...]
    """
    # Split into sentences/chunks
    sentences = re.split(r'(?<=[.!?])\s+', text)

    segments = []
    current_time = 0.0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Estimate duration based on word count
        words = len(sentence.split())
        duration = (words / avg_wpm) * 60  # Convert to seconds

        segments.append({
            "text": sentence,
            "start": current_time,
            "duration": duration
        })

        current_time += duration

    return segments


def chunk_into_sections(segments: list, target_duration: int = 180) -> list:
    """Group transcript segments into ~3 minute sections."""
    sections = []
    current_section = []
    section_start = 0

    for segment in segments:
        current_section.append(segment)
        duration = segment["start"] - section_start

        if duration >= target_duration and segment["text"].rstrip().endswith(('.', '?', '!')):
            sections.append({
                "start": section_start,
                "end": segment["start"] + segment.get("duration", 0),
                "segments": current_section
            })
            current_section = []
            section_start = segment["start"] + segment.get("duration", 0)

    if current_section:
        last_seg = current_section[-1]
        sections.append({
            "start": section_start,
            "end": last_seg["start"] + last_seg.get("duration", 0),
            "segments": current_section
        })

    return sections


def analyze_section(section: dict, llm: LLMClient) -> dict:
    """Generate title and description for a section using LLM."""
    text = " ".join(seg["text"] for seg in section["segments"])
    text = text[:1500]

    prompt = SECTION_PROMPT.format(text=text)
    result = llm.generate(prompt, timeout=60)

    title = "Untitled Section"
    description = ""

    for line in result.split('\n'):
        if line.startswith("TITLE:"):
            title = line[6:].strip()
        elif line.startswith("DESCRIPTION:"):
            description = line[12:].strip()

    return {
        "start": int(section["start"]),
        "end": int(section["end"]),
        "title": title,
        "description": description
    }


def generate_metadata(
    episode: dict,
    show: dict,
    segments: list,
    llm: LLMClient
) -> dict:
    """Generate full metadata for podcast episode."""

    # Combine all transcript text
    full_text = " ".join(seg["text"] for seg in segments)
    excerpt = full_text[:3000]

    # Generate title (use episode title if good, else generate)
    title = episode.get("title", "")
    if not title or len(title) < 5:
        prompt = f"""Based on this podcast transcript, generate a concise title (3-8 words).
Only output the title, nothing else.

Transcript:
{excerpt[:1000]}"""
        title = llm.generate(prompt, timeout=30) or "Untitled Episode"

    # Generate summary
    print("  Generating summary...")
    summary_prompt = SUMMARY_PROMPT.format(text=excerpt[:2000])
    summary_result = llm.generate(summary_prompt, timeout=90)
    summary = [line[2:].strip() for line in summary_result.split('\n')
               if line.strip().startswith('- ')]

    # Generate facets
    print("  Analyzing topics and difficulty...")
    facets_prompt = FACETS_PROMPT.format(
        title=title,
        description=episode.get("description", "")[:500],
        excerpt=excerpt[:1000]
    )
    facets_result = llm.generate(facets_prompt, timeout=30)

    facets = {
        "topics": ["other"],
        "format": "discussion",
        "difficulty": "intermediate"
    }

    for line in facets_result.split('\n'):
        if line.startswith("TOPIC:"):
            facets["topics"] = [line[6:].strip().lower()]
        elif line.startswith("FORMAT:"):
            facets["format"] = line[7:].strip().lower()
        elif line.startswith("DIFFICULTY:"):
            facets["difficulty"] = line[11:].strip().lower()

    # Generate sections
    print("  Generating sections...")
    sections_data = chunk_into_sections(segments)
    analyzed_sections = []
    for i, section in enumerate(sections_data[:10]):  # Limit to 10 sections
        print(f"    Section {i+1}/{min(len(sections_data), 10)}...")
        analyzed = analyze_section(section, llm)
        analyzed_sections.append(analyzed)

    return {
        "title": title,
        "summary": summary,
        "facets": facets,
        "sections": analyzed_sections
    }


def save_podcast(
    episode: dict,
    show: dict,
    analysis: dict,
    segments: list,
    transcript_source: str
) -> tuple:
    """
    Save podcast episode metadata and markdown.

    Returns:
        Tuple of (metadata_path, markdown_path)
    """
    # Generate filename slug
    title = analysis.get("title") or episode.get("title", "")
    slug = slugify(title)

    episode_id = generate_episode_id(episode)

    # Build metadata
    metadata = {
        "id": episode_id,
        "content_type": "podcast",
        "title": analysis.get("title"),
        "url": episode.get("url"),
        "audio_url": episode.get("audio_url"),
        "show": {
            "name": show.get("name"),
            "slug": show.get("slug"),
            "url": show.get("url"),
            "feed_url": show.get("feed_url"),
            "author": show.get("author"),
            "image_url": show.get("image_url")
        },
        "duration_seconds": episode.get("duration_seconds", 0),
        "published_date": episode.get("published_date"),
        "facets": analysis.get("facets", {}),
        "summary": analysis.get("summary", []),
        "sections": analysis.get("sections", []),
        "transcript_source": transcript_source,
        "added_date": datetime.now().strftime("%Y-%m-%d")
    }

    # Save metadata JSON
    metadata_path = METADATA_DIR / f"{slug}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Build markdown
    md_lines = [
        f"# {metadata['title']}",
        "",
        f"**Show:** [{show['name']}]({show.get('url', '')})",
        "",
        f"**Published:** {metadata['published_date'] or 'Unknown'}",
        "",
    ]

    if metadata.get("duration_seconds"):
        duration = metadata["duration_seconds"]
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        if hours:
            md_lines.append(f"**Duration:** {hours}h {minutes}m")
        else:
            md_lines.append(f"**Duration:** {minutes} minutes")
        md_lines.append("")

    if episode.get("audio_url"):
        md_lines.extend([
            f"**Audio:** [Listen]({episode['audio_url']})",
            ""
        ])

    # Summary
    if metadata.get("summary"):
        md_lines.extend(["## Summary", ""])
        for point in metadata["summary"]:
            md_lines.append(f"- {point}")
        md_lines.append("")

    # Sections
    if metadata.get("sections"):
        md_lines.extend(["## Sections", ""])
        for sec in metadata["sections"]:
            timestamp = format_timestamp_compact(sec["start"])
            md_lines.append(f"- **[{timestamp}]** {sec['title']} - {sec.get('description', '')}")
        md_lines.append("")

    # Full transcript
    md_lines.extend(["## Full Transcript", "", "<div class=\"transcript-prose\">"])

    for segment in segments:
        timestamp = format_timestamp_compact(segment["start"])
        text = segment["text"]
        md_lines.append(f'<span class="margin-timestamp">{timestamp}</span>')
        md_lines.append(f'<span class="prose-segment">{text} </span>')

    md_lines.extend(["</div>", ""])

    # Metadata footer
    md_lines.extend([
        "---",
        "",
        f"*Topics: {', '.join(metadata['facets'].get('topics', []))}*",
        f"*Format: {metadata['facets'].get('format', 'unknown')}*",
        f"*Difficulty: {metadata['facets'].get('difficulty', 'unknown')}*",
    ])

    # Save markdown
    markdown_path = PODCASTS_DIR / f"{slug}.md"
    with open(markdown_path, "w") as f:
        f.write("\n".join(md_lines))

    return metadata_path, markdown_path


def format_timestamp_compact(seconds: float) -> str:
    """Compact timestamp for display (0:03 or 1:23:45)."""
    s = int(seconds)
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def get_existing_podcast_ids() -> set:
    """Get set of podcast IDs already in the library."""
    ids = set()
    for json_file in METADATA_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                if data.get("content_type") == "podcast":
                    ids.add(data.get("id"))
        except Exception:
            pass
    return ids


def import_episode(
    feed_data: dict,
    episode_index: int = 0,
    manual_transcript: bool = False,
    dry_run: bool = False
) -> dict:
    """
    Import a single podcast episode.

    Args:
        feed_data: Parsed RSS feed data with 'show' and 'episodes'
        episode_index: Index of episode to import (0 = latest)
        manual_transcript: Whether to prompt for manual transcript
        dry_run: Preview without importing

    Returns:
        Metadata dict if successful, empty dict on failure
    """
    if not feed_data.get("episodes"):
        print("No episodes found in feed.")
        return {}

    if episode_index >= len(feed_data["episodes"]):
        print(f"Episode index {episode_index} out of range (max: {len(feed_data['episodes'])-1})")
        return {}

    episode = feed_data["episodes"][episode_index]
    show = feed_data["show"]

    print(f"\nImporting episode: {episode['title'][:50]}...")

    # Check if already imported
    episode_id = generate_episode_id(episode)
    existing_ids = get_existing_podcast_ids()
    if episode_id in existing_ids:
        print(f"  Episode already in library. Skipping.")
        return {}

    if dry_run:
        print(f"  [DRY RUN] Would import:")
        print(f"    Title: {episode['title']}")
        print(f"    Published: {episode.get('published_date', 'unknown')}")
        print(f"    Duration: {episode.get('duration_seconds', 0) // 60} minutes")
        print(f"    Audio: {episode.get('audio_url', 'N/A')[:50]}...")
        print(f"    Transcript URL: {episode.get('transcript_url', 'None')}")
        return {"dry_run": True}

    # Get transcript
    transcript = ""
    transcript_source = "unknown"

    # Try RSS-embedded transcript first
    if episode.get("transcript_url") and not manual_transcript:
        transcript = fetch_transcript_from_url(episode["transcript_url"])
        if transcript:
            transcript_source = "rss"
            print(f"  Found RSS transcript: {len(transcript)} characters")

    # Fall back to manual input
    if not transcript:
        if manual_transcript:
            transcript = prompt_for_transcript()
            transcript_source = "manual"
        else:
            print("  No transcript found in RSS feed.")
            print("  Use --manual flag to paste transcript, or check if podcast provides transcripts.")
            return {}

    if not transcript or len(transcript) < 100:
        print("  Error: Transcript too short or empty.")
        return {}

    # Parse transcript into segments
    segments = parse_plain_transcript(transcript)
    print(f"  Parsed {len(segments)} transcript segments")

    # Initialize LLM
    llm = LLMClient()
    if not llm.is_available():
        print("  Warning: LLM not available. Using basic metadata only.")
        analysis = {
            "title": episode.get("title"),
            "summary": [episode.get("description", "")[:200]],
            "facets": {"topics": ["other"], "format": "discussion", "difficulty": "intermediate"},
            "sections": []
        }
    else:
        # Generate metadata with LLM
        print("  Analyzing with LLM...")
        analysis = generate_metadata(episode, show, segments, llm)

    # Save
    metadata_path, markdown_path = save_podcast(
        episode, show, analysis, segments, transcript_source
    )
    print(f"  Saved: {metadata_path.name}")

    return {"success": True, "metadata_path": str(metadata_path)}


def main():
    parser = argparse.ArgumentParser(
        description="Import podcast episodes with transcripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python podcast_import.py <rss_feed_url>                # Import latest episode
    python podcast_import.py <rss_feed_url> --episode 0    # Specific episode (0=latest)
    python podcast_import.py <rss_feed_url> --list         # List all episodes
    python podcast_import.py <rss_feed_url> --manual       # Paste transcript manually
    python podcast_import.py <rss_feed_url> --dry-run      # Preview only
        """
    )

    parser.add_argument("feed_url", help="Podcast RSS feed URL")
    parser.add_argument("--episode", type=int, default=0,
                        help="Episode index to import (0=latest, default: 0)")
    parser.add_argument("--list", action="store_true",
                        help="List all episodes in feed")
    parser.add_argument("--manual", action="store_true",
                        help="Prompt for manual transcript paste")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without importing")

    args = parser.parse_args()

    # Parse RSS feed
    feed_data = parse_rss_feed(args.feed_url)
    if not feed_data:
        print("Error: Could not parse RSS feed.")
        sys.exit(1)

    # List mode
    if args.list:
        print(f"\n{'='*60}")
        print(f"EPISODES FROM: {feed_data['show']['name']}")
        print(f"{'='*60}")
        for ep in feed_data["episodes"]:
            transcript_indicator = " [T]" if ep.get("transcript_url") else ""
            print(f"  [{ep['index']}] {ep['title'][:50]}...{transcript_indicator}")
            print(f"      Published: {ep.get('published_date', 'unknown')} | "
                  f"Duration: {ep.get('duration_seconds', 0) // 60}m")
        print(f"\n[T] = Has embedded transcript")
        return

    # Import episode
    result = import_episode(
        feed_data,
        episode_index=args.episode,
        manual_transcript=args.manual,
        dry_run=args.dry_run
    )

    if result and result.get("success"):
        print("\nEpisode imported successfully!")
    elif result and result.get("dry_run"):
        print("\n[DRY RUN] No changes made.")
    else:
        print("\nFailed to import episode.")
        sys.exit(1)


if __name__ == "__main__":
    main()
