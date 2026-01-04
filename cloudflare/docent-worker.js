/**
 * Cloudflare Worker - Learning Library Docent API
 *
 * Provides an agentic docent experience with:
 * - Search across videos and papers
 * - Topic-based recommendations
 * - Learning path generation
 * - Recent content discovery
 * - Conversational chat interface
 */

// Configuration
const LIBRARY_URL = 'https://library.davidkarpay.com/library.json';
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

// Allowed origins for CORS
const ALLOWED_ORIGINS = new Set([
  'https://library.davidkarpay.com',
  'https://davidkarpay.com',
  'https://youtube-library.pages.dev',
  'http://localhost:8000',
  'http://127.0.0.1:8000'
]);

// In-memory cache for library data
let libraryCache = {
  data: null,
  fetchedAt: 0
};

/**
 * Security headers for all responses
 */
const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin'
};

/**
 * Fetch and cache library.json
 */
async function fetchLibrary() {
  const now = Date.now();

  // Return cached data if fresh
  if (libraryCache.data && (now - libraryCache.fetchedAt) < CACHE_TTL_MS) {
    return libraryCache.data;
  }

  try {
    const response = await fetch(LIBRARY_URL);
    if (!response.ok) {
      throw new Error(`Failed to fetch library: ${response.status}`);
    }

    const data = await response.json();
    libraryCache = { data, fetchedAt: now };
    return data;
  } catch (error) {
    // If fetch fails but we have stale cache, use it
    if (libraryCache.data) {
      console.error('Using stale cache:', error.message);
      return libraryCache.data;
    }
    throw error;
  }
}

/**
 * Create JSON response with CORS headers
 */
