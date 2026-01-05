#!/usr/bin/env python3
"""
blog_import.py

Import blog posts into the learning library with quality assessment.
Uses trafilatura for content extraction and LLM for quality scoring.

Quality Tiers:
- Tier 1: Trusted sources (auto-approve)
- Tier 2: LLM quality assessment (score 0-100)
- Tier 3: Pending review queue (for lower-scoring content)

Usage:
    python blog_import.py <url>                          # Import single post
    python blog_import.py <url> --dry-run                # Preview only
    python blog_import.py <url> --skip-quality           # Skip quality check
    python blog_import.py --review-pending               # Show pending queue
    python blog_import.py --approve <id>                 # Approve pending item
    python blog_import.py --reject <id>                  # Reject pending item

Prerequisites:
    pip install trafilatura bleach
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import bleach
import trafilatura

from llm_client import LLMClient

# Paths
BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
BLOGS_DIR = BASE_DIR / "blogs"
BLOGS_CACHE_DIR = BASE_DIR / "blogs_cache"
TRUSTED_BLOGS_FILE = BASE_DIR / "trusted_blogs.json"
PENDING_BLOGS_FILE = BASE_DIR / "pending_blogs.json"

# Ensure directories exist
METADATA_DIR.mkdir(exist_ok=True)
BLOGS_DIR.mkdir(exist_ok=True)

# Quality thresholds
QUALITY_THRESHOLD_AUTO = 70  # Auto-approve above this score
QUALITY_THRESHOLD_REVIEW = 40  # Add to pending review between 40-70

# Allowed HTML tags for sanitization
ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'code', 'pre', 'blockquote',
                'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'a']

# LLM Prompts
QUALITY_ASSESSMENT_PROMPT = """Assess this blog post for inclusion in a technical learning library.

Title: {title}
Author: {author}
Content excerpt:
{content_excerpt}

Rate on these dimensions (1-5 each):
- TECHNICAL_DEPTH: How substantive is the technical content?
- ORIGINALITY: Novel insights vs rehashed content?
- CLARITY: Well-written and well-structured?
- ACCURACY: Does it appear factually sound?
- PRACTICALITY: Actionable for practitioners?

Also flag any concerns:
- PROMOTIONAL: Is this primarily marketing/promotional?
- CLICKBAIT: Sensationalized or misleading title?
- OUTDATED: References obsolete technologies?

Format response EXACTLY as:
TECHNICAL_DEPTH: N
ORIGINALITY: N
CLARITY: N
ACCURACY: N
PRACTICALITY: N
FLAGS: [comma-separated list or "none"]
RECOMMENDATION: include|review|skip
REASON: <one sentence explanation>"""

SUMMARY_PROMPT = """Summarize this blog post in 3-5 bullet points.
Each bullet should be one sentence capturing a key insight or takeaway.
Format: Start each line with "- "

Title: {title}
Content:
{content}"""

FACETS_PROMPT = """Categorize this blog post.

Title: {title}
Content excerpt: {excerpt}

Choose ONE topic from: security, programming, ai-ml, entrepreneurship, devops,
                     databases, web-development, career, other
Choose ONE format from: tutorial, deep-dive, news, opinion, announcement, case-study, other
Choose ONE difficulty from: beginner, intermediate, advanced

Format your response EXACTLY as:
TOPIC: <topic>
FORMAT: <format>
DIFFICULTY: <difficulty>"""

SECTIONS_PROMPT = """Identify 3-5 key sections from this blog post.
For each section, provide a title and one-sentence description.

{content}

Format as:
SECTION 1:
TITLE: <section title>
DESCRIPTION: <one sentence summary>

SECTION 2:
TITLE: <title>
DESCRIPTION: <description>

