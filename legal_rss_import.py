#!/usr/bin/env python3
"""
legal_rss_import.py

Import legal news and analysis from RSS feeds into the learning library.
Designed for court news, legal blogs, and legal analysis from trusted sources.

Legal RSS Sources:
- SCOTUSblog: https://www.scotusblog.com/feed/
- Court News Florida: https://news.flcourts.gov/rss
- CourtListener: https://www.courtlistener.com/feed/court/scotus/

Usage:
    python legal_rss_import.py --feed <rss_url>              # Import from feed
    python legal_rss_import.py --feed <rss_url> --limit 5    # Import 5 items
    python legal_rss_import.py --all-sources                 # All configured feeds
    python legal_rss_import.py --list-sources                # Show configured feeds
    python legal_rss_import.py --dry-run                     # Preview only

Prerequisites:
    pip install feedparser trafilatura bleach defusedxml
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import bleach
import feedparser
import trafilatura

from llm_client import LLMClient

# Load .env file if present
ENV_FILE = Path(__file__).parent / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# Paths
BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
LEGAL_DIR = BASE_DIR / "legal"
LEGAL_CACHE_DIR = BASE_DIR / "legal_cache"
LEGAL_SOURCES_FILE = BASE_DIR / "trusted_legal_sources.json"

# Ensure directories exist
METADATA_DIR.mkdir(exist_ok=True)
LEGAL_DIR.mkdir(exist_ok=True)

# CourtListener API key (optional, but enables higher rate limits)
COURTLISTENER_API_KEY = os.environ.get("COURTLISTENER_API_KEY", "")

# Request settings
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Learning-Library-Bot/1.0"
}
REQUEST_DELAY = 2.0  # Be respectful to legal sites

# LLM Prompts for legal content
LEGAL_ANALYSIS_PROMPT = """Analyze this legal article/news item for a learning library.

Title: {title}
Source: {source_name}
Content: {content_excerpt}

Provide:
1. A concise summary (2-3 sentences) of the legal significance
2. 3-5 key points for legal practitioners or law students
3. Relevant legal topics/areas

Format your response EXACTLY as:
SUMMARY: <summary>
KEY_POINTS:
- <point 1>
- <point 2>
- <point 3>
LEGAL_TOPICS: <comma-separated list from: constitutional, criminal, civil-procedure,
              evidence, ethics, contracts, torts, property, administrative,
              employment, intellectual-property, immigration, environmental, other>"""

LEGAL_FACETS_PROMPT = """Categorize this legal content.

Title: {title}
Excerpt: {excerpt}

Choose format from: legal-analysis, court-news, opinion-summary, legal-guide, case-study, other
Choose difficulty from: beginner (accessible to non-lawyers), intermediate (law students),
                        advanced (practicing attorneys)

Format your response EXACTLY as:
FORMAT: <format>
DIFFICULTY: <difficulty>"""


def load_legal_sources() -> dict:
    """Load configured legal RSS sources."""
    if not LEGAL_SOURCES_FILE.exists():
        return {"legal_feeds": []}

    try:
        with open(LEGAL_SOURCES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading legal sources: {e}")
        return {"legal_feeds": []}


def is_safe_url(url: str) -> bool:
    """Validate URL is safe (not internal/localhost)."""
    parsed = urlparse(url)

    if parsed.scheme not in ('http', 'https'):
        return False

    hostname = parsed.hostname or ""
    if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return False

    if hostname.startswith(('10.', '172.16.', '192.168.')):
        return False

    return True


def safe_slug(text: str) -> str:
    """Create URL-safe slug with path traversal protection."""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')

    if '..' in slug or '/' in slug:
        slug = slug.replace('..', '').replace('/', '')

    return slug[:80] if slug else "untitled"


def generate_legal_id(url: str) -> str:
    """Generate unique ID from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def parse_legal_rss_feed(feed_url: str) -> dict:
    """
    Parse legal RSS feed and extract articles.

    Returns:
        Dict with 'source' info and 'articles' list
    """
    print(f"Fetching RSS feed: {feed_url}")

    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        print(f"Error parsing RSS feed: {feed.bozo_exception}")
        return {}

    # Extract source-level metadata
    source = {
        "name": feed.feed.get("title", "Unknown Source"),
        "description": feed.feed.get("description", ""),
        "url": feed.feed.get("link", ""),
        "feed_url": feed_url,
        "slug": safe_slug(feed.feed.get("title", "unknown-source"))
    }

    # Extract articles
    articles = []
    for entry in feed.entries:
        article = {
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "description": entry.get("summary", entry.get("description", "")),
            "published_date": "",
            "author": entry.get("author", ""),
            "categories": []
        }

        # Parse published date
        if entry.get("published_parsed"):
            try:
                dt = datetime(*entry.published_parsed[:6])
                article["published_date"] = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        # Extract categories/tags
        for tag in entry.get("tags", []):
            if tag.get("term"):
                article["categories"].append(tag["term"])

        if article["url"]:
            articles.append(article)

    print(f"Found {len(articles)} articles in feed")
    return {"source": source, "articles": articles}


