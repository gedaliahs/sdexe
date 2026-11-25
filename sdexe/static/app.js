let currentUrl = "";
let playlistEntries = [];
let outputFolder = "";
let lastEntryError = "";
const downloadHistory = [];
// Goes up every time a new link is fetched. A fetch, download or batch that
// started for an earlier link compares its own number and stops touching the page.
let cardGen = 0;
let fetchingText = null;
let singleActive = false;
let serverDefaults = {};

/* localStorage throws when the browser blocks site data (and when it is
   full). Preferences are a nicety: without them the page still has to work. */
function lsGet(key) {
    try { return localStorage.getItem(key); } catch { return null; }
}
function lsSet(key, value) {
    try { localStorage.setItem(key, value); } catch {}
}

/* ── Toast ── */
function showToast(message, type = "success", actions = null) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const span = document.createElement("span");
    span.textContent = message;
    toast.appendChild(span);
    const actionList = Array.isArray(actions) ? actions :
        (actions && actions.label ? [actions] :
        (typeof actions === "string" ? [{ label: actions, fn: arguments[3] }] : null));
    if (actionList) {
        actionList.forEach(({ label, fn }) => {
            const btn = document.createElement("button");
            btn.className = "toast-action";
            btn.textContent = label;
            btn.onclick = fn;
            toast.appendChild(btn);
        });
    }
    container.appendChild(toast);
    // Trim excess toasts (keep max 4)
    const toasts = container.querySelectorAll('.toast');
    if (toasts.length > 4) toasts[0].remove();
    requestAnimationFrame(() => requestAnimationFrame(() => toast.classList.add("toast-visible")));
    setTimeout(() => {
        toast.classList.remove("toast-visible");
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

/* ── Web Notifications ── */
// Settings writes "off" here when its notifications box is unticked. The
// browser permission can't be taken back from a page, so this is the switch.
function notificationsWanted() {
    return lsGet("sdexe_notifications") !== "off";
}
function sendNotification(title, body) {
    if (notificationsWanted() && "Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body });
    }
}
function requestNotifPermission() {
    if (notificationsWanted() && "Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
    }
}

/* ── Helpers ── */
function timeAgo(ts) {
    // The server stores epoch seconds, the client writes epoch milliseconds.
    if (ts && ts < 1e12) ts *= 1000;
    const diff = (Date.now() - ts) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function scrollIfNeeded(el) {
    const rect = el.getBoundingClientRect();
    const container = el.closest('.entries-list');
    if (!container) return;
    const cRect = container.getBoundingClientRect();
    if (rect.bottom > cRect.bottom || rect.top < cRect.top) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    // Also safe inside attribute values: value="${esc(v)}".
    return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function escAttr(s) {
    return esc(s);
}
function formatDuration(sec) {
    // Many sites report fractions of a second: 125.4 came out as "2:5.400000000000006".
    sec = Math.round(sec);
    if (!sec) return "";
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
    return `${m}:${String(s).padStart(2,"0")}`;
}
function parseTime(str) {
    if (!str || !str.trim()) return null;
    const parts = str.trim().split(":").map(Number);
    if (parts.some(n => isNaN(n) || n < 0)) return null;
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 1) return parts[0];
    return null;
}
function showError(msg) {
    const el = document.getElementById("error");
    document.getElementById("error-text").textContent = msg;
    el.hidden = false;
}
function hideError() { document.getElementById("error").hidden = true; }

function hideAll() {
    document.querySelector("main")?.classList.remove("has-result");
    document.getElementById("video-card").hidden = true;
    document.getElementById("playlist-panel").hidden = true;
    document.getElementById("v-progress").hidden = true;
    document.getElementById("v-save").hidden = true;
    document.getElementById("empty-state").hidden = false;
}

/* ── Download History ── */
// One save at a time. The server reads the file, adds the item and writes it
// back, so three batch downloads finishing together overwrote each other's entry.
let historySaves = Promise.resolve();
function addToHistory(title, format, id, url) {
    const item = { title, format, id, url: url || currentUrl, ts: Date.now() };
    downloadHistory.unshift(item);
    if (downloadHistory.length > 50) downloadHistory.pop();
    renderHistory();
    historySaves = historySaves.then(() => fetch("/api/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item),
    })).catch(() => {});
    return historySaves;
}

function refetchUrl(url) {
    const ta = document.getElementById("url");
    if (!ta) return;
    ta.value = url;
    ta.dispatchEvent(new Event("input"));
    fetchInfo();
}
function renderHistory() {
    const panel = document.getElementById("history-panel");
    const list = document.getElementById("history-list");
    const toggle = document.getElementById("history-toggle");
    if (!panel) return;
    if (!downloadHistory.length) {
        panel.hidden = false;
        list.innerHTML = '<p class="history-empty">No recent downloads</p>';
        return;
    }
    panel.hidden = false;
    if (toggle) toggle.innerHTML = `Recent downloads <span class="history-count">${downloadHistory.length}</span>`;
    list.innerHTML = downloadHistory.map(item => `
        <div class="history-item">
            <div class="history-info">
                <span class="history-title">${esc(item.title)}</span>
                <span class="history-meta"><span class="history-fmt">${esc(String(item.format || "").toUpperCase())}</span>${item.ts ? `<span class="history-time">${timeAgo(item.ts)}</span>` : ""}</span>
            </div>
            <div class="history-actions">
                ${item.url ? `<button type="button" class="history-refetch" title="Fetch this link again" data-url="${escAttr(item.url)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-2.64-6.36"/><path d="M21 3v6h-6"/></svg></button>` : ""}
                ${item.restored ? "" : `<a href="/api/file/${encodeURIComponent(item.id)}" class="history-save"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 3v12M6 9l6 6 6-6"/><path d="M5 21h14"/></svg>Save</a>`}
            </div>
        </div>
    `).join("");
    list.querySelectorAll(".history-refetch").forEach(btn =>
        btn.addEventListener("click", () => refetchUrl(btn.dataset.url)));
}
function toggleHistory() {
    const list = document.getElementById("history-list");
    const chevron = document.getElementById("history-chevron");
    if (!list) return;
    list.hidden = !list.hidden;
    if (chevron) chevron.classList.toggle("open", !list.hidden);
    document.querySelector(".history-header")?.setAttribute("aria-expanded", String(!list.hidden));
}

/* ── Config / Output Folder ── */
async function loadConfig() {
    try {
        const res = await fetch("/api/config");
        const cfg = await res.json();
        outputFolder = cfg.output_folder || "";
        // The defaults saved on the Settings page, for a browser that has no
        // choice of its own stored yet.
        serverDefaults = { format: cfg.default_format, quality: cfg.default_quality };
        updateFolderDisplay();
    } catch {}
    try {
        const res = await fetch("/api/history");
        const items = await res.json();
        if (Array.isArray(items) && items.length) {
            downloadHistory.length = 0;
            // Temp files do not survive a restart, so a Save link on a restored
            // item would just navigate to a "File not found" JSON body.
            items.forEach(i => downloadHistory.push({ ...i, restored: true }));
            renderHistory();
        }
    } catch {}
}
function updateFolderDisplay() {
    const el = document.getElementById("folder-display");
    if (!el) return;
    el.textContent = outputFolder || "None (manual save)";
}
async function promptSetFolder() {
    const recents = getRecentFolders();
    const hint = recents.length ? `\nRecent: ${recents.slice(0,3).join(", ")}` : "";
    const input = prompt(`Set download folder path (leave empty to disable):${hint}`, outputFolder);
    if (input === null) return;
    const wanted = input.trim();
    try {
        const res = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ output_folder: wanted }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.error) {
            showToast(data.error || "Could not use that folder.", "error");
            return;  // keep the previous folder
        }
    } catch {
        showToast("Could not reach sdexe to save the folder.", "error");
        return;
    }
    outputFolder = wanted;
    updateFolderDisplay();
    if (outputFolder) addRecentFolder(outputFolder);
}

/* ── Clipboard Auto-detect ── */
async function tryClipboard() {
    if (!navigator.clipboard) return;
    try {
        const text = await navigator.clipboard.readText();
        if (text && (text.startsWith("http://") || text.startsWith("https://"))) {
            const ta = document.getElementById("url");
            if (ta && !ta.value.trim()) {
                ta.value = text;
                ta.dispatchEvent(new Event("input"));
            }
        }
    } catch {}
}

/* ── Textarea Auto-resize ── */
function initTextarea() {
    const ta = document.getElementById("url");
    ta.addEventListener("input", () => {
        ta.style.height = "auto";
        const lines = ta.value.split("\n").length;
        const rows = Math.min(Math.max(lines, 1), 8);
        ta.rows = rows;
        ta.style.height = ta.scrollHeight + "px";
    });
}

/* ── Parse URLs from textarea ── */
function parseUrls(text) {
    const urls = text.split("\n")
        .map(l => l.trim())
        .filter(l => l && (l.startsWith("http://") || l.startsWith("https://")));
    // The same link pasted twice is still one download.
    return [...new Set(urls)];
}

/* ── Quality Dropdown ── */
function updateQuality(prefix) {
    const fmt = document.getElementById(prefix + "-format").value;
    const q = document.getElementById(prefix + "-quality");
    if (fmt === "mp4") {
        q.innerHTML = `<option value="best">Best</option><option value="1080p">1080p</option><option value="720p">720p</option><option value="480p">480p</option>`;
        q.disabled = false;
    } else if (fmt === "mp3") {
        q.innerHTML = `<option value="320">Best (320kbps)</option><option value="192">Medium (192kbps)</option><option value="128">Small (128kbps)</option>`;
        q.disabled = false;
    } else {
        q.innerHTML = `<option value="best">Lossless</option>`;
        q.disabled = true;
    }
    if (prefix === "v" && document.getElementById("v-format-picker")?.hidden !== false) {
        const subWrap = document.getElementById("v-subtitle-wrap");
        if (subWrap) subWrap.style.display = fmt === "mp4" ? "block" : "none";
    }
    lsSet("sdexe_format", fmt);
    // Rebuild quality pills
    const pillContainer = document.getElementById(prefix + '-quality-pills');
    if (pillContainer) {
        const options = [...document.getElementById(prefix + '-quality').options];
        pillContainer.innerHTML = options.map((opt, i) =>
            `<button class="pill${i === 0 ? ' active' : ''}" data-value="${opt.value}">${opt.textContent}</button>`
        ).join('');
        pillContainer.querySelectorAll('.pill').forEach(pill => {
            pill.addEventListener('click', () => {
                pillContainer.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                const qEl = document.getElementById(prefix + '-quality');
                qEl.value = pill.dataset.value;
                qEl.dispatchEvent(new Event('change'));
            });
        });
    }
}

/* ── Format Pills ── */
function initPills() {
    document.querySelectorAll('.pill-group').forEach(group => {
        const targetId = group.dataset.target;
        const select = document.getElementById(targetId);
        group.querySelectorAll('.pill[data-value]').forEach(pill => {
            pill.addEventListener('click', () => {
                group.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                if (select) {
                    select.value = pill.dataset.value;
                    select.dispatchEvent(new Event('change'));
                }
            });
        });
    });
}

function syncPillsToSelect(prefix) {
    const fmtSelect = document.getElementById(prefix + '-format');
    if (fmtSelect) {
        const group = document.querySelector(`.pill-group[data-target="${prefix}-format"]`);
        if (group) {
            group.querySelectorAll('.pill').forEach(p => {
                p.classList.toggle('active', p.dataset.value === fmtSelect.value);
            });
        }
    }
    const qSelect = document.getElementById(prefix + '-quality');
    const qPills = document.getElementById(prefix + '-quality-pills');
    if (qSelect && qPills) {
        qPills.querySelectorAll('.pill').forEach(p => {
            p.classList.toggle('active', p.dataset.value === qSelect.value);
        });
    }
}

/* ── Skeleton Loader ── */
function showSkeleton() {
    const el = document.getElementById("skeleton-card");
    if (el) el.hidden = false;
}
function hideSkeleton() {
    const el = document.getElementById("skeleton-card");
    if (el) el.hidden = true;
}

/* ── Fetch Info ── */
async function fetchInfo() {
    const text = document.getElementById("url").value.trim();
    if (!text) return;
    // Pasting starts a fetch, and so does the Enter that often follows it.
    if (text === fetchingText) return;
    fetchingText = text;
    const gen = ++cardGen;

    hideError();
    hideAll();
    // A download started from the card that just went away keeps running; it
    // reports through a toast and Recent downloads instead (see trackSingleProgress).
    singleActive = false;
    resetBtn(document.getElementById("v-dl-btn"), "Download");
    document.getElementById("empty-state").hidden = true;
    showSkeleton();
    document.querySelector(".search-bar").classList.add("is-loading");

    const urls = parseUrls(text);

    const btn = document.getElementById("fetch-btn");
    btn.disabled = true;
    btn.querySelector(".btn-text").textContent = "Loading";
    document.title = "Fetching\u2026 sdexe";

    try {
        if (urls.length > 1) {
            await fetchMultipleUrls(urls, gen);
        } else {
            const url = urls[0] || text;
            const res = await fetch("/api/info", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({url}),
            });
            const data = await res.json();
            if (gen !== cardGen) return;  // a newer fetch owns the page now
            if (!res.ok) { showError(data.error || "Failed to fetch info"); return; }

            currentUrl = url;

            if (data.type === "playlist") {
                renderPlaylist(data);
            } else {
                renderVideo(data);
            }
        }
    } catch (e) {
        if (gen === cardGen) showError("Network error. Is the server running?");
    } finally {
        if (gen === cardGen) {
            fetchingText = null;
            hideSkeleton();
            btn.disabled = false;
            btn.querySelector(".btn-text").textContent = "Fetch";
            document.title = "Media Downloader, sdexe";
            document.querySelector(".search-bar").classList.remove("is-loading");
        }
    }
}

/* ── Fetch Multiple URLs ── */
async function fetchMultipleUrls(urls, gen) {
    const btn = document.getElementById("fetch-btn");
    // One slot per link so the list keeps the order they were pasted in.
    const results = new Array(urls.length);
    let errors = 0;
    let finished = 0;
    let next = 0;
    btn.querySelector(".btn-text").textContent = `0 / ${urls.length}`;

    // Three lookups at a time (they used to run one after another).
    async function worker() {
        while (next < urls.length && gen === cardGen) {
            const i = next++;
            try {
                const res = await fetch("/api/info", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({url: urls[i]}),
                });
                const data = await res.json();
                if (!res.ok) {
                    errors++;
                } else if (data.type === "playlist") {
                    results[i] = data.entries;
                } else {
                    results[i] = [{
                        title: data.title || "Unknown",
                        url: data.url || urls[i],
                        duration: data.duration,
                        id: "",
                        thumbnail: data.thumbnail || "",
                    }];
                }
            } catch {
                errors++;
            }
            finished++;
            if (gen === cardGen) btn.querySelector(".btn-text").textContent = `${finished} / ${urls.length}`;
        }
    }
    await Promise.all(Array.from({length: Math.min(3, urls.length)}, worker));
    if (gen !== cardGen) return;

    const entries = results.flat().filter(Boolean);
    if (entries.length === 0) {
        showError(`Could not fetch info for any of the ${urls.length} URLs`);
        return;
    }

    renderPlaylist({
        title: `${entries.length} items from ${urls.length} links`,
        uploader: errors > 0 ? `${errors} link(s) failed` : null,
        count: entries.length,
        entries,
    });
}

/* ── Restore saved format/quality ── */
function restoreFormatPrefs(prefix) {
    const savedFmt = lsGet("sdexe_format") || serverDefaults.format;
    if (savedFmt) {
        const fmtEl = document.getElementById(prefix + "-format");
        if (fmtEl && fmtEl.querySelector(`option[value="${savedFmt}"]`)) fmtEl.value = savedFmt;
    }
    updateQuality(prefix);
    const savedQ = lsGet("sdexe_quality") || serverDefaults.quality;
    if (savedQ) {
        const qEl = document.getElementById(prefix + "-quality");
        if (qEl && qEl.querySelector(`option[value="${savedQ}"]`)) qEl.value = savedQ;
    }
    syncPillsToSelect(prefix);
}

/* ── Recently used folders ── */
function getRecentFolders() {
    try {
        const list = JSON.parse(lsGet("sdexe_recent_folders") || "[]");
        return Array.isArray(list) ? list : [];
    } catch { return []; }
}
function addRecentFolder(path) {
    if (!path) return;
    const recents = getRecentFolders().filter(f => f !== path);
    recents.unshift(path);
    lsSet("sdexe_recent_folders", JSON.stringify(recents.slice(0, 5)));
}

/* ── Render Single Video ── */
document.addEventListener("DOMContentLoaded", () => {
    const t = document.getElementById("v-title");
    if (t) t.addEventListener("input", () => {
        document.getElementById("v-title-display").textContent = t.value.trim() || "Untitled";
    });
});

/* ── Format Picker (per-stream table) ── */
let currentFormats = null;
let currentDuration = 0;
let activeDlBtn = null;
let activeFmtLabel = "";

function formatBytes(n) {
    if (!n) return "";
    if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB";
    if (n >= 1048576) return (n / 1048576).toFixed(2) + " MB";
    return (n / 1024).toFixed(0) + " KB";
}

function renderFormatPicker(data) {
    currentFormats = data.formats || null;
    currentDuration = data.duration || 0;
    const picker = document.getElementById("v-format-picker");
    const pills = document.getElementById("v-pills-wrap");
    const mainBtn = document.getElementById("v-dl-btn");
    const hasRows = currentFormats && (currentFormats.video.length || currentFormats.audio.length);
    if (!hasRows) {
        picker.hidden = true;
        pills.style.display = "";
        mainBtn.style.display = "";
        return;
    }
    picker.hidden = false;
    pills.style.display = "none";
    mainBtn.style.display = "none";
    const savedTab = lsGet("sdexe_format_tab");
    switchFormatTab(savedTab === "audio" || !currentFormats.video.length ? "audio" : "video");
}

function switchFormatTab(kind) {
    document.querySelectorAll(".fp-tab").forEach(t => t.classList.toggle("active", t.dataset.kind === kind));
    lsSet("sdexe_format_tab", kind);
    const subWrap = document.getElementById("v-subtitle-wrap");
    if (subWrap) subWrap.style.display = kind === "video" ? "block" : "none";

    const rows = [];
    if (kind === "video") {
        for (const f of currentFormats.video) {
            const tag = f.fps && f.fps >= 48 ? `<span class="fp-tag">${f.fps}fps</span>` : "";
            rows.push({label: f.label, tag, fmt: f.ext.toUpperCase(),
                       size: (f.approx && f.size ? "~" : "") + formatBytes(f.size),
                       pick: {kind: "video", format_id: f.format_id, ext: f.ext}});
        }
    } else {
        for (const f of currentFormats.audio) {
            rows.push({label: f.label, fmt: f.ext.toUpperCase(), size: formatBytes(f.size),
                       pick: {kind: "audio", format_id: f.format_id, ext: f.ext}});
        }
        // Converted options via the existing ffmpeg pipeline. Sizes are
        // estimates from duration x bitrate.
        const est = kbps => currentDuration ? "~" + formatBytes(currentDuration * kbps * 125) : "";
        rows.push({label: "320 kbps", fmt: "MP3", size: est(320), pick: {fmt: "mp3", quality: "320"}});
        rows.push({label: "192 kbps", fmt: "MP3", size: est(192), pick: {fmt: "mp3", quality: "192"}});
        rows.push({label: "128 kbps", fmt: "MP3", size: est(128), pick: {fmt: "mp3", quality: "128"}});
        rows.push({label: "Lossless", fmt: "FLAC", size: "", pick: {fmt: "flac", quality: "best"}});
        rows.push({label: "Lossless", fmt: "WAV", size: est(1411), pick: {fmt: "wav", quality: "best"}});
    }

    const container = document.getElementById("v-format-rows");
    container.innerHTML = rows.map((r, i) => `
        <div class="fp-row">
            <span class="fp-quality">${esc(r.label)}${r.tag || ""}</span>
            <span class="fp-fmt">${esc(r.fmt)}</span>
            <span class="fp-size">${esc(r.size)}</span>
            <button type="button" class="fp-btn" data-idx="${i}">Download</button>
        </div>`).join("");
    container.querySelectorAll(".fp-btn").forEach(btn => {
        // Switching between Video and Audio redraws the rows. While a download
        // is running they stay off, or a second one could be started on top of it.
        btn.disabled = singleActive;
        btn.addEventListener("click", () => startSingleDownload(rows[btn.dataset.idx].pick, btn));
    });
}

function toggleDetails() {
    const d = document.getElementById("v-details");
    d.hidden = !d.hidden;
    document.getElementById("v-edit-toggle").textContent = d.hidden ? "Edit details" : "Hide details";
    if (!d.hidden) document.getElementById("v-title").focus();
}

function renderVideo(data) {
    document.getElementById("v-thumb").src = data.thumbnail || "";
    document.getElementById("v-duration").textContent = formatDuration(data.duration);
    document.getElementById("v-title").value = data.title || "";
    document.getElementById("v-artist").value = data.uploader || "";
    document.getElementById("v-title-display").textContent = data.title || "Untitled";
    const sub = [data.uploader, data.upload_date].filter(Boolean).join(" · ");
    document.getElementById("v-subline").textContent = sub;
    document.getElementById("v-details").hidden = true;
    document.getElementById("v-edit-toggle").textContent = "Edit details";
    document.getElementById("v-album").value = "";
    const descWrap = document.getElementById("v-description-wrap");
    const descField = document.getElementById("v-description");
    const dateEl = document.getElementById("v-upload-date");
    if (data.description || data.upload_date) {
        descField.value = data.description || "";
        dateEl.textContent = data.upload_date ? `· ${data.upload_date}` : "";
        descWrap.hidden = false;
    } else {
        descField.value = "";
        dateEl.textContent = "";
        descWrap.hidden = true;
    }
    document.getElementById("video-card").hidden = false;
    document.querySelector("main")?.classList.add("has-result");
    restoreFormatPrefs("v");
    renderFormatPicker(data);
    // Clip controls
    const clipWrap = document.getElementById("v-clip-wrap");
    const clipToggle = document.getElementById("v-clip-toggle");
    const clipFields = document.getElementById("v-clip-fields");
    clipWrap.hidden = false;
    clipToggle.checked = false;
    clipFields.style.display = "none";
    document.getElementById("v-clip-start").value = "";
    document.getElementById("v-clip-end").value = "";
    document.getElementById("v-clip-end").placeholder = data.duration ? formatDuration(data.duration) : "end";
}

/* ── Render Playlist ── */
function renderPlaylist(data) {
    playlistEntries = data.entries;

    document.getElementById("p-title").textContent = data.title;
    document.getElementById("p-meta").textContent =
        [data.uploader, `${data.count} videos`,
         data.skipped ? `${data.skipped} private or unavailable left out` : null].filter(Boolean).join(" \u00B7 ");
    document.getElementById("p-artist").value = data.uploader || "";
    document.getElementById("p-album").value = data.title || "";

    const summary = document.getElementById("p-summary");
    summary.hidden = true;
    summary.className = "batch-summary";

    const list = document.getElementById("p-entries");
    list.innerHTML = "";

    data.entries.forEach((entry, i) => {
        const div = document.createElement("div");
        div.className = "entry";
        div.dataset.index = i;
        div.innerHTML = `
            <input type="checkbox" checked onchange="updateCount()" aria-label="${esc(entry.title)}">
            <img class="entry-thumb" src="${esc(entry.thumbnail || "")}" alt="" loading="lazy">
            <div class="entry-info">
                <span class="entry-title">${esc(entry.title)}</span>
                <span class="entry-duration">${formatDuration(entry.duration)}</span>
            </div>
            <div class="entry-status"></div>
        `;
        list.appendChild(div);
    });

    document.getElementById("p-select-all").checked = true;
    updateCount();
    // A batch still running for the previous list no longer owns this button.
    resetBtn(document.getElementById("p-dl-btn"), "Download Selected");
    restoreFormatPrefs("p");
    document.getElementById("playlist-panel").hidden = false;
}

/* ── Playlist Select All / Count ── */
function toggleSelectAll() {
    const checked = document.getElementById("p-select-all").checked;
    document.querySelectorAll("#p-entries .entry input[type=checkbox]").forEach(cb => cb.checked = checked);
    updateCount();
}

function updateCount() {
    const all = document.querySelectorAll("#p-entries .entry input[type=checkbox]");
    const checked = document.querySelectorAll("#p-entries .entry input[type=checkbox]:checked");
    document.getElementById("p-count").textContent = `${checked.length} / ${all.length} selected`;
}

/* ── Single Video Download ── */
async function startSingleDownload(pick = null, rowBtn = null) {
    hideError();
    document.getElementById("v-save").hidden = true;

    // pick comes from the format table: either an exact stream
    // ({kind, format_id, ext}) or a converted format ({fmt, quality}).
    let fmt = document.getElementById("v-format").value;
    let quality = document.getElementById("v-quality").value;
    let formatId = null, pickedExt = null;
    if (pick && pick.format_id) {
        fmt = pick.kind;
        quality = "best";
        formatId = pick.format_id;
        pickedExt = pick.ext;
    } else if (pick && pick.fmt) {
        fmt = pick.fmt;
        quality = pick.quality;
    }
    activeFmtLabel = pickedExt || fmt;
    const subtitles = document.getElementById("v-subtitles")?.checked ?? false;
    const metadata = {
        title: document.getElementById("v-title").value.trim(),
        artist: document.getElementById("v-artist").value.trim(),
        album: document.getElementById("v-album").value.trim(),
        description: document.getElementById("v-description").value.trim(),
    };

    // Clip params
    const clipEnabled = document.getElementById("v-clip-toggle")?.checked;
    const clipStartText = clipEnabled ? document.getElementById("v-clip-start").value.trim() : "";
    const clipEndText = clipEnabled ? document.getElementById("v-clip-end").value.trim() : "";
    const clipStart = parseTime(clipStartText);
    const clipEnd = parseTime(clipEndText);
    // A time that can't be read used to be dropped without a word, and the
    // whole video was downloaded instead of the clip.
    if ((clipStartText && clipStart === null) || (clipEndText && clipEnd === null)) {
        showError("Clip times look like 1:30 or 90 (seconds).");
        return;
    }
    if (clipStart !== null && clipEnd !== null && clipEnd <= clipStart) {
        showError("The clip has to end after it starts.");
        return;
    }
    if (clipStart !== null && currentDuration && clipStart >= currentDuration) {
        showError("The clip starts after the end of the video.");
        return;
    }

    const btn = rowBtn || document.getElementById("v-dl-btn");
    activeDlBtn = btn;
    singleActive = true;
    // What this download is, fixed now: by the time it finishes the card may
    // show a different link.
    const job = { gen: cardGen, url: currentUrl, title: metadata.title || "Download", fmt: activeFmtLabel, btn };
    if (rowBtn) {
        document.querySelectorAll(".fp-btn").forEach(b => { b.disabled = true; });
        document.querySelectorAll(".fp-row").forEach(r => r.classList.remove("is-active"));
        rowBtn.closest(".fp-row")?.classList.add("is-active");
    }
    btn.disabled = true;
    btn.textContent = "Starting...";
    requestNotifPermission();

    // Reset progress state
    const fill = document.getElementById("v-progress-fill");
    fill.style.width = "0%";
    fill.className = "progress-fill";
    const statusEl = document.getElementById("v-progress-status");
    const pctEl = document.getElementById("v-progress-pct");
    const detailEl = document.getElementById("v-progress-text");
    if (statusEl) statusEl.textContent = "Starting...";
    if (pctEl) pctEl.textContent = "";
    if (detailEl) detailEl.textContent = "";

    try {
        const body = {url: currentUrl, format: fmt, quality, metadata, subtitles};
        if (formatId) { body.format_id = formatId; body.ext = pickedExt; }
        if (clipStart !== null) body.clip_start = clipStart;
        if (clipEnd !== null) body.clip_end = clipEnd;
        const res = await fetch("/api/download", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (job.gen !== cardGen) {
            // Another link was fetched while this one was starting.
            if (res.ok) trackSingleProgress(data.id, false, job);
            return;
        }
        if (!res.ok) { showError(data.error || "Download failed"); endSingle(btn); return; }

        document.getElementById("v-progress").hidden = false;
        showCancelBtn(data.id);
        const hasMetadata = !!(metadata.title || metadata.artist || metadata.album);
        trackSingleProgress(data.id, hasMetadata, job);
    } catch (e) {
        if (job.gen !== cardGen) return;
        showError("Network error");
        endSingle(btn);
    }
}

function endSingle(btn) {
    singleActive = false;
    resetBtn(btn, "Download");
}

function showCancelBtn(dlId) {
    let cancelBtn = document.getElementById("v-cancel-btn");
    if (!cancelBtn) {
        cancelBtn = document.createElement("button");
        cancelBtn.id = "v-cancel-btn";
        cancelBtn.className = "btn-cancel";
        cancelBtn.textContent = "Cancel";
        const progressPanel = document.getElementById("v-progress");
        progressPanel.appendChild(cancelBtn);
    }
    cancelBtn.hidden = false;
    cancelBtn.disabled = false;
    cancelBtn.textContent = "Cancel";
    cancelBtn.onclick = async () => {
        cancelBtn.disabled = true;
        cancelBtn.textContent = "Cancelling...";
        try {
            const res = await fetch(`/api/cancel/${dlId}`, { method: "POST" });
            if (!res.ok) throw new Error("not cancelled");
        } catch {
            // Not cancelled: leave the button usable instead of stuck on "Cancelling...".
            cancelBtn.disabled = false;
            cancelBtn.textContent = "Cancel";
        }
    };
}

function hideCancelBtn() {
    const btn = document.getElementById("v-cancel-btn");
    if (btn) btn.hidden = true;
}

function trackSingleProgress(id, hasMetadata, job, retries = 0) {
    const fill = document.getElementById("v-progress-fill");
    const statusEl = document.getElementById("v-progress-status");
    const pctEl = document.getElementById("v-progress-pct");
    const detailEl = document.getElementById("v-progress-text");
    const btn = job.btn;
    const source = new EventSource(`/api/progress/${id}`);
    // False once another link has been fetched: the card now belongs to that
    // link, so this download finishes quietly (a toast and a history entry).
    const onCard = () => job.gen === cardGen;

    source.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        retries = 0;  // the limit is on failures in a row, not over a long download
        if (d.error && !d.status) {
            // The server no longer knows this id (it was restarted).
            source.close();
            if (!onCard()) return;
            fill.classList.add("is-error");
            hideCancelBtn();
            showError("sdexe lost track of this download. It was probably restarted. Start the download again.");
            if (statusEl) statusEl.textContent = "Failed";
            if (pctEl) pctEl.textContent = "";
            if (detailEl) detailEl.textContent = "";
            endSingle(btn);
            return;
        }
        if (!onCard()) {
            if (d.status === "done") {
                source.close();
                addToHistory(job.title, job.fmt, id, job.url);
                showToast(`${job.title} finished. It is in Recent downloads.`);
                sendNotification("sdexe", `Downloaded: ${job.title}`);
            } else if (d.status === "error") {
                source.close();
                showToast(`${job.title}: ${d.error || "Download failed"}`, "error");
            }
            return;
        }
        fill.style.width = d.progress + "%";
        const detail = d.detail || "";
        if (d.status === "downloading") {
            if (statusEl) statusEl.textContent = "Downloading...";
            if (pctEl) pctEl.textContent = d.progress + "%";
            if (detailEl) detailEl.textContent = detail;
        } else if (d.status === "processing") {
            const ppLabel = detail || "Processing";
            const step = d.pp_step || 1;
            if (statusEl) statusEl.textContent = `Post-processing ${step}: ${ppLabel}...`;
            if (pctEl) pctEl.textContent = "";
            if (detailEl) detailEl.textContent = "";
        } else if (d.status === "metadata") {
            const step = (d.pp_step || 0) + 1;
            if (statusEl) statusEl.textContent = `Post-processing ${step}: Embedding metadata...`;
            if (pctEl) pctEl.textContent = "";
            if (detailEl) detailEl.textContent = "";
        } else if (d.status === "done") {
            source.close();
            fill.style.width = "100%";
            fill.classList.add("is-complete");
            hideCancelBtn();
            const steps = (d.pp_step || 0) + (hasMetadata ? 1 : 0);
            if (statusEl) {
                statusEl.innerHTML = '<span class="progress-complete-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg></span> Complete' + (steps > 0 ? `, ${steps} post-processing step${steps === 1 ? "" : "s"}` : "");
            }
            if (pctEl) pctEl.textContent = "";
            if (detailEl) detailEl.textContent = "";
            const title = job.title;
            addToHistory(title, job.fmt, id, job.url);
            if (d.auto_saved && d.saved_path) {
                const filename = d.saved_path.split(/[\\/]/).pop();
                const savedPath = d.saved_path;
                showToast(`Saved: ${filename}`, "success", [
                    { label: "Open file", fn: () => fetch("/api/open-file", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ path: savedPath }),
                    })},
                    { label: "Open folder", fn: () => fetch("/api/open-folder", { method: "POST" }) },
                ]);
            } else {
                const link = document.getElementById("v-save");
                link.href = `/api/file/${id}`;
                link.hidden = false;
                showToast(`${title} ready. Click Save File`);
            }
            sendNotification("sdexe", `Downloaded: ${title}`);
            endSingle(btn);
        } else if (d.status === "error") {
            source.close();
            fill.classList.add("is-error");
            hideCancelBtn();
            showError(d.error || "Download failed");
            if (statusEl) statusEl.textContent = "Failed";
            if (pctEl) pctEl.textContent = "";
            if (detailEl) detailEl.textContent = "";
            endSingle(btn);
        }
    };
    source.onerror = () => {
        source.close();
        if (retries < 3) {
            if (onCard()) {
                if (statusEl) statusEl.textContent = `Connection lost, retrying (${retries + 1}/3)...`;
                if (pctEl) pctEl.textContent = "";
            }
            setTimeout(() => trackSingleProgress(id, hasMetadata, job, retries + 1), 1500);
        } else if (onCard()) {
            if (statusEl) statusEl.textContent = "Connection lost. Check download history";
            if (pctEl) pctEl.textContent = "";
            hideCancelBtn();
            endSingle(btn);
        }
    };
}

function resetBtn(btn, label) {
    if (btn.classList.contains("fp-btn")) {
        document.querySelectorAll(".fp-btn").forEach(b => { b.disabled = false; b.textContent = "Download"; });
        document.querySelectorAll(".fp-row").forEach(r => r.classList.remove("is-active"));
        return;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> ${label}`;
}

/* ── Batch Summary Helpers ── */
function showSummary() {
    document.getElementById("p-summary").hidden = false;
}

function updateSummary(current, total, done, failed, currentTitle) {
    document.getElementById("bs-label").textContent = "Downloading...";
    document.getElementById("bs-counter").textContent = `${current} / ${total}`;
    document.getElementById("bs-fill").style.width = ((done + failed) / total * 100) + "%";
    document.getElementById("bs-now").textContent = currentTitle ? `Now: ${currentTitle}` : "";

    const parts = [];
    if (done > 0) parts.push(`<span class="done">${done} done</span>`);
    if (failed > 0) parts.push(`<span class="fail">${failed} failed</span>`);
    const remaining = total - done - failed;
    if (remaining > 0 && (done > 0 || failed > 0)) parts.push(`${remaining} left`);
    document.getElementById("bs-stats").innerHTML = parts.join('<span style="color:var(--border)">|</span>');
}

function finishSummary(total, done, failed, completedIds) {
    const summary = document.getElementById("p-summary");
    summary.classList.add("is-done");

    document.getElementById("bs-label").textContent = failed > 0
        ? (lastEntryError ? `Finished with errors: ${lastEntryError}` : "Finished with errors")
        : "All downloads complete";
    document.getElementById("bs-counter").textContent = `${done} / ${total}`;
    document.getElementById("bs-fill").style.width = "100%";
    document.getElementById("bs-now").textContent = "";

    const parts = [];
    parts.push(`<span class="done">${done} downloaded</span>`);
    if (failed > 0) parts.push(`<span class="fail">${failed} failed</span>`);
    document.getElementById("bs-stats").innerHTML = parts.join('<span style="color:var(--border)">|</span>');

    const msg = failed > 0 ? `${done} downloaded, ${failed} failed` : `${done} files downloaded`;
    showToast(msg, failed > 0 ? "error" : "success");
    sendNotification("sdexe", msg);

    const old = summary.querySelector(".btn-zip");
    if (old) old.remove();

    if (completedIds.length > 1) {
        const btn = document.createElement("a");
        btn.className = "btn-save btn-zip";
        btn.textContent = "Download All as ZIP";
        btn.href = "#";
        let zipping = false;
        btn.onclick = async (e) => {
            e.preventDefault();
            if (zipping) return;  // Enter on the focused link gets past pointer-events
            zipping = true;
            btn.textContent = "Zipping...";
            btn.style.pointerEvents = "none";
            try {
                const res = await fetch("/api/batch-zip", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ids: completedIds}),
                });
                if (!res.ok) { btn.textContent = "ZIP failed"; return; }
                const blob = await res.blob();
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                const album = document.getElementById("p-album").value.trim();
                a.download = (album || "downloads") + ".zip";
                a.click();
                URL.revokeObjectURL(a.href);
                btn.textContent = "Download All as ZIP";
            } catch {
                btn.textContent = "ZIP failed";
            } finally {
                zipping = false;
                btn.style.pointerEvents = "";
            }
        };
        summary.appendChild(btn);
    }
}