(continue for remaining sections)"""


def load_trusted_sources() -> dict:
    """Load trusted blog sources from JSON file."""
    if not TRUSTED_BLOGS_FILE.exists():
        return {"trusted_sources": []}

    try:
        with open(TRUSTED_BLOGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"trusted_sources": []}


def is_trusted_source(url: str) -> tuple:
    """
    Check if URL is from a trusted source.

    Returns:
        Tuple of (is_trusted: bool, source_info: dict or None)
    """
    trusted = load_trusted_sources()
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")

    for source in trusted.get("trusted_sources", []):
        if source.get("domain") in domain or domain in source.get("domain", ""):
            return True, source

    return False, None


def is_safe_url(url: str) -> bool:
    """Validate URL is safe (not internal/localhost)."""
    parsed = urlparse(url)

    # Block unsafe schemes
    if parsed.scheme not in ('http', 'https'):
        return False

    # Block localhost and private IPs
    hostname = parsed.hostname or ""
    if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return False

    # Block private IP ranges (basic check)
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

    # Security: block path traversal
    if '..' in slug or '/' in slug:
        slug = slug.replace('..', '').replace('/', '')

    return slug[:80] if slug else "untitled"


def generate_post_id(url: str) -> str:
    """Generate unique ID from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def extract_blog_content(url: str) -> dict:
    """
    Extract article content using trafilatura.

    Returns:
        Dict with: title, author, content, published_date, word_count
    """
    print(f"  Fetching content from: {url}")

    try:
        # Download the page
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            print("  Error: Could not download page")
            return {}

        # Extract content
        content = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True
        )

        if not content:
            print("  Error: Could not extract content")
            return {}

        # Extract metadata
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


def assess_quality(title: str, author: str, content: str, llm: LLMClient) -> dict:
    """
    Assess content quality using LLM.

    Returns:
        Dict with: score (0-100), dimensions, flags, recommendation, reason
    """
    print("  Assessing content quality...")

    prompt = QUALITY_ASSESSMENT_PROMPT.format(
        title=title,
        author=author or "Unknown",
        content_excerpt=content[:2000]
    )

    response = llm.generate(prompt, timeout=60)

    # Parse response
    result = {
        "score": 50,
        "dimensions": {},
        "flags": [],
        "recommendation": "review",
        "reason": "Could not parse quality assessment"
    }

    dimensions = ["TECHNICAL_DEPTH", "ORIGINALITY", "CLARITY", "ACCURACY", "PRACTICALITY"]

    for dim in dimensions:
        match = re.search(rf"{dim}:\s*(\d)", response)
        if match:
            result["dimensions"][dim.lower()] = int(match.group(1))

    # Calculate overall score (average of dimensions * 20)
    if result["dimensions"]:
        avg = sum(result["dimensions"].values()) / len(result["dimensions"])
        result["score"] = int(avg * 20)

    # Parse flags
    flags_match = re.search(r"FLAGS:\s*\[?([^\]\n]+)\]?", response)
    if flags_match:
        flags_text = flags_match.group(1).strip()
        if flags_text.lower() != "none":
            result["flags"] = [f.strip().lower() for f in flags_text.split(",")]

    # Parse recommendation
    rec_match = re.search(r"RECOMMENDATION:\s*(\w+)", response)
    if rec_match:
        result["recommendation"] = rec_match.group(1).lower()

    # Parse reason
    reason_match = re.search(r"REASON:\s*(.+?)(?:\n|$)", response)
    if reason_match:
        result["reason"] = reason_match.group(1).strip()

    print(f"  Quality score: {result['score']}/100")
    if result["flags"]:
        print(f"  Flags: {', '.join(result['flags'])}")
    print(f"  Recommendation: {result['recommendation']}")

    return result


def add_to_pending(url: str, title: str, quality: dict, extracted: dict):
    """Add post to pending review queue."""
    pending = {"pending": []}

    if PENDING_BLOGS_FILE.exists():
        try:
            with open(PENDING_BLOGS_FILE) as f:
                pending = json.load(f)
        except Exception:
            pass

    # Check if already in pending
    for item in pending["pending"]:
        if item.get("url") == url:
            print("  Already in pending queue. Skipping.")
            return

    pending["pending"].append({
        "id": generate_post_id(url),
        "url": url,
        "title": title,
        "author": extracted.get("author", ""),
        "quality_score": quality["score"],
        "quality_flags": quality["flags"],
        "recommendation": quality["recommendation"],
        "reason": quality["reason"],
        "fetched_date": datetime.now().strftime("%Y-%m-%d")
    })

    with open(PENDING_BLOGS_FILE, "w") as f:
        json.dump(pending, f, indent=2)

    print(f"  Added to pending review queue.")


