#!/usr/bin/env python3
"""
arxiv_papers.py

Import papers directly from arXiv API into the learning library.
Query by category, date range, or search query.

Usage:
    python arxiv_papers.py --category cs.AI                 # Recent AI papers
    python arxiv_papers.py --category cs.LG --days 14       # Last 14 days
    python arxiv_papers.py --category cs.AI,cs.LG --limit 20  # Multiple categories
    python arxiv_papers.py --query "large language models"  # Search query
    python arxiv_papers.py --query "ti:transformer"         # Title search
    python arxiv_papers.py --single 2401.12345              # Single paper
    python arxiv_papers.py --dry-run                        # Preview only

Prerequisites:
    pip install requests defusedxml
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests
import defusedxml.ElementTree as ET  # Safe XML parsing

# Import shared functions from huggingface_papers
from huggingface_papers import (
    get_existing_paper_ids,
    analyze_paper,
    save_paper,
    fetch_arxiv_pdf_text,
    fetch_arxiv_abstract,
    METADATA_DIR,
    PAPERS_DIR,
    HEADERS,
)

# arXiv API settings
ARXIV_API_BASE = "http://export.arxiv.org/api/query"
ARXIV_RATE_LIMIT = 3.0  # arXiv policy: max 1 request per 3 seconds
ARXIV_MAX_RESULTS_PER_REQUEST = 100  # API limit per request

# XML namespaces
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

# Default categories of interest
DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]

# Map arXiv categories to our topic facets
CATEGORY_TO_TOPIC = {
    "cs.AI": "ai-ml",
    "cs.LG": "ai-ml",
    "cs.CL": "nlp",
    "cs.CV": "computer-vision",
    "cs.RO": "robotics",
    "cs.NE": "ai-ml",
    "stat.ML": "ai-ml",
    "cs.MA": "ai-ml",
    "cs.HC": "other",
    "cs.SE": "programming",
    "cs.CR": "security",
}


def build_arxiv_query(
    categories: list = None,
    query: str = None,
    from_date: str = None,
    to_date: str = None
) -> str:
    """
    Build arXiv API search query string.

    Args:
        categories: List of arXiv categories (e.g., ["cs.AI", "cs.LG"])
        query: Free-text search query or arXiv query syntax
        from_date: Start date YYYY-MM-DD
        to_date: End date YYYY-MM-DD

    Returns:
        Search query string for arXiv API
    """
    parts = []

    # Add category filter
    if categories:
        cat_queries = [f"cat:{cat}" for cat in categories]
        if len(cat_queries) == 1:
            parts.append(cat_queries[0])
        else:
            parts.append(f"({' OR '.join(cat_queries)})")

    # Add search query
    if query:
        # Check if it's already using arXiv query syntax (ti:, au:, abs:, etc.)
        if re.match(r"^(ti|au|abs|all|cat):", query):
            parts.append(query)
        else:
            # Free-text search across title and abstract
            parts.append(f"all:{query}")

    # Combine with AND
    if parts:
        return " AND ".join(parts)

    # Default: recent AI papers
    return "cat:cs.AI"


def parse_arxiv_response(xml_text: str) -> list:
    """
    Parse arXiv API Atom XML response into paper dicts.

    Args:
        xml_text: XML response from arXiv API

    Returns:
        List of paper dicts with: arxiv_id, title, abstract, authors, etc.
    """
    papers = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"Error parsing arXiv XML: {e}")
        return []

    # Find all entry elements
    for entry in root.findall(f"{ATOM_NS}entry"):
        paper = {}

        # Extract arXiv ID from the id URL
        id_elem = entry.find(f"{ATOM_NS}id")
        if id_elem is not None and id_elem.text:
            # Format: http://arxiv.org/abs/2401.12345v1
            match = re.search(r"arxiv\.org/abs/(\d{4}\.\d+)", id_elem.text)
            if match:
                paper["arxiv_id"] = match.group(1)
            else:
                continue

        # Title
        title_elem = entry.find(f"{ATOM_NS}title")
        if title_elem is not None and title_elem.text:
            # Clean up whitespace in title
            paper["title"] = " ".join(title_elem.text.split())

        # Abstract (summary)
        summary_elem = entry.find(f"{ATOM_NS}summary")
        if summary_elem is not None and summary_elem.text:
            paper["abstract"] = " ".join(summary_elem.text.split())

        # Authors
        authors = []
        for author in entry.findall(f"{ATOM_NS}author"):
            name_elem = author.find(f"{ATOM_NS}name")
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())
        paper["authors"] = authors

        # Categories
        categories = []
        primary_category = None
        for category in entry.findall(f"{ARXIV_NS}primary_category"):
            term = category.get("term")
            if term:
                primary_category = term
                categories.append(term)

        for category in entry.findall(f"{ATOM_NS}category"):
            term = category.get("term")
            if term and term not in categories:
                categories.append(term)

        paper["categories"] = categories
        paper["primary_category"] = primary_category or (categories[0] if categories else None)

        # Published date
        published_elem = entry.find(f"{ATOM_NS}published")
        if published_elem is not None and published_elem.text:
            # Format: 2024-01-15T18:00:00Z
            try:
                dt = datetime.fromisoformat(published_elem.text.replace("Z", "+00:00"))
                paper["published_date"] = dt.strftime("%Y-%m-%d")
            except ValueError:
                paper["published_date"] = published_elem.text[:10]

        # Updated date
        updated_elem = entry.find(f"{ATOM_NS}updated")
        if updated_elem is not None and updated_elem.text:
            try:
                dt = datetime.fromisoformat(updated_elem.text.replace("Z", "+00:00"))
                paper["updated_date"] = dt.strftime("%Y-%m-%d")
            except ValueError:
                paper["updated_date"] = updated_elem.text[:10]

        # URLs
        paper["arxiv_url"] = f"https://arxiv.org/abs/{paper['arxiv_id']}"
        paper["pdf_url"] = f"https://arxiv.org/pdf/{paper['arxiv_id']}.pdf"

        # No HuggingFace URL for direct arXiv imports
        paper["huggingface_url"] = None
        paper["upvotes"] = 0  # Not available from arXiv

        papers.append(paper)

    return papers


def fetch_arxiv_papers(
    search_query: str,
    max_results: int = 50,
    sort_by: str = "submittedDate",
    sort_order: str = "descending"
) -> list:
    """
    Fetch papers from arXiv API with rate limiting.

    Args:
        search_query: arXiv query string
        max_results: Maximum papers to fetch
        sort_by: Sort field (submittedDate, relevance, lastUpdatedDate)
        sort_order: ascending or descending

    Returns:
        List of paper dicts
    """
    all_papers = []
    start = 0

    while len(all_papers) < max_results:
        # Calculate batch size
        batch_size = min(ARXIV_MAX_RESULTS_PER_REQUEST, max_results - len(all_papers))

        params = {
            "search_query": search_query,
            "start": start,
            "max_results": batch_size,
            "sortBy": sort_by,
            "sortOrder": sort_order
        }

        url = f"{ARXIV_API_BASE}?{urlencode(params)}"
        print(f"Fetching from arXiv: start={start}, max={batch_size}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()

            papers = parse_arxiv_response(response.text)

            if not papers:
                # No more results
                break

            all_papers.extend(papers)
            start += len(papers)

            # If we got fewer than requested, we've reached the end
            if len(papers) < batch_size:
                break

            # Rate limiting
            if len(all_papers) < max_results:
                print(f"  Rate limiting: waiting {ARXIV_RATE_LIMIT}s...")
                time.sleep(ARXIV_RATE_LIMIT)

        except requests.RequestException as e:
            print(f"Error fetching from arXiv: {e}")
            break

    print(f"Fetched {len(all_papers)} papers from arXiv")
    return all_papers[:max_results]


def import_arxiv_paper(paper: dict, fetch_full_text: bool = False) -> dict:
    """
    Import single paper with LLM analysis.

    Args:
        paper: Paper dict from parse_arxiv_response
        fetch_full_text: Whether to download and extract PDF

    Returns:
        Metadata dict if successful, empty dict on failure
    """
    arxiv_id = paper.get("arxiv_id")
    print(f"\nImporting paper: {arxiv_id}")
    print(f"  Title: {paper.get('title', '')[:60]}...")

    # Ensure we have abstract
    if not paper.get("abstract"):
        print("  Fetching abstract from arXiv...")
        paper["abstract"] = fetch_arxiv_abstract(arxiv_id)
        time.sleep(ARXIV_RATE_LIMIT)

    if not paper.get("title"):
        print(f"  Error: Could not fetch paper details for {arxiv_id}")
        return {}

    # Fetch full text if requested
    full_text = ""
    if fetch_full_text:
        full_text = fetch_arxiv_pdf_text(arxiv_id)
        time.sleep(ARXIV_RATE_LIMIT)

    # Analyze with LLM
    print("  Analyzing paper with LLM...")
    analysis = analyze_paper(paper, full_text)

    # Add source field to indicate this came from arXiv directly
    # Modify the save to include arXiv-specific fields
    paper["source"] = "arxiv"

    # Save
    metadata_path, markdown_path = save_paper(paper, analysis)
    print(f"  Saved: {metadata_path.name}")

    return paper


def import_by_category(
    categories: list,
    days: int = 7,
    limit: int = 50,
    full_text: bool = False,
    dry_run: bool = False
) -> tuple:
    """
    Import recent papers from arXiv categories.

    Args:
        categories: List of arXiv categories (e.g., ["cs.AI"])
        days: How many days back to look
        limit: Maximum papers to import
        full_text: Whether to fetch full PDFs
        dry_run: Preview without importing

    Returns:
        Tuple of (success_count, skip_count, fail_count)
    """
    print("=" * 60)
    print("arXiv Papers Import (by Category)")
    print("=" * 60)
    print(f"Categories: {', '.join(categories)}")
    print(f"Days back: {days}")
    print(f"Limit: {limit}")

    # Build query
    search_query = build_arxiv_query(categories=categories)
    print(f"Query: {search_query}")

    # Fetch papers
    papers = fetch_arxiv_papers(search_query, max_results=limit)

    if not papers:
        print("No papers found.")
        return 0, 0, 0

    # Filter by date if specified
    if days > 0:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        papers = [p for p in papers if p.get("published_date", "9999") >= cutoff]
        print(f"After date filter (>= {cutoff}): {len(papers)} papers")

    # Get existing papers
    existing_ids = get_existing_paper_ids()
    print(f"Already in library: {len(existing_ids)} papers")

    # Filter out existing
    new_papers = [p for p in papers if p["arxiv_id"] not in existing_ids]
    print(f"New papers to import: {len(new_papers)}")

    if dry_run:
        print("\nDRY RUN - Papers that would be imported:")
        for i, paper in enumerate(new_papers, 1):
            print(f"  [{i}] {paper['title'][:60]}...")
            print(f"      arXiv: {paper['arxiv_id']} | Published: {paper.get('published_date', 'unknown')}")
            print(f"      Categories: {', '.join(paper.get('categories', [])[:3])}")
        return len(new_papers), len(papers) - len(new_papers), 0

    if not new_papers:
        print("No new papers to import.")
        return 0, len(papers), 0

    # Import papers
    return _import_papers(new_papers, full_text, len(papers) - len(new_papers))


def import_by_query(
    query: str,
    limit: int = 50,
    full_text: bool = False,
    dry_run: bool = False
) -> tuple:
    """
    Import papers matching search query.

    Args:
        query: Search query (free text or arXiv syntax)
        limit: Maximum papers to import
        full_text: Whether to fetch full PDFs
        dry_run: Preview without importing

    Returns:
        Tuple of (success_count, skip_count, fail_count)
    """
    print("=" * 60)
    print("arXiv Papers Import (by Query)")
    print("=" * 60)
    print(f"Query: {query}")
    print(f"Limit: {limit}")

    # Build query
    search_query = build_arxiv_query(query=query)
    print(f"API Query: {search_query}")

    # Fetch papers
    papers = fetch_arxiv_papers(search_query, max_results=limit, sort_by="relevance")

    if not papers:
        print("No papers found.")
        return 0, 0, 0

    # Get existing papers
    existing_ids = get_existing_paper_ids()
    print(f"Already in library: {len(existing_ids)} papers")

    # Filter out existing
    new_papers = [p for p in papers if p["arxiv_id"] not in existing_ids]
    print(f"New papers to import: {len(new_papers)}")

    if dry_run:
        print("\nDRY RUN - Papers that would be imported:")
        for i, paper in enumerate(new_papers, 1):
            print(f"  [{i}] {paper['title'][:60]}...")
            print(f"      arXiv: {paper['arxiv_id']} | Published: {paper.get('published_date', 'unknown')}")
        return len(new_papers), len(papers) - len(new_papers), 0

    if not new_papers:
        print("No new papers to import.")
        return 0, len(papers), 0

    # Import papers
    return _import_papers(new_papers, full_text, len(papers) - len(new_papers))


def _import_papers(papers: list, full_text: bool, skipped: int) -> tuple:
    """
    Helper to import a list of papers.

    Returns:
        Tuple of (success_count, skip_count, fail_count)
    """
    success = 0
    failed = 0

    for i, paper in enumerate(papers, 1):
        print(f"\n[{i}/{len(papers)}] {paper['title'][:50]}...")

        try:
            result = import_arxiv_paper(paper, fetch_full_text=full_text)
            if result:
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  Error: {e}")
            failed += 1

        # Rate limiting between papers
        if i < len(papers):
            time.sleep(ARXIV_RATE_LIMIT)

    print("\n" + "=" * 60)
    print("Import complete!")
    print(f"  Imported: {success}")
    print(f"  Skipped (existing): {skipped}")
    print(f"  Failed: {failed}")
    print("=" * 60)

    return success, skipped, failed


def main():
    parser = argparse.ArgumentParser(
        description="Import papers directly from arXiv API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python arxiv_papers.py --category cs.AI                 # Recent AI papers
    python arxiv_papers.py --category cs.LG --days 14       # Last 14 days
    python arxiv_papers.py --category cs.AI,cs.CL --limit 20  # Multiple categories
    python arxiv_papers.py --query "large language models"  # Free text search
    python arxiv_papers.py --query "ti:transformer"         # Title search
    python arxiv_papers.py --single 2401.12345              # Single paper
        """
    )

    # Discovery methods (mutually exclusive)
    discovery = parser.add_mutually_exclusive_group(required=True)
    discovery.add_argument(
        "--category",
        help="arXiv category(ies), comma-separated (e.g., cs.AI or cs.AI,cs.LG)"
    )
    discovery.add_argument(
        "--query",
        help="Search query (free text or arXiv syntax like ti:, au:, abs:)"
    )
    discovery.add_argument(
        "--single",
        help="Import single paper by arXiv ID"
    )

    # Filters and options
    parser.add_argument(
        "--days", type=int, default=7,
        help="Days back to look (default: 7)"
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Maximum papers to fetch (default: 50)"
    )
    parser.add_argument(
        "--full-text", action="store_true",
        help="Download and extract PDFs for all papers"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without importing"
    )

    args = parser.parse_args()

    if args.single:
        # Import single paper
        paper = {
            "arxiv_id": args.single,
            "arxiv_url": f"https://arxiv.org/abs/{args.single}",
            "pdf_url": f"https://arxiv.org/pdf/{args.single}.pdf",
            "huggingface_url": None,
            "upvotes": 0
        }

        # Check if already exists
        existing_ids = get_existing_paper_ids()
        if args.single in existing_ids:
            print(f"Paper {args.single} already in library. Skipping.")
            return

        # Fetch and import
        print(f"Fetching paper {args.single}...")
        paper["abstract"] = fetch_arxiv_abstract(args.single)
        time.sleep(ARXIV_RATE_LIMIT)

        # Parse more details from arXiv
        search_query = f"id:{args.single}"
        papers = fetch_arxiv_papers(search_query, max_results=1)
        if papers:
            paper.update(papers[0])

        result = import_arxiv_paper(paper, fetch_full_text=args.full_text)
        if result:
            print("\nPaper imported successfully!")
        else:
            print("\nFailed to import paper.")
            sys.exit(1)

    elif args.category:
        # Import by category
        categories = [c.strip() for c in args.category.split(",")]
        success, skipped, failed = import_by_category(
            categories=categories,
            days=args.days,
            limit=args.limit,
            full_text=args.full_text,
            dry_run=args.dry_run
        )

        if failed > 0 and success == 0:
            sys.exit(1)

    elif args.query:
        # Import by query
        success, skipped, failed = import_by_query(
            query=args.query,
            limit=args.limit,
            full_text=args.full_text,
            dry_run=args.dry_run
        )

        if failed > 0 and success == 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
