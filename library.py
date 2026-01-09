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

    # Infer domain for each entry (backward compatibility)
    for entry in entries:
        if "domain" not in entry:
            entry["domain"] = infer_domain(entry)

    return entries


def infer_domain(metadata: dict) -> str:
    """
    Infer domain from metadata for backward compatibility.

    Returns:
        "law" for legal content, "computer-science" for everything else
    """
    content_type = metadata.get("content_type", "")

    # Legal content types
    if content_type in ("legal", "law-journal"):
        return "law"

    # Check topics for legal content
    topics = metadata.get("facets", {}).get("topics", [])
    if "legal" in topics:
        return "law"

    # Default to computer science
    return "computer-science"


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
    """Build index of entries by content type (video/paper/podcast/blog/course/legal/law-journal)."""
    index = {"video": [], "paper": [], "podcast": [], "blog": [], "course": [], "legal": [], "law-journal": []}
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
    course_count = len(content_type_index["course"])
    legal_count = len(content_type_index["legal"])
    journal_count = len(content_type_index["law-journal"])
    print(f"  Videos: {video_count}, Papers: {paper_count}, Podcasts: {podcast_count}, Blogs: {blog_count}, Courses: {course_count}, Legal: {legal_count}, Journals: {journal_count}")

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
    (SITE_DIR / "courses").mkdir()
    (SITE_DIR / "legal").mkdir()
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
        blog_count=blog_count,
        course_count=course_count,
        total_entries=len(entries)
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

    # Generate course pages
    if course_count > 0:
        print("Generating course pages...")
        COURSES_DIR = BASE_DIR / "courses"
        try:
            course_template = env.get_template("course.html")
            for entry in content_type_index["course"]:
                entry["slug"] = entry["_filename"]

                # Read the markdown content
                md_file = COURSES_DIR / f"{entry['_filename']}.md"
                if md_file.exists():
                    md_content = md_file.read_text()
                else:
                    md_content = ""

                course_html = course_template.render(
                    entry=entry,
                    markdown_content=md_content,
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count,
                    course_count=course_count
                )
                (SITE_DIR / "courses" / f"{entry['_filename']}.html").write_text(course_html)

            # Generate courses index page
            print("Generating courses index...")
            try:
                courses_index_template = env.get_template("courses_index.html")
                courses_index_html = courses_index_template.render(
                    entries=content_type_index["course"],
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count,
                    course_count=course_count
                )
                (SITE_DIR / "courses" / "index.html").write_text(courses_index_html)
            except Exception as e:
                print(f"  Warning: Could not generate courses index: {e}")

        except Exception as e:
            print(f"  Warning: Could not generate course pages: {e}")

    # Generate legal content pages
    if legal_count > 0:
        print("Generating legal pages...")
        LEGAL_DIR = BASE_DIR / "legal"
        try:
            legal_template = env.get_template("legal.html")
            for entry in content_type_index["legal"]:
                entry["slug"] = entry["_filename"]

                # Read the markdown content
                md_file = LEGAL_DIR / f"{entry['_filename']}.md"
                if md_file.exists():
                    md_content = md_file.read_text()
                else:
                    md_content = ""

                legal_html = legal_template.render(
                    entry=entry,
                    markdown_content=md_content,
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count,
                    course_count=course_count,
                    legal_count=legal_count
                )
                (SITE_DIR / "legal" / f"{entry['_filename']}.html").write_text(legal_html)

            # Generate legal index page
            print("Generating legal index...")
            try:
                # Group by jurisdiction for better organization
                jurisdictions = {}
                for entry in content_type_index["legal"]:
                    code = entry.get("jurisdiction_code", "OTHER")
                    jurisdiction_name = entry.get("jurisdiction", "Other")
                    if code not in jurisdictions:
                        jurisdictions[code] = {
                            "code": code,
                            "name": jurisdiction_name,
                            "entries": []
                        }
                    jurisdictions[code]["entries"].append(entry)

                legal_index_template = env.get_template("legal_index.html")
                legal_index_html = legal_index_template.render(
                    entries=content_type_index["legal"],
                    jurisdictions=jurisdictions,
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count,
                    course_count=course_count,
                    legal_count=legal_count
                )
                (SITE_DIR / "legal" / "index.html").write_text(legal_index_html)
            except Exception as e:
                print(f"  Warning: Could not generate legal index: {e}")

        except Exception as e:
            print(f"  Warning: Could not generate legal pages: {e}")

    # Generate law journal pages
    if journal_count > 0:
        print("Generating law journal pages...")
        JOURNALS_DIR = BASE_DIR / "journals"
        (SITE_DIR / "journals").mkdir(parents=True, exist_ok=True)
        try:
            journal_template = env.get_template("law-journal.html")
            for entry in content_type_index["law-journal"]:
                entry["slug"] = entry["_filename"]

                # Read the markdown content
                md_file = JOURNALS_DIR / f"{entry['_filename']}.md"
                if md_file.exists():
                    md_content = md_file.read_text()
                else:
                    md_content = ""

                journal_html = journal_template.render(
                    entry=entry,
                    markdown_content=md_content,
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count,
                    course_count=course_count,
                    legal_count=legal_count,
                    journal_count=journal_count
                )
                (SITE_DIR / "journals" / f"{entry['_filename']}.html").write_text(journal_html)

            # Generate journals index page
            print("Generating journals index...")
            try:
                # Group by journal for better organization
                journals = {}
                for entry in content_type_index["law-journal"]:
                    journal_info = entry.get("journal", {})
                    journal_slug = journal_info.get("slug", "unknown-journal")
                    journal_name = journal_info.get("name", "Unknown Journal")
                    if journal_slug not in journals:
                        journals[journal_slug] = {
                            "slug": journal_slug,
                            "name": journal_name,
                            "institution": journal_info.get("institution", ""),
                            "entries": []
                        }
                    journals[journal_slug]["entries"].append(entry)

                # Use legal_index.html as base for now (can create dedicated template later)
                journals_index_template = env.get_template("legal_index.html")
                journals_index_html = journals_index_template.render(
                    entries=content_type_index["law-journal"],
                    jurisdictions=journals,  # Reuse jurisdictions template variable
                    video_count=video_count,
                    paper_count=paper_count,
                    podcast_count=podcast_count,
                    blog_count=blog_count,
                    course_count=course_count,
                    legal_count=legal_count,
                    journal_count=journal_count,
                    page_title="Law Journals",
                    is_journals=True
                )
                (SITE_DIR / "journals" / "index.html").write_text(journals_index_html)
            except Exception as e:
                print(f"  Warning: Could not generate journals index: {e}")

        except Exception as e:
            print(f"  Warning: Could not generate journal pages: {e}")

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
        "blog_count": blog_count,
        "course_count": course_count,
        "legal_count": legal_count,
        "journal_count": journal_count
    }
    with open(SITE_DIR / "library.json", "w") as f:
        json.dump(library_data, f, indent=2)

    # Also save to root for agent access
    with open(BASE_DIR / "library.json", "w") as f:
        json.dump(library_data, f, indent=2)

    # Generate agent discovery files
    print("Generating agent discovery files...")
    generate_agent_files(entries, facet_index, content_type_index)

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
    /* Domain accent colors */
    --domain-law: #7f1d1d;
    --domain-computer-science: #1e3a8a;
    --law-tint: rgba(127,29,29,.18);
    --cs-tint: rgba(30,58,138,.16);
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

