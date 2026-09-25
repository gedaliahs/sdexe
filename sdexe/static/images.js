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
showTab(location.hash.slice(1) || "resize");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "resize"));

setupPageDropOverlay();

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
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
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
        // HEIC files often arrive with an empty MIME type; accept by extension too.
        if (f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name)) {
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
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
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
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
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
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
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
            const match = cd.match(/filename="?(.+?)"?(?:;|$)/);
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

/* ═══════════════════════════════════════════════════════════════
   images2: HEIC, Adjust, EXIF, Border, Favicon Set, Upscale,
   Collage, ASCII, Color Picker
   ═══════════════════════════════════════════════════════════════ */

const DL_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M12 3v14M5 12l7 7 7-7"/><path d="M5 21h14"/></svg>`;

function isHeicFile(f) {
    return /\.(heic|heif)$/i.test(f.name) || /^image\/hei[cf]$/i.test(f.type || "");
}
function isImageFile(f) {
    return (f.type && f.type.startsWith("image/")) || isHeicFile(f);
}
function fileBase(name) { return name.replace(/\.[^.]+$/, ""); }
function fileExt(name) { const m = name.match(/\.([^.]+)$/); return m ? m[1].toLowerCase() : "png"; }
function filenameFromResponse(res, fallback) {
    const cd = res.headers.get("content-disposition") || "";
    const m = cd.match(/filename\*?="?(?:UTF-8'')?([^";]+)"?/i);
    return m ? decodeURIComponent(m[1]) : fallback;
}
function setBtnWorking(btn, label) { btn.disabled = true; btn.textContent = label; }
function setBtnIdle(btn, label) { btn.disabled = false; btn.innerHTML = `${DL_ICON} ${label}`; }
function showErr(id, msg) { const el = document.getElementById(id); el.textContent = msg; el.hidden = false; }
function hideErr(id) { document.getElementById(id).hidden = true; }
function readDimensions(file, cb) {
    const img = new window.Image();
    const url = URL.createObjectURL(file);
    img.onload = () => { cb(img.width, img.height); URL.revokeObjectURL(url); };
    img.onerror = () => { cb(0, 0); URL.revokeObjectURL(url); };
    img.src = url;
}
function flashCopied(btn) {
    if (!btn) return;
    const orig = btn.innerHTML;
    btn.classList.add("copied");
    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
    setTimeout(() => { btn.classList.remove("copied"); btn.innerHTML = orig; }, 1500);
}
function copyString(text, btn) {
    navigator.clipboard.writeText(text).then(() => flashCopied(btn)).catch(() => {
        const ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); ta.remove(); flashCopied(btn);
    });
}

/* Generic single-file wiring: drop zone → file info row → options/actions.
   Returns a state object with .file that the doX() function reads. */
function setupSingleImageTool(prefix, opts = {}) {
    const state = { file: null };
    setupDropZone(`${prefix}-drop`, `${prefix}-input`, files => {
        const f = files[0];
        if (!f || !(opts.accept ? opts.accept(f) : isImageFile(f))) {
            showErr(`${prefix}-error`, "Please select an image file");
            return;
        }
        hideErr(`${prefix}-error`);
        state.file = f;
        const thumb = document.getElementById(`${prefix}-thumb`);
        if (thumb) thumb.src = URL.createObjectURL(f);
        document.getElementById(`${prefix}-file-name`).textContent = f.name;
        const sizeEl = document.getElementById(`${prefix}-file-size`);
        if (sizeEl) sizeEl.textContent = formatSize(f.size);
        const dimEl = document.getElementById(`${prefix}-dimensions`);
        if (dimEl) {
            dimEl.textContent = "";
            readDimensions(f, (w, h) => {
                if (w) dimEl.textContent = `${w} × ${h}`;
                state.width = w; state.height = h;
                if (opts.onDimensions) opts.onDimensions(w, h);
            });
        }
        document.getElementById(`${prefix}-file-info`).hidden = false;
        const o = document.getElementById(`${prefix}-options`); if (o) o.hidden = false;
        const a = document.getElementById(`${prefix}-actions`); if (a) a.hidden = false;
        if (opts.onFile) opts.onFile(f);
    });
    state.clear = () => {
        state.file = null;
        document.getElementById(`${prefix}-file-info`).hidden = true;
        const o = document.getElementById(`${prefix}-options`); if (o) o.hidden = true;
        const a = document.getElementById(`${prefix}-actions`); if (a) a.hidden = true;
        hideErr(`${prefix}-error`);
        if (opts.onClear) opts.onClear();
    };
    return state;
}

