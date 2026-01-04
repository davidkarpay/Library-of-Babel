#!/usr/bin/env python3
"""
huggingface_papers.py

Import papers from HuggingFace's daily papers page into the learning library.
Fetches paper metadata, abstracts, and optionally full PDF text for high-relevance papers.

Usage:
    python huggingface_papers.py                        # Import today's papers
    python huggingface_papers.py --date 2026-01-02      # Import specific date
    python huggingface_papers.py --limit 10             # Limit number of papers
    python huggingface_papers.py --min-upvotes 20       # Only papers with 20+ upvotes
    python huggingface_papers.py --dry-run              # Preview without importing
    python huggingface_papers.py --full-text-threshold 50  # Full PDF for 50+ upvotes

Prerequisites:
    pip install beautifulsoup4 requests pdfplumber
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("Warning: pdfplumber not installed. Full PDF text extraction disabled.")
    print("Install with: pip install pdfplumber")

from llm_client import LLMClient

# Paths
BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
PAPERS_DIR = BASE_DIR / "papers"
PAPERS_CACHE_DIR = BASE_DIR / "papers_cache"

# URLs
HUGGINGFACE_BASE = "https://huggingface.co"
HUGGINGFACE_PAPERS = f"{HUGGINGFACE_BASE}/papers"
ARXIV_BASE = "https://arxiv.org"

# Request settings
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Learning-Library-Bot/1.0"
}
REQUEST_DELAY = 1.0  # Seconds between requests

# LLM Prompts
PAPER_SUMMARY_PROMPT = """Analyze this research paper and provide insights accessible to ML practitioners.

Title: {title}
Authors: {authors}
Abstract: {abstract}
{full_text_section}

Provide:
1. A concise title (5-10 words) that captures the main contribution
2. 3-5 key insights as bullet points
3. Practical applications or implications

Format your response EXACTLY as:
TITLE: <concise title>
INSIGHTS:
- <insight 1>
- <insight 2>
- <insight 3>
APPLICATIONS: <one sentence on practical implications>"""

PAPER_FACETS_PROMPT = """Categorize this research paper.

Title: {title}
Abstract: {abstract}

Choose PRIMARY topic from: nlp, computer-vision, multimodal, reinforcement-learning,
robotics, ai-safety, efficiency, ai-ml, programming, other

Choose SECONDARY topics (0-2) from the same list if applicable.

Choose format from: research-paper, survey, benchmark, dataset, other

Choose difficulty from:
- beginner (accessible overview, minimal math)
- intermediate (requires ML background)
- advanced (cutting-edge research, heavy math)

Format your response EXACTLY as:
PRIMARY_TOPIC: <topic>
SECONDARY_TOPICS: <comma-separated list or 'none'>
FORMAT: <format>
DIFFICULTY: <difficulty>"""

PAPER_SECTIONS_PROMPT = """Identify 3-5 key sections from this paper's content.
For each section, provide a title and one-sentence description.

{text_excerpt}

Format as:
SECTION 1:
TITLE: <section title>
DESCRIPTION: <one sentence summary>

SECTION 2:
TITLE: <title>
DESCRIPTION: <description>

