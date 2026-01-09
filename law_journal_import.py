#!/usr/bin/env python3
"""
law_journal_import.py

Import law school journal articles from RSS feeds into the learning library.
Focuses on criminal law, critical race theory, abolitionism, criminal procedure,
and indigent defense from top-tier law schools.

Usage:
    python law_journal_import.py --feed <rss_url>              # Import from feed
    python law_journal_import.py --feed <rss_url> --limit 5    # Import 5 items
    python law_journal_import.py --all-sources                 # All configured feeds
    python law_journal_import.py --list-sources                # Show configured feeds
    python law_journal_import.py --dry-run                     # Preview only

Prerequisites:
    pip install feedparser trafilatura bleach defusedxml
"""

import argparse
import hashlib
import json
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

# Paths
BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
JOURNALS_DIR = BASE_DIR / "journals"
JOURNAL_SOURCES_FILE = BASE_DIR / "trusted_journal_sources.json"

# Ensure directories exist
METADATA_DIR.mkdir(exist_ok=True)
JOURNALS_DIR.mkdir(exist_ok=True)

# Request settings
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Learning-Library-Bot/1.0"
}
REQUEST_DELAY = 2.0

# LLM Prompts for law journal content
JOURNAL_ANALYSIS_PROMPT = """Analyze this law journal article for a learning library focused on
criminal law, critical race theory, abolitionism, criminal procedure, and indigent defense.

Title: {title}
Journal: {journal_name}
Content: {content_excerpt}

Provide:
1. A concise summary (2-3 sentences) of the article's thesis and contribution
2. 3-5 key arguments or findings
3. Relevant legal topics from this list

Format your response EXACTLY as:
SUMMARY: <summary>
KEY_POINTS:
- <point 1>
- <point 2>
- <point 3>
LEGAL_TOPICS: <comma-separated list from: criminal-law, criminal-procedure, critical-race-theory,
              abolitionism, indigent-defense, mass-incarceration, constitutional, evidence,
              civil-rights, policing, sentencing, other>"""

JOURNAL_FACETS_PROMPT = """Categorize this law journal article.

Title: {title}
Excerpt: {excerpt}

Choose format from: law-review-article, case-note, essay, book-review, symposium, other
Choose difficulty from: intermediate (law students), advanced (practitioners/scholars)

Format your response EXACTLY as:
FORMAT: <format>
DIFFICULTY: <difficulty>"""


