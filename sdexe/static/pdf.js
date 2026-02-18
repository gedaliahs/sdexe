/* ── State ── */
let mergeFiles = [];
let splitFile = null;
let imgFiles = [];
let compressPdfFile = null;
let totextFile = null;
let addPwFile = null;
let removePwFile = null;
let rotatePagesFile = null;
let extractImagesFile = null;
let numberPagesFile = null;

/* ── Hash Routing ── */
function showTab(tab) {
    document.querySelectorAll(".pdf-section").forEach(s => s.classList.remove("active"));
    const el = document.getElementById("tab-" + tab);
    (el || document.querySelector(".pdf-section")).classList.add("active");
    window.scrollTo(0, 0);
}
showTab(location.hash.slice(1) || "merge");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "merge"));

/* ── Drop Zone Setup ── */
function setupDropZone(zoneId, inputId, handler) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
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

/* ── Full-page drop overlay ── */
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

/* ── Merge ── */
setupDropZone("merge-drop", "merge-input", files => {
    for (const f of files) {
        if (f.type === "application/pdf" || f.name.endsWith(".pdf")) {
            mergeFiles.push(f);
        }
    }
    renderMergeList();
});

function renderMergeList() {
    const list = document.getElementById("merge-list");
    list.innerHTML = "";
    mergeFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.draggable = true;
        div.dataset.index = i;
        div.innerHTML = `
            <span class="drag-handle">&#9776;</span>
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeMergeFile(${i})">&times;</button>
        `;
        setupDragItem(div, mergeFiles, renderMergeList);
        list.appendChild(div);
    });
    document.getElementById("merge-actions").hidden = mergeFiles.length < 2;
}

function removeMergeFile(i) {
    mergeFiles.splice(i, 1);
    renderMergeList();
}

