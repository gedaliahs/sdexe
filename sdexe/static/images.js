/* ── State ── */
let resizeFiles = [];
let compressFiles = [];
let iconvertFiles = [];
let cropFile = null;
let rotateFiles = [];
let stripExifFile = null;
let toIcoFile = null;
let flipFiles = [];
let grayscaleFiles = [];
let blurFiles = [];

/* ── Hash Routing ── */
function showTab(tab) {
    document.querySelectorAll(".pdf-section").forEach(s => s.classList.remove("active"));
    const el = document.getElementById("tab-" + tab);
    (el || document.querySelector(".pdf-section")).classList.add("active");
    window.scrollTo(0, 0);
}
showTab(location.hash.slice(1) || "resize");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "resize"));

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

/* ── Resize ── */
setupDropZone("resize-drop", "resize-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) resizeFiles.push(f);
    }
    renderResizeList();
});

function renderResizeList() {
    const list = document.getElementById("resize-file-list");
    list.innerHTML = "";
    resizeFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        const thumb = URL.createObjectURL(f);
        div.innerHTML = `
            <img class="img-thumb" src="${thumb}" alt="">
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeResizeFile(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    const hasFiles = resizeFiles.length > 0;
    document.getElementById("resize-file-info").hidden = !hasFiles;
    document.getElementById("resize-options").hidden = !hasFiles;
    document.getElementById("resize-actions").hidden = !hasFiles;
    if (resizeFiles.length === 1) {
        document.getElementById("resize-file-name").textContent = resizeFiles[0].name;
        document.getElementById("resize-file-size").textContent = formatSize(resizeFiles[0].size);
        const img = new window.Image();
        img.onload = () => {
            document.getElementById("resize-dimensions").textContent = `${img.width} × ${img.height}`;
        };
        img.src = URL.createObjectURL(resizeFiles[0]);
    } else if (resizeFiles.length > 1) {
        document.getElementById("resize-file-name").textContent = `${resizeFiles.length} images`;
        document.getElementById("resize-file-size").textContent = formatSize(resizeFiles.reduce((s, f) => s + f.size, 0));
        document.getElementById("resize-dimensions").textContent = "";
    }
}

function removeResizeFile(i) {
    resizeFiles.splice(i, 1);
    renderResizeList();
}

function clearResizeFile() {
    resizeFiles = [];
    renderResizeList();
}

function toggleResizeMode() {
    const mode = document.getElementById("resize-mode").value;
    document.getElementById("resize-dim-fields").hidden = mode === "percentage";
    document.getElementById("resize-pct-field").hidden = mode === "dimensions";
}

async function doResize() {
    if (!resizeFiles.length) return;
    const btn = document.getElementById("resize-btn");
    const err = document.getElementById("resize-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Resizing...";

    const form = new FormData();
    resizeFiles.forEach(f => form.append("files", f));
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
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?$/);
            const name = ct.includes("zip") ? "resized_images.zip" : (match ? match[1] : "resized.png");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Resize Images`;
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
            showToast("Saved: " + name);
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
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert Images`;
}

/* ── Crop ── */
setupDropZone("crop-drop", "crop-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    cropFile = f;
    const thumb = URL.createObjectURL(f);
    document.getElementById("crop-thumb").src = thumb;
    document.getElementById("crop-file-name").textContent = f.name;
    document.getElementById("crop-file-info").hidden = false;
    document.getElementById("crop-options").hidden = false;
    document.getElementById("crop-actions").hidden = false;
    const img = new window.Image();
    img.onload = () => {
        document.getElementById("crop-dimensions").textContent = `${img.width} × ${img.height}`;
        document.getElementById("crop-right").placeholder = img.width;
        document.getElementById("crop-bottom").placeholder = img.height;
    };
    img.src = thumb;
});

function clearCropFile() {
    cropFile = null;
    document.getElementById("crop-file-info").hidden = true;
    document.getElementById("crop-options").hidden = true;
    document.getElementById("crop-actions").hidden = true;
    document.getElementById("crop-dimensions").textContent = "";
}

async function doCrop() {
    if (!cropFile) return;
    const btn = document.getElementById("crop-btn");
    const err = document.getElementById("crop-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Cropping...";

    const form = new FormData();
    form.append("file", cropFile);
    form.append("left", document.getElementById("crop-left").value || "0");
    form.append("top", document.getElementById("crop-top").value || "0");
    form.append("right", document.getElementById("crop-right").value || "0");
    form.append("bottom", document.getElementById("crop-bottom").value || "0");

    try {
        const res = await fetch("/api/images/crop", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Crop failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = cropFile.name.replace(/\.[^.]+$/, "");
            const ext = cropFile.name.split(".").pop();
            downloadBlob(blob, `${base}_cropped.${ext}`);
            showToast("Saved: " + base + "_cropped." + ext);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Crop Image`;
}