/* ── Playlist Download (concurrent) ── */
async function startPlaylistDownload() {
    hideError();
    const entries = document.querySelectorAll("#p-entries .entry");
    const selected = [];
    entries.forEach(el => {
        if (el.querySelector("input[type=checkbox]").checked) selected.push(el);
    });
    if (selected.length === 0) { showError("No videos selected"); return; }

    const fmt = document.getElementById("p-format").value;
    const quality = document.getElementById("p-quality").value;
    const artist = document.getElementById("p-artist").value.trim();
    const album = document.getElementById("p-album").value.trim();
    const btn = document.getElementById("p-dl-btn");
    btn.disabled = true;
    requestNotifPermission();

    // This batch's own list and results. Fetching another link replaces
    // playlistEntries and the rows on the page; a batch that kept reading
    // those would download the new list's links under the old rows.
    const gen = cardGen;
    const live = () => gen === cardGen;
    const batchEntries = playlistEntries;
    const completedIds = [];

    const total = selected.length;
    let done = 0;
    let failed = 0;
    let queued = 0;

    const summary = document.getElementById("p-summary");
    summary.className = "batch-summary";
    showSummary();

    selected.forEach(el => {
        const status = el.querySelector(".entry-status");
        if (!status.querySelector(".entry-save")) {
            status.innerHTML = `<span class="entry-queued">Queued</span>`;
        }
    });

    const CONCURRENCY = Math.min(3, selected.length);

    async function worker() {
        // Stops taking new items once the list is gone from the page.
        while (queued < selected.length && live()) {
            const i = queued++;
            const el = selected[i];
            const idx = parseInt(el.dataset.index);
            const entry = batchEntries[idx];
            const status = el.querySelector(".entry-status");

            if (status.querySelector(".entry-save")) {
                // Downloaded by an earlier run of this list: keep it in the ZIP.
                if (el.dataset.dlId) completedIds.push(el.dataset.dlId);
                done++;
                updateSummary(done + failed, total, done, failed, null);
                continue;
            }

            el.classList.add("is-active");
            scrollIfNeeded(el);
            updateSummary(done + failed + 1, total, done, failed, entry.title);

            status.innerHTML = `
                <span class="entry-pct">0%</span>
                <div class="entry-progress"><div class="entry-progress-fill"></div></div>
            `;

            try {
                let res, data;
                for (let attempt = 0; ; attempt++) {
                    res = await fetch("/api/download", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({
                            url: entry.url,
                            format: fmt,
                            quality,
                            metadata: {title: entry.title, artist, album},
                        }),
                    });
                    data = await res.json();
                    // The server takes 12 new downloads per 10 seconds. A run of
                    // short or failing items can outpace that: wait, don't fail.
                    if (res.status !== 429 || attempt >= 5 || !live()) break;
                    await new Promise(r => setTimeout(r, 2500));
                }
                if (!res.ok) {
                    const reason = data.error || `Request failed (${res.status})`;
                    status.innerHTML = `<span class="entry-error" title="${esc(reason)}">${esc(reason)}</span>`;
                    lastEntryError = reason;
                    failed++;
                } else {
                    const ok = await trackEntryProgress(data.id, status);
                    if (ok) {
                        done++;
                        el.classList.add("is-done");
                        el.dataset.dlId = data.id;
                        completedIds.push(data.id);
                        addToHistory(entry.title, fmt, data.id, entry.url);
                    } else { failed++; }
                }
            } catch {
                const reason = "Could not reach sdexe";
                status.innerHTML = `<span class="entry-error" title="${esc(reason)}">${esc(reason)}</span>`;
                lastEntryError = reason;
                failed++;
            }

            el.classList.remove("is-active");
            if (live()) updateSummary(done + failed, total, done, failed, null);
        }
    }

    const workers = Array.from({length: CONCURRENCY}, worker);
    await Promise.all(workers);

    if (!live()) {
        // The list was replaced mid-batch. What finished is in Recent downloads.
        if (done > 0) showToast(`Earlier batch stopped: ${done} of ${total} downloaded.`);
        return;
    }
    finishSummary(total, done, failed, completedIds);
    resetBtn(btn, "Download Selected");
}

