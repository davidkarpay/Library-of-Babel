#!/usr/bin/env python3
"""
mcp_docent_server.py

MCP (Model Context Protocol) Server providing docent agent capabilities
for the learning library. Allows Claude and other MCP-compatible agents
to search, explore, and get recommendations from the library.

Usage:
    python mcp_docent_server.py               # Start server (stdio mode)

Claude Desktop config (claude_desktop_config.json):
{
    "mcpServers": {
        "learning-library": {
            "command": "python",
            "args": ["/path/to/mcp_docent_server.py"]
        }
    }
}

Tools provided:
    - search_library: Search videos and papers by keyword
    - recommend_by_topic: Get recommendations for a topic
    - get_learning_path: Generate beginner→advanced learning path
    - find_related_content: Find content related to a specific item
    - get_whats_new: Get recently added content
    - get_content_excerpt: Get excerpt from a specific item
"""

import json
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Base directory
BASE_DIR = Path(__file__).parent
LIBRARY_JSON = BASE_DIR / "library.json"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
PAPERS_DIR = BASE_DIR / "papers"


# MCP Protocol implementation (simplified stdio-based)
class MCPServer:
    """Simple MCP server using JSON-RPC over stdio."""

    def __init__(self, name: str):
        self.name = name
        self.tools = {}
        self.library = None

    def tool(self, name: str, description: str, input_schema: dict):
        """Decorator to register a tool."""
        def decorator(func):
            self.tools[name] = {
                "name": name,
                "description": description,
                "inputSchema": input_schema,
                "handler": func
            }
            return func
        return decorator

    def load_library(self):
        """Load the library data."""
        if not LIBRARY_JSON.exists():
            return {"entries": [], "total": 0}
        with open(LIBRARY_JSON) as f:
            return json.load(f)

    def get_library(self):
        """Get cached library data."""
        if self.library is None:
            self.library = self.load_library()
        return self.library

    def handle_request(self, request: dict) -> dict:
        """Handle a JSON-RPC request."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": self.name,
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {}
                    }
                }
            }

        elif method == "tools/list":
            tools_list = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"]
                }
                for t in self.tools.values()
            ]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools_list}
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if tool_name not in self.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                }

            try:
                result = self.tools[tool_name]["handler"](tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                    }
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)}
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}
            }

    def run(self):
        """Run the server in stdio mode."""
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line)
                response = self.handle_request(request)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except KeyboardInterrupt:
                break


# Create server instance
server = MCPServer("learning-library-docent")


# Tool implementations
@server.tool(
    name="search_library",
    description="Search the learning library (videos and papers) by keyword or topic",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "content_type": {
                "type": "string",
                "enum": ["all", "video", "paper"],
                "description": "Filter by content type"
            },
            "topic": {"type": "string", "description": "Filter by topic"},
            "difficulty": {
                "type": "string",
                "enum": ["beginner", "intermediate", "advanced"],
                "description": "Filter by difficulty"
            },
            "limit": {"type": "integer", "default": 10, "description": "Max results"}
        },
        "required": ["query"]
    }
)
def search_library(args: dict) -> dict:
    """Search the library."""
    query = args.get("query", "").lower()
    content_type = args.get("content_type", "all")
    topic_filter = args.get("topic")
    difficulty_filter = args.get("difficulty")
    limit = args.get("limit", 10)

    library = server.get_library()
    results = []

    for entry in library.get("entries", []):
        # Content type filter
        entry_type = entry.get("content_type", "video")
        if content_type != "all" and entry_type != content_type:
            continue

        # Topic filter
        if topic_filter:
            topics = entry.get("facets", {}).get("topics", [])
            if topic_filter.lower() not in [t.lower() for t in topics]:
                continue

        # Difficulty filter
        if difficulty_filter:
            diff = entry.get("facets", {}).get("difficulty", "")
            if diff.lower() != difficulty_filter.lower():
                continue

        # Search in title, summary, abstract
        searchable = " ".join([
            entry.get("title", ""),
            " ".join(entry.get("summary", [])),
            entry.get("abstract", "")
        ]).lower()

        if query in searchable:
            results.append({
                "id": entry.get("id"),
                "title": entry.get("title"),
                "content_type": entry_type,
                "topics": entry.get("facets", {}).get("topics", []),
                "difficulty": entry.get("facets", {}).get("difficulty"),
                "url": entry.get("url"),
                "summary": entry.get("summary", [])[:2]
            })

        if len(results) >= limit:
            break

    return {
        "query": query,
        "results_count": len(results),
        "results": results
    }


@server.tool(
    name="recommend_by_topic",
    description="Get content recommendations for a specific topic",
    input_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic to get recommendations for"},
            "content_type": {
                "type": "string",
                "enum": ["all", "video", "paper"]
            },
            "difficulty": {
                "type": "string",
                "enum": ["beginner", "intermediate", "advanced"]
            },
            "limit": {"type": "integer", "default": 5}
        },
        "required": ["topic"]
    }
)
def recommend_by_topic(args: dict) -> dict:
    """Get recommendations for a topic."""
    topic = args.get("topic", "").lower()
    content_type = args.get("content_type", "all")
    difficulty = args.get("difficulty")
    limit = args.get("limit", 5)

    library = server.get_library()
    results = []

    for entry in library.get("entries", []):
        entry_type = entry.get("content_type", "video")
        if content_type != "all" and entry_type != content_type:
            continue

        topics = [t.lower() for t in entry.get("facets", {}).get("topics", [])]
        if topic not in topics:
            continue

        if difficulty:
            if entry.get("facets", {}).get("difficulty", "").lower() != difficulty.lower():
                continue

        results.append({
            "id": entry.get("id"),
            "title": entry.get("title"),
            "content_type": entry_type,
            "difficulty": entry.get("facets", {}).get("difficulty"),
            "url": entry.get("url"),
            "summary": entry.get("summary", [])[:1]
        })

        if len(results) >= limit:
            break

    return {
        "topic": topic,
        "recommendations_count": len(results),
        "recommendations": results
    }


@server.tool(
    name="get_learning_path",
    description="Generate a structured learning path from beginner to advanced",
    input_schema={
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Learning goal or topic"},
            "current_level": {
                "type": "string",
                "enum": ["beginner", "intermediate", "advanced"],
                "description": "Current skill level"
            },
            "max_items": {"type": "integer", "default": 10}
        },
        "required": ["goal"]
    }
)
def get_learning_path(args: dict) -> dict:
    """Generate a learning path."""
    goal = args.get("goal", "").lower()
    current_level = args.get("current_level", "beginner")
    max_items = args.get("max_items", 10)

    library = server.get_library()

    # Determine difficulty progression
    levels = ["beginner", "intermediate", "advanced"]
    start_idx = levels.index(current_level) if current_level in levels else 0

    path = []
    for level in levels[start_idx:]:
        level_items = []

        for entry in library.get("entries", []):
            if entry.get("facets", {}).get("difficulty", "").lower() != level:
                continue

            # Check if matches goal
            searchable = " ".join([
                entry.get("title", ""),
                " ".join(entry.get("facets", {}).get("topics", [])),
                " ".join(entry.get("summary", []))
            ]).lower()

            if goal in searchable:
                level_items.append({
                    "id": entry.get("id"),
                    "title": entry.get("title"),
                    "content_type": entry.get("content_type", "video"),
                    "url": entry.get("url"),
                    "why": f"{level.title()} level content on {goal}"
                })

                if len(level_items) >= 3:  # Max 3 per level
                    break

        path.extend(level_items)
        if len(path) >= max_items:
            break

    return {
        "goal": goal,
        "starting_level": current_level,
        "path_length": len(path),
        "path": path[:max_items]
    }


@server.tool(
    name="find_related_content",
    description="Find content related to a specific item by ID",
    input_schema={
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "Video ID or arXiv ID"},
            "limit": {"type": "integer", "default": 5}
        },
        "required": ["item_id"]
    }
)
def find_related_content(args: dict) -> dict:
    """Find related content."""
    item_id = args.get("item_id", "")
    limit = args.get("limit", 5)

    library = server.get_library()

    # Find the source item
    source = None
    for entry in library.get("entries", []):
        if entry.get("id") == item_id or entry.get("arxiv_id") == item_id:
            source = entry
            break

    if not source:
        return {"error": f"Item not found: {item_id}"}

    # Find related by matching topics
    source_topics = set(t.lower() for t in source.get("facets", {}).get("topics", []))
    related = []

    for entry in library.get("entries", []):
        if entry.get("id") == item_id:
            continue

        entry_topics = set(t.lower() for t in entry.get("facets", {}).get("topics", []))
        overlap = source_topics & entry_topics

        if overlap:
            related.append({
                "id": entry.get("id"),
                "title": entry.get("title"),
                "content_type": entry.get("content_type", "video"),
                "url": entry.get("url"),
                "matching_topics": list(overlap),
                "relevance": len(overlap) / len(source_topics) if source_topics else 0
            })

    # Sort by relevance
    related.sort(key=lambda x: x["relevance"], reverse=True)

    return {
        "source_item": source.get("title"),
        "source_topics": list(source_topics),
        "related_count": len(related[:limit]),
        "related": related[:limit]
    }


@server.tool(
    name="get_whats_new",
    description="Get recently added content (papers and videos)",
    input_schema={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 7, "description": "Look back N days"},
            "content_type": {
                "type": "string",
                "enum": ["all", "video", "paper"]
            },
            "limit": {"type": "integer", "default": 10}
        }
    }
)
def get_whats_new(args: dict) -> dict:
    """Get recently added content."""
    days = args.get("days", 7)
    content_type = args.get("content_type", "all")
    limit = args.get("limit", 10)

    library = server.get_library()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    recent = []
    by_topic = {}

    for entry in library.get("entries", []):
        added_date = entry.get("added_date", "")
        if added_date < cutoff:
            continue

        entry_type = entry.get("content_type", "video")
        if content_type != "all" and entry_type != content_type:
            continue

        recent.append({
            "id": entry.get("id"),
            "title": entry.get("title"),
            "content_type": entry_type,
            "added_date": added_date,
            "topics": entry.get("facets", {}).get("topics", []),
            "url": entry.get("url")
        })

        # Count by topic
        for topic in entry.get("facets", {}).get("topics", []):
            by_topic[topic] = by_topic.get(topic, 0) + 1

    # Sort by date (newest first)
    recent.sort(key=lambda x: x["added_date"], reverse=True)

    video_count = sum(1 for r in recent if r["content_type"] == "video")
    paper_count = sum(1 for r in recent if r["content_type"] == "paper")

    return {
        "period": f"Last {days} days",
        "summary": f"{paper_count} new papers, {video_count} new videos",
        "total_new": len(recent),
        "by_topic": by_topic,
        "items": recent[:limit]
    }


@server.tool(
    name="get_content_excerpt",
    description="Get an excerpt from a specific video transcript or paper",
    input_schema={
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "Video ID or arXiv ID"},
            "section_index": {
                "type": "integer",
                "description": "0-based section index (optional)"
            },
            "max_chars": {"type": "integer", "default": 2000}
        },
        "required": ["item_id"]
    }
)
def get_content_excerpt(args: dict) -> dict:
    """Get content excerpt."""
    item_id = args.get("item_id", "")
    section_index = args.get("section_index")
    max_chars = args.get("max_chars", 2000)

    library = server.get_library()

    # Find the item
    item = None
    for entry in library.get("entries", []):
        if entry.get("id") == item_id or entry.get("arxiv_id") == item_id:
            item = entry
            break

    if not item:
        return {"error": f"Item not found: {item_id}"}

    result = {
        "id": item.get("id"),
        "title": item.get("title"),
        "content_type": item.get("content_type", "video"),
        "url": item.get("url")
    }

    # Get sections if available
    sections = item.get("sections", [])
    if sections:
        if section_index is not None and 0 <= section_index < len(sections):
            result["section"] = sections[section_index]
        else:
            result["sections"] = sections[:5]  # First 5 sections

    # Get summary
    result["summary"] = item.get("summary", [])

    # Try to read full content
    filename = item.get("_filename") or re.sub(r"[^\w-]", "-", item.get("title", "").lower())[:60]
    content_type = item.get("content_type", "video")

    if content_type == "paper":
        md_path = PAPERS_DIR / f"{filename}.md"
    else:
        md_path = TRANSCRIPTS_DIR / f"{filename}.md"

    if md_path.exists():
        content = md_path.read_text()
        result["excerpt"] = content[:max_chars]
        if len(content) > max_chars:
            result["excerpt"] += "..."
            result["truncated"] = True

    return result


if __name__ == "__main__":
    print("Learning Library Docent MCP Server", file=sys.stderr)
    print("Running in stdio mode...", file=sys.stderr)
    server.run()