/* Generic POST → download for single-file tools. */
async function postAndDownload(url, form, btnId, errId, workingLabel, idleLabel, fallbackName, failMsg) {
    const btn = document.getElementById(btnId);
    hideErr(errId);
    setBtnWorking(btn, workingLabel);
    try {
        const res = await fetch(url, { method: "POST", body: form });
        if (!res.ok) {
            let msg = failMsg;
            try { const data = await res.json(); msg = data.error || failMsg; } catch {}
            showErr(errId, msg);
        } else {
            const blob = await res.blob();
            const name = filenameFromResponse(res, fallbackName);
            downloadBlob(blob, name);
            showToast("Saved: " + name);
        }
    } catch {
        showErr(errId, "Network error");
    }
    setBtnIdle(btn, idleLabel);
}

/* ── HEIC → JPG ── */
let heicFiles = [];

setupDropZone("heic-drop", "heic-input", files => {
    let rejected = 0;
    for (const f of files) {
        if (isHeicFile(f)) heicFiles.push(f); else rejected++;
    }
    if (rejected) showErr("heic-error", `${rejected} file(s) skipped: only .heic / .heif are accepted here`);
    else hideErr("heic-error");
    renderHeicList();
});

function renderHeicList() {
    const list = document.getElementById("heic-file-list");
    list.innerHTML = "";
    heicFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.innerHTML = `
            <span class="img-thumb" style="display:flex;align-items:center;justify-content:center;font-size:.6rem;font-weight:600;color:var(--text-muted);">HEIC</span>
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeHeicFile(${i})">&times;</button>
        `;
        list.appendChild(div);
    });
    document.getElementById("heic-options").hidden = heicFiles.length === 0;
    document.getElementById("heic-actions").hidden = heicFiles.length === 0;
    const btn = document.getElementById("heic-btn");
    if (!btn.disabled) btn.innerHTML = `${DL_ICON} Convert ${heicFiles.length > 1 ? heicFiles.length + " Files" : "HEIC"}`;
}

function removeHeicFile(i) { heicFiles.splice(i, 1); renderHeicList(); }
function clearHeicFiles() { heicFiles = []; renderHeicList(); }
function toggleHeicQuality() {
    document.getElementById("heic-quality-field").hidden = document.getElementById("heic-format").value !== "jpg";
}

async function doHeic() {
    if (!heicFiles.length) return;
    const fmt = document.getElementById("heic-format").value;
    const form = new FormData();
    heicFiles.forEach(f => form.append("files", f));
    form.append("format", fmt);
    form.append("quality", document.getElementById("heic-quality").value || "90");
    const fallback = heicFiles.length > 1 ? `heic_converted_${fmt}.zip` : `${fileBase(heicFiles[0].name)}.${fmt}`;
    await postAndDownload("/api/images/heic", form, "heic-btn", "heic-error",
        "Converting...", heicFiles.length > 1 ? `Convert ${heicFiles.length} Files` : "Convert HEIC",
        fallback, "HEIC conversion failed");
}

/* ── Adjust ── */
let adjustBeforeUrl = null;
const adjustState = setupSingleImageTool("adjust", {
    onFile: f => {
        if (adjustBeforeUrl) URL.revokeObjectURL(adjustBeforeUrl);
        adjustBeforeUrl = URL.createObjectURL(f);
        document.getElementById("adjust-before").src = adjustBeforeUrl;
        document.getElementById("adjust-after").src = adjustBeforeUrl;
        resetAdjust();
    },
    onClear: () => {
        document.getElementById("adjust-before").src = "";
        document.getElementById("adjust-after").src = "";
    },
});
function clearAdjustFile() { adjustState.clear(); }