.legal-badge {
    background: #7f1d1d;
    color: white;
}

.journal-badge {
    background: #be185d;
    color: white;
}

/* Entry badges container */
.entry-badges {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
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

/* Domain separation styles */
.entry-card {
    position: relative;
    border-left: 4px solid var(--border);
}

.entry-card.domain-law {
    border-left-color: var(--domain-law);
}

.entry-card.domain-computer-science {
    border-left-color: var(--domain-computer-science);
}

/* Domain badge */
.domain-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.2rem 0.5rem;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--border);
}

.domain-badge::before {
    content: "";
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: var(--border);
}

.domain-badge.law {
    border-color: rgba(127,29,29,.5);
    color: #fca5a5;
}

.domain-badge.law::before {
    background: var(--domain-law);
}

.domain-badge.computer-science {
    border-color: rgba(30,58,138,.5);
    color: #93c5fd;
}

.domain-badge.computer-science::before {
    background: var(--domain-computer-science);
}

/* Domain filter toggle */
.domain-filter {
    display: inline-flex;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 999px;
    overflow: hidden;
    margin-left: 1rem;
}

.domain-filter a {
    padding: 0.35rem 0.75rem;
    font-size: 0.8rem;
    color: var(--text-muted);
    text-decoration: none;
    transition: background 0.2s, color 0.2s;
}