def load_journal_sources() -> dict:
    """Load configured journal RSS sources."""
    if not JOURNAL_SOURCES_FILE.exists():
        return {"journal_feeds": []}

    try:
        with open(JOURNAL_SOURCES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading journal sources: {e}")
        return {"journal_feeds": []}


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


def generate_journal_id(url: str) -> str:
    """Generate unique ID from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def parse_journal_rss_feed(feed_url: str) -> dict:
    """
    Parse journal RSS feed and extract articles.

    Returns:
        Dict with 'journal' info and 'articles' list
    """
    print(f"Fetching RSS feed: {feed_url}")

    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        print(f"Error parsing RSS feed: {feed.bozo_exception}")
        return {}

    # Extract journal-level metadata
    journal = {
        "name": feed.feed.get("title", "Unknown Journal"),
        "description": feed.feed.get("description", ""),
        "url": feed.feed.get("link", ""),
        "feed_url": feed_url,
        "slug": safe_slug(feed.feed.get("title", "unknown-journal"))
    }

    # Extract articles
    articles = []
    for entry in feed.entries:
        article = {
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "description": entry.get("summary", entry.get("description", "")),
            "published_date": "",
            "authors": [],
            "categories": []
        }

        # Parse published date
        if entry.get("published_parsed"):
            try:
                dt = datetime(*entry.published_parsed[:6])
                article["published_date"] = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        # Extract authors
        if entry.get("author"):
            article["authors"] = [{"name": entry.get("author")}]
        elif entry.get("authors"):
            article["authors"] = [{"name": a.get("name", "")} for a in entry.get("authors", [])]

        # Extract categories/tags
        for tag in entry.get("tags", []):
            if tag.get("term"):
                article["categories"].append(tag["term"])

        if article["url"]:
            articles.append(article)

    print(f"Found {len(articles)} articles in feed")
    return {"journal": journal, "articles": articles}


def extract_journal_content(url: str) -> dict:
    """
    Extract article content using trafilatura.

    Returns:
        Dict with: title, content, authors, published_date, word_count, abstract
    """
    print(f"  Fetching content from: {url}")

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            print("  Warning: Could not download page")
            return {}

        content = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True
        )

        if not content:
            print("  Warning: Could not extract content")
            return {}

        metadata = trafilatura.extract_metadata(downloaded)

        result = {
            "content": content,
            "title": "",
            "authors": [],
            "published_date": "",
            "word_count": len(content.split()),
            "abstract": ""
        }

        if metadata:
            result["title"] = metadata.title or ""
            if metadata.author:
                result["authors"] = [{"name": metadata.author}]
            if metadata.date:
                result["published_date"] = metadata.date
            if metadata.description:
                result["abstract"] = metadata.description

        # Sanitize content
        result["content"] = bleach.clean(content, tags=[], strip=True)

        print(f"  Extracted {result['word_count']} words")
        return result

    except Exception as e:
        print(f"  Error extracting content: {e}")
        return {}


def analyze_journal_content(title: str, content: str, journal_name: str, llm: LLMClient) -> dict:
    """
    Analyze journal content with LLM.

    Returns:
        Dict with: summary, key_points, legal_topics, format, difficulty
    """
    result = {
        "summary": [],
        "legal_topics": ["other"],
        "format": "law-review-article",
        "difficulty": "advanced"
    }

    if not llm.is_available():
        print("  Warning: LLM not available. Using default metadata.")
        return result

    # Get summary and key points
    print("  Analyzing journal article...")
    analysis_prompt = JOURNAL_ANALYSIS_PROMPT.format(
        title=title,
        journal_name=journal_name,
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
            result["legal_topics"] = [t for t in topics if t and t != "other"][:5]
            if not result["legal_topics"]:
                result["legal_topics"] = ["other"]

    # Get facets
    print("  Categorizing article...")
    facets_prompt = JOURNAL_FACETS_PROMPT.format(
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


def get_existing_journal_ids() -> set:
    """Get set of journal article IDs already in the library."""
    ids = set()
    for json_file in METADATA_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                if data.get("content_type") == "law-journal":
                    ids.add(data.get("id"))
        except Exception:
            pass
    return ids


def save_journal_article(article: dict, extracted: dict, analysis: dict, journal_info: dict, source_info: dict) -> tuple:
    """
    Save journal article metadata and markdown.

    Returns:
        Tuple of (metadata_path, markdown_path)
    """
    article_id = generate_journal_id(article["url"])
    title = extracted.get("title") or article.get("title", "Untitled")
    slug = safe_slug(title)

    # Merge authors from extraction and RSS
    authors = extracted.get("authors") or article.get("authors", [])
    if not authors:
        authors = [{"name": "Unknown"}]

    # Build metadata
    metadata = {
        "id": article_id,
        "content_type": "law-journal",
        "domain": "law",  # Domain separation: law vs computer-science
        "title": title,
        "url": article["url"],
        "journal": {
            "name": journal_info.get("name", "Unknown Journal"),
            "slug": journal_info.get("slug", "unknown-journal"),
            "url": journal_info.get("url", ""),
            "institution": source_info.get("institution", "")
        },
        "authors": authors,
        "published_date": extracted.get("published_date") or article.get("published_date", ""),
        "added_date": datetime.now().strftime("%Y-%m-%d"),
        "abstract": extracted.get("abstract", ""),
        "word_count": extracted.get("word_count", 0),
        "facets": {
            "topics": ["legal"],
            "format": analysis.get("format", "law-review-article"),
            "difficulty": analysis.get("difficulty", "advanced")
        },
        "legal_topics": analysis.get("legal_topics", ["other"]),
        "summary": analysis.get("summary", []),
        "sections": [],
        "access_type": source_info.get("access_type", "open"),
        "source_database": "rss",
        "license": "See original source",
        "attribution": f"Via {journal_info.get('name', 'RSS Feed')}"
    }

    # Save metadata JSON
    metadata_path = METADATA_DIR / f"{slug}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Build markdown
    md_lines = [
        f"# {metadata['title']}",
        "",
        f"**Journal:** [{metadata['journal']['name']}]({metadata['journal']['url']})",
        ""
    ]

    # Authors
    author_names = [a.get("name", "") for a in metadata.get("authors", []) if a.get("name")]
    if author_names:
        md_lines.extend([f"**Authors:** {', '.join(author_names)}", ""])

    if metadata.get("published_date"):
        md_lines.extend([f"**Published:** {metadata['published_date']}", ""])

    if metadata.get("journal", {}).get("institution"):
        md_lines.extend([f"**Institution:** {metadata['journal']['institution']}", ""])

    # Abstract
    if metadata.get("abstract"):
        md_lines.extend([
            "## Abstract",
            "",
            metadata["abstract"],
            ""
        ])

    # Summary
    if metadata.get("summary"):
        md_lines.extend(["## Key Points", ""])
        for point in metadata["summary"]:
            md_lines.append(f"- {point}")
        md_lines.append("")

    # Content excerpt
    content = extracted.get("content", "")
    if content:
        md_lines.extend([
            "## Article Excerpt",
            "",
            content[:5000] + ("..." if len(content) > 5000 else ""),
            ""
        ])

    # Metadata footer
    md_lines.extend([
        "---",
        "",
        f"*Legal Topics: {', '.join(metadata['legal_topics'])}*",
        f"*Format: {metadata['facets']['format']}*",
        f"*Difficulty: {metadata['facets']['difficulty']}*",
        f"*{metadata['attribution']}*"
    ])

    # Save markdown
    markdown_path = JOURNALS_DIR / f"{slug}.md"
    with open(markdown_path, "w") as f:
        f.write("\n".join(md_lines))

    return metadata_path, markdown_path


def import_journal_article(article: dict, journal_info: dict, source_info: dict, llm: LLMClient) -> bool:
    """
    Full import pipeline for a single journal article.

    Returns:
        True if successful, False otherwise
    """
    url = article.get("url", "")
    if not url or not is_safe_url(url):
        print(f"  Skipping invalid URL: {url}")
        return False

    # Extract content
    extracted = extract_journal_content(url)
    if not extracted.get("content"):
        # Use description from RSS as fallback
        extracted = {
            "content": article.get("description", ""),
            "title": article.get("title", ""),
            "authors": article.get("authors", []),
            "published_date": article.get("published_date", ""),
            "word_count": len(article.get("description", "").split()),
            "abstract": ""
        }

    if not extracted.get("content") or extracted.get("word_count", 0) < 100:
        print("  Skipping: Insufficient content")
        return False

    # Analyze content
    title = extracted.get("title") or article.get("title", "Untitled")
    analysis = analyze_journal_content(
        title=title,
        content=extracted["content"],
        journal_name=journal_info.get("name", "Unknown"),
        llm=llm
    )

    # Save
    metadata_path, markdown_path = save_journal_article(
        article, extracted, analysis, journal_info, source_info
    )
    print(f"  Saved: {metadata_path.name}")

    return True


def sync_journal_feed(
    feed_url: str,
    source_info: dict = None,
    limit: int = 10,
    dry_run: bool = False
) -> dict:
    """
    Sync journal content from a single RSS feed.

    Returns:
        Dict with: imported, skipped, failed counts
    """
    stats = {"imported": 0, "skipped": 0, "failed": 0}

    # Parse feed
    feed_data = parse_journal_rss_feed(feed_url)
    if not feed_data:
        return stats

    journal = feed_data.get("journal", {})
    journal["feed_url"] = feed_url

    source = source_info or {}

    articles = feed_data.get("articles", [])[:limit]

    if not articles:
        print("No articles found in feed.")
        return stats

    # Get existing IDs
    existing_ids = get_existing_journal_ids()
    print(f"Already in library: {len(existing_ids)} journal articles")

    # Filter new articles
    new_articles = []
    for article in articles:
        article_id = generate_journal_id(article["url"])
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
            success = import_journal_article(article, journal, source, llm)
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


def sync_journal_feeds(
    feeds: list = None,
    limit: int = 10,
    dry_run: bool = False
) -> dict:
    """
    Sync journal content from multiple RSS feeds.

    Args:
        feeds: List of feed URLs (or None to use all configured feeds)
        limit: Max items per feed
        dry_run: Preview without importing

    Returns:
        Dict with aggregate stats
    """
    sources_config = load_journal_sources()
    configured_feeds = sources_config.get("journal_feeds", [])

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
                feeds_to_sync.append({"feed_url": url, "name": "Unknown Journal"})

    if not feeds_to_sync:
        print("No feeds to sync. Configure feeds in trusted_journal_sources.json")
        return {"imported": 0, "skipped": 0, "failed": 0, "feeds_processed": 0}

    print(f"\n{'='*60}")
    print("LAW JOURNAL RSS SYNC")
    print(f"{'='*60}")
    print(f"Feeds to sync: {len(feeds_to_sync)}")

    total_stats = {"imported": 0, "skipped": 0, "failed": 0, "feeds_processed": 0}

    for feed_info in feeds_to_sync:
        feed_url = feed_info.get("feed_url")
        if not feed_url:
            continue

        print(f"\n--- {feed_info.get('name', 'Unknown')} ---")

        stats = sync_journal_feed(
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
    print("JOURNAL SYNC SUMMARY")
    print(f"{'='*60}")
    print(f"Feeds processed: {total_stats['feeds_processed']}")
    print(f"Articles imported: {total_stats['imported']}")
    print(f"Articles skipped: {total_stats['skipped']}")
    print(f"Articles failed: {total_stats['failed']}")

    return total_stats


def list_sources():
    """Display configured journal RSS sources."""
    sources = load_journal_sources()

    print(f"\n{'='*60}")
    print("CONFIGURED LAW JOURNAL RSS SOURCES")
    print(f"{'='*60}")

    feeds = sources.get("journal_feeds", [])
    if not feeds:
        print("\nNo feeds configured. Add feeds to trusted_journal_sources.json")
        return

    for feed in feeds:
        print(f"\n{feed.get('name', 'Unknown')}")
        print(f"  URL: {feed.get('feed_url', 'N/A')}")
        print(f"  Institution: {feed.get('institution', 'N/A')}")
        print(f"  Focus Areas: {', '.join(feed.get('focus_areas', []))}")
        print(f"  Access: {feed.get('access_type', 'N/A')}")

    print(f"\nTotal: {len(feeds)} journals configured")


def main():
    parser = argparse.ArgumentParser(
        description="Import law journal articles from RSS feeds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python law_journal_import.py --all-sources --dry-run
    python law_journal_import.py --feed https://scholarlycommons.law.northwestern.edu/jclc/recent.rss
    python law_journal_import.py --all-sources --limit 5
    python law_journal_import.py --list-sources
        """
    )
    parser.add_argument("--feed", help="Single RSS feed URL to import")
    parser.add_argument("--all-sources", action="store_true",
                        help="Import from all configured sources")
    parser.add_argument("--list-sources", action="store_true",
                        help="List configured journal sources")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max articles per feed (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without importing")
    args = parser.parse_args()

    if args.list_sources:
        list_sources()
        return

    if args.all_sources:
        stats = sync_journal_feeds(
            feeds=None,
            limit=args.limit,
            dry_run=args.dry_run
        )
    elif args.feed:
        if not is_safe_url(args.feed):
            print("Error: Invalid feed URL")
            sys.exit(1)

        stats = sync_journal_feeds(
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
