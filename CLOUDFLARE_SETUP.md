# Cloudflare Deployment Guide

Deploy your YouTube Learning Library to Cloudflare with secure AI chat powered by Ollama Pro.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        YOUR SETUP                                │
├─────────────────────────────────────────────────────────────────┤
│  library.davidkarpay.com  →  Cloudflare Pages (static site)     │
│           ↓                                                      │
│  /api/chat, /api/generate →  Cloudflare Worker (secure proxy)   │
│           ↓                                                      │
│  Ollama Pro API (your $20/month subscription)                   │
└─────────────────────────────────────────────────────────────────┘
```

**Security:** API key is stored secretly in the Worker. Never exposed to browsers.

---

## Prerequisites

- Cloudflare account (free tier works)
- Ollama Pro subscription with API key
- Node.js installed (for Wrangler CLI)

---

## Part 1: Deploy Static Site to Cloudflare Pages

### Option A: Connect GitHub Repository (Recommended)

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → Pages
2. Click "Create a project" → "Connect to Git"
3. Select your repository: `davidkarpay/my-youtube-library`
4. Configure build settings:
   - **Build command:** `python library.py`
   - **Build output directory:** `site`
   - **Root directory:** `/`
5. Click "Save and Deploy"

### Option B: Direct Upload

```bash
# Install Wrangler CLI
npm install -g wrangler

# Login to Cloudflare
wrangler login

# Deploy the site directory
wrangler pages deploy site --project-name=youtube-library
```

### Set Custom Domain

1. In Pages project settings → Custom domains
2. Add `library.davidkarpay.com`
3. Cloudflare will auto-configure DNS

---

## Part 2: Deploy the Secure API Worker

The Worker acts as a secure proxy - it holds your Ollama Pro API key secretly.

### Step 1: Install Wrangler

```bash
npm install -g wrangler
wrangler login
```

### Step 2: Add Your API Key as a Secret

```bash
cd cloudflare
wrangler secret put OLLAMA_API_KEY
# Paste your Ollama Pro API key when prompted
```

### Step 3: Deploy the Worker

```bash
cd cloudflare
wrangler deploy
```

### Step 4: Configure Routes

After deployment, the Worker runs at `youtube-library-api.<your-subdomain>.workers.dev`.

To route `/api/*` requests from your Pages site to the Worker:

1. Go to Cloudflare Dashboard → Workers & Pages → youtube-library-api
2. Settings → Triggers → Add Route
3. Add: `library.davidkarpay.com/api/*` → Zone: `davidkarpay.com`

---

## Part 3: Verify Setup

### Test the Worker Directly

```bash
# Should return error (no origin header)
curl https://youtube-library-api.<subdomain>.workers.dev/api/chat

# Test with origin header
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Origin: https://library.davidkarpay.com" \
  -d '{"model":"gpt-oss:120b-cloud","messages":[{"role":"user","content":"Hello"}]}' \
  https://youtube-library-api.<subdomain>.workers.dev/api/chat
```

### Test the Full Site

1. Visit `https://library.davidkarpay.com`
2. Try keyword search (works client-side with library.json)
3. Try AI chat (calls Worker → Ollama Pro)

---

## Security Features

| Protection | Implementation |
|------------|----------------|
| API Key Security | Stored as Worker secret, never in client code |
| Origin Validation | Only requests from davidkarpay.com allowed |
| CORS | Proper preflight handling |
| Method Validation | Only POST allowed to /api/* endpoints |

---

## Maintenance

### Update Site Content

```bash
# Add new videos
python youtube_transcript_to_md.py "https://youtube.com/watch?v=..."

# Regenerate site
python library.py

# Push to GitHub (auto-deploys via Pages)
git add .
git commit -m "Add new videos"
git push youtube-library main
```

### Rotate API Key

```bash
cd cloudflare
wrangler secret put OLLAMA_API_KEY
# Paste new key
```

### View Worker Logs

```bash
wrangler tail
```

---

## Costs

| Service | Cost |
|---------|------|
| Cloudflare Pages | Free (unlimited sites, 500 builds/month) |
| Cloudflare Workers | Free (100,000 requests/day) |
| Ollama Pro | $20/month (your existing subscription) |

**Total additional cost: $0**

---

## Troubleshooting

### "Forbidden" error in chat
- Check that your domain is in the ALLOWED_ORIGINS list in worker.js
- Verify the Origin header is being sent

### "AI service temporarily unavailable"
- Check Worker logs: `wrangler tail`
- Verify API key is set: `wrangler secret list`
- Test Ollama Pro API directly

### Chat works locally but not on Cloudflare
- Ensure Worker routes are configured correctly
- Check that /api/* routes go to the Worker, not Pages
