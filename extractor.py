"""Core video stream extraction engine.

Finds embedded videos (iframes, <video> tags, packed JS, JSON metadata,
player configs, obfuscated URLs, and network-intercepted streams)
and resolves them to direct playable URLs.
"""

import base64
import re
import json
import html
import subprocess
import shutil
import urllib.error
import urllib.request
import urllib.parse
import time
import random
from collections import OrderedDict

# All supported video extensions (used across all regex patterns)
VIDEO_EXT = (
    "mp4|m3u8|webm|mkv|ts|avi|mov|flv|wmv|3gp|ogg|ogv"
    "|mpg|mpeg|f4v|mpd|m4v|asf|rm|rmvb|dash"
)

try:
    import cloudscraper
    _scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "desktop": True},
    )
except ImportError:
    _scraper = None

# Playwright + stealth for browser-based extraction
try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

try:
    from playwright_stealth import stealth_sync
    _HAS_STEALTH = True
except ImportError:
    _HAS_STEALTH = False

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Domains that require Cloudflare bypass via cloudscraper
_CF_DOMAINS = ["apnetv.xyz", "apnetv.co"]


def fetch(url):
    if url.startswith("//"):
        url = "https:" + url

    # Use cloudscraper for known Cloudflare-protected sites
    if _scraper and any(d in url for d in _CF_DOMAINS):
        r = _scraper.get(url, timeout=15)
        return r.text

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Referer": url,
        })
        resp = urllib.request.urlopen(req, timeout=15)
        text = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        # On 403/503, retry with cloudscraper (handles bot protection)
        if _scraper and e.code in (403, 503):
            r = _scraper.get(url, timeout=15)
            return r.text
        raise

    # If we got a Cloudflare challenge page, retry with cloudscraper
    if _scraper and "Just a moment" in text[:500]:
        r = _scraper.get(url, timeout=15)
        return r.text

    return text


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def unpack_packer(page_html):
    """Unpack Dean Edwards' JavaScript packer."""
    m = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\.split\('\|'\)\)\)",
        page_html,
        re.DOTALL,
    )
    if not m:
        return None
    packed = m.group(0)
    parts = re.search(r"}\('(.*)',(\d+),(\d+),'(.*)'\.\s*split", packed, re.DOTALL)
    if not parts:
        return None

    p_str = parts.group(1)
    base = int(parts.group(2))
    count = int(parts.group(3))
    words = parts.group(4).split("|")

    def to_base(num, b):
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        if num < b:
            return chars[num]
        return to_base(num // b, b) + chars[num % b]

    lookup = {}
    for i in range(count):
        key = to_base(i, base)
        lookup[key] = words[i] if words[i] else key

    return re.sub(
        r"\b(\w+)\b", lambda m: lookup.get(m.group(0), m.group(0)), p_str
    )


def find_streams_in_text(text):
    """Find direct video URLs in any text."""
    results = []
    seen = set()

    # JWPlayer style: file:"url",label:"quality"
    for m in re.finditer(
        r'file\s*:\s*"(https?://[^"]+)",\s*label\s*:\s*"([^"]+)"', text
    ):
        url, quality = m.group(1), m.group(2)
        if url not in seen:
            seen.add(url)
            results.append({"url": url, "quality": quality})

    # Keyed video URLs
    for m in re.finditer(
        r'(?:src|source|file|video_url|videoUrl|stream_url|streamUrl|hlsUrl|dashUrl|mediaUrl)\s*[=:]\s*["\']?'
        rf'(https?://[^"\'\s<>,]+\.(?:{VIDEO_EXT})[^"\'\s<>,]*)',
        text, re.IGNORECASE,
    ):
        url = m.group(1)
        if url not in seen:
            seen.add(url)
            results.append({"url": url, "quality": "direct"})

    # Bare video URLs
    for m in re.finditer(
        rf'(https?://[^\s"\'\\\<>,]+\.(?:{VIDEO_EXT})(?:\?[^\s"\'\\<>,]*)?)',
        text,
    ):
        url = m.group(1)
        if url not in seen:
            seen.add(url)
            results.append({"url": url, "quality": "direct"})

    return results


def find_iframes(page_html):
    return re.findall(
        r'<iframe[^>]+src=["\']([^"\']+)["\']', page_html, re.IGNORECASE
    )


def find_video_tags(page_html):
    results = []
    seen = set()
    for m in re.finditer(
        r'<(?:video|source)[^>]+src=["\']([^"\']+)["\']',
        page_html,
        re.IGNORECASE,
    ):
        url = m.group(1)
        if url not in seen and re.search(rf"\.({VIDEO_EXT})", url):
            seen.add(url)
            results.append({"url": url, "quality": "direct"})
    return results


# ---------------------------------------------------------------------------
# NEW: Script player config extraction
# ---------------------------------------------------------------------------

def find_script_player_configs(page_html):
    """Extract video URLs from JavaScript player configurations."""
    results = []
    seen = set()

    # Extract all <script> tag contents
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', page_html, re.DOTALL | re.IGNORECASE)
    all_script_text = "\n".join(scripts)

    # JWPlayer: player.setup({sources: [{file: "..."}]})
    for m in re.finditer(
        r'(?:jwplayer|player|videoPlayer)\s*(?:\([^)]*\))?\s*\.setup\s*\(\s*(\{.*?\})\s*\)',
        all_script_text, re.DOTALL,
    ):
        try:
            # Try to extract file URLs from the config
            config_text = m.group(1)
            for url_m in re.finditer(
                rf'["\']?(file|src|source)\s*["\']?\s*:\s*["\'](https?://[^"\']+)["\']',
                config_text,
            ):
                url = url_m.group(2)
                if url not in seen:
                    seen.add(url)
                    results.append({"url": url, "quality": "JWPlayer"})
        except Exception:
            pass

    # video.js: videojs("player", {sources: [{src: "..."}]})
    for m in re.finditer(
        r'videojs\s*\([^,]+,\s*(\{.*?\})',
        all_script_text, re.DOTALL,
    ):
        config_text = m.group(1)
        for url_m in re.finditer(
            rf'["\'](src|file)["\']?\s*:\s*["\'](https?://[^"\']+)["\']',
            config_text,
        ):
            url = url_m.group(2)
            if url not in seen:
                seen.add(url)
                results.append({"url": url, "quality": "VideoJS"})

    # Clappr.Player: new Clappr.Player({source: "..."})
    for m in re.finditer(
        r'(?:new\s+)?Clappr\.Player\s*\(\s*(\{.*?\})\s*\)',
        all_script_text, re.DOTALL,
    ):
        config_text = m.group(1)
        for url_m in re.finditer(
            rf'["\']?source["\']?\s*:\s*["\'](https?://[^"\']+)["\']',
            config_text,
        ):
            url = url_m.group(1)
            if url not in seen:
                seen.add(url)
                results.append({"url": url, "quality": "Clappr"})

    # FlowPlayer
    for m in re.finditer(
        r'flowplayer\s*\([^,]+,\s*(\{.*?\})',
        all_script_text, re.DOTALL,
    ):
        config_text = m.group(1)
        for url_m in re.finditer(
            rf'["\'](src|url)["\']?\s*:\s*["\'](https?://[^"\']+)["\']',
            config_text,
        ):
            url = url_m.group(2)
            if url not in seen:
                seen.add(url)
                results.append({"url": url, "quality": "FlowPlayer"})

    # Generic: sources = [{src: "...", type: "..."}]
    for m in re.finditer(
        r'sources\s*[=:]\s*\[([^\]]+)\]',
        all_script_text, re.DOTALL,
    ):
        sources_text = m.group(1)
        for url_m in re.finditer(
            rf'(?:src|file|url)\s*["\']?\s*:\s*["\'](https?://[^"\']+)["\']',
            sources_text,
        ):
            url = url_m.group(1)
            if url not in seen:
                seen.add(url)
                results.append({"url": url, "quality": "player config"})

    return results


# ---------------------------------------------------------------------------
# NEW: JSON video URL extraction
# ---------------------------------------------------------------------------

def find_json_video_urls(page_html):
    """Extract video URLs from JSON-LD, inline JSON, and data attributes."""
    results = []
    seen = set()

    # JSON-LD VideoObject
    for m in re.finditer(
        r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(m.group(1))
            _extract_video_from_json(data, results, seen)
        except (json.JSONDecodeError, TypeError):
            pass

    # Inline JSON in script tags: var config = {...}
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', page_html, re.DOTALL | re.IGNORECASE)
    for script in scripts:
        for m in re.finditer(
            r'(?:var|let|const)\s+\w+\s*=\s*(\{[^;]{20,}\})\s*;',
            script, re.DOTALL,
        ):
            try:
                data = json.loads(m.group(1))
                _extract_video_from_json(data, results, seen)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

    # Data attributes on elements
    for attr in ("data-video-url", "data-stream", "data-source",
                  "data-video", "data-video-src", "data-hls", "data-dash"):
        for m in re.finditer(
            rf'{attr}\s*=\s*["\']([^"\']+)["\']',
            page_html, re.IGNORECASE,
        ):
            url = m.group(1)
            if url.startswith("http") and url not in seen:
                seen.add(url)
                results.append({"url": url, "quality": "data attribute"})

    return results


def _extract_video_from_json(data, results, seen):
    """Recursively extract video URLs from a JSON structure."""
    if isinstance(data, dict):
        # Check for VideoObject
        if data.get("@type") == "VideoObject":
            for key in ("contentUrl", "embedUrl", "url"):
                url = data.get(key)
                if url and url not in seen:
                    seen.add(url)
                    results.append({"url": url, "quality": "JSON-LD"})

        # Check for common video keys
        for key in ("video_url", "videoUrl", "stream_url", "streamUrl",
                      "hlsUrl", "dashUrl", "mp4Url", "src", "file",
                      "contentUrl", "embedUrl", "mediaUrl", "playbackUrl"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith("http") and val not in seen:
                if re.search(rf'\.({VIDEO_EXT})', val) or "m3u8" in val or "mpd" in val:
                    seen.add(val)
                    results.append({"url": val, "quality": "JSON config"})

        for val in data.values():
            _extract_video_from_json(val, results, seen)
    elif isinstance(data, list):
        for item in data:
            _extract_video_from_json(item, results, seen)


# ---------------------------------------------------------------------------
# NEW: Obfuscated URL decoding
# ---------------------------------------------------------------------------

def decode_obfuscated_urls(page_html):
    """Decode Base64/hex-encoded video URLs."""
    results = []
    seen = set()

    scripts = re.findall(r'<script[^>]*>(.*?)</script>', page_html, re.DOTALL | re.IGNORECASE)
    all_script_text = "\n".join(scripts)

    # atob("...") calls
    for m in re.finditer(r'atob\s*\(\s*["\']([A-Za-z0-9+/=]+)["\']', all_script_text):
        try:
            decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="ignore")
            for stream in find_streams_in_text(decoded):
                if stream["url"] not in seen:
                    seen.add(stream["url"])
                    stream["quality"] = "decoded (base64)"
                    results.append(stream)
        except Exception:
            pass

    # Plain base64 strings that look like URLs
    for m in re.finditer(r'["\']([A-Za-z0-9+/]{40,}={0,2})["\']', all_script_text):
        try:
            decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="ignore")
            if decoded.startswith("http"):
                for stream in find_streams_in_text(decoded):
                    if stream["url"] not in seen:
                        seen.add(stream["url"])
                        stream["quality"] = "decoded (base64)"
                        results.append(stream)
        except Exception:
            pass

    # Hex-encoded URLs: \x68\x74\x74\x70 = "http"
    for m in re.finditer(r'((?:\\x[0-9a-fA-F]{2}){10,})', all_script_text):
        try:
            decoded = bytes.fromhex(
                m.group(1).replace("\\x", "")
            ).decode("utf-8", errors="ignore")
            for stream in find_streams_in_text(decoded):
                if stream["url"] not in seen:
                    seen.add(stream["url"])
                    stream["quality"] = "decoded (hex)"
                    results.append(stream)
        except Exception:
            pass

    return results


# ---------------------------------------------------------------------------
# NEW: Playwright browser-based stream extraction
# ---------------------------------------------------------------------------

def _extract_streams_with_browser(page_url):
    """Use Playwright with stealth to intercept network requests for video streams.
    Captures .m3u8, .mp4, .ts, .mpd and other video URLs as the player loads them."""
    if not _HAS_PLAYWRIGHT:
        return []

    intercepted = []
    seen = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720},
        )
        page = ctx.new_page()

        if _HAS_STEALTH:
            stealth_sync(page)

        # Intercept ALL network responses for video content
        def _on_response(response):
            try:
                url = response.url
                ct = response.headers.get("content-type", "")

                # Check URL pattern
                is_video_url = bool(re.search(
                    rf'\.({VIDEO_EXT})(\?|$|#)',
                    url, re.IGNORECASE,
                ))

                # Check content type
                is_video_ct = any(t in ct for t in (
                    "video/", "application/x-mpegurl", "application/vnd.apple.mpegurl",
                    "application/dash+xml", "application/octet-stream",
                ))

                # Check for API responses that might contain stream URLs
                is_json_api = "application/json" in ct

                if (is_video_url or is_video_ct) and url not in seen:
                    seen.add(url)
                    quality = "direct"
                    if ".m3u8" in url:
                        quality = "HLS"
                    elif ".mpd" in url:
                        quality = "DASH"
                    intercepted.append({"url": url, "quality": quality})

                elif is_json_api and response.status == 200:
                    try:
                        body = response.text()
                        for stream in find_streams_in_text(body):
                            if stream["url"] not in seen:
                                seen.add(stream["url"])
                                stream["quality"] = "API response"
                                intercepted.append(stream)
                    except Exception:
                        pass

            except Exception:
                pass

        page.on("response", _on_response)

        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

            # Wait for network to settle
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Try to click play buttons
            play_selectors = [
                'button[class*="play"]', '[class*="play-btn"]',
                '[class*="play-button"]', '[aria-label*="play" i]',
                '.vjs-big-play-button', '.jw-icon-display',
                'video', '[class*="player"] button',
                '[id*="play"]', '.btn-play',
            ]
            for selector in play_selectors:
                try:
                    el = page.query_selector(selector)
                    if el and el.is_visible():
                        el.click()
                        time.sleep(2)
                        break
                except Exception:
                    continue

            # Wait for video streams to load after click
            time.sleep(3)

            # Extract <video> src from rendered DOM
            dom_sources = page.evaluate("""() => {
                const urls = [];
                // <video> tags
                document.querySelectorAll('video').forEach(v => {
                    if (v.src && !v.src.startsWith('blob:')) urls.push(v.src);
                    if (v.currentSrc && !v.currentSrc.startsWith('blob:')) urls.push(v.currentSrc);
                });
                // <source> tags
                document.querySelectorAll('source').forEach(s => {
                    if (s.src) urls.push(s.src);
                });
                // iframes (return their src for further processing)
                document.querySelectorAll('iframe').forEach(f => {
                    if (f.src) urls.push('IFRAME:' + f.src);
                });
                return urls;
            }""")

            for src in dom_sources:
                if src.startswith("IFRAME:"):
                    iframe_url = src[7:]
                    if iframe_url not in seen and not any(ad in iframe_url for ad in AD_DOMAINS):
                        seen.add(iframe_url)
                        # Try to extract from iframe
                        try:
                            name, streams = extract_from_embed(iframe_url)
                            intercepted.extend(streams)
                        except Exception:
                            pass
                elif src not in seen:
                    seen.add(src)
                    quality = "direct"
                    if ".m3u8" in src:
                        quality = "HLS"
                    intercepted.append({"url": src, "quality": quality})

        except Exception:
            pass
        finally:
            ctx.close()
            browser.close()

    return intercepted