/* ── Rotate ── */
setupDropZone("rotate-drop", "rotate-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) rotateFiles.push(f);
    }
    renderRotateList();
});

function renderRotateList() {
    const list = document.getElementById("rotate-file-list");
    list.innerHTML = "";
    rotateFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        const thumb = URL.createObjectURL(f);
        div.innerHTML = `
            <img class="img-thumb" src="${thumb}" alt="">
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeRotateFile(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    document.getElementById("rotate-options").hidden = rotateFiles.length === 0;
    document.getElementById("rotate-actions").hidden = rotateFiles.length === 0;
}

function removeRotateFile(i) { rotateFiles.splice(i, 1); renderRotateList(); }
function clearRotateFile() { rotateFiles = []; renderRotateList(); }

async function doRotate() {
    if (!rotateFiles.length) return;
    const btn = document.getElementById("rotate-btn");
    const err = document.getElementById("rotate-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Rotating...";

    const form = new FormData();
    rotateFiles.forEach(f => form.append("files", f));
    form.append("angle", document.getElementById("rotate-angle").value);

    try {
        const res = await fetch("/api/images/rotate", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Rotation failed";
            err.hidden = false;
        } else {
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?$/);
            const name = ct.includes("zip") ? "rotated_images.zip" : (match ? match[1] : "rotated.png");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Rotate Images`;
}

/* ── Strip EXIF ── */
setupDropZone("stripexif-drop", "stripexif-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    stripExifFile = f;
    document.getElementById("stripexif-thumb").src = URL.createObjectURL(f);
    document.getElementById("stripexif-file-name").textContent = f.name;
    document.getElementById("stripexif-file-size").textContent = formatSize(f.size);
    document.getElementById("stripexif-file-info").hidden = false;
    document.getElementById("stripexif-actions").hidden = false;
});

function clearStripExifFile() {
    stripExifFile = null;
    document.getElementById("stripexif-file-info").hidden = true;
    document.getElementById("stripexif-actions").hidden = true;
}

