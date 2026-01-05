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
PAPERS_DIR = BASE_DIR / "papers"
PODCASTS_DIR = BASE_DIR / "podcasts"
BLOGS_DIR = BASE_DIR / "blogs"
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


def build_content_type_index(entries: list) -> dict:
    """Build index of entries by content type (video/paper/podcast/blog)."""
    index = {"video": [], "paper": [], "podcast": [], "blog": []}
    for entry in entries:
        content_type = entry.get("content_type", "video")
        if content_type in index:
            index[content_type].append(entry)
        else:
            index["video"].append(entry)  # Default to video
    return index


def build_show_index(entries: list) -> dict:
    """Build index of podcast entries by show."""
    shows = defaultdict(list)
    for entry in entries:
        if entry.get("content_type") == "podcast":
            show = entry.get("show", {})
            show_slug = show.get("slug", "unknown-show")
            shows[show_slug].append(entry)
    return shows


def build_blog_source_index(entries: list) -> dict:
    """Build index of blog entries by source."""
    sources = defaultdict(list)
    for entry in entries:
        if entry.get("content_type") == "blog":
            blog = entry.get("blog", {})
            blog_slug = blog.get("slug", "unknown-blog")
            sources[blog_slug].append(entry)
    return sources


def format_duration(seconds) -> str:
    """Format seconds as human-readable duration."""
    if seconds is None:
        return ""
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return ""

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
    content_type_index = build_content_type_index(entries)
    show_index = build_show_index(entries)
    blog_source_index = build_blog_source_index(entries)

    video_count = len(content_type_index["video"])
    paper_count = len(content_type_index["paper"])
    podcast_count = len(content_type_index["podcast"])
    blog_count = len(content_type_index["blog"])
    print(f"  Videos: {video_count}, Papers: {paper_count}, Podcasts: {podcast_count}, Blogs: {blog_count}")

    # Set up Jinja environment
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    env.filters["format_duration"] = format_duration

    # Clear and recreate site directory
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir()
    (SITE_DIR / "topics").mkdir()
    (SITE_DIR / "transcripts").mkdir()
    (SITE_DIR / "papers").mkdir()
    (SITE_DIR / "podcasts").mkdir()
    (SITE_DIR / "shows").mkdir()
    (SITE_DIR / "blogs").mkdir()
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
        channels=channels_list[:10],
        video_count=video_count,
        paper_count=paper_count,
        podcast_count=podcast_count,
        blog_count=blog_count
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

    # Generate transcript pages (videos only)
    print("Generating transcript pages...")
    transcript_template = env.get_template("transcript.html")
    for entry in content_type_index["video"]:
        # Read the markdown content
        md_file = TRANSCRIPTS_DIR / f"{entry['_filename']}.md"
        if md_file.exists():
            md_content = md_file.read_text()
        else:
            md_content = ""

        transcript_html = transcript_template.render(
            entry=entry,
            markdown_content=md_content,
            video_count=video_count,
            paper_count=paper_count
        )
        (SITE_DIR / "transcripts" / f"{entry['_filename']}.html").write_text(transcript_html)

    # Generate paper pages
    if paper_count > 0:
        print("Generating paper pages...")
        try:
            paper_template = env.get_template("paper.html")
            for entry in content_type_index["paper"]:
                # Add slug for linking
                entry["slug"] = entry["_filename"]

                # Read the markdown content
                md_file = PAPERS_DIR / f"{entry['_filename']}.md"
                if md_file.exists():
                    md_content = md_file.read_text()
                else:
                    md_content = ""

                paper_html = paper_template.render(
                    entry=entry,
                    markdown_content=md_content,
                    video_count=video_count,
                    paper_count=paper_count
                )
                (SITE_DIR / "papers" / f"{entry['_filename']}.html").write_text(paper_html)

            # Generate papers index page
            print("Generating papers index...")
            papers_index_template = env.get_template("papers_index.html")

            # Get paper-specific topics
            paper_topics = set()
            for entry in content_type_index["paper"]:
                for topic in entry.get("facets", {}).get("topics", []):
                    paper_topics.add(topic)

            # Add slug to each paper entry
            papers_with_slugs = []
            for entry in content_type_index["paper"]:
                entry["slug"] = entry["_filename"]
                papers_with_slugs.append(entry)

            papers_index_html = papers_index_template.render(
                entries=papers_with_slugs,
                topics=sorted(paper_topics),
                video_count=video_count,
                paper_count=paper_count
            )
            (SITE_DIR / "papers" / "index.html").write_text(papers_index_html)

        except Exception as e:
            print(f"  Warning: Could not generate paper pages: {e}")

    # Copy CSS
    print("Writing CSS...")
    write_css()

    # Copy docent widget files
    print("Copying docent widget...")
    copy_widget_files()

    # Generate podcast pages
    if podcast_count > 0:
        print("Generating podcast pages...")
        try:
            podcast_template = env.get_template("podcast.html")
            for entry in content_type_index["podcast"]:
                entry["slug"] = entry["_filename"]

                # Read the markdown content
                md_file = PODCASTS_DIR / f"{entry['_filename']}.md"
                if md_file.exists():
                    md_content = md_file.read_text()
                else:
                    md_content = ""

                podcast_html = podcast_template.render(
                    entry=entry,
                    markdown_content=md_content,
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count
                )
                (SITE_DIR / "podcasts" / f"{entry['_filename']}.html").write_text(podcast_html)

            # Generate podcasts index page
            print("Generating podcasts index...")
            podcasts_index_template = env.get_template("podcasts_index.html")
            podcasts_index_html = podcasts_index_template.render(
                entries=content_type_index["podcast"],
                video_count=video_count,
                paper_count=paper_count,
                podcast_count=podcast_count,
                blog_count=blog_count
            )
            (SITE_DIR / "podcasts" / "index.html").write_text(podcasts_index_html)

        except Exception as e:
            print(f"  Warning: Could not generate podcast pages: {e}")

    # Generate blog pages
    if blog_count > 0:
        print("Generating blog pages...")
        try:
            blog_template = env.get_template("blog.html")
            for entry in content_type_index["blog"]:
                entry["slug"] = entry["_filename"]

                # Read the markdown content
                md_file = BLOGS_DIR / f"{entry['_filename']}.md"
                if md_file.exists():
                    md_content = md_file.read_text()
                else:
                    md_content = ""

                blog_html = blog_template.render(
                    entry=entry,
                    markdown_content=md_content,
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count
                )
                (SITE_DIR / "blogs" / f"{entry['_filename']}.html").write_text(blog_html)

            # Generate blogs index page
            print("Generating blogs index...")
            blogs_index_template = env.get_template("blogs_index.html")
            blogs_index_html = blogs_index_template.render(
                entries=content_type_index["blog"],
                video_count=video_count,
                paper_count=paper_count,
                podcast_count=podcast_count,
                blog_count=blog_count
            )
            (SITE_DIR / "blogs" / "index.html").write_text(blogs_index_html)

        except Exception as e:
            print(f"  Warning: Could not generate blog pages: {e}")

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
        "total": len(entries),
        "video_count": video_count,
        "paper_count": paper_count,
        "podcast_count": podcast_count,
        "blog_count": blog_count
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

