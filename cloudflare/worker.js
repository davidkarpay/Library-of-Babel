/**
 * Cloudflare Worker - Secure Ollama Pro Proxy
 *
 * Security features:
 * - API key hidden in environment secret
 * - Exact origin matching (no bypass possible)
 * - Persistent rate limiting via Cloudflare KV
 * - Hardcoded model (no user override)
 * - Security headers (CSP, X-Frame-Options, HSTS)
 * - Request size limits
 * - Generic error messages (no info leakage)
 */

// Exact allowed origins - no prefix matching
const ALLOWED_ORIGINS = new Set([
  'https://library.davidkarpay.com',
  'https://davidkarpay.com',
  'https://youtube-library.pages.dev',
  'http://localhost:8000',
  'http://127.0.0.1:8000'
]);

// Ollama Pro API endpoint
const OLLAMA_API_URL = 'https://ollama.com';

// Hardcoded model - users cannot override
const MODEL = 'gpt-oss:120b-cloud';

// Rate limiting configuration
const RATE_LIMIT = {
  PER_IP_PER_MINUTE: 10,
  GLOBAL_PER_DAY: 500,
  WINDOW_SECONDS: 60,
  DAY_SECONDS: 86400
};

// Max request body size (10KB)
const MAX_BODY_SIZE = 10 * 1024;

/**
 * Security headers for all responses
 */
const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'X-XSS-Protection': '1; mode=block',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  'Strict-Transport-Security': 'max-age=31536000; includeSubDomains'
};

/**
 * Check rate limit using Cloudflare KV
 */
async function checkRateLimit(ip, env) {
  const now = Math.floor(Date.now() / 1000);
  const minuteKey = `ip:${ip}:${Math.floor(now / RATE_LIMIT.WINDOW_SECONDS)}`;
  const dayKey = `global:${Math.floor(now / RATE_LIMIT.DAY_SECONDS)}`;

  try {
    // Check per-IP limit
    const ipCount = parseInt(await env.RATE_LIMIT.get(minuteKey)) || 0;
    if (ipCount >= RATE_LIMIT.PER_IP_PER_MINUTE) {
      return {
        allowed: false,
        reason: 'Rate limit exceeded. Please wait a minute.',
        retryAfter: RATE_LIMIT.WINDOW_SECONDS - (now % RATE_LIMIT.WINDOW_SECONDS)
      };
    }

    // Check global daily limit
    const globalCount = parseInt(await env.RATE_LIMIT.get(dayKey)) || 0;
    if (globalCount >= RATE_LIMIT.GLOBAL_PER_DAY) {
      return {
        allowed: false,
        reason: 'Service limit reached. Try again tomorrow.',
        retryAfter: RATE_LIMIT.DAY_SECONDS - (now % RATE_LIMIT.DAY_SECONDS)
      };
    }

    // Increment counters BEFORE returning (await for consistency)
    await Promise.all([
      env.RATE_LIMIT.put(minuteKey, String(ipCount + 1), { expirationTtl: RATE_LIMIT.WINDOW_SECONDS * 2 }),
      env.RATE_LIMIT.put(dayKey, String(globalCount + 1), { expirationTtl: RATE_LIMIT.DAY_SECONDS * 2 })
    ]);

    return {
      allowed: true,
      remaining: RATE_LIMIT.PER_IP_PER_MINUTE - ipCount - 1,
      dailyRemaining: RATE_LIMIT.GLOBAL_PER_DAY - globalCount - 1
    };
  } catch (error) {
    // If KV fails, allow request but log error
    console.error('Rate limit check failed:', error);
    return { allowed: true, remaining: -1, dailyRemaining: -1 };
  }
}

/**
 * Get client IP from Cloudflare headers
 */
function getClientIP(request) {
  // CF-Connecting-IP is set by Cloudflare and cannot be spoofed
  return request.headers.get('CF-Connecting-IP') || 'unknown';
}

