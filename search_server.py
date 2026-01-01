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

from llm_client import LLMClient

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
    # Search across multiple fields with OR grouping

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


# === AI Chat Interface ===

# Initialize LLM client
llm = LLMClient()

LIBRARY_SYSTEM_PROMPT = """You are a helpful assistant for a YouTube learning library containing 1,708 indexed video transcripts.

The library covers topics including:
- AI/ML, Security, DevOps, Databases, Programming, Web Development, Career, Entrepreneurship

FORMAT YOUR RESPONSES FOR A CHAT INTERFACE:
- Use **bold** for video titles and key terms
- Use bullet points (-) for lists, not numbered lists
- Use ### for section headers sparingly
- Keep responses concise - 2-4 recommended videos max
- DO NOT use markdown tables - use bullet lists instead
- Include timestamps like [00:05:30] when referencing specific sections

When users ask questions:
1. Recommend 2-4 most relevant videos with brief explanations
2. Mention difficulty level and duration
3. Reference specific sections with timestamps when helpful
4. Suggest what to explore next

Example format:
**Video Title** (10m, intermediate)
Brief explanation of why this is relevant.

Be concise and scannable. Focus on connecting users with the right content."""


def format_search_results_for_llm(results: list) -> str:
    """Format search results as context for the LLM."""
    if not results:
        return "No matching videos found."

    lines = []
    for i, r in enumerate(results[:10], 1):
        duration = r.get("duration", "")
        difficulty = r.get("facets", {}).get("difficulty", "")
        topics = ", ".join(r.get("facets", {}).get("topics", []))
        channel = r.get("channel", {}).get("name", "")

        lines.append(f"{i}. \"{r['title']}\"")
        lines.append(f"   Duration: {duration} | Difficulty: {difficulty} | Topics: {topics}")
        if channel:
            lines.append(f"   Channel: {channel}")

        # Add summary bullets if available
        summary = r.get("summary", [])
        if summary:
            for bullet in summary[:2]:
                lines.append(f"   - {bullet}")

        # Add matching sections
        sections = r.get("matching_sections", [])
        if sections:
            lines.append("   Key sections:")
            for sec in sections[:2]:
                lines.append(f"     [{sec['timestamp']}] {sec['title']}")

        lines.append("")

    return "\n".join(lines)


@app.route('/api/chat', methods=['POST'])
def api_chat():
    """
    AI-powered conversational search interface.

    Request body:
    {
        "messages": [
            {"role": "user", "content": "Find videos about Kubernetes"},
            {"role": "assistant", "content": "I found several..."},
            {"role": "user", "content": "Show me the security ones"}
        ]
    }

    Returns:
    {
        "response": "AI response text",
        "search_results": [...],  // Videos found (if search was performed)
        "query_used": "..."       // Search query extracted (if any)
    }
    """
    try:
        data = request.get_json() or {}
        messages = data.get("messages", [])

        if not messages:
            return jsonify({"error": "No messages provided", "response": ""})

        # Get the latest user message
        user_message = messages[-1].get("content", "") if messages else ""

        # Search the library based on user query
        search_results = []
        if user_message:
            results = search_videos(user_message, limit=10)
            search_results = results.get("results", [])

        # Build context with search results
        search_context = format_search_results_for_llm(search_results)

        # Create augmented message with search context
        augmented_content = f"""User query: {user_message}

Here are relevant videos from the library:
{search_context}

Based on these search results, help the user find what they're looking for."""

        # Build chat messages for LLM
        chat_messages = []
        # Add conversation history (excluding the last message which we augment)
        for msg in messages[:-1]:
            chat_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        # Add augmented last message
        chat_messages.append({
            "role": "user",
            "content": augmented_content
        })

        # Get LLM response
        response = llm.chat(chat_messages, system=LIBRARY_SYSTEM_PROMPT)

        if not response:
            response = "I'm having trouble connecting to the AI. Here are the search results I found:\n\n" + search_context

        return jsonify({
            "response": response,
            "search_results": search_results,
            "query_used": user_message
        })

    except Exception as e:
        return jsonify({"error": str(e), "response": ""})


@app.route('/api/chat/simple', methods=['POST'])
def api_chat_simple():
    """
    Simplified chat endpoint - just send a message, get a response.

    Request body:
    {
        "message": "Find videos about Kubernetes security"
    }

    Returns:
    {
        "response": "AI response",
        "videos": [...]
    }
    """
    try:
        data = request.get_json() or {}
        message = data.get("message", "")

        if not message:
            return jsonify({"error": "No message provided", "response": ""})

        # Search
        results = search_videos(message, limit=10)
        search_results = results.get("results", [])

        # Format for LLM
        search_context = format_search_results_for_llm(search_results)

        prompt = f"""User is searching the video library: "{message}"

Here are the matching videos:
{search_context}

Provide a helpful response recommending the most relevant videos. Be concise."""

        response = llm.generate(prompt, system=LIBRARY_SYSTEM_PROMPT)

        if not response:
            response = f"I found {len(search_results)} videos matching your query. Here are the top results."

        return jsonify({
            "response": response,
            "videos": search_results
        })

    except Exception as e:
        return jsonify({"error": str(e), "response": ""})


