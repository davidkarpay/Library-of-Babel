#!/bin/bash
#
# setup.sh - One-click setup for YouTube Learning Library
#
# This script installs all dependencies needed to run the YouTube Learning Library
# on a Mac. It's safe to run multiple times - it will skip already-installed components.
#
# Usage:
#   bash setup.sh
#
# Estimated time: 15-20 minutes (mostly downloading the AI model)
#

set -e  # Exit on error

# =============================================================================
# Colors and Formatting
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

print_header() {
    echo ""
    echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${BLUE}  $1${NC}"
    echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_step() {
    echo -e "${BOLD}→ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}! $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "  ${BLUE}$1${NC}"
}

# =============================================================================
# Check macOS
# =============================================================================

check_macos() {
    print_header "Checking System"

    if [[ "$OSTYPE" != "darwin"* ]]; then
        print_error "This script is designed for macOS only."
        print_info "Detected OS: $OSTYPE"
        exit 1
    fi

    print_success "Running on macOS"

    # Check macOS version
    macos_version=$(sw_vers -productVersion)
    print_info "macOS version: $macos_version"
}

# =============================================================================
# Install Xcode Command Line Tools
# =============================================================================

install_xcode_cli() {
    print_header "Xcode Command Line Tools"

    if xcode-select -p &>/dev/null; then
        print_success "Xcode Command Line Tools already installed"
    else
        print_step "Installing Xcode Command Line Tools..."
        print_info "A dialog may appear - click 'Install' to continue"
        xcode-select --install 2>/dev/null || true

        # Wait for installation
        echo ""
        print_warning "Please complete the Xcode Command Line Tools installation"
        print_info "Press Enter once the installation is complete..."
        read -r

        if xcode-select -p &>/dev/null; then
            print_success "Xcode Command Line Tools installed"
        else
            print_error "Xcode Command Line Tools installation failed"
            print_info "Please install manually and run this script again"
            exit 1
        fi
    fi
}

# =============================================================================
# Install Homebrew
# =============================================================================

install_homebrew() {
    print_header "Homebrew Package Manager"

    if command -v brew &>/dev/null; then
        print_success "Homebrew already installed"
        print_step "Updating Homebrew..."
        brew update --quiet
        print_success "Homebrew updated"
    else
        print_step "Installing Homebrew..."
        print_info "This may take a few minutes"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Add Homebrew to PATH for Apple Silicon Macs
        if [[ -f "/opt/homebrew/bin/brew" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
        fi

        if command -v brew &>/dev/null; then
            print_success "Homebrew installed"
        else
            print_error "Homebrew installation failed"
            exit 1
        fi
    fi
}

# =============================================================================
# Install Python 3
# =============================================================================

install_python() {
    print_header "Python 3"

    # Check if Python 3.9+ is available
    if command -v python3 &>/dev/null; then
        python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo "$python_version" | cut -d. -f1)
        minor=$(echo "$python_version" | cut -d. -f2)

        if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 9 ]]; then
            print_success "Python $python_version already installed"
            return
        else
            print_warning "Python $python_version found, but 3.9+ required"
        fi
    fi

    print_step "Installing Python 3.11 via Homebrew..."
    brew install python@3.11 --quiet

    # Verify installation
    if command -v python3 &>/dev/null; then
        python_version=$(python3 --version)
        print_success "$python_version installed"
    else
        print_error "Python installation failed"
        exit 1
    fi
}

# =============================================================================
# Install Python Packages
# =============================================================================

install_pip_packages() {
    print_header "Python Packages"

    packages=(
        "youtube-transcript-api"
        "requests"
        "jinja2"
        "scrapetube"
        "flask"
        "whoosh"
    )

    print_step "Installing required packages..."

    for package in "${packages[@]}"; do
        print_info "Installing $package..."
        pip3 install --quiet "$package"
    done

    print_success "All Python packages installed"
}

# =============================================================================
# Install Ollama
# =============================================================================

