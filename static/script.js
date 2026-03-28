/* =========================================================
   Stream Extractor — Client-side logic
   Premium edition with scroll animations, counters, particles
   ========================================================= */

// ─── Particle constellation background ───

(function initParticles() {
  const canvas = document.getElementById("particle-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let width, height, particles;
  const PARTICLE_COUNT = 60;
  const CONNECTION_DIST = 150;
  let animId;

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  }

  function createParticles() {
    particles = [];
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        size: Math.random() * 2 + 0.5,
      });
    }
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);

    // Draw connections
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < CONNECTION_DIST) {
          const alpha = (1 - dist / CONNECTION_DIST) * 0.15;
          ctx.beginPath();
          ctx.strokeStyle = `rgba(124, 58, 237, ${alpha})`;
          ctx.lineWidth = 0.5;
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }

    // Draw particles
    for (const p of particles) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(124, 58, 237, 0.4)";
      ctx.fill();

      // Move
      p.x += p.vx;
      p.y += p.vy;

      // Bounce
      if (p.x < 0 || p.x > width) p.vx *= -1;
      if (p.y < 0 || p.y > height) p.vy *= -1;
    }

    animId = requestAnimationFrame(draw);
  }

  resize();
  createParticles();
  draw();

  window.addEventListener("resize", () => {
    resize();
    createParticles();
  });
})();

// ─── Scroll-reveal animations (Intersection Observer) ───

(function initScrollReveal() {
  const reveals = document.querySelectorAll(".reveal");
  if (!reveals.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15, rootMargin: "0px 0px -40px 0px" }
  );

  reveals.forEach((el) => observer.observe(el));
})();

// ─── Animated number counters ───

(function initCounters() {
  const counters = document.querySelectorAll(".stat-number[data-target]");
  if (!counters.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const el = entry.target;
          const target = parseInt(el.dataset.target, 10);
          animateCounter(el, target);
          observer.unobserve(el);
        }
      });
    },
    { threshold: 0.5 }
  );

  counters.forEach((el) => observer.observe(el));

  function animateCounter(el, target) {
    const duration = 2000;
    const start = performance.now();

    function update(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(target * eased);

      if (progress < 1) {
        requestAnimationFrame(update);
      } else {
        el.textContent = target;
      }
    }

    requestAnimationFrame(update);
  }
})();

// ─── Smooth scroll for CTA ───

document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
  anchor.addEventListener("click", (e) => {
    const target = document.querySelector(anchor.getAttribute("href"));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
});

// ─── Tab navigation ───

const tabBtns = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");

tabBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabBtns.forEach((b) => {
      b.classList.remove("active");
      b.setAttribute("aria-selected", "false");
    });
    tabContents.forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    btn.setAttribute("aria-selected", "true");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

// ─── Cmd+A: select only input text when either input is focused ───

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "a") {
    const el = document.activeElement;
    if (el && (el.id === "url-input" || el.id === "photo-url-input")) {
      e.preventDefault();
      el.select();
    }
  }
});

/* =========================================================
   STREAM EXTRACTOR
   ========================================================= */

const form = document.getElementById("extract-form");
const input = document.getElementById("url-input");
const btn = document.getElementById("submit-btn");
const btnText = btn.querySelector(".btn-text");
const btnLoader = btn.querySelector(".btn-loader");
const errorEl = document.getElementById("error");
const resultsEl = document.getElementById("results");
const loadingStatus = document.getElementById("loading-status");

const STATUS_MESSAGES = [
  "Fetching page content\u2026",
  "Scanning for embedded video players\u2026",
  "Analyzing iframe sources\u2026",
  "Checking player configurations\u2026",
  "Unpacking obfuscated scripts\u2026",
  "Decoding hidden URLs\u2026",
  "Launching stealth browser\u2026",
  "Intercepting network streams\u2026",
  "Resolving stream URLs\u2026",
  "Almost there\u2026",
];

let statusInterval = null;

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = input.value.trim();
  if (!url) return;

  setLoading(true);
  hideError();
  hideResults();
  startStatusCycle();

  try {
    const res = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) {
      showError(data.error || "Something went wrong. Please try again.");
      return;
    }
    renderResults(data.results, data.used_ytdlp);
  } catch (err) {
    showError("Network error \u2014 make sure the server is running.");
  } finally {
    setLoading(false);
    stopStatusCycle();
  }
});

function setLoading(loading) {
  btn.disabled = loading;
  btnText.classList.toggle("hidden", loading);
  btnLoader.classList.toggle("hidden", !loading);
}

function startStatusCycle() {
  let idx = 0;
  loadingStatus.textContent = STATUS_MESSAGES[0];
  loadingStatus.classList.remove("hidden");
  statusInterval = setInterval(() => {
    idx = (idx + 1) % STATUS_MESSAGES.length;
    loadingStatus.textContent = STATUS_MESSAGES[idx];
  }, 3000);
}

