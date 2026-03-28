"""Photo extraction engine.

Scrapes all images from a webpage and returns metadata
(URL, filename, file size, type) for each image.
Dimensions are resolved client-side when thumbnails load.

Uses static HTML parsing first, then falls back to a headless
browser (Playwright) for JS-rendered pages.
"""

import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from extractor import fetch, UA

# Optional: headless browser for JS-heavy sites
try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AD_PATTERNS = [
    "googleads.", "doubleclick.net", "googlesyndication.",
    "facebook.com/tr", "google-analytics.com", "adservice.google",
    "/tracking-pixel", "pixel.gif", "spacer.gif",
    "/beacon/", "/1x1.", "pagead2.",
]

# Extensions/patterns that indicate site chrome, not content images
_CHROME_PATTERNS = [
    "favicon", "apple-touch-icon", "logo", "sprite",
    "icon-", "icons/", "/static/", "error-image",
]

_MAX_IMAGES = 200
_HEAD_TIMEOUT = 8
_HEAD_WORKERS = 12
# Minimum real images before we consider the static scrape sufficient
_MIN_CONTENT_IMAGES = 3


# ---------------------------------------------------------------------------
# Image source discovery (from HTML)
# ---------------------------------------------------------------------------

def _extract_img_tags(html_text, urls):
    """<img> tags: src, data-src, data-lazy, data-original, srcset."""
    for tag in re.finditer(r'<img[^>]+>', html_text, re.IGNORECASE):
        tag_str = tag.group(0)
        for attr in ("src", "data-src", "data-lazy", "data-original"):
            m = re.search(rf'{attr}\s*=\s*["\']([^"\']+)["\']', tag_str, re.IGNORECASE)
            if m:
                urls.add(m.group(1))
        m = re.search(r'srcset\s*=\s*["\']([^"\']+)["\']', tag_str, re.IGNORECASE)
        if m:
            for part in m.group(1).split(","):
                part = part.strip()
                if part:
                    urls.add(part.split()[0])


def _extract_picture_sources(html_text, urls):
    """<picture>/<source> srcset attributes."""
    for m in re.finditer(
        r'<(?:picture|source)[^>]+srcset\s*=\s*["\']([^"\']+)["\']',
        html_text, re.IGNORECASE,
    ):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                urls.add(part.split()[0])


def _extract_css_backgrounds(html_text, urls):
    """CSS background-image url() values."""
    for m in re.finditer(
        r'background(?:-image)?\s*:\s*[^;]*url\(["\']?([^"\')\s]+)["\']?\)',
        html_text, re.IGNORECASE,
    ):
        urls.add(m.group(1))


def _extract_og_meta(html_text, urls):
    """Open Graph og:image meta tags."""
    for m in re.finditer(
        r'<meta[^>]+(?:property|name)\s*=\s*["\']og:image["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
        html_text, re.IGNORECASE,
    ):
        urls.add(m.group(1))
    for m in re.finditer(
        r'<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]+(?:property|name)\s*=\s*["\']og:image["\']',
        html_text, re.IGNORECASE,
    ):
        urls.add(m.group(1))


def _extract_twitter_meta(html_text, urls):
    """Twitter card twitter:image meta tags."""
    for m in re.finditer(
        r'<meta[^>]+(?:property|name)\s*=\s*["\']twitter:image["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
        html_text, re.IGNORECASE,
    ):
        urls.add(m.group(1))
    for m in re.finditer(
        r'<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]+(?:property|name)\s*=\s*["\']twitter:image["\']',
        html_text, re.IGNORECASE,
    ):
        urls.add(m.group(1))


def _extract_favicons(html_text, urls):
    """Favicons and apple-touch-icons."""
    for m in re.finditer(
        r'<link[^>]+rel\s*=\s*["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]+href\s*=\s*["\']([^"\']+)["\']',
        html_text, re.IGNORECASE,
    ):
        urls.add(m.group(1))


def _extract_all_from_html(page_html, urls):
    """Run all HTML-based discovery functions."""
    _extract_img_tags(page_html, urls)
    _extract_picture_sources(page_html, urls)
    _extract_css_backgrounds(page_html, urls)
    _extract_og_meta(page_html, urls)
    _extract_twitter_meta(page_html, urls)
    _extract_favicons(page_html, urls)


# ---------------------------------------------------------------------------
# Headless browser fallback
# ---------------------------------------------------------------------------

