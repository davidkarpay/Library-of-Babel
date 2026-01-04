#!/usr/bin/env python3
"""
sync_daily.py

Automated daily sync for HuggingFace papers.
Can be run via cron, GitHub Actions, or manually.

Usage:
    python sync_daily.py                    # Sync today's papers
    python sync_daily.py --date 2026-01-02  # Sync specific date
    python sync_daily.py --backfill 7       # Sync last 7 days
    python sync_daily.py --dry-run          # Preview without importing

This script:
1. Imports papers from HuggingFace daily papers
2. Regenerates the static site
3. Optionally commits and pushes changes
"""

import argparse
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Import local modules
from huggingface_papers import import_daily_papers
from library import generate_site

BASE_DIR = Path(__file__).parent


def sync_papers(
    date: str = None,
    backfill_days: int = 0,
    min_upvotes: int = 0,
    dry_run: bool = False
) -> dict:
    """
    Sync papers for given date(s).

    Args:
        date: Specific date to sync (YYYY-MM-DD)
        backfill_days: Number of days to backfill
        min_upvotes: Minimum upvotes filter
        dry_run: Preview without importing

    Returns:
        Dict with sync statistics
    """
    stats = {
        "dates_processed": 0,
        "papers_imported": 0,
        "papers_skipped": 0,
        "papers_failed": 0
    }

    # Determine dates to process
    dates = []
    if backfill_days > 0:
        for i in range(backfill_days):
            d = datetime.now() - timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d"))
    else:
        dates = [date or datetime.now().strftime("%Y-%m-%d")]

    print(f"Syncing papers for {len(dates)} date(s)...")

    for d in dates:
        print(f"\n--- Processing {d} ---")
        success, skipped, failed = import_daily_papers(
            date=d,
            min_upvotes=min_upvotes,
            dry_run=dry_run
        )

        stats["dates_processed"] += 1
        stats["papers_imported"] += success
        stats["papers_skipped"] += skipped
        stats["papers_failed"] += failed

    return stats


def main():
    parser = argparse.ArgumentParser(description="Daily paper sync")
    parser.add_argument("--date", help="Specific date to sync (YYYY-MM-DD)")
    parser.add_argument("--backfill", type=int, default=0,
                        help="Number of days to backfill")
    parser.add_argument("--min-upvotes", type=int, default=0,
                        help="Minimum upvotes filter")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without importing")
    parser.add_argument("--no-regenerate", action="store_true",
                        help="Skip site regeneration")
    parser.add_argument("--commit", action="store_true",
                        help="Commit changes to git")
    args = parser.parse_args()

    print("=" * 60)
    print("DAILY PAPER SYNC")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Sync papers
    stats = sync_papers(
        date=args.date,
        backfill_days=args.backfill,
        min_upvotes=args.min_upvotes,
        dry_run=args.dry_run
    )

    print("\n" + "=" * 60)
    print("SYNC SUMMARY")
    print("=" * 60)
    print(f"Dates processed: {stats['dates_processed']}")
    print(f"Papers imported: {stats['papers_imported']}")
    print(f"Papers skipped:  {stats['papers_skipped']}")
    print(f"Papers failed:   {stats['papers_failed']}")

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        return

    # Regenerate site
    if not args.no_regenerate and stats['papers_imported'] > 0:
        print("\n" + "=" * 60)
        print("REGENERATING SITE")
        print("=" * 60)
        generate_site()
        print("Site regenerated successfully.")

    # Commit changes
    if args.commit and stats['papers_imported'] > 0:
        print("\n" + "=" * 60)
        print("COMMITTING CHANGES")
        print("=" * 60)

        try:
            # Stage changes
            subprocess.run(
                ["git", "add", "metadata/", "papers/", "site/", "library.json"],
                cwd=BASE_DIR,
                check=True
            )

            # Commit
            commit_msg = f"Daily paper sync: {stats['papers_imported']} papers added"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=BASE_DIR,
                check=True
            )
            print(f"Committed: {commit_msg}")

        except subprocess.CalledProcessError as e:
            print(f"Git commit failed: {e}")

    print("\n" + "=" * 60)
    print("SYNC COMPLETE")
    print("=" * 60)

    # Exit with error if all papers failed
    if stats['papers_failed'] > 0 and stats['papers_imported'] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
