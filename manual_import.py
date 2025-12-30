#!/usr/bin/env python3
"""
manual_import.py

Manually import a YouTube video by pasting transcript text.
Useful for videos without auto-generated captions.

Usage:
    python manual_import.py <youtube_url>
"""

import json
import sys
from pathlib import Path

import requests

from youtube_transcript_to_md import (
    extract_video_id,
    generate_metadata,
    write_markdown,
    sanitize_filename,
    TRANSCRIPTS_DIR,
    METADATA_DIR,
    BASE_DIR
)
from library import generate_site

PENDING_FILE = BASE_DIR / "pending.json"


def get_video_title(url: str) -> str:
    """Try to get video title from YouTube oEmbed API."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        response = requests.get(oembed_url, timeout=10)
        response.raise_for_status()
        return response.json().get("title", "")
    except Exception:
        return ""


def parse_manual_transcript(text: str) -> list:
    """
    Parse manually pasted transcript into segment format.
    Assumes plain text, creates artificial segments.
    """
    # Split into sentences/chunks
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    segments = []
    current_time = 0.0
    avg_duration = 3.0  # Assume ~3 seconds per sentence

    for sentence in sentences:
        if sentence.strip():
            segments.append({
                "text": sentence.strip(),
                "start": current_time,
                "duration": avg_duration
            })
            current_time += avg_duration

    return segments


def remove_from_pending(video_id: str):
    """Remove a video from pending.json after successful import."""
    if not PENDING_FILE.exists():
        return

    try:
        with open(PENDING_FILE) as f:
            pending = json.load(f)

        pending["failed"] = [
            item for item in pending["failed"]
            if item["video_id"] != video_id
        ]

        with open(PENDING_FILE, "w") as f:
            json.dump(pending, f, indent=2)
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print("Usage: python manual_import.py <youtube_url>")
        sys.exit(1)

    url = sys.argv[1]

    try:
        video_id = extract_video_id(url)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Video ID: {video_id}")

    # Try to get title from YouTube
    title = get_video_title(url)
    if title:
        print(f"Title: {title}")

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

    print("\nGenerating metadata with LLM analysis...")
    metadata = generate_metadata(segments, video_id, url)

    # Override title if we got it from oEmbed and LLM title is generic
    if title and metadata["title"].startswith("Video "):
        metadata["title"] = title

    filename = sanitize_filename(metadata["title"])
    md_path = TRANSCRIPTS_DIR / f"{filename}.md"
    json_path = METADATA_DIR / f"{filename}.json"

    print(f"Writing markdown to {md_path.name}...")
    write_markdown(segments, metadata, md_path)

    print(f"Writing metadata to {json_path.name}...")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # Remove from pending if it was there
    remove_from_pending(video_id)

    print("\nRegenerating site...")
    generate_site()

    print(f"\nDone! Added: {metadata['title']}")


if __name__ == "__main__":
    main()
