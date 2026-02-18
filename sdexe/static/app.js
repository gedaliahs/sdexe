let currentUrl = "";
let playlistEntries = [];
let completedIds = [];
let outputFolder = "";
const downloadHistory = [];

/* ── Toast ── */
function showToast(message, type = "success", actions = null) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const span = document.createElement("span");
    span.textContent = message;
    toast.appendChild(span);
    // actions: array of {label, fn} objects, or single {label, fn}, or legacy (actionLabel, actionFn) via compat
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
    requestAnimationFrame(() => requestAnimationFrame(() => toast.classList.add("toast-visible")));
    setTimeout(() => {
        toast.classList.remove("toast-visible");
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

/* ── Web Notifications ── */
function sendNotification(title, body) {
    if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body });
    }
}
function requestNotifPermission() {
    if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
    }
}

/* ── Download History ── */
async function addToHistory(title, format, id, url) {
    const item = { title, format, id, url: url || currentUrl };
    downloadHistory.unshift(item);
    if (downloadHistory.length > 50) downloadHistory.pop();
    renderHistory();
    try {
        await fetch("/api/history", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(item),
        });
    } catch {}
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
    if (toggle) toggle.textContent = `Recent (${downloadHistory.length})`;
    list.innerHTML = downloadHistory.map(item => `
        <div class="history-item">
            <div class="history-info">
                <span class="history-title">${esc(item.title)}</span>
                <span class="history-fmt">${item.format.toUpperCase()}</span>
            </div>
            ${item.url ? `<button class="history-refetch" title="Re-fetch this URL" onclick="refetchUrl(${JSON.stringify(item.url)})">↩</button>` : ""}
            <a href="/api/file/${item.id}" class="history-save">Save</a>
        </div>
    `).join("");
}
function toggleHistory() {
    const list = document.getElementById("history-list");
    const chevron = document.getElementById("history-chevron");
    if (!list) return;
    list.hidden = !list.hidden;
    if (chevron) chevron.classList.toggle("open", !list.hidden);
}

/* ── Config / Output Folder ── */
async function loadConfig() {
    try {
        const res = await fetch("/api/config");
        const cfg = await res.json();
        outputFolder = cfg.output_folder || "";
        updateFolderDisplay();
    } catch {}
    try {
        const res = await fetch("/api/history");
        const items = await res.json();
        if (Array.isArray(items) && items.length) {
            downloadHistory.length = 0;
            items.forEach(i => downloadHistory.push(i));
            renderHistory();
        }
    } catch {}
}
function updateFolderDisplay() {
    const el = document.getElementById("folder-display");
    if (!el) return;
    el.textContent = outputFolder || "None (manual save)";
}
function promptSetFolder() {
    const recents = getRecentFolders();
    const hint = recents.length ? `\nRecent: ${recents.slice(0,3).join(", ")}` : "";
    const input = prompt(`Set download folder path (leave empty to disable):${hint}`, outputFolder);
    if (input === null) return;
    outputFolder = input.trim();
    updateFolderDisplay();
    if (outputFolder) addRecentFolder(outputFolder);
    fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ output_folder: outputFolder }),
    });
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

/* ── Helpers ── */
function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}
function formatDuration(sec) {
    if (!sec) return "";
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
    return `${m}:${String(s).padStart(2,"0")}`;
}
function showError(msg) { const el = document.getElementById("error"); el.textContent = msg; el.hidden = false; }
function hideError() { document.getElementById("error").hidden = true; }