function jsonResponse(data, status, origin) {
  const headers = {
    'Content-Type': 'application/json',
    ...SECURITY_HEADERS
  };

  if (origin && ALLOWED_ORIGINS.has(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS';
    headers['Access-Control-Allow-Headers'] = 'Content-Type';
  }

  return new Response(JSON.stringify(data), { status, headers });
}

/**
 * Error response helper
 */
function errorResponse(message, status, origin) {
  return jsonResponse({ error: message }, status, origin);
}

/**
 * Check if entry matches filters
 */
function matchesFilters(entry, filters) {
  if (filters.type && filters.type !== 'all') {
    if (entry.content_type !== filters.type) return false;
  }

  if (filters.topic) {
    const topics = entry.facets?.topics || [];
    if (!topics.includes(filters.topic)) return false;
  }

  if (filters.difficulty) {
    if (entry.facets?.difficulty !== filters.difficulty) return false;
  }

  if (filters.format) {
    if (entry.facets?.format !== filters.format) return false;
  }

  if (filters.channel) {
    const channelSlug = entry.channel?.slug || '';
    if (channelSlug !== filters.channel) return false;
  }

  return true;
}

/**
 * Score an entry against search terms
 */
function scoreEntry(entry, terms) {
  if (!terms || terms.length === 0) return 1; // No query = return all

  let score = 0;
  const title = (entry.title || '').toLowerCase();
  const summary = (entry.summary || []).join(' ').toLowerCase();
  const abstract = (entry.abstract || '').toLowerCase();
  const topics = (entry.facets?.topics || []).join(' ').toLowerCase();
  const channelName = (entry.channel?.name || '').toLowerCase();

  for (const term of terms) {
    // Title matches (highest weight)
    if (title.includes(term)) score += 3;

    // Topic matches (high weight)
    if (topics.includes(term)) score += 2.5;

    // Channel name matches
    if (channelName.includes(term)) score += 2;

    // Summary/abstract matches
    if (summary.includes(term)) score += 2;
    if (abstract.includes(term)) score += 2;

    // Section title matches
    const sections = entry.sections || [];
    for (const section of sections) {
      if ((section.title || '').toLowerCase().includes(term)) {
        score += 1;
        break; // Only count once per entry
      }
    }
  }

  return score;
}

/**
 * Search the library
 */
function search(entries, query, filters = {}) {
  const terms = query ? query.toLowerCase().split(/\s+/).filter(t => t.length > 1) : [];
  const limit = Math.min(parseInt(filters.limit) || 20, 50);

  const results = entries
    .filter(e => matchesFilters(e, filters))
    .map(e => {
      const score = scoreEntry(e, terms);
      return { ...e, _score: score };
    })
    .filter(e => terms.length === 0 || e._score > 0)
    .sort((a, b) => b._score - a._score)
    .slice(0, limit);

  // Clean up internal score field for response
  return results.map(({ _score, ...rest }) => ({ ...rest, score: _score }));
}

/**
 * Get recommendations by topic and level
 */
function recommend(entries, topic, level, limit = 10) {
  // Filter by topic first
  let filtered = entries.filter(e => {
    const topics = e.facets?.topics || [];
    return topics.includes(topic);
  });

  // Filter by level if specified
  if (level) {
    filtered = filtered.filter(e => e.facets?.difficulty === level);
  }

  // Sort by recency (added_date) and quality indicators
  filtered.sort((a, b) => {
    // Papers: sort by upvotes
    if (a.content_type === 'paper' && b.content_type === 'paper') {
      return (b.upvotes || 0) - (a.upvotes || 0);
    }
    // Videos: sort by date
    const dateA = new Date(a.added_date || 0);
    const dateB = new Date(b.added_date || 0);
    return dateB - dateA;
  });

  return filtered.slice(0, limit);
}

/**
 * Generate a learning path from beginner to advanced
 */
function getLearningPath(entries, goal) {
  // Extract keywords from goal
  const terms = goal.toLowerCase().split(/\s+/).filter(t => t.length > 2);

  // Find relevant entries
  const relevant = entries
    .map(e => ({ ...e, _score: scoreEntry(e, terms) }))
    .filter(e => e._score > 0)
    .sort((a, b) => b._score - a._score);

  // Group by difficulty
  const byLevel = {
    beginner: [],
    intermediate: [],
    advanced: []
  };

  for (const entry of relevant) {
    const level = entry.facets?.difficulty || 'intermediate';
    if (byLevel[level] && byLevel[level].length < 5) {
      const { _score, ...clean } = entry;
      byLevel[level].push(clean);
    }
  }

  return [
    { level: 'beginner', items: byLevel.beginner },
    { level: 'intermediate', items: byLevel.intermediate },
    { level: 'advanced', items: byLevel.advanced }
  ].filter(level => level.items.length > 0);
}

/**
 * Get recently added content
 */
function getWhatsNew(entries, days = 7, contentType = 'all') {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = cutoff.toISOString().split('T')[0];

  let filtered = entries.filter(e => {
    const addedDate = e.added_date || '1970-01-01';
    return addedDate >= cutoffStr;
  });

  if (contentType !== 'all') {
    filtered = filtered.filter(e => e.content_type === contentType);
  }

  // Sort by date descending
  filtered.sort((a, b) => {
    const dateA = new Date(a.added_date || 0);
    const dateB = new Date(b.added_date || 0);
    return dateB - dateA;
  });

  return {
    since: cutoffStr,
    count: filtered.length,
    items: filtered.slice(0, 50)
  };
}

/**
 * Get content by ID
 */
function getContent(entries, id) {
  return entries.find(e => e.id === id || e.slug === id || e._filename === id);
}

/**
 * Handle chat messages with hybrid search + response generation
 */
async function handleChat(entries, message, context = [], env) {
  // Extract potential search terms from the message
  const searchTerms = message
    .toLowerCase()
    .replace(/[^\w\s]/g, ' ')
    .split(/\s+/)
    .filter(t => t.length > 2)
    .filter(t => !['help', 'find', 'show', 'want', 'need', 'learn', 'about', 'the', 'for', 'and', 'with'].includes(t));

  // Search for relevant content
  const searchResults = search(entries, searchTerms.join(' '), { limit: 5 });

  // Build response based on results
  let response;
  if (searchResults.length === 0) {
    response = "I couldn't find any content matching your query. Try searching for specific topics like 'kubernetes', 'transformers', 'security', or browse by topic.";
  } else {
    const contentTypes = [...new Set(searchResults.map(r => r.content_type))];
    const typeWord = contentTypes.length === 1
      ? (contentTypes[0] === 'paper' ? 'papers' : 'videos')
      : 'resources';

    response = `I found ${searchResults.length} ${typeWord} that might help:\n\n`;

    for (const result of searchResults) {
      const type = result.content_type === 'paper' ? 'Paper' : 'Video';
      const summary = result.summary?.[0] || '';
      response += `- **${result.title}** (${type})\n`;
      if (summary) response += `  ${summary.slice(0, 100)}...\n`;
    }

    response += '\nWould you like me to find more specific content or explore a different topic?';
  }

  return {
    response,
    recommendations: searchResults,
    search_query: searchTerms.join(' ')
  };
}

/**
 * Main request handler
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin') || '';

    // Only handle /api/* routes
    if (!url.pathname.startsWith('/api/')) {
      return new Response('Not found', { status: 404 });
    }

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      if (!ALLOWED_ORIGINS.has(origin)) {
        return new Response('Forbidden', { status: 403 });
      }
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': origin,
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
          'Access-Control-Max-Age': '86400'
        }
      });
    }

    // Fetch library data
    let library;
    try {
      library = await fetchLibrary();
    } catch (error) {
      console.error('Failed to fetch library:', error);
      return errorResponse('Service temporarily unavailable', 503, origin);
    }

    const entries = library.entries || [];

    // Route handling
    const path = url.pathname;

    // GET /api/search
    if (path === '/api/search' && request.method === 'GET') {
      const query = url.searchParams.get('q') || '';
      const filters = {
        type: url.searchParams.get('type'),
        topic: url.searchParams.get('topic'),
        difficulty: url.searchParams.get('difficulty'),
        format: url.searchParams.get('format'),
        channel: url.searchParams.get('channel'),
        limit: url.searchParams.get('limit')
      };

      const results = search(entries, query, filters);

      return jsonResponse({
        query,
        filters: Object.fromEntries(Object.entries(filters).filter(([_, v]) => v)),
        total: results.length,
        results
      }, 200, origin);
    }

    // GET /api/recommend
    if (path === '/api/recommend' && request.method === 'GET') {
      const topic = url.searchParams.get('topic');
      const level = url.searchParams.get('level');
      const limit = parseInt(url.searchParams.get('limit')) || 10;

      if (!topic) {
        return errorResponse('Missing required parameter: topic', 400, origin);
      }

      const recommendations = recommend(entries, topic, level, limit);

      return jsonResponse({
        topic,
        level: level || 'all',
        count: recommendations.length,
        recommendations
      }, 200, origin);
    }

    // GET /api/learning-path
    if (path === '/api/learning-path' && request.method === 'GET') {
      const goal = url.searchParams.get('goal');

      if (!goal) {
        return errorResponse('Missing required parameter: goal', 400, origin);
      }

      const path = getLearningPath(entries, goal);

      return jsonResponse({
        goal,
        path,
        total_items: path.reduce((sum, level) => sum + level.items.length, 0)
      }, 200, origin);
    }

    // GET /api/whats-new
    if (path === '/api/whats-new' && request.method === 'GET') {
      const days = parseInt(url.searchParams.get('days')) || 7;
      const type = url.searchParams.get('type') || 'all';

      const result = getWhatsNew(entries, days, type);

      return jsonResponse(result, 200, origin);
    }

    // GET /api/content/:id
    if (path.startsWith('/api/content/') && request.method === 'GET') {
      const id = path.replace('/api/content/', '');
      const content = getContent(entries, id);

      if (!content) {
        return errorResponse('Content not found', 404, origin);
      }

      return jsonResponse(content, 200, origin);
    }

    // GET /api/stats
    if (path === '/api/stats' && request.method === 'GET') {
      return jsonResponse({
        total: entries.length,
        video_count: library.video_count || entries.filter(e => e.content_type === 'video').length,
        paper_count: library.paper_count || entries.filter(e => e.content_type === 'paper').length,
        facets: library.facets,
        channels_count: library.channels?.length || 0
      }, 200, origin);
    }

    // POST /api/chat
    if (path === '/api/chat' && request.method === 'POST') {
      try {
        const body = await request.json();
        const message = body.message;
        const context = body.context || [];

        if (!message) {
          return errorResponse('Missing required field: message', 400, origin);
        }

        const result = await handleChat(entries, message, context, env);

        return jsonResponse(result, 200, origin);
      } catch (error) {
        console.error('Chat error:', error);
        return errorResponse('Invalid request', 400, origin);
      }
    }

    // GET /api/facets
    if (path === '/api/facets' && request.method === 'GET') {
      return jsonResponse({
        topics: library.facets?.topics || [],
        formats: library.facets?.formats || [],
        difficulties: library.facets?.difficulties || [],
        channels: library.channels || []
      }, 200, origin);
    }

    return errorResponse('Not found', 404, origin);
  }
};
