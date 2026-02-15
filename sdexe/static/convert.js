/* ── State ── */
let mdFile = null;
let csvFile = null;
let jsonFile = null;

/* ── Tab Switching ── */
document.querySelectorAll(".pdf-tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".pdf-tab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".pdf-section").forEach(s => s.classList.remove("active"));
        tab.classList.add("active");
        document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
    });
});

/* ── Drop Zone Setup ── */
function setupDropZone(zoneId, inputId, handler) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);

    zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", e => {
        e.preventDefault();
        zone.classList.remove("drag-over");
        handler(e.dataTransfer.files);
    });
    input.addEventListener("change", () => {
        handler(input.files);
        input.value = "";
    });
}

/* ── Markdown to HTML ── */
setupDropZone("md-drop", "md-input", files => {
    const f = files[0];
    if (!f) return;
    mdFile = f;

    document.getElementById("md-file-name").textContent = f.name;
    document.getElementById("md-file-size").textContent = formatSize(f.size);
    document.getElementById("md-file-info").hidden = false;

    // Read file content into textarea
    const reader = new FileReader();
    reader.onload = e => {
        document.getElementById("md-text").value = e.target.result;
    };
    reader.readAsText(f);
});

function clearMdFile() {
    mdFile = null;
    document.getElementById("md-file-info").hidden = true;
}

async function doMdToHtml() {
    const btn = document.getElementById("md-btn");
    const err = document.getElementById("md-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    const text = document.getElementById("md-text").value.trim();

    if (mdFile) {
        form.append("file", mdFile);
    } else if (text) {
        form.append("text", text);
    } else {
        err.textContent = "Upload a file or paste markdown text";
        err.hidden = false;
        btn.disabled = false;
        btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to HTML`;
        return;
    }

    try {
        const res = await fetch("/api/convert/md-to-html", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            downloadBlob(blob, "converted.html");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to HTML`;
}

/* ── CSV to JSON ── */
setupDropZone("csv-drop", "csv-input", files => {
    const f = files[0];
    if (!f) return;
    csvFile = f;

    document.getElementById("csv-file-name").textContent = f.name;
    document.getElementById("csv-file-size").textContent = formatSize(f.size);
    document.getElementById("csv-file-info").hidden = false;
    document.getElementById("csv-actions").hidden = false;
});

function clearCsvFile() {
    csvFile = null;
    document.getElementById("csv-file-info").hidden = true;
    document.getElementById("csv-actions").hidden = true;
}

async function doCsvToJson() {
    if (!csvFile) return;
    const btn = document.getElementById("csv-btn");
    const err = document.getElementById("csv-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    form.append("file", csvFile);

    try {
        const res = await fetch("/api/convert/csv-to-json", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = csvFile.name.replace(/\.csv$/i, "");
            downloadBlob(blob, base + ".json");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to JSON`;
}

/* ── JSON to CSV ── */
setupDropZone("json-drop", "json-input", files => {
    const f = files[0];
    if (!f) return;
    jsonFile = f;

    document.getElementById("json-file-name").textContent = f.name;
    document.getElementById("json-file-size").textContent = formatSize(f.size);
    document.getElementById("json-file-info").hidden = false;
    document.getElementById("json-actions").hidden = false;
});

function clearJsonFile() {
    jsonFile = null;
    document.getElementById("json-file-info").hidden = true;
    document.getElementById("json-actions").hidden = true;
}

async function doJsonToCsv() {
    if (!jsonFile) return;
    const btn = document.getElementById("json-btn");
    const err = document.getElementById("json-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    form.append("file", jsonFile);

    try {
        const res = await fetch("/api/convert/json-to-csv", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = jsonFile.name.replace(/\.json$/i, "");
            downloadBlob(blob, base + ".csv");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to CSV`;
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
