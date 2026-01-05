#!/usr/bin/env python3
"""
sync_daily.py

Automated daily sync for papers from HuggingFace and/or arXiv.
Can be run via cron, GitHub Actions, or manually.

Usage:
    python sync_daily.py                              # Sync HuggingFace papers (default)
    python sync_daily.py --source huggingface         # Explicit HuggingFace only
    python sync_daily.py --source arxiv               # arXiv only
    python sync_daily.py --source huggingface arxiv   # Both sources
    python sync_daily.py --arxiv-categories cs.AI cs.LG  # Specify arXiv categories
    python sync_daily.py --date 2026-01-02            # Sync specific date
    python sync_daily.py --backfill 7                 # Sync last 7 days
    python sync_daily.py --dry-run                    # Preview without importing

This script:
1. Imports papers from HuggingFace and/or arXiv
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
from arxiv_papers import import_by_category as import_arxiv_papers
from library import generate_site

BASE_DIR = Path(__file__).parent

# Default arXiv categories for sync
DEFAULT_ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]


def sync_huggingface(
    date: str = None,
    backfill_days: int = 0,
    min_upvotes: int = 0,
    dry_run: bool = False
) -> dict:
    """
    Sync papers from HuggingFace for given date(s).

    Args:
        date: Specific date to sync (YYYY-MM-DD)
        backfill_days: Number of days to backfill
        min_upvotes: Minimum upvotes filter
        dry_run: Preview without importing

    Returns:
        Dict with sync statistics
    """
    stats = {
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

    print(f"\n{'='*60}")
    print("HUGGINGFACE PAPERS SYNC")
    print(f"{'='*60}")
    print(f"Syncing HuggingFace papers for {len(dates)} date(s)...")

    for d in dates:
        print(f"\n--- Processing {d} ---")
        success, skipped, failed = import_daily_papers(
            date=d,
            min_upvotes=min_upvotes,
            dry_run=dry_run
        )

        stats["papers_imported"] += success
        stats["papers_skipped"] += skipped
        stats["papers_failed"] += failed

    return stats


def sync_arxiv(
    categories: list = None,
    days: int = 1,
    limit: int = 50,
    dry_run: bool = False
) -> dict:
    """
    Sync papers from arXiv for given categories.

    Args:
        categories: arXiv categories to sync
        days: Days back to look
        limit: Max papers per category
        dry_run: Preview without importing

    Returns:
        Dict with sync statistics
    """
    categories = categories or DEFAULT_ARXIV_CATEGORIES

    print(f"\n{'='*60}")
    print("ARXIV PAPERS SYNC")
    print(f"{'='*60}")
    print(f"Categories: {', '.join(categories)}")
    print(f"Days back: {days}")

    success, skipped, failed = import_arxiv_papers(
        categories=categories,
        days=days,
        limit=limit,
        full_text=False,
        dry_run=dry_run
    )

    return {
        "papers_imported": success,
        "papers_skipped": skipped,
        "papers_failed": failed
    }


def sync_papers(
    sources: list = None,
    date: str = None,
    backfill_days: int = 0,
    min_upvotes: int = 0,
    arxiv_categories: list = None,
    arxiv_limit: int = 50,
    dry_run: bool = False
) -> dict:
    """
    Sync papers from specified sources.

    Args:
        sources: List of sources ["huggingface", "arxiv"]. Defaults to ["huggingface"]
        date: Specific date to sync (YYYY-MM-DD)
        backfill_days: Number of days to backfill
        min_upvotes: Minimum upvotes filter (HuggingFace only)
        arxiv_categories: arXiv categories to sync
        arxiv_limit: Max papers from arXiv
        dry_run: Preview without importing

    Returns:
        Dict with sync statistics
    """
    sources = sources or ["huggingface"]
    days = backfill_days if backfill_days > 0 else 1

    stats = {
        "sources_processed": [],
        "papers_imported": 0,
        "papers_skipped": 0,
        "papers_failed": 0
    }

    # Sync HuggingFace
    if "huggingface" in sources:
        hf_stats = sync_huggingface(
            date=date,
            backfill_days=backfill_days,
            min_upvotes=min_upvotes,
            dry_run=dry_run
        )
        stats["sources_processed"].append("huggingface")
        stats["papers_imported"] += hf_stats["papers_imported"]
        stats["papers_skipped"] += hf_stats["papers_skipped"]
        stats["papers_failed"] += hf_stats["papers_failed"]

    # Sync arXiv
    if "arxiv" in sources:
        arxiv_stats = sync_arxiv(
            categories=arxiv_categories,
            days=days,
            limit=arxiv_limit,
            dry_run=dry_run
        )
        stats["sources_processed"].append("arxiv")
        stats["papers_imported"] += arxiv_stats["papers_imported"]
        stats["papers_skipped"] += arxiv_stats["papers_skipped"]
        stats["papers_failed"] += arxiv_stats["papers_failed"]

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Daily paper sync from HuggingFace and/or arXiv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python sync_daily.py                              # HuggingFace only (default)
    python sync_daily.py --source huggingface         # Explicit HuggingFace
    python sync_daily.py --source arxiv               # arXiv only
    python sync_daily.py --source huggingface arxiv   # Both sources
    python sync_daily.py --arxiv-categories cs.AI cs.LG  # Custom arXiv categories
        """
    )
    parser.add_argument("--source", nargs="+", default=["huggingface"],
                        choices=["huggingface", "arxiv"],
                        help="Source(s) to sync from (default: huggingface)")
    parser.add_argument("--date", help="Specific date to sync (YYYY-MM-DD)")
    parser.add_argument("--backfill", type=int, default=0,
                        help="Number of days to backfill")
    parser.add_argument("--min-upvotes", type=int, default=0,
                        help="Minimum upvotes filter (HuggingFace only)")
    parser.add_argument("--arxiv-categories", nargs="+",
                        default=DEFAULT_ARXIV_CATEGORIES,
                        help=f"arXiv categories to sync (default: {' '.join(DEFAULT_ARXIV_CATEGORIES)})")
    parser.add_argument("--arxiv-limit", type=int, default=50,
                        help="Max papers from arXiv (default: 50)")
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
    print(f"Sources: {', '.join(args.source)}")
    print()

    # Sync papers
    stats = sync_papers(
        sources=args.source,
        date=args.date,
        backfill_days=args.backfill,
        min_upvotes=args.min_upvotes,
        arxiv_categories=args.arxiv_categories,
        arxiv_limit=args.arxiv_limit,
        dry_run=args.dry_run
    )

    print("\n" + "=" * 60)
    print("SYNC SUMMARY")
    print("=" * 60)
    print(f"Sources synced:  {', '.join(stats['sources_processed'])}")
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