def extract_legal_content(url: str) -> dict:
    """
    Extract article content using trafilatura.

    Returns:
        Dict with: title, content, author, published_date, word_count
    """
    print(f"  Fetching content from: {url}")

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            print("  Error: Could not download page")
            return {}

        content = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True
        )

        if not content:
            print("  Error: Could not extract content")
            return {}

        metadata = trafilatura.extract_metadata(downloaded)

        result = {
            "content": content,
            "title": "",
            "author": "",
            "published_date": "",
            "word_count": len(content.split())
        }

        if metadata:
            result["title"] = metadata.title or ""
            result["author"] = metadata.author or ""
            if metadata.date:
                result["published_date"] = metadata.date

        # Sanitize content
        result["content"] = bleach.clean(content, tags=[], strip=True)

        print(f"  Extracted {result['word_count']} words")
        return result

    except Exception as e:
        print(f"  Error extracting content: {e}")
        return {}


def analyze_legal_content(title: str, content: str, source_name: str, llm: LLMClient) -> dict:
    """
    Analyze legal content with LLM.

    Returns:
        Dict with: summary, key_points, legal_topics, format, difficulty
    """
    result = {
        "summary": [],
        "legal_topics": ["other"],
        "format": "legal-analysis",
        "difficulty": "intermediate"
    }

    if not llm.is_available():
        print("  Warning: LLM not available. Using default metadata.")
        return result

    # Get summary and key points
    print("  Analyzing legal content...")
    analysis_prompt = LEGAL_ANALYSIS_PROMPT.format(
        title=title,
        source_name=source_name,
        content_excerpt=content[:3000]
    )

    analysis_response = llm.generate(analysis_prompt, timeout=60)

    if analysis_response:
        # Parse summary
        summary_match = re.search(r"SUMMARY:\s*(.+?)(?=KEY_POINTS:|$)", analysis_response, re.DOTALL)
        if summary_match:
            summary_text = summary_match.group(1).strip()
            result["summary"] = [summary_text]

        # Parse key points
        points_match = re.search(r"KEY_POINTS:\s*(.+?)(?=LEGAL_TOPICS:|$)", analysis_response, re.DOTALL)
        if points_match:
            points_text = points_match.group(1)
            points = re.findall(r"-\s*(.+?)(?=\n-|\n\n|$)", points_text, re.DOTALL)
            if points:
                result["summary"].extend([p.strip() for p in points if p.strip()])

        # Parse legal topics
        topics_match = re.search(r"LEGAL_TOPICS:\s*(.+?)(?:\n|$)", analysis_response)
        if topics_match:
            topics_text = topics_match.group(1).strip()
            topics = [t.strip().lower() for t in topics_text.split(",")]
            result["legal_topics"] = [t for t in topics if t and t != "other"][:3]
            if not result["legal_topics"]:
                result["legal_topics"] = ["other"]

    # Get facets
    print("  Categorizing content...")
    facets_prompt = LEGAL_FACETS_PROMPT.format(
        title=title,
        excerpt=content[:1500]
    )

    facets_response = llm.generate(facets_prompt, timeout=30)

    if facets_response:
        format_match = re.search(r"FORMAT:\s*(\S+)", facets_response)
        if format_match:
            result["format"] = format_match.group(1).lower().strip()

        diff_match = re.search(r"DIFFICULTY:\s*(\S+)", facets_response)
        if diff_match:
            result["difficulty"] = diff_match.group(1).lower().strip()

    return result