.domain-filter a:hover {
    background: rgba(255,255,255,0.05);
}

.domain-filter a.active {
    background: var(--bg-light);
    color: var(--text);
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

/* === Hero Section (Above the Fold) === */
.hero {
    min-height: 50vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 2rem;
    margin-bottom: 2rem;
}

.hero-search {
    width: 100%;
    max-width: 700px;
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
}

.hero-search input {
    flex: 1;
    padding: 1rem 1.25rem;
    background: var(--bg-light);
    border: 2px solid var(--border);
    border-radius: 0.5rem;
    color: var(--text);
    font-size: 1.1rem;
}

.hero-search input:focus {
    outline: none;
    border-color: var(--accent);
}

.hero-search input::placeholder {
    color: var(--text-muted);
}

.hero-search button {
    padding: 1rem 1.5rem;
    background: var(--accent);
    border: none;
    border-radius: 0.5rem;
    color: white;
    cursor: pointer;
    font-size: 1rem;
    font-weight: 500;
}

.hero-search button:hover {
    opacity: 0.9;
}

.hero-search #clear-search {
    background: var(--bg-light);
    border: 2px solid var(--border);
    color: var(--text);
}

.hero-chat {
    width: 100%;
    max-width: 700px;
    display: flex;
    gap: 0.5rem;
    margin-bottom: 2rem;
}

.hero-chat input {
    flex: 1;
    padding: 0.75rem 1rem;
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    color: var(--text);
    font-size: 0.95rem;
}

.hero-chat input:focus {
    outline: none;
    border-color: var(--accent);
}

.hero-chat input::placeholder {
    color: var(--text-muted);
}

.hero-chat button {
    padding: 0.75rem 1.25rem;
    background: var(--bg-light);
    border: 1px solid var(--accent);
    border-radius: 0.5rem;
    color: var(--accent);
    cursor: pointer;
    font-size: 0.9rem;
}

.hero-chat button:hover {
    background: var(--accent);
    color: white;
}

/* Docent Desk */
.docent-desk {
    margin-top: 1rem;
}

.docent-icon {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 1rem;
    transition: color 0.2s;
}

.docent-icon:hover {
    color: var(--accent);
}

.docent-icon svg {
    width: 2rem;
    height: 2rem;
}

.docent-icon span {
    font-size: 0.85rem;
}

/* Chat Container (Expandable) */
.chat-container-expandable {
    max-width: 700px;
    margin: 0 auto 2rem;
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    padding: 1rem;
}

.chat-container-expandable .chat-messages {
    max-height: 400px;
    overflow-y: auto;
    padding: 0.5rem;
    background: var(--bg);
    border-radius: 0.25rem;
}

/* Modal */
.modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
}

.modal-content {
    background: var(--bg-light);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 2rem;
    max-width: 600px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
    position: relative;
}

.modal-close {
    position: absolute;
    top: 1rem;
    right: 1rem;
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1.5rem;
    cursor: pointer;
    line-height: 1;
}

.modal-close:hover {
    color: var(--accent);
}

.modal-content h2 {
    color: var(--accent);
    margin-bottom: 1.5rem;
}

