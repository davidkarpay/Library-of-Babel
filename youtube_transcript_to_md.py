#!/usr/bin/env python3
"""
youtube_transcript_to_md.py

Fetch a YouTube video's transcript, generate structured metadata with LLM analysis,
and save as Markdown + JSON for the learning library.

Usage:
    python youtube_transcript_to_md.py <youtube_url>

Requires:
    pip install youtube-transcript-api requests
"""

import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from youtube_transcript_api import YouTubeTranscriptApi

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")

BASE_DIR = Path(__file__).parent
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
METADATA_DIR = BASE_DIR / "metadata"

TRANSCRIPTS_DIR.mkdir(exist_ok=True)
METADATA_DIR.mkdir(exist_ok=True)


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be"}:
        return parsed.path.lstrip("/")
    if parsed.hostname in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            return parse_qs(parsed.query)["v"][0]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/")[2]
    raise ValueError("Unsupported YouTube URL format")


def fetch_transcript(video_id: str):
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
    return transcript.to_raw_data()


def sanitize_filename(name: str, max_length: int = 50) -> str:
    name = name.lower().strip()
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s_]+', '-', name)
    name = re.sub(r'-+', '-', name)
    name = name.strip('-')
    if len(name) > max_length:
        name = name[:max_length].rsplit('-', 1)[0]
    return name or "transcript"


def slugify_channel(name: str) -> str:
    """Create URL-safe slug from channel name."""
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-') or "unknown-channel"


def fetch_channel_info(video_id: str) -> dict:
    """Fetch channel information using YouTube oEmbed API (no API key required)."""
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(url, timeout=10)
        if response.ok:
            data = response.json()
            channel_name = data.get("author_name", "Unknown Channel")
            channel_url = data.get("author_url", "")

            # Extract channel ID from URL if available
            channel_id = ""
            if channel_url:
                if "/channel/" in channel_url:
                    channel_id = channel_url.split("/channel/")[-1]
                elif "/@" in channel_url:
                    channel_id = channel_url.split("/@")[-1]

            return {
                "id": channel_id,
                "name": channel_name,
                "url": channel_url,
                "slug": slugify_channel(channel_name)
            }
    except Exception as e:
        print(f"  Warning: Could not fetch channel info: {e}")

    return {
        "id": "",
        "name": "Unknown Channel",
        "url": "",
        "slug": "unknown-channel"
    }


def format_timestamp(seconds: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(int(seconds)))


def format_timestamp_compact(seconds: float) -> str:
    """Compact timestamp for margin display (0:03 or 1:23:45)."""
    s = int(seconds)
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def ollama_generate(prompt: str, timeout: int = 60) -> str:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=timeout
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"Warning: Ollama request failed: {e}")
        return ""


def chunk_into_sections(transcript: list, target_duration: int = 180) -> list:
    """Group transcript segments into ~3 minute sections."""
    sections = []
    current_section = []
    section_start = 0

    for segment in transcript:
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


def analyze_section(section: dict) -> dict:
    """Generate title and description for a section using LLM."""
    text = " ".join(seg["text"] for seg in section["segments"])
    text = text[:1500]

    prompt = f"""Analyze this transcript section and provide:
1. A short title (3-7 words)
2. A one-sentence description

Format your response exactly as:
TITLE: <title here>
DESCRIPTION: <description here>

Transcript section:
{text}"""

    result = ollama_generate(prompt)

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


