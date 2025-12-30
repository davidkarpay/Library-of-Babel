# YouTube Learning Library

A personal, searchable library from YouTube videos. Downloads transcripts, uses AI to analyze and summarize content, and builds a beautiful website you can browse offline.

```
YouTube Video  →  AI Analysis  →  Searchable Library
```

## Quick Start (Mac)

**One-click setup:**
```bash
bash setup.sh
```

This installs everything automatically (~15-20 minutes).

---

## Manual Setup Guide

### Before You Start

Make sure you have:
- [ ] A Mac computer (any recent model)
- [ ] At least 8GB of RAM
- [ ] At least 10GB of free disk space
- [ ] An internet connection
- [ ] About 30 minutes of time

---

### Step 1: Open Terminal

Terminal is the app where you'll type commands.

1. Press **Command + Space** (opens Spotlight search)
2. Type **Terminal**
3. Press **Enter**

> **Tip:** Keep Terminal open throughout this entire setup process.

---

### Step 2: Check Python Installation

Most Macs already have Python installed.

```bash
python3 --version
```

**Expected output:** `Python 3.11.6` (or any version 3.9 or higher)

<details>
<summary>What if Python is not installed?</summary>

If you see "command not found":
1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Click the yellow "Download Python" button
3. Open the downloaded file and follow the installer
4. Close Terminal and reopen it
5. Try the command again

</details>

---

### Step 3: Install Required Packages

```bash
pip3 install youtube-transcript-api requests jinja2 scrapetube flask whoosh
```

Wait until it finishes and you see your cursor again.

<details>
<summary>What do these packages do?</summary>

- **youtube-transcript-api** - Downloads transcripts from YouTube videos
- **requests** - Lets the tool talk to websites
- **jinja2** - Creates the HTML pages for your library
- **scrapetube** - Finds all videos on a YouTube channel
- **flask** - Powers the search feature
- **whoosh** - Makes searching fast

</details>

---

### Step 4: Install Ollama (The AI Brain)

Ollama is a free app that runs AI on your Mac. It analyzes videos and creates summaries.

**Option A - Download from website (easiest):**
1. Go to [ollama.ai](https://ollama.ai)
2. Click "Download for macOS"
3. Open the downloaded file and drag Ollama to your Applications folder
4. Open Ollama from your Applications folder (you'll see a llama icon in your menu bar)

**Option B - Using Homebrew:**
```bash
brew install ollama
```

---

### Step 5: Download the AI Model

This is about 4.7GB and may take 5-15 minutes.

```bash
ollama pull llama3.1:8b
```

> **Tip:** This only needs to be done once. The model stays on your computer.

---

### Step 6: Start the Ollama Server

The AI needs to be running in the background.

```bash
ollama serve
```

> **Important:** This command keeps running and won't give you your cursor back. That's normal!

**Now open a NEW Terminal window:** Press **Command + N**

> **Tip:** If you downloaded Ollama from their website and it's running in your menu bar, you can skip this step - it starts automatically!

---

### Step 7: Navigate to the Tool Folder

In your new Terminal window:

```bash
cd ~/Desktop/youtube_transcript_to_md
```

> **Tip:** If you saved the folder somewhere else, replace the path with your actual location.

---

### Step 8: Test It Works!

Add your first video:

```bash
python3 youtube_transcript_to_md.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

You'll see progress messages as the AI analyzes the video (1-3 minutes).

---

### Step 9: Generate Your Library Website

```bash
python3 library.py
```

To view your library, open the **site** folder and double-click **index.html**!

---

## Common Commands

### Add a Single Video
```bash
python3 youtube_transcript_to_md.py "YOUTUBE_URL_HERE"
```

### Import All Videos from a Channel
```bash
python3 channel_import.py "https://www.youtube.com/@ChannelName"
```

### Import Multiple Videos from a List
Create a text file with YouTube URLs (one per line), then:
```bash
python3 batch_import.py your_list.md
```

### Rebuild the Website
Run after adding new videos:
```bash
python3 library.py
```

### Start the Search Server
```bash
python3 search_server.py
```
Then visit [http://localhost:5000](http://localhost:5000) in your browser.

### Validate Your Setup
```bash
python3 validate_setup.py
```

---

## Troubleshooting

<details>
<summary>"command not found: python3"</summary>

Python isn't installed. Go to [python.org/downloads](https://python.org/downloads) and install it, then restart Terminal.

</details>

<details>
<summary>"command not found: pip3"</summary>

Try using `python3 -m pip install` instead of `pip3 install`.

</details>

<details>
<summary>"No transcript available" error</summary>

This video doesn't have captions/subtitles on YouTube. You can:
- Try a different video
- Use manual import: `python3 manual_import.py "URL"` and paste the transcript yourself

</details>

<details>
<summary>"Ollama request failed" or AI analysis not working</summary>

Make sure Ollama is running:
1. Check if the Ollama llama icon is in your menu bar (top of screen)
2. If not, open Ollama from your Applications folder
3. Or run `ollama serve` in a Terminal window

</details>

<details>
<summary>"Permission denied" error</summary>

Try adding `sudo` before the command:
```bash
sudo pip3 install youtube-transcript-api requests jinja2 scrapetube flask whoosh
```

</details>

<details>
<summary>Processing is very slow</summary>

This is normal! The AI runs locally on your Mac, which takes time. Each 3-minute section takes about 30-60 seconds to analyze. A 20-minute video might take 5-10 minutes total.

Newer Apple Silicon Macs (M1, M2, M3) are significantly faster than Intel Macs.

</details>

---

## Glossary

| Term | Meaning |
|------|---------|
| **Terminal** | An app on your Mac where you type text commands instead of clicking buttons |
| **Python** | A programming language. You don't need to learn it - just have it installed |
| **pip** | A tool that installs Python add-ons. Like an app store for Python tools |
| **Ollama** | An app that runs AI models on your Mac. The "brain" that analyzes videos |
| **LLM** | Large Language Model - the type of AI that understands text. ChatGPT is an LLM |
| **Transcript** | The written text of everything said in a video, with timestamps |

---

## Files

| File | Purpose |
|------|---------|
| `setup.sh` | One-click automated installer |
| `setup-guide.html` | Visual setup guide (open in browser) |
| `validate_setup.py` | Check if your setup is correct |
| `youtube_transcript_to_md.py` | Add a single video |
| `batch_import.py` | Import videos from a URL list |
| `channel_import.py` | Import all videos from a channel |
| `manual_import.py` | Add video by pasting transcript |
| `library.py` | Generate the browsable website |
| `search_server.py` | Start the search server |

---

## License

MIT