.docent-section {
    margin-bottom: 1.5rem;
}

.docent-section h3 {
    color: var(--text);
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
}

.docent-section ul {
    list-style: none;
    padding: 0;
}

.docent-section li {
    margin-bottom: 0.5rem;
    color: var(--text-muted);
}

.docent-section a {
    color: var(--accent);
    text-decoration: none;
}

.docent-section a:hover {
    text-decoration: underline;
}

.docent-section code {
    background: var(--bg);
    padding: 0.2rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.85rem;
}

.api-endpoints {
    font-family: monospace;
    font-size: 0.85rem;
}

.api-endpoints li {
    margin-bottom: 0.25rem;
}

/* Search feedback */
.search-loading, .search-empty, .search-count {
    color: var(--text-muted);
    padding: 1rem;
}

.search-count {
    margin-bottom: 1rem;
}

/* Mobile hero adjustments */
@media (max-width: 600px) {
    .hero {
        min-height: 40vh;
        padding: 1rem;
    }

    .hero-search input, .hero-chat input {
        font-size: 1rem;
        padding: 0.75rem 1rem;
    }

    .hero-search button, .hero-chat button {
        padding: 0.75rem 1rem;
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


def generate_agent_files(entries: list, facet_index: dict, content_type_index: dict):
    """Generate agent discovery files: robots.txt, sitemap.xml, llms.txt, ai.json."""
    from datetime import datetime

    total = len(entries)
    video_count = len(content_type_index["video"])
    paper_count = len(content_type_index["paper"])
    podcast_count = len(content_type_index["podcast"])
    blog_count = len(content_type_index["blog"])
    today = datetime.now().strftime("%Y-%m-%d")

    # robots.txt
    robots_txt = f"""# Learning Library - robots.txt
# Last updated: {today}

User-agent: *
Allow: /

# Agent discovery files
# /llms.txt - AI agent guide
# /.well-known/ai.json - API capabilities
# /library.json - Full content index

Sitemap: https://library.davidkarpay.com/sitemap.xml
"""
    (SITE_DIR / "robots.txt").write_text(robots_txt)
    print("  Generated robots.txt")

    # sitemap.xml
    sitemap_entries = ['<?xml version="1.0" encoding="UTF-8"?>']
    sitemap_entries.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    # Static pages
    static_pages = [
        ("", "1.0", "daily"),
        ("papers/index.html", "0.8", "daily"),
        ("podcasts/index.html", "0.8", "daily"),
        ("blogs/index.html", "0.8", "daily"),
        ("channels/index.html", "0.7", "weekly"),
    ]
    for page, priority, changefreq in static_pages:
        sitemap_entries.append(f"""  <url>
    <loc>https://library.davidkarpay.com/{page}</loc>
    <priority>{priority}</priority>
    <changefreq>{changefreq}</changefreq>
  </url>""")

    # Content pages
    for entry in entries:
        content_type = entry.get("content_type", "video")
        filename = entry.get("_filename", "")
        if not filename:
            continue

        if content_type == "paper":
            path = f"papers/{filename}.html"
        elif content_type == "podcast":
            path = f"podcasts/{filename}.html"
        elif content_type == "blog":
            path = f"blogs/{filename}.html"
        else:
            path = f"transcripts/{filename}.html"

        sitemap_entries.append(f"""  <url>
    <loc>https://library.davidkarpay.com/{path}</loc>
    <priority>0.6</priority>
    <changefreq>monthly</changefreq>
  </url>""")

    sitemap_entries.append('</urlset>')
    (SITE_DIR / "sitemap.xml").write_text('\n'.join(sitemap_entries))
    print(f"  Generated sitemap.xml ({len(entries) + len(static_pages)} URLs)")

    # llms.txt - AI agent discovery guide
    topics_list = ", ".join(sorted(facet_index["topics"].keys()))
    llms_txt = f"""# Learning Library - AI Agent Guide
# Last updated: {today}
# Total items: {total}

## Description
A curated learning library containing educational content on technology, programming, AI/ML, security, and more.

Content types:
- Videos: {video_count} (YouTube transcripts with timestamps)
- Papers: {paper_count} (Research papers with abstracts)
- Podcasts: {podcast_count} (Audio transcripts)
- Blogs: {blog_count} (Technical articles)

Topics: {topics_list}

## Quick Access

Data:
- /library.json - Complete index with all metadata ({total} items)
- /sitemap.xml - All page URLs
- /.well-known/ai.json - Machine-readable API capabilities

## REST API

Base URL: https://youtube-library-docent.dlkarpay.workers.dev

Endpoints:
- GET /api/search?q=<query>&type=video|paper|podcast|blog|all&topic=<topic>&limit=20
- GET /api/recommend?topic=<topic>&level=beginner|intermediate|advanced&limit=10
- GET /api/learning-path?goal=<learning_goal>
- GET /api/whats-new?days=7&type=all
- GET /api/content/<id>
- GET /api/stats
- GET /api/facets
- POST /api/chat {{"message": "...", "context": []}}

## MCP Server

For Claude Desktop integration, add to claude_desktop_config.json:
{{
  "mcpServers": {{
    "learning-library": {{
      "command": "python",
      "args": ["/path/to/mcp_docent_server.py"]
    }}
  }}
}}

MCP Tools: search_library, recommend_by_topic, get_learning_path, find_related_content, get_whats_new, get_content_excerpt

## Schema

Content entry structure:
{{
  "id": "unique-id",
  "content_type": "video|paper|podcast|blog",
  "title": "Title",
  "url": "source-url",
  "facets": {{
    "topics": ["ai-ml", "security"],
    "format": "tutorial|deep-dive|research-paper",
    "difficulty": "beginner|intermediate|advanced"
  }},
  "summary": ["Key point 1", "Key point 2"],
  "sections": [{{"title": "...", "description": "..."}}]
}}

## Rate Limits
- API: 100 requests/minute per IP
- For bulk access, use /library.json directly
"""
    (SITE_DIR / "llms.txt").write_text(llms_txt)
    print("  Generated llms.txt")

    # .well-known/ai.json
    (SITE_DIR / ".well-known").mkdir(exist_ok=True)
    ai_json = {
        "version": "1.0",
        "name": "Learning Library",
        "description": f"Curated educational content library with {total} items",
        "updated": today,
        "content": {
            "total": total,
            "videos": video_count,
            "papers": paper_count,
            "podcasts": podcast_count,
            "blogs": blog_count
        },
        "topics": sorted(facet_index["topics"].keys()),
        "api": {
            "base_url": "https://youtube-library-docent.dlkarpay.workers.dev",
            "endpoints": [
                {"path": "/api/search", "method": "GET", "params": ["q", "type", "topic", "difficulty", "limit"]},
                {"path": "/api/recommend", "method": "GET", "params": ["topic", "level", "limit"]},
                {"path": "/api/learning-path", "method": "GET", "params": ["goal"]},
                {"path": "/api/whats-new", "method": "GET", "params": ["days", "type"]},
                {"path": "/api/content/{id}", "method": "GET"},
                {"path": "/api/chat", "method": "POST"}
            ]
        },
        "data": {
            "library_json": "https://library.davidkarpay.com/library.json",
            "sitemap": "https://library.davidkarpay.com/sitemap.xml",
            "llms_txt": "https://library.davidkarpay.com/llms.txt"
        },
        "mcp": {
            "available": True,
            "script": "mcp_docent_server.py",
            "tools": [
                "search_library",
                "recommend_by_topic",
                "get_learning_path",
                "find_related_content",
                "get_whats_new",
                "get_content_excerpt"
            ]
        }
    }
    with open(SITE_DIR / ".well-known" / "ai.json", "w") as f:
        json.dump(ai_json, f, indent=2)
    print("  Generated .well-known/ai.json")


if __name__ == "__main__":
    generate_site()