function trackEntryProgress(id, statusEl, retries = 0) {
    return new Promise(resolve => {
        const fill = () => statusEl.querySelector(".entry-progress-fill");
        const pct = () => statusEl.querySelector(".entry-pct");
        const source = new EventSource(`/api/progress/${id}`);

        source.onmessage = (ev) => {
            const d = JSON.parse(ev.data);
            retries = 0;
            if (d.error && !d.status) {
                // The server no longer knows this id (it was restarted).
                source.close();
                const reason = "sdexe was restarted during this download";
                statusEl.innerHTML = `<span class="entry-error" title="${esc(reason)}">${esc(reason)}</span>`;
                lastEntryError = reason;
                resolve(false);
                return;
            }
            if (fill()) fill().style.width = d.progress + "%";

            if (d.status === "downloading" && pct()) {
                pct().textContent = d.progress + "%";
            } else if (d.status === "processing" && pct()) {
                pct().textContent = d.detail || "Processing";
                pct().classList.add("entry-processing");
            } else if (d.status === "metadata" && pct()) {
                pct().textContent = "Embedding metadata";
                pct().classList.add("entry-processing");
            } else if (d.status === "done") {
                source.close();
                statusEl.innerHTML = `<a href="/api/file/${encodeURIComponent(id)}" class="entry-save">Save</a>`;
                resolve(true);
            } else if (d.status === "error") {
                source.close();
                // Show the real reason. A bare "Failed" makes a broken playlist
                // impossible to diagnose.
                const reason = d.error || "Failed";
                statusEl.innerHTML = `<span class="entry-error" title="${esc(reason)}">${esc(reason)}</span>`;
                lastEntryError = reason;
                resolve(false);
            }
        };
        source.onerror = () => {
            source.close();
            if (retries < 2) {
                setTimeout(() => trackEntryProgress(id, statusEl, retries + 1).then(resolve), 1200);
            } else {
                statusEl.innerHTML = `<span class="entry-error" title="Lost connection to sdexe">Connection lost</span>`;
                lastEntryError = "Lost connection to sdexe";
                resolve(false);
            }
        };
    });
}

