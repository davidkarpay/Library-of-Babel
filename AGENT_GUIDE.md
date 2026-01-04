# Learning Library Agent Guide

This document provides context for AI agents accessing the Learning Library - a curated collection of AI/ML educational content including YouTube video transcripts and HuggingFace research papers.

## Overview

The library contains indexed educational content:
- **Videos**: YouTube video transcripts with timestamped sections and LLM-generated summaries
- **Papers**: Research papers from HuggingFace Daily Papers with abstracts and key insights

All content is analyzed by LLM to extract:
- Key insights and summaries
- Topic classification (ai-ml, nlp, security, etc.)
- Difficulty level (beginner, intermediate, advanced)
- Section breakdowns with descriptions

## Integration Methods

### 1. MCP Server (for Claude)

Connect Claude to the library using MCP:

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "learning-library": {
      "command": "python",
      "args": ["/path/to/mcp_docent_server.py"]
    }
  }
}
```

**Available MCP Tools:**
| Tool | Description |
|------|-------------|
| `search_library` | Search by keyword, filter by type/topic/difficulty |
| `recommend_by_topic` | Get curated recommendations for a topic |
| `get_learning_path` | Generate beginner→advanced learning progression |
| `find_related_content` | Find content related to a specific item |
| `get_whats_new` | Recently added content (last N days) |
| `get_content_excerpt` | Get transcript/paper excerpt |

### 2. REST API (when search_server.py is running)

**Search Endpoints:**
```
GET /api/search?q=<query>&type=all|video|paper&topic=<topic>&limit=20
GET /api/smart-search?q=<query>&limit=10   # AI-reranked results
```

**Docent Endpoints:**
```
GET  /api/docent/guide?goal=<learning_goal>
POST /api/docent/recommend  {context, interests, level, time_available}
GET  /api/docent/whats-new?days=7&type=all|video|paper
GET  /api/content/<type>/<id>
```

**Chat Endpoint:**
```
POST /api/chat
{
  "messages": [
    {"role": "user", "content": "Find videos about Kubernetes security"}
  ]
}
```

### 3. Cloudflare Worker API (Public, Always Available)

The Docent Worker provides a public API for external agents:

**Base URL:** `https://youtube-library-docent.dlkarpay.workers.dev`

**Endpoints:**
```
GET /api/search?q=<query>&type=video|paper|all&topic=<topic>&difficulty=<level>&limit=20
GET /api/recommend?topic=<topic>&level=beginner|intermediate|advanced&limit=10
GET /api/learning-path?goal=<learning_goal>
GET /api/whats-new?days=7&type=video|paper|all
GET /api/content/<id>
GET /api/stats
GET /api/facets
POST /api/chat  {"message": "...", "context": []}
```

**Example:**
```bash
curl "https://youtube-library-docent.dlkarpay.workers.dev/api/search?q=transformers&type=video&limit=5"
```

### 4. Direct library.json Access

Download and parse `library.json` for offline agent access:

```python
import requests
library = requests.get("https://library.davidkarpay.com/library.json").json()

# Structure:
{
  "entries": [...],           # All content metadata
  "total": 1713,
  "video_count": 1710,
  "paper_count": 3,
  "facets": {
    "topics": ["ai-ml", "security", ...],
    "formats": ["tutorial", "deep-dive", ...],
    "difficulties": ["beginner", "intermediate", "advanced"]
  },
  "channels": [...]
}
```

## Content Schema

### Video Entry
```json
{
  "id": "youtube_video_id",
  "content_type": "video",
  "title": "LLM-generated title",
  "url": "https://youtube.com/watch?v=...",
  "channel": {"name": "Channel Name", "slug": "channel-name"},
  "duration_seconds": 600,
  "facets": {
    "topics": ["ai-ml", "programming"],
    "format": "tutorial",
    "difficulty": "intermediate"
  },
  "summary": ["Key insight 1", "Key insight 2"],
  "sections": [
    {"start": 0, "end": 180, "title": "Section", "description": "..."}
  ],
  "added_date": "2026-01-03"
}
```

### Paper Entry
```json
{
  "id": "arxiv_id",
  "content_type": "paper",
  "title": "Paper title",
  "url": "https://huggingface.co/papers/...",
  "arxiv_url": "https://arxiv.org/abs/...",
  "authors": ["Author 1", "Author 2"],
  "abstract": "Full abstract text",
  "upvotes": 72,
  "published_date": "2026-01-02",
  "facets": {
    "topics": ["nlp", "efficiency"],
    "format": "research-paper",
    "difficulty": "advanced"
  },
  "summary": ["Main contribution", "Key finding"],
  "added_date": "2026-01-03"
}
```

## Topic Taxonomy

### Video Topics
`security`, `programming`, `ai-ml`, `entrepreneurship`, `devops`, `databases`, `web-development`, `career`, `other`

### Paper Topics
`nlp`, `computer-vision`, `multimodal`, `reinforcement-learning`, `robotics`, `ai-safety`, `efficiency`, `ai-ml`, `other`

### Formats
- Videos: `tutorial`, `deep-dive`, `news`, `interview`, `review`, `other`
- Papers: `research-paper`, `survey`, `benchmark`, `dataset`, `other`

### Difficulty Levels
- `beginner`: Accessible overview, minimal prerequisites
- `intermediate`: Requires ML/programming background
- `advanced`: Cutting-edge research, heavy math

## Example Agent Workflows

### 1. Research a Topic
```python
# Find beginner content on transformers
results = search_library(query="transformers", difficulty="beginner")

# Get a learning path
path = get_learning_path(goal="understand transformer architecture")

# Find recent papers
new_papers = get_whats_new(days=7, content_type="paper")
```

### 2. Prepare for Implementation
```python
# Find practical tutorials
tutorials = search_library(
    query="kubernetes deployment",
    content_type="video",
    format="tutorial"
)

# Get relevant paper for theory
papers = search_library(
    query="container orchestration",
    content_type="paper"
)

# Get transcript excerpt for context
excerpt = get_content_excerpt(item_id="video_id", max_chars=3000)
```

### 3. Stay Current
```python
# Get recent high-impact papers
new = get_whats_new(days=7, content_type="paper")
high_impact = [p for p in new["items"] if p.get("upvotes", 0) > 20]

# Find related content to a paper you're reading
related = find_related_content(item_id="2512.23959")
```

## Citation Format

When referencing content from this library:

- **Videos**: `[Title](youtube_url) at timestamp`
- **Papers**: `[Title](https://arxiv.org/abs/{arxiv_id})`

## Rate Limits

- API: 100 requests/minute per IP
- MCP: No rate limit (local)
- For bulk operations, use `library.json` directly

## Updates

- Papers: Daily sync at 2 PM UTC via GitHub Actions
- Videos: Manual import via CLI
- library.json: Regenerated after each import

---

*This guide is auto-generated. Last updated: 2026-01-04*