function stopStatusCycle() {
  clearInterval(statusInterval);
  statusInterval = null;
  loadingStatus.classList.add("hidden");
}

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove("hidden");
}

function hideError() {
  errorEl.classList.add("hidden");
}

function hideResults() {
  resultsEl.classList.add("hidden");
  resultsEl.innerHTML = "";
}

// ─── Render stream results ───

function renderResults(groups, usedYtdlp) {
  resultsEl.innerHTML = "";

  if (!groups || groups.length === 0) {
    resultsEl.innerHTML = `
      <div class="no-results">
        <div class="no-results-icon">&#128269;</div>
        <div class="no-results-title">No Streams Found</div>
        <div class="no-results-text">
          We couldn't detect any video streams on this page.
          The content may be DRM-protected or loaded dynamically.
        </div>
      </div>`;
    resultsEl.classList.remove("hidden");
    return;
  }

  const totalStreams = groups.reduce((sum, g) => sum + g.streams.length, 0);

  const header = document.createElement("div");
  header.innerHTML = `
    <div class="results-header">
      <span class="results-title">Stream Sources Detected</span>
      <span class="results-count">${totalStreams} stream${totalStreams !== 1 ? "s" : ""} found</span>
    </div>
    <p class="results-subtitle">Ready to play \u2014 copy any link and open it in IINA, VLC, or your preferred media player.</p>`;
  resultsEl.appendChild(header);

  if (usedYtdlp) {
    const note = document.createElement("div");
    note.className = "ytdlp-note";
    note.textContent = "Streams extracted via yt-dlp (encrypted source resolved)";
    resultsEl.appendChild(note);
  }

  groups.forEach((group, gi) => {
    const card = document.createElement("div");
    card.className = "source-group";
    card.style.animationDelay = `${gi * 0.1}s`;

    const ct = group.streams.length;
    card.innerHTML = `
      <div class="source-header">
        <span class="source-name">
          <svg class="source-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
          ${esc(group.source)}
        </span>
        <span class="source-badge">${ct} stream${ct !== 1 ? "s" : ""}</span>
      </div>
      <ul class="stream-list">
        ${group.streams.map((s) => `
          <li class="stream-item">
            <span class="quality-tag ${qualityClass(s.quality)}">${esc(s.quality)}</span>
            <span class="stream-url">${esc(s.url)}</span>
            <button class="copy-btn" data-url="${attr(s.url)}">
              <svg class="copy-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
              <span>Copy</span>
            </button>
          </li>
        `).join("")}
      </ul>`;
    resultsEl.appendChild(card);
  });

  resultsEl.classList.remove("hidden");
  resultsEl.querySelectorAll(".copy-btn").forEach((b) => {
    b.addEventListener("click", () => copyUrl(b));
  });
  resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

function qualityClass(quality) {
  const q = quality.toLowerCase();
  if (q.includes("hls") || q.includes("m3u8")) return "q-hls";
  if (q.includes("direct")) return "q-direct";
  if (q.includes("yt-dlp") || q.includes("audio")) return "q-ytdlp";
  return "q-default";
}

/* =========================================================
   PHOTO EXTRACTOR
   ========================================================= */

const photoForm = document.getElementById("photo-extract-form");
const photoInput = document.getElementById("photo-url-input");
const photoBtn = document.getElementById("photo-submit-btn");
const photoBtnText = photoBtn.querySelector(".btn-text");
const photoBtnLoader = photoBtn.querySelector(".btn-loader");
const photoErrorEl = document.getElementById("photo-error");
const photoResultsEl = document.getElementById("photo-results");
const photoLoadingStatus = document.getElementById("photo-loading-status");

const PHOTO_STATUS_MESSAGES = [
  "Fetching page content\u2026",
  "Scanning for images\u2026",
  "Checking CSS backgrounds and meta tags\u2026",
  "Launching stealth browser\u2026",
  "Bypassing anti-bot protection\u2026",
  "Scrolling page to load lazy images\u2026",
  "Intercepting network image requests\u2026",
  "Fetching image metadata\u2026",
  "Almost done\u2026",
];

let photoStatusInterval = null;

photoForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = photoInput.value.trim();
  if (!url) return;

  photoBtn.disabled = true;
  photoBtnText.classList.add("hidden");
  photoBtnLoader.classList.remove("hidden");
  photoErrorEl.classList.add("hidden");
  photoResultsEl.classList.add("hidden");
  photoResultsEl.innerHTML = "";
  startPhotoStatusCycle();

  try {
    const res = await fetch("/api/extract-photos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) {
      photoErrorEl.textContent = data.error || "Something went wrong.";
      photoErrorEl.classList.remove("hidden");
      return;
    }
    renderPhotoResults(data.results);
  } catch (err) {
    photoErrorEl.textContent = "Network error \u2014 make sure the server is running.";
    photoErrorEl.classList.remove("hidden");
  } finally {
    photoBtn.disabled = false;
    photoBtnText.classList.remove("hidden");
    photoBtnLoader.classList.add("hidden");
    stopPhotoStatusCycle();
  }
});