def _fetch_with_browser(page_url):
    """Use Playwright headless Chromium to render JS-heavy pages.
    Returns a set of image URLs found in the rendered DOM."""
    urls = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        try:
            page.goto(page_url, wait_until="networkidle", timeout=30000)
            # Scroll down to trigger lazy loading
            for _ in range(3):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(800)

            # Extract from rendered DOM via JS
            img_urls = page.evaluate("""() => {
                const urls = new Set();
                // All img tags
                document.querySelectorAll('img').forEach(img => {
                    if (img.src) urls.add(img.src);
                    if (img.dataset.src) urls.add(img.dataset.src);
                    if (img.dataset.lazy) urls.add(img.dataset.lazy);
                    if (img.currentSrc) urls.add(img.currentSrc);
                    if (img.srcset) {
                        img.srcset.split(',').forEach(p => {
                            const u = p.trim().split(' ')[0];
                            if (u) urls.add(u);
                        });
                    }
                });
                // picture/source srcsets
                document.querySelectorAll('picture source, source[srcset]').forEach(el => {
                    if (el.srcset) {
                        el.srcset.split(',').forEach(p => {
                            const u = p.trim().split(' ')[0];
                            if (u) urls.add(u);
                        });
                    }
                });
                // CSS background images on visible elements
                document.querySelectorAll('[style*="background"]').forEach(el => {
                    const bg = getComputedStyle(el).backgroundImage;
                    const m = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                    if (m) urls.add(m[1]);
                });
                // OG / Twitter meta
                document.querySelectorAll('meta[property="og:image"], meta[name="twitter:image"]').forEach(m => {
                    if (m.content) urls.add(m.content);
                });
                return [...urls];
            }""")
            urls.update(img_urls)
        except Exception:
            pass
        finally:
            ctx.close()
            browser.close()
    return urls


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _resolve_url(raw_url, base_url):
    """Convert relative/protocol-relative URLs to absolute."""
    if not raw_url or raw_url.startswith("data:"):
        return None
    if raw_url.startswith("//"):
        resolved = "https:" + raw_url
    elif not raw_url.startswith("http"):
        resolved = urllib.parse.urljoin(base_url, raw_url)
    else:
        resolved = raw_url
    if not resolved.startswith(("http://", "https://")):
        return None
    return resolved


def _is_ad_image(url):
    url_lower = url.lower()
    return any(p in url_lower for p in _AD_PATTERNS)


def _is_chrome_image(url):
    """Check if URL is likely site chrome (favicon, logo, icons) not content."""
    url_lower = url.lower()
    return any(p in url_lower for p in _CHROME_PATTERNS)


def _format_size(size_bytes):
    if size_bytes is None:
        return "Unknown"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# Metadata via HEAD requests
# ---------------------------------------------------------------------------

def _get_image_info(url):
    """Fetch image metadata via HEAD request."""
    filename = urllib.parse.urlparse(url).path.split("/")[-1] or "image"
    if "?" in filename:
        filename = filename.split("?")[0]

    try:
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": UA,
            "Accept": "image/*,*/*",
        })
        resp = urllib.request.urlopen(req, timeout=_HEAD_TIMEOUT)
        content_type = resp.headers.get("Content-Type", "")
        content_length = resp.headers.get("Content-Length")

        if content_type and not content_type.startswith("image/"):
            return None

        size_bytes = int(content_length) if content_length else None
        file_type = content_type.split("/")[-1].split(";")[0].upper() if content_type else None
        if not file_type:
            ext = filename.rsplit(".", 1)[-1].upper() if "." in filename else "Unknown"
            file_type = ext

        if size_bytes is not None and size_bytes < 200:
            return None

        return {
            "url": url,
            "filename": filename,
            "type": file_type,
            "size_bytes": size_bytes,
            "size_display": _format_size(size_bytes),
            "content_type": content_type,
        }
    except Exception:
        ext = filename.rsplit(".", 1)[-1].upper() if "." in filename else "IMG"
        return {
            "url": url,
            "filename": filename,
            "type": ext,
            "size_bytes": None,
            "size_display": "Unknown",
            "content_type": None,
        }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_photos(page_url):
    """Scrape all images from a webpage. Returns list of image info dicts.

    Strategy:
    1. Fetch HTML statically and parse for images.
    2. If too few content images found, fall back to headless browser.
    3. Fetch metadata for all discovered images via parallel HEAD requests.
    """
    page_html = fetch(page_url)
    raw_urls = set()
    _extract_all_from_html(page_html, raw_urls)

    # Check if we found enough real content images (not just favicons/logos)
    resolved_quick = []
    for raw in raw_urls:
        url = _resolve_url(raw, page_url)
        if url and not _is_ad_image(url):
            resolved_quick.append(url)

    content_count = sum(1 for u in resolved_quick if not _is_chrome_image(u))

    # If static parse found very few content images, try headless browser
    if content_count < _MIN_CONTENT_IMAGES and _HAS_PLAYWRIGHT:
        browser_urls = _fetch_with_browser(page_url)
        raw_urls.update(browser_urls)

    # Resolve and deduplicate
    resolved = []
    seen = set()
    for raw in raw_urls:
        url = _resolve_url(raw, page_url)
        if url and url not in seen and not _is_ad_image(url):
            seen.add(url)
            resolved.append(url)

    resolved = resolved[:_MAX_IMAGES]

    # Fetch metadata in parallel
    results = []
    with ThreadPoolExecutor(max_workers=_HEAD_WORKERS) as pool:
        futures = {pool.submit(_get_image_info, url): url for url in resolved}
        for future in as_completed(futures):
            try:
                info = future.result()
            except Exception:
                continue
            if info:
                results.append(info)

    results.sort(key=lambda x: x.get("size_bytes") or 0, reverse=True)
    return results