def generate_metadata(transcript: list, video_id: str, url: str,
                      channel_name: str = None, channel_id: str = None) -> dict:
    """Generate complete metadata for a video transcript.

    Args:
        transcript: List of transcript segments
        video_id: YouTube video ID
        url: Full YouTube URL
        channel_name: Optional channel name (if already known from channel import)
        channel_id: Optional channel ID (if already known from channel import)
    """
    print("  Chunking transcript into sections...")
    sections = chunk_into_sections(transcript)

    print(f"  Analyzing {len(sections)} sections...")
    analyzed_sections = []
    for i, section in enumerate(sections):
        print(f"    Section {i+1}/{len(sections)}...")
        analyzed_sections.append(analyze_section(section))

    full_text = " ".join(seg["text"] for seg in transcript)
    excerpt = full_text[:3000]

    print("  Generating title...")
    title_prompt = f"""Based on this transcript, generate a concise title (3-8 words).
Only output the title, nothing else.

Transcript:
{excerpt}"""
    title = ollama_generate(title_prompt) or f"Video {video_id}"

    print("  Generating summary...")
    summary_prompt = f"""Summarize this transcript in 3-5 bullet points.
Each bullet should be one sentence capturing a key insight or topic.
Format: Start each line with "- "

Transcript:
{excerpt}"""
    summary_result = ollama_generate(summary_prompt, timeout=90)
    summary = [line[2:].strip() for line in summary_result.split('\n')
               if line.strip().startswith('- ')]

    print("  Extracting facets...")
    facets_prompt = f"""Analyze this transcript and categorize it.

Choose ONE topic from: security, programming, ai-ml, entrepreneurship, devops, databases, web-development, career, other
Choose ONE format from: tutorial, deep-dive, news, interview, review, other
Choose ONE difficulty from: beginner, intermediate, advanced

Format your response exactly as:
TOPIC: <topic>
FORMAT: <format>
DIFFICULTY: <difficulty>

Transcript:
{excerpt}"""
    facets_result = ollama_generate(facets_prompt)

    facets = {"topics": ["other"], "format": "other", "difficulty": "intermediate"}
    for line in facets_result.split('\n'):
        if line.startswith("TOPIC:"):
            topic = line[6:].strip().lower().replace(" ", "-")
            facets["topics"] = [topic]
        elif line.startswith("FORMAT:"):
            facets["format"] = line[7:].strip().lower().replace(" ", "-")
        elif line.startswith("DIFFICULTY:"):
            facets["difficulty"] = line[11:].strip().lower()

    duration = transcript[-1]["start"] + transcript[-1].get("duration", 0) if transcript else 0

    # Fetch channel info if not provided
    if channel_name:
        channel_info = {
            "id": channel_id or "",
            "name": channel_name,
            "url": f"https://www.youtube.com/@{channel_id}" if channel_id else "",
            "slug": slugify_channel(channel_name)
        }
    else:
        print("  Fetching channel info...")
        channel_info = fetch_channel_info(video_id)

    return {
        "id": video_id,
        "title": title,
        "url": url,
        "channel": channel_info,
        "duration_seconds": int(duration),
        "facets": facets,
        "summary": summary[:5],
        "sections": analyzed_sections,
        "added_date": date.today().isoformat()
    }


def write_markdown(transcript: list, metadata: dict, output_path: Path):
    """Write enhanced markdown with sections."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {metadata['title']}\n\n")
        f.write(f"**Source:** [{metadata['url']}]({metadata['url']})\n\n")
        f.write(f"**Duration:** {format_timestamp(metadata['duration_seconds'])}\n\n")

        if metadata.get("summary"):
            f.write("## Summary\n\n")
            for point in metadata["summary"]:
                f.write(f"- {point}\n")
            f.write("\n")

        f.write("## Sections\n\n")
        for section in metadata.get("sections", []):
            ts = format_timestamp(section["start"])
            yt_link = f"{metadata['url']}&t={section['start']}s"
            f.write(f"- [{ts}]({yt_link}) **{section['title']}** - {section['description']}\n")
        f.write("\n")

        f.write("## Full Transcript\n\n")
        f.write('<div class="transcript-prose">\n')
        for segment in transcript:
            seconds = int(segment["start"])
            ts = format_timestamp_compact(seconds)
            text = segment["text"].replace("\n", " ").strip()
            yt_link = f"{metadata['url']}&t={seconds}s"
            f.write(f'<span class="margin-timestamp"><a href="{yt_link}">{ts}</a></span>')
            f.write(f'<span class="prose-segment">{text} </span>\n')
        f.write('</div>\n')


def main():
    if len(sys.argv) < 2:
        print("Usage: python youtube_transcript_to_md.py <youtube_url>")
        sys.exit(1)

    url = sys.argv[1]
    video_id = extract_video_id(url)

    print(f"Fetching transcript for {video_id}...")
    transcript = fetch_transcript(video_id)

    print("Generating metadata with LLM analysis...")
    metadata = generate_metadata(transcript, video_id, url)

    filename = sanitize_filename(metadata["title"])
    md_path = TRANSCRIPTS_DIR / f"{filename}.md"
    json_path = METADATA_DIR / f"{filename}.json"

    print(f"Writing markdown to {md_path}...")
    write_markdown(transcript, metadata, md_path)

    print(f"Writing metadata to {json_path}...")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nDone! Files created:")
    print(f"  Transcript: {md_path}")
    print(f"  Metadata: {json_path}")


if __name__ == "__main__":
    main()
