/* shared.js: helpers used by every tool page.
   Loaded by base.html before each page's own script, so these globals are
   defined first. Extracted from per-page copies that had drifted apart. */

/* ── Tab routing ── */
function showTab(tab) {
    document.querySelectorAll(".pdf-section").forEach(s => s.classList.remove("active"));
    const el = document.getElementById("tab-" + tab);
    (el || document.querySelector(".pdf-section")).classList.add("active");
    window.scrollTo(0, 0);
}

/* ── Drop zone wiring ── */
function setupDropZone(zoneId, inputId, handler) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    if (!zone || !input) return;
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

/* ── Full-page drop overlay ── (idempotent; pages with file tools call this once) */
function setupPageDropOverlay() {
    if (window._pageDropOverlayReady) return;
    window._pageDropOverlayReady = true;
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
    document.addEventListener("dragleave", function(e) {
        // Must mirror the dragenter filter. Counting text and link drags here
        // drove dc negative, which left the overlay permanently hidden.
        if (!e.dataTransfer || !e.dataTransfer.types.includes("Files")) return;
        if (--dc <= 0) { dc = 0; ov.classList.remove("visible"); }
    });
    document.addEventListener("drop", function(e) {
        dc = 0; ov.classList.remove("visible");
        if (!e.dataTransfer.files.length) return;
        var handlers = window._pageDropHandlers || [];
        var visible = [];
        for (var i = 0; i < handlers.length; i++) {
            var zone = document.getElementById(handlers[i].zoneId);
            // A hidden subsection's zone must not swallow the drop.
            if (zone && zone.closest(".pdf-section.active") && zone.offsetParent !== null) {
                visible.push({ zone: zone, handler: handlers[i].handler });
            }
        }
        var file = e.dataTransfer.files[0];
        // Prefer a zone whose accept list matches the dropped file.
        for (var j = 0; j < visible.length; j++) {
            var input = visible[j].zone.querySelector("input[type=file]");
            var accept = input && input.accept ? input.accept : "";
            if (accept && file && _acceptMatches(accept, file)) {
                e.preventDefault(); visible[j].handler(e.dataTransfer.files); return;
            }
        }
        if (visible.length) { e.preventDefault(); visible[0].handler(e.dataTransfer.files); return; }
        if (handlers.length) { e.preventDefault(); handlers[0].handler(e.dataTransfer.files); }
    });
}

function _acceptMatches(accept, file) {
    var name = (file.name || "").toLowerCase();
    var type = (file.type || "").toLowerCase();
    return accept.split(",").some(function(rule) {
        rule = rule.trim().toLowerCase();
        if (!rule) return false;
        if (rule.startsWith(".")) return name.endsWith(rule);
        if (rule.endsWith("/*")) return type.startsWith(rule.slice(0, -1));
        return type === rule;
    });
}