(continue for remaining sections)"""


def fetch_daily_papers(date: str = None) -> list:
    """
    Fetch list of papers from HuggingFace daily papers page.

    Args:
        date: Date string YYYY-MM-DD. Defaults to today (uses main /papers page).

    Returns:
        List of paper dicts with: arxiv_id, title, upvotes, comments, submitter, org
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # Try date-specific URL first, then fall back to main page
    urls_to_try = [
        f"{HUGGINGFACE_PAPERS}/date/{date}",
        HUGGINGFACE_PAPERS  # Main page shows today's papers
    ]

    soup = None
    for url in urls_to_try:
        print(f"Fetching papers from: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Check if we got papers
            test_links = soup.find_all("a", href=re.compile(r"/papers/\d{4}\.\d+"))
            if test_links:
                print(f"Found {len(test_links)} paper links")
                break
            else:
                print(f"No paper links found at {url}, trying next...")

        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            continue

    if not soup:
        print("Error: Could not fetch papers from any URL")
        return []

    papers = []

    # Find paper links - arXiv IDs are YYMM.NNNNN format (e.g., 2512.23959)
    paper_links = soup.find_all("a", href=re.compile(r"/papers/\d{4}\.\d+"))

    seen_ids = set()
    for link in paper_links:
        href = link.get("href", "")
        match = re.search(r"/papers/(\d{4}\.\d+)", href)
        if not match:
            continue

        arxiv_id = match.group(1)
        if arxiv_id in seen_ids:
            continue

        # Get title from link text (skip if it's an image-only link)
        title = link.get_text(strip=True)

        # If this link has no text (probably an image link), look for a sibling/nearby h3 or title link
        if not title or len(title) < 10:
            # Try to find the title in a nearby h3 element
            parent = link.find_parent("article") or link.find_parent("div", class_=True)
            if parent:
                h3 = parent.find("h3")
                if h3:
                    title_link = h3.find("a", href=re.compile(rf"/papers/{arxiv_id}"))
                    if title_link:
                        title = title_link.get_text(strip=True)

        if not title or len(title) < 10:
            continue

        seen_ids.add(arxiv_id)

        # Try to find upvotes in nearby elements
        upvotes = 0
        parent = link.find_parent("article") or link.find_parent("div", class_=True)
        if parent:
            # Look for upvote count - typically a number near a heart/upvote icon
            for elem in parent.find_all(string=re.compile(r"^\d+$")):
                try:
                    val = int(elem.strip())
                    if val > upvotes and val < 10000:  # Reasonable upvote range
                        upvotes = val
                except ValueError:
                    pass

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "upvotes": upvotes,
            "huggingface_url": f"{HUGGINGFACE_BASE}/papers/{arxiv_id}",
            "arxiv_url": f"{ARXIV_BASE}/abs/{arxiv_id}",
            "published_date": date
        })

    print(f"Found {len(papers)} papers for {date}")
    return papers


def fetch_paper_details(arxiv_id: str) -> dict:
    """
    Fetch full paper details from HuggingFace paper page.

    Returns:
        Dict with: title, abstract, authors, organization, upvotes
    """
    url = f"{HUGGINGFACE_PAPERS}/{arxiv_id}"

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching paper details for {arxiv_id}: {e}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    details = {"arxiv_id": arxiv_id}

    # Title - usually in h1
    title_elem = soup.find("h1")
    if title_elem:
        details["title"] = title_elem.get_text(strip=True)

    # Abstract - look for abstract section
    abstract_elem = soup.find("p", class_=re.compile(r"abstract", re.I))
    if not abstract_elem:
        # Try finding by content pattern
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 200 and not text.startswith("http"):
                details["abstract"] = text
                break
    else:
        details["abstract"] = abstract_elem.get_text(strip=True)

    # Authors - look for author links or text
    authors = []
    author_section = soup.find(string=re.compile(r"author", re.I))
    if author_section:
        parent = author_section.find_parent()
        if parent:
            author_links = parent.find_all("a")
            for a in author_links:
                name = a.get_text(strip=True)
                if name and len(name) > 1 and len(name) < 50:
                    authors.append(name)

    # Fallback: look for spans with author-like content
    if not authors:
        for span in soup.find_all("span"):
            text = span.get_text(strip=True)
            # Author patterns: "Name, Name, Name" or single names
            if "," in text and len(text) < 500:
                potential_authors = [a.strip() for a in text.split(",")]
                if all(len(a) < 50 for a in potential_authors[:5]):
                    authors = potential_authors[:10]  # Limit to 10 authors
                    break

    details["authors"] = authors

    # Organization
    org_elem = soup.find("img", {"alt": re.compile(r"logo", re.I)})
    if org_elem:
        parent = org_elem.find_parent()
        if parent:
            org_text = parent.get_text(strip=True)
            if org_text and len(org_text) < 100:
                details["organization"] = org_text

    # Try to get upvotes
    upvote_elem = soup.find(string=re.compile(r"^\d+$"))
    if upvote_elem:
        try:
            details["upvotes"] = int(upvote_elem.strip())
        except ValueError:
            details["upvotes"] = 0

    return details