function hideAll() {
    document.getElementById("video-card").hidden = true;
    document.getElementById("playlist-panel").hidden = true;
    document.getElementById("v-progress").hidden = true;
    document.getElementById("v-save").hidden = true;
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
    return text.split("\n")
        .map(l => l.trim())
        .filter(l => l && (l.startsWith("http://") || l.startsWith("https://")));
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
    // Show subtitle option only for MP4 (single video)
    if (prefix === "v") {
        const subWrap = document.getElementById("v-subtitle-wrap");
        if (subWrap) subWrap.style.display = fmt === "mp4" ? "block" : "none";
    }
    // Persist format choice
    localStorage.setItem("sdexe_format", fmt);
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

    hideError();
    hideAll();
    showSkeleton();

    const urls = parseUrls(text);

    const btn = document.getElementById("fetch-btn");
    btn.disabled = true;
    btn.querySelector(".btn-text").textContent = "Loading";
    document.title = "Fetching… — sdexe";

    try {
        if (urls.length > 1) {
            await fetchMultipleUrls(urls);
        } else {
            // Single URL — original behavior
            const url = urls[0] || text;
            const res = await fetch("/api/info", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({url}),
            });
            const data = await res.json();
            if (!res.ok) { showError(data.error || "Failed to fetch info"); return; }

            currentUrl = url;

            if (data.type === "playlist") {
                renderPlaylist(data);
            } else {
                renderVideo(data);
            }
        }
    } catch (e) {
        showError("Network error — is the server running?");
    } finally {
        hideSkeleton();
        btn.disabled = false;
        btn.querySelector(".btn-text").textContent = "Fetch";
        document.title = "Media Downloader — sdexe";
    }
}

/* ── Fetch Multiple URLs ── */
async function fetchMultipleUrls(urls) {
    const btn = document.getElementById("fetch-btn");
    const entries = [];
    let errors = 0;

    for (let i = 0; i < urls.length; i++) {
        btn.querySelector(".btn-text").textContent = `${i + 1} / ${urls.length}`;
        try {
            const res = await fetch("/api/info", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({url: urls[i]}),
            });
            const data = await res.json();
            if (!res.ok) { errors++; continue; }

            if (data.type === "playlist") {
                // Flatten playlist entries
                for (const entry of data.entries) {
                    entries.push(entry);
                }
            } else {
                entries.push({
                    title: data.title || "Unknown",
                    url: data.url || urls[i],
                    duration: data.duration,
                    id: "",
                    thumbnail: data.thumbnail || "",
                });
            }
        } catch {
            errors++;
        }
    }

    if (entries.length === 0) {
        showError(`Could not fetch info for any of the ${urls.length} URLs`);
        return;
    }

    // Show as a virtual playlist
    renderPlaylist({
        title: `${entries.length} items from ${urls.length} links`,
        uploader: errors > 0 ? `${errors} link(s) failed` : null,
        count: entries.length,
        entries,
    });
}

/* ── Restore saved format/quality ── */
function restoreFormatPrefs(prefix) {
    const savedFmt = localStorage.getItem("sdexe_format");
    if (savedFmt) {
        const fmtEl = document.getElementById(prefix + "-format");
        if (fmtEl && fmtEl.querySelector(`option[value="${savedFmt}"]`)) fmtEl.value = savedFmt;
    }
    updateQuality(prefix);
    const savedQ = localStorage.getItem("sdexe_quality");
    if (savedQ) {
        const qEl = document.getElementById(prefix + "-quality");
        if (qEl && qEl.querySelector(`option[value="${savedQ}"]`)) qEl.value = savedQ;
    }
}

/* ── Recently used folders ── */
function getRecentFolders() {
    try { return JSON.parse(localStorage.getItem("sdexe_recent_folders") || "[]"); } catch { return []; }
}
function addRecentFolder(path) {
    if (!path) return;
    const recents = getRecentFolders().filter(f => f !== path);
    recents.unshift(path);
    localStorage.setItem("sdexe_recent_folders", JSON.stringify(recents.slice(0, 5)));
}

/* ── Render Single Video ── */
function renderVideo(data) {
    document.getElementById("v-thumb").src = data.thumbnail || "";
    document.getElementById("v-duration").textContent = formatDuration(data.duration);
    document.getElementById("v-title").value = data.title || "";
    document.getElementById("v-artist").value = data.uploader || "";
    document.getElementById("v-album").value = "";
    document.getElementById("video-card").hidden = false;
    restoreFormatPrefs("v");
}

