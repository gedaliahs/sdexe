/* ── State ── */
let mdFile = null;
let csvFile = null;
let jsonFile = null;
let yamlFile = null;
let json2yamlFile = null;
let csv2tsvFile = null;
let tsv2csvFile = null;
let xmlFile = null;
let createZipFiles = [];
let extractZipFile = null;

/* ── Hash Routing ── */
function showTab(tab) {
    document.querySelectorAll(".pdf-section").forEach(s => s.classList.remove("active"));
    const el = document.getElementById("tab-" + tab);
    (el || document.querySelector(".pdf-section")).classList.add("active");
}
showTab(location.hash.slice(1) || "md2html");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "md2html"));

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

/* ── Subtab switching ── */
document.querySelectorAll("[data-subtab]").forEach(btn => {
    btn.addEventListener("click", () => {
        const parent = btn.closest(".card-body");
        parent.querySelectorAll("[data-subtab]").forEach(b => b.classList.remove("active"));
        parent.querySelectorAll(".pdf-subsection").forEach(s => { s.hidden = true; s.classList.remove("active"); });
        btn.classList.add("active");
        const sec = document.getElementById("subtab-" + btn.dataset.subtab);
        if (sec) { sec.hidden = false; sec.classList.add("active"); }
    });
});

/* ── Markdown Preview ── */
async function doMdPreview() {
    const text = document.getElementById("md-text").value.trim();
    const previewEl = document.getElementById("md-preview");
    const btn = document.getElementById("md-preview-btn");
    if (!text) { previewEl.hidden = true; return; }

    btn.disabled = true;
    btn.textContent = "Previewing...";
    const form = new FormData();
    form.append("text", text);
    try {
        const res = await fetch("/api/convert/md-preview", { method: "POST", body: form });
        const data = await res.json();
        if (data.html) {
            previewEl.innerHTML = data.html;
            previewEl.hidden = false;
        }
    } catch {}
    btn.disabled = false;
    btn.textContent = "Preview";
}

/* ── YAML to JSON ── */
setupDropZone("yaml-drop", "yaml-input", files => {
    const f = files[0];
    if (!f) return;
    yamlFile = f;
    document.getElementById("yaml-file-name").textContent = f.name;
    document.getElementById("yaml-file-size").textContent = formatSize(f.size);
    document.getElementById("yaml-file-info").hidden = false;
    document.getElementById("yaml-actions").hidden = false;
});

function clearYamlFile() {
    yamlFile = null;
    document.getElementById("yaml-file-info").hidden = true;
    document.getElementById("yaml-actions").hidden = true;
}

async function doYamlToJson() {
    if (!yamlFile) return;
    await simpleConvert("yaml-btn", "yaml-error", "/api/convert/yaml-to-json", yamlFile, f => f.name.replace(/\.(yaml|yml)$/i, ".json"), "Convert to JSON");
}

/* ── JSON to YAML ── */
setupDropZone("json2yaml-drop", "json2yaml-input", files => {
    const f = files[0];
    if (!f) return;
    json2yamlFile = f;
    document.getElementById("json2yaml-file-name").textContent = f.name;
    document.getElementById("json2yaml-file-size").textContent = formatSize(f.size);
    document.getElementById("json2yaml-file-info").hidden = false;
    document.getElementById("json2yaml-actions").hidden = false;
});

function clearJson2YamlFile() {
    json2yamlFile = null;
    document.getElementById("json2yaml-file-info").hidden = true;
    document.getElementById("json2yaml-actions").hidden = true;
}

async function doJsonToYaml() {
    if (!json2yamlFile) return;
    await simpleConvert("json2yaml-btn", "json2yaml-error", "/api/convert/json-to-yaml", json2yamlFile, f => f.name.replace(/\.json$/i, ".yaml"), "Convert to YAML");
}

/* ── CSV to TSV ── */
setupDropZone("csv2tsv-drop", "csv2tsv-input", files => {
    const f = files[0];
    if (!f) return;
    csv2tsvFile = f;
    document.getElementById("csv2tsv-file-name").textContent = f.name;
    document.getElementById("csv2tsv-file-size").textContent = formatSize(f.size);
    document.getElementById("csv2tsv-file-info").hidden = false;
    document.getElementById("csv2tsv-actions").hidden = false;
});

function clearCsv2TsvFile() {
    csv2tsvFile = null;
    document.getElementById("csv2tsv-file-info").hidden = true;
    document.getElementById("csv2tsv-actions").hidden = true;
}

