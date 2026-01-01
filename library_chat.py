#!/usr/bin/env python3
"""
library_chat.py

Interactive CLI for conversational library search.
Uses the search server's AI chat endpoint to find relevant videos.

Usage:
    python library_chat.py
    python library_chat.py --server http://localhost:5001

Requires:
    - search_server.py running with AI chat endpoints
    - Ollama server running (local or cloud)
"""

import sys
import os
import json
import requests
import readline  # Enables arrow keys and history in input()
from typing import Optional

# Default server URL
DEFAULT_SERVER = os.environ.get("LIBRARY_SERVER", "http://localhost:5001")


def format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m" if mins else f"{hours}h"


def print_header():
    """Print the welcome header."""
    print()
    print("YouTube Learning Library Assistant")
    print("=" * 40)
    print("Type your question to search 1,708 videos.")
    print("Commands: /help, /stats, /quit")
    print("=" * 40)
    print()


def print_help():
    """Print help information."""
    print("""
Commands:
  /help     - Show this help message
  /stats    - Show library statistics
  /clear    - Clear conversation history
  /quit     - Exit the assistant

Tips:
  - Ask natural language questions about topics
  - Request learning paths or recommendations
  - Ask for specific video suggestions
  - Say "build a prompt for..." to create prompts

Examples:
  "Find videos about Kubernetes security"
  "What's a good learning path for databases?"
  "Recommend beginner videos on AI"
  "Build a prompt for implementing OAuth"
""")


def get_stats(server: str) -> Optional[dict]:
    """Fetch library statistics."""
    try:
        response = requests.get(f"{server}/api/stats", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching stats: {e}")
        return None


def chat(server: str, messages: list) -> Optional[dict]:
    """Send chat request to server."""
    try:
        response = requests.post(
            f"{server}/api/chat",
            json={"messages": messages},
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("Request timed out. The AI might be processing a complex query.")
        return None
    except requests.exceptions.ConnectionError:
        print(f"Could not connect to server at {server}")
        print("Make sure search_server.py is running.")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None


def display_response(result: dict):
    """Display the AI response and video results."""
    response = result.get("response", "")
    videos = result.get("videos_found", [])

    # Print AI response
    print()
    print(response)

    # If there are videos not mentioned in the response, show them
    if videos and len(videos) > 3:
        print()
        print(f"({len(videos)} total videos found)")


def main():
    """Main interactive loop."""
    import argparse

    parser = argparse.ArgumentParser(description="Interactive library search assistant")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Server URL")
    args = parser.parse_args()

    server = args.server

    # Check server connection
    print(f"Connecting to {server}...")
    stats = get_stats(server)
    if not stats:
        print("Failed to connect. Is search_server.py running?")
        sys.exit(1)

    print_header()

    # Conversation history for multi-turn chat
    messages = []

    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.lower() == "/quit" or user_input.lower() == "/exit":
                print("Goodbye!")
                break

            if user_input.lower() == "/help":
                print_help()
                continue

            if user_input.lower() == "/stats":
                stats = get_stats(server)
                if stats:
                    print(f"\nLibrary: {stats.get('documents', 0)} videos indexed")
                continue

            if user_input.lower() == "/clear":
                messages = []
                print("Conversation cleared.")
                continue

            # Add user message to history
            messages.append({"role": "user", "content": user_input})

            # Send to AI
            print()
            print("Searching library...")
            result = chat(server, messages)

            if result:
                # Add assistant response to history
                ai_response = result.get("response", "")
                if ai_response:
                    messages.append({"role": "assistant", "content": ai_response})

                display_response(result)

            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()
