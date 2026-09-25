/* ── State ── */
const avFiles = {};
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

/* ── Hash Routing ── */
showTab(location.hash.slice(1) || "av-convert-audio");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "av-convert-audio"));

setupPageDropOverlay();

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
        item.innerHTML = `<span class="file-name">${esc(f.name)}</span><span class="file-size">${formatSize(f.size)}</span><button class="file-remove" onclick="removeMergeAudio(${i})">&times;</button>`;
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

/* ── Two-file helper (video + companion file sections) ── */
function avPairLoad(prefix, slot, files, acceptType, update) {
    const f = files[0];
    if (!f) return;
    if (acceptType && !f.type.startsWith(acceptType) && !(acceptType === "image/" && /\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name))) return;
    avFiles[`${prefix}-${slot}`] = f;
    document.getElementById(`${prefix}-${slot}-name`).textContent = f.name;
    document.getElementById(`${prefix}-${slot}-size`).textContent = formatSize(f.size);
    document.getElementById(`${prefix}-${slot}-info`).hidden = false;
    update();
}

function avPairClear(prefix, slot, update) {
    avFiles[`${prefix}-${slot}`] = null;
    document.getElementById(`${prefix}-${slot}-info`).hidden = true;
    update();
}

function avPairUpdate(prefix, slots) {
    const ready = slots.every(s => avFiles[`${prefix}-${s}`]);
    const opts = document.getElementById(`${prefix}-options`);
    if (opts) opts.hidden = !ready;
    document.getElementById(`${prefix}-actions`).hidden = !ready;
}

