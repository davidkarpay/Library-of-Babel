#!/usr/bin/env python3
"""
search_server.py

Full-text search server for the YouTube learning library.
Serves the static site and provides a search API with transcript indexing.

Usage:
    python search_server.py              # Start server on port 5000
    python search_server.py --rebuild-index  # Rebuild search index only
    python search_server.py --stats      # Show index statistics

Environment Variables:
    SEARCH_PORT - Server port (default: 5000)
    SEARCH_HOST - Server host (default: 127.0.0.1)

Requires:
    pip install flask whoosh
"""

import argparse
import json
import os
import re
from pathlib import Path

try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("Error: Flask is required. Install with: pip install flask")
    exit(1)

try:
    from whoosh.fields import Schema, TEXT, ID, STORED, NUMERIC
    from whoosh.index import create_in, open_dir, exists_in
    from whoosh.qparser import MultifieldParser, OrGroup
    from whoosh.highlight import HtmlFormatter, ContextFragmenter
    from whoosh import scoring
except ImportError:
    print("Error: Whoosh is required. Install with: pip install whoosh")
    exit(1)

# === Configuration ===
BASE_DIR = Path(__file__).parent
SITE_DIR = BASE_DIR / "site"
INDEX_DIR = BASE_DIR / "search_index"
METADATA_DIR = BASE_DIR / "metadata"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"

# === Whoosh Schema ===
schema = Schema(
    video_id=ID(stored=True, unique=True),
    slug=ID(stored=True),
    title=TEXT(stored=True),
    summary=TEXT(stored=True),
    topics=TEXT(stored=True),
    format=STORED,
    difficulty=STORED,
    channel_name=TEXT(stored=True),
    channel_slug=STORED,
    duration_seconds=NUMERIC(stored=True),
    url=STORED,
    added_date=STORED,
    transcript=TEXT,  # Full text, searchable but not stored
    sections=STORED   # JSON string of sections
)

# === Flask App ===
app = Flask(__name__, static_folder=str(SITE_DIR), static_url_path='')