function adjustValues() {
    const v = id => parseInt(document.getElementById(id).value, 10);
    return { brightness: v("adjust-brightness"), contrast: v("adjust-contrast"),
             saturation: v("adjust-saturation"), sharpness: v("adjust-sharpness") };
}

function updateAdjustPreview() {
    const vals = adjustValues();
    for (const k of Object.keys(vals)) {
        document.getElementById(`adjust-${k}-val`).textContent = vals[k] + "%";
    }
    // Client-side approximation via CSS filters; sharpness has no CSS filter
    // equivalent, so it is only applied by the server on download.
    const after = document.getElementById("adjust-after");
    after.style.filter = `brightness(${vals.brightness}%) contrast(${vals.contrast}%) saturate(${vals.saturation}%)`;
}

function resetAdjust() {
    for (const k of ["brightness", "contrast", "saturation", "sharpness"]) {
        document.getElementById(`adjust-${k}`).value = 100;
    }
    updateAdjustPreview();
}

async function doAdjust() {
    if (!adjustState.file) return;
    const vals = adjustValues();
    const form = new FormData();
    form.append("file", adjustState.file);
    for (const k of Object.keys(vals)) form.append(k, vals[k]);
    const f = adjustState.file;
    await postAndDownload("/api/images/adjust", form, "adjust-btn", "adjust-error",
        "Applying...", "Apply &amp; Download", `${fileBase(f.name)}_adjusted.${fileExt(f.name)}`, "Adjustment failed");
}

/* ── EXIF Viewer ── */
let exifJson = null;
const exifState = setupSingleImageTool("exif", {
    onFile: f => loadExif(f),
    onClear: () => { document.getElementById("exif-result").hidden = true; exifJson = null; },
});
function clearExifFile() { exifState.clear(); }

function exifRow(table, key, val, isSection) {
    const tr = document.createElement("tr");
    if (isSection) {
        tr.innerHTML = `<td class="kv-section" colspan="2">${esc(key)}</td>`;
    } else {
        let display;
        if (val === null || val === undefined) display = "";
        else if (typeof val === "object") display = JSON.stringify(val);
        else display = String(val);
        tr.innerHTML = `<td class="kv-key">${esc(key)}</td><td class="kv-val"></td>`;
        const td = tr.lastElementChild;
        if (typeof val === "string" && /^https?:\/\//.test(val)) {
            const a = document.createElement("a");
            a.href = val; a.target = "_blank"; a.rel = "noopener"; a.textContent = val;
            td.appendChild(a);
        } else {
            td.textContent = display;
        }
    }
    table.appendChild(tr);
}

async function loadExif(file) {
    const result = document.getElementById("exif-result");
    const table = document.getElementById("exif-table");
    result.hidden = true;
    hideErr("exif-error");
    table.innerHTML = "";
    const form = new FormData();
    form.append("file", file);
    try {
        const res = await fetch("/api/images/exif", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) { showErr("exif-error", data.error || "Could not read metadata"); return; }
        exifJson = data;

        exifRow(table, "File", null, true);
        const fi = data.file || {};
        exifRow(table, "Name", fi.name);
        exifRow(table, "Size", formatSize(fi.size_bytes || 0) + ` (${(fi.size_bytes || 0).toLocaleString()} bytes)`);
        exifRow(table, "Dimensions", `${fi.width} × ${fi.height}`);
        exifRow(table, "Format", fi.format);
        exifRow(table, "Mode", fi.mode);

        const tags = data.exif || {};
        const keys = Object.keys(tags).sort();
        if (keys.length) {
            exifRow(table, `EXIF (${keys.length} tags)`, null, true);
            for (const k of keys) exifRow(table, k, tags[k]);
        }
        if (data.gps) {
            exifRow(table, "GPS", null, true);
            if (data.gps.latitude !== undefined) {
                exifRow(table, "Latitude", data.gps.latitude);
                exifRow(table, "Longitude", data.gps.longitude);
                exifRow(table, "Map", data.gps.maps_url);
            }
            if (data.gps.altitude_m !== undefined) exifRow(table, "Altitude (m)", data.gps.altitude_m);
            for (const [k, v] of Object.entries(data.gps.raw || {})) exifRow(table, k, v);
        }
        document.getElementById("exif-count").textContent = keys.length
            ? `${keys.length} EXIF tag${keys.length === 1 ? "" : "s"}${data.gps ? " · GPS present" : ""}`
            : "No EXIF metadata found in this file";
        result.hidden = false;
    } catch {
        showErr("exif-error", "Network error");
    }
}