/* ── Keyboard: the Recent downloads header is a div, so give it a button's keys ── */
document.querySelector(".history-header")?.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleHistory();
    }
});

/* ── Keyboard: "/" to focus URL bar ── */
document.addEventListener("keydown", e => {
    if (e.key === "/" && !["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName)) {
        e.preventDefault();
        const ta = document.getElementById("url");
        if (ta) { ta.focus(); ta.select(); }
    }
});

/* ── Enter key (Ctrl/Cmd+Enter for multi-line, Enter for single-line) ── */
document.getElementById("url").addEventListener("keydown", e => {
    const ta = e.target;
    const isMultiLine = ta.value.includes("\n");
    if (e.key === "Enter" && !isMultiLine && !e.shiftKey) {
        e.preventDefault();
        fetchInfo();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        fetchInfo();
    }
});

/* ── Paste-to-fetch ── */
document.getElementById("url").addEventListener("paste", () => {
    setTimeout(() => {
        const text = document.getElementById("url").value.trim();
        if (text && (text.startsWith("http://") || text.startsWith("https://"))) {
            fetchInfo();
        }
    }, 0);
});

/* ── Persist quality selection ── */
document.addEventListener("change", e => {
    if (e.target.id === "v-quality" || e.target.id === "p-quality") {
        lsSet("sdexe_quality", e.target.value);
    }
});

/* ── Clip Toggle ── */
document.getElementById("v-clip-toggle").addEventListener("change", function() {
    document.getElementById("v-clip-fields").style.display = this.checked ? "flex" : "none";
});

/* ── Init ── */
initTextarea();
initPills();
loadConfig();
tryClipboard();