async function doStripExif() {
    if (!stripExifFile) return;
    const btn = document.getElementById("stripexif-btn");
    const err = document.getElementById("stripexif-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Stripping...";

    const form = new FormData();
    form.append("file", stripExifFile);

    try {
        const res = await fetch("/api/images/strip-exif", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Failed to strip EXIF";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = stripExifFile.name.replace(/\.[^.]+$/, "");
            const ext = stripExifFile.name.split(".").pop();
            downloadBlob(blob, `${base}_clean.${ext}`);
            showToast("Saved: " + base + "_clean." + ext);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Strip EXIF`;
}

/* ── To ICO ── */
setupDropZone("toico-drop", "toico-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    toIcoFile = f;
    document.getElementById("toico-thumb").src = URL.createObjectURL(f);
    document.getElementById("toico-file-name").textContent = f.name;
    document.getElementById("toico-file-info").hidden = false;
    document.getElementById("toico-options").hidden = false;
    document.getElementById("toico-actions").hidden = false;
});

function clearToIcoFile() {
    toIcoFile = null;
    document.getElementById("toico-file-info").hidden = true;
    document.getElementById("toico-options").hidden = true;
    document.getElementById("toico-actions").hidden = true;
}

async function doToIco() {
    if (!toIcoFile) return;
    const btn = document.getElementById("toico-btn");
    const err = document.getElementById("toico-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const checked = [...document.querySelectorAll(".ico-size:checked")].map(cb => cb.value);
    if (!checked.length) {
        err.textContent = "Select at least one size";
        err.hidden = false;
        btn.disabled = false;
        btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to ICO`;
        return;
    }

    const form = new FormData();
    form.append("file", toIcoFile);
    form.append("sizes", checked.join(","));

    try {
        const res = await fetch("/api/images/to-ico", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = toIcoFile.name.replace(/\.[^.]+$/, "");
            downloadBlob(blob, `${base}.ico`);
            showToast("Saved: " + base + ".ico");
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to ICO`;
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

/* ── Flip ── */
setupDropZone("flip-drop", "flip-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) flipFiles.push(f);
    }
    renderFlipList();
});

function renderFlipList() {
    const list = document.getElementById("flip-file-list");
    list.innerHTML = "";
    flipFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        const thumb = URL.createObjectURL(f);
        div.innerHTML = `
            <img class="img-thumb" src="${thumb}" alt="">
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeFlipFile(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    document.getElementById("flip-options").hidden = flipFiles.length === 0;
    document.getElementById("flip-actions").hidden = flipFiles.length === 0;
}

function removeFlipFile(i) { flipFiles.splice(i, 1); renderFlipList(); }
function clearFlipFile() { flipFiles = []; renderFlipList(); }

async function doFlip() {
    if (!flipFiles.length) return;
    const btn = document.getElementById("flip-btn");
    const err = document.getElementById("flip-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Flipping...";

    const form = new FormData();
    flipFiles.forEach(f => form.append("files", f));
    form.append("direction", document.getElementById("flip-direction").value);

    try {
        const res = await fetch("/api/images/flip", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Flip failed";
            err.hidden = false;
        } else {
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?$/);
            const name = ct.includes("zip") ? "flipped_images.zip" : (match ? match[1] : "flipped.png");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Flip Images`;
}

/* ── Grayscale ── */
setupDropZone("grayscale-drop", "grayscale-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) grayscaleFiles.push(f);
    }
    renderGrayscaleList();
});

function renderGrayscaleList() {
    const list = document.getElementById("grayscale-file-list");
    list.innerHTML = "";
    grayscaleFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        const thumb = URL.createObjectURL(f);
        div.innerHTML = `
            <img class="img-thumb" src="${thumb}" alt="">
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeGrayscaleFile(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    document.getElementById("grayscale-actions").hidden = grayscaleFiles.length === 0;
}

function removeGrayscaleFile(i) { grayscaleFiles.splice(i, 1); renderGrayscaleList(); }
function clearGrayscaleFile() { grayscaleFiles = []; renderGrayscaleList(); }

async function doGrayscale() {
    if (!grayscaleFiles.length) return;
    const btn = document.getElementById("grayscale-btn");
    const err = document.getElementById("grayscale-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Converting...";

    const form = new FormData();
    grayscaleFiles.forEach(f => form.append("files", f));

    try {
        const res = await fetch("/api/images/grayscale", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Conversion failed";
            err.hidden = false;
        } else {
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?$/);
            const name = ct.includes("zip") ? "grayscale_images.zip" : (match ? match[1] : "grayscale.png");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Convert to Grayscale`;
}

/* ── QR Code Generator ── */
let qrBlobUrl = null;

async function doQrGenerate() {
    const text = document.getElementById("qr-text").value.trim();
    const btn = document.getElementById("qr-btn");
    const err = document.getElementById("qr-error");
    err.hidden = true;

    if (!text) {
        err.textContent = "Enter text or a URL";
        err.hidden = false;
        return;
    }

    btn.disabled = true;
    btn.textContent = "Generating...";

    try {
        const res = await fetch("/api/images/qr-generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text: text,
                size: parseInt(document.getElementById("qr-size").value),
                error_correction: document.getElementById("qr-ec").value,
                fill_color: document.getElementById("qr-fill").value,
                back_color: document.getElementById("qr-back").value,
            }),
        });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Generation failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            if (qrBlobUrl) URL.revokeObjectURL(qrBlobUrl);
            qrBlobUrl = URL.createObjectURL(blob);
            document.getElementById("qr-img").src = qrBlobUrl;
            document.getElementById("qr-preview").hidden = false;
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }

    btn.disabled = false;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> Generate QR Code';
}

function downloadQr() {
    if (!qrBlobUrl) return;
    const a = document.createElement("a");
    a.href = qrBlobUrl;
    a.download = "qrcode.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast("Saved: qrcode.png");
}

/* ── Blur ── */
setupDropZone("blur-drop", "blur-input", files => {
    for (const f of files) {
        if (f.type.startsWith("image/")) blurFiles.push(f);
    }
    renderBlurList();
});

function renderBlurList() {
    const list = document.getElementById("blur-file-list");
    list.innerHTML = "";
    blurFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        const thumb = URL.createObjectURL(f);
        div.innerHTML = `
            <img class="img-thumb" src="${thumb}" alt="">
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeBlurFile(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    document.getElementById("blur-options").hidden = blurFiles.length === 0;
    document.getElementById("blur-actions").hidden = blurFiles.length === 0;
}

function removeBlurFile(i) { blurFiles.splice(i, 1); renderBlurList(); }
function clearBlurFile() { blurFiles = []; renderBlurList(); }

async function doBlur() {
    if (!blurFiles.length) return;
    const btn = document.getElementById("blur-btn");
    const err = document.getElementById("blur-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Applying blur...";

    const form = new FormData();
    blurFiles.forEach(f => form.append("files", f));
    form.append("radius", document.getElementById("blur-radius").value);

    try {
        const res = await fetch("/api/images/blur", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Blur failed";
            err.hidden = false;
        } else {
            const ct = res.headers.get("content-type") || "";
            const blob = await res.blob();
            const cd = res.headers.get("content-disposition") || "";
            const match = cd.match(/filename="?(.+?)"?$/);
            const name = ct.includes("zip") ? "blurred_images.zip" : (match ? match[1] : "blurred.png");
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Apply Blur`;
}

/* ── Image Watermark ── */
let imgWmFile = null;

setupDropZone("imgwm-drop", "imgwm-input", files => {
    const f = files[0];
    if (!f || !f.type.startsWith("image/")) return;
    imgWmFile = f;
    document.getElementById("imgwm-thumb").src = URL.createObjectURL(f);
    document.getElementById("imgwm-file-name").textContent = f.name;
    document.getElementById("imgwm-file-info").hidden = false;
    document.getElementById("imgwm-options").hidden = false;
    document.getElementById("imgwm-actions").hidden = false;
});

function clearImgWmFile() {
    imgWmFile = null;
    document.getElementById("imgwm-file-info").hidden = true;
    document.getElementById("imgwm-options").hidden = true;
    document.getElementById("imgwm-actions").hidden = true;
}

async function doImgWatermark() {
    if (!imgWmFile) return;
    const text = document.getElementById("imgwm-text").value.trim();
    if (!text) {
        const err = document.getElementById("imgwm-error");
        err.textContent = "Enter watermark text";
        err.hidden = false;
        return;
    }
    const btn = document.getElementById("imgwm-btn");
    const err = document.getElementById("imgwm-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Watermarking...";

    const form = new FormData();
    form.append("file", imgWmFile);
    form.append("text", text);
    form.append("position", document.getElementById("imgwm-position").value);
    form.append("font_size", document.getElementById("imgwm-fontsize").value);
    form.append("opacity", document.getElementById("imgwm-opacity").value);

    try {
        const res = await fetch("/api/images/watermark", { method: "POST", body: form });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Watermark failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            const base = imgWmFile.name.replace(/\.[^.]+$/, "");
            const ext = imgWmFile.name.split(".").pop();
            downloadBlob(blob, `${base}_watermarked.${ext}`);
            showToast("Saved: " + base + "_watermarked." + ext);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Add Watermark`;
}

/* ── Placeholder Image ── */
let phBlobUrl = null;

async function doPlaceholder() {
    const btn = document.getElementById("ph-btn");
    const err = document.getElementById("ph-error");
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = "Generating...";

    const width = parseInt(document.getElementById("ph-width").value) || 800;
    const height = parseInt(document.getElementById("ph-height").value) || 600;
    const bgColor = document.getElementById("ph-bg").value;
    const textColor = document.getElementById("ph-text-color").value;
    const text = document.getElementById("ph-text").value.trim();

    try {
        const res = await fetch("/api/images/placeholder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ width, height, bg_color: bgColor, text_color: textColor, text }),
        });
        if (!res.ok) {
            const data = await res.json();
            err.textContent = data.error || "Generation failed";
            err.hidden = false;
        } else {
            const blob = await res.blob();
            if (phBlobUrl) URL.revokeObjectURL(phBlobUrl);
            phBlobUrl = URL.createObjectURL(blob);
            document.getElementById("ph-img").src = phBlobUrl;
            document.getElementById("ph-preview").hidden = false;
            downloadBlob(blob, `placeholder_${width}x${height}.png`);
            showToast(`Saved: placeholder_${width}x${height}.png`);
        }
    } catch {
        err.textContent = "Network error";
        err.hidden = false;
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg> Generate Image`;
}