/* ── Render Playlist ── */
function renderPlaylist(data) {
    playlistEntries = data.entries;

    document.getElementById("p-title").textContent = data.title;
    document.getElementById("p-meta").textContent =
        [data.uploader, `${data.count} videos`].filter(Boolean).join(" · ");
    document.getElementById("p-artist").value = data.uploader || "";
    document.getElementById("p-album").value = data.title || "";

    // Reset summary
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
            <input type="checkbox" checked onchange="updateCount()">
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
async function startSingleDownload() {
    hideError();
    document.getElementById("v-save").hidden = true;

    const fmt = document.getElementById("v-format").value;
    const quality = document.getElementById("v-quality").value;
    const subtitles = document.getElementById("v-subtitles")?.checked ?? false;
    const metadata = {
        title: document.getElementById("v-title").value.trim(),
        artist: document.getElementById("v-artist").value.trim(),
        album: document.getElementById("v-album").value.trim(),
    };

    const btn = document.getElementById("v-dl-btn");
    btn.disabled = true;
    btn.textContent = "Starting...";
    requestNotifPermission();

    try {
        const res = await fetch("/api/download", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({url: currentUrl, format: fmt, quality, metadata, subtitles}),
        });
        const data = await res.json();
        if (!res.ok) { showError(data.error || "Download failed"); resetBtn(btn, "Download"); return; }

        document.getElementById("v-progress").hidden = false;
        showCancelBtn(data.id);
        const hasMetadata = !!(metadata.title || metadata.artist || metadata.album);
        trackSingleProgress(data.id, hasMetadata);
    } catch (e) {
        showError("Network error");
        resetBtn(btn, "Download");
    }
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
    cancelBtn.onclick = async () => {
        cancelBtn.disabled = true;
        cancelBtn.textContent = "Cancelling...";
        await fetch(`/api/cancel/${dlId}`, { method: "POST" });
    };
}

function hideCancelBtn() {
    const btn = document.getElementById("v-cancel-btn");
    if (btn) btn.hidden = true;
}

function trackSingleProgress(id, hasMetadata, retries = 0) {
    const fill = document.getElementById("v-progress-fill");
    const text = document.getElementById("v-progress-text");
    const btn = document.getElementById("v-dl-btn");
    const source = new EventSource(`/api/progress/${id}`);

    source.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        fill.style.width = d.progress + "%";
        const detail = d.detail || "";
        if (d.status === "downloading") {
            text.textContent = `Downloading... ${d.progress}%` + (detail ? `  ·  ${detail}` : "");
        } else if (d.status === "processing") {
            const ppLabel = detail || "Processing";
            const step = d.pp_step || 1;
            text.textContent = `Post-processing ${step}: ${ppLabel}...`;
        } else if (d.status === "metadata") {
            const step = (d.pp_step || 0) + 1;
            text.textContent = `Post-processing ${step}: Embedding metadata...`;
        } else if (d.status === "done") {
            source.close(); fill.style.width = "100%"; hideCancelBtn();
            const steps = (d.pp_step || 0) + (hasMetadata ? 1 : 0);
            text.textContent = `Complete` + (steps > 0 ? ` — ${steps} post-processing step${steps === 1 ? "" : "s"} finished` : "");
            const title = document.getElementById("v-title").value.trim() || "Download";
            const fmt = document.getElementById("v-format").value;
            addToHistory(title, fmt, id);
            if (d.auto_saved && d.saved_path) {
                const filename = d.saved_path.split("/").pop();
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
                showToast(`${title} ready — click Save File`);
            }
            sendNotification("sdexe", `Downloaded: ${title}`);
            resetBtn(btn, "Download");
        } else if (d.status === "error") {
            source.close(); hideCancelBtn();
            showError(d.error || "Download failed"); text.textContent = "";
            resetBtn(btn, "Download");
        }
    };
    source.onerror = () => {
        source.close();
        if (retries < 3) {
            text.textContent = `Connection lost — retrying (${retries + 1}/3)...`;
            setTimeout(() => trackSingleProgress(id, hasMetadata, retries + 1), 1500);
        } else {
            text.textContent = "Connection lost — check download history";
            hideCancelBtn();
            resetBtn(btn, "Download");
        }
    };
}

