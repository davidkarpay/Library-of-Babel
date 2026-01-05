# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A personal learning library that combines multiple content sources: YouTube video transcripts, research papers (HuggingFace + arXiv), podcasts, and blog posts. Content is analyzed by LLM to generate metadata (sections, summaries, topics, difficulty levels) and served via a static HTML site with AI-powered search.

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

# Import papers directly from arXiv API
python arxiv_papers.py --category cs.AI              # Recent AI papers
python arxiv_papers.py --category cs.LG --days 7     # Last 7 days
python arxiv_papers.py --query "transformers"        # Search query
python arxiv_papers.py --single 2401.12345           # Single paper by ID
python arxiv_papers.py --dry-run                     # Preview only

# Automated daily sync (papers from multiple sources)
python sync_daily.py                              # HuggingFace only (default)
python sync_daily.py --source huggingface arxiv   # Both sources
python sync_daily.py --source arxiv               # arXiv only
python sync_daily.py --arxiv-categories cs.AI cs.LG cs.CL  # Custom categories
python sync_daily.py --backfill 7                 # Sync last 7 days
python sync_daily.py --commit                     # Commit changes after sync

# === PODCAST IMPORT ===

# Import podcast episodes from RSS feed
python podcast_import.py <rss_feed_url>              # Import latest episode
python podcast_import.py <feed_url> --episode 2      # Specific episode (0-indexed)
python podcast_import.py <feed_url> --limit 5        # Import multiple episodes
python podcast_import.py <feed_url> --manual         # Paste transcript manually
python podcast_import.py <feed_url> --dry-run        # Preview only
python podcast_import.py <feed_url> --list           # List available episodes

# === BLOG IMPORT ===

# Import blog posts (with quality scoring)
python blog_import.py <url>                          # Import single post
python blog_import.py <url> --dry-run                # Preview only
python blog_import.py --review-pending               # Review pending queue
python blog_import.py --approve <id>                 # Approve pending item
python blog_import.py --reject <id>                  # Reject pending item
python blog_import.py --list-trusted                 # Show trusted sources

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
podcasts/       → Markdown files with podcast transcripts
blogs/          → Markdown files with blog post content
metadata/       → JSON files with structured data (all content types)
templates/      → Jinja2 templates (base, index, content type pages)
site/           → Generated static site
  ├── index.html, library.json
  ├── papers/       → Research paper pages
  ├── podcasts/     → Podcast episode pages
  ├── shows/        → Podcast show pages
  ├── blogs/        → Blog post pages
  ├── topics/       → Topic filter pages
  ├── channels/     → Channel browse pages
  ├── browse/       → A-Z alphabetical pages
  └── transcripts/  → Individual video pages
