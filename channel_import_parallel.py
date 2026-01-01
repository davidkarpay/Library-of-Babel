#!/usr/bin/env python3
"""
channel_import_parallel.py

Parallel import of all videos from a YouTube channel.
Uses ThreadPoolExecutor to process multiple videos concurrently.

Usage:
    python channel_import_parallel.py <channel_url>
    python channel_import_parallel.py https://www.youtube.com/@NateBJones --workers 8

Options:
    --workers N       Number of parallel workers (default: 6)
    --limit N         Only process first N videos
    --dry-run         Show what would be imported without processing
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

try:
    import scrapetube
except ImportError:
    print("Error: scrapetube is required. Install with: pip install scrapetube")
    sys.exit(1)

from youtube_transcript_to_md import (
    fetch_transcript,
    generate_metadata,
    write_markdown,
    sanitize_filename,
    slugify_channel,
    TRANSCRIPTS_DIR,
    METADATA_DIR,
    BASE_DIR
)
from batch_import import get_existing_video_ids, load_pending, save_pending
from library import generate_site
from channel_import import (
    extract_channel_identifier,
    fetch_channel_videos,
    get_channel_info_from_video,
    get_video_title_from_scrape
)

PENDING_FILE = BASE_DIR / "pending.json"

# Thread-safe counters
print_lock = Lock()
pending_lock = Lock()
stats = {"success": 0, "failed": 0, "processed": 0}
stats_lock = Lock()


def safe_print(*args, **kwargs):
    """Thread-safe print."""
    with print_lock:
        print(*args, **kwargs)


# US location IDs for ExpressVPN (via expresso)
US_VPN_LOCATIONS = [
    6, 70, 74, 71,  # Los Angeles
    9,   # Chicago
    19,  # Atlanta
    18,  # Dallas
    1,   # San Francisco
    2,   # Seattle
    25,  # Washington DC
    75,  # New York
    54,  # Miami
]


def switch_vpn():
    """Switch to a random US ExpressVPN location using expresso CLI."""
    expresso_path = os.path.expanduser("~/bin/expresso")
    if not os.path.exists(expresso_path):
        safe_print("Warning: expresso not found at ~/bin/expresso")
        return False

    try:
        location_id = random.choice(US_VPN_LOCATIONS)
        safe_print(f"\n>>> Switching VPN to location {location_id}...")

        result = subprocess.run(
            [expresso_path, "connect", "--change", str(location_id)],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            safe_print(f">>> VPN switched: {result.stdout.strip()}")
            time.sleep(3)  # Wait for connection to stabilize
            return True
        else:
            safe_print(f">>> VPN switch failed: {result.stderr.strip()}")
            return False

    except Exception as e:
        safe_print(f">>> VPN switch error: {e}")
        return False


def process_video_parallel(video_id: str, channel_info: dict, index: int, total: int, delay: float = 1.5) -> tuple:
    """
    Process a single video (thread-safe version with rate limiting).

    Returns: (video_id, success, message)
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    max_retries = 3
    base_backoff = 5  # seconds for exponential backoff

    for attempt in range(max_retries):
        try:
            # Add delay with jitter to avoid synchronized requests
            time.sleep(delay + random.uniform(0, 0.5))

            safe_print(f"[{index}/{total}] Starting: {video_id}" + (f" (retry {attempt+1})" if attempt > 0 else ""))

            transcript = fetch_transcript(video_id)
            metadata = generate_metadata(
                transcript,
                video_id,
                url,
                channel_name=channel_info['name'],
                channel_id=channel_info['id']
            )

            filename = sanitize_filename(metadata["title"])
            md_path = TRANSCRIPTS_DIR / f"{filename}.md"
            json_path = METADATA_DIR / f"{filename}.json"

            write_markdown(transcript, metadata, md_path)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            with stats_lock:
                stats["success"] += 1
                stats["processed"] += 1

            safe_print(f"[{index}/{total}] Done: {metadata['title'][:50]}")
            return (video_id, True, metadata["title"])

        except Exception as e:
            error_str = str(e)

            # Check if it's a rate limiting error and we have retries left
            if "blocking requests from your IP" in error_str and attempt < max_retries - 1:
                wait_time = base_backoff * (2 ** attempt) + random.uniform(0, 3)
                safe_print(f"[{index}/{total}] Rate limited, waiting {wait_time:.1f}s before retry...")
                time.sleep(wait_time)
                continue

            # Final failure - log it
            with stats_lock:
                stats["failed"] += 1
                stats["processed"] += 1

            safe_print(f"[{index}/{total}] FAILED: {video_id} - {error_str[:50]}")

            # Add to pending (thread-safe)
            with pending_lock:
                try:
                    pending = load_pending()
                    existing_ids = {item["video_id"] for item in pending["failed"]}
                    if video_id not in existing_ids:
                        pending["failed"].append({
                            "url": url,
                            "video_id": video_id,
                            "error": error_str,
                            "attempted_at": datetime.now().isoformat(),
                            "source_channel": channel_info['name']
                        })
                        save_pending(pending)
                except Exception:
                    pass

            return (video_id, False, error_str)

    # Should not reach here, but just in case
    return (video_id, False, "Max retries exceeded")