async function doCsvToTsv() {
    if (!csv2tsvFile) return;
    await simpleConvert("csv2tsv-btn", "csv2tsv-error", "/api/convert/csv-to-tsv", csv2tsvFile, f => f.name.replace(/\.csv$/i, ".tsv"), "Convert to TSV");
}

/* ── TSV to CSV ── */
setupDropZone("tsv2csv-drop", "tsv2csv-input", files => {
    const f = files[0];
    if (!f) return;
    tsv2csvFile = f;
    document.getElementById("tsv2csv-file-name").textContent = f.name;
    document.getElementById("tsv2csv-file-size").textContent = formatSize(f.size);
    document.getElementById("tsv2csv-file-info").hidden = false;
    document.getElementById("tsv2csv-actions").hidden = false;
});

function clearTsv2CsvFile() {
    tsv2csvFile = null;
    document.getElementById("tsv2csv-file-info").hidden = true;
    document.getElementById("tsv2csv-actions").hidden = true;
}

async function doTsvToCsv() {
    if (!tsv2csvFile) return;
    await simpleConvert("tsv2csv-btn", "tsv2csv-error", "/api/convert/tsv-to-csv", tsv2csvFile, f => f.name.replace(/\.(tsv|txt)$/i, ".csv"), "Convert to CSV");
}

/* ── XML to JSON ── */
setupDropZone("xml-drop", "xml-input", files => {
    const f = files[0];
    if (!f) return;
    xmlFile = f;
    document.getElementById("xml-file-name").textContent = f.name;
    document.getElementById("xml-file-size").textContent = formatSize(f.size);
    document.getElementById("xml-file-info").hidden = false;
    document.getElementById("xml-actions").hidden = false;
});

function clearXmlFile() {
    xmlFile = null;
    document.getElementById("xml-file-info").hidden = true;
    document.getElementById("xml-actions").hidden = true;
}

async function doXmlToJson() {
    if (!xmlFile) return;
    await simpleConvert("xml-btn", "xml-error", "/api/convert/xml-to-json", xmlFile, f => f.name.replace(/\.xml$/i, ".json"), "Convert to JSON");
}

/* ── Create ZIP ── */
setupDropZone("createzip-drop", "createzip-input", files => {
    for (const f of files) createZipFiles.push(f);
    renderCreateZipList();
});

function renderCreateZipList() {
    const list = document.getElementById("createzip-list");
    list.innerHTML = "";
    createZipFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.innerHTML = `
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeCreateZipFile(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    document.getElementById("createzip-actions").hidden = createZipFiles.length === 0;
}

function removeCreateZipFile(i) {
    createZipFiles.splice(i, 1);
    renderCreateZipList();
}

function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

async function doCreateZip() {
    if (!createZipFiles.length) return;
    const btn = document.getElementById("createzip-btn");
    const err = document.getElementById("createzip-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Creating...";

    const form = new FormData();
    createZipFiles.forEach(f => form.append("files", f));

    try {
        const res = await fetch("/api/convert/zip", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Failed to create ZIP";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            downloadBlob(blob, "archive.zip");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Create ZIP`;
}

/* ── Extract ZIP ── */
setupDropZone("extractzip-drop", "extractzip-input", files => {
    const f = files[0];
    if (!f) return;
    extractZipFile = f;
    document.getElementById("extractzip-file-name").textContent = f.name;
    document.getElementById("extractzip-file-size").textContent = formatSize(f.size);
    document.getElementById("extractzip-file-info").hidden = false;
    document.getElementById("extractzip-actions").hidden = false;
});

function clearExtractZipFile() {
    extractZipFile = null;
    document.getElementById("extractzip-file-info").hidden = true;
    document.getElementById("extractzip-actions").hidden = true;
}

async function doExtractZip() {
    if (!extractZipFile) return;
    const btn = document.getElementById("extractzip-btn");
    const err = document.getElementById("extractzip-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Extracting...";

    const form = new FormData();
    form.append("file", extractZipFile);

    try {
        const res = await fetch("/api/convert/unzip", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Failed to extract ZIP";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const ct = res.headers.get("content-type") || "";
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
            const base = extractZipFile.name.replace(/\.zip$/i, "");
            const name = match ? match[1] : (ct.includes("zip") ? `${base}_extracted.zip` : base);
            downloadBlob(blob, name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Extract ZIP`;
}

/* ── Generic single-file converter ── */
async function simpleConvert(btnId, errId, endpoint, file, nameFn, label) {
    const btn = document.getElementById(btnId);
    const err = document.getElementById(errId);
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    form.append("file", file);

    try {
        const res = await fetch(endpoint, { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            downloadBlob(blob, nameFn(file));
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> ${label}`;
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
