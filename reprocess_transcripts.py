#!/usr/bin/env python3
"""
Reprocess existing transcript markdown files to generate metadata.
Extracts the YouTube URL from the markdown and re-fetches the transcript.
"""

import re
import sys
from pathlib import Path

# Import from the main script
from youtube_transcript_to_md import (
    extract_video_id,
    fetch_transcript,
    generate_metadata,
    write_markdown,
    sanitize_filename,
    TRANSCRIPTS_DIR,
    METADATA_DIR
)
import json


def extract_url_from_markdown(md_path: Path) -> str:
    """Extract the YouTube URL from a markdown transcript file."""
    content = md_path.read_text()

    # Try to find URL in **Source:** format
    match = re.search(r'\*\*Source:\*\*\s*(https?://[^\s\)]+)', content)
    if match:
        return match.group(1)

    # Try markdown link format
    match = re.search(r'\[https?://[^\]]+\]\((https?://[^\)]+)\)', content)
    if match:
        return match.group(1)

    return None


def reprocess_file(md_path: Path):
    """Reprocess a single transcript file."""
    print(f"\nProcessing: {md_path.name}")

    url = extract_url_from_markdown(md_path)
    if not url:
        print(f"  ERROR: Could not extract URL from {md_path}")
        return False

    print(f"  Found URL: {url}")

    try:
        video_id = extract_video_id(url)
        print(f"  Video ID: {video_id}")

        print("  Fetching transcript...")
        transcript = fetch_transcript(video_id)

        print("  Generating metadata...")
        metadata = generate_metadata(transcript, video_id, url)

        # Use the generated title for the filename
        filename = sanitize_filename(metadata["title"])
        new_md_path = TRANSCRIPTS_DIR / f"{filename}.md"
        json_path = METADATA_DIR / f"{filename}.json"

        print(f"  Writing markdown to {new_md_path.name}...")
        write_markdown(transcript, metadata, new_md_path)

        print(f"  Writing metadata to {json_path.name}...")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        # Remove old file if different name
        if md_path != new_md_path and md_path.exists():
            print(f"  Removing old file: {md_path.name}")
            md_path.unlink()

        print(f"  Done: {filename}")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    # Find all markdown files in transcripts directory
    md_files = list(TRANSCRIPTS_DIR.glob("*.md"))

    if not md_files:
        print("No transcript files found in transcripts/")
        sys.exit(1)

    print(f"Found {len(md_files)} transcript file(s) to reprocess")

    success = 0
    failed = 0

    for md_path in md_files:
        if reprocess_file(md_path):
            success += 1
        else:
            failed += 1

    print(f"\n{'='*50}")
    print(f"Complete! Success: {success}, Failed: {failed}")


if __name__ == "__main__":
    main()
