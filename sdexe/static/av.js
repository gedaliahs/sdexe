/* ── State ── */
const avFiles = {};

/* ── Hash Routing ── */
function showTab(tab) {
    document.querySelectorAll(".pdf-section").forEach(s => s.classList.remove("active"));
    const el = document.getElementById("tab-" + tab);
    (el || document.querySelector(".pdf-section")).classList.add("active");
    window.scrollTo(0, 0);
}
showTab(location.hash.slice(1) || "av-convert-audio");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "av-convert-audio"));

/* ── Drop Zone Setup ── */
function setupDropZone(zoneId, inputId, handler) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    if (!zone || !input) return;
    let dragCount = 0;

    zone.addEventListener("dragenter", e => { e.preventDefault(); if (++dragCount === 1) zone.classList.add("drag-over"); });
    zone.addEventListener("dragover", e => { e.preventDefault(); });
    zone.addEventListener("dragleave", () => { if (--dragCount === 0) zone.classList.remove("drag-over"); });
    zone.addEventListener("drop", e => {
        e.preventDefault();
        dragCount = 0;
        zone.classList.remove("drag-over");
        handler(e.dataTransfer.files);
    });
    input.addEventListener("change", () => {
        handler(input.files);
        input.value = "";
    });
}

/* ── Generic AV file loader ── */
function loadAvFile(prefix, files, acceptType) {
    const f = files[0];
    if (!f) return;
    if (acceptType && !f.type.startsWith(acceptType)) return;
    avFiles[prefix] = f;
    document.getElementById(`${prefix}-name`).textContent = f.name;
    document.getElementById(`${prefix}-size`).textContent = formatSize(f.size);
    document.getElementById(`${prefix}-info`).hidden = false;
    document.getElementById(`${prefix}-options`).hidden = false;
    document.getElementById(`${prefix}-actions`).hidden = false;
}

function clearAvFile(prefix) {
    avFiles[prefix] = null;
    document.getElementById(`${prefix}-info`).hidden = true;
    document.getElementById(`${prefix}-options`).hidden = true;
    document.getElementById(`${prefix}-actions`).hidden = true;
}

/* ── Generic AV fetch ── */
async function avFetch(prefix, endpoint, buildForm, downloadName, loadingText) {
    const f = avFiles[prefix];
    if (!f) return;
    const btn = document.getElementById(`${prefix}-btn`);
    const err = document.getElementById(`${prefix}-error`);
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = loadingText || "Processing...";

    const form = buildForm(f);

    try {
        const res = await fetch(endpoint, { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Processing failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
            const name = match ? match[1] : downloadName(f);
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }

    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> ${btn.dataset.label || "Download"}`;
}

/* ── Convert Audio ── */
setupDropZone("av-convert-audio-drop", "av-convert-audio-input", files => loadAvFile("av-convert-audio", files, "audio/"));

document.getElementById("av-convert-audio-btn").dataset.label = "Convert Audio";

async function doAvConvertAudio() {
    const f = avFiles["av-convert-audio"];
    if (!f) return;
    const fmt = document.getElementById("av-convert-audio-format").value;
    await avFetch("av-convert-audio", "/api/av/convert-audio",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("format", fmt); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "." + fmt,
        "Converting..."
    );
}

/* ── Trim Audio ── */
setupDropZone("av-trim-audio-drop", "av-trim-audio-input", files => loadAvFile("av-trim-audio", files, "audio/"));

document.getElementById("av-trim-audio-btn").dataset.label = "Trim Audio";

async function doAvTrimAudio() {
    const f = avFiles["av-trim-audio"];
    if (!f) return;
    const start = document.getElementById("av-trim-audio-start").value.trim();
    const end = document.getElementById("av-trim-audio-end").value.trim();
    if (!start) {
        const err = document.getElementById("av-trim-audio-error");
        err.textContent = "Start time is required";
        err.hidden = false;
        return;
    }
    await avFetch("av-trim-audio", "/api/av/trim-audio",
        file => {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("start", start);
            if (end) fd.append("end", end);
            return fd;
        },
        file => { const base = file.name.replace(/\.[^.]+$/, ""); const ext = file.name.split(".").pop(); return `${base}_trimmed.${ext}`; },
        "Trimming..."
    );
}

/* ── Change Speed ── */
setupDropZone("av-speed-drop", "av-speed-input", files => loadAvFile("av-speed", files, "audio/"));

document.getElementById("av-speed-btn").dataset.label = "Change Speed";

async function doAvSpeed() {
    const f = avFiles["av-speed"];
    if (!f) return;
    const speed = document.getElementById("av-speed-value").value;
    await avFetch("av-speed", "/api/av/audio-speed",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("speed", speed); return fd; },
        file => { const base = file.name.replace(/\.[^.]+$/, ""); const ext = file.name.split(".").pop(); return `${base}_${speed}x.${ext}`; },
        "Processing..."
    );
}

/* ── Extract Audio ── */
setupDropZone("av-extract-audio-drop", "av-extract-audio-input", files => loadAvFile("av-extract-audio", files, "video/"));

document.getElementById("av-extract-audio-btn").dataset.label = "Extract Audio";

async function doAvExtractAudio() {
    const f = avFiles["av-extract-audio"];
    if (!f) return;
    const fmt = document.getElementById("av-extract-audio-format").value;
    await avFetch("av-extract-audio", "/api/av/extract-audio",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("format", fmt); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_audio." + fmt,
        "Extracting..."
    );
}

/* ── Trim Video ── */
setupDropZone("av-trim-video-drop", "av-trim-video-input", files => loadAvFile("av-trim-video", files, "video/"));

document.getElementById("av-trim-video-btn").dataset.label = "Trim Video";

async function doAvTrimVideo() {
    const f = avFiles["av-trim-video"];
    if (!f) return;
    const start = document.getElementById("av-trim-video-start").value.trim();
    const end = document.getElementById("av-trim-video-end").value.trim();
    if (!start) {
        const err = document.getElementById("av-trim-video-error");
        err.textContent = "Start time is required";
        err.hidden = false;
        return;
    }
    await avFetch("av-trim-video", "/api/av/trim-video",
        file => {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("start", start);
            if (end) fd.append("end", end);
            return fd;
        },
        file => { const base = file.name.replace(/\.[^.]+$/, ""); const ext = file.name.split(".").pop(); return `${base}_trimmed.${ext}`; },
        "Trimming..."
    );
}

/* ── Compress Video ── */
setupDropZone("av-compress-video-drop", "av-compress-video-input", files => loadAvFile("av-compress-video", files, "video/"));

document.getElementById("av-compress-video-btn").dataset.label = "Compress Video";

async function doAvCompressVideo() {
    const f = avFiles["av-compress-video"];
    if (!f) return;
    const quality = document.getElementById("av-compress-video-quality").value;
    await avFetch("av-compress-video", "/api/av/compress-video",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("quality", quality); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_compressed.mp4",
        "Compressing..."
    );
}

/* ── Convert Video ── */
setupDropZone("av-convert-video-drop", "av-convert-video-input", files => loadAvFile("av-convert-video", files, "video/"));

document.getElementById("av-convert-video-btn").dataset.label = "Convert Video";

async function doAvConvertVideo() {
    const f = avFiles["av-convert-video"];
    if (!f) return;
    const fmt = document.getElementById("av-convert-video-format").value;
    await avFetch("av-convert-video", "/api/av/convert-video",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("format", fmt); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "." + fmt,
        "Converting..."
    );
}

/* ── Helpers ── */
function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
}

function downloadBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}
