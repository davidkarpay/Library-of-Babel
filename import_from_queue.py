#!/usr/bin/env python3
"""
import_from_queue.py

Process videos from import_queue.json through the transcript pipeline.
Videos are added to the queue by youtube_history.py or manually.

Usage:
    python import_from_queue.py              # Process all queued videos
    python import_from_queue.py --limit 10   # Process only 10 videos
    python import_from_queue.py --dry-run    # Preview without importing
"""

import argparse
import json
import sys
import time
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

QUEUE_FILE = BASE_DIR / "import_queue.json"
PENDING_FILE = BASE_DIR / "pending.json"


def load_queue():
    """Load the import queue."""
    if not QUEUE_FILE.exists():
        return {"videos": []}
    try:
        with open(QUEUE_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading queue: {e}")
        return {"videos": []}


def save_queue(queue):
    """Save the import queue."""
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def load_pending():
    """Load pending.json."""
    if PENDING_FILE.exists():
        try:
            with open(PENDING_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"failed": []}


def save_pending(data):
    """Save pending.json."""
    with open(PENDING_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_to_pending(video, error):
    """Add a failed video to pending.json."""
    pending = load_pending()

    # Check if already in pending
    existing_ids = {item["video_id"] for item in pending["failed"]}
    if video["id"] in existing_ids:
        return

    pending["failed"].append({
        "url": video["url"],
        "video_id": video["id"],
        "error": str(error),
        "attempted_at": datetime.now().isoformat(),
        "source": "import_queue"
    })
    save_pending(pending)


def remove_from_queue(video_id, queue):
    """Remove a video from the queue."""
    queue["videos"] = [v for v in queue["videos"] if v["id"] != video_id]
    return queue


def process_video(video):
    """Process a single video through the import pipeline."""
    video_id = video["id"]
    url = video["url"]

    try:
        # Fetch transcript
        transcript = fetch_transcript(video_id)

        if not transcript:
            raise Exception("No transcript available")

        # Generate metadata with LLM analysis
        metadata = generate_metadata(transcript, video_id, url)

        if not metadata:
            raise Exception("Failed to generate metadata")

        # Create output filename
        filename = sanitize_filename(metadata["title"])

        # Write files
        transcript_path = TRANSCRIPTS_DIR / f"{filename}.md"
        metadata_path = METADATA_DIR / f"{filename}.json"

        write_markdown(transcript, metadata, transcript_path)

        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return True, metadata["title"]

    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Process import queue")
    parser.add_argument("--limit", type=int, help="Max videos to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between imports")
    args = parser.parse_args()

    print("=" * 60)
    print("Import Queue Processor")
    print("=" * 60)

    queue = load_queue()
    videos = queue.get("videos", [])

    if not videos:
        print("Queue is empty. Nothing to import.")
        print("\nTo add videos, run:")
        print("  python youtube_history.py")
        return

    print(f"Found {len(videos)} videos in queue.\n")

    if args.limit:
        videos = videos[:args.limit]
        print(f"Processing first {args.limit} videos.\n")

    if args.dry_run:
        print("DRY RUN - No changes will be made.\n")
        for i, video in enumerate(videos, 1):
            print(f"[{i}] {video['title']}")
            print(f"    Channel: {video.get('channel', 'Unknown')}")
            print(f"    URL: {video['url']}")
        return

    # Process videos
    success_count = 0
    fail_count = 0

    for i, video in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] {video['title'][:50]}...")

        success, result = process_video(video)

        if success:
            print(f"  ✓ Imported: {result}")
            queue = remove_from_queue(video["id"], queue)
            save_queue(queue)
            success_count += 1
        else:
            print(f"  ✗ Failed: {result}")
            add_to_pending(video, result)
            queue = remove_from_queue(video["id"], queue)
            save_queue(queue)
            fail_count += 1

        # Delay between imports
        if i < len(videos):
            time.sleep(args.delay)

    print("\n" + "=" * 60)
    print(f"Import complete!")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {fail_count} (added to pending.json)")
    print("=" * 60)

    # Regenerate site if any imports succeeded
    if success_count > 0:
        print("\nRegenerating site...")
        generate_site()
        print("Site updated!")


if __name__ == "__main__":
    main()