async function doMerge() {
    const btn = document.getElementById("merge-btn");
    const err = document.getElementById("merge-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Merging...";

    const form = new FormData();
    mergeFiles.forEach(f => form.append("files", f));

    try {
        const res = await fetch("/api/pdf/merge", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Merge failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            downloadBlob(blob, "merged.pdf");
            showToast("Saved: merged.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Merge PDFs`;
}

/* ── Split ── */
setupDropZone("split-drop", "split-input", async files => {
    const f = files[0];
    if (!f) return;
    splitFile = f;

    document.getElementById("split-file-name").textContent = f.name;
    document.getElementById("split-file-info").hidden = false;
    document.getElementById("split-options").hidden = false;
    document.getElementById("split-actions").hidden = false;

    // Get page count
    const form = new FormData();
    form.append("file", f);
    try {
        const res = await fetch("/api/pdf/page-count", { method: "POST", body: form });
        const data = await res.json();
        if (data.pages) {
            document.getElementById("split-page-count").textContent = `${data.pages} pages`;
        }
    } catch {}
});

function clearSplitFile() {
    splitFile = null;
    document.getElementById("split-file-info").hidden = true;
    document.getElementById("split-options").hidden = true;
    document.getElementById("split-actions").hidden = true;
    document.getElementById("split-page-count").textContent = "";
    document.getElementById("split-ranges").value = "";
}

async function doSplit() {
    if (!splitFile) return;
    const btn = document.getElementById("split-btn");
    const err = document.getElementById("split-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Splitting...";

    const form = new FormData();
    form.append("file", splitFile);
    form.append("ranges", document.getElementById("split-ranges").value);

    try {
        const res = await fetch("/api/pdf/split", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Split failed";
            err.hidden = false;
        } else {
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const name = ct.includes("zip") ? "split_pages.zip" : "split.pdf";
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Split PDF`;
}

/* ── Images to PDF ── */
setupDropZone("img-drop", "img-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) {
            imgFiles.push(f);
        }
    }
    renderImgList();
});

function renderImgList() {
    const list = document.getElementById("img-list");
    list.innerHTML = "";
    imgFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.draggable = true;
        div.dataset.index = i;

        const thumb = URL.createObjectURL(f);
        div.innerHTML = `
            <span class="drag-handle">&#9776;</span>
            <img class="img-thumb" src="${thumb}" alt="">
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeImgFile(${i})">&times;</button>
        `;
        setupDragItem(div, imgFiles, renderImgList);
        list.appendChild(div);
    });
    document.getElementById("img-actions").hidden = imgFiles.length === 0;
}

function removeImgFile(i) {
    imgFiles.splice(i, 1);
    renderImgList();
}

async function doImagesToPdf() {
    const btn = document.getElementById("img-btn");
    const err = document.getElementById("img-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    imgFiles.forEach(f => form.append("files", f));

    try {
        const res = await fetch("/api/pdf/images-to-pdf", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            downloadBlob(blob, "images.pdf");
            showToast("Saved: images.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to PDF`;
}

/* ── Drag and Drop Reorder ── */
let dragSrcIndex = null;

function setupDragItem(el, arr, renderFn) {
    el.addEventListener("dragstart", e => {
        dragSrcIndex = parseInt(el.dataset.index);
        el.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
    });
    el.addEventListener("dragend", () => {
        el.classList.remove("dragging");
        dragSrcIndex = null;
    });
    el.addEventListener("dragover", e => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        el.classList.add("drag-target");
    });
    el.addEventListener("dragleave", () => el.classList.remove("drag-target"));
    el.addEventListener("drop", e => {
        e.preventDefault();
        e.stopPropagation();
        el.classList.remove("drag-target");
        const targetIndex = parseInt(el.dataset.index);
        if (dragSrcIndex !== null && dragSrcIndex !== targetIndex) {
            const [item] = arr.splice(dragSrcIndex, 1);
            arr.splice(targetIndex, 0, item);
            renderFn();
        }
    });
}

/* ── Subtab switching (for Password tab) ── */
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
// Init first subtab
document.querySelectorAll(".pdf-subsection").forEach((s, i) => {
    if (i === 0) { s.hidden = false; s.classList.add("active"); }
});

/* ── Compress PDF ── */
setupDropZone("compress-drop", "compress-pdf-input", files => {
    const f = files[0];
    if (!f) return;
    compressPdfFile = f;
    document.getElementById("compress-pdf-name").textContent = f.name;
    document.getElementById("compress-pdf-size").textContent = formatSize(f.size);
    document.getElementById("compress-pdf-info").hidden = false;
    document.getElementById("compress-pdf-actions").hidden = false;
});

function clearCompressPdf() {
    compressPdfFile = null;
    document.getElementById("compress-pdf-info").hidden = true;
    document.getElementById("compress-pdf-actions").hidden = true;
}

async function doCompressPdf() {
    if (!compressPdfFile) return;
    const btn = document.getElementById("compress-pdf-btn");
    const err = document.getElementById("compress-pdf-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Compressing...";

    const form = new FormData();
    form.append("file", compressPdfFile);

    try {
        const res = await fetch("/api/pdf/compress", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Compression failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = compressPdfFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_compressed.pdf");
            showToast("Saved: " + base + "_compressed.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Compress PDF`;
}

/* ── PDF → Text ── */
setupDropZone("totext-drop", "totext-input", files => {
    const f = files[0];
    if (!f) return;
    totextFile = f;
    document.getElementById("totext-file-name").textContent = f.name;
    document.getElementById("totext-file-size").textContent = formatSize(f.size);
    document.getElementById("totext-file-info").hidden = false;
    document.getElementById("totext-actions").hidden = false;
});

function clearTotextFile() {
    totextFile = null;
    document.getElementById("totext-file-info").hidden = true;
    document.getElementById("totext-actions").hidden = true;
}

async function doToText() {
    if (!totextFile) return;
    const btn = document.getElementById("totext-btn");
    const err = document.getElementById("totext-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Extracting...";

    const form = new FormData();
    form.append("file", totextFile);

    try {
        const res = await fetch("/api/pdf/to-text", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Extraction failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = totextFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + ".txt");
            showToast("Saved: " + base + ".txt");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Extract Text`;
}

/* ── PDF Add Password ── */
setupDropZone("addpw-drop", "addpw-input", files => {
    const f = files[0];
    if (!f) return;
    addPwFile = f;
    document.getElementById("addpw-file-name").textContent = f.name;
    document.getElementById("addpw-file-size").textContent = formatSize(f.size);
    document.getElementById("addpw-file-info").hidden = false;
    document.getElementById("addpw-options").hidden = false;
    document.getElementById("addpw-actions").hidden = false;
});

function clearAddPwFile() {
    addPwFile = null;
    document.getElementById("addpw-file-info").hidden = true;
    document.getElementById("addpw-options").hidden = true;
    document.getElementById("addpw-actions").hidden = true;
}

async function doAddPassword() {
    if (!addPwFile) return;
    const password = document.getElementById("addpw-password").value;
    if (!password) { document.getElementById("addpw-error").textContent = "Enter a password"; document.getElementById("addpw-error").hidden = false; return; }
    const btn = document.getElementById("addpw-btn");
    const err = document.getElementById("addpw-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Protecting...";

    const form = new FormData();
    form.append("file", addPwFile);
    form.append("password", password);

    try {
        const res = await fetch("/api/pdf/add-password", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = addPwFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_protected.pdf");
            showToast("Saved: " + base + "_protected.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Protect PDF`;
}

/* ── PDF Remove Password ── */
setupDropZone("removepw-drop", "removepw-input", files => {
    const f = files[0];
    if (!f) return;
    removePwFile = f;
    document.getElementById("removepw-file-name").textContent = f.name;
    document.getElementById("removepw-file-size").textContent = formatSize(f.size);
    document.getElementById("removepw-file-info").hidden = false;
    document.getElementById("removepw-options").hidden = false;
    document.getElementById("removepw-actions").hidden = false;
});

function clearRemovePwFile() {
    removePwFile = null;
    document.getElementById("removepw-file-info").hidden = true;
    document.getElementById("removepw-options").hidden = true;
    document.getElementById("removepw-actions").hidden = true;
}

async function doRemovePassword() {
    if (!removePwFile) return;
    const password = document.getElementById("removepw-password").value;
    const btn = document.getElementById("removepw-btn");
    const err = document.getElementById("removepw-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Unlocking...";

    const form = new FormData();
    form.append("file", removePwFile);
    form.append("password", password);

    try {
        const res = await fetch("/api/pdf/remove-password", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = removePwFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_unlocked.pdf");
            showToast("Saved: " + base + "_unlocked.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Unlock PDF`;
}

/* ── Rotate Pages ── */
setupDropZone("rotatepages-drop", "rotatepages-input", async files => {
    const f = files[0];
    if (!f) return;
    rotatePagesFile = f;
    document.getElementById("rotatepages-file-name").textContent = f.name;
    document.getElementById("rotatepages-file-info").hidden = false;
    document.getElementById("rotatepages-options").hidden = false;
    document.getElementById("rotatepages-actions").hidden = false;
    const form = new FormData();
    form.append("file", f);
    try {
        const res = await fetch("/api/pdf/page-count", { method: "POST", body: form });
        const data = await res.json();
        if (data.pages) {
            document.getElementById("rotatepages-page-count").textContent = `${data.pages} pages`;
        }
    } catch {}
});

function clearRotatePagesFile() {
    rotatePagesFile = null;
    document.getElementById("rotatepages-file-info").hidden = true;
    document.getElementById("rotatepages-options").hidden = true;
    document.getElementById("rotatepages-actions").hidden = true;
    document.getElementById("rotatepages-page-count").textContent = "";
    document.getElementById("rotatepages-pages").value = "";
}

async function doRotatePages() {
    if (!rotatePagesFile) return;
    const btn = document.getElementById("rotatepages-btn");
    const err = document.getElementById("rotatepages-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Rotating...";

    const form = new FormData();
    form.append("file", rotatePagesFile);
    form.append("angle", document.getElementById("rotatepages-angle").value);
    const pagesVal = document.getElementById("rotatepages-pages").value.trim();
    form.append("pages", pagesVal || "all");

    try {
        const res = await fetch("/api/pdf/rotate", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Rotation failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = rotatePagesFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_rotated.pdf");
            showToast("Saved: " + base + "_rotated.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Rotate Pages`;
}

/* ── Extract Images ── */
setupDropZone("extractimages-drop", "extractimages-input", files => {
    const f = files[0];
    if (!f || (!f.type.includes("pdf") && !f.name.endsWith(".pdf"))) return;
    extractImagesFile = f;
    document.getElementById("extractimages-file-name").textContent = f.name;
    document.getElementById("extractimages-file-size").textContent = formatSize(f.size);
    document.getElementById("extractimages-file-info").hidden = false;
    document.getElementById("extractimages-actions").hidden = false;
});

function clearExtractImagesFile() {
    extractImagesFile = null;
    document.getElementById("extractimages-file-info").hidden = true;
    document.getElementById("extractimages-actions").hidden = true;
}

async function doExtractImages() {
    if (!extractImagesFile) return;
    const btn = document.getElementById("extractimages-btn");
    const err = document.getElementById("extractimages-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Extracting...";

    const fd = new FormData();
    fd.append("file", extractImagesFile);
    try {
        const res = await fetch("/api/pdf/extract-images", { method: "POST", body: fd });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Extraction failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
            const name = match ? match[1] : "images.zip";
            downloadBlob(blob, name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Extract Images';
}

/* ── Number Pages ── */
setupDropZone("numberpages-drop", "numberpages-input", files => {
    const f = files[0];
    if (!f || (!f.type.includes("pdf") && !f.name.endsWith(".pdf"))) return;
    numberPagesFile = f;
    document.getElementById("numberpages-file-name").textContent = f.name;
    document.getElementById("numberpages-file-size").textContent = formatSize(f.size);
    document.getElementById("numberpages-file-info").hidden = false;
    document.getElementById("numberpages-options").hidden = false;
    document.getElementById("numberpages-actions").hidden = false;
});

function clearNumberPagesFile() {
    numberPagesFile = null;
    document.getElementById("numberpages-file-info").hidden = true;
    document.getElementById("numberpages-options").hidden = true;
    document.getElementById("numberpages-actions").hidden = true;
}

async function doNumberPages() {
    if (!numberPagesFile) return;
    const btn = document.getElementById("numberpages-btn");
    const err = document.getElementById("numberpages-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Processing...";

    const fd = new FormData();
    fd.append("file", numberPagesFile);
    fd.append("position", document.getElementById("numberpages-position").value);
    fd.append("start", document.getElementById("numberpages-start").value);
    try {
        const res = await fetch("/api/pdf/number-pages", { method: "POST", body: fd });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Processing failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
            const name = match ? match[1] : "numbered.pdf";
            downloadBlob(blob, name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Number Pages';
}

/* ── Helpers ── */
function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

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
