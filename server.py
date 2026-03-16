import os
import re
import smtplib
import logging
import base64
import httpx
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from playwright.async_api import async_playwright
from readability import Document
from bs4 import BeautifulSoup

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("xtok")

app = FastAPI(title="xtok")

API_KEY = os.environ["API_KEY"]
TWITTER_AUTH_TOKEN = os.environ["TWITTER_AUTH_TOKEN"]
TWITTER_CT0 = os.environ["TWITTER_CT0"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
KINDLE_EMAIL = os.environ["KINDLE_EMAIL"]


class SendRequest(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# 1. Fetch the full page HTML via Playwright (needs Twitter auth cookies)
# ---------------------------------------------------------------------------
async def fetch_twitter_html(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        # Remove webdriver flag that Twitter detects
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        # Set Twitter auth cookies
        await context.add_cookies(
            [
                {
                    "name": "auth_token",
                    "value": TWITTER_AUTH_TOKEN,
                    "domain": ".x.com",
                    "path": "/",
                },
                {
                    "name": "ct0",
                    "value": TWITTER_CT0,
                    "domain": ".x.com",
                    "path": "/",
                },
            ]
        )

        page = await context.new_page()
        # Normalize twitter.com → x.com
        url = re.sub(r"https?://(www\.)?twitter\.com", "https://x.com", url)
        log.info(f"Fetching {url}")
        await page.goto(url, wait_until="networkidle", timeout=30_000)
        # Wait for tweet content to actually render
        try:
            await page.wait_for_selector('[data-testid="tweetText"]', timeout=10_000)
        except Exception:
            log.warning("tweetText not found, trying article content")
            try:
                await page.wait_for_selector("article", timeout=5_000)
            except Exception:
                log.warning("No article element found either, proceeding with current HTML")
        await page.wait_for_timeout(2000)
        html = await page.content()
        await browser.close()
        return html


# ---------------------------------------------------------------------------
# 2. Download images and embed as base64 data URIs
# ---------------------------------------------------------------------------
def embed_images(soup_el) -> None:
    """Download all images in the element and replace src with base64 data URIs."""
    for img in soup_el.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue
        try:
            log.info(f"Downloading image: {src[:80]}")
            resp = httpx.get(src, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
            b64 = base64.b64encode(resp.content).decode("ascii")
            img["src"] = f"data:{content_type};base64,{b64}"
        except Exception as e:
            log.warning(f"Failed to download image {src[:80]}: {e}")
            img.decompose()  # Remove broken images


# ---------------------------------------------------------------------------
# 3. Extract clean article text with Readability, filtering error containers
# ---------------------------------------------------------------------------
def extract_article(html: str, url: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")

    # Try Twitter Article format first (long-form posts)
    title_el = soup.select_one('[data-testid="twitter-article-title"]')
    body_el = soup.select_one('[data-testid="twitterArticleRichTextView"]')

    if title_el and body_el:
        title = title_el.get_text(separator=" ", strip=True)
        # Clean the article body — keep structure but strip Twitter CSS classes
        for tag in body_el.find_all(True):
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in ("href", "src", "alt")}
        # Fix image URLs — make relative paths absolute and use full-size images
        for img in body_el.find_all("img"):
            src = img.get("src", "")
            if src and not src.startswith("http"):
                img["src"] = f"https://x.com{src}"
            # Request larger image size for Kindle readability
            if "pbs.twimg.com" in img.get("src", ""):
                img["src"] = re.sub(r"name=\w+", "name=large", img["src"])
        # Also fix link hrefs
        for a in body_el.find_all("a"):
            href = a.get("href", "")
            if href and not href.startswith("http"):
                a["href"] = f"https://x.com{href}"
        # Unwrap links around images so accidental taps don't open the browser
        for a in body_el.find_all("a"):
            if a.find("img"):
                a.unwrap()
        # Download and embed images as base64
        embed_images(body_el)
        content_html = str(body_el)
        log.info(f"Extracted Twitter Article: {title[:80]}")
        return title, content_html

    # Fallback: regular tweet thread — collect all tweetText elements
    tweet_texts = soup.select('[data-testid="tweetText"]')
    if tweet_texts:
        # Get author name from the first tweet
        user_el = soup.select_one('[data-testid="User-Name"]')
        author = user_el.get_text(separator=" ", strip=True) if user_el else "Thread"
        title = f"{author} — Thread"
        parts = []
        for t in tweet_texts:
            for tag in t.find_all(True):
                tag.attrs = {k: v for k, v in tag.attrs.items() if k in ("href", "src", "alt")}
            for img in t.find_all("img"):
                src = img.get("src", "")
                if src and not src.startswith("http"):
                    img["src"] = f"https://x.com{src}"
                if "pbs.twimg.com" in img.get("src", ""):
                    img["src"] = re.sub(r"name=\w+", "name=large", img["src"])
            for a in t.find_all("a"):
                href = a.get("href", "")
                if href and not href.startswith("http"):
                    a["href"] = f"https://x.com{href}"
            for a in t.find_all("a"):
                if a.find("img"):
                    a.unwrap()
            embed_images(t)
            parts.append(f"<div>{t.decode_contents()}</div><hr>")
        content_html = "\n".join(parts)
        log.info(f"Extracted thread with {len(tweet_texts)} tweets")
        return title, content_html

    # Last resort: Readability on cleaned HTML
    for el in soup.select('[data-testid="error-detail"]'):
        el.decompose()
    for noscript in soup.find_all("noscript"):
        noscript.decompose()

    cleaned_html = str(soup)
    doc = Document(cleaned_html, url=url)
    title = doc.title()
    content_html = doc.summary(html_partial=True)
    log.info(f"Fell back to Readability extraction")
    return title, content_html


# ---------------------------------------------------------------------------
# 3. Build a Kindle-friendly HTML email
# ---------------------------------------------------------------------------
def build_kindle_html(title: str, content_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: Georgia, serif;
            font-size: 1.1em;
            line-height: 1.6;
            margin: 2em;
            color: #1a1a1a;
        }}
        h1 {{
            font-size: 1.5em;
            margin-bottom: 1em;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
        a {{
            color: #1a1a1a;
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {content_html}
</body>
</html>"""


# ---------------------------------------------------------------------------
# 4. Send to Kindle via Gmail SMTP
# ---------------------------------------------------------------------------
def send_to_kindle(title: str, html_body: str) -> None:
    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = KINDLE_EMAIL
    msg["Subject"] = "convert"  # "convert" tells Kindle to convert the attachment
    # Attach HTML as a file — Kindle needs it as an attachment, not email body
    attachment = MIMEBase("text", "html")
    attachment.set_payload(html_body.encode("utf-8"))
    encoders.encode_base64(attachment)
    safe_title = re.sub(r'[^\w\s-]', '', title or 'article')[:50].strip()
    attachment.add_header("Content-Disposition", "attachment", filename=f"{safe_title}.html")
    msg.attach(attachment)

    log.info(f"Sending '{title}' to {KINDLE_EMAIL}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    log.info("Sent successfully")


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------
@app.post("/send")
async def send_to_kindle_endpoint(
    req: SendRequest,
    x_api_key: str = Header(alias="X-API-Key"),
):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    url = req.url.strip()
    if not re.match(r"https?://(www\.)?(twitter\.com|x\.com)/", url):
        raise HTTPException(status_code=400, detail="Not a Twitter/X URL")

    try:
        html = await fetch_twitter_html(url)
        title, content_html = extract_article(html, url)
        kindle_html = build_kindle_html(title, content_html)
        send_to_kindle(title, kindle_html)
        return {"status": "sent", "title": title}
    except Exception as e:
        log.exception("Failed to process")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
