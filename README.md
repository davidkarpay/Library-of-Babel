# YouTube Transcript → Markdown

This tool downloads a YouTube video's transcript and converts it into a clean,
timestamped Markdown file.

## Features
- Accepts standard YouTube URLs
- Uses YouTube's official caption data (no scraping)
- Outputs readable Markdown with timestamps
- Works with manually provided or auto-generated captions

## Requirements
- Python 3.9+
- `youtube-transcript-api`

Install dependencies:

```bash
pip install youtube-transcript-api
```

## Usage

```bash
python youtube_transcript_to_md.py "https://www.youtube.com/watch?v=xNcEgqzlPqs&t=449s"
```

Output:
- `xNcEgqzlPqs.md`

Or specify a filename:

```bash
python youtube_transcript_to_md.py <url> output.md
```

## Notes
- If a video has no transcript, the script will raise an error.
- Ads do not affect this script (unlike browser-based extraction).
- This is suitable for research, note-taking, and downstream NLP workflows.

## Tested With
- “AI Agents That Actually Work: The Pattern Anthropic Just Revealed”