/* Margin timestamp transcript viewer (Akademie Ausgabe style) */
.transcript-prose {
    padding-left: 5.5rem;
    position: relative;
    line-height: 1.9;
    font-size: 1rem;
}

.margin-timestamp {
    position: absolute;
    left: 0;
    width: 4.5rem;
    text-align: right;
    font-family: 'SF Mono', 'Menlo', 'Monaco', 'Consolas', monospace;
    font-size: 0.65rem;
    color: var(--text-muted);
    opacity: 0.35;
    user-select: none;
    transition: opacity 0.15s ease;
}

.margin-timestamp:hover {
    opacity: 0.85;
    color: var(--accent);
}

.margin-timestamp a {
    color: inherit;
    text-decoration: none;
}

.prose-segment {
    display: inline;
}

/* Mobile: inline superscript timestamps */
@media (max-width: 640px) {
    .transcript-prose {
        padding-left: 0;
    }

    .margin-timestamp {
        position: static;
        display: inline;
        width: auto;
        opacity: 0.2;
        font-size: 0.55rem;
        vertical-align: super;
        margin-right: 0.2rem;
    }
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

/* Dual Search Interface */
.dual-search {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.search-panel, .chat-panel {
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    padding: 1rem;
    min-height: 300px;
    display: flex;
    flex-direction: column;
}

.panel-title {
    color: var(--accent);
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
}

.search-panel .search-container {
    margin-bottom: 0.5rem;
}

.search-explainer {
    color: var(--text-muted);
    font-size: 0.75rem;
    margin: 0 0 1rem 0;
    opacity: 0.8;
}

.search-panel .search-results {
    flex: 1;
    overflow-y: auto;
    max-height: 400px;
}

/* Chat Interface */
.chat-container {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.chat-messages {
    flex: 1;
    overflow-y: auto;
    max-height: 350px;
    padding: 0.5rem;
    background: var(--bg);
    border-radius: 0.25rem;
    margin-bottom: 1rem;
}

.chat-message {
    margin-bottom: 1rem;
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    font-size: 0.9rem;
    line-height: 1.5;
}

.chat-message.user {
    background: var(--accent);
    color: white;
    margin-left: 2rem;
}

.chat-message.assistant {
    background: var(--bg-light);
    border: 1px solid var(--border);
    margin-right: 2rem;
}

.chat-message.loading {
    opacity: 0.6;
    font-style: italic;
}

.chat-message p {
    margin: 0;
}

.chat-videos {
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--border);
}

.chat-videos ul {
    list-style: none;
    margin-top: 0.5rem;
}

.chat-videos li {
    margin-bottom: 0.4rem;
}

.chat-videos a {
    color: var(--text);
    text-decoration: none;
}

.chat-videos a:hover {
    color: var(--accent);
}

.chat-videos .meta {
    color: var(--text-muted);
    font-size: 0.8rem;
}

/* Chat message formatting */
.chat-message h3, .chat-message h4 {
    color: var(--accent);
    margin: 0.75rem 0 0.5rem 0;
    font-size: 0.95rem;
}

.chat-message h3:first-child, .chat-message h4:first-child {
    margin-top: 0;
}

.chat-message ul {
    margin: 0.5rem 0;
    padding-left: 1.25rem;
}

.chat-message li {
    margin-bottom: 0.3rem;
}

.chat-message .timestamp {
    font-family: monospace;
    background: var(--bg);
    padding: 0.1rem 0.3rem;
    border-radius: 0.2rem;
    font-size: 0.8rem;
    color: var(--accent);
}

.chat-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.75rem 0;
    font-size: 0.85rem;
}

.chat-table th, .chat-table td {
    padding: 0.5rem 0.75rem;
    text-align: left;
    border-bottom: 1px solid var(--border);
}

.chat-table th {
    background: var(--bg);
    color: var(--accent);
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
}

.chat-table tr:hover {
    background: rgba(233, 69, 96, 0.05);
}

.chat-message em {
    color: var(--text-muted);
}

/* Search History Panel */
.history-panel {
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    margin-bottom: 2rem;
}

.history-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border);
}

