#!/usr/bin/env python3
"""
youtube_history.py

Import videos from your YouTube watch history.
Uses YouTube Data API v3 with OAuth to access your history,
scores relevance using LLM, and queues approved videos for import.

Prerequisites:
    1. Create Google Cloud project at https://console.cloud.google.com/
    2. Enable YouTube Data API v3
    3. Create OAuth credentials (Desktop app)
    4. Download credentials.json to this directory

Usage:
    python youtube_history.py                    # Fetch and review history
    python youtube_history.py --limit 100        # Limit to 100 videos
    python youtube_history.py --min-score 7      # Higher relevance threshold
    python youtube_history.py --skip-scoring     # Skip LLM scoring, show all
    python youtube_history.py --auto-add         # Auto-add all relevant (no review)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Google API imports
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

from llm_client import LLMClient

# Paths
BASE_DIR = Path(__file__).parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKENS_FILE = BASE_DIR / "tokens.json"
QUEUE_FILE = BASE_DIR / "import_queue.json"
METADATA_DIR = BASE_DIR / "metadata"

# OAuth scopes
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

# Relevance scoring prompt
RELEVANCE_PROMPT = """You are analyzing a YouTube video for a learning library focused on:
- Artificial Intelligence & Machine Learning
- Programming & Software Development
- DevOps & Cloud Infrastructure
- Security & Cryptography
- Databases & Data Engineering
- Computer Science fundamentals

Video Title: {title}
Channel: {channel}
Description: {description}

Rate the educational relevance from 0-10:
- 0-3: Not relevant (entertainment, vlogs, music, unrelated content)
- 4-5: Tangentially related (general tech news, product reviews)
- 6-7: Relevant (programming tutorial, tech deep-dive)
- 8-10: Highly relevant (AI/ML focused, advanced CS topics)

Respond with ONLY this format:
SCORE: X
REASON: One sentence explanation"""


def authenticate():
    """Authenticate with YouTube Data API using OAuth."""
    creds = None

    # Check for existing tokens
    if TOKENS_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKENS_FILE), SCOPES)
        except Exception as e:
            print(f"Warning: Could not load tokens: {e}")

    # If no valid credentials, run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired credentials...")
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f"\nError: {CREDENTIALS_FILE} not found!")
                print("\nTo set up YouTube API access:")
                print("1. Go to https://console.cloud.google.com/")
                print("2. Create a project and enable YouTube Data API v3")
                print("3. Create OAuth credentials (Desktop app)")
                print("4. Download the JSON and save as 'credentials.json'")
                sys.exit(1)

            print("\nOpening browser for authentication...")
            print("Please log in with your YouTube/Google account.\n")

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open(TOKENS_FILE, "w") as f:
            f.write(creds.to_json())
        print("Credentials saved for future use.\n")

    return build("youtube", "v3", credentials=creds)


def get_watch_history(youtube, max_results=200):
    """Fetch videos from watch history."""
    print(f"Fetching up to {max_results} videos from watch history...")

    videos = []
    next_page_token = None

    # Note: YouTube API doesn't directly expose watch history.
    # We'll use the "liked videos" playlist or search through activities.
    # Actually, watch history requires special access - let's use activities API

    try:
        # Get the user's channel
        channels = youtube.channels().list(
            part="contentDetails",
            mine=True
        ).execute()

        if not channels.get("items"):
            print("Error: Could not access your YouTube channel.")
            return []

        # Try to get watch history through activities
        # Note: Activities API shows likes, uploads, comments, etc.
        # Watch history is actually not directly accessible via API for privacy

        # Alternative: Use liked videos as a proxy
        print("\nNote: YouTube API doesn't expose watch history directly for privacy.")
        print("Fetching your LIKED videos instead (videos you've thumbs-up'd).\n")

        liked_playlist_id = channels["items"][0]["contentDetails"]["relatedPlaylists"].get("likes")

        if not liked_playlist_id:
            print("Could not find liked videos playlist.")
            return []

        while len(videos) < max_results:
            request = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=liked_playlist_id,
                maxResults=min(50, max_results - len(videos)),
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                video_id = snippet.get("resourceId", {}).get("videoId")

                if video_id:
                    videos.append({
                        "id": video_id,
                        "title": snippet.get("title", "Unknown"),
                        "channel": snippet.get("videoOwnerChannelTitle", "Unknown"),
                        "description": snippet.get("description", "")[:500],
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "added_at": snippet.get("publishedAt", "")
                    })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        print(f"Found {len(videos)} liked videos.\n")
        return videos

    except Exception as e:
        print(f"Error fetching videos: {e}")
        return []


def get_existing_video_ids():
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


def score_relevance(video, llm):
    """Score a video's relevance using LLM."""
    prompt = RELEVANCE_PROMPT.format(
        title=video["title"],
        channel=video["channel"],
        description=video["description"][:300] if video["description"] else "No description"
    )

    response = llm.generate(prompt, timeout=30)

    # Parse score from response
    score = 0
    reason = ""

    if response:
        # Extract score
        score_match = re.search(r'SCORE:\s*(\d+)', response)
        if score_match:
            score = int(score_match.group(1))
            score = min(10, max(0, score))  # Clamp to 0-10

        # Extract reason
        reason_match = re.search(r'REASON:\s*(.+)', response)
        if reason_match:
            reason = reason_match.group(1).strip()

    return score, reason