function copyExifJson(btn) {
    if (!exifJson) return;
    copyString(JSON.stringify(exifJson, null, 2), btn);
}

/* ── Border / Padding ── */
const borderState = setupSingleImageTool("border");
function clearBorderFile() { borderState.clear(); }

function toggleBorderMode() {
    const mode = document.getElementById("border-mode").value;
    const isPng = borderState.file && /\.(png|webp)$/i.test(borderState.file.name);
    document.getElementById("border-color-field").hidden = mode === "padding" && isPng;
    document.getElementById("border-mode-hint").textContent = mode === "border"
        ? "Border: a solid colored frame around the image."
        : (isPng ? "Padding: transparent space around the image (PNG / WebP)."
                 : "Padding: colored space around the image (JPG has no transparency).");
    document.getElementById("border-btn").innerHTML = `${DL_ICON} ${mode === "border" ? "Add Border" : "Add Padding"}`;
}

async function doBorder() {
    if (!borderState.file) return;
    const mode = document.getElementById("border-mode").value;
    const form = new FormData();
    form.append("file", borderState.file);
    form.append("size", document.getElementById("border-size").value || "0");
    form.append("color", document.getElementById("border-color").value);
    form.append("mode", mode);
    form.append("radius", document.getElementById("border-radius").value || "0");
    const f = borderState.file;
    const suffix = mode === "border" ? "bordered" : "padded";
    await postAndDownload("/api/images/border", form, "border-btn", "border-error",
        "Working...", mode === "border" ? "Add Border" : "Add Padding",
        `${fileBase(f.name)}_${suffix}.${fileExt(f.name)}`, "Border failed");
}

/* ── Favicon Set ── */
const faviconState = setupSingleImageTool("favicon", {
    onDimensions: (w, h) => {
        if (w && h && w !== h) {
            const side = Math.min(w, h);
            document.getElementById("favicon-dimensions").textContent = `${w} × ${h} → ${side} × ${side}`;
        }
    },
});
function clearFaviconFile() { faviconState.clear(); }

async function doFaviconSet() {
    if (!faviconState.file) return;
    const form = new FormData();
    form.append("file", faviconState.file);
    await postAndDownload("/api/images/favicon-set", form, "favicon-btn", "favicon-error",
        "Generating...", "Generate Favicon Set", `${fileBase(faviconState.file.name)}_favicons.zip`, "Favicon generation failed");
}

/* ── Upscale ── */
const upscaleState = setupSingleImageTool("upscale", { onDimensions: () => updateUpscaleHint() });
function clearUpscaleFile() { upscaleState.clear(); }

function updateUpscaleHint() {
    const f = parseInt(document.getElementById("upscale-factor").value, 10);
    const w = upscaleState.width, h = upscaleState.height;
    const hint = document.getElementById("upscale-hint");
    if (!w || !h) { hint.textContent = ""; return; }
    const ow = w * f, oh = h * f;
    const mp = (ow * oh / 1e6).toFixed(1);
    hint.textContent = `${w} × ${h} → ${ow} × ${oh} (${mp} MP)` + (ow * oh > 80e6 ? " — exceeds the 80 MP limit" : "");
}