install_ollama() {
    print_header "Ollama (AI Engine)"

    if command -v ollama &>/dev/null; then
        print_success "Ollama already installed"
    else
        print_step "Installing Ollama via Homebrew..."
        brew install ollama --quiet

        if command -v ollama &>/dev/null; then
            print_success "Ollama installed"
        else
            print_error "Ollama installation failed"
            print_info "Try downloading manually from https://ollama.ai"
            exit 1
        fi
    fi
}

# =============================================================================
# Start Ollama and Pull Model
# =============================================================================

setup_ollama_model() {
    print_header "AI Model Setup"

    # Check if Ollama is running
    print_step "Starting Ollama service..."

    # Try to start Ollama in background
    if ! curl -s http://localhost:11434 &>/dev/null; then
        # Start Ollama service
        ollama serve &>/dev/null &
        OLLAMA_PID=$!

        # Wait for Ollama to start
        print_info "Waiting for Ollama to start..."
        for i in {1..30}; do
            if curl -s http://localhost:11434 &>/dev/null; then
                break
            fi
            sleep 1
        done
    fi

    if curl -s http://localhost:11434 &>/dev/null; then
        print_success "Ollama is running"
    else
        print_warning "Could not start Ollama automatically"
        print_info "Please open the Ollama app from Applications and run this script again"
        exit 1
    fi

    # Check if model is already downloaded
    print_step "Checking for llama3.1:8b model..."

    if ollama list 2>/dev/null | grep -q "llama3.1:8b"; then
        print_success "Model llama3.1:8b already downloaded"
    else
        print_step "Downloading llama3.1:8b model..."
        print_info "This is ~4.7GB and may take 5-15 minutes"
        echo ""

        ollama pull llama3.1:8b

        if ollama list 2>/dev/null | grep -q "llama3.1"; then
            print_success "Model downloaded successfully"
        else
            print_error "Model download failed"
            print_info "Try running: ollama pull llama3.1:8b"
            exit 1
        fi
    fi
}

# =============================================================================
# Create Directories
# =============================================================================

create_directories() {
    print_header "Project Setup"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    directories=("transcripts" "metadata" "templates" "site")

    for dir in "${directories[@]}"; do
        if [[ -d "$SCRIPT_DIR/$dir" ]]; then
            print_success "$dir/ directory exists"
        else
            mkdir -p "$SCRIPT_DIR/$dir"
            print_success "$dir/ directory created"
        fi
    done
}

# =============================================================================
# Run Validation
# =============================================================================

run_validation() {
    print_header "Validating Setup"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [[ -f "$SCRIPT_DIR/validate_setup.py" ]]; then
        print_step "Running validation script..."
        echo ""
        python3 "$SCRIPT_DIR/validate_setup.py"
    else
        print_warning "validate_setup.py not found, skipping validation"
    fi
}

# =============================================================================
# Success Message
# =============================================================================

print_success_message() {
    echo ""
    echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${GREEN}  Setup Complete!${NC}"
    echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${BOLD}Next Steps:${NC}"
    echo ""
    echo -e "  1. Add your first video:"
    echo -e "     ${BLUE}python3 youtube_transcript_to_md.py \"https://youtube.com/watch?v=...\"${NC}"
    echo ""
    echo -e "  2. Generate the library website:"
    echo -e "     ${BLUE}python3 library.py${NC}"
    echo ""
    echo -e "  3. Open ${BLUE}site/index.html${NC} in your browser"
    echo ""
    echo -e "${BOLD}For more help:${NC}"
    echo -e "  - Open ${BLUE}setup-guide.html${NC} for detailed instructions"
    echo -e "  - Run ${BLUE}python3 validate_setup.py${NC} to check your setup"
    echo ""
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo ""
    echo -e "${BOLD}YouTube Learning Library - Setup Script${NC}"
    echo -e "This will install all required dependencies."
    echo -e "Estimated time: 15-20 minutes"
    echo ""
    echo -e "Press Enter to continue (or Ctrl+C to cancel)..."
    read -r

    check_macos
    install_xcode_cli
    install_homebrew
    install_python
    install_pip_packages
    install_ollama
    setup_ollama_model
    create_directories
    run_validation
    print_success_message
}

# Run main function
main
