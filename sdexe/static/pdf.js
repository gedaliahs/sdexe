/* ── State ── */
let mergeFiles = [];
let splitFile = null;
let imgFiles = [];

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
