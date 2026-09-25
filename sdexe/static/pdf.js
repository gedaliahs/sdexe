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
let watermarkFile = null;
let reorderFile = null;
let deletePagesFile = null;
let metadataFile = null;

/* ── Hash Routing ── */
showTab(location.hash.slice(1) || "merge");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "merge"));

setupPageDropOverlay();

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

/* ── Watermark ── */
setupDropZone("watermark-drop", "watermark-input", files => {
    const f = files[0];
    if (!f || (!f.type.includes("pdf") && !f.name.endsWith(".pdf"))) return;
    watermarkFile = f;
    document.getElementById("watermark-file-name").textContent = f.name;
    document.getElementById("watermark-file-size").textContent = formatSize(f.size);
    document.getElementById("watermark-file-info").hidden = false;
    document.getElementById("watermark-options").hidden = false;
    document.getElementById("watermark-actions").hidden = false;
});

document.getElementById("watermark-opacity").addEventListener("input", function() {
    document.getElementById("watermark-opacity-val").textContent = this.value;
});

function clearWatermarkFile() {
    watermarkFile = null;
    document.getElementById("watermark-file-info").hidden = true;
    document.getElementById("watermark-options").hidden = true;
    document.getElementById("watermark-actions").hidden = true;
    document.getElementById("watermark-text").value = "";
}

