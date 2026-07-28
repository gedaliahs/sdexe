/* transcribe.js: upload a media file, stream progress, render and export the
   transcript. Talks to /api/transcribe, /api/transcribe/progress/<id>, and
   /api/transcribe/export. */

let transcribeFile = null;
let transcribeSegments = [];
let transcribeSource = null;

function esc(s) {
    return String(s).replace(/[&<>"']/g, c => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
}

function fmtSize(bytes) {
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB";
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
    if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
    return bytes + " B";
}

function fmtTime(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const mm = h ? String(m).padStart(2, "0") : String(m);
    return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0");
}

function showTranscribeError(msg) {
    const el = document.getElementById("transcribe-error");
    el.textContent = msg;
    el.hidden = false;
}

function hideTranscribeError() {
    document.getElementById("transcribe-error").hidden = true;
}

/* ── File selection ── */
function handleTranscribeFiles(files) {
    if (!files || !files.length) return;
    hideTranscribeError();
    transcribeFile = files[0];
    document.getElementById("transcribe-file-name").textContent = transcribeFile.name;
    document.getElementById("transcribe-file-size").textContent = fmtSize(transcribeFile.size);
    document.getElementById("transcribe-file-info").hidden = false;
    document.getElementById("transcribe-options").hidden = false;
    document.getElementById("transcribe-results").hidden = true;
    document.getElementById("transcribe-progress").hidden = true;
    transcribeSegments = [];
}

function clearTranscribeFile() {
    transcribeFile = null;
    transcribeSegments = [];
    document.getElementById("transcribe-file-info").hidden = true;
    document.getElementById("transcribe-options").hidden = true;
    document.getElementById("transcribe-progress").hidden = true;
    document.getElementById("transcribe-results").hidden = true;
    hideTranscribeError();
}

/* ── Transcription ── */
async function startTranscription() {
    if (!transcribeFile) { showTranscribeError("Select a file first."); return; }
    hideTranscribeError();

    const btn = document.getElementById("transcribe-btn");
    btn.disabled = true;

    const diarizeEl = document.getElementById("transcribe-diarize");
    const tokenEl = document.getElementById("transcribe-hf-token");
    const speakersEl = document.getElementById("transcribe-num-speakers");

    const form = new FormData();
    form.append("file", transcribeFile);
    form.append("model", document.getElementById("transcribe-model").value);
    form.append("language", document.getElementById("transcribe-language").value);
    form.append("diarize", diarizeEl && diarizeEl.checked ? "true" : "false");
    if (tokenEl && tokenEl.value.trim()) form.append("hf_token", tokenEl.value.trim());
    if (speakersEl && speakersEl.value.trim()) form.append("num_speakers", speakersEl.value.trim());

    const panel = document.getElementById("transcribe-progress");
    const fill = document.getElementById("transcribe-progress-fill");
    const statusEl = document.getElementById("transcribe-progress-status");
    const pctEl = document.getElementById("transcribe-progress-pct");
    const detailEl = document.getElementById("transcribe-progress-detail");
    panel.hidden = false;
    fill.style.width = "0%";
    statusEl.textContent = "Uploading...";
    pctEl.textContent = "";
    detailEl.textContent = "";
    document.getElementById("transcribe-results").hidden = true;

    let id;
    try {
        const res = await fetch("/api/transcribe", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok || data.error) {
            panel.hidden = true;
            btn.disabled = false;
            showTranscribeError(data.error || "Could not start transcription.");
            return;
        }
        id = data.id;
    } catch {
        panel.hidden = true;
        btn.disabled = false;
        showTranscribeError("Could not reach the app. Is it still running?");
        return;
    }

    if (transcribeSource) transcribeSource.close();
    const source = new EventSource(`/api/transcribe/progress/${encodeURIComponent(id)}`);
    transcribeSource = source;

    const finish = () => {
        source.close();
        if (transcribeSource === source) transcribeSource = null;
        btn.disabled = false;
    };

    source.onmessage = (ev) => {
        let d;
        try { d = JSON.parse(ev.data); } catch { return; }

        if (d.error && !d.status) {
            panel.hidden = true;
            showTranscribeError(d.error);
            finish();
            return;
        }

        const pct = Math.max(0, Math.min(100, d.progress || 0));
        fill.style.width = pct + "%";
        pctEl.textContent = pct + "%";
        statusEl.textContent = (d.status || "").replace(/_/g, " ") || "Working";
        detailEl.textContent = d.detail || "";

        if (d.status === "error") {
            panel.hidden = true;
            showTranscribeError(d.error || "Transcription failed.");
            finish();
        } else if (d.status === "done") {
            panel.hidden = true;
            transcribeSegments = d.segments || [];
            renderTranscript(d.language);
            finish();
        }
    };

    source.onerror = () => {
        panel.hidden = true;
        showTranscribeError("Lost connection while transcribing.");
        finish();
    };
}

/* ── Results ── */
function renderTranscript(language) {
    const wrap = document.getElementById("transcribe-results");
    const list = document.getElementById("transcript-segments");
    const langBadge = document.getElementById("transcribe-lang-badge");
    const countBadge = document.getElementById("transcribe-seg-count");

    if (!transcribeSegments.length) {
        showTranscribeError("No speech was found in that file.");
        return;
    }

    langBadge.textContent = language ? `Language: ${language}` : "";
    langBadge.hidden = !language;
    countBadge.textContent = `${transcribeSegments.length} segment${transcribeSegments.length === 1 ? "" : "s"}`;

    list.innerHTML = transcribeSegments.map((seg, i) => `
        <div class="transcript-segment" data-index="${i}">
            <div class="transcript-segment-meta">
                <span class="transcript-time">${fmtTime(seg.start)}</span>
                ${seg.speaker ? `<span class="transcript-speaker">${esc(seg.speaker)}</span>` : ""}
            </div>
            <p class="transcript-text">${esc(seg.text || "")}</p>
        </div>
    `).join("");

    wrap.hidden = false;
    const search = document.getElementById("transcript-search-input");
    if (search) { search.value = ""; searchTranscript(); }
}

function searchTranscript() {
    const input = document.getElementById("transcript-search-input");
    const countEl = document.getElementById("transcript-search-count");
    const query = (input.value || "").trim().toLowerCase();
    const rows = document.querySelectorAll("#transcript-segments .transcript-segment");

    if (!query) {
        rows.forEach(r => { r.hidden = false; r.classList.remove("is-hit"); });
        countEl.textContent = "";
        return;
    }

    let hits = 0;
    rows.forEach(row => {
        const text = (transcribeSegments[Number(row.dataset.index)] || {}).text || "";
        const match = text.toLowerCase().includes(query);
        row.hidden = !match;
        row.classList.toggle("is-hit", match);
        if (match) hits++;
    });
    countEl.textContent = `${hits} match${hits === 1 ? "" : "es"}`;
}

async function copyTranscript() {
    if (!transcribeSegments.length) return;
    const text = transcribeSegments
        .map(s => (s.speaker ? `[${s.speaker}] ` : "") + (s.text || ""))
        .join("\n");
    try {
        await navigator.clipboard.writeText(text);
        showToast("Transcript copied");
    } catch {
        showTranscribeError("Could not copy to the clipboard.");
    }
}

async function exportTranscript() {
    if (!transcribeSegments.length) return;
    const fmt = document.getElementById("transcript-export-format").value;
    try {
        const res = await fetch("/api/transcribe/export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ segments: transcribeSegments, format: fmt, include_speakers: true }),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showTranscribeError(data.error || "Export failed.");
            return;
        }
        const blob = await res.blob();
        const cd = res.headers.get("Content-Disposition") || "";
        const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
        const name = match ? match[1] : `transcript.${fmt}`;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch {
        showTranscribeError("Export failed.");
    }
}

/* ── Init ── */
document.addEventListener("DOMContentLoaded", () => {
    setupDropZone("transcribe-drop", "transcribe-input", handleTranscribeFiles);
    setupPageDropOverlay();

    const diarize = document.getElementById("transcribe-diarize");
    if (diarize) {
        diarize.addEventListener("change", () => {
            document.getElementById("transcribe-diarize-options").hidden = !diarize.checked;
        });
    }
});
