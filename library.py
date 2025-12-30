#!/usr/bin/env python3
"""
library.py

Generate a static HTML site from the YouTube transcript library.
Reads metadata JSON files and generates browsable HTML pages.

Usage:
    python library.py

Requires:
    pip install jinja2
"""

import json
import shutil
from collections import defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
TEMPLATES_DIR = BASE_DIR / "templates"
SITE_DIR = BASE_DIR / "site"


def load_library() -> list:
    """Load all metadata files and return sorted list."""
    entries = []
    for json_file in METADATA_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                data["_filename"] = json_file.stem
                entries.append(data)
        except Exception as e:
            print(f"Warning: Could not load {json_file}: {e}")

    # Sort by date added, newest first
    entries.sort(key=lambda x: x.get("added_date", ""), reverse=True)
    return entries


def build_facet_index(entries: list) -> dict:
    """Build index of entries by facet values."""
    index = {
        "topics": defaultdict(list),
        "format": defaultdict(list),
        "difficulty": defaultdict(list)
    }

    for entry in entries:
        facets = entry.get("facets", {})

        for topic in facets.get("topics", []):
            index["topics"][topic].append(entry)

        fmt = facets.get("format", "other")
        index["format"][fmt].append(entry)

        diff = facets.get("difficulty", "intermediate")
        index["difficulty"][diff].append(entry)

    return index


def build_channel_index(entries: list) -> dict:
    """Build index of entries by channel."""
    channels = defaultdict(list)
    for entry in entries:
        channel = entry.get("channel", {})
        channel_slug = channel.get("slug", "unknown-channel")
        channels[channel_slug].append(entry)
    return channels


def build_alpha_index(entries: list) -> dict:
    """Build index of entries by first letter of title."""
    alpha = defaultdict(list)
    for entry in entries:
        title = entry.get("title", "")
        if title:
            first_char = title[0].lower()
            if first_char.isalpha():
                alpha[first_char].append(entry)
            else:
                alpha["0-9"].append(entry)
    return alpha


def format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        return f"{mins}m"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"


def generate_site():
    """Generate the complete static site."""
    print("Loading library...")
    entries = load_library()

    if not entries:
        print("No entries found in metadata/")
        return

    print(f"Found {len(entries)} entries")

    facet_index = build_facet_index(entries)
    channel_index = build_channel_index(entries)
    alpha_index = build_alpha_index(entries)

    # Set up Jinja environment
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    env.filters["format_duration"] = format_duration

    # Clear and recreate site directory
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir()
    (SITE_DIR / "topics").mkdir()
    (SITE_DIR / "transcripts").mkdir()
    (SITE_DIR / "channels").mkdir()
    (SITE_DIR / "browse").mkdir()
    (SITE_DIR / "assets").mkdir()

    # Build channels list for templates
    channels_list = []
    for slug, channel_entries in channel_index.items():
        if channel_entries:
            channel_info = channel_entries[0].get("channel", {})
            channels_list.append({
                "slug": slug,
                "name": channel_info.get("name", slug),
                "url": channel_info.get("url", ""),
                "count": len(channel_entries)
            })
    channels_list.sort(key=lambda x: x["name"].lower())

    # Generate index page
    print("Generating index page...")
    index_template = env.get_template("index.html")
    index_html = index_template.render(
        entries=entries,
        facet_index=facet_index,
        topics=sorted(facet_index["topics"].keys()),
        formats=sorted(facet_index["format"].keys()),
        difficulties=["beginner", "intermediate", "advanced"],
        channels=channels_list[:10]
    )
    (SITE_DIR / "index.html").write_text(index_html)

    # Generate topic pages
    print("Generating topic pages...")
    topic_template = env.get_template("topic.html")
    for topic, topic_entries in facet_index["topics"].items():
        topic_html = topic_template.render(
            topic=topic,
            entries=topic_entries,
            total_entries=len(entries)
        )
        (SITE_DIR / "topics" / f"{topic}.html").write_text(topic_html)

    # Generate channel index page
    print("Generating channel pages...")
    try:
        channels_index_template = env.get_template("channels_index.html")
        channels_index_html = channels_index_template.render(
            channels=channels_list,
            entries=entries
        )
        (SITE_DIR / "channels" / "index.html").write_text(channels_index_html)
    except Exception as e:
        print(f"  Warning: Could not generate channels index: {e}")

    # Generate individual channel pages
    try:
        channel_template = env.get_template("channel.html")
        for slug, channel_entries in channel_index.items():
            channel_info = channel_entries[0].get("channel", {}) if channel_entries else {}
            channel_html = channel_template.render(
                channel_name=channel_info.get("name", slug),
                channel_url=channel_info.get("url", ""),
                entries=channel_entries,
                total_entries=len(entries)
            )
            (SITE_DIR / "channels" / f"{slug}.html").write_text(channel_html)
    except Exception as e:
        print(f"  Warning: Could not generate channel pages: {e}")

    # Generate A-Z browse pages
    print("Generating A-Z browse pages...")
    alphabet = list("abcdefghijklmnopqrstuvwxyz") + ["0-9"]
    try:
        letter_template = env.get_template("letter.html")
        for letter in alphabet:
            letter_entries = alpha_index.get(letter, [])
            # Sort alphabetically within each letter
            letter_entries.sort(key=lambda x: x.get("title", "").lower())

            letter_html = letter_template.render(
                letter=letter,
                alphabet=alphabet,
                entries=letter_entries,
                total_entries=len(entries)
            )
            (SITE_DIR / "browse" / f"{letter}.html").write_text(letter_html)
    except Exception as e:
        print(f"  Warning: Could not generate A-Z pages: {e}")

    # Generate transcript pages
    print("Generating transcript pages...")
    transcript_template = env.get_template("transcript.html")
    for entry in entries:
        # Read the markdown content
        md_file = TRANSCRIPTS_DIR / f"{entry['_filename']}.md"
        if md_file.exists():
            md_content = md_file.read_text()
        else:
            md_content = ""

        transcript_html = transcript_template.render(
            entry=entry,
            markdown_content=md_content
        )
        (SITE_DIR / "transcripts" / f"{entry['_filename']}.html").write_text(transcript_html)

    # Copy CSS
    print("Writing CSS...")
    write_css()

    # Write library.json
    print("Writing library.json...")
    library_data = {
        "entries": entries,
        "facets": {
            "topics": list(facet_index["topics"].keys()),
            "formats": list(facet_index["format"].keys()),
            "difficulties": list(facet_index["difficulty"].keys())
        },
        "channels": [{"slug": c["slug"], "name": c["name"], "count": c["count"]} for c in channels_list],
        "total": len(entries)
    }
    with open(SITE_DIR / "library.json", "w") as f:
        json.dump(library_data, f, indent=2)

    # Also save to root for agent access
    with open(BASE_DIR / "library.json", "w") as f:
        json.dump(library_data, f, indent=2)

    print(f"\nSite generated at: {SITE_DIR}")
    print(f"Open {SITE_DIR / 'index.html'} in a browser to view")