async function doWatermark() {
    if (!watermarkFile) return;
    const text = document.getElementById("watermark-text").value.trim();
    if (!text) { document.getElementById("watermark-error").textContent = "Enter watermark text"; document.getElementById("watermark-error").hidden = false; return; }
    const btn = document.getElementById("watermark-btn");
    const err = document.getElementById("watermark-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Processing...";

    const form = new FormData();
    form.append("file", watermarkFile);
    form.append("text", text);
    form.append("font_size", document.getElementById("watermark-fontsize").value);
    form.append("opacity", document.getElementById("watermark-opacity").value);
    form.append("position", document.getElementById("watermark-position").value);

    try {
        const res = await fetch("/api/pdf/watermark", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Watermark failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = watermarkFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_watermarked.pdf");
            showToast("Saved: " + base + "_watermarked.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Add Watermark';
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

/* ── Reorder Pages ── */
setupDropZone("reorder-drop", "reorder-input", async files => {
    const f = files[0];
    if (!f) return;
    reorderFile = f;
    document.getElementById("reorder-file-name").textContent = f.name;
    document.getElementById("reorder-file-info").hidden = false;
    document.getElementById("reorder-options").hidden = false;
    document.getElementById("reorder-actions").hidden = false;

    const form = new FormData();
    form.append("file", f);
    try {
        const res = await fetch("/api/pdf/page-count", { method: "POST", body: form });
        const data = await res.json();
        if (data.pages) {
            document.getElementById("reorder-page-count").textContent = `${data.pages} pages`;
        }
    } catch {}
});

function clearReorderFile() {
    reorderFile = null;
    document.getElementById("reorder-file-info").hidden = true;
    document.getElementById("reorder-options").hidden = true;
    document.getElementById("reorder-actions").hidden = true;
    document.getElementById("reorder-page-count").textContent = "";
    document.getElementById("reorder-order").value = "";
}

async function doReorder() {
    if (!reorderFile) return;
    const order = document.getElementById("reorder-order").value.trim();
    if (!order) { document.getElementById("reorder-error").textContent = "Enter a page order"; document.getElementById("reorder-error").hidden = false; return; }
    const btn = document.getElementById("reorder-btn");
    const err = document.getElementById("reorder-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Reordering...";

    const form = new FormData();
    form.append("file", reorderFile);
    form.append("order", order);

    try {
        const res = await fetch("/api/pdf/reorder", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Reorder failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = reorderFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_reordered.pdf");
            showToast("Saved: " + base + "_reordered.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Reorder Pages`;
}

/* ── Delete Pages ── */
setupDropZone("deletepages-drop", "deletepages-input", async files => {
    const f = files[0];
    if (!f) return;
    deletePagesFile = f;
    document.getElementById("deletepages-file-name").textContent = f.name;
    document.getElementById("deletepages-file-info").hidden = false;
    document.getElementById("deletepages-options").hidden = false;
    document.getElementById("deletepages-actions").hidden = false;

    const form = new FormData();
    form.append("file", f);
    try {
        const res = await fetch("/api/pdf/page-count", { method: "POST", body: form });
        const data = await res.json();
        if (data.pages) {
            document.getElementById("deletepages-page-count").textContent = `${data.pages} pages`;
        }
    } catch {}
});

function clearDeletePagesFile() {
    deletePagesFile = null;
    document.getElementById("deletepages-file-info").hidden = true;
    document.getElementById("deletepages-options").hidden = true;
    document.getElementById("deletepages-actions").hidden = true;
    document.getElementById("deletepages-page-count").textContent = "";
    document.getElementById("deletepages-pages").value = "";
}

async function doDeletePages() {
    if (!deletePagesFile) return;
    const pages = document.getElementById("deletepages-pages").value.trim();
    if (!pages) { document.getElementById("deletepages-error").textContent = "Enter pages to delete"; document.getElementById("deletepages-error").hidden = false; return; }
    const btn = document.getElementById("deletepages-btn");
    const err = document.getElementById("deletepages-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Deleting...";

    const form = new FormData();
    form.append("file", deletePagesFile);
    form.append("pages", pages);

    try {
        const res = await fetch("/api/pdf/delete-pages", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Delete failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = deletePagesFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_deleted.pdf");
            showToast("Saved: " + base + "_deleted.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Delete Pages`;
}

/* ── Edit Metadata ── */
setupDropZone("metadata-drop", "metadata-input", async files => {
    const f = files[0];
    if (!f) return;
    metadataFile = f;
    document.getElementById("metadata-file-name").textContent = f.name;
    document.getElementById("metadata-file-size").textContent = formatSize(f.size);
    document.getElementById("metadata-file-info").hidden = false;
    document.getElementById("metadata-options").hidden = false;
    document.getElementById("metadata-actions").hidden = false;

    // Auto-fetch existing metadata
    const form = new FormData();
    form.append("file", f);
    form.append("action", "get");
    try {
        const res = await fetch("/api/pdf/metadata", { method: "POST", body: form });
        if (res.ok) {
            const data = await res.json();
            document.getElementById("metadata-title").value = data.title || "";
            document.getElementById("metadata-author").value = data.author || "";
            document.getElementById("metadata-subject").value = data.subject || "";
            document.getElementById("metadata-creator").value = data.creator || "";
        }
    } catch {}
});

function clearMetadataFile() {
    metadataFile = null;
    document.getElementById("metadata-file-info").hidden = true;
    document.getElementById("metadata-options").hidden = true;
    document.getElementById("metadata-actions").hidden = true;
    document.getElementById("metadata-title").value = "";
    document.getElementById("metadata-author").value = "";
    document.getElementById("metadata-subject").value = "";
    document.getElementById("metadata-creator").value = "";
}

async function doSaveMetadata() {
    if (!metadataFile) return;
    const btn = document.getElementById("metadata-btn");
    const err = document.getElementById("metadata-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Saving...";

    const form = new FormData();
    form.append("file", metadataFile);
    form.append("action", "set");
    form.append("title", document.getElementById("metadata-title").value);
    form.append("author", document.getElementById("metadata-author").value);
    form.append("subject", document.getElementById("metadata-subject").value);
    form.append("creator", document.getElementById("metadata-creator").value);

    try {
        const res = await fetch("/api/pdf/metadata", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Metadata update failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = metadataFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_metadata.pdf");
            showToast("Saved: " + base + "_metadata.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Save Metadata`;
}

/* ── PDF → Images ── */
let pdf2ImagesFile = null;

setupDropZone("pdf2images-drop", "pdf2images-input", async files => {
    const f = files[0];
    if (!f || (!f.type.includes("pdf") && !f.name.toLowerCase().endsWith(".pdf"))) return;
    pdf2ImagesFile = f;
    document.getElementById("pdf2images-file-name").textContent = f.name;
    document.getElementById("pdf2images-file-size").textContent = formatSize(f.size);
    document.getElementById("pdf2images-file-info").hidden = false;
    document.getElementById("pdf2images-options").hidden = false;
    document.getElementById("pdf2images-actions").hidden = false;
    fetchPageCount(f, "pdf2images-page-count");
});

function clearPdf2ImagesFile() {
    pdf2ImagesFile = null;
    document.getElementById("pdf2images-file-info").hidden = true;
    document.getElementById("pdf2images-options").hidden = true;
    document.getElementById("pdf2images-actions").hidden = true;
    document.getElementById("pdf2images-page-count").textContent = "";
    document.getElementById("pdf2images-pages").value = "";
}

async function doPdf2Images() {
    if (!pdf2ImagesFile) return;
    const btn = document.getElementById("pdf2images-btn");
    const err = document.getElementById("pdf2images-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Rendering...";

    const fmt = document.getElementById("pdf2images-format").value;
    const form = new FormData();
    form.append("file", pdf2ImagesFile);
    form.append("format", fmt);
    form.append("dpi", document.getElementById("pdf2images-dpi").value);
    const pagesVal = document.getElementById("pdf2images-pages").value.trim();
    form.append("pages", pagesVal || "all");

    try {
        const res = await fetch("/api/pdf/to-images", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = pdf2ImagesFile.name.replace(/\.pdf$/i, "");
            const name = blob.type === "application/zip" ? base + "_pages.zip" : filenameFromResponse(res, base + "." + fmt);
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to Images`;
}

/* ── OCR ── */
let ocrFile = null;

setupDropZone("ocr-drop", "ocr-input", files => {
    const f = files[0];
    if (!f) return;
    ocrFile = f;
    document.getElementById("ocr-file-name").textContent = f.name;
    document.getElementById("ocr-file-size").textContent = formatSize(f.size);
    document.getElementById("ocr-file-info").hidden = false;
    document.getElementById("ocr-options").hidden = false;
    document.getElementById("ocr-actions").hidden = false;
    document.getElementById("ocr-result").hidden = true;
    document.getElementById("ocr-output").value = "";
});

function clearOcrFile() {
    ocrFile = null;
    document.getElementById("ocr-file-info").hidden = true;
    document.getElementById("ocr-options").hidden = true;
    document.getElementById("ocr-actions").hidden = true;
    document.getElementById("ocr-result").hidden = true;
    document.getElementById("ocr-output").value = "";
}

async function doOcr() {
    if (!ocrFile) return;
    const btn = document.getElementById("ocr-btn");
    const err = document.getElementById("ocr-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Recognising...";

    const form = new FormData();
    form.append("file", ocrFile);
    form.append("language", document.getElementById("ocr-language").value);

    try {
        const res = await fetch("/api/pdf/ocr", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) {
            err.textContent = data.error || "OCR failed";
            err.hidden = false;
        } else {
            document.getElementById("ocr-output").value = data.text || "";
            document.getElementById("ocr-result-meta").textContent =
                data.pages + (data.pages === 1 ? " page" : " pages") + " · " + (data.text || "").length + " chars";
            document.getElementById("ocr-result").hidden = false;
            showToast("OCR complete: " + data.pages + (data.pages === 1 ? " page" : " pages"));
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Run OCR`;
}

function copyOcrText(btn) {
    const el = document.getElementById("ocr-output");
    navigator.clipboard.writeText(el.value).then(() => {
        btn.classList.add("copied");
        const orig = btn.innerHTML;
        btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
        setTimeout(() => { btn.classList.remove("copied"); btn.innerHTML = orig; }, 1500);
    }).catch(() => {
        el.select();
        document.execCommand("copy");
    });
}

function downloadOcrText() {
    const text = document.getElementById("ocr-output").value;
    const base = ocrFile ? ocrFile.name.replace(/\.[^.]+$/, "") : "ocr";
    downloadBlob(new Blob([text], { type: "text/plain;charset=utf-8" }), base + "_ocr.txt");
    showToast("Saved: " + base + "_ocr.txt");
}

/* ── Office → PDF ── */
let office2PdfFile = null;

setupDropZone("office2pdf-drop", "office2pdf-input", files => {
    const f = files[0];
    if (!f) return;
    office2PdfFile = f;
    document.getElementById("office2pdf-file-name").textContent = f.name;
    document.getElementById("office2pdf-file-size").textContent = formatSize(f.size);
    document.getElementById("office2pdf-file-info").hidden = false;
    document.getElementById("office2pdf-actions").hidden = false;
});

function clearOffice2PdfFile() {
    office2PdfFile = null;
    document.getElementById("office2pdf-file-info").hidden = true;
    document.getElementById("office2pdf-actions").hidden = true;
}

async function doOffice2Pdf() {
    if (!office2PdfFile) return;
    const btn = document.getElementById("office2pdf-btn");
    const err = document.getElementById("office2pdf-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    form.append("file", office2PdfFile);

    try {
        const res = await fetch("/api/pdf/from-office", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = office2PdfFile.name.replace(/\.[^.]+$/, "");
            downloadBlob(blob, base + ".pdf");
            showToast("Saved: " + base + ".pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to PDF`;
}

/* ── Stamp Image ── */
let stampFile = null;
let stampImage = null;

setupDropZone("stamp-drop", "stamp-input", files => {
    const f = files[0];
    if (!f || (!f.type.includes("pdf") && !f.name.toLowerCase().endsWith(".pdf"))) return;
    stampFile = f;
    document.getElementById("stamp-file-name").textContent = f.name;
    document.getElementById("stamp-file-size").textContent = formatSize(f.size);
    document.getElementById("stamp-file-info").hidden = false;
    document.getElementById("stamp-options").hidden = false;
    document.getElementById("stamp-actions").hidden = false;
    fetchPageCount(f, "stamp-page-count");
});

setupDropZone("stamp-image-drop", "stamp-image-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    stampImage = f;
    document.getElementById("stamp-image-name").textContent = f.name;
    document.getElementById("stamp-image-size").textContent = formatSize(f.size);
    document.getElementById("stamp-image-info").hidden = false;
    document.getElementById("stamp-image-drop").hidden = true;
});

document.getElementById("stamp-opacity").addEventListener("input", function() {
    document.getElementById("stamp-opacity-val").textContent = this.value;
});

function clearStampImage() {
    stampImage = null;
    document.getElementById("stamp-image-info").hidden = true;
    document.getElementById("stamp-image-drop").hidden = false;
}

function clearStampFile() {
    stampFile = null;
    clearStampImage();
    document.getElementById("stamp-file-info").hidden = true;
    document.getElementById("stamp-options").hidden = true;
    document.getElementById("stamp-actions").hidden = true;
    document.getElementById("stamp-page-count").textContent = "";
    document.getElementById("stamp-pages").value = "";
}

async function doStamp() {
    if (!stampFile) return;
    const err = document.getElementById("stamp-error");
    if (!stampImage) { err.textContent = "Choose an image to stamp"; err.hidden = false; return; }
    const btn = document.getElementById("stamp-btn");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Stamping...";

    const form = new FormData();
    form.append("file", stampFile);
    form.append("image", stampImage);
    form.append("position", document.getElementById("stamp-position").value);
    form.append("scale", document.getElementById("stamp-scale").value || "25");
    form.append("opacity", document.getElementById("stamp-opacity").value);
    const pagesVal = document.getElementById("stamp-pages").value.trim();
    form.append("pages", pagesVal || "all");

    try {
        const res = await fetch("/api/pdf/stamp", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Stamping failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = stampFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_stamped.pdf");
            showToast("Saved: " + base + "_stamped.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Stamp PDF`;
}

/* ── Resize Pages ── */
let pageSizeFile = null;

setupDropZone("pagesize-drop", "pagesize-input", files => {
    const f = files[0];
    if (!f || (!f.type.includes("pdf") && !f.name.toLowerCase().endsWith(".pdf"))) return;
    pageSizeFile = f;
    document.getElementById("pagesize-file-name").textContent = f.name;
    document.getElementById("pagesize-file-size").textContent = formatSize(f.size);
    document.getElementById("pagesize-file-info").hidden = false;
    document.getElementById("pagesize-options").hidden = false;
    document.getElementById("pagesize-actions").hidden = false;
    fetchPageCount(f, "pagesize-page-count");
});

function clearPageSizeFile() {
    pageSizeFile = null;
    document.getElementById("pagesize-file-info").hidden = true;
    document.getElementById("pagesize-options").hidden = true;
    document.getElementById("pagesize-actions").hidden = true;
    document.getElementById("pagesize-page-count").textContent = "";
}

async function doPageSize() {
    if (!pageSizeFile) return;
    const btn = document.getElementById("pagesize-btn");
    const err = document.getElementById("pagesize-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Resizing...";

    const size = document.getElementById("pagesize-size").value;
    const form = new FormData();
    form.append("file", pageSizeFile);
    form.append("size", size);
    form.append("fit", document.getElementById("pagesize-fit").value);

    try {
        const res = await fetch("/api/pdf/page-size", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Resize failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = pageSizeFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_" + size + ".pdf");
            showToast("Saved: " + base + "_" + size + ".pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Resize Pages`;
}

/* ── Flatten ── */
let flattenFile = null;

setupDropZone("flatten-drop", "flatten-input", files => {
    const f = files[0];
    if (!f || (!f.type.includes("pdf") && !f.name.toLowerCase().endsWith(".pdf"))) return;
    flattenFile = f;
    document.getElementById("flatten-file-name").textContent = f.name;
    document.getElementById("flatten-file-size").textContent = formatSize(f.size);
    document.getElementById("flatten-file-info").hidden = false;
    document.getElementById("flatten-actions").hidden = false;
    fetchPageCount(f, "flatten-page-count");
});

function clearFlattenFile() {
    flattenFile = null;
    document.getElementById("flatten-file-info").hidden = true;
    document.getElementById("flatten-actions").hidden = true;
    document.getElementById("flatten-page-count").textContent = "";
}

async function doFlatten() {
    if (!flattenFile) return;
    const btn = document.getElementById("flatten-btn");
    const err = document.getElementById("flatten-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Flattening...";

    const form = new FormData();
    form.append("file", flattenFile);

    try {
        const res = await fetch("/api/pdf/flatten", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Flatten failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = flattenFile.name.replace(/\.pdf$/i, "");
            downloadBlob(blob, base + "_flattened.pdf");
            showToast("Saved: " + base + "_flattened.pdf");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Flatten PDF`;
}

/* Fills a .count-badge with the page count of a PDF (best effort). */
async function fetchPageCount(file, badgeId) {
    const form = new FormData();
    form.append("file", file);
    try {
        const res = await fetch("/api/pdf/page-count", { method: "POST", body: form });
        const data = await res.json();
        if (data.pages) document.getElementById(badgeId).textContent = data.pages + (data.pages === 1 ? " page" : " pages");
    } catch {}
}

/* Reads the filename from a Content-Disposition header, or returns fallback. */
function filenameFromResponse(res, fallback) {
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    return m ? decodeURIComponent(m[1]) : fallback;
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
