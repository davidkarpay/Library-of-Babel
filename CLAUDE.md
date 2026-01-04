# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A personal learning library that combines YouTube video transcripts and HuggingFace research papers. Content is analyzed by LLM to generate metadata (sections, summaries, topics, difficulty levels) and served via a static HTML site with AI-powered search.

## Commands

```bash
# Add a new video to the library
python youtube_transcript_to_md.py "https://youtube.com/watch?v=..."

# Batch import from markdown file containing URLs
python batch_import.py <markdown_file>

# Import all videos from a YouTube channel
python channel_import.py "https://youtube.com/@ChannelName"
python channel_import.py "https://youtube.com/@ChannelName" --limit 10 --dry-run

# Manually add video (paste transcript when no captions available)
python manual_import.py "https://youtube.com/watch?v=..."

# Regenerate the static HTML site
python library.py

# Reprocess all existing transcripts (re-fetch and regenerate metadata)
python reprocess_transcripts.py

# Backfill channel info for existing videos
python backfill_channels.py

# Start the search server (enables full-text search)
python search_server.py
python search_server.py --rebuild-index  # Rebuild search index

# === PAPER IMPORT ===

# Import papers from HuggingFace daily papers
python huggingface_papers.py                        # Import today's papers
python huggingface_papers.py --date 2026-01-02      # Specific date
python huggingface_papers.py --limit 10             # Limit number
python huggingface_papers.py --min-upvotes 20       # Filter by upvotes
python huggingface_papers.py --dry-run              # Preview only

# Automated daily sync (papers)
python sync_daily.py                    # Sync today's papers
python sync_daily.py --backfill 7       # Sync last 7 days
python sync_daily.py --commit           # Commit changes after sync

# === AGENT INTEGRATION ===

# Start MCP docent server (for Claude integration)
python mcp_docent_server.py

# Import from YouTube history (liked videos)
python youtube_history.py               # Interactive review
python youtube_history.py --auto-add    # Auto-add all relevant
```

## Failed Transcript Workflow

When videos fail (no captions available), they are logged to `pending.json`:
1. `batch_import.py` logs failures automatically
2. Review `pending.json` to see failed videos
3. For important videos: run `python manual_import.py <url>` and paste transcript
4. Successfully imported videos are removed from pending.json

## Environment Variables

- `OLLAMA_URL` - Ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_MODEL` - Model for LLM analysis (default: `gpt-oss:120b-cloud`)
- `SEARCH_PORT` - Search server port (default: `5000`)
- `SEARCH_HOST` - Search server host (default: `127.0.0.1`)

## Architecture

**Data Flow:**
1. `youtube_transcript_to_md.py` fetches transcript via `youtube-transcript-api`
2. Chunks transcript into ~3min sections, calls Ollama for title/description per section
3. Generates overall title, summary bullets, and facets (topic/format/difficulty)
4. Outputs: `transcripts/{slug}.md` + `metadata/{slug}.json`
5. `library.py` reads all metadata JSON, renders Jinja2 templates to `site/`

**Directory Structure:**
```
transcripts/    → Markdown files with full timestamped video transcripts
papers/         → Markdown files with paper analysis and excerpts
metadata/       → JSON files with structured data (videos and papers)
templates/      → Jinja2 templates (base, index, topic, channel, letter, transcript, paper)
site/           → Generated static site
  ├── index.html, library.json
  ├── papers/       → Research paper pages
  ├── topics/       → Topic filter pages
  ├── channels/     → Channel browse pages
  ├── browse/       → A-Z alphabetical pages
  └── transcripts/  → Individual video pages
search_index/   → Whoosh full-text search index (created by search_server.py)
library.json    → Root copy of master index for external tool access
pending.json    → Failed imports awaiting manual processing
papers_cache/   → Cached PDF downloads from arXiv (gitignored)
```

**Key Files:**
- `youtube_transcript_to_md.py` - Main video ingestion script with LLM analysis
- `huggingface_papers.py` - Paper ingestion from HuggingFace daily papers
- `library.py` - Static site generator (Jinja2 templates, CSS embedded)
- `batch_import.py` - Batch URL extraction and import with failure logging
- `channel_import.py` - Import all videos from a YouTube channel
- `manual_import.py` - Interactive import for videos without auto-captions
- `youtube_history.py` - Import from YouTube liked videos via API
- `sync_daily.py` - Automated daily paper sync
- `mcp_docent_server.py` - MCP server for Claude agent integration
- `search_server.py` - Flask server with Whoosh full-text search
- `AGENT_GUIDE.md` - Documentation for AI agents using the library

**LLM Analysis Pipeline** (in `youtube_transcript_to_md.py`):
- `chunk_into_sections()` groups transcript segments into ~180 second chunks
- `analyze_section()` calls Ollama to generate title/description per section
- `generate_title()` creates overall video title from first 500 chars
- `generate_summary()` creates bullet-point summary from full transcript
- `extract_facets()` classifies topic, format, and difficulty

**Metadata JSON Schema:**
```json
{
  "id": "video_id",
  "title": "LLM-generated title",
  "url": "https://youtube.com/watch?v=...",
  "channel": {
    "id": "UCxxxx",
    "name": "Channel Name",
    "url": "https://youtube.com/@channelname",
    "slug": "channel-name"
  },
  "duration_seconds": 600,
  "facets": {
    "topics": ["ai-ml"],
    "format": "tutorial",
    "difficulty": "intermediate"
  },
  "summary": ["Key insight 1", "Key insight 2"],
  "sections": [
    {"start": 0, "end": 180, "title": "Section Title", "description": "One-sentence description"}
  ],
  "added_date": "2025-12-29"
}
```

**Facet Values:**
- Topics (list, can have multiple): security, programming, ai-ml, entrepreneurship, devops, databases, web-development, career, other
- Format (single value): tutorial, deep-dive, news, interview, review, other
- Difficulty (single value): beginner, intermediate, advanced

**Search API Endpoints** (when search_server.py is running):
- `GET /api/search?q=<query>` - Full-text search with optional filters (`topic`, `format`, `difficulty`, `channel`)
- `GET /api/stats` - Index statistics
- `POST /api/rebuild-index` - Rebuild the search index

## Dependencies

```bash
pip install youtube-transcript-api requests jinja2 scrapetube flask whoosh
```

- **Core:** youtube-transcript-api, requests, jinja2
- **Channel import:** scrapetube (no API key required)
- **Search server:** flask, whoosh

Requires Ollama running locally with a model available for LLM analysis.