async function doUpscale() {
    if (!upscaleState.file) return;
    const factor = document.getElementById("upscale-factor").value;
    const form = new FormData();
    form.append("file", upscaleState.file);
    form.append("factor", factor);
    const f = upscaleState.file;
    await postAndDownload("/api/images/upscale", form, "upscale-btn", "upscale-error",
        "Upscaling...", "Upscale Image", `${fileBase(f.name)}_${factor}x.${fileExt(f.name)}`, "Upscale failed");
}

/* ── Collage / Sprite Sheet ── */
let collageFiles = [];

setupDropZone("collage-drop", "collage-input", files => {
    for (const f of files) if (isImageFile(f)) collageFiles.push(f);
    renderCollageList();
});

function renderCollageList() {
    const list = document.getElementById("collage-list");
    list.innerHTML = "";
    collageFiles.forEach((f, i) => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.draggable = true;
        div.dataset.index = i;
        div.innerHTML = `
            <span class="drag-handle">&#9776;</span>
            <img class="img-thumb" src="${URL.createObjectURL(f)}" alt="">
            <span class="file-name">${esc(f.name)}</span>
            <span class="file-size">${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeCollageFile(${i})">&times;</button>
        `;
        setupDragItem(div, collageFiles, renderCollageList);
        list.appendChild(div);
    });
    const has = collageFiles.length > 0;
    document.getElementById("collage-options").hidden = !has;
    document.getElementById("collage-actions").hidden = !has;
    updateCollageHint();
}

function removeCollageFile(i) { collageFiles.splice(i, 1); renderCollageList(); }
function clearCollageFiles() { collageFiles = []; renderCollageList(); }

function updateCollageHint() {
    const n = collageFiles.length;
    const hint = document.getElementById("collage-hint");
    if (!n) { hint.textContent = ""; return; }
    const colsIn = parseInt(document.getElementById("collage-columns").value, 10);
    const cols = Math.min(n, colsIn > 0 ? colsIn : Math.ceil(Math.sqrt(n)));
    const rows = Math.ceil(n / cols);
    const cell = parseInt(document.getElementById("collage-cell").value, 10) || 256;
    const gap = parseInt(document.getElementById("collage-gap").value, 10) || 0;
    const w = cols * cell + (cols - 1) * gap, h = rows * cell + (rows - 1) * gap;
    hint.textContent = `${n} image${n === 1 ? "" : "s"} · ${cols} × ${rows} grid · output ${w} × ${h} px`;
}
["collage-columns", "collage-cell", "collage-gap"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", updateCollageHint);
});

async function doCollage() {
    if (!collageFiles.length) return;
    const output = document.getElementById("collage-output").value;
    const form = new FormData();
    collageFiles.forEach(f => form.append("files", f));
    form.append("columns", document.getElementById("collage-columns").value || "0");
    form.append("cell", document.getElementById("collage-cell").value || "256");
    form.append("gap", document.getElementById("collage-gap").value || "0");
    form.append("background", document.getElementById("collage-bg").value);
    form.append("fit", document.getElementById("collage-fit").value);
    form.append("output", output);
    form.append("transparent", document.getElementById("collage-transparent").checked ? "true" : "false");
    await postAndDownload("/api/images/collage", form, "collage-btn", "collage-error",
        "Building...", "Build Collage", output === "zip" ? "sprite_sheet.zip" : "collage.png", "Collage failed");
}

/* ── Image → ASCII ── */
let asciiText = "";
const asciiState = setupSingleImageTool("ascii", {
    onClear: () => { document.getElementById("ascii-result").hidden = true; asciiText = ""; },
});
function clearAsciiFile() { asciiState.clear(); }