# ---------------------------------------------------------------------------
# Site-specific extractors
# ---------------------------------------------------------------------------

def extract_okru(embed_url):
    page = fetch(embed_url)
    m = re.search(r'data-options="([^"]*metadata[^"]*)"', page)
    if not m:
        return []
    raw = html.unescape(m.group(1))
    try:
        opts = json.loads(raw)
        metadata = json.loads(opts["flashvars"]["metadata"])
    except (json.JSONDecodeError, KeyError):
        return []

    results = []
    for v in metadata.get("videos", []):
        name, url = v.get("name", "unknown"), v.get("url", "")
        if url:
            results.append({"url": url, "quality": name})
    hls = metadata.get("hlsManifestUrl", "")
    if hls:
        results.append({"url": hls, "quality": "HLS"})
    return results


def extract_dailymotion(embed_url):
    video_id = re.search(r"/(?:video|embed)/([a-zA-Z0-9]+)", embed_url)
    if not video_id:
        return []
    api_url = f"https://www.dailymotion.com/player/metadata/video/{video_id.group(1)}"
    try:
        data = json.loads(fetch(api_url))
        m3u8 = data.get("qualities", {}).get("auto", [{}])[0].get("url", "")
        if m3u8:
            return [{"url": m3u8, "quality": "HLS auto"}]
    except Exception:
        pass
    return []


