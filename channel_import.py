#!/usr/bin/env python3
"""
channel_import.py

Import all videos from a YouTube channel into the library.
Skips already-imported videos and handles failures gracefully.

Usage:
    python channel_import.py <channel_url>
    python channel_import.py https://www.youtube.com/@NateBJones
    python channel_import.py https://www.youtube.com/c/ChannelName
    python channel_import.py https://www.youtube.com/channel/UC...

Options:
    --limit N         Only process first N videos (default: all)
    --delay SECONDS   Delay between imports (default: 2.0)
    --dry-run         Show what would be imported without processing
    --oldest-first    Process oldest videos first (default: newest first)

Requires:
    pip install scrapetube
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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

PENDING_FILE = BASE_DIR / "pending.json"


def extract_channel_identifier(url: str) -> tuple:
    """
    Parse channel URL to extract identifier type and value.

    Returns: (channel_type, identifier) where type is 'username', 'custom', 'id', or 'url'

    Examples:
        https://www.youtube.com/@NateBJones -> ('username', 'NateBJones')
        https://www.youtube.com/c/ChannelName -> ('custom', 'ChannelName')
        https://www.youtube.com/channel/UCxxxx -> ('id', 'UCxxxx')
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')

    if path.startswith('@'):
        return ('username', path[1:].split('/')[0])
    elif path.startswith('c/'):
        return ('custom', path[2:].split('/')[0])
    elif path.startswith('channel/'):
        return ('id', path[8:].split('/')[0])
    elif path.startswith('user/'):
        return ('username', path[5:].split('/')[0])
    else:
        # Try to use the URL directly
        return ('url', url)


def fetch_channel_videos(channel_url: str, limit: int = None, oldest_first: bool = False) -> list:
    """
    Fetch video list from channel using scrapetube.

    Args:
        channel_url: YouTube channel URL
        limit: Max videos to fetch (None for all)
        oldest_first: If True, sort by oldest first

    Returns: List of video dicts with videoId, title, etc.
    """
    channel_type, identifier = extract_channel_identifier(channel_url)

    sort_by = "oldest" if oldest_first else "newest"

    try:
        if channel_type == 'username':
            videos = scrapetube.get_channel(channel_username=identifier, sort_by=sort_by)
        elif channel_type == 'id':
            videos = scrapetube.get_channel(channel_id=identifier, sort_by=sort_by)
        else:
            # Try with channel_url for custom URLs
            videos = scrapetube.get_channel(channel_url=channel_url, sort_by=sort_by)

        result = []
        for i, video in enumerate(videos):
            if limit and i >= limit:
                break
            result.append(video)
        return result

    except Exception as e:
        print(f"Error fetching channel videos: {e}")
        return []


def get_channel_info_from_video(video: dict) -> dict:
    """Extract channel info from a video dict returned by scrapetube."""
    try:
        owner_text = video.get('ownerText', {})
        runs = owner_text.get('runs', [{}])
        channel_name = runs[0].get('text', 'Unknown Channel') if runs else 'Unknown Channel'

        # Try to get channel ID from navigation endpoint
        channel_id = ""
        if runs:
            nav_endpoint = runs[0].get('navigationEndpoint', {})
            browse_endpoint = nav_endpoint.get('browseEndpoint', {})
            channel_id = browse_endpoint.get('browseId', '')

        return {
            'name': channel_name,
            'id': channel_id,
            'url': f"https://www.youtube.com/channel/{channel_id}" if channel_id else "",
            'slug': slugify_channel(channel_name)
        }
    except Exception:
        return {
            'name': 'Unknown Channel',
            'id': '',
            'url': '',
            'slug': 'unknown-channel'
        }


def get_video_title_from_scrape(video: dict) -> str:
    """Extract video title from scrapetube video dict."""
    try:
        title_obj = video.get('title', {})
        runs = title_obj.get('runs', [])
        if runs:
            return runs[0].get('text', 'Unknown')
        # Fallback to accessibility text
        return title_obj.get('accessibility', {}).get('accessibilityData', {}).get('label', 'Unknown')
    except Exception:
        return 'Unknown'


def process_channel_video(video_id: str, channel_info: dict) -> tuple:
    """
    Process a single video with channel metadata.

    Args:
        video_id: YouTube video ID
        channel_info: Dict with channel name, id, url, slug

    Returns: (success, message)
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
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

        return True, metadata["title"]
    except Exception as e:
        return False, str(e)


def add_channel_to_pending(video_id: str, url: str, error: str, channel_name: str):
    """Add failed video to pending.json with channel source info."""
    pending = load_pending()

    existing_ids = {item["video_id"] for item in pending["failed"]}
    if video_id in existing_ids:
        return

    pending["failed"].append({
        "url": url,
        "video_id": video_id,
        "error": error,
        "attempted_at": datetime.now().isoformat(),
        "source_channel": channel_name
    })
    save_pending(pending)


def main():
    parser = argparse.ArgumentParser(
        description='Import all videos from a YouTube channel'
    )
    parser.add_argument('channel_url', help='YouTube channel URL')
    parser.add_argument('--limit', type=int, help='Max videos to process')
    parser.add_argument('--delay', type=float, default=2.0,
                        help='Delay between imports in seconds (default: 2.0)')
    parser.add_argument('--dry-run', action='store_true',
                        help='List videos without importing')
    parser.add_argument('--oldest-first', action='store_true',
                        help='Process oldest videos first (default: newest first)')

    args = parser.parse_args()

    print(f"Fetching videos from {args.channel_url}...")

    videos = fetch_channel_videos(args.channel_url, args.limit, args.oldest_first)

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
        for i, video in enumerate(to_process, 1):
            title = get_video_title_from_scrape(video)
            print(f"  {i}. [{video.get('videoId')}] {title[:60]}...")
        return

    if not to_process:
        print("\nNothing new to import!")
        return

    # Process each video
    success = 0
    failed = 0

    print(f"\nStarting import with {args.delay}s delay between videos...\n")

    for i, video in enumerate(to_process, 1):
        video_id = video.get('videoId')
        title = get_video_title_from_scrape(video)

        print(f"[{i}/{len(to_process)}] {video_id}: {title[:50]}...")

        ok, msg = process_channel_video(video_id, channel_info)

        if ok:
            print(f"  -> Success: {msg}")
            success += 1
        else:
            print(f"  -> FAILED: {msg}")
            url = f"https://www.youtube.com/watch?v={video_id}"
            add_channel_to_pending(video_id, url, msg, channel_info['name'])
            failed += 1

        # Rate limiting between videos
        if i < len(to_process):
            time.sleep(args.delay)

    print(f"\n{'='*50}")
    print(f"Complete! Success: {success}, Failed: {failed}")

    if failed > 0:
        print(f"\nFailed videos logged to: {PENDING_FILE}")
        print("Use 'python manual_import.py <url>' to add transcripts manually")

    if success > 0:
        print("\nRegenerating site...")
        generate_site()
        print("Done!")


if __name__ == "__main__":
    main()
