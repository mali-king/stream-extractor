#!/usr/bin/env python3
"""Stream Extractor — Web server."""

import ipaddress
import os
import socket
from urllib.parse import urlparse

import urllib.request

from flask import Flask, render_template, request, jsonify, Response
from extractor import extract_streams, _has_ytdlp, UA
from photo_extractor import extract_photos

app = Flask(__name__)


def _validate_url(url):
    """Reject internal/private addresses to prevent SSRF."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed.")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("Missing hostname.")
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Requests to internal addresses are not allowed.")
    except socket.gaierror:
        raise ValueError("Could not resolve hostname.")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tool")
def tool():
    return render_template("tool.html")


@app.route("/api/extract", methods=["POST"])
def api_extract():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        _validate_url(url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        groups = extract_streams(url)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not groups:
        hint = "" if _has_ytdlp() else " (install yt-dlp for wider site support)"
        return jsonify({"error": f"No video streams found on this page.{hint}"}), 404

    used_ytdlp = any(g["source"] == "yt-dlp" for g in groups)
    return jsonify({"url": url, "results": groups, "used_ytdlp": used_ytdlp})


@app.route("/api/extract-photos", methods=["POST"])
def api_extract_photos():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        _validate_url(url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        photos = extract_photos(url)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not photos:
        return jsonify({"error": "No images found on this page."}), 404

    return jsonify({"url": url, "results": photos, "count": len(photos)})


@app.route("/api/download-photo")
def api_download_photo():
    """Proxy-download an image so the browser saves it directly."""
    url = (request.args.get("url") or "").strip()
    filename = request.args.get("filename") or "image"

    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "Invalid URL."}), 400

    try:
        _validate_url(url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "image/*,*/*",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        content_type = resp.headers.get("Content-Type", "application/octet-stream")

        def stream():
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                yield chunk

        return Response(
            stream(),
            content_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=8080)