@app.route('/api/smart-search')
def api_smart_search():
    """
    AI-enhanced search with reranking and summarization.

    Query params:
        q       - Search query (required)
        limit   - Max results (default 10, max 20)

    Returns:
    {
        "query": "kubernetes security",
        "results": [
            {
                ...standard fields...,
                "relevance_explanation": "Why this video matches",
                "key_concepts": ["concept1", "concept2"]
            }
        ],
        "suggestions": ["related topic 1", "related topic 2"],
        "learning_path": ["beginner video", "intermediate video", "advanced video"]
    }
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required", "results": []})

    limit = min(int(request.args.get('limit', 10)), 20)

    try:
        # Step 1: Get initial Whoosh results (fetch more than needed for reranking)
        raw_results = search_videos(query, limit=50)
        all_results = raw_results.get("results", [])

        if not all_results:
            return jsonify({
                "query": query,
                "results": [],
                "suggestions": [],
                "learning_path": []
            })

        # Step 2: Format results for LLM reranking
        video_list = []
        for i, r in enumerate(all_results[:30]):  # Limit to 30 for prompt size
            video_list.append(
                f"{i+1}. \"{r['title']}\" ({r.get('duration', '')} | {r.get('facets', {}).get('difficulty', '')})"
            )
        videos_text = "\n".join(video_list)

        # Step 3: Ask LLM to rerank and analyze
        rerank_prompt = f"""Given this search query: "{query}"

Here are video search results ranked by text matching:
{videos_text}

Tasks:
1. Select the TOP 5 most relevant videos for this query (by number)
2. For each selected video, explain WHY it's relevant in 1 sentence
3. List 2-3 related topics the user might want to explore
4. Suggest a learning path (beginner -> advanced order) from the top results

Format your response EXACTLY as JSON:
{{
  "top_videos": [
    {{"rank": 1, "number": X, "explanation": "Why relevant"}},
    {{"rank": 2, "number": X, "explanation": "Why relevant"}},
    ...
  ],
  "related_topics": ["topic1", "topic2", "topic3"],
  "learning_path": [X, Y, Z]  // video numbers in suggested learning order
}}

Return ONLY valid JSON, no other text."""

        llm_response = llm.generate(rerank_prompt, timeout=60)

        # Step 4: Parse LLM response
        reranked_results = []
        suggestions = []
        learning_path = []

        try:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', llm_response)
            if json_match:
                parsed = json.loads(json_match.group())

                # Build reranked results
                top_videos = parsed.get("top_videos", [])
                for item in top_videos[:limit]:
                    video_num = item.get("number", 1) - 1  # Convert to 0-indexed
                    if 0 <= video_num < len(all_results):
                        result = all_results[video_num].copy()
                        result["relevance_explanation"] = item.get("explanation", "")
                        result["ai_rank"] = item.get("rank", 0)
                        reranked_results.append(result)

                suggestions = parsed.get("related_topics", [])[:5]

                # Build learning path from video numbers
                path_nums = parsed.get("learning_path", [])
                for num in path_nums[:5]:
                    if isinstance(num, int) and 0 < num <= len(all_results):
                        learning_path.append(all_results[num - 1]["title"])

        except (json.JSONDecodeError, KeyError, IndexError):
            # Fallback: use original ranking
            reranked_results = all_results[:limit]

        # If parsing failed or returned empty, use original results
        if not reranked_results:
            reranked_results = all_results[:limit]

        return jsonify({
            "query": query,
            "total_found": len(all_results),
            "results": reranked_results,
            "suggestions": suggestions,
            "learning_path": learning_path
        })

    except Exception as e:
        return jsonify({"error": str(e), "results": []})


@app.route('/api/build-prompt', methods=['POST'])
def api_build_prompt():
    """
    Generate a prompt from selected library content.

    Request body:
    {
        "goal": "Implement secure Kubernetes deployment",
        "type": "task",  // learning | task | research
        "video_slugs": ["slug1", "slug2"],  // Optional: specific videos
        "search_query": "kubernetes security",  // Optional: auto-find videos
        "limit": 3  // Number of videos for auto-search
    }

    Returns:
    {
        "prompt": "Generated prompt text...",
        "sources": ["slug1", "slug2"],
        "context_chars": 15000,
        "prompt_type": "task"
    }
    """
    try:
        from prompt_builder import PromptBuilder

        data = request.get_json() or {}
        goal = data.get("goal", "").strip()

        if not goal:
            return jsonify({"error": "Goal is required", "prompt": ""})

        prompt_type = data.get("type", "task")
        video_slugs = data.get("video_slugs", [])
        search_query = data.get("search_query")
        limit = min(int(data.get("limit", 3)), 10)

        builder = PromptBuilder(llm)

        if video_slugs:
            # Use specified videos
            result = builder.build_prompt(goal, prompt_type, video_slugs)
        else:
            # Auto-search for relevant videos
            query = search_query or goal
            result = builder.quick_prompt(goal, query, limit)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "prompt": ""})


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