function startPhotoStatusCycle() {
  let idx = 0;
  photoLoadingStatus.textContent = PHOTO_STATUS_MESSAGES[0];
  photoLoadingStatus.classList.remove("hidden");
  photoStatusInterval = setInterval(() => {
    idx = (idx + 1) % PHOTO_STATUS_MESSAGES.length;
    photoLoadingStatus.textContent = PHOTO_STATUS_MESSAGES[idx];
  }, 2500);
}

function stopPhotoStatusCycle() {
  clearInterval(photoStatusInterval);
  photoStatusInterval = null;
  photoLoadingStatus.classList.add("hidden");
}

// ─── Render photo results ───

function renderPhotoResults(photos) {
  photoResultsEl.innerHTML = "";

  if (!photos || photos.length === 0) {
    photoResultsEl.innerHTML = `
      <div class="no-results">
        <div class="no-results-icon">&#128247;</div>
        <div class="no-results-title">No Images Found</div>
        <div class="no-results-text">
          We couldn't find any images on this page.
          The site may block external access or load images dynamically.
        </div>
      </div>`;
    photoResultsEl.classList.remove("hidden");
    return;
  }

  // Header with count + Download All
  const header = document.createElement("div");
  header.innerHTML = `
    <div class="photo-results-actions">
      <div class="results-left">
        <span class="results-title">Images Found</span>
        <span class="results-count">${photos.length} image${photos.length !== 1 ? "s" : ""}</span>
      </div>
      <button class="download-all-btn" id="download-all-btn">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download All
      </button>
    </div>
    <p class="photo-results-subtitle">Click any image to download, or use the button above to download all at once.</p>`;
  photoResultsEl.appendChild(header);

  // Grid
  const grid = document.createElement("div");
  grid.className = "photo-grid";

  photos.forEach((photo, i) => {
    const card = document.createElement("div");
    card.className = "photo-card";
    card.style.animationDelay = `${i * 0.04}s`;

    card.innerHTML = `
      <div class="photo-thumb-wrap">
        <img class="photo-card-thumb"
             src="${attr(photo.url)}"
             alt="${attr(photo.filename)}"
             loading="lazy"
             crossorigin="anonymous"
             onload="window._updateDim(this)"
             onerror="this.parentElement.innerHTML='<div class=\\'photo-thumb-placeholder\\'>Failed to load</div>'">
        <div class="photo-thumb-overlay">
          <a href="/api/download-photo?url=${encodeURIComponent(photo.url)}&filename=${encodeURIComponent(photo.filename)}"
             download="${attr(photo.filename)}" class="photo-overlay-btn">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Download
          </a>
        </div>
      </div>
      <div class="photo-card-info">
        <div class="photo-card-filename" title="${attr(photo.filename)}">${esc(photo.filename)}</div>
        <div class="photo-card-meta">
          <span class="photo-meta-tag type-tag">${esc(photo.type)}</span>
          <span class="photo-meta-tag size-tag">${esc(photo.size_display)}</span>
          <span class="photo-meta-tag dim-tag dimensions-tag">\u2014</span>
        </div>
      </div>`;
    grid.appendChild(card);
  });

  photoResultsEl.appendChild(grid);
  photoResultsEl.classList.remove("hidden");

  // Download All handler — routes through server proxy for direct save
  document.getElementById("download-all-btn").addEventListener("click", () => {
    photos.forEach((photo, i) => {
      setTimeout(() => {
        const a = document.createElement("a");
        a.href = `/api/download-photo?url=${encodeURIComponent(photo.url)}&filename=${encodeURIComponent(photo.filename)}`;
        a.download = photo.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }, i * 150);
    });
  });

  photoResultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Client-side dimension detection (called from onload)
window._updateDim = function (img) {
  const card = img.closest(".photo-card");
  if (!card) return;
  const dimTag = card.querySelector(".dimensions-tag");
  if (dimTag && img.naturalWidth && img.naturalHeight) {
    dimTag.textContent = `${img.naturalWidth} \u00d7 ${img.naturalHeight}`;
  }
};

/* =========================================================
   SHARED UTILITIES
   ========================================================= */

async function copyUrl(btn) {
  const url = btn.dataset.url;
  const label = btn.querySelector("span");
  const icon = btn.querySelector("svg");

  try {
    await navigator.clipboard.writeText(url);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = url;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }

  label.textContent = "Copied!";
  icon.innerHTML = '<polyline points="20 6 9 17 4 12"/>';
  btn.classList.add("copied");

  setTimeout(() => {
    label.textContent = "Copy";
    icon.innerHTML =
      '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>' +
      '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>';
    btn.classList.remove("copied");
  }, 2000);
}

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function attr(str) {
  return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}