def fetch_arxiv_abstract(arxiv_id: str) -> str:
    """Fetch abstract directly from arXiv as fallback."""
    url = f"{ARXIV_BASE}/abs/{arxiv_id}"

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching arXiv abstract: {e}")
        return ""

    soup = BeautifulSoup(response.text, "html.parser")

    # arXiv has abstract in a specific blockquote
    abstract_block = soup.find("blockquote", class_="abstract")
    if abstract_block:
        # Remove the "Abstract:" label
        text = abstract_block.get_text(strip=True)
        text = re.sub(r"^Abstract:\s*", "", text)
        return text

    return ""


def fetch_arxiv_pdf_text(arxiv_id: str, max_pages: int = 15) -> str:
    """
    Download PDF from arXiv and extract text.

    Args:
        arxiv_id: arXiv paper ID
        max_pages: Maximum pages to extract (default 15)

    Returns:
        Extracted text from PDF
    """
    if not PDF_SUPPORT:
        return ""

    pdf_url = f"{ARXIV_BASE}/pdf/{arxiv_id}.pdf"

    # Create cache directory
    PAPERS_CACHE_DIR.mkdir(exist_ok=True)
    cache_path = PAPERS_CACHE_DIR / f"{arxiv_id}.pdf"

    # Download if not cached
    if not cache_path.exists():
        print(f"  Downloading PDF from arXiv...")
        try:
            response = requests.get(pdf_url, headers=HEADERS, timeout=60, stream=True)
            response.raise_for_status()

            with open(cache_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        except requests.RequestException as e:
            print(f"  Error downloading PDF: {e}")
            return ""

    # Extract text
    print(f"  Extracting text from PDF...")
    text_parts = []

    try:
        with pdfplumber.open(cache_path) as pdf:
            pages_to_read = min(len(pdf.pages), max_pages)
            for i, page in enumerate(pdf.pages[:pages_to_read]):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        print(f"  Error extracting PDF text: {e}")
        return ""

    full_text = "\n\n".join(text_parts)
    print(f"  Extracted {len(full_text)} characters from {len(text_parts)} pages")

    return full_text


def analyze_paper(paper: dict, full_text: str = None) -> dict:
    """
    Run LLM analysis on paper to generate summary, sections, and facets.

    Args:
        paper: Paper dict with title, abstract, authors
        full_text: Optional full paper text for deeper analysis

    Returns:
        Dict with: llm_title, summary, sections, facets
    """
    llm = LLMClient()

    if not llm.is_available():
        print("Warning: LLM not available. Using basic metadata only.")
        return {
            "llm_title": paper.get("title", ""),
            "summary": [paper.get("abstract", "")[:200] + "..."] if paper.get("abstract") else [],
            "sections": [],
            "facets": {
                "topics": ["ai-ml"],
                "format": "research-paper",
                "difficulty": "advanced"
            }
        }

    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    authors = ", ".join(paper.get("authors", [])[:5])

    result = {}

    # Generate summary
    print("  Generating summary...")
    full_text_section = ""
    if full_text:
        # Include first ~3000 chars of full text
        full_text_section = f"\n\nFull Text Excerpt:\n{full_text[:3000]}..."

    summary_prompt = PAPER_SUMMARY_PROMPT.format(
        title=title,
        authors=authors,
        abstract=abstract,
        full_text_section=full_text_section
    )

    summary_response = llm.generate(summary_prompt, timeout=60)

    # Parse summary response
    result["llm_title"] = title  # Default
    result["summary"] = []

    if summary_response:
        # Extract title
        title_match = re.search(r"TITLE:\s*(.+?)(?=\n|INSIGHTS)", summary_response, re.DOTALL)
        if title_match:
            result["llm_title"] = title_match.group(1).strip()

        # Extract insights
        insights_match = re.search(r"INSIGHTS:\s*(.+?)(?=APPLICATIONS|$)", summary_response, re.DOTALL)
        if insights_match:
            insights_text = insights_match.group(1)
            insights = re.findall(r"-\s*(.+?)(?=\n-|\n\n|$)", insights_text, re.DOTALL)
            result["summary"] = [i.strip() for i in insights if i.strip()]

    # Generate facets
    print("  Analyzing topics and difficulty...")
    facets_prompt = PAPER_FACETS_PROMPT.format(
        title=title,
        abstract=abstract
    )

    facets_response = llm.generate(facets_prompt, timeout=30)

    # Parse facets
    result["facets"] = {
        "topics": ["ai-ml"],
        "format": "research-paper",
        "difficulty": "advanced"
    }

    if facets_response:
        # Primary topic
        primary_match = re.search(r"PRIMARY_TOPIC:\s*(\S+)", facets_response)
        if primary_match:
            primary = primary_match.group(1).lower().strip()
            result["facets"]["topics"] = [primary]

        # Secondary topics
        secondary_match = re.search(r"SECONDARY_TOPICS:\s*(.+?)(?=\n|FORMAT)", facets_response)
        if secondary_match:
            secondary_text = secondary_match.group(1).strip()
            if secondary_text.lower() != "none":
                secondary = [t.strip().lower() for t in secondary_text.split(",")]
                result["facets"]["topics"].extend([t for t in secondary if t and t != "none"])

        # Format
        format_match = re.search(r"FORMAT:\s*(\S+)", facets_response)
        if format_match:
            result["facets"]["format"] = format_match.group(1).lower().strip()

        # Difficulty
        diff_match = re.search(r"DIFFICULTY:\s*(\S+)", facets_response)
        if diff_match:
            result["facets"]["difficulty"] = diff_match.group(1).lower().strip()

    # Generate sections (only for full-text papers)
    result["sections"] = []
    if full_text and len(full_text) > 2000:
        print("  Identifying key sections...")
        sections_prompt = PAPER_SECTIONS_PROMPT.format(
            text_excerpt=full_text[:6000]
        )

        sections_response = llm.generate(sections_prompt, timeout=45)

        if sections_response:
            # Parse sections
            section_blocks = re.findall(
                r"SECTION \d+:\s*TITLE:\s*(.+?)\s*DESCRIPTION:\s*(.+?)(?=SECTION \d+:|$)",
                sections_response,
                re.DOTALL
            )

            for i, (sec_title, sec_desc) in enumerate(section_blocks):
                result["sections"].append({
                    "index": i,
                    "title": sec_title.strip(),
                    "description": sec_desc.strip()
                })

    return result


def sanitize_filename(title: str) -> str:
    """Convert title to safe filename slug."""
    # Remove special characters
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    # Replace spaces with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    # Trim
    slug = slug.strip("-")
    # Limit length
    return slug[:80]


def save_paper(paper: dict, analysis: dict) -> tuple:
    """
    Save paper metadata and markdown.

    Returns:
        Tuple of (metadata_path, markdown_path)
    """
    # Create directories
    METADATA_DIR.mkdir(exist_ok=True)
    PAPERS_DIR.mkdir(exist_ok=True)

    # Create filename from title
    title = analysis.get("llm_title") or paper.get("title", paper["arxiv_id"])
    slug = sanitize_filename(title)

    # Build metadata
    metadata = {
        "id": paper["arxiv_id"],
        "content_type": "paper",
        "title": analysis.get("llm_title") or paper.get("title"),
        "url": paper.get("huggingface_url"),
        "arxiv_id": paper["arxiv_id"],
        "arxiv_url": paper.get("arxiv_url"),
        "huggingface_url": paper.get("huggingface_url"),
        "authors": paper.get("authors", []),
        "abstract": paper.get("abstract", ""),
        "organization": paper.get("organization", ""),
        "upvotes": paper.get("upvotes", 0),
        "published_date": paper.get("published_date"),
        "has_full_text": bool(analysis.get("sections")),
        "facets": analysis.get("facets", {}),
        "summary": analysis.get("summary", []),
        "sections": analysis.get("sections", []),
        "added_date": datetime.now().strftime("%Y-%m-%d")
    }

    # Save metadata JSON
    metadata_path = METADATA_DIR / f"{slug}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Build markdown
    md_lines = [
        f"# {metadata['title']}",
        "",
        f"**Authors:** {', '.join(metadata['authors'][:5])}{'...' if len(metadata['authors']) > 5 else ''}",
        "",
        f"**Source:** [HuggingFace]({metadata['huggingface_url']}) | [arXiv]({metadata['arxiv_url']})",
        "",
        f"**Published:** {metadata['published_date']}",
        "",
    ]

    if metadata.get("organization"):
        md_lines.extend([f"**Organization:** {metadata['organization']}", ""])

    # Summary
    if metadata.get("summary"):
        md_lines.extend(["## Summary", ""])
        for point in metadata["summary"]:
            md_lines.append(f"- {point}")
        md_lines.append("")

    # Abstract
    if metadata.get("abstract"):
        md_lines.extend([
            "## Abstract",
            "",
            metadata["abstract"],
            ""
        ])

    # Sections
    if metadata.get("sections"):
        md_lines.extend(["## Key Sections", ""])
        for sec in metadata["sections"]:
            md_lines.append(f"- **{sec['title']}** - {sec['description']}")
        md_lines.append("")

    # Metadata footer
    md_lines.extend([
        "---",
        "",
        f"*Topics: {', '.join(metadata['facets'].get('topics', []))}*",
        f"*Difficulty: {metadata['facets'].get('difficulty', 'unknown')}*",
        f"*Upvotes: {metadata.get('upvotes', 0)}*",
    ])

    # Save markdown
    markdown_path = PAPERS_DIR / f"{slug}.md"
    with open(markdown_path, "w") as f:
        f.write("\n".join(md_lines))

    return metadata_path, markdown_path


def get_existing_paper_ids() -> set:
    """Get set of arXiv IDs already in the library."""
    ids = set()
    for json_file in METADATA_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                if data.get("content_type") == "paper":
                    ids.add(data.get("arxiv_id") or data.get("id"))
        except Exception:
            pass
    return ids


def import_paper(arxiv_id: str, paper_info: dict = None, fetch_full_text: bool = False) -> dict:
    """
    Full import pipeline for a single paper.

    Args:
        arxiv_id: arXiv paper ID
        paper_info: Optional pre-fetched paper info
        fetch_full_text: Whether to download and extract PDF text

    Returns:
        Metadata dict if successful, empty dict on failure
    """
    print(f"\nImporting paper: {arxiv_id}")

    # Fetch details if not provided
    if not paper_info or not paper_info.get("abstract"):
        print("  Fetching paper details...")
        details = fetch_paper_details(arxiv_id)
        time.sleep(REQUEST_DELAY)

        if paper_info:
            paper_info.update(details)
        else:
            paper_info = details

        # Fallback to arXiv for abstract
        if not paper_info.get("abstract"):
            print("  Fetching abstract from arXiv...")
            paper_info["abstract"] = fetch_arxiv_abstract(arxiv_id)
            time.sleep(REQUEST_DELAY)

    if not paper_info.get("title"):
        print(f"  Error: Could not fetch paper details for {arxiv_id}")
        return {}

    # Fetch full text if requested
    full_text = ""
    if fetch_full_text:
        full_text = fetch_arxiv_pdf_text(arxiv_id)
        time.sleep(REQUEST_DELAY)

    # Analyze with LLM
    print("  Analyzing paper with LLM...")
    analysis = analyze_paper(paper_info, full_text)

    # Save
    metadata_path, markdown_path = save_paper(paper_info, analysis)
    print(f"  Saved: {metadata_path.name}")

    return paper_info


def import_daily_papers(
    date: str = None,
    limit: int = None,
    min_upvotes: int = 0,
    full_text_threshold: int = 50,
    dry_run: bool = False
) -> tuple:
    """
    Import all papers from HuggingFace daily papers page.

    Args:
        date: Date string YYYY-MM-DD (defaults to today)
        limit: Maximum papers to import
        min_upvotes: Only import papers with at least this many upvotes
        full_text_threshold: Fetch full PDF for papers with upvotes >= this
        dry_run: Preview without importing

    Returns:
        Tuple of (success_count, skip_count, fail_count)
    """
    print("=" * 60)
    print("HuggingFace Daily Papers Import")
    print("=" * 60)

    # Fetch paper list
    papers = fetch_daily_papers(date)

    if not papers:
        print("No papers found.")
        return 0, 0, 0

    # Filter by upvotes
    if min_upvotes > 0:
        papers = [p for p in papers if p.get("upvotes", 0) >= min_upvotes]
        print(f"After upvote filter (>= {min_upvotes}): {len(papers)} papers")

    # Limit
    if limit:
        papers = papers[:limit]
        print(f"Limited to: {len(papers)} papers")

    # Get existing
    existing_ids = get_existing_paper_ids()
    print(f"Already in library: {len(existing_ids)} papers")

    # Filter out existing
    new_papers = [p for p in papers if p["arxiv_id"] not in existing_ids]
    print(f"New papers to import: {len(new_papers)}")

    if dry_run:
        print("\nDRY RUN - Papers that would be imported:")
        for i, paper in enumerate(new_papers, 1):
            print(f"  [{i}] {paper['title'][:60]}...")
            print(f"      arXiv: {paper['arxiv_id']} | Upvotes: {paper.get('upvotes', 0)}")
        return len(new_papers), len(papers) - len(new_papers), 0

    if not new_papers:
        print("No new papers to import.")
        return 0, len(papers), 0

    # Import papers
    success = 0
    failed = 0

    for i, paper in enumerate(new_papers, 1):
        print(f"\n[{i}/{len(new_papers)}] {paper['title'][:50]}...")

        # Determine if we should fetch full text
        fetch_full = paper.get("upvotes", 0) >= full_text_threshold
        if fetch_full:
            print(f"  High upvotes ({paper.get('upvotes', 0)}) - fetching full PDF")

        try:
            result = import_paper(paper["arxiv_id"], paper, fetch_full_text=fetch_full)
            if result:
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  Error: {e}")
            failed += 1

        # Delay between papers
        if i < len(new_papers):
            time.sleep(REQUEST_DELAY)

    print("\n" + "=" * 60)
    print(f"Import complete!")
    print(f"  Imported: {success}")
    print(f"  Skipped (existing): {len(papers) - len(new_papers)}")
    print(f"  Failed: {failed}")
    print("=" * 60)

    return success, len(papers) - len(new_papers), failed


def main():
    parser = argparse.ArgumentParser(description="Import HuggingFace daily papers")
    parser.add_argument("--date", help="Date YYYY-MM-DD (default: today)")
    parser.add_argument("--limit", type=int, help="Max papers to import")
    parser.add_argument("--min-upvotes", type=int, default=0, help="Minimum upvotes filter")
    parser.add_argument("--full-text-threshold", type=int, default=50,
                        help="Fetch full PDF for papers with >= this many upvotes")
    parser.add_argument("--dry-run", action="store_true", help="Preview without importing")
    parser.add_argument("--single", help="Import single paper by arXiv ID")
    args = parser.parse_args()

    if args.single:
        # Import single paper
        result = import_paper(args.single, fetch_full_text=True)
        if result:
            print("\nPaper imported successfully!")
        else:
            print("\nFailed to import paper.")
            sys.exit(1)
    else:
        # Import daily papers
        success, skipped, failed = import_daily_papers(
            date=args.date,
            limit=args.limit,
            min_upvotes=args.min_upvotes,
            full_text_threshold=args.full_text_threshold,
            dry_run=args.dry_run
        )

        if failed > 0 and success == 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
