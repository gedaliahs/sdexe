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

/* ── Nav menus by keyboard ──
   The menus open on hover, which a keyboard can't do, so from a tool page the
   other tools were out of reach without a mouse. Down arrow on a menu's name
   opens it, the arrows move through it, Escape closes it. Tab order is as it
   was: closed menus are skipped. */
function sdexeCloseNavMenus() {
    document.querySelectorAll(".nav-group.open").forEach(function(g) {
        g.classList.remove("open");
        var t = g.querySelector(".nav-group-trigger");
        if (t) t.setAttribute("aria-expanded", "false");
    });
}
document.addEventListener("keydown", function(e) {
    var el = document.activeElement;
    var group = el && el.closest ? el.closest(".nav-group") : null;
    if (!group) return;
    var trigger = group.querySelector(".nav-group-trigger");
    var isOpen = group.classList.contains("open");
    if (e.key === "Escape" && isOpen) {
        sdexeCloseNavMenus();
        trigger.focus();
    } else if (e.key === "ArrowDown" || (e.key === "ArrowUp" && isOpen)) {
        e.preventDefault();
        if (!isOpen) {
            sdexeCloseNavMenus();
            group.classList.add("open");
            trigger.setAttribute("aria-expanded", "true");
        }
        var items = Array.prototype.slice.call(group.querySelectorAll(".nav-group-item"));
        var next = items.indexOf(el) + (e.key === "ArrowDown" ? 1 : -1);
        if (next < 0) trigger.focus();
        else if (next < items.length) items[next].focus();
    }
});
document.addEventListener("focusin", function(e) {
    var open = document.querySelector(".nav-group.open");
    if (open && !open.contains(e.target)) sdexeCloseNavMenus();
});
/* Picking a tool on the page you are already on doesn't reload, so hand focus
   to that tool: the menu closes and Tab carries on inside it. */
document.addEventListener("click", function(e) {
    var item = e.target.closest ? e.target.closest(".nav-group-menu a") : null;
    if (!item || item.pathname !== location.pathname) return;
    // After the page's own hashchange handler has switched tabs.
    setTimeout(function() {
        sdexeCloseNavMenus();
        var section = document.querySelector(".pdf-section.active");
        if (!section) { item.blur(); return; }
        section.tabIndex = -1;
        section.focus({ preventScroll: true });
    }, 60);
});

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
    // The picker is a <label> around a hidden input, which the Tab key skips.
    // Make the label itself a keyboard button.
    const browse = input.closest("label");
    if (browse && !browse.hasAttribute("tabindex")) {
        browse.tabIndex = 0;
        browse.setAttribute("role", "button");
        browse.addEventListener("keydown", e => {
            if (e.target !== browse || (e.key !== "Enter" && e.key !== " ")) return;
            e.preventDefault();
            input.click();
        });
    }
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
            // A zone on a tab or subsection that isn't showing must not swallow
            // the drop. A zone outside any tab (the Transcribe page) counts
            // whenever it is on screen.
            var section = zone && zone.closest(".pdf-section");
            if (zone && zone.offsetParent !== null && (!section || section.classList.contains("active"))) {
                visible.push({ zone: zone, handler: handlers[i].handler });
            }
        }
        var file = e.dataTransfer.files[0];
        // The zone under the pointer wins. The overlay sits on top while
        // dragging, so look through everything stacked at that point.
        var stack = document.elementsFromPoint ? document.elementsFromPoint(e.clientX, e.clientY) : [];
        for (var k = 0; k < visible.length; k++) {
            if (stack.indexOf(visible[k].zone) !== -1 || stack.some(function(el) { return visible[k].zone.contains(el) && el !== ov; })) {
                e.preventDefault(); visible[k].handler(e.dataTransfer.files); return;
            }
        }
        // Otherwise, a zone whose accept list matches the dropped file.
        for (var j = 0; j < visible.length; j++) {
            var input = visible[j].zone.querySelector("input[type=file]");
            var accept = input && input.accept ? input.accept : "";
            if (accept && file && _acceptMatches(accept, file)) {
                e.preventDefault(); visible[j].handler(e.dataTransfer.files); return;
            }
        }
        // Nothing on the open tab takes files (recorders, QR code): don't
        // load it into a tab the user can't see.
        if (visible.length) { e.preventDefault(); visible[0].handler(e.dataTransfer.files); return; }
        e.preventDefault();
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


/* The filename from a Content-Disposition header, or null. Prefers the UTF-8
   `filename*` the server sends (the plain `filename=` is an ASCII fallback that
   mangles non-English names), and never throws on names with % in them. */
function sdexeFilename(cd) {
    cd = cd || "";
    var star = /filename\*\s*=\s*(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    if (star) {
        try { return decodeURIComponent(star[1]); } catch (e) { return star[1]; }
    }
    // A quoted name may hold ";" and escaped quotes; an unquoted one ends at ";".
    var quoted = /filename\s*=\s*"((?:\\.|[^"\\])*)"/i.exec(cd);
    if (quoted) return quoted[1].replace(/\\(.)/g, "$1");
    var plain = /filename\s*=\s*([^";\s][^";]*)/i.exec(cd);
    return plain ? plain[1].trim() : null;
}

/* Same, shaped like a regex match so callers can keep using match[1]. */
function sdexeFilenameMatch(cd) {
    var name = sdexeFilename(cd);
    return name ? [name, name] : null;
}


/* One object URL per File, reused across re-renders. Lists redraw often, and a
   fresh URL each time kept every old copy of the image alive. */
var _sdexeFileURLs = new WeakMap();
function sdexeFileURL(file) {
    var url = _sdexeFileURLs.get(file);
    if (!url) { url = URL.createObjectURL(file); _sdexeFileURLs.set(file, url); }
    return url;
}

/* Point a media element at a new blob, releasing the one it showed before. */
function sdexeSetBlobSrc(el, blob) {
    if (!el) return;
    if (el.src && el.src.indexOf("blob:") === 0) URL.revokeObjectURL(el.src);
    el.src = URL.createObjectURL(blob);
}