def load_queue():
    """Load the import queue."""
    if QUEUE_FILE.exists():
        try:
            with open(QUEUE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"videos": [], "created": datetime.now().isoformat()}


def save_queue(queue):
    """Save the import queue."""
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def add_to_queue(video):
    """Add a video to the import queue."""
    queue = load_queue()

    # Check if already queued
    existing_ids = {v["id"] for v in queue["videos"]}
    if video["id"] in existing_ids:
        return False

    queue["videos"].append({
        "id": video["id"],
        "url": video["url"],
        "title": video["title"],
        "channel": video["channel"],
        "added": datetime.now().isoformat()
    })

    save_queue(queue)
    return True


def interactive_review(videos, existing_ids, auto_add=False):
    """Interactive CLI to review and approve videos."""
    queued = 0
    skipped = 0
    already_imported = 0

    print("\n" + "=" * 60)
    print("RELEVANT VIDEOS FOR REVIEW")
    print("=" * 60)

    for i, video in enumerate(videos, 1):
        # Skip if already in library
        if video["id"] in existing_ids:
            already_imported += 1
            continue

        score = video.get("score", 0)
        reason = video.get("reason", "")

        print(f"\n[{i}/{len(videos)}] Score: {score}/10")
        print(f"Title: {video['title']}")
        print(f"Channel: {video['channel']}")
        if reason:
            print(f"Reason: {reason}")
        print(f"URL: {video['url']}")

        if auto_add:
            if add_to_queue(video):
                queued += 1
                print("→ Auto-added to queue")
            continue

        # Interactive prompt
        while True:
            choice = input("\n[A]dd to queue / [S]kip / [V]iew description / [Q]uit? ").strip().lower()

            if choice == 'a':
                if add_to_queue(video):
                    queued += 1
                    print("✓ Added to import queue")
                else:
                    print("Already in queue")
                break
            elif choice == 's':
                skipped += 1
                print("→ Skipped")
                break
            elif choice == 'v':
                print(f"\nDescription:\n{video['description'][:500]}...")
            elif choice == 'q':
                print("\nQuitting review...")
                print(f"\nSummary: {queued} queued, {skipped} skipped, {already_imported} already imported")
                return queued
            else:
                print("Invalid choice. Enter A, S, V, or Q.")

    print("\n" + "=" * 60)
    print(f"Review complete!")
    print(f"  Queued for import: {queued}")
    print(f"  Skipped: {skipped}")
    print(f"  Already in library: {already_imported}")
    print("=" * 60)

    if queued > 0:
        print(f"\nRun 'python import_from_queue.py' to import queued videos.")

    return queued


def main():
    parser = argparse.ArgumentParser(description="Import from YouTube watch history")
    parser.add_argument("--limit", type=int, default=200, help="Max videos to fetch")
    parser.add_argument("--min-score", type=int, default=6, help="Minimum relevance score")
    parser.add_argument("--skip-scoring", action="store_true", help="Skip LLM scoring")
    parser.add_argument("--auto-add", action="store_true", help="Auto-add without review")
    args = parser.parse_args()

    print("=" * 60)
    print("YouTube History Import")
    print("=" * 60)

    # Authenticate
    youtube = authenticate()

    # Get videos
    videos = get_watch_history(youtube, args.limit)

    if not videos:
        print("No videos found.")
        return

    # Get existing library
    existing_ids = get_existing_video_ids()
    print(f"Current library has {len(existing_ids)} videos.")

    # Filter out already imported
    new_videos = [v for v in videos if v["id"] not in existing_ids]
    print(f"Found {len(new_videos)} new videos (not in library).\n")

    if not new_videos:
        print("All videos are already in your library!")
        return

    # Score relevance
    if not args.skip_scoring:
        print("Analyzing relevance with AI...")
        llm = LLMClient()

        if not llm.is_available():
            print("Warning: LLM not available. Skipping relevance scoring.")
            args.skip_scoring = True
        else:
            for i, video in enumerate(new_videos, 1):
                print(f"  [{i}/{len(new_videos)}] {video['title'][:50]}...", end=" ", flush=True)
                score, reason = score_relevance(video, llm)
                video["score"] = score
                video["reason"] = reason
                print(f"→ {score}/10")

            # Filter by score
            relevant = [v for v in new_videos if v.get("score", 0) >= args.min_score]
            print(f"\n{len(relevant)} videos scored >= {args.min_score}/10")
            new_videos = sorted(relevant, key=lambda x: x.get("score", 0), reverse=True)

    if not new_videos:
        print("No relevant videos found.")
        return

    # Review
    interactive_review(new_videos, existing_ids, args.auto_add)


if __name__ == "__main__":
    main()
