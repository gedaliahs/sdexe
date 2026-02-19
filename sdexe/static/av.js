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
    if (!window._pageDropHandlers) window._pageDropHandlers = [];
    window._pageDropHandlers.push({ zoneId, handler });
}

(function() {
    var ov = document.createElement("div");
    ov.className = "page-drop-overlay";
    ov.innerHTML = '<div class="page-drop-message">Drop files anywhere</div>';
    document.body.appendChild(ov);
    var dc = 0;
    document.addEventListener("dragenter", function(e) {
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault(); if (++dc === 1) ov.classList.add("visible");
    });
    document.addEventListener("dragover", function(e) { e.preventDefault(); });
    document.addEventListener("dragleave", function() { if (--dc === 0) ov.classList.remove("visible"); });
    document.addEventListener("drop", function(e) {
        dc = 0; ov.classList.remove("visible");
        if (!e.dataTransfer.files.length) return;
        var handlers = window._pageDropHandlers || [];
        for (var i = 0; i < handlers.length; i++) {
            var zone = document.getElementById(handlers[i].zoneId);
            if (zone && zone.closest(".pdf-section.active")) {
                e.preventDefault(); handlers[i].handler(e.dataTransfer.files); return;
            }
        }
        if (handlers.length) { e.preventDefault(); handlers[0].handler(e.dataTransfer.files); }
    });
})();

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

/* ── Merge Audio ── */
let mergeAudioFiles = [];

setupDropZone("av-merge-audio-drop", "av-merge-audio-input", files => {
    for (const f of files) {
        if (f.type.startsWith("audio/") || /\.(mp3|wav|ogg|flac|aac|m4a)$/i.test(f.name)) {
            mergeAudioFiles.push(f);
        }
    }
    renderMergeAudioList();
});

function renderMergeAudioList() {
    const list = document.getElementById("av-merge-audio-list");
    list.innerHTML = "";
    mergeAudioFiles.forEach((f, i) => {
        const item = document.createElement("div");
        item.className = "file-item";
        item.innerHTML = `<span class="file-name">${f.name}</span><span class="file-size">${formatSize(f.size)}</span><button class="file-remove" onclick="removeMergeAudio(${i})">&times;</button>`;
        list.appendChild(item);
    });
    const show = mergeAudioFiles.length >= 2;
    document.getElementById("av-merge-audio-options").hidden = !show;
    document.getElementById("av-merge-audio-actions").hidden = !show;
}

function removeMergeAudio(i) {
    mergeAudioFiles.splice(i, 1);
    renderMergeAudioList();
}