def extract_youtube(embed_url):
    video_id = re.search(r"(?:embed/|v=|youtu\.be/)([a-zA-Z0-9_-]{11})", embed_url)
    if video_id:
        return [{
            "url": f"https://www.youtube.com/watch?v={video_id.group(1)}",
            "quality": "YouTube (use yt-dlp)",
        }]
    return []


def extract_generic(embed_url):
    page = fetch(embed_url)
    results = []
    unpacked = unpack_packer(page)
    if unpacked:
        results.extend(find_streams_in_text(unpacked))
    results.extend(find_streams_in_text(page))
    results.extend(find_video_tags(page))
    results.extend(find_script_player_configs(page))
    results.extend(find_json_video_urls(page))
    results.extend(decode_obfuscated_urls(page))

    seen = set()
    unique = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    return unique


# ---------------------------------------------------------------------------
# yt-dlp fallback
# ---------------------------------------------------------------------------

def _has_ytdlp():
    return shutil.which("yt-dlp") is not None


def extract_with_ytdlp(page_url):
    """Use yt-dlp to extract direct stream URLs as a fallback."""
    if not _has_ytdlp():
        return []

    try:
        result = subprocess.run(
            ["yt-dlp", "--no-download", "-j", "--no-warnings", "--", page_url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return []

        streams = []
        seen = set()
        for line in result.stdout.strip().splitlines():
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Best single URL
            direct_url = info.get("url", "")
            if direct_url and direct_url not in seen:
                seen.add(direct_url)
                ext = info.get("ext", "?")
                res = info.get("resolution", "")
                quality = f"{res} {ext}".strip() if res else ext
                streams.append({"url": direct_url, "quality": quality})

            # All formats
            for fmt in info.get("formats", []):
                url = fmt.get("url", "")
                if not url or url in seen:
                    continue
                # Skip manifests and storyboards
                proto = fmt.get("protocol", "")
                if proto in ("m3u8", "m3u8_native", "http", "https", ""):
                    vcodec = fmt.get("vcodec", "none")
                    acodec = fmt.get("acodec", "none")
                    if vcodec == "none" and acodec == "none":
                        continue
                    seen.add(url)
                    res = fmt.get("resolution", "")
                    ext = fmt.get("ext", "?")
                    note = fmt.get("format_note", "")
                    label = note or res or ext
                    if vcodec == "none":
                        label = f"audio ({label})"
                    streams.append({"url": url, "quality": label})

        return streams
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

SITE_EXTRACTORS = OrderedDict([
    ("ok.ru", ("OK.ru", extract_okru)),
    ("dailymotion.com", ("Dailymotion", extract_dailymotion)),
    ("youtube.com", ("YouTube", extract_youtube)),
    ("youtu.be", ("YouTube", extract_youtube)),
])

AD_DOMAINS = [
    "googleads", "doubleclick", "googlesyndication",
    "adservice", "facebook.com/plugins", "evacuateenclose",
    "sysmeasuring", "push-sdk", "ueuee.com",
]

# Trailer-only domains — found via iframes but not the real content
TRAILER_DOMAINS = ["youtube.com", "youtu.be"]


def domain_label(url):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        return host.replace("www.", "")
    except Exception:
        return url[:40]


def extract_from_embed(embed_url):
    for domain, (name, extractor) in SITE_EXTRACTORS.items():
        if domain in embed_url:
            return name, extractor(embed_url)
    return domain_label(embed_url), extract_generic(embed_url)


def _discover_ajax_embeds(page, page_url):
    """Discover embed URLs via AJAX APIs (for sites like attackertv, fmovies, etc.)."""
    embeds = []
    parsed = urllib.parse.urlparse(page_url)
    base = f"{parsed.scheme}://{parsed.hostname}"

    # Pattern: /ajax/episode/sources/{id} (attackertv, fmovies, flixhq, etc.)
    # The page has a watch ID in data-watch_id or in the URL slug
    watch_id = None

    # From data attribute
    m = re.search(r'data-watch_id="(\d+)"', page)
    if m:
        watch_id = m.group(1)

    # From URL: /watch-movie/slug-MOVIEID.EPISODEID or /watch-tv/slug.EPISODEID
    if not watch_id:
        m = re.search(r'[./](\d{5,})(?:\?|$)', page_url)
        if m:
            watch_id = m.group(1)

    if watch_id:
        ajax_url = f"{base}/ajax/episode/sources/{watch_id}"
        try:
            req = urllib.request.Request(ajax_url, headers={
                "User-Agent": UA,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": page_url,
            })
            resp = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
            data = json.loads(resp)
            link = data.get("link", "")
            if link:
                embeds.append(link)
        except Exception:
            pass

    return embeds


def _is_trailer_only(group):
    """Check if a result group only contains trailer links."""
    return all(
        any(td in s.get("url", "").lower() for td in TRAILER_DOMAINS)
        for s in group["streams"]
    )


def extract_streams(page_url):
    """Main entry point. Returns list of source groups with their streams.

    Enhanced pipeline:
    1. Iframes from HTML
    2. AJAX-discovered embeds
    3. Direct <video>/<source> tags
    4. Script player configs (JWPlayer, VideoJS, Clappr, etc.)
    5. JSON video URLs (JSON-LD, inline JSON, data attrs)
    6. Packed JS on main page
    7. Obfuscated URL decoding (base64, hex, atob)
    8. Inline URLs
    9. Playwright browser extraction (network interception)
    10. yt-dlp fallback

    Returns:
        list[dict]: Each dict has keys: source, embed_url, streams
    """
    page = fetch(page_url)
    groups = []
    all_embed_urls = []

    # 1. Iframes from HTML
    iframes = find_iframes(page)
    iframes = [u for u in iframes if not any(ad in u for ad in AD_DOMAINS)]

    # 2. AJAX-discovered embeds (for SPA-style sites)
    ajax_embeds = _discover_ajax_embeds(page, page_url)

    # Combine, dedup
    seen_embeds = set()
    for raw_url in iframes + ajax_embeds:
        url = raw_url if raw_url.startswith("http") else "https:" + raw_url
        if url not in seen_embeds:
            seen_embeds.add(url)
            all_embed_urls.append(url)

    unresolved_embeds = []

    for url in all_embed_urls:
        # Skip trailer-only iframes when we also have AJAX results
        if ajax_embeds and any(td in url for td in TRAILER_DOMAINS):
            continue
        try:
            name, streams = extract_from_embed(url)
        except Exception as e:
            name = domain_label(url)
            streams = []
        if streams:
            groups.append({"source": name, "embed_url": url, "streams": streams})
        else:
            unresolved_embeds.append(url)

    # 3. Direct <video>/<source> tags
    direct = find_video_tags(page)
    if direct:
        groups.append({"source": "Direct video", "embed_url": page_url, "streams": direct})

    # 4. Script player configs
    player_configs = find_script_player_configs(page)
    if player_configs:
        groups.append({"source": "Player config", "embed_url": page_url, "streams": player_configs})

    # 5. JSON video URLs
    json_urls = find_json_video_urls(page)
    if json_urls:
        groups.append({"source": "JSON metadata", "embed_url": page_url, "streams": json_urls})

    # 6. Packed JS on main page
    unpacked = unpack_packer(page)
    if unpacked:
        packed_streams = find_streams_in_text(unpacked)
        if packed_streams:
            groups.append({"source": "Packed JS", "embed_url": page_url, "streams": packed_streams})

    # 7. Obfuscated URL decoding
    decoded_streams = decode_obfuscated_urls(page)
    if decoded_streams:
        groups.append({"source": "Decoded", "embed_url": page_url, "streams": decoded_streams})

    # 8. Inline URLs
    if not groups:
        inline = find_streams_in_text(page)
        if inline:
            groups.append({"source": "Inline", "embed_url": page_url, "streams": inline})

    # 9. Playwright browser extraction — when nothing found yet
    real_streams = [g for g in groups if not _is_trailer_only(g)]
    if not real_streams and _HAS_PLAYWRIGHT:
        browser_streams = _extract_streams_with_browser(page_url)
        if browser_streams:
            groups = [{"source": "Browser extraction", "embed_url": page_url, "streams": browser_streams}]

    # 10. yt-dlp fallback — when we only found trailers or nothing useful
    real_streams = [g for g in groups if not _is_trailer_only(g)]
    if not real_streams and _has_ytdlp():
        # Try yt-dlp on embed URLs first (more likely to work), then page URL
        urls_to_try = [u for u in all_embed_urls if not any(td in u for td in TRAILER_DOMAINS)]
        urls_to_try.append(page_url)

        for try_url in urls_to_try:
            ytdlp_streams = extract_with_ytdlp(try_url)
            # Filter out YouTube trailer results
            ytdlp_streams = [
                s for s in ytdlp_streams
                if not any(td in s["url"] for td in ["youtube.com", "googlevideo.com", "ytimg.com"])
            ]
            if ytdlp_streams:
                groups = [{"source": "yt-dlp", "embed_url": try_url, "streams": ytdlp_streams}]
                break

    # 11. If we still have nothing useful, show unresolved embeds
    real_streams = [g for g in groups if not _is_trailer_only(g)]
    if not real_streams and unresolved_embeds:
        groups = [{
            "source": "Embed found (encrypted)",
            "embed_url": unresolved_embeds[0],
            "streams": [{
                "url": unresolved_embeds[0],
                "quality": "embed page (open in browser)",
            }],
        }]

    return groups