function resetBtn(btn, label) {
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

function finishSummary(total, done, failed) {
    const summary = document.getElementById("p-summary");
    summary.classList.add("is-done");

    document.getElementById("bs-label").textContent = failed > 0 ? "Finished with errors" : "All downloads complete";
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

    // Remove any existing ZIP button
    const old = summary.querySelector(".btn-zip");
    if (old) old.remove();

    if (completedIds.length > 1) {
        const btn = document.createElement("a");
        btn.className = "btn-save btn-zip";
        btn.textContent = "Download All as ZIP";
        btn.href = "#";
        btn.onclick = async (e) => {
            e.preventDefault();
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
    completedIds = [];
    requestNotifPermission();

    const total = selected.length;
    let done = 0;
    let failed = 0;
    let queued = 0; // next index to pick up

    // Reset summary banner
    const summary = document.getElementById("p-summary");
    summary.className = "batch-summary";
    showSummary();

    // Mark all selected as queued (skip already-done ones)
    selected.forEach(el => {
        const status = el.querySelector(".entry-status");
        if (!status.querySelector(".entry-save")) {
            status.innerHTML = `<span class="entry-queued">Queued</span>`;
        }
    });

    const CONCURRENCY = Math.min(3, selected.length);

    async function worker() {
        while (queued < selected.length) {
            const i = queued++;
            const el = selected[i];
            const idx = parseInt(el.dataset.index);
            const entry = playlistEntries[idx];
            const status = el.querySelector(".entry-status");

            // Skip already-downloaded entries
            if (status.querySelector(".entry-save")) {
                done++;
                updateSummary(done + failed, total, done, failed, null);
                continue;
            }

            el.classList.add("is-active");
            el.scrollIntoView({ behavior: "smooth", block: "nearest" });
            updateSummary(done + failed + 1, total, done, failed, entry.title);

            status.innerHTML = `
                <span class="entry-pct">0%</span>
                <div class="entry-progress"><div class="entry-progress-fill"></div></div>
            `;

            try {
                const res = await fetch("/api/download", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        url: entry.url,
                        format: fmt,
                        quality,
                        metadata: {title: entry.title, artist, album},
                    }),
                });
                const data = await res.json();
                if (!res.ok) {
                    status.innerHTML = `<span class="entry-error">Error</span>`;
                    failed++;
                } else {
                    const ok = await trackEntryProgress(data.id, status);
                    if (ok) {
                        done++;
                        el.classList.add("is-done");
                        completedIds.push(data.id);
                        addToHistory(entry.title, fmt, data.id);
                    } else { failed++; }
                }
            } catch {
                status.innerHTML = `<span class="entry-error">Failed</span>`;
                failed++;
            }

            el.classList.remove("is-active");
            updateSummary(done + failed, total, done, failed, null);
        }
    }

    const workers = Array.from({length: CONCURRENCY}, worker);
    await Promise.all(workers);

    finishSummary(total, done, failed);
    resetBtn(btn, "Download Selected");
}

function trackEntryProgress(id, statusEl, retries = 0) {
    return new Promise(resolve => {
        const fill = () => statusEl.querySelector(".entry-progress-fill");
        const pct = () => statusEl.querySelector(".entry-pct");
        const source = new EventSource(`/api/progress/${id}`);

        source.onmessage = (ev) => {
            const d = JSON.parse(ev.data);
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
                statusEl.innerHTML = `<a href="/api/file/${id}" class="entry-save">Save</a>`;
                resolve(true);
            } else if (d.status === "error") {
                source.close();
                statusEl.innerHTML = `<span class="entry-error">Failed</span>`;
                resolve(false);
            }
        };
        source.onerror = () => {
            source.close();
            if (retries < 2) {
                setTimeout(() => trackEntryProgress(id, statusEl, retries + 1).then(resolve), 1200);
            } else {
                statusEl.innerHTML = `<span class="entry-error">Failed</span>`;
                resolve(false);
            }
        };
    });
}

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
        localStorage.setItem("sdexe_quality", e.target.value);
    }
});

/* ── Init ── */
initTextarea();
loadConfig();
tryClipboard();