async function doAvMergeAudio() {
    if (mergeAudioFiles.length < 2) return;
    const btn = document.getElementById("av-merge-audio-btn");
    const err = document.getElementById("av-merge-audio-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Merging...";

    const fmt = document.getElementById("av-merge-audio-format").value;
    const fd = new FormData();
    mergeAudioFiles.forEach(f => fd.append("files", f));
    fd.append("format", fmt);

    try {
        const res = await fetch("/api/av/merge-audio", { method: "POST", body: fd });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Merge failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            downloadBlob(blob, `merged.${fmt}`);
            showToast("Saved: merged." + fmt);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Merge Audio';
}

/* ── Normalize Volume ── */
setupDropZone("av-normalize-drop", "av-normalize-input", files => loadAvFile("av-normalize", files, "audio/"));

document.getElementById("av-normalize-btn").dataset.label = "Normalize Volume";

async function doAvNormalize() {
    await avFetch("av-normalize", "/api/av/normalize-volume",
        file => { const fd = new FormData(); fd.append("file", file); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_normalized." + file.name.split(".").pop(),
        "Normalizing..."
    );
}

/* ── Video to GIF ── */
setupDropZone("av-video-to-gif-drop", "av-video-to-gif-input", files => loadAvFile("av-video-to-gif", files, "video/"));

document.getElementById("av-video-to-gif-btn").dataset.label = "Convert to GIF";

async function doAvVideoToGif() {
    const f = avFiles["av-video-to-gif"];
    if (!f) return;
    const fps = document.getElementById("av-video-to-gif-fps").value;
    const width = document.getElementById("av-video-to-gif-width").value;
    await avFetch("av-video-to-gif", "/api/av/video-to-gif",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("fps", fps); fd.append("width", width); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + ".gif",
        "Converting..."
    );
}

/* ── Reverse Audio ── */
setupDropZone("reverse-audio-drop", "reverse-audio-input", files => loadAvFile("reverse-audio", files, "audio/"));

document.getElementById("reverse-audio-btn").dataset.label = "Reverse Audio";

async function doReverseAudio() {
    await avFetch("reverse-audio", "/api/av/reverse-audio",
        file => { const fd = new FormData(); fd.append("file", file); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_reversed." + file.name.split(".").pop(),
        "Reversing..."
    );
}

/* ── Change Pitch ── */
setupDropZone("pitch-drop", "pitch-input", files => loadAvFile("pitch", files, "audio/"));

document.getElementById("pitch-btn").dataset.label = "Change Pitch";

async function doPitch() {
    const f = avFiles["pitch"];
    if (!f) return;
    const semitones = document.getElementById("pitch-semitones").value;
    await avFetch("pitch", "/api/av/change-pitch",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("semitones", semitones); return fd; },
        file => { const base = file.name.replace(/\.[^.]+$/, ""); const ext = file.name.split(".").pop(); return `${base}_pitch${semitones >= 0 ? '+' : ''}${semitones}.${ext}`; },
        "Processing..."
    );
}

/* ── Audio Equalizer ── */
setupDropZone("equalizer-drop", "equalizer-input", files => loadAvFile("equalizer", files, "audio/"));

document.getElementById("equalizer-btn").dataset.label = "Apply Equalizer";

async function doEqualizer() {
    const f = avFiles["equalizer"];
    if (!f) return;
    const bass = document.getElementById("eq-bass").value;
    const mid = document.getElementById("eq-mid").value;
    const treble = document.getElementById("eq-treble").value;
    await avFetch("equalizer", "/api/av/audio-equalizer",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("bass", bass); fd.append("mid", mid); fd.append("treble", treble); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_eq." + file.name.split(".").pop(),
        "Applying EQ..."
    );
}

/* ── Audio Fade ── */
setupDropZone("fade-drop", "fade-input", files => loadAvFile("fade", files, "audio/"));

document.getElementById("fade-btn").dataset.label = "Apply Fade";

async function doFade() {
    const f = avFiles["fade"];
    if (!f) return;
    const fadeIn = document.getElementById("fade-in").value;
    const fadeOut = document.getElementById("fade-out").value;
    const duration = document.getElementById("fade-duration").value;
    if (!fadeIn && !fadeOut) {
        const err = document.getElementById("fade-error");
        err.textContent = "Set at least one fade duration";
        err.hidden = false;
        return;
    }
    await avFetch("fade", "/api/av/audio-fade",
        file => {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("fade_in", fadeIn || "0");
            fd.append("fade_out", fadeOut || "0");
            if (duration) fd.append("duration", duration);
            return fd;
        },
        file => file.name.replace(/\.[^.]+$/, "") + "_fade." + file.name.split(".").pop(),
        "Applying fade..."
    );
}

/* ── Crop Video ── */
setupDropZone("crop-video-drop", "crop-video-input", files => loadAvFile("crop-video", files, "video/"));

document.getElementById("crop-video-btn").dataset.label = "Crop Video";

async function doCropVideo() {
    const f = avFiles["crop-video"];
    if (!f) return;
    const w = document.getElementById("crop-video-width").value;
    const h = document.getElementById("crop-video-height").value;
    const x = document.getElementById("crop-video-x").value;
    const y = document.getElementById("crop-video-y").value;
    if (!w || !h) {
        const err = document.getElementById("crop-video-error");
        err.textContent = "Width and height are required";
        err.hidden = false;
        return;
    }
    await avFetch("crop-video", "/api/av/crop-video",
        file => {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("width", w);
            fd.append("height", h);
            fd.append("x", x || "0");
            fd.append("y", y || "0");
            return fd;
        },
        file => file.name.replace(/\.[^.]+$/, "") + "_cropped." + file.name.split(".").pop(),
        "Cropping..."
    );
}

/* ── Rotate Video ── */
setupDropZone("rotate-video-drop", "rotate-video-input", files => loadAvFile("rotate-video", files, "video/"));

document.getElementById("rotate-video-btn").dataset.label = "Rotate Video";

async function doRotateVideo() {
    const f = avFiles["rotate-video"];
    if (!f) return;
    const angle = document.getElementById("rotate-video-angle").value;
    await avFetch("rotate-video", "/api/av/rotate-video",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("angle", angle); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_rotated." + file.name.split(".").pop(),
        "Rotating..."
    );
}

/* ── Resize Video ── */
setupDropZone("resize-video-drop", "resize-video-input", files => loadAvFile("resize-video", files, "video/"));

document.getElementById("resize-video-btn").dataset.label = "Resize Video";

async function doResizeVideo() {
    const f = avFiles["resize-video"];
    if (!f) return;
    const w = document.getElementById("resize-video-width").value;
    const h = document.getElementById("resize-video-height").value;
    if (!w || !h) {
        const err = document.getElementById("resize-video-error");
        err.textContent = "Width and height are required";
        err.hidden = false;
        return;
    }
    await avFetch("resize-video", "/api/av/resize-video",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("width", w); fd.append("height", h); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_resized." + file.name.split(".").pop(),
        "Resizing..."
    );
}

/* ── Reverse Video ── */
setupDropZone("reverse-video-drop", "reverse-video-input", files => loadAvFile("reverse-video", files, "video/"));

document.getElementById("reverse-video-btn").dataset.label = "Reverse Video";

async function doReverseVideo() {
    await avFetch("reverse-video", "/api/av/reverse-video",
        file => { const fd = new FormData(); fd.append("file", file); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_reversed." + file.name.split(".").pop(),
        "Reversing..."
    );
}

/* ── Loop Video ── */
setupDropZone("loop-video-drop", "loop-video-input", files => loadAvFile("loop-video", files, "video/"));

document.getElementById("loop-video-btn").dataset.label = "Loop Video";

async function doLoopVideo() {
    const f = avFiles["loop-video"];
    if (!f) return;
    const count = document.getElementById("loop-video-count").value;
    await avFetch("loop-video", "/api/av/loop-video",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("count", count); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + `_x${count}.` + file.name.split(".").pop(),
        "Looping..."
    );
}

/* ── Mute Video ── */
setupDropZone("mute-video-drop", "mute-video-input", files => loadAvFile("mute-video", files, "video/"));

document.getElementById("mute-video-btn").dataset.label = "Mute Video";

async function doMuteVideo() {
    await avFetch("mute-video", "/api/av/mute-video",
        file => { const fd = new FormData(); fd.append("file", file); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_muted." + file.name.split(".").pop(),
        "Muting..."
    );
}

/* ── Add Audio to Video ── */
let addAudioVideoFile = null;
let addAudioAudioFile = null;

setupDropZone("add-audio-video-drop", "add-audio-video-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("video/")) return;
    addAudioVideoFile = f;
    document.getElementById("add-audio-video-name").textContent = f.name;
    document.getElementById("add-audio-video-size").textContent = formatSize(f.size);
    document.getElementById("add-audio-video-info").hidden = false;
    updateAddAudioActions();
});

setupDropZone("add-audio-audio-drop", "add-audio-audio-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("audio/")) return;
    addAudioAudioFile = f;
    document.getElementById("add-audio-audio-name").textContent = f.name;
    document.getElementById("add-audio-audio-size").textContent = formatSize(f.size);
    document.getElementById("add-audio-audio-info").hidden = false;
    updateAddAudioActions();
});

function clearAddAudioVideo() {
    addAudioVideoFile = null;
    document.getElementById("add-audio-video-info").hidden = true;
    updateAddAudioActions();
}

function clearAddAudioAudio() {
    addAudioAudioFile = null;
    document.getElementById("add-audio-audio-info").hidden = true;
    updateAddAudioActions();
}

function updateAddAudioActions() {
    document.getElementById("add-audio-actions").hidden = !(addAudioVideoFile && addAudioAudioFile);
}

async function doAddAudio() {
    if (!addAudioVideoFile || !addAudioAudioFile) return;
    const btn = document.getElementById("add-audio-btn");
    const err = document.getElementById("add-audio-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Processing...";

    const fd = new FormData();
    fd.append("video", addAudioVideoFile);
    fd.append("audio", addAudioAudioFile);

    try {
        const res = await fetch("/api/av/add-audio", { method: "POST", body: fd });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Processing failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
            const name = match ? match[1] : addAudioVideoFile.name.replace(/\.[^.]+$/, "") + "_with_audio." + addAudioVideoFile.name.split(".").pop();
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Add Audio';
}

/* ── Burn Subtitles ── */
let burnSubsVideoFile = null;
let burnSubsSrtFile = null;

setupDropZone("burn-subs-video-drop", "burn-subs-video-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("video/")) return;
    burnSubsVideoFile = f;
    document.getElementById("burn-subs-video-name").textContent = f.name;
    document.getElementById("burn-subs-video-size").textContent = formatSize(f.size);
    document.getElementById("burn-subs-video-info").hidden = false;
    updateBurnSubsActions();
});

setupDropZone("burn-subs-srt-drop", "burn-subs-srt-input", files => {
    const f = files[0];
    if (!f || !f.name.toLowerCase().endsWith(".srt")) return;
    burnSubsSrtFile = f;
    document.getElementById("burn-subs-srt-name").textContent = f.name;
    document.getElementById("burn-subs-srt-size").textContent = formatSize(f.size);
    document.getElementById("burn-subs-srt-info").hidden = false;
    updateBurnSubsActions();
});

function clearBurnSubsVideo() {
    burnSubsVideoFile = null;
    document.getElementById("burn-subs-video-info").hidden = true;
    updateBurnSubsActions();
}

function clearBurnSubsSrt() {
    burnSubsSrtFile = null;
    document.getElementById("burn-subs-srt-info").hidden = true;
    updateBurnSubsActions();
}

function updateBurnSubsActions() {
    document.getElementById("burn-subs-actions").hidden = !(burnSubsVideoFile && burnSubsSrtFile);
}

async function doBurnSubs() {
    if (!burnSubsVideoFile || !burnSubsSrtFile) return;
    const btn = document.getElementById("burn-subs-btn");
    const err = document.getElementById("burn-subs-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Burning subtitles...";

    const fd = new FormData();
    fd.append("video", burnSubsVideoFile);
    fd.append("subtitles", burnSubsSrtFile);

    try {
        const res = await fetch("/api/av/burn-subtitles", { method: "POST", body: fd });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Processing failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
            const name = match ? match[1] : burnSubsVideoFile.name.replace(/\.[^.]+$/, "") + "_subtitled." + burnSubsVideoFile.name.split(".").pop();
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Burn Subtitles';
}

/* ── Voice Recorder ── */
let audioMediaRecorder = null;
let audioRecordChunks = [];
let audioRecordBlob = null;
let audioRecordStream = null;
let audioCtx = null;
let audioAnalyser = null;
let audioAnimFrame = null;
let audioTimerInterval = null;
let audioRecordStart = 0;

function startAudioRecording() {
    const err = document.getElementById("recorder-audio-error");
    err.hidden = true;
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
        audioRecordStream = stream;
        audioRecordChunks = [];

        // Set up waveform visualization
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioCtx.createMediaStreamSource(stream);
        audioAnalyser = audioCtx.createAnalyser();
        audioAnalyser.fftSize = 256;
        source.connect(audioAnalyser);
        drawAudioWaveform();

        audioMediaRecorder = new MediaRecorder(stream);
        audioMediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioRecordChunks.push(e.data); };
        audioMediaRecorder.onstop = () => {
            audioRecordBlob = new Blob(audioRecordChunks, { type: "audio/webm" });
            document.getElementById("recorder-audio-player").src = URL.createObjectURL(audioRecordBlob);
            document.getElementById("recorder-audio-result").hidden = false;
        };
        audioMediaRecorder.start();

        // UI state
        document.getElementById("recorder-audio-start").hidden = true;
        document.getElementById("recorder-audio-pause").hidden = false;
        document.getElementById("recorder-audio-stop").hidden = false;

        // Timer
        audioRecordStart = Date.now();
        audioTimerInterval = setInterval(updateAudioTimer, 200);
    }).catch(e => {
        err.textContent = "Microphone access denied: " + e.message;
        err.hidden = false;
    });
}

function pauseAudioRecording() {
    if (!audioMediaRecorder) return;
    const btn = document.getElementById("recorder-audio-pause");
    if (audioMediaRecorder.state === "recording") {
        audioMediaRecorder.pause();
        btn.textContent = "Resume";
    } else {
        audioMediaRecorder.resume();
        btn.textContent = "Pause";
    }
}

function stopAudioRecording() {
    if (audioMediaRecorder && audioMediaRecorder.state !== "inactive") {
        audioMediaRecorder.stop();
    }
    if (audioRecordStream) {
        audioRecordStream.getTracks().forEach(t => t.stop());
    }
    cancelAnimationFrame(audioAnimFrame);
    clearInterval(audioTimerInterval);
    if (audioCtx) audioCtx.close();
    document.getElementById("recorder-audio-pause").hidden = true;
    document.getElementById("recorder-audio-stop").hidden = true;
}

function resetAudioRecording() {
    document.getElementById("recorder-audio-result").hidden = true;
    document.getElementById("recorder-audio-start").hidden = false;
    document.getElementById("recorder-audio-timer").textContent = "00:00";
    // Clear waveform
    const canvas = document.getElementById("recorder-audio-waveform");
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    audioRecordBlob = null;
}

function updateAudioTimer() {
    const elapsed = Math.floor((Date.now() - audioRecordStart) / 1000);
    const min = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const sec = String(elapsed % 60).padStart(2, "0");
    document.getElementById("recorder-audio-timer").textContent = min + ":" + sec;
}

function drawAudioWaveform() {
    const canvas = document.getElementById("recorder-audio-waveform");
    const ctx = canvas.getContext("2d");
    const bufLen = audioAnalyser.frequencyBinCount;
    const data = new Uint8Array(bufLen);

    function draw() {
        audioAnimFrame = requestAnimationFrame(draw);
        audioAnalyser.getByteTimeDomainData(data);
        ctx.fillStyle = "#f7f6f5";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#4285f4";
        ctx.beginPath();
        const sliceWidth = canvas.width / bufLen;
        let x = 0;
        for (let i = 0; i < bufLen; i++) {
            const v = data[i] / 128.0;
            const y = v * canvas.height / 2;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            x += sliceWidth;
        }
        ctx.lineTo(canvas.width, canvas.height / 2);
        ctx.stroke();
    }
    draw();
}

async function downloadAudioRecording() {
    if (!audioRecordBlob) return;
    const fmt = document.getElementById("recorder-audio-format").value;
    if (fmt === "webm") {
        downloadBlob(audioRecordBlob, "recording.webm");
        showToast("Saved: recording.webm");
        return;
    }
    // Convert via backend
    const btn = document.getElementById("recorder-audio-download");
    btn.disabled = true;
    btn.textContent = "Converting...";
    const fd = new FormData();
    fd.append("file", audioRecordBlob, "recording.webm");
    fd.append("format", fmt);
    try {
        const res = await fetch("/api/av/convert-audio", { method: "POST", body: fd });
        if (!res.ok) {
            const data = await res.json();
            document.getElementById("recorder-audio-error").textContent = data.error || "Conversion failed";
            document.getElementById("recorder-audio-error").hidden = false;
        } else {
            const blob = await res.blob();
            downloadBlob(blob, "recording." + fmt);
            showToast("Saved: recording." + fmt);
        }
    } catch {
        document.getElementById("recorder-audio-error").textContent = "Conversion failed";
        document.getElementById("recorder-audio-error").hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Download Recording';
}

/* ── Screen Recorder ── */
let screenMediaRecorder = null;
let screenRecordChunks = [];
let screenRecordBlob = null;
let screenRecordStream = null;
let screenTimerInterval = null;
let screenRecordStart = 0;

async function startScreenRecording() {
    const err = document.getElementById("recorder-screen-error");
    err.hidden = true;
    const includeAudio = document.getElementById("recorder-screen-audio").checked;
    try {
        const displayStream = await navigator.mediaDevices.getDisplayMedia({
            video: true,
            audio: includeAudio,
        });
        screenRecordStream = displayStream;
        screenRecordChunks = [];

        screenMediaRecorder = new MediaRecorder(displayStream);
        screenMediaRecorder.ondataavailable = e => { if (e.data.size > 0) screenRecordChunks.push(e.data); };
        screenMediaRecorder.onstop = () => {
            screenRecordBlob = new Blob(screenRecordChunks, { type: "video/webm" });
            document.getElementById("recorder-screen-player").src = URL.createObjectURL(screenRecordBlob);
            document.getElementById("recorder-screen-result").hidden = false;
        };

        // Handle user stopping via browser UI (clicking "Stop sharing")
        displayStream.getVideoTracks()[0].onended = () => stopScreenRecording();

        screenMediaRecorder.start();

        document.getElementById("recorder-screen-start").hidden = true;
        document.getElementById("recorder-screen-stop").hidden = false;

        screenRecordStart = Date.now();
        screenTimerInterval = setInterval(updateScreenTimer, 200);
    } catch (e) {
        err.textContent = "Screen sharing denied or not supported: " + e.message;
        err.hidden = false;
    }
}

function stopScreenRecording() {
    if (screenMediaRecorder && screenMediaRecorder.state !== "inactive") {
        screenMediaRecorder.stop();
    }
    if (screenRecordStream) {
        screenRecordStream.getTracks().forEach(t => t.stop());
    }
    clearInterval(screenTimerInterval);
    document.getElementById("recorder-screen-stop").hidden = true;
}

function resetScreenRecording() {
    document.getElementById("recorder-screen-result").hidden = true;
    document.getElementById("recorder-screen-start").hidden = false;
    document.getElementById("recorder-screen-timer").textContent = "00:00";
    screenRecordBlob = null;
}

function updateScreenTimer() {
    const elapsed = Math.floor((Date.now() - screenRecordStart) / 1000);
    const min = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const sec = String(elapsed % 60).padStart(2, "0");
    document.getElementById("recorder-screen-timer").textContent = min + ":" + sec;
}

function downloadScreenRecording() {
    if (!screenRecordBlob) return;
    downloadBlob(screenRecordBlob, "screen-recording.webm");
    showToast("Saved: screen-recording.webm");
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
