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
showTab(location.hash.slice(1) || "md2html");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "md2html"));

setupPageDropOverlay();

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
            showToast("Saved: converted.html");
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
            showToast("Saved: " + base + ".json");
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
            showToast("Saved: " + base + ".csv");
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
            const tmp = document.createElement("div");
            tmp.innerHTML = data.html;
            tmp.querySelectorAll("script,iframe,object,embed,link[rel=import]").forEach(el => el.remove());
            tmp.querySelectorAll("*").forEach(el => {
                for (const attr of [...el.attributes]) {
                    if (attr.name.startsWith("on") || (attr.name === "href" && attr.value.trim().toLowerCase().startsWith("javascript:"))) {
                        el.removeAttribute(attr.name);
                    }
                }
            });
            previewEl.innerHTML = tmp.innerHTML;
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
            showToast("Saved: archive.zip");
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
            showToast("Saved: " + name);
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
            const dlName = nameFn(file);
            downloadBlob(blob, dlName);
            showToast("Saved: " + dlName);
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

/* ═══════════════════ Batch 2: data tools ═══════════════════ */

const DL_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg>`;

function copyText(id, btn) {
    const el = document.getElementById(id);
    navigator.clipboard.writeText(el.value || el.textContent).then(() => {
        if (btn) {
            btn.classList.add("copied");
            const orig = btn.innerHTML;
            btn.innerHTML = "Copied!";
            setTimeout(() => { btn.classList.remove("copied"); btn.innerHTML = orig; }, 1500);
        }
    }).catch(() => {
        el.select && el.select();
        document.execCommand("copy");
    });
}

function downloadText(id, name) {
    const el = document.getElementById(id);
    const blob = new Blob([el.value || el.textContent], { type: "text/plain;charset=utf-8" });
    downloadBlob(blob, name || "result.txt");
    showToast("Saved: " + (name || "result.txt"));
}

function showErr(errId, msg) {
    const err = document.getElementById(errId);
    err.textContent = msg;
    err.hidden = false;
}

function filenameFromResponse(res, fallback) {
    const cd = res.headers.get("content-disposition") || "";
    const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
    return m ? decodeURIComponent(m[1]) : fallback;
}

/* Generic file-or-text tool whose route returns JSON {result, filename}.
   `key` is the element-id prefix: {key}-drop, {key}-input, {key}-file-info, {key}-text, {key}-btn, {key}-error, {key}-result */
const textToolFile = {};
const textToolOutName = {};

function setupTextTool(key, opts) {
    setupDropZone(key + "-drop", key + "-input", files => {
        const f = files[0];
        if (!f) return;
        textToolFile[key] = f;
        document.getElementById(key + "-file-name").textContent = f.name;
        document.getElementById(key + "-file-size").textContent = formatSize(f.size);
        document.getElementById(key + "-file-info").hidden = false;
        const reader = new FileReader();
        reader.onload = e => { document.getElementById(key + "-text").value = e.target.result; };
        reader.readAsText(f);
    });
}

function clearTextTool(key) {
    textToolFile[key] = null;
    document.getElementById(key + "-file-info").hidden = true;
}

async function runTextTool(key, endpoint, label, extraForm, defaultName) {
    const btn = document.getElementById(key + "-btn");
    const err = document.getElementById(key + "-error");
    const wrap = document.getElementById(key + "-result-wrap");
    err.hidden = true;
    const text = document.getElementById(key + "-text").value;
    if (!text.trim()) {
        showErr(key + "-error", "Upload a file or paste text first");
        return;
    }
    btn.disabled = true;
    btn.textContent = "Converting...";
    const form = new FormData();
    const f = textToolFile[key];
    if (f) form.append("file", f); else form.append("text", text);
    if (extraForm) extraForm(form);
    try {
        const res = await fetch(endpoint, { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) {
            showErr(key + "-error", data.error || "Conversion failed");
            wrap.hidden = true;
        } else {
            document.getElementById(key + "-result").value = data.result;
            textToolOutName[key] = data.filename || defaultName;
            wrap.hidden = false;
        }
    } catch {
        showErr(key + "-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = DL_ICON + " " + label;
}

/* ── JSON to XML ── */
let json2xmlOutName = "data.xml";
setupTextTool("json2xml");
function clearJson2XmlFile() { clearTextTool("json2xml"); }
async function doJsonToXml() {
    await runTextTool("json2xml", "/api/convert/json-to-xml", "Convert to XML",
        form => form.append("root", document.getElementById("json2xml-root").value.trim() || "root"), "data.xml");
    json2xmlOutName = textToolOutName.json2xml || "data.xml";
}

/* ── Excel to CSV ── */
let xlsx2csvFile = null;
setupDropZone("xlsx2csv-drop", "xlsx2csv-input", files => {
    const f = files[0];
    if (!f) return;
    xlsx2csvFile = f;
    document.getElementById("xlsx2csv-file-name").textContent = f.name;
    document.getElementById("xlsx2csv-file-size").textContent = formatSize(f.size);
    document.getElementById("xlsx2csv-file-info").hidden = false;
    document.getElementById("xlsx2csv-actions").hidden = false;
});
function clearXlsx2CsvFile() {
    xlsx2csvFile = null;
    document.getElementById("xlsx2csv-file-info").hidden = true;
    document.getElementById("xlsx2csv-actions").hidden = true;
}
async function doXlsxToCsv() {
    if (!xlsx2csvFile) return;
    const btn = document.getElementById("xlsx2csv-btn");
    const err = document.getElementById("xlsx2csv-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";
    const form = new FormData();
    form.append("file", xlsx2csvFile);
    form.append("sheet", document.getElementById("xlsx2csv-sheet").value.trim());
    try {
        const res = await fetch("/api/convert/xlsx-to-csv", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            showErr("xlsx2csv-error", data.error || "Conversion failed");
        } else {
            const blob = await res.blob();
            const base = xlsx2csvFile.name.replace(/\.(xlsx|xlsm)$/i, "");
            const name = filenameFromResponse(res, base + ".csv");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        showErr("xlsx2csv-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = DL_ICON + " Convert to CSV";
}

/* ── CSV to Excel ── */
let csv2xlsxFiles = [];
setupDropZone("csv2xlsx-drop", "csv2xlsx-input", files => {
    for (const f of files) csv2xlsxFiles.push(f);
    renderSimpleList("csv2xlsx-list", csv2xlsxFiles, "removeCsv2XlsxFile", "csv2xlsx-actions");
});
function removeCsv2XlsxFile(i) {
    csv2xlsxFiles.splice(i, 1);
    renderSimpleList("csv2xlsx-list", csv2xlsxFiles, "removeCsv2XlsxFile", "csv2xlsx-actions");
}
function renderSimpleList(listId, arr, removeFn, actionsId) {
    const list = document.getElementById(listId);
    list.innerHTML = "";
    arr.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.innerHTML = `
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="${removeFn}(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    list.hidden = arr.length === 0;
    if (actionsId) document.getElementById(actionsId).hidden = arr.length === 0;
}
async function doCsvToXlsx() {
    if (!csv2xlsxFiles.length) return;
    const btn = document.getElementById("csv2xlsx-btn");
    const err = document.getElementById("csv2xlsx-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";
    const form = new FormData();
    csv2xlsxFiles.forEach(f => form.append("files", f));
    form.append("header", document.getElementById("csv2xlsx-header").checked ? "true" : "false");
    try {
        const res = await fetch("/api/convert/csv-to-xlsx", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            showErr("csv2xlsx-error", data.error || "Conversion failed");
        } else {
            const blob = await res.blob();
            const fallback = csv2xlsxFiles.length === 1 ? csv2xlsxFiles[0].name.replace(/\.[^.]+$/, "") + ".xlsx" : "workbook.xlsx";
            const name = filenameFromResponse(res, fallback);
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        showErr("csv2xlsx-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = DL_ICON + " Convert to Excel";
}

/* ── HTML to Markdown ── */
let html2mdOutName = "converted.md";
setupTextTool("html2md");
function clearHtml2MdFile() { clearTextTool("html2md"); }
async function doHtmlToMd() {
    await runTextTool("html2md", "/api/convert/html-to-md", "Convert to Markdown", null, "converted.md");
    html2mdOutName = textToolOutName.html2md || "converted.md";
}

/* ── TOML ↔ JSON ── */
setupTextTool("toml2json");
setupTextTool("json2toml");
async function doTomlToJson() {
    await runTextTool("toml2json", "/api/convert/toml-to-json", "Convert to JSON", null, "data.json");
}
async function doJsonToToml() {
    await runTextTool("json2toml", "/api/convert/json-to-toml", "Convert to TOML", null, "data.toml");
}

/* ── SQL Formatter ── */
async function doSqlFormat(minify) {
    const btn = document.getElementById(minify ? "sql-minify-btn" : "sql-btn");
    const other = document.getElementById(minify ? "sql-btn" : "sql-minify-btn");
    const err = document.getElementById("sql-error");
    const wrap = document.getElementById("sql-result-wrap");
    err.hidden = true;
    const text = document.getElementById("sql-text").value;
    if (!text.trim()) { showErr("sql-error", "Paste some SQL first"); return; }
    btn.disabled = true; other.disabled = true;
    const origLabel = btn.innerHTML;
    btn.textContent = minify ? "Minifying..." : "Formatting...";
    const form = new FormData();
    form.append("text", text);
    form.append("keyword_case", document.getElementById("sql-case").value);
    form.append("indent_width", document.getElementById("sql-indent").value || "2");
    form.append("reindent", document.getElementById("sql-reindent").checked ? "true" : "false");
    form.append("strip_comments", document.getElementById("sql-strip").checked ? "true" : "false");
    form.append("minify", minify ? "true" : "false");
    try {
        const res = await fetch("/api/convert/sql-format", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) {
            showErr("sql-error", data.error || "Formatting failed");
            wrap.hidden = true;
        } else {
            document.getElementById("sql-result").value = data.result;
            wrap.hidden = false;
        }
    } catch {
        showErr("sql-error", "Network error");
    }
    btn.disabled = false; other.disabled = false;
    btn.innerHTML = origLabel;
}

/* ═══════════════════ Batch 2: file tools ═══════════════════ */

/* ── Extract Archive ── */
let extArcFile = null;
setupDropZone("extarc-drop", "extarc-input", files => {
    const f = files[0];
    if (!f) return;
    extArcFile = f;
    document.getElementById("extarc-file-name").textContent = f.name;
    document.getElementById("extarc-file-size").textContent = formatSize(f.size);
    document.getElementById("extarc-file-info").hidden = false;
    document.getElementById("extarc-actions").hidden = false;
    document.getElementById("extarc-error").hidden = true;
    loadArchiveListing(f);
});
function clearExtArcFile() {
    extArcFile = null;
    document.getElementById("extarc-file-info").hidden = true;
    document.getElementById("extarc-actions").hidden = true;
    document.getElementById("extarc-listing").hidden = true;
    document.getElementById("extarc-error").hidden = true;
}
async function loadArchiveListing(f) {
    const listing = document.getElementById("extarc-listing");
    const rows = document.getElementById("extarc-rows");
    const summary = document.getElementById("extarc-summary");
    listing.hidden = true;
    rows.innerHTML = "";
    summary.textContent = "Reading...";
    const form = new FormData();
    form.append("file", f);
    try {
        const res = await fetch("/api/convert/archive-list", { method: "POST", body: form });
        const data = await res.json();
        if (f !== extArcFile) return;
        if (!res.ok) {
            showErr("extarc-error", data.error || "Could not read archive");
            document.getElementById("extarc-actions").hidden = true;
            return;
        }
        const entries = data.entries || [];
        const shown = entries.slice(0, 500);
        rows.innerHTML = shown.map(e => `<tr><td>${esc(e.name)}</td><td class="c2-right">${formatSize(e.size)}</td></tr>`).join("");
        if (entries.length > shown.length) {
            rows.innerHTML += `<tr><td colspan="2" style="color:var(--text-muted)">… and ${entries.length - shown.length} more</td></tr>`;
        }
        summary.textContent = `${entries.length} file${entries.length === 1 ? "" : "s"} · ${formatSize(data.total_size || 0)} uncompressed`;
        listing.hidden = false;
    } catch {
        if (f === extArcFile) showErr("extarc-error", "Network error");
    }
}
async function doExtractArchive() {
    if (!extArcFile) return;
    const btn = document.getElementById("extarc-btn");
    const err = document.getElementById("extarc-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Extracting...";
    const form = new FormData();
    form.append("file", extArcFile);
    try {
        const res = await fetch("/api/convert/extract-archive", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            showErr("extarc-error", data.error || "Failed to extract archive");
        } else {
            const blob = await res.blob();
            const name = filenameFromResponse(res, extArcFile.name.replace(/\.[^.]+$/, "") + "_extracted.zip");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        showErr("extarc-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = DL_ICON + " Extract to ZIP";
}

/* ── Checksum ── */
let checksumFiles = [];
let checksumResults = null;
setupDropZone("checksum-drop", "checksum-input", files => {
    for (const f of files) checksumFiles.push(f);
    checksumResults = null;
    document.getElementById("checksum-results").hidden = true;
    renderSimpleList("checksum-list", checksumFiles, "removeChecksumFile", "checksum-actions");
});
function removeChecksumFile(i) {
    checksumFiles.splice(i, 1);
    checksumResults = null;
    document.getElementById("checksum-results").hidden = true;
    renderSimpleList("checksum-list", checksumFiles, "removeChecksumFile", "checksum-actions");
}
async function doChecksum() {
    if (!checksumFiles.length) return;
    const btn = document.getElementById("checksum-btn");
    const err = document.getElementById("checksum-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Hashing...";
    const form = new FormData();
    checksumFiles.forEach(f => form.append("files", f));
    try {
        const res = await fetch("/api/convert/checksum", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) {
            showErr("checksum-error", data.error || "Hashing failed");
        } else {
            checksumResults = data;
            renderChecksumResults();
        }
    } catch {
        showErr("checksum-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><polyline points="20 6 9 17 4 12"/></svg> Compute Hashes`;
}
function renderChecksumResults() {
    const box = document.getElementById("checksum-results");
    if (!checksumResults) { box.hidden = true; return; }
    const expected = document.getElementById("checksum-expected").value.trim().toLowerCase();
    const algos = [["md5", "MD5"], ["sha1", "SHA-1"], ["sha256", "SHA-256"], ["sha512", "SHA-512"]];
    let html = "";
    for (const [name, h] of Object.entries(checksumResults)) {
        let anyMatch = false;
        const rows = algos.map(([k, label]) => {
            const val = h[k];
            let cls = "";
            if (expected) {
                if (val === expected) { cls = "c2-match"; anyMatch = true; }
                else if (expected.length === val.length) cls = "c2-mismatch";
            }
            const id = "ck-" + Math.random().toString(36).slice(2, 9);
            return `<tr class="${cls}"><td class="c2-algo">${label}</td><td class="c2-hash" id="${id}">${esc(val)}</td><td class="c2-right"><button class="btn-copy" onclick="copyText('${id}', this)">Copy</button></td></tr>`;
        }).join("");
        const badge = expected ? (anyMatch ? `<span class="c2-badge match">MATCH</span>` : `<span class="c2-badge mismatch">NO MATCH</span>`) : "";
        html += `<div class="c2-file-heading"><span>${esc(name)} <span class="file-size">${formatSize(h.size)}</span></span>${badge}</div>
            <div class="c2-table-wrap"><table class="c2-table"><tbody>${rows}</tbody></table></div>`;
    }
    box.innerHTML = html;
    box.hidden = false;
}

/* ── Batch Rename ──
   Mirrors tools_convert2.rename_one / batch_rename_names. Keep in sync:
     1. split stem / ext (ext = text after last dot; dotfiles like ".env" have no ext)
     2. plain find → replace on the stem (all occurrences, case-sensitive)
     3. case (keep | lower | upper | title) on the stem
     4. pattern tokens {name} {ext} {n} {n:03} {date}; ".{ext}" collapses when ext is empty
     5. strip path separators; fall back to original name if empty; dedupe with _2, _3… */
let renameFiles = [];
setupDropZone("rename-drop", "rename-input", files => {
    for (const f of files) renameFiles.push(f);
    renderSimpleList("rename-list", renameFiles, "removeRenameFile", "rename-actions");
    renderRenamePreview();
});
function removeRenameFile(i) {
    renameFiles.splice(i, 1);
    renderSimpleList("rename-list", renameFiles, "removeRenameFile", "rename-actions");
    renderRenamePreview();
}
function renameApplyCase(s, mode) {
    if (mode === "lower") return s.toLowerCase();
    if (mode === "upper") return s.toUpperCase();
    if (mode === "title") return s.replace(/[A-Za-z]+/g, w => w[0].toUpperCase() + w.slice(1).toLowerCase());
    return s;
}
function renameOne(filename, index, pattern, find, replace, mode, dateStr) {
    const base = filename.split("/").pop().split("\\").pop();
    let stem = base, ext = "";
    const dot = base.lastIndexOf(".");
    if (dot > 0) { stem = base.slice(0, dot); ext = base.slice(dot + 1); }
    if (find) stem = stem.split(find).join(replace);
    stem = renameApplyCase(stem, mode);
    const pat = pattern.trim() ? pattern : "{name}.{ext}";
    let out = pat.split("{name}").join(stem);
    out = out.split(".{ext}").join(ext ? "." + ext : "");
    out = out.split("{ext}").join(ext);
    out = out.split("{date}").join(dateStr);
    out = out.replace(/\{n(?::0?(\d+))?\}/g, (_, w) => w ? String(index).padStart(parseInt(w, 10), "0") : String(index));
    out = out.replace(/[\/\\]/g, "_").trim();
    return out || base;
}
function renameDedupe(name, used) {
    if (!used.has(name)) { used.add(name); return name; }
    const dot = name.lastIndexOf(".");
    const hasExt = dot > -1 && !name.slice(dot + 1).includes("/");
    const stem = hasExt ? name.slice(0, dot) : name;
    const suffix = hasExt ? name.slice(dot) : "";
    let n = 2, cand = `${stem}_${n}${suffix}`;
    while (used.has(cand)) { n++; cand = `${stem}_${n}${suffix}`; }
    used.add(cand);
    return cand;
}
function renameToday() {
    const d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
function renameParams() {
    return {
        pattern: document.getElementById("rename-pattern").value,
        find: document.getElementById("rename-find").value,
        replace: document.getElementById("rename-replace").value,
        mode: document.getElementById("rename-case").value,
        start: parseInt(document.getElementById("rename-start").value, 10) || 0,
        date: renameToday(),
    };
}
function renamePreview(names) {
    const p = renameParams();
    const used = new Set();
    return names.map((n, i) => renameDedupe(renameOne(n, p.start + i, p.pattern, p.find, p.replace, p.mode, p.date), used));
}
function renderRenamePreview() {
    const wrap = document.getElementById("rename-preview-wrap");
    const rows = document.getElementById("rename-rows");
    if (!renameFiles.length) { wrap.hidden = true; return; }
    const news = renamePreview(renameFiles.map(f => f.name));
    rows.innerHTML = renameFiles.map((f, i) => {
        const changed = news[i] !== f.name;
        return `<tr><td>${esc(f.name)}</td><td class="${changed ? "c2-changed" : "c2-unchanged"}">${esc(news[i])}</td></tr>`;
    }).join("");
    wrap.hidden = false;
}
async function doBatchRename() {
    if (!renameFiles.length) return;
    const btn = document.getElementById("rename-btn");
    const err = document.getElementById("rename-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Renaming...";
    const p = renameParams();
    const form = new FormData();
    renameFiles.forEach(f => form.append("files", f));
    form.append("pattern", p.pattern);
    form.append("find", p.find);
    form.append("replace", p.replace);
    form.append("case", p.mode);
    form.append("start", String(p.start));
    form.append("date", p.date);
    try {
        const res = await fetch("/api/convert/batch-rename", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            showErr("rename-error", data.error || "Rename failed");
        } else {
            const blob = await res.blob();
            downloadBlob(blob, "renamed.zip");
            showToast("Saved: renamed.zip");
        }
    } catch {
        showErr("rename-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = DL_ICON + " Rename &amp; Download ZIP";
}

/* ── File Splitter ── */
let splitFileObj = null;
setupDropZone("splitfile-drop", "splitfile-input", files => {
    const f = files[0];
    if (!f) return;
    splitFileObj = f;
    document.getElementById("splitfile-file-name").textContent = f.name;
    document.getElementById("splitfile-file-size").textContent = formatSize(f.size);
    document.getElementById("splitfile-file-info").hidden = false;
    document.getElementById("splitfile-actions").hidden = false;
    updateSplitEstimate();
});
function clearSplitFile() {
    splitFileObj = null;
    document.getElementById("splitfile-file-info").hidden = true;
    document.getElementById("splitfile-actions").hidden = true;
    document.getElementById("splitfile-estimate").textContent = "";
}
function updateSplitEstimate() {
    const el = document.getElementById("splitfile-estimate");
    const mb = parseFloat(document.getElementById("splitfile-chunk").value);
    if (!splitFileObj || !(mb > 0)) { el.textContent = ""; return; }
    const parts = Math.ceil(splitFileObj.size / (mb * 1048576));
    el.textContent = parts > 1 ? `→ ${parts} parts` : "file is smaller than one chunk";
}
async function doSplitFile() {
    if (!splitFileObj) return;
    const btn = document.getElementById("splitfile-btn");
    const err = document.getElementById("splitfile-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Splitting...";
    const form = new FormData();
    form.append("file", splitFileObj);
    form.append("chunk_mb", document.getElementById("splitfile-chunk").value || "100");
    try {
        const res = await fetch("/api/convert/split-file", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            showErr("splitfile-error", data.error || "Split failed");
        } else {
            const blob = await res.blob();
            const name = filenameFromResponse(res, splitFileObj.name.replace(/\.[^.]+$/, "") + "_parts.zip");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        showErr("splitfile-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = DL_ICON + " Split File";
}

/* ── Join Files ── */
let joinFilesArr = [];
setupDropZone("joinfiles-drop", "joinfiles-input", files => {
    for (const f of files) joinFilesArr.push(f);
    joinFilesArr.sort((a, b) => a.name.localeCompare(b.name));
    renderSimpleList("joinfiles-list", joinFilesArr, "removeJoinFile", "joinfiles-actions");
});
function removeJoinFile(i) {
    joinFilesArr.splice(i, 1);
    renderSimpleList("joinfiles-list", joinFilesArr, "removeJoinFile", "joinfiles-actions");
}
async function doJoinFiles() {
    if (!joinFilesArr.length) return;
    const btn = document.getElementById("joinfiles-btn");
    const err = document.getElementById("joinfiles-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Joining...";
    const form = new FormData();
    joinFilesArr.forEach(f => form.append("files", f));
    try {
        const res = await fetch("/api/convert/join-files", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            showErr("joinfiles-error", data.error || "Join failed");
        } else {
            const blob = await res.blob();
            const name = filenameFromResponse(res, joinFilesArr[0].name.replace(/\.\d{3,}$/, ""));
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        showErr("joinfiles-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = DL_ICON + " Join Files";
}