async function doAscii() {
    if (!asciiState.file) return;
    const btn = document.getElementById("ascii-btn");
    hideErr("ascii-error");
    setBtnWorking(btn, "Converting...");
    const form = new FormData();
    form.append("file", asciiState.file);
    form.append("width", document.getElementById("ascii-width").value || "100");
    form.append("charset", document.getElementById("ascii-charset").value);
    form.append("invert", document.getElementById("ascii-invert").checked ? "true" : "false");
    try {
        const res = await fetch("/api/images/ascii", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) {
            showErr("ascii-error", data.error || "Conversion failed");
        } else {
            asciiText = data.text || "";
            document.getElementById("ascii-output").textContent = asciiText;
            document.getElementById("ascii-meta").textContent = `${data.width} × ${data.lines} characters`;
            document.getElementById("ascii-result").hidden = false;
        }
    } catch {
        showErr("ascii-error", "Network error");
    }
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/></svg> Convert to ASCII`;
}

function copyAscii(btn) { if (asciiText) copyString(asciiText, btn); }
function downloadAscii() {
    if (!asciiText || !asciiState.file) return;
    const name = `${fileBase(asciiState.file.name)}_ascii.txt`;
    downloadBlob(new Blob([asciiText], { type: "text/plain;charset=utf-8" }), name);
    showToast("Saved: " + name);
}

/* ── Color Picker (client-side only) ── */
let cpCanvas = null, cpCtx = null, cpPalette = [];
const CP_MAX_SIDE = 1600;

const colorPickerState = setupSingleImageTool("colorpicker", {
    onFile: f => loadColorPickerImage(f),
    onClear: () => {
        document.getElementById("colorpicker-work").hidden = true;
        clearPalette();
        if (cpCtx && cpCanvas) cpCtx.clearRect(0, 0, cpCanvas.width, cpCanvas.height);
    },
});
function clearColorPickerFile() { colorPickerState.clear(); }

function loadColorPickerImage(file) {
    cpCanvas = document.getElementById("colorpicker-canvas");
    cpCtx = cpCanvas.getContext("2d", { willReadFrequently: true });
    const img = new window.Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
        // Downscale huge images so sampling stays snappy; colors are unaffected.
        const scale = Math.min(1, CP_MAX_SIDE / Math.max(img.width, img.height));
        cpCanvas.width = Math.max(1, Math.round(img.width * scale));
        cpCanvas.height = Math.max(1, Math.round(img.height * scale));
        cpCtx.drawImage(img, 0, 0, cpCanvas.width, cpCanvas.height);
        URL.revokeObjectURL(url);
        document.getElementById("colorpicker-work").hidden = false;
        clearPalette();
        setHoverColor(null);
    };
    img.onerror = () => showErr("colorpicker-error", "Could not decode this image in the browser");
    img.src = url;
}

function cpCanvasPoint(e) {
    const r = cpCanvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - r.left) * cpCanvas.width / r.width);
    const y = Math.floor((e.clientY - r.top) * cpCanvas.height / r.height);
    if (x < 0 || y < 0 || x >= cpCanvas.width || y >= cpCanvas.height) return null;
    return { x, y };
}

function cpSampleAt(x, y) {
    const d = cpCtx.getImageData(x, y, 1, 1).data;
    return { r: d[0], g: d[1], b: d[2], a: d[3] };
}

function rgbToHex(c) {
    return "#" + [c.r, c.g, c.b].map(v => v.toString(16).padStart(2, "0")).join("");
}
function rgbToHsl(c) {
    const r = c.r / 255, g = c.g / 255, b = c.b / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0; const l = (max + min) / 2;
    if (max !== min) {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        switch (max) {
            case r: h = (g - b) / d + (g < b ? 6 : 0); break;
            case g: h = (b - r) / d + 2; break;
            default: h = (r - g) / d + 4;
        }
        h /= 6;
    }
    return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
}
function fmtRgb(c) { return `rgb(${c.r}, ${c.g}, ${c.b})`; }
function fmtHsl(c) { const h = rgbToHsl(c); return `hsl(${h.h}, ${h.s}%, ${h.l}%)`; }

function setHoverColor(c, pt) {
    const sw = document.getElementById("colorpicker-hover-swatch");
    const txt = document.getElementById("colorpicker-hover-text");
    if (!c) {
        sw.style.background = "transparent";
        txt.textContent = "Hover over the image to sample a color; click to add it to the palette.";
        return;
    }
    sw.style.background = rgbToHex(c);
    txt.textContent = `${rgbToHex(c)}   ${fmtRgb(c)}   ${fmtHsl(c)}   @ ${pt.x}, ${pt.y}`;
}

(function wireColorPickerCanvas() {
    const canvas = document.getElementById("colorpicker-canvas");
    if (!canvas) return;
    canvas.addEventListener("mousemove", e => {
        if (!cpCtx) return;
        const pt = cpCanvasPoint(e);
        if (!pt) { setHoverColor(null); return; }
        setHoverColor(cpSampleAt(pt.x, pt.y), pt);
    });
    canvas.addEventListener("mouseleave", () => setHoverColor(null));
    canvas.addEventListener("click", e => {
        if (!cpCtx) return;
        const pt = cpCanvasPoint(e);
        if (!pt) return;
        addPaletteColor(cpSampleAt(pt.x, pt.y), `${pt.x}, ${pt.y}`);
    });
})();

function addPaletteColor(c, note) {
    const hex = rgbToHex(c);
    if (cpPalette.some(p => p.hex === hex)) { showToast(hex + " is already in the palette"); return; }
    cpPalette.push({ hex, c, note });
    renderPalette();
}

function removePaletteColor(i) { cpPalette.splice(i, 1); renderPalette(); }
function clearPalette() { cpPalette = []; renderPalette(); }

function renderPalette() {
    const body = document.getElementById("colorpicker-palette");
    body.innerHTML = "";
    cpPalette.forEach((p, i) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td style="width:44px;"><span class="cp-swatch lg" style="background:${p.hex}"></span></td>
            <td class="kv-val">${p.hex}</td>
            <td class="kv-val">${fmtRgb(p.c)}</td>
            <td class="kv-val">${fmtHsl(p.c)}</td>
            <td style="white-space:nowrap;text-align:right;">
                <button class="btn-copy" onclick="copyString('${p.hex}', this)">Copy</button>
                <button class="split-remove" title="Remove" onclick="removePaletteColor(${i})">&times;</button>
            </td>
        `;
        body.appendChild(tr);
    });
    document.getElementById("colorpicker-table").hidden = cpPalette.length === 0;
    document.getElementById("colorpicker-empty").hidden = cpPalette.length > 0;
}

