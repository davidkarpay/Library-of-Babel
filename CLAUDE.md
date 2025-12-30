# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A personal YouTube learning library that fetches transcripts, generates LLM-analyzed metadata (sections, summaries, facets), and builds a static HTML site for browsing.

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
```

## Failed Transcript Workflow

When videos fail (no captions available), they are logged to `pending.json`:
1. `batch_import.py` logs failures automatically
2. Review `pending.json` to see failed videos
3. For important videos: run `python manual_import.py <url>` and paste transcript
4. Successfully imported videos are removed from pending.json

## Environment Variables

- `OLLAMA_URL` - Ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_MODEL` - Model for LLM analysis (default: `llama3.1:8b`)

## Architecture

**Data Flow:**
1. `youtube_transcript_to_md.py` fetches transcript via `youtube-transcript-api`
2. Chunks transcript into ~3min sections, calls Ollama for title/description per section
3. Generates overall title, summary bullets, and facets (topic/format/difficulty)
4. Outputs: `transcripts/{slug}.md` + `metadata/{slug}.json`
5. `library.py` reads all metadata JSON, renders Jinja2 templates to `site/`

**Directory Structure:**
```
transcripts/    → Markdown files with full timestamped transcripts
metadata/       → JSON files with structured data (one per video)
templates/      → Jinja2 templates (base, index, topic, channel, letter, transcript)
site/           → Generated static site
  ├── index.html, library.json
  ├── topics/       → Topic filter pages
  ├── channels/     → Channel browse pages
  ├── browse/       → A-Z alphabetical pages
  └── transcripts/  → Individual video pages
search_index/   → Whoosh full-text search index (created by search_server.py)
library.json    → Root copy of master index for external tool access
pending.json    → Failed imports awaiting manual processing
```

**Key Files:**
- `youtube_transcript_to_md.py` - Main ingestion script with LLM analysis
- `library.py` - Static site generator (Jinja2 templates, CSS embedded)
- `batch_import.py` - Batch URL extraction and import with failure logging
- `channel_import.py` - Import all videos from a YouTube channel
- `manual_import.py` - Interactive import for videos without auto-captions
- `backfill_channels.py` - Add channel info to existing metadata
- `search_server.py` - Flask server with Whoosh full-text search
- `reprocess_transcripts.py` - Re-fetch and regenerate all existing entries

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
  "url": "youtube URL",
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
  "summary": ["bullet1", "bullet2"],
  "sections": [
    {"start": 0, "end": 180, "title": "...", "description": "..."}
  ],
  "added_date": "2025-12-29"
}
```

**Facet Values:**
- Topics: security, programming, ai-ml, entrepreneurship, devops, databases, web-development, career, other
- Format: tutorial, deep-dive, news, interview, review, other
- Difficulty: beginner, intermediate, advanced

## Dependencies

```bash
pip install youtube-transcript-api requests jinja2 scrapetube flask whoosh
```

- **Core:** youtube-transcript-api, requests, jinja2
- **Channel import:** scrapetube (no API key required)
- **Search server:** flask, whoosh

Requires Ollama running locally with a model available for LLM analysis.
