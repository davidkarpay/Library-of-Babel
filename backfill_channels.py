#!/usr/bin/env python3
"""
backfill_channels.py

Update existing metadata files with channel information.
Fetches channel name/URL from YouTube oEmbed API for each video.

Usage:
    python backfill_channels.py
"""

import json
import time
from pathlib import Path

from youtube_transcript_to_md import fetch_channel_info

BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"


def main():
    json_files = list(METADATA_DIR.glob("*.json"))
    print(f"Found {len(json_files)} metadata files")

    updated = 0
    skipped = 0
    failed = 0

    for i, json_file in enumerate(json_files, 1):
        try:
            with open(json_file) as f:
                data = json.load(f)

            # Skip if already has valid channel info
            channel = data.get("channel")
            if channel and channel.get("name") and channel.get("name") != "Unknown Channel":
                print(f"[{i}/{len(json_files)}] {json_file.name} - Already has channel, skipping")
                skipped += 1
                continue

            video_id = data.get("id")
            if not video_id:
                print(f"[{i}/{len(json_files)}] {json_file.name} - No video ID, skipping")
                skipped += 1
                continue

            print(f"[{i}/{len(json_files)}] {json_file.name} - Fetching channel info...")
            channel_info = fetch_channel_info(video_id)

            if channel_info.get("name") == "Unknown Channel":
                print(f"  -> Could not fetch channel info")
                failed += 1
            else:
                data["channel"] = channel_info
                with open(json_file, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"  -> Updated: {channel_info['name']}")
                updated += 1

            # Small delay to avoid rate limiting
            time.sleep(0.5)

        except Exception as e:
            print(f"[{i}/{len(json_files)}] {json_file.name} - Error: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Complete! Updated: {updated}, Skipped: {skipped}, Failed: {failed}")


if __name__ == "__main__":
    main()
