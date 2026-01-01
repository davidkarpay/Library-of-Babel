#!/usr/bin/env python3
"""
channel_import_pipeline.py

Producer-consumer pipeline for importing YouTube channel videos.
Separates slow YouTube API calls from fast local LLM processing.

Architecture:
  PRODUCER (1 thread)     QUEUE      CONSUMERS (N threads)    SITE UPDATER
  ┌─────────────────┐   ┌───────┐   ┌─────────────────┐      ┌────────────┐
  │ Fetch transcript│──►│ Queue │──►│ LLM processing  │──►   │ Regenerate │
  │ SLOWLY (no rate │   └───────┘   │ (parallel, fast)│      │ every N    │
  │ limit)          │               └─────────────────┘      └────────────┘
  └─────────────────┘

Usage:
    python channel_import_pipeline.py <channel_url>
    python channel_import_pipeline.py https://www.youtube.com/@IBMTechnology --consumers 4
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Lock, Event

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

# Thread-safe state
print_lock = Lock()
stats_lock = Lock()
pending_lock = Lock()
stats = {"success": 0, "failed": 0, "fetched": 0, "processed": 0}
done_event = Event()

# US location IDs for ExpressVPN (via expresso)
US_VPN_LOCATIONS = [6, 70, 74, 71, 9, 19, 18, 1, 2, 25, 75, 54]


def safe_print(*args, **kwargs):
    """Thread-safe print."""
    with print_lock:
        print(*args, **kwargs, flush=True)


def switch_vpn():
    """Switch to a random US ExpressVPN location using expresso CLI."""
    expresso_path = os.path.expanduser("~/bin/expresso")
    if not os.path.exists(expresso_path):
        return False

    try:
        location_id = random.choice(US_VPN_LOCATIONS)
        safe_print(f"\n>>> Switching VPN to location {location_id}...")

        result = subprocess.run(
            [expresso_path, "connect", "--change", str(location_id)],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode == 0:
            safe_print(f">>> VPN switched: {result.stdout.strip()}")
            time.sleep(3)
            return True
        return False
    except Exception as e:
        safe_print(f">>> VPN switch error: {e}")
        return False


def producer(video_queue: Queue, videos: list, channel_info: dict,
             delay: float = 8.0, vpn_rotate: int = 0):
    """
    Producer: Fetch transcripts slowly (one at a time) to avoid rate limits.
    VPN rotates on: every N attempts OR after 3 consecutive failures (rate limit detection).
    """
    total = len(videos)
    fetched = 0
    attempts = 0
    consecutive_failures = 0
    last_vpn_switch = 0

    for i, video in enumerate(videos, 1):
        if done_event.is_set():
            break

        video_id = video.get('videoId')
        url = f"https://www.youtube.com/watch?v={video_id}"

        # Delay between fetches
        time.sleep(delay + random.uniform(0, 1))

        attempts += 1

        # VPN rotation: every N attempts OR after consecutive failures
        if vpn_rotate > 0:
            should_rotate = (attempts > 0 and attempts > last_vpn_switch and attempts % vpn_rotate == 0)
            if should_rotate or consecutive_failures >= 3:
                if consecutive_failures >= 3:
                    safe_print(f">>> {consecutive_failures} consecutive failures - rotating VPN...")
                switch_vpn()
                last_vpn_switch = attempts
                consecutive_failures = 0

        try:
            safe_print(f"[FETCH {i}/{total}] {video_id}")
            transcript = fetch_transcript(video_id)

            # Add to queue for processing
            video_queue.put({
                'video_id': video_id,
                'url': url,
                'transcript': transcript,
                'channel_info': channel_info,
                'index': i,
                'total': total
            })

            with stats_lock:
                stats["fetched"] += 1
                fetched += 1
            consecutive_failures = 0  # Reset on success

        except Exception as e:
            error_str = str(e)
            consecutive_failures += 1
            safe_print(f"[FETCH {i}/{total}] FAILED: {video_id} - {error_str[:50]}")

            # Log to pending
            with pending_lock:
                try:
                    pending = load_pending()
                    if video_id not in {item["video_id"] for item in pending["failed"]}:
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

            with stats_lock:
                stats["failed"] += 1

    safe_print(f"\n>>> Producer finished. Fetched {fetched}/{total} transcripts.")


def consumer(video_queue: Queue, consumer_id: int):
    """
    Consumer: Process transcripts with LLM (no rate limit).
    """
    while not done_event.is_set():
        try:
            item = video_queue.get(timeout=5)
        except Empty:
            # Check if producer is done and queue is empty
            if video_queue.empty():
                time.sleep(1)
                if video_queue.empty():
                    continue
            continue

        if item is None:  # Poison pill
            break

        video_id = item['video_id']
        url = item['url']
        transcript = item['transcript']
        channel_info = item['channel_info']
        index = item['index']
        total = item['total']

        try:
            safe_print(f"[LLM {index}/{total}] Processing: {video_id}")

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

            safe_print(f"[LLM {index}/{total}] Done: {metadata['title'][:50]}")

        except Exception as e:
            with stats_lock:
                stats["failed"] += 1
                stats["processed"] += 1
            safe_print(f"[LLM {index}/{total}] FAILED: {video_id} - {str(e)[:50]}")

        video_queue.task_done()


def site_updater(interval: int = 50):
    """
    Site Updater: Regenerate the library site periodically.
    """
    last_count = 0

    while not done_event.is_set():
        time.sleep(30)  # Check every 30 seconds

        with stats_lock:
            current = stats["success"]

        if current >= last_count + interval:
            safe_print(f"\n>>> Regenerating site ({current} videos imported)...")
            try:
                generate_site()
                safe_print(f">>> Site updated!")
            except Exception as e:
                safe_print(f">>> Site update failed: {e}")
            last_count = current


def main():
    parser = argparse.ArgumentParser(
        description='Producer-consumer pipeline for YouTube channel import'
    )
    parser.add_argument('channel_url', help='YouTube channel URL')
    parser.add_argument('--consumers', type=int, default=4,
                        help='Number of LLM consumer threads (default: 4)')
    parser.add_argument('--delay', type=float, default=8.0,
                        help='Delay between transcript fetches (default: 8.0)')
    parser.add_argument('--vpn-rotate', type=int, default=15,
                        help='Switch VPN every N fetches (0 = disabled, default: 15)')
    parser.add_argument('--site-update', type=int, default=50,
                        help='Regenerate site every N imports (0 = disabled, default: 50)')
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

    # Get channel info
    channel_info = get_channel_info_from_video(videos[0])
    print(f"Channel: {channel_info['name']}")

    # Filter to new videos
    existing_ids = get_existing_video_ids()
    print(f"Already in library: {len(existing_ids)} videos")

    to_process = [v for v in videos if v.get('videoId') and v.get('videoId') not in existing_ids]
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

    # Create queue with buffer
    video_queue = Queue(maxsize=20)

    print(f"\n{'='*60}")
    print(f"Starting pipeline:")
    print(f"  Producer: 1 thread (delay: {args.delay}s, VPN rotate: {args.vpn_rotate})")
    print(f"  Consumers: {args.consumers} threads (LLM processing)")
    print(f"  Site updates: every {args.site_update} videos")
    print(f"  Videos to process: {len(to_process)}")
    print(f"{'='*60}\n")

    start_time = time.time()

    # Start threads
    threads = []

    # Producer (1 thread)
    producer_thread = Thread(
        target=producer,
        args=(video_queue, to_process, channel_info, args.delay, args.vpn_rotate),
        name="producer"
    )
    producer_thread.start()
    threads.append(producer_thread)

    # Consumers (N threads)
    for i in range(args.consumers):
        t = Thread(target=consumer, args=(video_queue, i), name=f"consumer-{i}")
        t.start()
        threads.append(t)

    # Site updater (1 thread)
    if args.site_update > 0:
        updater_thread = Thread(target=site_updater, args=(args.site_update,), name="site-updater")
        updater_thread.daemon = True
        updater_thread.start()

    # Wait for producer to finish
    producer_thread.join()

    # Wait for queue to drain
    video_queue.join()

    # Signal consumers to stop
    done_event.set()
    for _ in range(args.consumers):
        video_queue.put(None)

    # Wait for consumers
    for t in threads[1:]:  # Skip producer (already joined)
        t.join(timeout=5)

    elapsed = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"Pipeline complete!")
    print(f"  Success: {stats['success']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Time: {elapsed:.1f}s ({elapsed/len(to_process):.1f}s per video avg)")
    print(f"{'='*60}")

    # Final site regeneration
    if stats['success'] > 0:
        print("\nFinal site regeneration...")
        generate_site()
        print("Done!")


if __name__ == "__main__":
    main()