.history-header .panel-title {
    margin: 0;
    padding: 0;
    border: none;
}

.history-controls {
    display: flex;
    gap: 0.5rem;
}

.history-toggle, .history-clear {
    padding: 0.35rem 0.75rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 0.25rem;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.8rem;
    transition: all 0.2s;
}

.history-toggle:hover, .history-clear:hover {
    border-color: var(--accent);
    color: var(--accent);
}

.history-content {
    padding: 1rem;
    max-height: 300px;
    overflow-y: auto;
}

.history-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.history-empty {
    color: var(--text-muted);
    text-align: center;
    padding: 1rem;
    font-size: 0.9rem;
}

.history-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.6rem 0.75rem;
    background: var(--bg);
    border-radius: 0.25rem;
    gap: 1rem;
}

.history-item:hover {
    background: rgba(233, 69, 96, 0.05);
}

.history-item-main {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex: 1;
    min-width: 0;
}

.history-type {
    padding: 0.2rem 0.5rem;
    border-radius: 0.2rem;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    flex-shrink: 0;
}

.history-type.keyword {
    background: var(--bg-light);
    color: var(--text-muted);
    border: 1px solid var(--border);
}

.history-type.ai {
    background: var(--accent);
    color: white;
}

.history-query {
    font-size: 0.9rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.history-item-meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-shrink: 0;
}