search_index/   → Whoosh full-text search index (created by search_server.py)
library.json    → Root copy of master index for external tool access
pending.json    → Failed video imports awaiting manual processing
pending_blogs.json → Blog posts awaiting quality review (gitignored)
trusted_blogs.json → Curated list of auto-approved blog sources
papers_cache/   → Cached PDF downloads from arXiv (gitignored)
podcasts_cache/ → Cached audio files (gitignored)
blogs_cache/    → Cached HTML for retries (gitignored)
```

**Key Files:**
- `youtube_transcript_to_md.py` - Main video ingestion script with LLM analysis
- `huggingface_papers.py` - Paper ingestion from HuggingFace daily papers
- `arxiv_papers.py` - Direct arXiv API integration for paper import
- `podcast_import.py` - Podcast episode import from RSS feeds
- `blog_import.py` - Blog post import with quality scoring
- `library.py` - Static site generator (Jinja2 templates, CSS embedded)
- `batch_import.py` - Batch URL extraction and import with failure logging
- `channel_import.py` - Import all videos from a YouTube channel
- `manual_import.py` - Interactive import for videos without auto-captions
- `youtube_history.py` - Import from YouTube liked videos via API
- `sync_daily.py` - Automated daily sync (HuggingFace + arXiv papers)
- `mcp_docent_server.py` - MCP server for Claude agent integration
- `search_server.py` - Flask server with Whoosh full-text search
- `trusted_blogs.json` - Curated list of auto-approved blog sources
- `AGENT_GUIDE.md` - Documentation for AI agents using the library

**LLM Analysis Pipeline** (in `youtube_transcript_to_md.py`):
- `chunk_into_sections()` groups transcript segments into ~180 second chunks
- `analyze_section()` calls Ollama to generate title/description per section
- `generate_title()` creates overall video title from first 500 chars
- `generate_summary()` creates bullet-point summary from full transcript
- `extract_facets()` classifies topic, format, and difficulty

**Video Metadata Schema:**
```json
{
  "id": "video_id",
  "content_type": "video",
  "title": "LLM-generated title",
  "url": "https://youtube.com/watch?v=...",
  "channel": {
    "id": "UCxxxx",
    "name": "Channel Name",
    "url": "https://youtube.com/@channelname",
    "slug": "channel-name"
  },
  "duration_seconds": 600,
  "published_date": "2025-12-25",
  "added_date": "2025-12-29",
  "facets": {
    "topics": ["ai-ml"],
    "format": "tutorial",
    "difficulty": "intermediate"
  },
  "summary": ["Key insight 1", "Key insight 2"],
  "sections": [
    {"start": 0, "end": 180, "title": "Section Title", "description": "One-sentence description"}
  ]
}
```

**Podcast Metadata Schema:**
```json
{
  "id": "episode-guid-hash",
  "content_type": "podcast",
  "title": "Episode Title",
  "url": "https://podcast.example.com/ep123",
  "audio_url": "https://cdn.example.com/ep123.mp3",
  "show": {
    "name": "Show Name",
    "slug": "show-name",
    "feed_url": "https://podcast.example.com/feed.xml"
  },
  "duration_seconds": 3600,
  "published_date": "2026-01-01",
  "added_date": "2026-01-04",
  "transcript_source": "rss|manual",
  "facets": {...},
  "summary": [...],
  "sections": [...]
}
```

**Blog Metadata Schema:**
```json
{
  "id": "url-hash",
  "content_type": "blog",
  "title": "Article Title",
  "url": "https://example.com/article",
  "blog": {
    "name": "Blog Name",
    "slug": "blog-name",
    "domain": "example.com"
  },
  "author": {"name": "Author Name"},
  "published_date": "2026-01-04",
  "added_date": "2026-01-04",
  "word_count": 2500,
  "quality_score": 85,
  "quality_flags": [],
  "is_trusted_source": true,
  "facets": {...},
  "summary": [...],
  "sections": [...]
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
pip install youtube-transcript-api requests jinja2 scrapetube flask whoosh feedparser trafilatura bleach defusedxml
```

- **Core:** youtube-transcript-api, requests, jinja2
- **Channel import:** scrapetube (no API key required)
- **Search server:** flask, whoosh
- **Podcasts/Blogs:** feedparser (RSS parsing), trafilatura (blog content extraction)
- **Security:** bleach (HTML sanitization), defusedxml (safe XML parsing)

Requires Ollama running locally with a model available for LLM analysis.

## Blog Quality System

Blog imports use a three-tier quality system to prevent low-quality content:

1. **Trusted Sources** (auto-approved): Domains in `trusted_blogs.json` bypass quality scoring
2. **LLM Quality Assessment**: Posts scored 0-100 on technical depth, originality, clarity, accuracy, practicality
3. **Pending Review Queue**: Posts with `quality_score < 70` go to `pending_blogs.json` for manual review

Quality thresholds:
- Score ≥ 70: Auto-approved
- Score 40-69: Added to pending review queue
- Score < 40: Rejected

Use `python blog_import.py --review-pending` to review and approve/reject pending items.