def get_existing_legal_ids() -> set:
    """Get set of legal article IDs already in the library."""
    ids = set()
    for json_file in METADATA_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                if data.get("content_type") == "legal":
                    ids.add(data.get("id"))
        except Exception:
            pass
    return ids


def save_legal_article(article: dict, extracted: dict, analysis: dict, source_info: dict) -> tuple:
    """
    Save legal article metadata and markdown.

    Returns:
        Tuple of (metadata_path, markdown_path)
    """
    article_id = generate_legal_id(article["url"])
    title = extracted.get("title") or article.get("title", "Untitled")
    slug = safe_slug(title)

    # Build metadata
    metadata = {
        "id": article_id,
        "content_type": "legal",
        "domain": "law",  # Domain separation: law vs computer-science
        "title": title,
        "url": article["url"],
        "source": {
            "name": source_info.get("name", "Unknown"),
            "feed_url": source_info.get("feed_url", ""),
            "source_type": source_info.get("source_type", "legal_analysis")
        },
        "jurisdiction": source_info.get("jurisdiction", ""),
        "author": extracted.get("author") or article.get("author", ""),
        "published_date": extracted.get("published_date") or article.get("published_date", ""),
        "added_date": datetime.now().strftime("%Y-%m-%d"),
        "word_count": extracted.get("word_count", 0),
        "facets": {
            "topics": ["legal"],
            "format": analysis.get("format", "legal-analysis"),
            "difficulty": analysis.get("difficulty", "intermediate")
        },
        "legal_topics": analysis.get("legal_topics", ["other"]),
        "summary": analysis.get("summary", []),
        "sections": [],
        "license": "See original source",
        "attribution": f"Via {source_info.get('name', 'RSS Feed')}"
    }

    # Save metadata JSON
    metadata_path = METADATA_DIR / f"{slug}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Build markdown
    md_lines = [
        f"# {metadata['title']}",
        "",
        f"**Source:** [{metadata['source']['name']}]({metadata['url']})",
        ""
    ]

    if metadata.get("author"):
        md_lines.extend([f"**Author:** {metadata['author']}", ""])

    if metadata.get("published_date"):
        md_lines.extend([f"**Published:** {metadata['published_date']}", ""])

    if metadata.get("jurisdiction"):
        md_lines.extend([f"**Jurisdiction:** {metadata['jurisdiction']}", ""])

    # Summary
    if metadata.get("summary"):
        md_lines.extend(["## Summary", ""])
        for point in metadata["summary"]:
            md_lines.append(f"- {point}")
        md_lines.append("")

    # Content excerpt
    content = extracted.get("content", "")
    if content:
        md_lines.extend([
            "## Content",
            "",
            content[:5000] + ("..." if len(content) > 5000 else ""),
            ""
        ])

    # Metadata footer
    md_lines.extend([
        "---",
        "",
        f"*Legal Topics: {', '.join(metadata['legal_topics'])}*",
        f"*Difficulty: {metadata['facets']['difficulty']}*",
        f"*{metadata['attribution']}*"
    ])

    # Save markdown
    markdown_path = LEGAL_DIR / f"{slug}.md"
    with open(markdown_path, "w") as f:
        f.write("\n".join(md_lines))

    return metadata_path, markdown_path


