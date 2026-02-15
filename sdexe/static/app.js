let currentUrl = "";
let playlistEntries = [];
let completedIds = [];

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
        q.innerHTML = `<option value="best">Best (320kbps)</option>`;
        q.disabled = true;
    } else {
        q.innerHTML = `<option value="best">Lossless</option>`;
        q.disabled = true;
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

    hideError();
    hideAll();
    showSkeleton();

    const urls = parseUrls(text);

    const btn = document.getElementById("fetch-btn");
    btn.disabled = true;
    btn.querySelector(".btn-text").textContent = "Loading";

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

/* ── Render Single Video ── */
function renderVideo(data) {
    document.getElementById("v-thumb").src = data.thumbnail || "";
    document.getElementById("v-duration").textContent = formatDuration(data.duration);
    document.getElementById("v-title").value = data.title || "";
    document.getElementById("v-artist").value = data.uploader || "";
    document.getElementById("v-album").value = "";
    document.getElementById("video-card").hidden = false;
    updateQuality("v");
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
    updateQuality("p");
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
    const metadata = {
        title: document.getElementById("v-title").value.trim(),
        artist: document.getElementById("v-artist").value.trim(),
        album: document.getElementById("v-album").value.trim(),
    };

    const btn = document.getElementById("v-dl-btn");
    btn.disabled = true;
    btn.textContent = "Starting...";

    try {
        const res = await fetch("/api/download", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({url: currentUrl, format: fmt, quality, metadata}),
        });
        const data = await res.json();
        if (!res.ok) { showError(data.error || "Download failed"); resetBtn(btn, "Download"); return; }

        document.getElementById("v-progress").hidden = false;
        const hasMetadata = !!(metadata.title || metadata.artist || metadata.album);
        trackSingleProgress(data.id, hasMetadata);
    } catch (e) {
        showError("Network error");
        resetBtn(btn, "Download");
    }
}

function trackSingleProgress(id, hasMetadata) {
    const fill = document.getElementById("v-progress-fill");
    const text = document.getElementById("v-progress-text");
    const btn = document.getElementById("v-dl-btn");
    const source = new EventSource(`/api/progress/${id}`);

    source.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        if (d.error && !["done","error","downloading","processing","starting","metadata"].includes(d.status)) {
            source.close(); showError(d.error); resetBtn(btn, "Download"); return;
        }
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
            source.close(); fill.style.width = "100%";
            const steps = (d.pp_step || 0) + (hasMetadata ? 1 : 0);
            text.textContent = `Complete` + (steps > 0 ? ` — ${steps} post-processing step${steps === 1 ? "" : "s"} finished` : "");
            const link = document.getElementById("v-save");
            link.href = `/api/file/${id}`;
            link.hidden = false;
            resetBtn(btn, "Download");
        } else if (d.status === "error") {
            source.close(); showError(d.error || "Download failed"); text.textContent = "Error";
            resetBtn(btn, "Download");
        }
    };
    source.onerror = () => { source.close(); text.textContent = "Connection lost"; resetBtn(btn, "Download"); };
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

/* ── Playlist Download ── */
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

    const total = selected.length;
    let done = 0;
    let failed = 0;

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

    for (let i = 0; i < selected.length; i++) {
        const el = selected[i];
        const idx = parseInt(el.dataset.index);
        const entry = playlistEntries[idx];
        const status = el.querySelector(".entry-status");

        // Skip already-downloaded entries
        if (status.querySelector(".entry-save")) {
            done++;
            updateSummary(i + 1, total, done, failed, null);
            continue;
        }

        // Highlight current
        el.classList.add("is-active");
        updateSummary(i + 1, total, done, failed, entry.title);

        // Scroll entry into view
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });

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
                el.classList.remove("is-active");
                updateSummary(i + 1, total, done, failed, null);
                continue;
            }

            const ok = await trackEntryProgress(data.id, status);
            if (ok) { done++; el.classList.add("is-done"); completedIds.push(data.id); }
            else { failed++; }
        } catch (e) {
            status.innerHTML = `<span class="entry-error">Failed</span>`;
            failed++;
        }

        el.classList.remove("is-active");
        updateSummary(i + 1, total, done, failed, null);
    }

    finishSummary(total, done, failed);
    resetBtn(btn, "Download Selected");
}

function trackEntryProgress(id, statusEl) {
    return new Promise(resolve => {
        const fill = statusEl.querySelector(".entry-progress-fill");
        const pct = statusEl.querySelector(".entry-pct");
        const source = new EventSource(`/api/progress/${id}`);

        source.onmessage = (ev) => {
            const d = JSON.parse(ev.data);
            if (fill) fill.style.width = d.progress + "%";

            if (d.status === "downloading" && pct) {
                pct.textContent = d.progress + "%";
            } else if (d.status === "processing" && pct) {
                const label = d.detail || "Processing";
                pct.textContent = label;
                pct.classList.add("entry-processing");
            } else if (d.status === "metadata" && pct) {
                pct.textContent = "Embedding metadata";
                pct.classList.add("entry-processing");
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
            statusEl.innerHTML = `<span class="entry-error">Failed</span>`;
            resolve(false);
        };
    });
}

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

/* ── Init ── */
initTextarea();
