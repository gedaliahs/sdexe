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