def import_legal_article(article: dict, source_info: dict, llm: LLMClient) -> bool:
    """
    Full import pipeline for a single legal article.

    Returns:
        True if successful, False otherwise
    """
    url = article.get("url", "")
    if not url or not is_safe_url(url):
        print(f"  Skipping invalid URL: {url}")
        return False

    # For CourtListener, use RSS content directly (web scraping returns HTTP 202)
    # CourtListener uses CloudFront CDN which blocks/delays scraping requests
    # The RSS feed already contains complete opinion content in the description field
    if "courtlistener.com" in url:
        print("  Using RSS content directly (CourtListener)")
        extracted = {
            "content": article.get("description", ""),
            "title": article.get("title", ""),
            "author": article.get("author", ""),
            "published_date": article.get("published_date", ""),
            "word_count": len(article.get("description", "").split())
        }
    else:
        # For other sources, try web scraping first
        extracted = extract_legal_content(url)
        if not extracted.get("content"):
            # Use description from RSS as fallback
            extracted = {
                "content": article.get("description", ""),
                "title": article.get("title", ""),
                "author": article.get("author", ""),
                "published_date": article.get("published_date", ""),
                "word_count": len(article.get("description", "").split())
            }

    if not extracted.get("content") or extracted.get("word_count", 0) < 50:
        print("  Skipping: Insufficient content")
        return False

    # Analyze content
    title = extracted.get("title") or article.get("title", "Untitled")
    analysis = analyze_legal_content(
        title=title,
        content=extracted["content"],
        source_name=source_info.get("name", "Unknown"),
        llm=llm
    )

    # Save
    metadata_path, markdown_path = save_legal_article(article, extracted, analysis, source_info)
    print(f"  Saved: {metadata_path.name}")

    return True


def sync_legal_feed(
    feed_url: str,
    source_info: dict = None,
    limit: int = 10,
    dry_run: bool = False
) -> dict:
    """
    Sync legal content from a single RSS feed.

    Returns:
        Dict with: imported, skipped, failed counts
    """
    stats = {"imported": 0, "skipped": 0, "failed": 0}

    # Parse feed
    feed_data = parse_legal_rss_feed(feed_url)
    if not feed_data:
        return stats

    source = source_info or feed_data.get("source", {})
    source["feed_url"] = feed_url

    articles = feed_data.get("articles", [])[:limit]

    if not articles:
        print("No articles found in feed.")
        return stats

    # Get existing IDs
    existing_ids = get_existing_legal_ids()
    print(f"Already in library: {len(existing_ids)} legal items")

    # Filter new articles
    new_articles = []
    for article in articles:
        article_id = generate_legal_id(article["url"])
        if article_id not in existing_ids:
            new_articles.append(article)
        else:
            stats["skipped"] += 1

    print(f"New articles to import: {len(new_articles)}")

    if dry_run:
        print("\nDRY RUN - Articles that would be imported:")
        for i, article in enumerate(new_articles, 1):
            print(f"  [{i}] {article['title'][:60]}...")
            print(f"      URL: {article['url'][:70]}...")
        return {"imported": len(new_articles), "skipped": stats["skipped"], "failed": 0}

    if not new_articles:
        return stats

    # Initialize LLM
    llm = LLMClient()

    # Import articles
    for i, article in enumerate(new_articles, 1):
        print(f"\n[{i}/{len(new_articles)}] {article['title'][:50]}...")

        try:
            success = import_legal_article(article, source, llm)
            if success:
                stats["imported"] += 1
            else:
                stats["failed"] += 1
        except Exception as e:
            print(f"  Error: {e}")
            stats["failed"] += 1

        # Rate limiting
        if i < len(new_articles):
            time.sleep(REQUEST_DELAY)

    return stats