/* Like avFetch but the FormData is built by the caller (multi-file sections). */
async function avFetchForm(prefix, endpoint, fd, fallbackName, loadingText) {
    const btn = document.getElementById(`${prefix}-btn`);
    const err = document.getElementById(`${prefix}-error`);
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = loadingText || "Processing...";
    try {
        const res = await fetch(endpoint, { method: "POST", body: fd });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Processing failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
            const name = match ? match[1] : fallbackName;
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

function avShowError(prefix, msg) {
    const err = document.getElementById(`${prefix}-error`);
    err.textContent = msg;
    err.hidden = false;
}

/* ── Remove Silence ── */
setupDropZone("silence-drop", "silence-input", files => loadAvFile("silence", files, "audio/"));

document.getElementById("silence-btn").dataset.label = "Remove Silence";

async function doRemoveSilence() {
    const threshold = document.getElementById("silence-threshold").value;
    const minSilence = document.getElementById("silence-min").value;
    await avFetch("silence", "/api/av/remove-silence",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("threshold_db", threshold); fd.append("min_silence", minSilence); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_nosilence." + file.name.split(".").pop(),
        "Removing silence..."
    );
}

/* ── Split Audio ── */
setupDropZone("split-audio-drop", "split-audio-input", files => loadAvFile("split-audio", files, "audio/"));

document.getElementById("split-audio-btn").dataset.label = "Split Audio";

function updateSplitAudioMode() {
    const mode = document.getElementById("split-audio-mode").value;
    const label = document.getElementById("split-audio-value-label");
    const input = document.getElementById("split-audio-value");
    if (mode === "count") { label.textContent = "Number of parts"; input.value = "2"; input.min = "2"; }
    else { label.textContent = "Seconds per part"; input.value = "60"; input.min = "1"; }
}

async function doSplitAudio() {
    const mode = document.getElementById("split-audio-mode").value;
    const value = parseFloat(document.getElementById("split-audio-value").value);
    if (!(value > 0) || (mode === "count" && value < 2)) {
        avShowError("split-audio", mode === "count" ? "Enter at least 2 parts" : "Enter a part length greater than 0");
        return;
    }
    await avFetch("split-audio", "/api/av/split-audio",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("mode", mode); fd.append("value", value); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_parts.zip",
        "Splitting..."
    );
}

/* ── Channels ── */
setupDropZone("channels-drop", "channels-input", files => loadAvFile("channels", files, "audio/"));

document.getElementById("channels-btn").dataset.label = "Convert Channels";

async function doChannels() {
    const mode = document.getElementById("channels-mode").value;
    await avFetch("channels", "/api/av/channels",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("mode", mode); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_" + mode + "." + file.name.split(".").pop(),
        "Converting..."
    );
}

/* ── Bitrate ── */
setupDropZone("bitrate-drop", "bitrate-input", files => loadAvFile("bitrate", files, "audio/"));

document.getElementById("bitrate-btn").dataset.label = "Change Bitrate";

async function doBitrate() {
    const bitrate = document.getElementById("bitrate-value").value;
    const fmt = document.getElementById("bitrate-format").value;
    await avFetch("bitrate", "/api/av/bitrate",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("bitrate", bitrate); fd.append("format", fmt); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_" + bitrate + "k." + (fmt === "keep" ? file.name.split(".").pop() : fmt),
        "Encoding..."
    );
}

/* ── Tag Editor ── */
const TAG_FIELDS = ["title", "artist", "album", "year", "genre", "track", "comment"];
let tagsCoverFile = null;

setupDropZone("tags-drop", "tags-input", files => {
    loadAvFile("tags", files, "audio/");
    if (avFiles["tags"]) readTags();
});

setupDropZone("tags-cover-drop", "tags-cover-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    tagsCoverFile = f;
    document.getElementById("tags-cover-name").textContent = f.name;
    document.getElementById("tags-cover-size").textContent = formatSize(f.size);
    document.getElementById("tags-cover-info").hidden = false;
});

document.getElementById("tags-btn").dataset.label = "Save Tags";

function clearTagsFile() {
    clearAvFile("tags");
    clearTagsCover();
    TAG_FIELDS.forEach(k => document.getElementById("tags-" + k).value = "");
}

function clearTagsCover() {
    tagsCoverFile = null;
    document.getElementById("tags-cover-info").hidden = true;
}

async function readTags() {
    const f = avFiles["tags"];
    if (!f) return;
    const err = document.getElementById("tags-error");
    err.hidden = true;
    TAG_FIELDS.forEach(k => document.getElementById("tags-" + k).value = "");
    const fd = new FormData();
    fd.append("file", f);
    try {
        const res = await fetch("/api/av/tags/read", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) {
            err.textContent = data.error || "Could not read tags";
            err.hidden = false;
            return;
        }
        TAG_FIELDS.forEach(k => document.getElementById("tags-" + k).value = data[k] || "");
        const hint = document.getElementById("tags-cover-hint");
        document.getElementById("tags-cover-wrap").hidden = !data.can_cover;
        hint.textContent = data.has_cover
            ? "this file already has cover art · drop a new image to replace it"
            : "optional · drop a JPG or PNG here to set the cover art";
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
}

async function doWriteTags() {
    const f = avFiles["tags"];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    TAG_FIELDS.forEach(k => fd.append(k, document.getElementById("tags-" + k).value.trim()));
    if (tagsCoverFile) fd.append("cover", tagsCoverFile);
    await avFetchForm("tags", "/api/av/tags/write", fd,
        f.name.replace(/\.[^.]+$/, "") + "_tagged." + f.name.split(".").pop(), "Saving...");
}

/* ── Audio to Video ── */
let audio2videoImageFile = null;

setupDropZone("audio2video-drop", "audio2video-input", files => loadAvFile("audio2video", files, "audio/"));

setupDropZone("audio2video-image-drop", "audio2video-image-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    audio2videoImageFile = f;
    document.getElementById("audio2video-image-name").textContent = f.name;
    document.getElementById("audio2video-image-size").textContent = formatSize(f.size);
    document.getElementById("audio2video-image-info").hidden = false;
});

document.getElementById("audio2video-btn").dataset.label = "Create Video";

function clearAudio2VideoImage() {
    audio2videoImageFile = null;
    document.getElementById("audio2video-image-info").hidden = true;
}

function updateAudio2VideoStyle() {
    const style = document.getElementById("audio2video-style").value;
    document.getElementById("audio2video-image-wrap").hidden = style !== "image";
    document.getElementById("audio2video-color-field").hidden = style === "image";
}

async function doAudio2Video() {
    const style = document.getElementById("audio2video-style").value;
    if (style === "image" && !audio2videoImageFile) {
        avShowError("audio2video", "Select an image for the still image style");
        return;
    }
    const color = document.getElementById("audio2video-color").value;
    const background = document.getElementById("audio2video-background").value;
    const resolution = document.getElementById("audio2video-resolution").value;
    await avFetch("audio2video", "/api/av/audio-to-video",
        file => {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("style", style);
            fd.append("color", color);
            fd.append("background", background);
            fd.append("resolution", resolution);
            if (style === "image") fd.append("image", audio2videoImageFile);
            return fd;
        },
        file => file.name.replace(/\.[^.]+$/, "") + "_video.mp4",
        "Rendering video..."
    );
}

/* ── Merge Clips ── */
let mergeVideoFiles = [];

setupDropZone("merge-video-drop", "merge-video-input", files => {
    for (const f of files) {
        if (f.type.startsWith("video/") || /\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(f.name)) {
            mergeVideoFiles.push(f);
        }
    }
    renderMergeVideoList();
});

function renderMergeVideoList() {
    const list = document.getElementById("merge-video-list");
    list.innerHTML = "";
    mergeVideoFiles.forEach((f, i) => {
        const item = document.createElement("div");
        item.className = "file-item";
        item.innerHTML = `<span class="file-name">${esc(f.name)}</span><span class="file-size">${formatSize(f.size)}</span><button class="file-remove" onclick="removeMergeVideo(${i})">&times;</button>`;
        list.appendChild(item);
    });
    const show = mergeVideoFiles.length >= 2;
    document.getElementById("merge-video-options").hidden = !show;
    document.getElementById("merge-video-actions").hidden = !show;
}

function removeMergeVideo(i) {
    mergeVideoFiles.splice(i, 1);
    renderMergeVideoList();
}

document.getElementById("merge-video-btn").dataset.label = "Merge Clips";

async function doMergeVideo() {
    if (mergeVideoFiles.length < 2) return;
    const fd = new FormData();
    mergeVideoFiles.forEach(f => fd.append("files", f));
    fd.append("resolution", document.getElementById("merge-video-resolution").value);
    await avFetchForm("merge-video", "/api/av/merge-video", fd, "merged.mp4", "Merging clips...");
}

/* ── Watermark / Logo ── */
const updateVideoWatermark = () => avPairUpdate("video-watermark", ["video", "image"]);
setupDropZone("video-watermark-video-drop", "video-watermark-video-input", files => avPairLoad("video-watermark", "video", files, "video/", updateVideoWatermark));
setupDropZone("video-watermark-image-drop", "video-watermark-image-input", files => avPairLoad("video-watermark", "image", files, "image/", updateVideoWatermark));
function clearVideoWatermarkVideo() { avPairClear("video-watermark", "video", updateVideoWatermark); }
function clearVideoWatermarkImage() { avPairClear("video-watermark", "image", updateVideoWatermark); }

document.getElementById("video-watermark-btn").dataset.label = "Add Watermark";

async function doVideoWatermark() {
    const video = avFiles["video-watermark-video"], image = avFiles["video-watermark-image"];
    if (!video || !image) return;
    const fd = new FormData();
    fd.append("video", video);
    fd.append("image", image);
    fd.append("position", document.getElementById("video-watermark-position").value);
    fd.append("scale", document.getElementById("video-watermark-scale").value);
    fd.append("opacity", document.getElementById("video-watermark-opacity").value);
    fd.append("margin", document.getElementById("video-watermark-margin").value);
    await avFetchForm("video-watermark", "/api/av/video-watermark", fd,
        video.name.replace(/\.[^.]+$/, "") + "_watermarked." + video.name.split(".").pop(), "Adding watermark...");
}

/* ── Extract Frames ── */
setupDropZone("frames-drop", "frames-input", files => loadAvFile("frames", files, "video/"));

document.getElementById("frames-btn").dataset.label = "Extract Frames";

function updateFramesMode() {
    const mode = document.getElementById("frames-mode").value;
    document.getElementById("frames-time-field").hidden = mode !== "single";
    document.getElementById("frames-interval-field").hidden = mode !== "interval";
    document.getElementById("frames-count-field").hidden = mode !== "count";
}

async function doFrames() {
    const mode = document.getElementById("frames-mode").value;
    const fmt = document.getElementById("frames-format").value;
    const time = document.getElementById("frames-time").value;
    const interval = document.getElementById("frames-interval").value;
    const count = document.getElementById("frames-count").value;
    if (mode === "interval" && !(parseFloat(interval) > 0)) { avShowError("frames", "Interval must be greater than 0"); return; }
    if (mode === "count" && !(parseInt(count) >= 1)) { avShowError("frames", "Enter how many frames to extract"); return; }
    await avFetch("frames", "/api/av/frames",
        file => {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("mode", mode);
            fd.append("format", fmt);
            fd.append("time", time || "0");
            fd.append("interval", interval || "1");
            fd.append("count", count || "10");
            return fd;
        },
        file => { const base = file.name.replace(/\.[^.]+$/, ""); return mode === "single" ? `${base}_frame.${fmt}` : `${base}_frames.zip`; },
        "Extracting..."
    );
}

/* ── Change Video Speed ── */
setupDropZone("video-speed-drop", "video-speed-input", files => loadAvFile("video-speed", files, "video/"));

document.getElementById("video-speed-btn").dataset.label = "Change Speed";

async function doVideoSpeed() {
    const speed = parseFloat(document.getElementById("video-speed-value").value);
    if (!(speed >= 0.25 && speed <= 4)) { avShowError("video-speed", "Speed must be between 0.25 and 4"); return; }
    const keepPitch = document.getElementById("video-speed-pitch").checked;
    await avFetch("video-speed", "/api/av/video-speed",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("speed", speed); fd.append("keep_pitch", keepPitch); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_" + speed + "x." + file.name.split(".").pop(),
        "Changing speed..."
    );
}

/* ── Stabilize ── */
setupDropZone("stabilize-drop", "stabilize-input", files => loadAvFile("stabilize", files, "video/"));

document.getElementById("stabilize-btn").dataset.label = "Stabilize Video";

async function doStabilize() {
    const strength = document.getElementById("stabilize-strength").value;
    await avFetch("stabilize", "/api/av/stabilize",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("strength", strength); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "_stabilized." + file.name.split(".").pop(),
        "Stabilizing..."
    );
}

/* ── GIF to Video ── */
setupDropZone("gif2video-drop", "gif2video-input", files => {
    const f = files[0];
    if (!f) return;
    if (f.type !== "image/gif" && !/\.gif$/i.test(f.name)) return;
    loadAvFile("gif2video", files);
});

document.getElementById("gif2video-btn").dataset.label = "Convert GIF";

async function doGif2Video() {
    const fmt = document.getElementById("gif2video-format").value;
    const loop = document.getElementById("gif2video-loop").value;
    await avFetch("gif2video", "/api/av/gif-to-video",
        file => { const fd = new FormData(); fd.append("file", file); fd.append("format", fmt); fd.append("loop_count", loop || "1"); return fd; },
        file => file.name.replace(/\.[^.]+$/, "") + "." + fmt,
        "Converting..."
    );
}

/* ── Video Info ── */
let videoInfoData = null;

setupDropZone("video-info-drop", "video-info-input", files => {
    const f = files[0];
    if (!f) return;
    if (!f.type.startsWith("video/") && !f.type.startsWith("audio/") && !/\.(mp4|mov|webm|mkv|avi|m4v|mp3|wav|ogg|flac|aac|m4a|opus|wma|ts|mts|3gp)$/i.test(f.name)) return;
    loadAvFile("video-info", files);
    fetchVideoInfo();
});

function clearVideoInfo() {
    clearAvFile("video-info");
    videoInfoData = null;
    document.getElementById("video-info-result").hidden = true;
}

function fmtDuration(s) {
    if (!s && s !== 0) return "unknown";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = (s % 60).toFixed(2);
    return (h ? h + ":" : "") + String(m).padStart(h ? 2 : 1, "0") + ":" + String(sec).padStart(5, "0") + ` (${s.toFixed(2)} s)`;
}

function fmtBitrate(b) { return b ? (b >= 1000000 ? (b / 1000000).toFixed(2) + " Mb/s" : Math.round(b / 1000) + " kb/s") : "unknown"; }

function infoRows(table, rows) {
    table.innerHTML = "";
    rows.forEach(([k, v, head]) => {
        const tr = document.createElement("tr");
        if (head) tr.className = "info-stream-head";
        const td1 = document.createElement("td"), td2 = document.createElement("td");
        td1.textContent = k;
        td2.textContent = v == null || v === "" ? "—" : v;
        tr.appendChild(td1); tr.appendChild(td2);
        table.appendChild(tr);
    });
}

async function fetchVideoInfo() {
    const f = avFiles["video-info"];
    if (!f) return;
    const err = document.getElementById("video-info-error");
    const status = document.getElementById("video-info-status");
    err.hidden = true;
    status.hidden = false;
    document.getElementById("video-info-result").hidden = true;
    document.getElementById("video-info-actions").hidden = true;
    const fd = new FormData();
    fd.append("file", f);
    try {
        const res = await fetch("/api/av/info", { method: "POST", body: fd });
        const data = await res.json();
        status.hidden = true;
        if (!res.ok) {
            err.textContent = data.error || "Could not read file";
            err.hidden = false;
            return;
        }
        videoInfoData = data;
        const v = data.video, a = data.audio;
        const rows = [
            ["File", data.filename],
            ["Container", data.container],
            ["Duration", fmtDuration(data.duration)],
            ["Size", formatSize(data.size)],
            ["Bitrate", fmtBitrate(data.bitrate)],
        ];
        if (v) {
            rows.push(["Video codec", v.codec_long || v.codec]);
            rows.push(["Resolution", v.width && v.height ? `${v.width} x ${v.height}` : null]);
            rows.push(["Frame rate", v.fps ? `${v.fps} fps` : null]);
            rows.push(["Pixel format", v.pix_fmt]);
        }
        if (a) {
            rows.push(["Audio codec", a.codec_long || a.codec]);
            rows.push(["Sample rate", a.sample_rate ? `${a.sample_rate} Hz` : null]);
            rows.push(["Channels", a.channels ? `${a.channels} (${a.channel_layout || ""})` : a.channel_layout]);
            rows.push(["Audio bitrate", a.bitrate ? fmtBitrate(a.bitrate) : null]);
        }
        const tags = Object.entries(data.tags || {}).filter(([k]) => !/^(major_brand|minor_version|compatible_brands|encoder|handler_name|vendor_id)$/.test(k));
        tags.slice(0, 12).forEach(([k, val]) => rows.push([k, val]));
        infoRows(document.getElementById("video-info-table"), rows);

        const srows = [];
        (data.streams || []).forEach(s => {
            srows.push([`#${s.index} ${s.type}`, s.codec_long || s.codec, true]);
            if (s.type === "video") {
                srows.push(["Resolution", s.width && s.height ? `${s.width} x ${s.height}` : null]);
                srows.push(["Frame rate", s.fps ? `${s.fps} fps` : null]);
                if (s.attached_pic) srows.push(["Role", "cover art"]);
            } else if (s.type === "audio") {
                srows.push(["Sample rate", s.sample_rate ? `${s.sample_rate} Hz` : null]);
                srows.push(["Channels", s.channel_layout || s.channels]);
            }
            if (s.bitrate) srows.push(["Bitrate", fmtBitrate(s.bitrate)]);
        });
        infoRows(document.getElementById("video-info-streams"), srows);
        document.getElementById("video-info-result").hidden = false;
        document.getElementById("video-info-actions").hidden = false;
    } catch {
        status.hidden = true;
        err.textContent = "Network error";
        err.hidden = false;
    }
}

async function copyVideoInfoJson() {
    if (!videoInfoData) return;
    try {
        await navigator.clipboard.writeText(JSON.stringify(videoInfoData, null, 2));
        showToast("Copied JSON to clipboard");
    } catch {
        avShowError("video-info", "Could not access the clipboard");
    }
}

/* ── Picture-in-Picture ── */
const updatePip = () => avPairUpdate("pip", ["main", "overlay"]);
setupDropZone("pip-main-drop", "pip-main-input", files => avPairLoad("pip", "main", files, "video/", updatePip));
setupDropZone("pip-overlay-drop", "pip-overlay-input", files => avPairLoad("pip", "overlay", files, "video/", updatePip));
function clearPipMain() { avPairClear("pip", "main", updatePip); }
function clearPipOverlay() { avPairClear("pip", "overlay", updatePip); }

document.getElementById("pip-btn").dataset.label = "Create PiP Video";

async function doPip() {
    const main = avFiles["pip-main"], overlay = avFiles["pip-overlay"];
    if (!main || !overlay) return;
    const fd = new FormData();
    fd.append("main", main);
    fd.append("overlay", overlay);
    fd.append("position", document.getElementById("pip-position").value);
    fd.append("scale", document.getElementById("pip-scale").value);
    fd.append("margin", document.getElementById("pip-margin").value);
    await avFetchForm("pip", "/api/av/pip", fd, main.name.replace(/\.[^.]+$/, "") + "_pip.mp4", "Compositing...");
}

/* ── Webcam ── */
let webcamStream = null;
let webcamRecorder = null;
let webcamChunks = [];
let webcamBlob = null;
let webcamTimerInterval = null;
let webcamRecordStart = 0;

function webcamErrorMessage(e) {
    if (e && (e.name === "NotAllowedError" || e.name === "SecurityError")) {
        return "Camera access was denied. Allow camera (and microphone) access for this site in your browser settings, then try again.";
    }
    if (e && (e.name === "NotFoundError" || e.name === "OverconstrainedError")) {
        return "No camera was found on this device.";
    }
    if (e && e.name === "NotReadableError") {
        return "The camera is in use by another application.";
    }
    return "Could not start the camera: " + ((e && e.message) || "not supported in this browser");
}

async function startWebcam() {
    const err = document.getElementById("webcam-error");
    err.hidden = true;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        err.textContent = "Camera capture is not supported in this browser.";
        err.hidden = false;
        return;
    }
    const wantAudio = document.getElementById("webcam-audio").checked;
    try {
        try {
            webcamStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: wantAudio });
        } catch (e) {
            // A missing or blocked microphone should not stop the camera.
            if (!wantAudio || e.name === "NotAllowedError") throw e;
            webcamStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
            showToast("Microphone unavailable; recording without audio");
        }
        const preview = document.getElementById("webcam-preview");
        preview.srcObject = webcamStream;
        preview.hidden = false;
        document.getElementById("webcam-start").hidden = true;
        document.getElementById("webcam-photo").hidden = false;
        document.getElementById("webcam-record").hidden = false;
        document.getElementById("webcam-off").hidden = false;
        webcamStream.getVideoTracks()[0].onended = () => stopWebcam();
    } catch (e) {
        err.textContent = webcamErrorMessage(e);
        err.hidden = false;
    }
}