/**
 * Create response with security headers
 */
function secureResponse(body, status, origin, extraHeaders = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...SECURITY_HEADERS,
    ...extraHeaders
  };

  // Only add CORS headers for allowed origins
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS';
  }

  return new Response(JSON.stringify(body), { status, headers });
}

/**
 * Generic error response (no internal details)
 */
function errorResponse(message, status, origin, retryAfter = null) {
  const headers = retryAfter ? { 'Retry-After': String(retryAfter) } : {};
  return secureResponse({ error: message }, status, origin, headers);
}

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
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
          'Access-Control-Max-Age': '86400',
          ...SECURITY_HEADERS
        }
      });
    }

    // Validate origin (exact match only)
    if (!ALLOWED_ORIGINS.has(origin)) {
      return errorResponse('Forbidden', 403, null);
    }

    // Check request size
    const contentLength = parseInt(request.headers.get('Content-Length') || '0');
    if (contentLength > MAX_BODY_SIZE) {
      return errorResponse('Request too large', 413, origin);
    }

    // Check rate limit
    const clientIP = getClientIP(request);
    const rateCheck = await checkRateLimit(clientIP, env);

    if (!rateCheck.allowed) {
      return errorResponse(rateCheck.reason, 429, origin, rateCheck.retryAfter);
    }

    // Route to handlers
    if (url.pathname === '/api/chat') {
      return handleChat(request, env, origin, rateCheck);
    }

    if (url.pathname === '/api/generate') {
      return handleGenerate(request, env, origin, rateCheck);
    }

    return errorResponse('Not found', 404, origin);
  }
};

/**
 * Handle /api/chat - Multi-turn conversation
 */
async function handleChat(request, env, origin, rateInfo) {
  if (request.method !== 'POST') {
    return errorResponse('Method not allowed', 405, origin);
  }

  try {
    const body = await request.json();

    // Validate required fields
    if (!body.messages || !Array.isArray(body.messages)) {
      return errorResponse('Invalid request', 400, origin);
    }

    // Forward to Ollama Pro with hardcoded model
    const response = await fetch(`${OLLAMA_API_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${env.OLLAMA_API_KEY}`
      },
      body: JSON.stringify({
        model: MODEL,  // Hardcoded - ignore user input
        messages: body.messages,
        stream: false
      })
    });

    if (!response.ok) {
      console.error('Ollama API error:', response.status);
      return errorResponse('Service temporarily unavailable', 502, origin);
    }

    const data = await response.json();

    return secureResponse(data, 200, origin, {
      'X-RateLimit-Remaining': String(rateInfo.remaining),
      'X-RateLimit-Daily-Remaining': String(rateInfo.dailyRemaining)
    });

  } catch (error) {
    console.error('Chat error:', error.message);
    return errorResponse('Service error', 500, origin);
  }
}

/**
 * Handle /api/generate - Single-turn generation
 */
async function handleGenerate(request, env, origin, rateInfo) {
  if (request.method !== 'POST') {
    return errorResponse('Method not allowed', 405, origin);
  }

  try {
    const body = await request.json();

    if (!body.prompt) {
      return errorResponse('Invalid request', 400, origin);
    }

    const response = await fetch(`${OLLAMA_API_URL}/api/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${env.OLLAMA_API_KEY}`
      },
      body: JSON.stringify({
        model: MODEL,  // Hardcoded - ignore user input
        prompt: body.prompt,
        system: body.system,
        stream: false
      })
    });

    if (!response.ok) {
      return errorResponse('Service temporarily unavailable', 502, origin);
    }

    const data = await response.json();

    return secureResponse(data, 200, origin, {
      'X-RateLimit-Remaining': String(rateInfo.remaining),
      'X-RateLimit-Daily-Remaining': String(rateInfo.dailyRemaining)
    });

  } catch (error) {
    console.error('Generate error:', error.message);
    return errorResponse('Service error', 500, origin);
  }
}
