/**
 * Learning Library Docent Widget
 * Floating chat interface for interacting with the docent API
 */

(function() {
  'use strict';

  // Configuration
  const API_BASE = 'https://youtube-library-docent.dlkarpay.workers.dev';
  const STORAGE_KEY = 'docent_chat_history';
  const MAX_HISTORY = 20;

  // State
  let isOpen = false;
  let isLoading = false;
  let messages = [];

  // DOM Elements
  let widget, button, chatWindow, messagesContainer, inputField, sendButton;

  /**
   * Initialize the widget
   */
  function init() {
    createWidget();
    loadHistory();
    attachEventListeners();
  }

  /**
   * Create widget DOM elements
   */
  function createWidget() {
    // Main container
    widget = document.createElement('div');
    widget.id = 'docent-widget';
    widget.innerHTML = `
      <button id="docent-button" aria-label="Ask the Library Docent">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      </button>
      <div id="docent-chat" class="docent-hidden">
        <div class="docent-header">
          <span>Library Docent</span>
          <button class="docent-close" aria-label="Close">&times;</button>
        </div>
        <div class="docent-messages"></div>
        <div class="docent-input-area">
          <input type="text" placeholder="Ask about videos, papers, or topics..." aria-label="Message">
          <button class="docent-send" aria-label="Send">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(widget);

    // Get references
    button = document.getElementById('docent-button');
    chatWindow = document.getElementById('docent-chat');
    messagesContainer = chatWindow.querySelector('.docent-messages');
    inputField = chatWindow.querySelector('input');
    sendButton = chatWindow.querySelector('.docent-send');
  }

  /**
   * Attach event listeners
   */
  function attachEventListeners() {
    button.addEventListener('click', toggleChat);
    chatWindow.querySelector('.docent-close').addEventListener('click', toggleChat);
    sendButton.addEventListener('click', sendMessage);
    inputField.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  /**
   * Toggle chat window visibility
   */
  function toggleChat() {
    isOpen = !isOpen;
    chatWindow.classList.toggle('docent-hidden', !isOpen);
    button.classList.toggle('docent-active', isOpen);

    if (isOpen) {
      inputField.focus();
      // Show welcome message if no history
      if (messages.length === 0) {
        addMessage('docent', "Welcome! I'm the Library Docent. Ask me about videos, papers, or topics you'd like to learn about.");
      }
    }
  }

  /**
   * Send a message to the docent
   */
  async function sendMessage() {
    const text = inputField.value.trim();
    if (!text || isLoading) return;

    inputField.value = '';
    addMessage('user', text);

    isLoading = true;
    sendButton.disabled = true;

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
      });

      if (!response.ok) throw new Error('API error');

      const data = await response.json();

      // Add response text
      addMessage('docent', data.response);

      // Add recommendation cards if present
      if (data.recommendations && data.recommendations.length > 0) {
        addRecommendations(data.recommendations);
      }

    } catch (error) {
      console.error('Docent error:', error);
      addMessage('docent', "Sorry, I'm having trouble connecting. Please try again later.");
    } finally {
      isLoading = false;
      sendButton.disabled = false;
    }
  }

  /**
   * Add a message to the chat
   */
  function addMessage(role, text) {
    const msg = { role, text, timestamp: Date.now() };
    messages.push(msg);

    const msgEl = document.createElement('div');
    msgEl.className = `docent-message docent-${role}`;
    msgEl.innerHTML = formatMessage(text);
    messagesContainer.appendChild(msgEl);

    // Only auto-scroll for user messages, not bot responses
    if (role === 'user') {
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    saveHistory();
  }

  /**
   * Add recommendation cards
   */
  function addRecommendations(recs) {
    const container = document.createElement('div');
    container.className = 'docent-recommendations';

    for (const rec of recs.slice(0, 3)) {
      const card = document.createElement('a');
      card.className = 'docent-rec-card';

      // Determine link
      if (rec.content_type === 'paper') {
        card.href = `papers/${rec.slug || rec._filename}.html`;
      } else {
        card.href = `transcripts/${rec.slug || rec._filename}.html`;
      }

      const type = rec.content_type === 'paper' ? 'Paper' : 'Video';
      const badge = rec.content_type === 'paper' ? 'paper-badge' : 'video-badge';

      card.innerHTML = `
        <span class="docent-badge ${badge}">${type}</span>
        <span class="docent-rec-title">${escapeHtml(rec.title)}</span>
      `;

      container.appendChild(card);
    }

    messagesContainer.appendChild(container);
  }

  /**
   * Format message text (convert markdown-like syntax)
   */
  function formatMessage(text) {
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }

  /**
   * Escape HTML entities
   */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Save chat history to sessionStorage
   */
  function saveHistory() {
    const trimmed = messages.slice(-MAX_HISTORY);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    } catch (e) {
      // Storage full or unavailable
    }
  }

  /**
   * Load chat history from sessionStorage
   */
  function loadHistory() {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY);
      if (saved) {
        messages = JSON.parse(saved);
        for (const msg of messages) {
          const msgEl = document.createElement('div');
          msgEl.className = `docent-message docent-${msg.role}`;
          msgEl.innerHTML = formatMessage(msg.text);
          messagesContainer.appendChild(msgEl);
        }
      }
    } catch (e) {
      // Storage unavailable
    }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