def sync_legal_feeds(
    feeds: list = None,
    limit: int = 10,
    dry_run: bool = False
) -> dict:
    """
    Sync legal content from multiple RSS feeds.

    Args:
        feeds: List of feed URLs (or None to use all configured feeds)
        limit: Max items per feed
        dry_run: Preview without importing

    Returns:
        Dict with aggregate stats
    """
    sources_config = load_legal_sources()
    configured_feeds = sources_config.get("legal_feeds", [])

    if not feeds:
        # Use all configured feeds
        feeds_to_sync = configured_feeds
    else:
        # Match provided URLs to configured feeds (or use directly)
        feeds_to_sync = []
        for url in feeds:
            matched = False
            for feed in configured_feeds:
                if feed.get("feed_url") == url:
                    feeds_to_sync.append(feed)
                    matched = True
                    break
            if not matched:
                feeds_to_sync.append({"feed_url": url, "name": "Unknown Feed"})

    if not feeds_to_sync:
        print("No feeds to sync. Configure feeds in trusted_legal_sources.json")
        return {"imported": 0, "skipped": 0, "failed": 0, "feeds_processed": 0}

    print(f"\n{'='*60}")
    print("LEGAL RSS SYNC")
    print(f"{'='*60}")
    print(f"Feeds to sync: {len(feeds_to_sync)}")

    total_stats = {"imported": 0, "skipped": 0, "failed": 0, "feeds_processed": 0}

    for feed_info in feeds_to_sync:
        feed_url = feed_info.get("feed_url")
        if not feed_url:
            continue

        print(f"\n--- {feed_info.get('name', 'Unknown')} ---")

        stats = sync_legal_feed(
            feed_url=feed_url,
            source_info=feed_info,
            limit=limit,
            dry_run=dry_run
        )

        total_stats["imported"] += stats.get("imported", 0)
        total_stats["skipped"] += stats.get("skipped", 0)
        total_stats["failed"] += stats.get("failed", 0)
        total_stats["feeds_processed"] += 1

        # Delay between feeds
        time.sleep(REQUEST_DELAY)

    print(f"\n{'='*60}")
    print("LEGAL SYNC SUMMARY")
    print(f"{'='*60}")
    print(f"Feeds processed: {total_stats['feeds_processed']}")
    print(f"Articles imported: {total_stats['imported']}")
    print(f"Articles skipped: {total_stats['skipped']}")
    print(f"Articles failed: {total_stats['failed']}")

    return total_stats


def list_sources():
    """Display configured legal RSS sources."""
    sources = load_legal_sources()

    print(f"\n{'='*60}")
    print("CONFIGURED LEGAL RSS SOURCES")
    print(f"{'='*60}")

    feeds = sources.get("legal_feeds", [])
    if not feeds:
        print("\nNo feeds configured. Add feeds to trusted_legal_sources.json")
        return

    for feed in feeds:
        print(f"\n{feed.get('name', 'Unknown')}")
        print(f"  URL: {feed.get('feed_url', 'N/A')}")
        print(f"  Type: {feed.get('source_type', 'N/A')}")
        print(f"  Jurisdiction: {feed.get('jurisdiction', 'N/A')}")

    print(f"\nTotal: {len(feeds)} feeds configured")


def main():
    parser = argparse.ArgumentParser(
        description="Import legal content from RSS feeds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python legal_rss_import.py --feed https://www.scotusblog.com/feed/
    python legal_rss_import.py --all-sources --limit 5
    python legal_rss_import.py --list-sources
    python legal_rss_import.py --all-sources --dry-run
        """
    )
    parser.add_argument("--feed", help="Single RSS feed URL to import")
    parser.add_argument("--all-sources", action="store_true",
                        help="Import from all configured sources")
    parser.add_argument("--list-sources", action="store_true",
                        help="List configured legal sources")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max articles per feed (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without importing")
    args = parser.parse_args()

    if args.list_sources:
        list_sources()
        return

    if args.all_sources:
        stats = sync_legal_feeds(
            feeds=None,
            limit=args.limit,
            dry_run=args.dry_run
        )
    elif args.feed:
        if not is_safe_url(args.feed):
            print("Error: Invalid feed URL")
            sys.exit(1)

        stats = sync_legal_feeds(
            feeds=[args.feed],
            limit=args.limit,
            dry_run=args.dry_run
        )
    else:
        parser.print_help()
        sys.exit(1)

    if stats.get("failed", 0) > 0 and stats.get("imported", 0) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