def extract_plain_text(markdown_content: str) -> str:
    """Strip markdown formatting to get plain text for indexing."""
    text = markdown_content
    # Remove markdown headers
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    # Remove links but keep text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove bold/italic
    text = re.sub(r'\*+([^*]+)\*+', r'\1', text)
    # Remove timestamp spans
    text = re.sub(r'<span class="timestamp">[^<]+</span>', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def build_index():
    """Build or rebuild the search index from metadata and transcripts."""
    INDEX_DIR.mkdir(exist_ok=True)

    print("Building search index...")

    ix = create_in(str(INDEX_DIR), schema)
    writer = ix.writer()

    count = 0
    for json_file in METADATA_DIR.glob("*.json"):
        slug = json_file.stem

        try:
            # Load metadata
            with open(json_file) as f:
                meta = json.load(f)

            # Load transcript text
            transcript_path = TRANSCRIPTS_DIR / f"{slug}.md"
            transcript_text = ""
            if transcript_path.exists():
                raw_content = transcript_path.read_text()
                transcript_text = extract_plain_text(raw_content)

            # Extract channel info
            channel = meta.get("channel", {})
            channel_name = channel.get("name", "")
            channel_slug = channel.get("slug", "")

            # Build summary text
            summary_list = meta.get("summary", [])
            summary_text = " ".join(summary_list) if summary_list else ""

            # Build topics text
            topics_list = meta.get("facets", {}).get("topics", [])
            topics_text = " ".join(topics_list)

            writer.add_document(
                video_id=meta.get("id", ""),
                slug=slug,
                title=meta.get("title", ""),
                summary=summary_text,
                topics=topics_text,
                format=meta.get("facets", {}).get("format", ""),
                difficulty=meta.get("facets", {}).get("difficulty", ""),
                channel_name=channel_name,
                channel_slug=channel_slug,
                duration_seconds=meta.get("duration_seconds", 0),
                url=meta.get("url", ""),
                added_date=meta.get("added_date", ""),
                transcript=transcript_text,
                sections=json.dumps(meta.get("sections", []))
            )
            count += 1
            print(f"  Indexed: {slug}")

        except Exception as e:
            print(f"  Error indexing {json_file.name}: {e}")

    writer.commit()
    print(f"\nIndex built with {count} documents")
    return ix


def get_index():
    """Get or create the search index."""
    if exists_in(str(INDEX_DIR)):
        return open_dir(str(INDEX_DIR))
    else:
        return build_index()


def format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration."""
    if not seconds:
        return "0m"
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        return f"{mins}m"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"


def format_timestamp(seconds: int) -> str:
    """Format seconds as HH:MM:SS timestamp."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def find_matching_sections(sections_json: str, query_terms: list, url: str) -> list:
    """Find sections that contain query terms."""
    try:
        sections = json.loads(sections_json) if sections_json else []
    except json.JSONDecodeError:
        return []

    matching = []
    query_lower = [t.lower() for t in query_terms]

    for section in sections:
        title = section.get("title", "").lower()
        desc = section.get("description", "").lower()
        combined = f"{title} {desc}"

        # Check if any query term appears in this section
        if any(term in combined for term in query_lower):
            start = section.get("start", 0)
            matching.append({
                "start": start,
                "title": section.get("title", ""),
                "description": section.get("description", ""),
                "timestamp": format_timestamp(start),
                "timestamp_url": f"{url}&t={start}s"
            })

    return matching[:3]  # Limit to top 3 matching sections


def search_videos(query: str, limit: int = 20, offset: int = 0, filters: dict = None):
    """
    Search videos with query and optional filters.

    Returns dict with query, total, and results list.
    """
    ix = get_index()

    # Parse query to search multiple fields with boosting
    parser = MultifieldParser(
        ["title", "summary", "transcript", "channel_name", "topics"],
        schema=ix.schema,
        group=OrGroup
    )
    # Boost title matches
    parser.add_plugin(None)  # Reset plugins

    try:
        q = parser.parse(query)
    except Exception:
        # Fallback to simple query
        q = parser.parse(f'"{query}"')

    # Extract query terms for section matching
    query_terms = query.split()

    with ix.searcher(weighting=scoring.BM25F()) as searcher:
        # Apply filters if provided
        filter_q = None
        if filters:
            filter_parts = []
            if filters.get("topic"):
                filter_parts.append(f'topics:{filters["topic"]}')
            if filters.get("format"):
                filter_parts.append(f'format:{filters["format"]}')
            if filters.get("difficulty"):
                filter_parts.append(f'difficulty:{filters["difficulty"]}')
            if filters.get("channel"):
                filter_parts.append(f'channel_slug:{filters["channel"]}')

            if filter_parts:
                filter_str = " AND ".join(filter_parts)
                filter_q = parser.parse(filter_str)

        results = searcher.search(q, limit=offset + limit, filter=filter_q)

        # Format results
        formatted = []
        highlighter = HtmlFormatter(tagname="mark")

        for hit in results[offset:offset + limit]:
            # Get highlighted fields
            title_highlighted = hit.highlights("title", top=1) or hit["title"]
            summary_highlighted = hit.highlights("summary", top=3) or hit["summary"]

            # Find matching sections
            matching_sections = find_matching_sections(
                hit.get("sections", "[]"),
                query_terms,
                hit.get("url", "")
            )

            # Parse summary back to list
            summary_text = hit.get("summary", "")
            # Try to split on common patterns
            summary_list = [s.strip() for s in summary_text.split(". ") if s.strip()]

            formatted.append({
                "video_id": hit["video_id"],
                "slug": hit["slug"],
                "title": hit["title"],
                "title_highlighted": title_highlighted,
                "summary": summary_list[:3],
                "summary_highlighted": summary_highlighted,
                "url": hit.get("url", ""),
                "duration_seconds": hit.get("duration_seconds", 0),
                "duration": format_duration(hit.get("duration_seconds", 0)),
                "facets": {
                    "topics": hit.get("topics", "").split() if hit.get("topics") else [],
                    "format": hit.get("format", ""),
                    "difficulty": hit.get("difficulty", "")
                },
                "channel": {
                    "name": hit.get("channel_name", ""),
                    "slug": hit.get("channel_slug", "")
                },
                "added_date": hit.get("added_date", ""),
                "matching_sections": matching_sections,
                "score": hit.score
            })

        return {
            "query": query,
            "total": len(results),
            "results": formatted
        }


# === Flask Routes ===

@app.route('/')
def index():
    """Serve the main index page."""
    return send_from_directory(SITE_DIR, 'index.html')


@app.route('/<path:path>')
def static_files(path):
    """Serve static files from site directory."""
    return send_from_directory(SITE_DIR, path)


@app.route('/api/search')
def api_search():
    """Search API endpoint."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required", "results": []})

    limit = min(int(request.args.get('limit', 20)), 100)
    offset = int(request.args.get('offset', 0))

    filters = {}
    if request.args.get('topic'):
        filters['topic'] = request.args.get('topic')
    if request.args.get('format'):
        filters['format'] = request.args.get('format')
    if request.args.get('difficulty'):
        filters['difficulty'] = request.args.get('difficulty')
    if request.args.get('channel'):
        filters['channel'] = request.args.get('channel')

    try:
        results = search_videos(query, limit, offset, filters if filters else None)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e), "results": []})


@app.route('/api/rebuild-index', methods=['POST'])
def api_rebuild():
    """Rebuild the search index."""
    try:
        build_index()
        ix = get_index()
        return jsonify({
            "status": "ok",
            "message": "Index rebuilt",
            "documents": ix.doc_count()
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/stats')
def api_stats():
    """Get index statistics."""
    try:
        ix = get_index()
        return jsonify({
            "documents": ix.doc_count(),
            "index_path": str(INDEX_DIR)
        })
    except Exception as e:
        return jsonify({"error": str(e)})


# === Main ===

def main():
    parser = argparse.ArgumentParser(description='YouTube Library Search Server')
    parser.add_argument('--rebuild-index', action='store_true',
                        help='Rebuild search index and exit')
    parser.add_argument('--stats', action='store_true',
                        help='Show index statistics and exit')
    parser.add_argument('--port', type=int, default=None,
                        help='Server port (default: 5000 or SEARCH_PORT env)')
    parser.add_argument('--host', type=str, default=None,
                        help='Server host (default: 127.0.0.1 or SEARCH_HOST env)')

    args = parser.parse_args()

    if args.rebuild_index:
        build_index()
        return

    if args.stats:
        if exists_in(str(INDEX_DIR)):
            ix = open_dir(str(INDEX_DIR))
            print(f"Documents indexed: {ix.doc_count()}")
            print(f"Index location: {INDEX_DIR}")
        else:
            print("No index found. Run with --rebuild-index to create one.")
        return

    # Ensure index exists
    if not exists_in(str(INDEX_DIR)):
        print("Building search index for the first time...")
        build_index()
    else:
        ix = get_index()
        print(f"Loaded search index with {ix.doc_count()} documents")

    # Get server config
    port = args.port or int(os.environ.get('SEARCH_PORT', 5000))
    host = args.host or os.environ.get('SEARCH_HOST', '127.0.0.1')
    debug = os.environ.get('SEARCH_DEBUG', 'false').lower() == 'true'

    print(f"\nStarting server at http://{host}:{port}")
    print("Press Ctrl+C to stop\n")

    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