def main():
    parser = argparse.ArgumentParser(
        description='Parallel import of YouTube channel videos'
    )
    parser.add_argument('channel_url', help='YouTube channel URL')
    parser.add_argument('--workers', type=int, default=2,
                        help='Number of parallel workers (default: 2)')
    parser.add_argument('--delay', type=float, default=1.5,
                        help='Delay between requests in seconds (default: 1.5)')
    parser.add_argument('--vpn-rotate', type=int, default=0,
                        help='Switch VPN every N successful imports (0 = disabled, requires expresso)')
    parser.add_argument('--limit', type=int, help='Max videos to process')
    parser.add_argument('--dry-run', action='store_true',
                        help='List videos without importing')

    args = parser.parse_args()

    print(f"Fetching videos from {args.channel_url}...")

    videos = fetch_channel_videos(args.channel_url, args.limit)

    if not videos:
        print("No videos found! Check the channel URL.")
        sys.exit(1)

    print(f"Found {len(videos)} videos")

    # Get channel info from first video
    channel_info = get_channel_info_from_video(videos[0])
    print(f"Channel: {channel_info['name']}")

    # Get existing video IDs
    existing_ids = get_existing_video_ids()
    print(f"Already in library: {len(existing_ids)} videos")

    # Filter to new videos only
    to_process = []
    for video in videos:
        vid = video.get('videoId')
        if vid and vid not in existing_ids:
            to_process.append(video)

    print(f"New videos to import: {len(to_process)}")

    if args.dry_run:
        print("\nDry run - videos that would be imported:")
        for i, video in enumerate(to_process[:50], 1):
            title = get_video_title_from_scrape(video)
            print(f"  {i}. [{video.get('videoId')}] {title[:60]}...")
        if len(to_process) > 50:
            print(f"  ... and {len(to_process) - 50} more")
        return

    if not to_process:
        print("\nNothing new to import!")
        return

    total = len(to_process)
    vpn_info = f", VPN rotate every {args.vpn_rotate}" if args.vpn_rotate > 0 else ""
    print(f"\nStarting parallel import with {args.workers} workers (delay: {args.delay}s{vpn_info})...")
    print(f"Processing {total} videos...\n")

    start_time = time.time()
    last_vpn_switch_at = 0  # Track when we last switched VPN

    # Process videos in parallel
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for i, video in enumerate(to_process, 1):
            video_id = video.get('videoId')
            future = executor.submit(
                process_video_parallel,
                video_id,
                channel_info,
                i,
                total,
                args.delay
            )
            futures[future] = video_id

        # Wait for all to complete
        for future in as_completed(futures):
            # Check if we need to rotate VPN
            if args.vpn_rotate > 0:
                current_success = stats["success"]
                if current_success > 0 and current_success > last_vpn_switch_at and current_success % args.vpn_rotate == 0:
                    switch_vpn()
                    last_vpn_switch_at = current_success

    elapsed = time.time() - start_time

    print(f"\n{'='*50}")
    print(f"Complete! Success: {stats['success']}, Failed: {stats['failed']}")
    print(f"Time: {elapsed:.1f}s ({elapsed/total:.1f}s per video avg)")

    if stats['failed'] > 0:
        print(f"\nFailed videos logged to: {PENDING_FILE}")
        print("Use 'python manual_import.py <url>' to add transcripts manually")

    if stats['success'] > 0:
        print("\nRegenerating site...")
        generate_site()
        print("Done!")


if __name__ == "__main__":
    main()