def write_css():
    """Write the CSS file."""
    css = '''
:root {
    --bg: #1a1a2e;
    --bg-light: #16213e;
    --accent: #e94560;
    --text: #eee;
    --text-muted: #888;
    --border: #333;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}

header {
    border-bottom: 1px solid var(--border);
    padding-bottom: 1rem;
    margin-bottom: 2rem;
}

header h1 {
    color: var(--accent);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

header a {
    color: var(--text);
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.icon {
    width: 1.5em;
    height: 1.5em;
    stroke: var(--accent);
}

/* Facet filters */
.filters {
    display: flex;
    gap: 2rem;
    margin-bottom: 2rem;
    flex-wrap: wrap;
}

.filter-group h3 {
    color: var(--text-muted);
    font-size: 0.85rem;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
}

.filter-group .tags {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.tag {
    background: var(--bg-light);
    color: var(--text);
    padding: 0.25rem 0.75rem;
    border-radius: 1rem;
    font-size: 0.85rem;
    text-decoration: none;
    border: 1px solid var(--border);
    transition: all 0.2s;
}

.tag:hover {
    border-color: var(--accent);
    color: var(--accent);
}

.tag.active {
    background: var(--accent);
    border-color: var(--accent);
}

/* Entry cards */
.entries {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 1.5rem;
}

.entry-card {
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    padding: 1.5rem;
    transition: border-color 0.2s;
}

.entry-card:hover {
    border-color: var(--accent);
}

.entry-card h2 {
    font-size: 1.1rem;
    margin-bottom: 0.5rem;
}

.entry-card h2 a {
    color: var(--text);
    text-decoration: none;
}

.entry-card h2 a:hover {
    color: var(--accent);
}

.entry-meta {
    color: var(--text-muted);
    font-size: 0.85rem;
    margin-bottom: 1rem;
}

.entry-summary {
    font-size: 0.9rem;
    color: var(--text-muted);
}

.entry-summary ul {
    list-style: none;
    padding-left: 0;
}

.entry-summary li::before {
    content: "→ ";
    color: var(--accent);
}

/* Transcript page */
.transcript-header {
    margin-bottom: 2rem;
}

.video-embed {
    position: relative;
    padding-bottom: 56.25%;
    margin-bottom: 2rem;
    background: #000;
    border-radius: 0.5rem;
    overflow: hidden;
}

.video-embed iframe {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
}

.sections-nav {
    background: var(--bg-light);
    padding: 1.5rem;
    border-radius: 0.5rem;
    margin-bottom: 2rem;
}

.sections-nav h3 {
    margin-bottom: 1rem;
    color: var(--accent);
}

.sections-nav ul {
    list-style: none;
}

.sections-nav li {
    margin-bottom: 0.5rem;
}

.sections-nav a {
    color: var(--text);
    text-decoration: none;
}

.sections-nav a:hover {
    color: var(--accent);
}

.sections-nav .timestamp {
    color: var(--text-muted);
    font-family: monospace;
    margin-right: 0.5rem;
}

/* Full transcript */
.transcript-content {
    background: var(--bg-light);
    padding: 2rem;
    border-radius: 0.5rem;
}

.transcript-content h2,
.transcript-content h3 {
    color: var(--accent);
    margin: 1.5rem 0 1rem;
}

.transcript-content .timestamp {
    color: var(--text-muted);
    font-family: monospace;
    font-size: 0.8rem;
    margin-right: 0.5rem;
    opacity: 0.6;
}

.transcript-content p {
    margin-bottom: 0.5rem;
}

/* Summary */
.summary {
    background: var(--bg-light);
    padding: 1.5rem;
    border-radius: 0.5rem;
    margin-bottom: 2rem;
    border-left: 3px solid var(--accent);
}

.summary h3 {
    color: var(--accent);
    margin-bottom: 1rem;
}

.summary ul {
    list-style: none;
}

.summary li {
    margin-bottom: 0.5rem;
}

.summary li::before {
    content: "• ";
    color: var(--accent);
}

/* Back link */
.back-link {
    display: inline-block;
    margin-bottom: 1rem;
    color: var(--text-muted);
    text-decoration: none;
}

.back-link:hover {
    color: var(--accent);
}

/* Main Navigation */
.main-nav {
    display: flex;
    gap: 1.5rem;
    margin-top: 0.75rem;
    flex-wrap: wrap;
    align-items: center;
}

.main-nav a {
    color: var(--text-muted);
    text-decoration: none;
    font-size: 0.9rem;
    transition: color 0.2s;
}

.main-nav a:hover {
    color: var(--accent);
}

.main-nav a.active {
    color: var(--accent);
}

.nav-divider {
    color: var(--border);
}

/* Channel List */
.channel-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 1rem;
}

.channel-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.25rem;
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    text-decoration: none;
    color: var(--text);
    transition: border-color 0.2s;
}

.channel-card:hover {
    border-color: var(--accent);
}

.channel-name {
    font-weight: 500;
}

.channel-count {
    color: var(--text-muted);
    font-size: 0.85rem;
}

.channel-link {
    color: var(--accent);
    text-decoration: none;
}

.channel-link:hover {
    text-decoration: underline;
}

/* Letter Navigation */
.letter-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
    padding: 1rem;
    background: var(--bg-light);
    border-radius: 0.5rem;
}

.letter-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 0.25rem;
    color: var(--text);
    text-decoration: none;
    font-weight: 500;
    font-size: 0.9rem;
    transition: all 0.2s;
}

.letter-link:hover {
    border-color: var(--accent);
    color: var(--accent);
}

.letter-link.active {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--bg);
}

/* Search Container */
.search-container {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 2rem;
}

#search-input {
    flex: 1;
    padding: 0.75rem 1rem;
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    color: var(--text);
    font-size: 1rem;
}

#search-input:focus {
    outline: none;
    border-color: var(--accent);
}

#search-input::placeholder {
    color: var(--text-muted);
}

#search-btn, #clear-search {
    padding: 0.75rem 1.5rem;
    background: var(--accent);
    border: none;
    border-radius: 0.5rem;
    color: white;
    cursor: pointer;
    font-size: 0.9rem;
    transition: opacity 0.2s;
}

#search-btn:hover, #clear-search:hover {
    opacity: 0.9;
}

#clear-search {
    background: var(--bg-light);
    border: 1px solid var(--border);
    color: var(--text);
}

/* Search Results */
.search-results {
    margin-bottom: 2rem;
}

.search-result-card {
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    padding: 1.5rem;
    margin-bottom: 1rem;
}

.search-result-card mark {
    background: var(--accent);
    color: white;
    padding: 0 0.2rem;
    border-radius: 0.2rem;
}

.matching-sections {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
}

.matching-section {
    margin-top: 0.75rem;
    padding: 0.75rem;
    background: var(--bg);
    border-radius: 0.25rem;
    font-size: 0.9rem;
}

.matching-section .timestamp {
    color: var(--accent);
    font-family: monospace;
}

.matching-section a {
    color: var(--text);
    text-decoration: none;
}

.matching-section a:hover {
    color: var(--accent);
}

.matching-section p {
    margin-top: 0.5rem;
    color: var(--text-muted);
}
'''
    (SITE_DIR / "assets" / "style.css").write_text(css)


if __name__ == "__main__":
    generate_site()
