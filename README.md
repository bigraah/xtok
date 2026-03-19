# xtok — Send X/Twitter Threads to Kindle

A self-hosted API that converts X (Twitter) threads and articles into Kindle-friendly documents and delivers them via email.

## How it works

1. You send a POST request with an X/Twitter URL
2. The server fetches the full thread using Playwright (with your Twitter auth cookies)
3. It extracts the content, embeds images, and builds a clean HTML document
4. It emails the HTML to your Kindle address via Gmail SMTP
5. Your Kindle converts and delivers it automatically

## Setup

### 1. Get your Twitter auth cookies

1. Log into [x.com](https://x.com) in your browser
2. Open DevTools → Application → Cookies → `https://x.com`
3. Copy the values for `auth_token` and `ct0`

### 2. Get a Gmail App Password

1. Enable 2FA on your Google account
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an app password (name it anything)
4. Copy the 16-character password

### 3. Get your Kindle email address

1. Go to Amazon → Account → Manage Your Content and Devices → Preferences
2. Find "Personal Document Settings" → your `@kindle.com` address
3. Add your Gmail address to the **Approved Personal Document Email List**

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
TWITTER_AUTH_TOKEN=your_auth_token_here
TWITTER_CT0=your_ct0_token_here

GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=your_app_password_here

KINDLE_EMAIL=you@kindle.com

API_KEY=choose_any_secret_key
```

## Running locally

```bash
pip install -r requirements.txt
playwright install chromium
python server.py
```

The server starts at `http://localhost:8000`.

### Send a thread

```bash
curl -X POST http://localhost:8000/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"url": "https://x.com/username/status/123456789"}'
```

Response:

```json
{"status": "sent", "title": "Thread title here"}
```

### Health check

```bash
curl http://localhost:8000/health
```

## Deploying to Render

The repo includes a `render.yaml` for one-click deployment on [Render](https://render.com).

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New → Blueprint
3. Connect your repo
4. Set all environment variables in the Render dashboard (same as `.env`)
5. Deploy

Once deployed, use your Render URL instead of `localhost:8000`.

## iOS Shortcut

A `Send to Kindle.shortcut` is included. It lets you share any X/Twitter URL directly from the iOS share sheet.

**Setup:**

1. Import the shortcut on your iPhone
2. Set your server URL and API key inside the shortcut

Then tap **Share → Send to Kindle** on any tweet or thread.

## API Reference

### `POST /send`

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | X/Twitter URL (tweet or thread) |

**Headers:**

| Header | Description |
|--------|-------------|
| `X-API-Key` | Your configured `API_KEY` |

**Supports:**
- Regular tweets
- Tweet threads
- Twitter Articles (long-form posts)
