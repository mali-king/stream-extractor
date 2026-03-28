<div align="center">
  <h1>🍿 StreamVault</h1>
  <p><b>The ultimate tool to extract high-quality video streams and photo galleries from anywhere on the web.</b></p>
  
  [![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
  [![Flask](https://img.shields.io/badge/Flask-Web%20App-black?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com/)
  [![Playwright](https://img.shields.io/badge/Playwright-Stealth-2EAD33?style=for-the-badge&logo=playwright)](https://playwright.dev/)
  [![License](https://img.shields.io/badge/License-MIT-purple?style=for-the-badge)](#license)
</div>

---

## 🚀 Overview

**StreamVault** is an advanced, commercial-grade media extraction engine. Simply paste a URL, and StreamVault will scan the page to uncover hidden video stream endpoints (like HLS `.m3u8` and DASH `.mpd`) and bulk-extract high-resolution photo galleries. Designed for power users, researchers, and media enthusiasts.

## ✨ Features

- **🎥 Deep Stream Extraction:** Automatically decodes and extracts direct raw video streams (HLS, DASH, MP4, WebM) hidden inside complicated players (JWPlayer, VideoJS, custom scripts, etc.).
- **📸 Smart Photo Scraper:** Finds the highest resolution images on a page, including lazy-loaded content, `srcset` elements, and hidden metadata pictures.
- **🛡️ Anti-Bot Bypass:** Uses an advanced headless Chromium browser (via `playwright-stealth`) to bypass Cloudflare, DataDome, and modern enterprise-grade WAF firewalls.
- **⚡ Supercharged UI:** A stunning, premium "Liquid Glass" dark-mode frontend featuring interactive smooth scroll, animated stats, and easy 1-click URL copying.

## 🛠️ Tech Stack

- **Backend Logic:** Python 3, Flask, yt-dlp, BeautifulSoup4
- **Browser Automation:** Playwright, Playwright-Stealth
- **Frontend Design:** Vanilla HTML5, CSS3 (Glassmorphism), Vanilla JavaScript

---

## ⚙️ Installation

To set up StreamVault on your local machine, follow these steps:

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/stream-extractor.git
cd stream-extractor
```

### 2. Create a virtual environment (Recommended)
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright Browsers
StreamVault requires Playwright to emulate a real browser and bypass protections.
```bash
playwright install chromium
```

---

## 🚦 Usage

Start the Flask server:
```bash
python app.py
```
Then, open your browser and navigate to:
**👉 `http://127.0.0.1:8080/`**

1. Go to the **StreamVault** homepage.
2. Click **Start Extracting** to access the tool.
3. Paste any webpage URL.
4. Choose either **Extract Streams** or **Extract Photos**.
5. Copy the extracted `.m3u8`/`.mpd`/direct URL directly into VLC, IINA, or your favorite media player, or bulk download the images!

---

## ⚠️ Disclaimer

StreamVault is provided for **educational purposes only**. Please respect copyright and the terms of service of the websites you interact with. Do not use this tool to download or distribute copyrighted material without permission. The developer assumes no responsibility for how this software is used.

---

## 👨‍💻 Author

**Developed by Abdirahman Hussein**

This project was hand-crafted from the ground up, combining advanced backend web-scraping techniques with modern, premium frontend design paradigms to create the best possible extraction experience.

---
<div align="center">
  <i>If you found this tool useful, feel free to ⭐ the repository!</i>
</div>