.history-time {
    color: var(--text-muted);
    font-size: 0.75rem;
}

.history-results {
    color: var(--text-muted);
    font-size: 0.75rem;
}

.history-rerun {
    padding: 0.25rem 0.5rem;
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.2rem;
    color: var(--text);
    cursor: pointer;
    font-size: 0.75rem;
}

.history-rerun:hover {
    border-color: var(--accent);
    color: var(--accent);
}

.history-delete {
    padding: 0.15rem 0.4rem;
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
}

.history-delete:hover {
    color: var(--accent);
}

/* Paper-specific styles */
.content-type-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 0.25rem;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-bottom: 0.5rem;
}

.paper-badge {
    background: #6366f1;
    color: white;
}

.video-badge {
    background: #ef4444;
    color: white;
}

.podcast-badge {
    background: #22c55e;
    color: white;
}

.blog-badge {
    background: #f59e0b;
    color: white;
}

.paper-header {
    margin-bottom: 2rem;
}

.paper-meta .authors {
    font-size: 0.95rem;
    color: var(--text);
}

.paper-links {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
}

.upvotes {
    color: #22c55e;
    font-weight: 600;
}

.abstract {
    background: var(--bg-light);
    padding: 1.5rem;
    border-radius: 0.5rem;
    margin-bottom: 2rem;
    border-left: 3px solid #6366f1;
}

.abstract h3 {
    color: #6366f1;
    margin-bottom: 1rem;
}

.abstract p {
    line-height: 1.7;
}

.paper-content {
    background: var(--bg-light);
    padding: 2rem;
    border-radius: 0.5rem;
}

.paper-content h3 {
    color: #6366f1;
    margin-bottom: 1rem;
}

.papers-list .entry-card {
    border-left: 3px solid #6366f1;
}

.entry-list {
    list-style: none;
}

.entry-card {
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    padding: 1.25rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}

.entry-card:hover {
    border-color: var(--accent);
}

.entry-header {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    flex-wrap: wrap;
}

.entry-title {
    color: var(--text);
    text-decoration: none;
    font-size: 1.1rem;
    font-weight: 500;
}

.entry-title:hover {
    color: var(--accent);
}

.entry-summary {
    margin-top: 0.75rem;
    color: var(--text-muted);
    font-size: 0.9rem;
    line-height: 1.5;
}

.tag-small {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
}

.empty-state {
    text-align: center;
    padding: 3rem;
    color: var(--text-muted);
}

.empty-state code {
    background: var(--bg);
    padding: 0.2rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.9rem;
}

.subtitle {
    color: var(--text-muted);
    font-size: 0.95rem;
    margin-top: 0.25rem;
}

.chat-input-container {
    display: flex;
    gap: 0.5rem;
}

#chat-input {
    flex: 1;
    padding: 0.6rem 0.75rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 0.25rem;
    color: var(--text);
    font-size: 0.9rem;
}

#chat-input:focus {
    outline: none;
    border-color: var(--accent);
}

#chat-input::placeholder {
    color: var(--text-muted);
}

#chat-btn {
    padding: 0.6rem 1rem;
    background: var(--accent);
    border: none;
    border-radius: 0.25rem;
    color: white;
    cursor: pointer;
    font-size: 0.85rem;
}

#chat-btn:hover {
    opacity: 0.9;
}

/* Responsive: stack on mobile */
@media (max-width: 900px) {
    .dual-search {
        grid-template-columns: 1fr;
    }

    .search-panel, .chat-panel {
        min-height: 250px;
    }

    .chat-messages {
        max-height: 250px;
    }
}
'''
    (SITE_DIR / "assets" / "style.css").write_text(css)


def copy_widget_files():
    """Copy docent widget files to site directory."""
    widget_js = BASE_DIR / "docent-widget.js"
    widget_css = BASE_DIR / "docent-widget.css"

    if widget_js.exists():
        shutil.copy(widget_js, SITE_DIR / "docent-widget.js")
        print("  Copied docent-widget.js")
    else:
        print("  Warning: docent-widget.js not found")

    if widget_css.exists():
        shutil.copy(widget_css, SITE_DIR / "docent-widget.css")
        print("  Copied docent-widget.css")
    else:
        print("  Warning: docent-widget.css not found")


if __name__ == "__main__":
    generate_site()