def show_pending():
    """Display pending review queue."""
    if not PENDING_BLOGS_FILE.exists():
        print("No pending items.")
        return

    with open(PENDING_BLOGS_FILE) as f:
        pending = json.load(f)

    if not pending.get("pending"):
        print("No pending items.")
        return

    print(f"\n{'='*60}")
    print("PENDING REVIEW QUEUE")
    print(f"{'='*60}")

    for item in pending["pending"]:
        print(f"\nID: {item['id']}")
        print(f"Title: {item['title'][:50]}...")
        print(f"URL: {item['url'][:60]}...")
        print(f"Score: {item['quality_score']}/100")
        print(f"Flags: {', '.join(item['quality_flags']) if item['quality_flags'] else 'none'}")
        print(f"Recommendation: {item['recommendation']}")
        print(f"Reason: {item['reason']}")
        print(f"Fetched: {item['fetched_date']}")

    print(f"\nTotal: {len(pending['pending'])} items pending review")
    print("\nUse --approve <id> or --reject <id> to process items.")


def approve_pending(item_id: str) -> bool:
    """Approve a pending item and import it."""
    if not PENDING_BLOGS_FILE.exists():
        print("No pending items.")
        return False

    with open(PENDING_BLOGS_FILE) as f:
        pending = json.load(f)

    # Find item
    item = None
    for i, p in enumerate(pending.get("pending", [])):
        if p["id"] == item_id or p["id"].startswith(item_id):
            item = pending["pending"].pop(i)
            break

    if not item:
        print(f"Item {item_id} not found in pending queue.")
        return False

    # Save updated pending list
    with open(PENDING_BLOGS_FILE, "w") as f:
        json.dump(pending, f, indent=2)

    # Import the post
    print(f"Approving and importing: {item['title'][:50]}...")
    return import_blog_post(item["url"], skip_quality=True)


def reject_pending(item_id: str) -> bool:
    """Reject and remove a pending item."""
    if not PENDING_BLOGS_FILE.exists():
        print("No pending items.")
        return False

    with open(PENDING_BLOGS_FILE) as f:
        pending = json.load(f)

    # Find and remove item
    for i, p in enumerate(pending.get("pending", [])):
        if p["id"] == item_id or p["id"].startswith(item_id):
            removed = pending["pending"].pop(i)
            with open(PENDING_BLOGS_FILE, "w") as f:
                json.dump(pending, f, indent=2)
            print(f"Rejected: {removed['title'][:50]}...")
            return True

    print(f"Item {item_id} not found in pending queue.")
    return False


def generate_blog_metadata(title: str, content: str, llm: LLMClient) -> dict:
    """Generate summary, facets, and sections using LLM."""
    result = {
        "summary": [],
        "facets": {"topics": ["other"], "format": "other", "difficulty": "intermediate"},
        "sections": []
    }

    # Generate summary
    print("  Generating summary...")
    summary_prompt = SUMMARY_PROMPT.format(title=title, content=content[:3000])
    summary_result = llm.generate(summary_prompt, timeout=90)
    result["summary"] = [line[2:].strip() for line in summary_result.split('\n')
                         if line.strip().startswith('- ')]

    # Generate facets
    print("  Analyzing topics...")
    facets_prompt = FACETS_PROMPT.format(title=title, excerpt=content[:1500])
    facets_result = llm.generate(facets_prompt, timeout=30)

    for line in facets_result.split('\n'):
        if line.startswith("TOPIC:"):
            result["facets"]["topics"] = [line[6:].strip().lower()]
        elif line.startswith("FORMAT:"):
            result["facets"]["format"] = line[7:].strip().lower()
        elif line.startswith("DIFFICULTY:"):
            result["facets"]["difficulty"] = line[11:].strip().lower()

    # Generate sections (for longer posts)
    if len(content) > 1000:
        print("  Identifying sections...")
        sections_prompt = SECTIONS_PROMPT.format(content=content[:6000])
        sections_result = llm.generate(sections_prompt, timeout=45)

        section_blocks = re.findall(
            r"SECTION \d+:\s*TITLE:\s*(.+?)\s*DESCRIPTION:\s*(.+?)(?=SECTION \d+:|$)",
            sections_result,
            re.DOTALL
        )

        for sec_title, sec_desc in section_blocks:
            result["sections"].append({
                "title": sec_title.strip(),
                "description": sec_desc.strip()
            })

    return result