function copyPaletteAll(btn) {
    if (!cpPalette.length) return;
    copyString(cpPalette.map(p => p.hex).join("\n"), btn);
}

/* Bucket quantization: 4 bits per channel (4096 buckets), then average the
   pixels in the top 8 buckets so the swatch is a real color from the image
   rather than the bucket midpoint. Near-duplicate buckets are merged. */
function extractPalette() {
    if (!cpCtx) return;
    const { width, height } = cpCanvas;
    // Sample at most ~250k pixels for speed.
    const step = Math.max(1, Math.floor(Math.sqrt((width * height) / 250000)));
    const data = cpCtx.getImageData(0, 0, width, height).data;
    const buckets = new Map();
    for (let y = 0; y < height; y += step) {
        for (let x = 0; x < width; x += step) {
            const i = (y * width + x) * 4;
            if (data[i + 3] < 128) continue; // skip transparent
            const r = data[i], g = data[i + 1], b = data[i + 2];
            const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
            let bk = buckets.get(key);
            if (!bk) { bk = { n: 0, r: 0, g: 0, b: 0 }; buckets.set(key, bk); }
            bk.n++; bk.r += r; bk.g += g; bk.b += b;
        }
    }
    const sorted = [...buckets.values()].sort((a, b) => b.n - a.n);
    const picked = [];
    for (const bk of sorted) {
        const c = { r: Math.round(bk.r / bk.n), g: Math.round(bk.g / bk.n), b: Math.round(bk.b / bk.n) };
        // Merge colors that are visually very close to one already picked.
        const dup = picked.some(p => Math.abs(p.r - c.r) + Math.abs(p.g - c.g) + Math.abs(p.b - c.b) < 24);
        if (dup) continue;
        picked.push(c);
        if (picked.length >= 8) break;
    }
    cpPalette = picked.map(c => ({ hex: rgbToHex(c), c, note: "extracted" }));
    renderPalette();
    showToast(`Extracted ${picked.length} colors`);
}
