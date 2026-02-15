/* ── State ── */
let resizeFile = null;
let compressFiles = [];
let iconvertFiles = [];

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

/* ── Resize ── */
setupDropZone("resize-drop", "resize-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    resizeFile = f;

    document.getElementById("resize-file-name").textContent = f.name;
    document.getElementById("resize-file-size").textContent = formatSize(f.size);
    document.getElementById("resize-file-info").hidden = false;
    document.getElementById("resize-options").hidden = false;
    document.getElementById("resize-actions").hidden = false;

    const thumb = document.getElementById("resize-thumb");
    thumb.src = URL.createObjectURL(f);

    // Read original dimensions
    const img = new window.Image();
    img.onload = () => {
        document.getElementById("resize-dimensions").textContent = `${img.width} × ${img.height}`;
    };
    img.src = URL.createObjectURL(f);
});

function clearResizeFile() {
    resizeFile = null;
    document.getElementById("resize-file-info").hidden = true;
    document.getElementById("resize-options").hidden = true;
    document.getElementById("resize-actions").hidden = true;
}

function toggleResizeMode() {
    const mode = document.getElementById("resize-mode").value;
    document.getElementById("resize-dim-fields").hidden = mode === "percentage";
    document.getElementById("resize-pct-field").hidden = mode === "dimensions";
}

async function doResize() {
    if (!resizeFile) return;
    const btn = document.getElementById("resize-btn");
    const err = document.getElementById("resize-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Resizing...";

    const form = new FormData();
    form.append("file", resizeFile);
    form.append("mode", document.getElementById("resize-mode").value);
    form.append("width", document.getElementById("resize-width").value);
    form.append("height", document.getElementById("resize-height").value);
    form.append("percentage", document.getElementById("resize-percentage").value);
    form.append("maintain_aspect", document.getElementById("resize-aspect").checked ? "true" : "false");

    try {
        const res = await fetch("/api/images/resize", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Resize failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?$/);
            downloadBlob(blob, match ? match[1] : "resized.png");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Resize Image`;
}

/* ── Compress ── */
setupDropZone("compress-drop", "compress-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) {
            compressFiles.push(f);
        }
    }
    renderCompressList();
});

function renderCompressList() {
    const list = document.getElementById("compress-list");
    list.innerHTML = "";
    compressFiles.forEach((f, i) => {
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
            <button class="file-remove" onclick="removeCompressFile(${i})">&times;</button>
        `;
        setupDragItem(div, compressFiles, renderCompressList);
        list.appendChild(div);
    });
    document.getElementById("compress-options").hidden = compressFiles.length === 0;
    document.getElementById("compress-actions").hidden = compressFiles.length === 0;
}

function removeCompressFile(i) {
    compressFiles.splice(i, 1);
    renderCompressList();
}

async function doCompress() {
    const btn = document.getElementById("compress-btn");
    const err = document.getElementById("compress-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Compressing...";

    const form = new FormData();
    compressFiles.forEach(f => form.append("files", f));
    form.append("quality", document.getElementById("compress-quality").value);

    try {
        const res = await fetch("/api/images/compress", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Compression failed";
            err.hidden = false;
        } else {
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const name = ct.includes("zip") ? "compressed_images.zip" : "compressed.jpg";
            downloadBlob(blob, name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Compress Images`;
}

/* ── Convert Format ── */
setupDropZone("iconvert-drop", "iconvert-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) {
            iconvertFiles.push(f);
        }
    }
    renderIconvertList();
});

function renderIconvertList() {
    const list = document.getElementById("iconvert-list");
    list.innerHTML = "";
    iconvertFiles.forEach((f, i) => {
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
            <button class="file-remove" onclick="removeIconvertFile(${i})">&times;</button>
        `;
        setupDragItem(div, iconvertFiles, renderIconvertList);
        list.appendChild(div);
    });
    document.getElementById("iconvert-options").hidden = iconvertFiles.length === 0;
    document.getElementById("iconvert-actions").hidden = iconvertFiles.length === 0;
}

function removeIconvertFile(i) {
    iconvertFiles.splice(i, 1);
    renderIconvertList();
}

async function doImageConvert() {
    const btn = document.getElementById("iconvert-btn");
    const err = document.getElementById("iconvert-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    iconvertFiles.forEach(f => form.append("files", f));
    form.append("format", document.getElementById("iconvert-format").value);

    try {
        const res = await fetch("/api/images/convert", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const fmt = document.getElementById("iconvert-format").value;
            const name = ct.includes("zip") ? `converted_${fmt}.zip` : `converted.${fmt}`;
            downloadBlob(blob, name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert Images`;
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