def save_blog_post(url: str, extracted: dict, analysis: dict, quality: dict = None) -> tuple:
    """
    Save blog post metadata and markdown.

    Returns:
        Tuple of (metadata_path, markdown_path)
    """
    title = extracted.get("title") or "Untitled"
    slug = safe_slug(title)
    post_id = generate_post_id(url)

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")

    # Build metadata
    metadata = {
        "id": post_id,
        "content_type": "blog",
        "title": title,
        "url": url,
        "blog": {
            "name": domain,
            "slug": safe_slug(domain),
            "domain": domain
        },
        "author": {"name": extracted.get("author", "")},
        "published_date": extracted.get("published_date", ""),
        "word_count": extracted.get("word_count", 0),
        "reading_time_minutes": max(1, extracted.get("word_count", 0) // 200),
        "facets": analysis.get("facets", {}),
        "summary": analysis.get("summary", []),
        "sections": analysis.get("sections", []),
        "added_date": datetime.now().strftime("%Y-%m-%d")
    }

    if quality:
        metadata["quality_score"] = quality.get("score", 0)
        metadata["quality_flags"] = quality.get("flags", [])

    # Save metadata JSON
    metadata_path = METADATA_DIR / f"{slug}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Build markdown
    md_lines = [
        f"# {title}",
        "",
        f"**Source:** [{domain}]({url})",
        "",
    ]

    if extracted.get("author"):
        md_lines.extend([f"**Author:** {extracted['author']}", ""])

    if metadata.get("published_date"):
        md_lines.extend([f"**Published:** {metadata['published_date']}", ""])

    md_lines.extend([
        f"**Reading time:** {metadata['reading_time_minutes']} min ({metadata['word_count']} words)",
        ""
    ])

    # Summary
    if metadata.get("summary"):
        md_lines.extend(["## Summary", ""])
        for point in metadata["summary"]:
            md_lines.append(f"- {point}")
        md_lines.append("")

    # Sections
    if metadata.get("sections"):
        md_lines.extend(["## Key Sections", ""])
        for sec in metadata["sections"]:
            md_lines.append(f"- **{sec['title']}** - {sec.get('description', '')}")
        md_lines.append("")

    # Full content
    md_lines.extend([
        "## Content",
        "",
        extracted.get("content", ""),
        ""
    ])

    # Metadata footer
    md_lines.extend([
        "---",
        "",
        f"*Topics: {', '.join(metadata['facets'].get('topics', []))}*",
        f"*Format: {metadata['facets'].get('format', 'unknown')}*",
        f"*Difficulty: {metadata['facets'].get('difficulty', 'unknown')}*",
    ])

    if quality:
        md_lines.append(f"*Quality Score: {quality.get('score', 0)}/100*")

    # Save markdown
    markdown_path = BLOGS_DIR / f"{slug}.md"
    with open(markdown_path, "w") as f:
        f.write("\n".join(md_lines))

    return metadata_path, markdown_path


def get_existing_blog_ids() -> set:
    """Get set of blog post IDs already in the library."""
    ids = set()
    for json_file in METADATA_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                if data.get("content_type") == "blog":
                    ids.add(data.get("id"))
        except Exception:
            pass
    return ids


def import_blog_post(
    url: str,
    skip_quality: bool = False,
    dry_run: bool = False
) -> bool:
    """
    Import a single blog post.

    Args:
        url: Blog post URL
        skip_quality: Skip quality assessment
        dry_run: Preview without importing

    Returns:
        True if successful, False otherwise
    """
    print(f"\nImporting blog post: {url[:60]}...")

    # Validate URL
    if not is_safe_url(url):
        print("  Error: URL is not safe (localhost, private IP, or invalid scheme)")
        return False

    # Check if already imported
    post_id = generate_post_id(url)
    existing_ids = get_existing_blog_ids()
    if post_id in existing_ids:
        print("  Post already in library. Skipping.")
        return False

    # Check if from trusted source
    is_trusted, trust_info = is_trusted_source(url)
    if is_trusted:
        print(f"  Trusted source: {trust_info.get('author', trust_info.get('domain'))}")

    # Extract content
    extracted = extract_blog_content(url)
    if not extracted or not extracted.get("content"):
        print("  Error: Could not extract content")
        return False

    title = extracted.get("title", "Untitled")

    if dry_run:
        print(f"  [DRY RUN] Would import:")
        print(f"    Title: {title}")
        print(f"    Author: {extracted.get('author', 'Unknown')}")
        print(f"    Words: {extracted.get('word_count', 0)}")
        print(f"    Published: {extracted.get('published_date', 'Unknown')}")
        return True

    # Initialize LLM
    llm = LLMClient()
    if not llm.is_available():
        print("  Warning: LLM not available. Using basic metadata only.")
        analysis = {
            "summary": [],
            "facets": {"topics": ["other"], "format": "other", "difficulty": "intermediate"},
            "sections": []
        }
        quality = None
    else:
        # Quality assessment (skip for trusted sources or if explicitly skipped)
        quality = None
        if not is_trusted and not skip_quality:
            quality = assess_quality(
                title,
                extracted.get("author", ""),
                extracted.get("content", ""),
                llm
            )

            # Check quality thresholds
            if quality["score"] < QUALITY_THRESHOLD_REVIEW:
                print(f"  Quality too low ({quality['score']}/100). Skipping.")
                return False

            if quality["score"] < QUALITY_THRESHOLD_AUTO and quality["recommendation"] != "include":
                print(f"  Quality needs review ({quality['score']}/100).")
                add_to_pending(url, title, quality, extracted)
                return False

        # Generate metadata
        analysis = generate_blog_metadata(title, extracted.get("content", ""), llm)

    # Save
    metadata_path, markdown_path = save_blog_post(url, extracted, analysis, quality)
    print(f"  Saved: {metadata_path.name}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Import blog posts with quality assessment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python blog_import.py <url>                  # Import single post
    python blog_import.py <url> --dry-run        # Preview only
    python blog_import.py <url> --skip-quality   # Skip quality check
    python blog_import.py --review-pending       # Show pending queue
    python blog_import.py --approve abc123       # Approve pending item
    python blog_import.py --reject abc123        # Reject pending item
        """
    )

    parser.add_argument("url", nargs="?", help="Blog post URL to import")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without importing")
    parser.add_argument("--skip-quality", action="store_true",
                        help="Skip quality assessment")
    parser.add_argument("--review-pending", action="store_true",
                        help="Show pending review queue")
    parser.add_argument("--approve", metavar="ID",
                        help="Approve pending item by ID")
    parser.add_argument("--reject", metavar="ID",
                        help="Reject pending item by ID")

    args = parser.parse_args()

    # Handle pending queue operations
    if args.review_pending:
        show_pending()
        return

    if args.approve:
        success = approve_pending(args.approve)
        sys.exit(0 if success else 1)

    if args.reject:
        success = reject_pending(args.reject)
        sys.exit(0 if success else 1)

    # Import URL
    if not args.url:
        parser.print_help()
        sys.exit(1)

    success = import_blog_post(
        args.url,
        skip_quality=args.skip_quality,
        dry_run=args.dry_run
    )

    if success:
        print("\nBlog post imported successfully!")
    else:
        print("\nFailed to import blog post.")
        sys.exit(1)


if __name__ == "__main__":
    main()
