"""Core video stream extraction engine.

Finds embedded videos (iframes, <video> tags, packed JS, JSON metadata)
and resolves them to direct playable URLs.
"""

import re
import json
import html
import subprocess
import shutil
import urllib.error
import urllib.request
import urllib.parse
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
        r'(?:src|source|file|video_url)\s*[=:]\s*["\']?'
        rf'(https?://[^"\'<>\s,]+\.(?:{VIDEO_EXT})[^"\'<>\s,]*)',
        text,
    ):
        url = m.group(1)
        if url not in seen:
            seen.add(url)
            results.append({"url": url, "quality": "direct"})

    # Bare video URLs
    for m in re.finditer(
        rf'(https?://[^\s"\'<>\\,]+\.(?:{VIDEO_EXT})(?:\?[^\s"\'<>\\,]*)?)',
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

    # 4. Packed JS on main page
    unpacked = unpack_packer(page)
    if unpacked:
        packed_streams = find_streams_in_text(unpacked)
        if packed_streams:
            groups.append({"source": "Packed JS", "embed_url": page_url, "streams": packed_streams})

    # 5. Inline URLs
    if not groups:
        inline = find_streams_in_text(page)
        if inline:
            groups.append({"source": "Inline", "embed_url": page_url, "streams": inline})

    # 6. yt-dlp fallback — when we only found trailers or nothing useful
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

    # 7. If we still have nothing useful, show unresolved embeds so user knows what was found
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
