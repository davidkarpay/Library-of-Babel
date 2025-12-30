#!/usr/bin/env python3
"""
batch_import.py

Process multiple YouTube URLs from a markdown file into the library.
Skips videos already processed, handles failures gracefully.

Usage:
    python batch_import.py <markdown_file>
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from youtube_transcript_to_md import (
    extract_video_id,
    fetch_transcript,
    generate_metadata,
    write_markdown,
    sanitize_filename,
    TRANSCRIPTS_DIR,
    METADATA_DIR,
    BASE_DIR
)
from library import generate_site

PENDING_FILE = BASE_DIR / "pending.json"


def extract_urls_from_markdown(md_path: Path) -> list:
    """Extract all YouTube URLs from a markdown file."""
    content = md_path.read_text()
    pattern = r'https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+'
    return list(set(re.findall(pattern, content)))


def get_existing_video_ids() -> set:
    """Get set of video IDs already in the library."""
    ids = set()
    for json_file in METADATA_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                ids.add(data.get("id"))
        except Exception:
            pass
    return ids


def load_pending() -> dict:
    """Load pending.json or return empty structure."""
    if PENDING_FILE.exists():
        try:
            with open(PENDING_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"failed": []}


def save_pending(data: dict):
    """Save pending.json."""
    with open(PENDING_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_to_pending(url: str, video_id: str, error: str, source_file: str):
    """Add a failed video to pending.json."""
    pending = load_pending()

    # Check if already in pending
    existing_ids = {item["video_id"] for item in pending["failed"]}
    if video_id in existing_ids:
        return

    pending["failed"].append({
        "url": url,
        "video_id": video_id,
        "error": error,
        "attempted_at": datetime.now().isoformat(),
        "source_file": source_file
    })
    save_pending(pending)


def process_video(url: str) -> tuple:
    """Process a single video. Returns (success, message)."""
    try:
        video_id = extract_video_id(url)
        transcript = fetch_transcript(video_id)
        metadata = generate_metadata(transcript, video_id, url)

        filename = sanitize_filename(metadata["title"])
        md_path = TRANSCRIPTS_DIR / f"{filename}.md"
        json_path = METADATA_DIR / f"{filename}.json"

        write_markdown(transcript, metadata, md_path)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return True, metadata["title"]
    except Exception as e:
        return False, str(e)


def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_import.py <markdown_file>")
        sys.exit(1)

    md_path = Path(sys.argv[1])
    if not md_path.exists():
        print(f"File not found: {md_path}")
        sys.exit(1)

    print(f"Extracting URLs from {md_path.name}...")
    urls = extract_urls_from_markdown(md_path)
    print(f"Found {len(urls)} unique YouTube URLs")

    existing_ids = get_existing_video_ids()
    print(f"Already in library: {len(existing_ids)} videos")

    # Filter out already processed
    to_process = []
    for url in urls:
        try:
            vid = extract_video_id(url)
            if vid not in existing_ids:
                to_process.append(url)
        except ValueError:
            pass

    print(f"To process: {len(to_process)} new videos\n")

    if not to_process:
        print("Nothing to process!")
        return

    success = 0
    failed = 0
    failures = []

    for i, url in enumerate(to_process, 1):
        video_id = extract_video_id(url)
        print(f"[{i}/{len(to_process)}] Processing {video_id}...")

        ok, msg = process_video(url)
        if ok:
            print(f"  -> {msg}")
            success += 1
        else:
            print(f"  FAILED: {msg}")
            add_to_pending(url, video_id, msg, md_path.name)
            failures.append((video_id, msg))
            failed += 1

    print(f"\n{'='*50}")
    print(f"Complete! Success: {success}, Failed: {failed}")

    if failures:
        print(f"\nFailed videos logged to: {PENDING_FILE}")
        print("Use 'python manual_import.py <url>' to add transcripts manually")
        for vid, err in failures:
            print(f"  - {vid}: {err}")

    if success > 0:
        print("\nRegenerating site...")
        generate_site()
        print("Done!")


if __name__ == "__main__":
    main()
