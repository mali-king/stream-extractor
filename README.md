<div align="center">
  <h1>StreamVault</h1>
  <p><b>A tool to extract video streams and photo galleries from web pages.</b></p>
  
  <h3><a href="https://streamvault-coyd.onrender.com" target="_blank">Live Demo Available Here</a></h3>
  
  [![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
  [![Flask](https://img.shields.io/badge/Flask-Web%20App-black?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com/)
  [![Playwright](https://img.shields.io/badge/Playwright-Stealth-2EAD33?style=for-the-badge&logo=playwright)](https://playwright.dev/)
  [![License](https://img.shields.io/badge/License-MIT-purple?style=for-the-badge)](#license)
</div>

---

## Overview

StreamVault is a media extraction tool. By providing a URL, StreamVault will scan the page to uncover hidden video stream endpoints (such as HLS `.m3u8` and DASH `.mpd`) and bulk-extract high-resolution photo galleries. It is built to assist in media research and archiving.

## Features

- **Deep Stream Extraction:** Automatically decodes and extracts direct raw video streams (HLS, DASH, MP4, WebM) from various players (JWPlayer, VideoJS, custom scripts, etc.).
- **Smart Photo Scraper:** Finds high-resolution images on a page, including lazy-loaded content, `srcset` elements, and hidden metadata pictures.
- **Anti-Bot Bypass:** Uses a headless Chromium browser (via `playwright-stealth`) to bypass Cloudflare, DataDome, and modern WAF firewalls.
- **User Interface:** A simple dark-mode frontend featuring an interactive scroll, stats, and 1-click URL copying.

## Tech Stack

- **Backend:** Python 3, Flask, yt-dlp, BeautifulSoup4
- **Browser Automation:** Playwright, Playwright-Stealth
- **Frontend:** HTML5, CSS3, Vanilla JavaScript

---

## Installation

To set up StreamVault on your local machine, follow these steps:

### 1. Clone the repository
```bash
git clone https://github.com/mali-king/stream-extractor.git
cd stream-extractor
```

### 2. Create a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright Browsers
StreamVault requires Playwright to emulate a real browser.
```bash
playwright install chromium
```

---

## Usage

Start the Flask server:
```bash
python app.py
```
Then, open your browser and navigate to:
**`http://127.0.0.1:8080/`**

1. Go to the StreamVault homepage.
2. Click **Start Extracting** to access the tool.
3. Paste any webpage URL.
4. Choose either **Extract Streams** or **Extract Photos**.
5. Copy the extracted `.m3u8`/`.mpd`/direct URL directly into VLC, IINA, or your favorite media player, or bulk download the images.

---

## Disclaimer

StreamVault is provided for educational purposes only. Please respect copyright and the terms of service of the websites you interact with. Do not use this tool to download or distribute copyrighted material without permission.

---

## Author

Developed by Abdirahman Hussein.

---
<div align="center">
  <i>If you found this tool useful, feel free to star the repository.</i>
</div>