function stopWebcam() {
    if (webcamRecorder && webcamRecorder.state !== "inactive") stopWebcamRecording();
    if (webcamStream) {
        webcamStream.getTracks().forEach(t => t.stop());
        webcamStream = null;
    }
    const preview = document.getElementById("webcam-preview");
    preview.srcObject = null;
    preview.hidden = true;
    document.getElementById("webcam-start").hidden = false;
    document.getElementById("webcam-photo").hidden = true;
    document.getElementById("webcam-record").hidden = true;
    document.getElementById("webcam-stop").hidden = true;
    document.getElementById("webcam-off").hidden = true;
}

function takeWebcamPhoto() {
    const preview = document.getElementById("webcam-preview");
    if (!webcamStream || !preview.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = preview.videoWidth;
    canvas.height = preview.videoHeight;
    canvas.getContext("2d").drawImage(preview, 0, 0);
    canvas.toBlob(blob => {
        if (!blob) return;
        const name = "webcam-photo-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".png";
        downloadBlob(blob, name);
        showToast("Saved: " + name);
    }, "image/png");
}

function startWebcamRecording() {
    if (!webcamStream) return;
    const err = document.getElementById("webcam-error");
    err.hidden = true;
    if (typeof MediaRecorder === "undefined") {
        err.textContent = "Video recording is not supported in this browser.";
        err.hidden = false;
        return;
    }
    webcamChunks = [];
    document.getElementById("webcam-result").hidden = true;
    try {
        const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find(m => MediaRecorder.isTypeSupported(m));
        webcamRecorder = mime ? new MediaRecorder(webcamStream, { mimeType: mime }) : new MediaRecorder(webcamStream);
    } catch (e) {
        err.textContent = "Could not start recording: " + e.message;
        err.hidden = false;
        return;
    }
    webcamRecorder.ondataavailable = e => { if (e.data.size > 0) webcamChunks.push(e.data); };
    webcamRecorder.onstop = () => {
        webcamBlob = new Blob(webcamChunks, { type: "video/webm" });
        document.getElementById("webcam-player").src = URL.createObjectURL(webcamBlob);
        document.getElementById("webcam-result").hidden = false;
    };
    webcamRecorder.start();
    document.getElementById("webcam-record").hidden = true;
    document.getElementById("webcam-photo").hidden = true;
    document.getElementById("webcam-off").hidden = true;
    document.getElementById("webcam-stop").hidden = false;
    webcamRecordStart = Date.now();
    document.getElementById("webcam-timer").textContent = "00:00";
    webcamTimerInterval = setInterval(updateWebcamTimer, 200);
}

function stopWebcamRecording() {
    if (webcamRecorder && webcamRecorder.state !== "inactive") webcamRecorder.stop();
    clearInterval(webcamTimerInterval);
    document.getElementById("webcam-stop").hidden = true;
    if (webcamStream) {
        document.getElementById("webcam-record").hidden = false;
        document.getElementById("webcam-photo").hidden = false;
        document.getElementById("webcam-off").hidden = false;
    }
}

function updateWebcamTimer() {
    const elapsed = Math.floor((Date.now() - webcamRecordStart) / 1000);
    const min = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const sec = String(elapsed % 60).padStart(2, "0");
    document.getElementById("webcam-timer").textContent = min + ":" + sec;
}

function resetWebcamRecording() {
    document.getElementById("webcam-result").hidden = true;
    document.getElementById("webcam-timer").textContent = "00:00";
    webcamBlob = null;
}

function downloadWebcamRecording() {
    if (!webcamBlob) return;
    const name = "webcam-recording-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".webm";
    downloadBlob(webcamBlob, name);
    showToast("Saved: " + name);
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
