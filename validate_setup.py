#!/usr/bin/env python3
"""
validate_setup.py

Validates that your system is correctly set up for the YouTube Learning Library.
Run this script to check all prerequisites before using the tool.

Usage:
    python3 validate_setup.py
"""

import shutil
import sys
import urllib.request
import urllib.error
import json
from pathlib import Path


# ANSI color codes
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def print_status(name: str, passed: bool, message: str = ""):
    """Print a check result with color coding."""
    if passed:
        status = f"{Colors.GREEN}PASS{Colors.RESET}"
    else:
        status = f"{Colors.RED}FAIL{Colors.RESET}"

    print(f"  [{status}] {name}")
    if message and not passed:
        print(f"         {Colors.YELLOW}{message}{Colors.RESET}")


def print_header(title: str):
    """Print a section header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{title}{Colors.RESET}")
    print("-" * 40)


def check_python_version() -> bool:
    """Check Python version is 3.9 or higher."""
    version = sys.version_info
    passed = version >= (3, 9)
    message = ""
    if not passed:
        message = f"Found Python {version.major}.{version.minor}, need 3.9+. Visit python.org/downloads"
    print_status(f"Python {version.major}.{version.minor}.{version.micro}", passed, message)
    return passed


def check_package(package_name: str, import_name: str = None) -> bool:
    """Check if a Python package is importable."""
    import_name = import_name or package_name
    try:
        __import__(import_name)
        print_status(package_name, True)
        return True
    except ImportError:
        print_status(package_name, False, f"Run: pip3 install {package_name}")
        return False


def check_ollama_installed() -> bool:
    """Check if Ollama is installed."""
    ollama_path = shutil.which('ollama')
    if ollama_path:
        print_status("Ollama installed", True)
        return True
    else:
        print_status("Ollama installed", False, "Download from ollama.ai or run: brew install ollama")
        return False


def check_ollama_running() -> bool:
    """Check if Ollama server is running."""
    try:
        req = urllib.request.Request("http://localhost:11434", method='GET')
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                print_status("Ollama server running", True)
                return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        pass

    print_status("Ollama server running", False, "Start Ollama from Applications or run: ollama serve")
    return False


def check_ollama_model() -> bool:
    """Check if the required model is downloaded."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method='GET')
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            models = [m.get('name', '') for m in data.get('models', [])]

            # Check for llama3.1:8b or similar
            has_model = any('llama3.1' in m or 'llama3.1:8b' in m for m in models)

            if has_model:
                print_status("llama3.1:8b model", True)
                return True
            else:
                print_status("llama3.1:8b model", False, "Run: ollama pull llama3.1:8b")
                return False
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        print_status("llama3.1:8b model", False, "Could not check - is Ollama running?")
        return False


def check_project_files() -> tuple:
    """Check that required project files exist."""
    required_files = [
        'youtube_transcript_to_md.py',
        'library.py',
        'batch_import.py',
        'channel_import.py',
        'manual_import.py'
    ]

    base_dir = Path(__file__).parent
    results = []

    for filename in required_files:
        filepath = base_dir / filename
        exists = filepath.exists()
        results.append(exists)
        if not exists:
            print_status(filename, False, "File missing - are you in the correct directory?")
        else:
            print_status(filename, True)

    return all(results), len([r for r in results if r]), len(required_files)


def check_directories() -> bool:
    """Check that required directories exist or can be created."""
    base_dir = Path(__file__).parent
    directories = ['transcripts', 'metadata', 'templates']

    all_ok = True
    for dirname in directories:
        dirpath = base_dir / dirname
        if dirpath.exists():
            print_status(f"{dirname}/ directory", True)
        else:
            # Try to create it
            try:
                dirpath.mkdir(exist_ok=True)
                print_status(f"{dirname}/ directory", True, "(created)")
            except Exception as e:
                print_status(f"{dirname}/ directory", False, f"Cannot create: {e}")
                all_ok = False

    return all_ok


def main():
    """Run all validation checks."""
    print(f"\n{Colors.BOLD}YouTube Learning Library - Setup Validation{Colors.RESET}")
    print("=" * 45)

    results = []

    # Python version
    print_header("Python")
    results.append(check_python_version())

    # Required packages
    print_header("Python Packages")
    packages = [
        ('youtube-transcript-api', 'youtube_transcript_api'),
        ('requests', 'requests'),
        ('jinja2', 'jinja2'),
        ('scrapetube', 'scrapetube'),
        ('flask', 'flask'),
        ('whoosh', 'whoosh'),
    ]
    for package_name, import_name in packages:
        results.append(check_package(package_name, import_name))

    # Ollama
    print_header("Ollama (AI)")
    ollama_installed = check_ollama_installed()
    results.append(ollama_installed)

    if ollama_installed:
        ollama_running = check_ollama_running()
        results.append(ollama_running)

        if ollama_running:
            results.append(check_ollama_model())
        else:
            print_status("llama3.1:8b model", False, "Cannot check - Ollama not running")
            results.append(False)
    else:
        print_status("Ollama server running", False, "Install Ollama first")
        print_status("llama3.1:8b model", False, "Install Ollama first")
        results.extend([False, False])

    # Project files
    print_header("Project Files")
    files_ok, files_found, files_total = check_project_files()

    # Directories
    print_header("Directories")
    results.append(check_directories())

    # Summary
    passed = sum(results)
    total = len(results)

    print("\n" + "=" * 45)
    if passed == total:
        print(f"{Colors.GREEN}{Colors.BOLD}All checks passed! ({passed}/{total}){Colors.RESET}")
        print("\nYou're ready to use the YouTube Learning Library!")
        print(f"Try: {Colors.BLUE}python3 youtube_transcript_to_md.py \"<youtube_url>\"{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}Some checks failed ({passed}/{total} passed){Colors.RESET}")
        print("\nPlease fix the issues above before using the tool.")
        print(f"See {Colors.BLUE}setup-guide.html{Colors.RESET} for detailed instructions.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
