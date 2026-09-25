/* ── Hash Routing ── */
if (typeof document !== "undefined") {
    showTab(location.hash.slice(1) || "wordcount");
    window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "wordcount"));
}

/* ── Word Counter ── */
function updateWordCount() {
    const text = document.getElementById("wc-input").value;
    const chars = text.length;
    const charsNoSpaces = text.replace(/\s/g, "").length;
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    const lines = text ? text.split(/\n/).length : 0;
    const sentences = text.trim() ? text.split(/[.!?]+/).filter(s => s.trim()).length : 0;
    const readTime = Math.ceil(words / 238);

    document.getElementById("wc-chars").textContent = chars.toLocaleString();
    document.getElementById("wc-chars-no-spaces").textContent = charsNoSpaces.toLocaleString();
    document.getElementById("wc-words").textContent = words.toLocaleString();
    document.getElementById("wc-lines").textContent = lines.toLocaleString();
    document.getElementById("wc-sentences").textContent = sentences.toLocaleString();
    document.getElementById("wc-read-time").textContent = readTime < 1 ? "< 1 min" : readTime + " min";
}

/* ── Find & Replace ── */
function doFindReplace() {
    const find = document.getElementById("fr-find").value;
    const replace = document.getElementById("fr-replace").value;
    const input = document.getElementById("fr-input").value;
    const caseSensitive = document.getElementById("fr-case").checked;
    const useRegex = document.getElementById("fr-regex").checked;
    const err = document.getElementById("fr-error");
    const countEl = document.getElementById("fr-count");
    err.hidden = true;

    if (!find) {
        document.getElementById("fr-output").value = input;
        countEl.textContent = "";
        return;
    }

    try {
        let count = 0;
        let result;
        if (useRegex) {
            const flags = "g" + (caseSensitive ? "" : "i");
            const rx = new RegExp(find, flags);
            result = input.replace(rx, m => { count++; return replace; });
        } else {
            const escaped = find.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            const flags = "g" + (caseSensitive ? "" : "i");
            const rx = new RegExp(escaped, flags);
            result = input.replace(rx, m => { count++; return replace; });
        }
        document.getElementById("fr-output").value = result;
        countEl.textContent = count === 0 ? "No matches found" : `${count} replacement${count === 1 ? "" : "s"} made`;
    } catch (e) {
        err.textContent = "Invalid regex: " + e.message;
        err.hidden = false;
    }
}

/* ── Regex Tester ── */
function doRegex() {
    const pattern = document.getElementById("rx-pattern").value;
    const flags = document.getElementById("rx-flags").value;
    const input = document.getElementById("rx-input").value;
    const highlightEl = document.getElementById("rx-highlighted");
    const matchesEl = document.getElementById("rx-matches");
    const err = document.getElementById("rx-error");
    err.hidden = true;
    matchesEl.innerHTML = "";
    highlightEl.style.display = "none";

    if (!pattern || !input) return;

    try {
        const cleanFlags = flags.replace(/[^gimsuy]/g, "");
        const rx = new RegExp(pattern, cleanFlags.includes("g") ? cleanFlags : cleanFlags + "g");
        const matches = [...input.matchAll(rx)];

        if (matches.length === 0) {
            matchesEl.innerHTML = `<p style="color: var(--text-secondary); font-size: 0.875rem;">No matches found</p>`;
            return;
        }

        // Build highlighted version
        let highlighted = "";
        let lastIndex = 0;
        for (const m of matches) {
            const start = m.index;
            const end = start + m[0].length;
            highlighted += esc(input.slice(lastIndex, start));
            highlighted += `<mark style="background: #fbbf24; border-radius: 3px;">${esc(m[0])}</mark>`;
            lastIndex = end;
        }
        highlighted += esc(input.slice(lastIndex));
        highlightEl.innerHTML = highlighted;
        highlightEl.style.display = "block";

        // Show match list
        const header = document.createElement("p");
        header.style.cssText = "font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 8px;";
        header.textContent = `${matches.length} match${matches.length === 1 ? "" : "es"}`;
        matchesEl.appendChild(header);

        matches.slice(0, 50).forEach((m, i) => {
            const div = document.createElement("div");
            div.style.cssText = "font-family: monospace; font-size: 0.8rem; padding: 4px 8px; background: var(--surface-2); border-radius: 4px; margin-bottom: 4px;";
            div.textContent = `[${i + 1}] "${m[0]}" at index ${m.index}`;
            matchesEl.appendChild(div);
        });
        if (matches.length > 50) {
            const more = document.createElement("p");
            more.style.cssText = "font-size: 0.8rem; color: var(--text-secondary);";
            more.textContent = `... and ${matches.length - 50} more`;
            matchesEl.appendChild(more);
        }
    } catch (e) {
        err.textContent = "Invalid regex: " + e.message;
        err.hidden = false;
    }
}

/* ── Base64 ── */
function doB64Encode() {
    const input = document.getElementById("b64-input").value;
    const err = document.getElementById("b64-error");
    err.hidden = true;
    try {
        document.getElementById("b64-output").value = btoa(unescape(encodeURIComponent(input)));
    } catch (e) {
        err.textContent = "Encoding failed: " + e.message;
        err.hidden = false;
    }
}

function doB64Decode() {
    const input = document.getElementById("b64-input").value.trim();
    const err = document.getElementById("b64-error");
    err.hidden = true;
    try {
        document.getElementById("b64-output").value = decodeURIComponent(escape(atob(input)));
    } catch (e) {
        err.textContent = "Invalid Base64: " + e.message;
        err.hidden = false;
    }
}

function doB64File() {
    const file = document.getElementById("b64-file-input").files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
        const data = e.target.result;
        // data is data URL, extract base64 part
        const b64 = data.split(",")[1] || data;
        document.getElementById("b64-output").value = b64;
    };
    reader.readAsDataURL(file);
}

/* ── Hash Generator ── */
async function doHash() {
    const text = document.getElementById("hash-input").value;
    const algos = [...document.querySelectorAll(".hash-algo:checked")].map(cb => cb.value);
    const results = document.getElementById("hash-results");
    const err = document.getElementById("hash-error");
    err.hidden = true;
    results.innerHTML = "";

    if (!text) {
        err.textContent = "Enter some text to hash";
        err.hidden = false;
        return;
    }
    if (!algos.length) {
        err.textContent = "Select at least one algorithm";
        err.hidden = false;
        return;
    }

    const encoder = new TextEncoder();
    const data = encoder.encode(text);

    for (const algo of algos) {
        try {
            const hashBuffer = await crypto.subtle.digest(algo, data);
            const hashArray = Array.from(new Uint8Array(hashBuffer));
            const hex = hashArray.map(b => b.toString(16).padStart(2, "0")).join("");

            const row = document.createElement("div");
            row.style.cssText = "margin-bottom: 12px;";
            row.innerHTML = `
                <div style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 4px;">${algo}</div>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <code style="font-size: 0.78rem; word-break: break-all; flex: 1; padding: 6px 10px; background: var(--surface-2); border-radius: 6px;">${hex}</code>
                    <button onclick="navigator.clipboard.writeText('${hex}')" style="flex-shrink: 0; font-size: 0.8rem; background: none; border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; cursor: pointer; color: var(--text-secondary);">Copy</button>
                </div>
            `;
            results.appendChild(row);
        } catch (e) {
            err.textContent = `${algo} failed: ${e.message}`;
            err.hidden = false;
        }
    }
}

/* ── Hash File ── */
async function doHashFile() {
    const fileInput = document.getElementById("hash-file-input");
    const file = fileInput.files[0];
    if (!file) return;
    fileInput.value = "";

    const algos = [...document.querySelectorAll(".hash-algo:checked")].map(cb => cb.value);
    const results = document.getElementById("hash-results");
    const err = document.getElementById("hash-error");
    err.hidden = true;
    results.innerHTML = `<p style="font-size:.85rem;color:var(--text-secondary);">Hashing ${esc(file.name)} (${(file.size / 1024).toFixed(1)} KB)...</p>`;

    if (!algos.length) {
        err.textContent = "Select at least one algorithm";
        err.hidden = false;
        results.innerHTML = "";
        return;
    }

    const buffer = await file.arrayBuffer();
    results.innerHTML = "";

    for (const algo of algos) {
        try {
            const hashBuffer = await crypto.subtle.digest(algo, buffer);
            const hex = Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, "0")).join("");
            const row = document.createElement("div");
            row.style.cssText = "margin-bottom: 12px;";
            row.innerHTML = `
                <div style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 4px;">${algo} <span style="color:var(--text-muted);">${esc(file.name)}</span></div>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <code style="font-size: 0.78rem; word-break: break-all; flex: 1; padding: 6px 10px; background: var(--surface-2); border-radius: 6px;">${hex}</code>
                    <button class="btn-copy" onclick="navigator.clipboard.writeText('${hex}');this.classList.add('copied');this.innerHTML='Copied!';setTimeout(()=>{this.classList.remove('copied');this.innerHTML='Copy'},1500)">Copy</button>
                </div>
            `;
            results.appendChild(row);
        } catch (e) {
            err.textContent = `${algo} failed: ${e.message}`;
            err.hidden = false;
        }
    }
}

/* ── Text Diff ── */
function doDiff() {
    const original = document.getElementById("diff-original").value.split("\n");
    const modified = document.getElementById("diff-modified").value.split("\n");
    const output = document.getElementById("diff-output");
    const summary = document.getElementById("diff-summary");

    const diff = computeDiff(original, modified);
    let added = 0, removed = 0;
    let html = "";

    for (const line of diff) {
        if (line.type === "add") {
            added++;
            html += `<div style="background: #bbf7d0; padding: 2px 12px; white-space: pre-wrap; word-break: break-word;"><span style="color: #065f46; user-select: none;">+ </span>${esc(line.text)}</div>`;
        } else if (line.type === "remove") {
            removed++;
            html += `<div style="background: #fecaca; padding: 2px 12px; white-space: pre-wrap; word-break: break-word;"><span style="color: #991b1b; user-select: none;">- </span>${esc(line.text)}</div>`;
        } else {
            html += `<div style="padding: 2px 12px; white-space: pre-wrap; word-break: break-word; color: var(--text-secondary);"><span style="user-select: none;">  </span>${esc(line.text)}</div>`;
        }
    }

    output.innerHTML = html;
    output.style.display = "block";
    summary.textContent = diff.length === 0 ? "Files are identical" : `${added} addition${added === 1 ? "" : "s"}, ${removed} deletion${removed === 1 ? "" : "s"}`;
}

function computeDiff(a, b) {
    // Simple LCS-based line diff
    const m = a.length, n = b.length;
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = m - 1; i >= 0; i--) {
        for (let j = n - 1; j >= 0; j--) {
            if (a[i] === b[j]) dp[i][j] = dp[i + 1][j + 1] + 1;
            else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
    }
    const result = [];
    let i = 0, j = 0;
    while (i < m || j < n) {
        if (i < m && j < n && a[i] === b[j]) {
            result.push({ type: "equal", text: a[i] });
            i++; j++;
        } else if (j < n && (i >= m || dp[i][j + 1] >= dp[i + 1][j])) {
            result.push({ type: "add", text: b[j] });
            j++;
        } else {
            result.push({ type: "remove", text: a[i] });
            i++;
        }
    }
    return result;
}

/* ── Color Converter ── */
function colorFromHex() {
    const hex = document.getElementById("color-hex").value.trim();
    const match = hex.match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (!match) return;
    let h = match[1];
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    const r = parseInt(h.slice(0,2), 16);
    const g = parseInt(h.slice(2,4), 16);
    const b = parseInt(h.slice(4,6), 16);
    setRgb(r, g, b, "hex");
}

function colorFromRgb() {
    const r = clamp(parseInt(document.getElementById("color-r").value) || 0, 0, 255);
    const g = clamp(parseInt(document.getElementById("color-g").value) || 0, 0, 255);
    const b = clamp(parseInt(document.getElementById("color-b").value) || 0, 0, 255);
    setRgb(r, g, b, "rgb");
}

function colorFromHsl() {
    const h = clamp(parseInt(document.getElementById("color-h").value) || 0, 0, 360);
    const s = clamp(parseInt(document.getElementById("color-s").value) || 0, 0, 100);
    const l = clamp(parseInt(document.getElementById("color-l").value) || 0, 0, 100);
    const [r, g, b] = hslToRgb(h, s, l);
    setRgb(r, g, b, "hsl");
}

function setRgb(r, g, b, source) {
    if (source !== "rgb") {
        document.getElementById("color-r").value = r;
        document.getElementById("color-g").value = g;
        document.getElementById("color-b").value = b;
    }
    const hex = "#" + [r, g, b].map(v => v.toString(16).padStart(2, "0")).join("");
    if (source !== "hex") document.getElementById("color-hex").value = hex;
    const [h, s, l] = rgbToHsl(r, g, b);
    if (source !== "hsl") {
        document.getElementById("color-h").value = h;
        document.getElementById("color-s").value = s;
        document.getElementById("color-l").value = l;
    }
    document.getElementById("color-swatch").style.background = hex;
    document.getElementById("color-hex-display").textContent = "HEX: " + hex.toUpperCase();
    document.getElementById("color-rgb-display").textContent = `RGB: rgb(${r}, ${g}, ${b})`;
    document.getElementById("color-hsl-display").textContent = `HSL: hsl(${h}, ${s}%, ${l}%)`;
}

function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;
    if (max === min) { h = s = 0; }
    else {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        switch (max) {
            case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
            case g: h = ((b - r) / d + 2) / 6; break;
            default: h = ((r - g) / d + 4) / 6;
        }
    }
    return [Math.round(h * 360), Math.round(s * 100), Math.round(l * 100)];
}

function hslToRgb(h, s, l) {
    s /= 100; l /= 100;
    const k = n => (n + h / 30) % 12;
    const a = s * Math.min(l, 1 - l);
    const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

function clamp(v, min, max) { return Math.min(max, Math.max(min, v)); }

// Init color display
if (typeof document !== "undefined") setRgb(59, 130, 246, "rgb");

/* ── URL Encoder/Decoder ── */
function doUrlEncode() {
    const input = document.getElementById("url-input").value;
    const err = document.getElementById("url-error");
    err.hidden = true;
    try {
        document.getElementById("url-output").value = encodeURIComponent(input);
    } catch (e) {
        err.textContent = "Encoding failed: " + e.message;
        err.hidden = false;
    }
}

function doUrlDecode() {
    const input = document.getElementById("url-input").value;
    const err = document.getElementById("url-error");
    err.hidden = true;
    try {
        document.getElementById("url-output").value = decodeURIComponent(input);
    } catch (e) {
        err.textContent = "Decoding failed: " + e.message;
        err.hidden = false;
    }
}

/* ── JSON Formatter ── */
function doJsonFormat() {
    const input = document.getElementById("json-input").value;
    const err = document.getElementById("json-error");
    err.hidden = true;
    try {
        const obj = JSON.parse(input);
        document.getElementById("json-output").value = JSON.stringify(obj, null, 2);
    } catch (e) {
        err.textContent = "Invalid JSON: " + e.message;
        err.hidden = false;
    }
}

function doJsonMinify() {
    const input = document.getElementById("json-input").value;
    const err = document.getElementById("json-error");
    err.hidden = true;
    try {
        const obj = JSON.parse(input);
        document.getElementById("json-output").value = JSON.stringify(obj);
    } catch (e) {
        err.textContent = "Invalid JSON: " + e.message;
        err.hidden = false;
    }
}

/* ── JWT Decoder ── */
function doJwtDecode() {
    const input = document.getElementById("jwt-input").value.trim();
    const results = document.getElementById("jwt-results");
    const err = document.getElementById("jwt-error");
    err.hidden = true;
    results.innerHTML = "";

    if (!input) {
        err.textContent = "Enter a JWT token";
        err.hidden = false;
        return;
    }

    const parts = input.split(".");
    if (parts.length !== 3) {
        err.textContent = "Invalid JWT: expected 3 parts separated by dots, got " + parts.length;
        err.hidden = false;
        return;
    }

    function b64decode(str) {
        const pad = str.length % 4;
        const padded = str + "=".repeat(pad ? 4 - pad : 0);
        return decodeURIComponent(atob(padded.replace(/-/g, "+").replace(/_/g, "/")).split("").map(c =>
            "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2)
        ).join(""));
    }

    try {
        const header = JSON.parse(b64decode(parts[0]));
        const payload = JSON.parse(b64decode(parts[1]));

        function renderSection(title, obj) {
            let html = `<div style="margin-bottom: 16px;">
                <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .05em;">${title}</div>
                <pre style="font-family: ui-monospace, monospace; font-size: 0.8rem; padding: 12px; background: var(--surface-2); border-radius: 8px; overflow-x: auto; white-space: pre-wrap; word-break: break-word;">${esc(JSON.stringify(obj, null, 2))}</pre>
            </div>`;
            return html;
        }

        results.innerHTML = renderSection("Header", header) + renderSection("Payload", payload);

        if (payload.exp) {
            const expDate = new Date(payload.exp * 1000);
            const expired = expDate < new Date();
            results.innerHTML += `<div style="font-size: 0.85rem; color: ${expired ? "var(--danger)" : "var(--green)"};">${expired ? "Expired" : "Expires"}: ${expDate.toLocaleString()}</div>`;
        }
        if (payload.iat) {
            results.innerHTML += `<div style="font-size: 0.85rem; color: var(--text-secondary);">Issued: ${new Date(payload.iat * 1000).toLocaleString()}</div>`;
        }
    } catch (e) {
        err.textContent = "Failed to decode JWT: " + e.message;
        err.hidden = false;
    }
}

/* ── Case Converter ── */
function doCase(type) {
    const input = document.getElementById("case-input").value;
    let result;
    switch (type) {
        case "upper": result = input.toUpperCase(); break;
        case "lower": result = input.toLowerCase(); break;
        case "title": result = input.replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()); break;
        case "camel": {
            const words = input.replace(/[^a-zA-Z0-9\s]/g, " ").trim().split(/\s+/);
            result = words.map((w, i) => i === 0 ? w.toLowerCase() : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join("");
            break;
        }
        case "snake": result = input.replace(/[^a-zA-Z0-9]/g, " ").trim().split(/\s+/).map(w => w.toLowerCase()).join("_"); break;
        case "kebab": result = input.replace(/[^a-zA-Z0-9]/g, " ").trim().split(/\s+/).map(w => w.toLowerCase()).join("-"); break;
        default: result = input;
    }
    document.getElementById("case-output").value = result;
}

/* ── UUID Generator ── */
function doUuid() {
    const count = Math.min(Math.max(parseInt(document.getElementById("uuid-count").value) || 1, 1), 100);
    const uuids = [];
    for (let i = 0; i < count; i++) uuids.push(crypto.randomUUID());
    document.getElementById("uuid-output").value = uuids.join("\n");
}

/* ── Unix Timestamp ── */
function tsFromUnix() {
    const val = document.getElementById("ts-unix").value.trim();
    const display = document.getElementById("ts-date-display");
    if (!val) { display.textContent = ""; return; }
    const ts = parseInt(val);
    if (isNaN(ts)) { display.textContent = "Invalid timestamp"; return; }
    const ms = val.length > 12 ? ts : ts * 1000;
    const d = new Date(ms);
    display.textContent = d.toLocaleString() + " (" + Intl.DateTimeFormat().resolvedOptions().timeZone + ")";
    document.getElementById("ts-datetime").value = new Date(ms - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    document.getElementById("ts-unix-display").textContent = "";
}

function tsFromDatetime() {
    const val = document.getElementById("ts-datetime").value;
    const display = document.getElementById("ts-unix-display");
    if (!val) { display.textContent = ""; return; }
    const ts = Math.floor(new Date(val).getTime() / 1000);
    display.textContent = ts;
    document.getElementById("ts-unix").value = ts;
    document.getElementById("ts-date-display").textContent = "";
}

function tsNow() {
    const now = Math.floor(Date.now() / 1000);
    document.getElementById("ts-unix").value = now;
    tsFromUnix();
}

/* ── Lorem Ipsum ── */
const _loremSentences = [
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.",
    "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore.",
    "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia.",
    "Nulla facilisi morbi tempus iaculis urna id volutpat lacus.",
    "Viverra accumsan in nisl nisi scelerisque eu ultrices vitae.",
    "Amet consectetur adipiscing elit pellentesque habitant morbi tristique senectus.",
    "Egestas purus viverra accumsan in nisl nisi scelerisque eu.",
    "Feugiat in ante metus dictum at tempor commodo ullamcorper.",
    "Pellentesque habitant morbi tristique senectus et netus et malesuada fames.",
    "Turpis egestas integer eget aliquet nibh praesent tristique magna.",
    "Quis hendrerit dolor magna eget est lorem ipsum dolor.",
    "Volutpat consequat mauris nunc congue nisi vitae suscipit tellus.",
    "Arcu cursus vitae congue mauris rhoncus aenean vel elit.",
    "Facilisis magna etiam tempor orci eu lobortis elementum nibh.",
    "Id aliquet risus feugiat in ante metus dictum at.",
    "Sagittis scelerisque purus semper eget duis at tellus at.",
    "Bibendum at varius vel pharetra vel turpis nunc eget.",
    "Odio morbi quis commodo odio aenean sed adipiscing diam.",
];

function doLorem() {
    const count = Math.min(Math.max(parseInt(document.getElementById("lorem-count").value) || 3, 1), 20);
    const paragraphs = [];
    for (let p = 0; p < count; p++) {
        const len = 4 + Math.floor(Math.random() * 4);
        const sentences = [];
        for (let s = 0; s < len; s++) {
            sentences.push(_loremSentences[Math.floor(Math.random() * _loremSentences.length)]);
        }
        if (p === 0 && sentences[0] !== _loremSentences[0]) sentences[0] = _loremSentences[0];
        paragraphs.push(sentences.join(" "));
    }
    document.getElementById("lorem-output").value = paragraphs.join("\n\n");
}

/* ── Helpers ── */
function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function copyText(id, btn) {
    const el = document.getElementById(id);
    navigator.clipboard.writeText(el.value || el.textContent).then(() => {
        if (btn) {
            btn.classList.add("copied");
            const orig = btn.innerHTML;
            btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
            setTimeout(() => { btn.classList.remove("copied"); btn.innerHTML = orig; }, 1500);
        }
    }).catch(() => {
        el.select && el.select();
        document.execCommand("copy");
    });
}

/* ── Password Generator ── */
function doPassword() {
    const len = Math.min(128, Math.max(4, parseInt(document.getElementById("pw-length").value) || 20));
    const upper = document.getElementById("pw-upper").checked;
    const lower = document.getElementById("pw-lower").checked;
    const digits = document.getElementById("pw-digits").checked;
    const symbols = document.getElementById("pw-symbols").checked;

    let chars = "";
    if (upper) chars += "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    if (lower) chars += "abcdefghijklmnopqrstuvwxyz";
    if (digits) chars += "0123456789";
    if (symbols) chars += "!@#$%^&*()_+-=[]{}|;:,.<>?";

    if (!chars) {
        chars = "abcdefghijklmnopqrstuvwxyz0123456789";
    }

    const arr = new Uint32Array(len);
    crypto.getRandomValues(arr);
    let password = "";
    for (let i = 0; i < len; i++) {
        password += chars[arr[i] % chars.length];
    }

    document.getElementById("pw-output").value = password;

    // Strength estimation
    const poolSize = (upper ? 26 : 0) + (lower ? 26 : 0) + (digits ? 10 : 0) + (symbols ? 27 : 0);
    const entropy = Math.floor(len * Math.log2(poolSize || 36));
    let strength = "Weak";
    if (entropy >= 128) strength = "Very Strong";
    else if (entropy >= 80) strength = "Strong";
    else if (entropy >= 60) strength = "Good";
    else if (entropy >= 40) strength = "Fair";
    document.getElementById("pw-strength").textContent = `${entropy} bits of entropy, ${strength}`;

    const fill = document.getElementById("pw-strength-fill");
    const pct = Math.min(100, (entropy / 128) * 100);
    const colors = { "Weak": "#ef4444", "Fair": "#f59e0b", "Good": "#eab308", "Strong": "#22c55e", "Very Strong": "#10b981" };
    fill.style.width = pct + "%";
    fill.style.background = colors[strength] || "#ef4444";
}

/* ══════════════════════════════════════════════════════════════════
   Line Tools, Cron Explainer, HTML Entities, String Escape, Number
   Base, Unit Converter, Slug Generator, Markdown Table, Text to Speech.
   Pure functions are plain top-level so they load in Node for tests;
   all DOM wiring lives in initTextTools2() at the bottom.
   ══════════════════════════════════════════════════════════════════ */

/* ── Line Tools (pure) ── */
function countLines(text) { return text === "" ? 0 : text.split(/\r?\n/).length; }

function unescapeSep(s) {
    return s.replace(/\\(n|t|r|\\)/g, (m, c) => ({ n: "\n", t: "\t", r: "\r", "\\": "\\" })[c]);
}

function lineNumKey(line) {
    const m = line.match(/-?\d+(\.\d+)?/);
    return m ? parseFloat(m[0]) : Infinity;
}

function lineTransform(text, op, opts) {
    opts = opts || {};
    let lines = text.split(/\r?\n/);
    switch (op) {
        case "sortaz": lines.sort((a, b) => a.localeCompare(b)); break;
        case "sortza": lines.sort((a, b) => b.localeCompare(a)); break;
        case "sortnum": lines.sort((a, b) => lineNumKey(a) - lineNumKey(b)); break;
        case "natural": lines.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" })); break;
        case "reverse": lines.reverse(); break;
        case "shuffle":
            for (let i = lines.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [lines[i], lines[j]] = [lines[j], lines[i]];
            }
            break;
        case "dedupe": {
            const seen = new Set();
            lines = lines.filter(l => {
                const k = opts.caseSensitive ? l : l.toLowerCase();
                if (seen.has(k)) return false;
                seen.add(k); return true;
            });
            break;
        }
        case "noblank": lines = lines.filter(l => l.trim() !== ""); break;
        case "trim": lines = lines.map(l => l.trim()); break;
        case "number": {
            const w = String(lines.length).length;
            lines = lines.map((l, i) => String(i + 1).padStart(w) + ". " + l);
            break;
        }
        case "affix": lines = lines.map(l => (opts.prefix || "") + l + (opts.suffix || "")); break;
        case "join": return lines.join(unescapeSep(opts.sep == null ? ", " : opts.sep));
        case "split": {
            const sep = unescapeSep(opts.sep == null ? "," : opts.sep);
            return sep ? text.split(sep).join("\n") : text;
        }
    }
    return lines.join("\n");
}

/* ── Cron Explainer (pure) ── */
const CRON_ALIASES = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *",
};
const CRON_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const CRON_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const CRON_DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const CRON_DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const CRON_FIELDS = [
    { key: "second", name: "Second", min: 0, max: 59 },
    { key: "minute", name: "Minute", min: 0, max: 59 },
    { key: "hour", name: "Hour", min: 0, max: 23 },
    { key: "dom", name: "Day of month", min: 1, max: 31 },
    { key: "month", name: "Month", min: 1, max: 12, names: CRON_MONTHS, nameOffset: 1 },
    { key: "dow", name: "Day of week", min: 0, max: 7, names: CRON_DAYS, nameOffset: 0 },
];

function cronParseField(raw, spec) {
    const terms = [];
    const values = new Set();
    const top = spec.key === "dow" ? 6 : spec.max;
    const parseVal = s => {
        const up = s.toUpperCase();
        if (spec.names) {
            const i = spec.names.indexOf(up);
            if (i >= 0) return i + spec.nameOffset;
        }
        if (!/^\d+$/.test(s)) throw new Error(`Invalid value "${s}" in ${spec.name.toLowerCase()} field`);
        const n = parseInt(s, 10);
        if (n < spec.min || n > spec.max) throw new Error(`${spec.name} value ${n} is out of range (${spec.min}-${spec.max})`);
        return n;
    };
    if (raw === "") throw new Error(`${spec.name} field is empty`);
    for (const part of raw.split(",")) {
        if (part === "") throw new Error(`Empty list item in ${spec.name.toLowerCase()} field`);
        let base = part, stepStr = null;
        const slash = part.indexOf("/");
        if (slash >= 0) { base = part.slice(0, slash); stepStr = part.slice(slash + 1); }
        let step = 1;
        if (stepStr !== null) {
            if (!/^\d+$/.test(stepStr) || +stepStr === 0) throw new Error(`Invalid step "/${stepStr}" in ${spec.name.toLowerCase()} field`);
            step = +stepStr;
        }
        let from, to, type;
        if (base === "*" || base === "?") {
            from = spec.min; to = top; type = stepStr !== null ? "step" : "all";
        } else if (base.includes("-")) {
            const [a, b, extra] = base.split("-");
            if (extra !== undefined || a === "" || b === "") throw new Error(`Invalid range "${base}" in ${spec.name.toLowerCase()} field`);
            from = parseVal(a); to = parseVal(b);
            if (spec.key === "dow" && to === 7 && from > 0) to = 7; // e.g. 5-7 => Fri..Sun
            if (from > to) throw new Error(`Range "${base}" runs backwards in ${spec.name.toLowerCase()} field`);
            type = stepStr !== null ? "rangestep" : "range";
        } else {
            from = parseVal(base);
            if (stepStr !== null) { to = top; type = "rangestep"; }
            else { to = from; type = "value"; }
        }
        for (let v = from; v <= to; v += step) values.add(spec.key === "dow" && v === 7 ? 0 : v);
        terms.push({ type, from, to, step });
    }
    const all = terms.length === 1 && terms[0].type === "all";
    return { raw, all, values, terms };
}

function parseCron(input) {
    let expr = (input || "").trim().replace(/\s+/g, " ");
    if (!expr) throw new Error("Enter a cron expression");
    let alias = null;
    if (expr.startsWith("@")) {
        const a = CRON_ALIASES[expr.toLowerCase()];
        if (!a) throw new Error(`Unknown alias "${expr}" (try @hourly, @daily, @weekly, @monthly, @yearly)`);
        alias = expr.toLowerCase(); expr = a;
    }
    const parts = expr.split(" ");
    if (parts.length !== 5 && parts.length !== 6) throw new Error(`Expected 5 fields (or 6 with seconds), got ${parts.length}`);
    const hasSeconds = parts.length === 6;
    const specs = hasSeconds ? CRON_FIELDS : CRON_FIELDS.slice(1);
    const fields = {};
    specs.forEach((spec, i) => { fields[spec.key] = cronParseField(parts[i], spec); });
    if (!hasSeconds) fields.second = { raw: "0", all: false, values: new Set([0]), terms: [{ type: "value", from: 0, to: 0, step: 1 }], implicit: true };
    return { expr, alias, hasSeconds, fields };
}

function joinAnd(items) {
    if (items.length <= 1) return items.join("");
    if (items.length === 2) return items[0] + " and " + items[1];
    return items.slice(0, -1).join(", ") + ", and " + items[items.length - 1];
}
function ordinal(n) {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
function pad2(n) { return String(n).padStart(2, "0"); }

function cronFieldDesc(field, key) {
    const label = { second: "second", minute: "minute", hour: "hour", dom: "day-of-month", month: "month", dow: "day-of-week" }[key];
    const fmt = v => key === "month" ? CRON_MONTH_NAMES[v - 1] : key === "dow" ? CRON_DAY_NAMES[v % 7] : String(v);
    const named = key === "month" || key === "dow";
    if (field.all) return `every ${label}`;
    const vals = field.terms.filter(t => t.type === "value").map(t => fmt(t.from));
    const out = [];
    if (vals.length) out.push(named ? joinAnd(vals) : `${label} ${joinAnd(vals)}`);
    for (const t of field.terms) {
        if (t.type === "value") continue;
        if (t.type === "step") out.push(named || key === "dom" ? `every ${ordinal(t.step)} ${label}` : `every ${t.step} ${label}s`);
        else if (t.type === "range") out.push(named ? `${fmt(t.from)} through ${fmt(t.to)}` : `every ${label} from ${fmt(t.from)} through ${fmt(t.to)}`);
        else if (t.type === "rangestep") out.push((named || key === "dom" ? `every ${ordinal(t.step)} ${label}` : `every ${t.step} ${label}s`) + ` from ${fmt(t.from)} through ${fmt(t.to)}`);
    }
    return out.join(" and ");
}

function cronDescribe(p) {
    const f = p.fields;
    const onlyValues = fld => fld.terms.every(t => t.type === "value");
    const sorted = fld => [...fld.values].sort((a, b) => a - b);
    let time = null;
    if (onlyValues(f.minute) && onlyValues(f.hour) && onlyValues(f.second) && f.second.values.size === 1) {
        const sec = sorted(f.second)[0];
        const combos = [];
        for (const h of sorted(f.hour)) for (const m of sorted(f.minute)) combos.push(pad2(h) + ":" + pad2(m) + (p.hasSeconds && sec !== 0 ? ":" + pad2(sec) : ""));
        if (combos.length <= 6) time = "at " + joinAnd(combos);
    }
    if (!time) {
        const parts = [];
        const secTrivial = f.second.values.size === 1 && f.second.values.has(0) && onlyValues(f.second);
        if (p.hasSeconds && !secTrivial) parts.push(onlyValues(f.second) ? "at " + cronFieldDesc(f.second, "second") : cronFieldDesc(f.second, "second"));
        if (f.minute.all) { if (!parts.length) parts.push("every minute"); }
        else parts.push(onlyValues(f.minute) ? "at " + cronFieldDesc(f.minute, "minute") : cronFieldDesc(f.minute, "minute"));
        if (!f.hour.all) parts.push(onlyValues(f.hour) ? "past " + cronFieldDesc(f.hour, "hour") : cronFieldDesc(f.hour, "hour"));
        time = parts.join(", ");
    }
    const date = [];
    const domC = f.dom.all ? null : "on " + cronFieldDesc(f.dom, "dom");
    const dowC = f.dow.all ? null : "on " + cronFieldDesc(f.dow, "dow");
    if (domC && dowC) date.push(domC + " or " + dowC);
    else if (domC) date.push(domC);
    else if (dowC) date.push(dowC);
    if (!f.month.all) date.push("in " + cronFieldDesc(f.month, "month"));
    let s = [time, ...date].join(" ");
    return s.charAt(0).toUpperCase() + s.slice(1) + ".";
}

function cronDayMatches(p, d) {
    const f = p.fields;
    const domOk = f.dom.values.has(d.getDate());
    const dowOk = f.dow.values.has(d.getDay());
    if (!f.dom.all && !f.dow.all) return domOk || dowOk;
    if (!f.dom.all) return domOk;
    if (!f.dow.all) return dowOk;
    return true;
}

function cronNext(p, from, count) {
    const f = p.fields;
    count = count || 5;
    let t = new Date(from.getTime());
    t.setMilliseconds(0);
    if (p.hasSeconds) t.setSeconds(t.getSeconds() + 1);
    else { t.setSeconds(0); t.setMinutes(t.getMinutes() + 1); }
    const out = [];
    let guard = 0;
    while (out.length < count && guard++ < 300000) {
        const y = t.getFullYear(), mo = t.getMonth(), d = t.getDate(), h = t.getHours(), mi = t.getMinutes(), s = t.getSeconds();
        if (!f.month.values.has(mo + 1)) { t = new Date(y, mo + 1, 1, 0, 0, 0); continue; }
        if (!cronDayMatches(p, t)) { t = new Date(y, mo, d + 1, 0, 0, 0); continue; }
        if (!f.hour.values.has(h)) { t = new Date(y, mo, d, h + 1, 0, 0); continue; }
        if (!f.minute.values.has(mi)) { t = new Date(y, mo, d, h, mi + 1, 0); continue; }
        if (!f.second.values.has(s)) { t = new Date(y, mo, d, h, mi, s + 1); continue; }
        out.push(new Date(t.getTime()));
        t = p.hasSeconds ? new Date(y, mo, d, h, mi, s + 1) : new Date(y, mo, d, h, mi + 1, 0);
    }
    return out;
}

function relativeTime(ms) {
    const s = Math.round(ms / 1000);
    if (s < 60) return `in ${s}s`;
    const m = Math.floor(s / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (m < 60) return `in ${m}m ${s % 60}s`;
    if (h < 48) return `in ${h}h ${m % 60}m`;
    return `in ${d}d ${h % 24}h`;
}

/* ── HTML Entities (pure) ── */
const HTML_ENTITIES = {
    amp: 38, lt: 60, gt: 62, quot: 34, apos: 39, nbsp: 160, iexcl: 161, cent: 162, pound: 163, curren: 164, yen: 165,
    brvbar: 166, sect: 167, uml: 168, copy: 169, ordf: 170, laquo: 171, not: 172, shy: 173, reg: 174, macr: 175, deg: 176,
    plusmn: 177, sup2: 178, sup3: 179, acute: 180, micro: 181, para: 182, middot: 183, cedil: 184, sup1: 185, ordm: 186,
    raquo: 187, frac14: 188, frac12: 189, frac34: 190, iquest: 191, Agrave: 192, Aacute: 193, Acirc: 194, Atilde: 195,
    Auml: 196, Aring: 197, AElig: 198, Ccedil: 199, Egrave: 200, Eacute: 201, Ecirc: 202, Euml: 203, Igrave: 204,
    Iacute: 205, Icirc: 206, Iuml: 207, ETH: 208, Ntilde: 209, Ograve: 210, Oacute: 211, Ocirc: 212, Otilde: 213, Ouml: 214,
    times: 215, Oslash: 216, Ugrave: 217, Uacute: 218, Ucirc: 219, Uuml: 220, Yacute: 221, THORN: 222, szlig: 223,
    agrave: 224, aacute: 225, acirc: 226, atilde: 227, auml: 228, aring: 229, aelig: 230, ccedil: 231, egrave: 232,
    eacute: 233, ecirc: 234, euml: 235, igrave: 236, iacute: 237, icirc: 238, iuml: 239, eth: 240, ntilde: 241, ograve: 242,
    oacute: 243, ocirc: 244, otilde: 245, ouml: 246, divide: 247, oslash: 248, ugrave: 249, uacute: 250, ucirc: 251,
    uuml: 252, yacute: 253, thorn: 254, yuml: 255, OElig: 338, oelig: 339, Scaron: 352, scaron: 353, Yuml: 376, fnof: 402,
    circ: 710, tilde: 732, Alpha: 913, Beta: 914, Gamma: 915, Delta: 916, Epsilon: 917, Zeta: 918, Eta: 919, Theta: 920,
    Iota: 921, Kappa: 922, Lambda: 923, Mu: 924, Nu: 925, Xi: 926, Omicron: 927, Pi: 928, Rho: 929, Sigma: 931, Tau: 932,
    Upsilon: 933, Phi: 934, Chi: 935, Psi: 936, Omega: 937, alpha: 945, beta: 946, gamma: 947, delta: 948, epsilon: 949,
    zeta: 950, eta: 951, theta: 952, iota: 953, kappa: 954, lambda: 955, mu: 956, nu: 957, xi: 958, omicron: 959, pi: 960,
    rho: 961, sigmaf: 962, sigma: 963, tau: 964, upsilon: 965, phi: 966, chi: 967, psi: 968, omega: 969, thetasym: 977,
    upsih: 978, piv: 982, ensp: 8194, emsp: 8195, thinsp: 8201, zwnj: 8204, zwj: 8205, lrm: 8206, rlm: 8207, ndash: 8211,
    mdash: 8212, lsquo: 8216, rsquo: 8217, sbquo: 8218, ldquo: 8220, rdquo: 8221, bdquo: 8222, dagger: 8224, Dagger: 8225,
    bull: 8226, hellip: 8230, permil: 8240, prime: 8242, Prime: 8243, lsaquo: 8249, rsaquo: 8250, oline: 8254, frasl: 8260,
    euro: 8364, image: 8465, weierp: 8472, real: 8476, trade: 8482, alefsym: 8501, larr: 8592, uarr: 8593, rarr: 8594,
    darr: 8595, harr: 8596, crarr: 8629, lArr: 8656, uArr: 8657, rArr: 8658, dArr: 8659, hArr: 8660, forall: 8704,
    part: 8706, exist: 8707, empty: 8709, nabla: 8711, isin: 8712, notin: 8713, ni: 8715, prod: 8719, sum: 8721, minus: 8722,
    lowast: 8727, radic: 8730, prop: 8733, infin: 8734, ang: 8736, and: 8743, or: 8744, cap: 8745, cup: 8746, int: 8747,
    there4: 8756, sim: 8764, cong: 8773, asymp: 8776, ne: 8800, equiv: 8801, le: 8804, ge: 8805, sub: 8834, sup: 8835,
    nsub: 8836, sube: 8838, supe: 8839, oplus: 8853, otimes: 8855, perp: 8869, sdot: 8901, lceil: 8968, rceil: 8969,
    lfloor: 8970, rfloor: 8971, lang: 9001, rang: 9002, loz: 9674, spades: 9824, clubs: 9827, hearts: 9829, diams: 9830,
    check: 10003, cross: 10007, star: 9734, starf: 9733, hyphen: 8208, dash: 8208, NewLine: 10, Tab: 9,
};
const HTML_ENTITY_BY_CODE = (() => {
    const m = {};
    for (const [name, code] of Object.entries(HTML_ENTITIES)) if (!(code in m)) m[code] = name;
    m[39] = "#39"; // &apos; is HTML5-only; &#39; is universally safe
    return m;
})();

function encodeEntities(text, opts) {
    opts = opts || {};
    const mode = opts.mode || "named", scope = opts.scope || "unsafe";
    const unsafe = new Set([38, 60, 62, 34, 39]);
    let out = "";
    for (const ch of text) {
        const cp = ch.codePointAt(0);
        const hit = unsafe.has(cp) || (scope === "nonascii" && cp > 126);
        if (!hit) { out += ch; continue; }
        if (mode === "named" && HTML_ENTITY_BY_CODE[cp]) out += "&" + HTML_ENTITY_BY_CODE[cp] + ";";
        else if (mode === "hex") out += "&#x" + cp.toString(16).toUpperCase() + ";";
        else out += "&#" + cp + ";";
    }
    return out;
}

function decodeEntities(text) {
    return text.replace(/&(#[xX][0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]*);/g, (m, body) => {
        let cp;
        if (body[0] === "#") cp = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
        else if (body in HTML_ENTITIES) cp = HTML_ENTITIES[body];
        else return m;
        if (!(cp >= 0 && cp <= 0x10FFFF) || (cp >= 0xD800 && cp <= 0xDFFF)) return m;
        return String.fromCodePoint(cp);
    });
}

/* ── String Escape (pure) ── */
function escapeCString(s, style) {
    // style: "json" | "js" | "python"
    let out = "";
    for (const ch of s) {
        const cp = ch.codePointAt(0);
        switch (ch) {
            case "\\": out += "\\\\"; continue;
            case '"': out += '\\"'; continue;
            case "\n": out += "\\n"; continue;
            case "\r": out += "\\r"; continue;
            case "\t": out += "\\t"; continue;
            case "\b": out += "\\b"; continue;
            case "\f": out += "\\f"; continue;
        }
        if (style !== "json" && ch === "'") { out += "\\'"; continue; }
        if (style !== "json" && ch === "\v") { out += "\\v"; continue; }
        if (style !== "json" && ch === "\0") { out += "\\0"; continue; }
        if (cp < 0x20 || cp === 0x7f) { out += style === "json" ? "\\u" + cp.toString(16).padStart(4, "0") : "\\x" + cp.toString(16).padStart(2, "0"); continue; }
        if (style === "js" && (cp === 0x2028 || cp === 0x2029)) { out += "\\u" + cp.toString(16); continue; }
        out += ch;
    }
    return out;
}

function unescapeCString(s) {
    const simple = { n: "\n", r: "\r", t: "\t", b: "\b", f: "\f", v: "\v", "0": "\0", a: "\x07", "\\": "\\", '"': '"', "'": "'", "/": "/" };
    return s.replace(/\\(u\{([0-9a-fA-F]{1,6})\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|([0-7]{1,3})|(\r?\n)|(.))/gs, (m, all, ub, u4, x2, oct, nl, c) => {
        if (ub) return String.fromCodePoint(parseInt(ub, 16));
        if (u4) return String.fromCharCode(parseInt(u4, 16));
        if (x2) return String.fromCharCode(parseInt(x2, 16));
        if (oct) return String.fromCharCode(parseInt(oct, 8));
        if (nl) return "";
        if (c in simple) return simple[c];
        return c;
    });
}

function escapeCsvField(s) {
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function unescapeCsvField(s) {
    const t = s.trim();
    if (t.length >= 2 && t[0] === '"' && t[t.length - 1] === '"') return t.slice(1, -1).replace(/""/g, '"');
    return s;
}
function escapeShellSingle(s) { return "'" + s.replace(/'/g, "'\\''") + "'"; }
function unescapeShellSingle(s) {
    let out = "", i = 0;
    const t = s.trim();
    if (!t.startsWith("'")) return t.replace(/\\(.)/g, "$1");
    while (i < t.length) {
        const ch = t[i];
        if (ch === "'") { const j = t.indexOf("'", i + 1); if (j < 0) { out += t.slice(i + 1); break; } out += t.slice(i + 1, j); i = j + 1; }
        else if (ch === "\\" && i + 1 < t.length) { out += t[i + 1]; i += 2; }
        else if (ch === '"') { const j = t.indexOf('"', i + 1); if (j < 0) { out += t.slice(i + 1); break; } out += t.slice(i + 1, j); i = j + 1; }
        else { out += ch; i++; }
    }
    return out;
}
function escapeRegex(s) { return s.replace(/[.*+?^${}()|[\]\\\/-]/g, "\\$&"); }
function unescapeRegex(s) { return s.replace(/\\([.*+?^${}()|[\]\\\/-])/g, "$1"); }

function stringEscape(s, lang, direction) {
    const enc = direction !== "unescape";
    switch (lang) {
        case "json": return enc ? escapeCString(s, "json") : unescapeCString(s);
        case "js": return enc ? escapeCString(s, "js") : unescapeCString(s);
        case "python": return enc ? escapeCString(s, "python") : unescapeCString(s);
        case "htmlattr": return enc ? encodeEntities(s, { mode: "named", scope: "unsafe" }) : decodeEntities(s);
        case "csv": return enc ? escapeCsvField(s) : unescapeCsvField(s);
        case "shell": return enc ? escapeShellSingle(s) : unescapeShellSingle(s);
        case "url": return enc ? encodeURIComponent(s) : decodeURIComponent(s);
        case "regex": return enc ? escapeRegex(s) : unescapeRegex(s);
    }
    throw new Error("Unknown language: " + lang);
}

/* ── Number Base (pure) ── */
function parseBigIntBase(str, base) {
    let s = String(str).trim().replace(/[\s_,]/g, "");
    if (!s) return null;
    let neg = false;
    if (s[0] === "-" || s[0] === "+") { neg = s[0] === "-"; s = s.slice(1); }
    const pre = s.slice(0, 2).toLowerCase();
    if ((base === 16 && pre === "0x") || (base === 2 && pre === "0b") || (base === 8 && pre === "0o")) s = s.slice(2);
    if (!s) throw new Error("No digits after prefix");
    const digits = "0123456789abcdefghijklmnopqrstuvwxyz";
    const B = BigInt(base);
    let n = 0n;
    for (const ch of s.toLowerCase()) {
        const d = digits.indexOf(ch);
        if (d < 0 || d >= base) throw new Error(`"${ch}" is not a valid base-${base} digit`);
        n = n * B + BigInt(d);
    }
    return neg ? -n : n;
}

function groupDigits(s, size, sep) {
    const padLen = (size - (s.length % size)) % size;
    s = "0".repeat(padLen) + s;
    return s.match(new RegExp(`.{${size}}`, "g")).join(sep === undefined ? " " : sep);
}

function baseOutputs(n, upper) {
    const neg = n < 0n, a = neg ? -n : n, sign = neg ? "-" : "";
    const hex = a.toString(16);
    const out = {
        binary: sign + groupDigits(a.toString(2), 4),
        octal: sign + a.toString(8),
        decimal: n.toString(),
        hex: sign + (upper ? hex.toUpperCase() : hex),
        base36: sign + (upper ? a.toString(36).toUpperCase() : a.toString(36)),
        char: null,
    };
    if (!neg && a <= 0x10FFFFn) {
        const cp = Number(a);
        const surrogate = cp >= 0xD800 && cp <= 0xDFFF;
        out.char = { codePoint: "U+" + cp.toString(16).toUpperCase().padStart(4, "0"), char: surrogate ? null : String.fromCodePoint(cp), control: cp < 32 || (cp >= 127 && cp < 160) };
    }
    return out;
}

function twosComplement(n, bits) {
    const min = -(1n << BigInt(bits - 1)), max = (1n << BigInt(bits)) - 1n;
    if (n < min || n > max) return null;
    const u = BigInt.asUintN(bits, n);
    return {
        bin: groupDigits(u.toString(2).padStart(bits, "0"), 8),
        hex: u.toString(16).padStart(bits / 4, "0"),
        unsigned: u.toString(),
        signed: BigInt.asIntN(bits, n).toString(),
    };
}

/* ── Unit Converter (pure) ── */
const UNIT_CATEGORIES = {
    length: { label: "Length", units: {
        meter: 1, kilometer: 1e3, centimeter: 1e-2, millimeter: 1e-3, micrometer: 1e-6, nanometer: 1e-9,
        mile: 1609.344, yard: 0.9144, foot: 0.3048, inch: 0.0254, "nautical mile": 1852,
        "astronomical unit": 149597870700, "light-year": 9460730472580800,
    } },
    mass: { label: "Mass", units: {
        kilogram: 1, gram: 1e-3, milligram: 1e-6, microgram: 1e-9, tonne: 1000,
        pound: 0.45359237, ounce: 0.028349523125, stone: 6.35029318, "US ton": 907.18474, "imperial ton": 1016.0469088,
    } },
    temperature: { label: "Temperature", units: {
        celsius: { to: c => c, from: c => c },
        fahrenheit: { to: f => (f - 32) * 5 / 9, from: c => c * 9 / 5 + 32 },
        kelvin: { to: k => k - 273.15, from: c => c + 273.15 },
        rankine: { to: r => (r - 491.67) * 5 / 9, from: c => (c + 273.15) * 9 / 5 },
    } },
    area: { label: "Area", units: {
        "square meter": 1, "square kilometer": 1e6, "square centimeter": 1e-4, "square millimeter": 1e-6, hectare: 1e4,
        acre: 4046.8564224, "square mile": 2589988.110336, "square yard": 0.83612736, "square foot": 0.09290304, "square inch": 0.00064516,
    } },
    volume: { label: "Volume", units: {
        liter: 1, milliliter: 1e-3, "cubic meter": 1000, "cubic centimeter": 1e-3, "US gallon": 3.785411784, "US quart": 0.946352946,
        "US pint": 0.473176473, "US cup": 0.2365882365, "US fluid ounce": 0.0295735295625, tablespoon: 0.01478676478125,
        teaspoon: 0.00492892159375, "imperial gallon": 4.54609, "imperial pint": 0.56826125, "cubic foot": 28.316846592, "cubic inch": 0.016387064,
    } },
    speed: { label: "Speed", units: {
        "meter/second": 1, "kilometer/hour": 1 / 3.6, "mile/hour": 0.44704, "foot/second": 0.3048, knot: 1852 / 3600,
        "mach (sea level)": 340.29, "speed of light": 299792458,
    } },
    time: { label: "Time", units: {
        nanosecond: 1e-9, microsecond: 1e-6, millisecond: 1e-3, second: 1, minute: 60, hour: 3600, day: 86400, week: 604800,
        "month (avg)": 2629746, "year (avg)": 31556952, decade: 315569520, century: 3155695200,
    } },
    data: { label: "Data size", units: {
        bit: 1, byte: 8, kilobit: 1e3, kibibit: 1024, kilobyte: 8e3, kibibyte: 8192, megabit: 1e6, mebibit: 1048576,
        megabyte: 8e6, mebibyte: 8388608, gigabit: 1e9, gibibit: 1073741824, gigabyte: 8e9, gibibyte: 8589934592,
        terabit: 1e12, tebibit: 1099511627776, terabyte: 8e12, tebibyte: 8796093022208, petabyte: 8e15, pebibyte: 9007199254740992,
    } },
    energy: { label: "Energy", units: {
        joule: 1, kilojoule: 1e3, megajoule: 1e6, calorie: 4.184, kilocalorie: 4184, "watt-hour": 3600, "kilowatt-hour": 3.6e6,
        electronvolt: 1.602176634e-19, BTU: 1055.05585262, "foot-pound": 1.3558179483314004, erg: 1e-7,
    } },
    pressure: { label: "Pressure", units: {
        pascal: 1, kilopascal: 1e3, megapascal: 1e6, bar: 1e5, millibar: 100, atmosphere: 101325, psi: 6894.757293168,
        torr: 101325 / 760, mmHg: 133.322387415, inHg: 3386.389,
    } },
};

function formatUnitValue(v) {
    if (!isFinite(v)) return String(v);
    if (v === 0) return "0";
    const r = Number(v.toPrecision(12));
    const a = Math.abs(r);
    if (a >= 1e15 || a < 1e-6) return r.toExponential(6).replace(/\.?0+e/, "e");
    return String(r);
}

function convertUnit(cat, value, from, to) {
    const c = UNIT_CATEGORIES[cat];
    if (!c) throw new Error("Unknown category");
    const uf = c.units[from], ut = c.units[to];
    if (uf === undefined || ut === undefined) throw new Error("Unknown unit");
    if (typeof uf === "object") return ut.from(uf.to(value));
    return value * uf / ut;
}

/* ── Slug Generator (pure) ── */
const SLUG_CHAR_MAP = {
    "ß": "ss", "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "TH", "ı": "i", "ħ": "h", "Ħ": "H", "ŧ": "t", "Ŧ": "T", "ŋ": "n", "Ŋ": "N",
    "ſ": "s", "ƒ": "f", "ŀ": "l", "Ŀ": "L", "ĸ": "k", "«": "", "»": "", "“": "", "”": "", "‘": "", "’": "", "…": "",
    "€": "euro", "£": "pound", "$": "dollar", "%": " percent ", "+": " plus ", "@": " at ",
};
const SLUG_STOP_WORDS = new Set(["a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for", "with", "by", "from", "is", "are", "was", "were", "it", "this", "that", "as", "be", "into", "vs"]);

function slugify(text, opts) {
    opts = opts || {};
    const sep = opts.separator || "-";
    let s = text.replace(/&/g, " and ").replace(/[$%+@€£]/g, ch => SLUG_CHAR_MAP[ch]);
    if (opts.transliterate !== false) {
        s = s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        s = s.replace(/[^\x00-\x7F]/g, ch => SLUG_CHAR_MAP[ch] !== undefined ? SLUG_CHAR_MAP[ch] : ch);
    }
    if (opts.lowercase !== false) s = s.toLowerCase();
    s = s.replace(/'/g, "");
    const keep = opts.transliterate !== false ? /[^A-Za-z0-9]+/g : /[^\p{L}\p{N}]+/gu;
    let words = s.split(keep).filter(Boolean);
    if (opts.removeStopWords && words.length > 1) {
        const kept = words.filter(w => !SLUG_STOP_WORDS.has(w.toLowerCase()));
        if (kept.length) words = kept;
    }
    let out = words.join(sep);
    const max = parseInt(opts.maxLength, 10);
    if (max > 0 && out.length > max) {
        out = out.slice(0, max);
        const cut = out.lastIndexOf(sep);
        if (cut > 0) out = out.slice(0, cut);
    }
    return out;
}

/* ── Markdown Table (pure) ── */
function detectDelimiter(text) {
    const first = text.split(/\r?\n/).find(l => l.trim()) || "";
    let best = ",", bestCount = 0;
    for (const d of ["\t", ",", ";", "|"]) {
        let count = 0, inQ = false;
        for (const ch of first) { if (ch === '"') inQ = !inQ; else if (!inQ && ch === d) count++; }
        if (count > bestCount) { best = d; bestCount = count; }
    }
    return best;
}

function parseDelimited(text, delim) {
    delim = delim || detectDelimiter(text);
    const rows = [];
    let row = [], field = "", inQ = false, quoted = false, i = 0;
    while (i < text.length) {
        const ch = text[i];
        if (inQ) {
            if (ch === '"') { if (text[i + 1] === '"') { field += '"'; i += 2; continue; } inQ = false; i++; continue; }
            field += ch; i++; continue;
        }
        if (ch === '"' && field.trim() === "" && !quoted) { inQ = true; quoted = true; field = ""; i++; continue; }
        if (ch === delim) { row.push(quoted ? field : field.trim()); field = ""; quoted = false; i++; continue; }
        if (ch === "\r") { i++; continue; }
        if (ch === "\n") { row.push(quoted ? field : field.trim()); rows.push(row); row = []; field = ""; quoted = false; i++; continue; }
        field += ch; i++;
    }
    if (field !== "" || quoted || row.length) { row.push(quoted ? field : field.trim()); rows.push(row); }
    let out = rows.filter(r => r.some(c => c !== ""));
    if (delim === "|") {
        out = out.map(r => { r = r.slice(); if (r.length && r[0] === "") r.shift(); if (r.length && r[r.length - 1] === "") r.pop(); return r; })
            .filter(r => !r.every(c => /^:?-+:?$/.test(c)));
    }
    return out;
}

function strWidth(s) { return [...s].length; }

function toMarkdownTable(rows, aligns, opts) {
    opts = opts || {};
    if (!rows || !rows.length) return "";
    const ncols = Math.max(...rows.map(r => r.length));
    if (ncols === 0) return "";
    const clean = rows.map(r => { const c = r.slice(); while (c.length < ncols) c.push(""); return c.map(v => String(v).replace(/\|/g, "\\|").replace(/\r?\n/g, "<br>")); });
    let header, body;
    if (opts.header === false) { header = Array.from({ length: ncols }, (_, i) => "Column " + (i + 1)); body = clean; }
    else { header = clean[0]; body = clean.slice(1); }
    aligns = Array.from({ length: ncols }, (_, i) => (aligns && aligns[i]) || "left");
    const widths = header.map((h, c) => Math.max(3, strWidth(h), ...body.map(r => strWidth(r[c]))));
    const padCell = (v, c) => {
        if (opts.compact) return v;
        const extra = widths[c] - strWidth(v);
        if (aligns[c] === "right") return " ".repeat(extra) + v;
        if (aligns[c] === "center") { const l = Math.floor(extra / 2); return " ".repeat(l) + v + " ".repeat(extra - l); }
        return v + " ".repeat(extra);
    };
    // Separator cells: compact uses 3-wide cells inside the normal "| x | y |"
    // layout; padded output spans the full column width so the pipes line up.
    const sepCell = c => {
        const w = opts.compact ? 3 : widths[c] + 2;
        if (aligns[c] === "center") return ":" + "-".repeat(w - 2) + ":";
        if (aligns[c] === "right") return "-".repeat(w - 1) + ":";
        return "-".repeat(w);
    };
    const line = cells => "| " + cells.join(" | ") + " |";
    const sepLine = opts.compact ? line(header.map((_, c) => sepCell(c))) : "|" + header.map((_, c) => sepCell(c)).join("|") + "|";
    const out = [line(header.map(padCell)), sepLine];
    for (const r of body) out.push(line(r.map(padCell)));
    return out.join("\n");
}

function splitMarkdownRow(line) {
    let t = line.trim();
    if (t.startsWith("|")) t = t.slice(1);
    if (t.endsWith("|") && !t.endsWith("\\|")) t = t.slice(0, -1);
    const cells = []; let cur = "";
    for (let i = 0; i < t.length; i++) {
        if (t[i] === "\\" && t[i + 1] === "|") { cur += "|"; i++; }
        else if (t[i] === "|") { cells.push(cur); cur = ""; }
        else cur += t[i];
    }
    cells.push(cur);
    return cells.map(c => c.trim().replace(/<br\s*\/?>/gi, "\n"));
}

function markdownTableToRows(md) {
    const lines = md.split(/\r?\n/).filter(l => l.trim() && l.includes("|"));
    return lines.map(splitMarkdownRow).filter(cells => !cells.every(c => /^:?-+:?$/.test(c) || c === ""));
}

function rowsToCsv(rows, delim) {
    delim = delim || ",";
    const rx = new RegExp(`["\\r\\n${delim === "\t" ? "\\t" : delim}]`);
    return rows.map(r => r.map(c => rx.test(c) ? '"' + c.replace(/"/g, '""') + '"' : c).join(delim)).join("\n");
}

/* ── DOM wiring: Line Tools, HTML Entities, String Escape, Markdown Table, Text to Speech ── */
function doLines(op) {
    const input = document.getElementById("lt-input").value;
    const out = lineTransform(input, op, {
        caseSensitive: document.getElementById("lt-case").checked,
        prefix: document.getElementById("lt-prefix").value,
        suffix: document.getElementById("lt-suffix").value,
        sep: document.getElementById("lt-sep").value,
    });
    document.getElementById("lt-output").value = out;
    document.getElementById("lt-count").textContent =
        `${countLines(input)} line${countLines(input) === 1 ? "" : "s"} in → ${countLines(out)} out`;
}
function linesUseOutput() {
    const out = document.getElementById("lt-output");
    if (!out.value) return;
    document.getElementById("lt-input").value = out.value;
    out.value = "";
    document.getElementById("lt-count").textContent = `${countLines(document.getElementById("lt-input").value)} lines`;
}

let entDirection = "encode";
function entOpts() {
    return {
        mode: document.querySelector("[data-ent-mode].active")?.dataset.entMode || "named",
        scope: document.querySelector("[data-ent-scope].active")?.dataset.entScope || "unsafe",
    };
}
function entRun() {
    const input = document.getElementById("ent-input").value;
    document.getElementById("ent-output").value = entDirection === "encode" ? encodeEntities(input, entOpts()) : decodeEntities(input);
}
function entSetDirection(dir) {
    entDirection = dir;
    document.getElementById("ent-mode-encode").classList.toggle("active", dir === "encode");
    document.getElementById("ent-mode-decode").classList.toggle("active", dir === "decode");
    document.getElementById("ent-encode-opts").style.display = dir === "encode" ? "" : "none";
    entRun();
}

let escDirection = "escape";
function escRun() {
    const err = document.getElementById("esc-error");
    err.hidden = true;
    try {
        document.getElementById("esc-output").value =
            stringEscape(document.getElementById("esc-input").value, document.getElementById("esc-lang").value, escDirection);
    } catch (e) {
        document.getElementById("esc-output").value = "";
        err.textContent = "Could not " + escDirection + ": " + e.message;
        err.hidden = false;
    }
}
function escSetDirection(dir) {
    escDirection = dir;
    document.getElementById("esc-dir-escape").classList.toggle("active", dir === "escape");
    document.getElementById("esc-dir-unescape").classList.toggle("active", dir === "unescape");
    escRun();
}

/* Markdown table: the grid is the source of truth; pasting CSV fills the grid. */
let mtRows = [["Name", "Role"], ["", ""]];
let mtAligns = [];
function mtRenderGrid() {
    const table = document.getElementById("mt-grid");
    const ncols = Math.max(1, ...mtRows.map(r => r.length));
    mtRows = mtRows.map(r => { const c = r.slice(); while (c.length < ncols) c.push(""); return c; });
    while (mtAligns.length < ncols) mtAligns.push("left");
    let html = "<tr>" + mtRows[0].map((_, c) => `<th><select data-col="${c}" title="Alignment">` +
        ["left", "center", "right"].map(a => `<option value="${a}"${mtAligns[c] === a ? " selected" : ""}>${a[0].toUpperCase() + a.slice(1)}</option>`).join("") +
        `</select><button type="button" class="tt-grid-x" data-delcol="${c}" title="Remove column">&times;</button></th>`).join("") + "<th></th></tr>";
    html += mtRows.map((row, r) => "<tr>" + row.map((v, c) =>
        `<td><input type="text" data-r="${r}" data-c="${c}" value="${esc(v)}"></td>`).join("") +
        `<td><button type="button" class="tt-grid-x" data-delrow="${r}" title="Remove row">&times;</button></td></tr>`).join("");
    table.innerHTML = html;
    table.querySelectorAll("input[data-r]").forEach(inp => inp.addEventListener("input", () => {
        mtRows[+inp.dataset.r][+inp.dataset.c] = inp.value; mtRender();
    }));
    table.querySelectorAll("select[data-col]").forEach(sel => sel.addEventListener("change", () => {
        mtAligns[+sel.dataset.col] = sel.value; mtRender();
    }));
    table.querySelectorAll("[data-delcol]").forEach(b => b.addEventListener("click", () => {
        if (mtRows[0].length <= 1) return;
        const c = +b.dataset.delcol; mtRows.forEach(r => r.splice(c, 1)); mtAligns.splice(c, 1); mtRenderGrid(); mtRender();
    }));
    table.querySelectorAll("[data-delrow]").forEach(b => b.addEventListener("click", () => {
        if (mtRows.length <= 1) return;
        mtRows.splice(+b.dataset.delrow, 1); mtRenderGrid(); mtRender();
    }));
}
function mtRender() {
    document.getElementById("mt-output").value = toMarkdownTable(mtRows, mtAligns, {
        header: document.getElementById("mt-header").checked,
        compact: document.getElementById("mt-compact").checked,
    });
}
function mtFromInput() {
    const text = document.getElementById("mt-input").value;
    if (!text.trim()) return;
    mtRows = parseDelimited(text);
    mtAligns = [];
    mtRenderGrid(); mtRender();
}
function mtAddRow() { mtRows.push(new Array(mtRows[0].length).fill("")); mtRenderGrid(); mtRender(); }
function mtAddCol() { mtRows.forEach(r => r.push("")); mtAligns.push("left"); mtRenderGrid(); mtRender(); }
function mtClear() { mtRows = [["", ""], ["", ""]]; mtAligns = []; document.getElementById("mt-input").value = ""; mtRenderGrid(); mtRender(); }
function mtSetMode(mode) {
    document.getElementById("mt-mode-build").classList.toggle("active", mode === "build");
    document.getElementById("mt-mode-reverse").classList.toggle("active", mode === "reverse");
    document.getElementById("mt-build").hidden = mode !== "build";
    document.getElementById("mt-reverse").hidden = mode !== "reverse";
}
function mtReverse() {
    const rows = markdownTableToRows(document.getElementById("mt-md-input").value);
    document.getElementById("mt-csv-output").value = rowsToCsv(rows, document.getElementById("mt-csv-delim").value);
}

/* Text to speech via the Web Speech API */
let ttsVoices = [];
function ttsLoadVoices() {
    if (!("speechSynthesis" in window)) return;
    ttsVoices = speechSynthesis.getVoices();
    const sel = document.getElementById("tts-voice");
    if (!ttsVoices.length) return;
    const current = sel.value;
    sel.innerHTML = ttsVoices.map((v, i) => `<option value="${i}">${esc(v.name)} (${esc(v.lang)})${v.default ? " · default" : ""}</option>`).join("");
    const def = ttsVoices.findIndex(v => v.default);
    sel.value = current && ttsVoices[+current] ? current : String(def >= 0 ? def : 0);
}
function ttsSetStatus(msg) { document.getElementById("tts-status").textContent = msg; }
function ttsSpeak() {
    const err = document.getElementById("tts-error");
    err.hidden = true;
    if (!("speechSynthesis" in window)) {
        err.textContent = "This browser does not support speech synthesis."; err.hidden = false; return;
    }
    const text = document.getElementById("tts-input").value.trim();
    if (!text) { err.textContent = "Type some text first."; err.hidden = false; return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = ttsVoices[+document.getElementById("tts-voice").value];
    if (v) u.voice = v;
    u.rate = parseFloat(document.getElementById("tts-rate").value);
    u.pitch = parseFloat(document.getElementById("tts-pitch").value);
    u.onstart = () => ttsSetStatus("Speaking…");
    u.onend = () => ttsSetStatus("Done");
    u.onerror = e => { if (e.error !== "interrupted" && e.error !== "canceled") { err.textContent = "Speech failed: " + e.error; err.hidden = false; } ttsSetStatus(""); };
    speechSynthesis.speak(u);
}
function ttsPause() { if ("speechSynthesis" in window && speechSynthesis.speaking) { speechSynthesis.pause(); ttsSetStatus("Paused"); } }
function ttsResume() { if ("speechSynthesis" in window && speechSynthesis.paused) { speechSynthesis.resume(); ttsSetStatus("Speaking…"); } }
function ttsStop() { if ("speechSynthesis" in window) { speechSynthesis.cancel(); ttsSetStatus(""); } }

if (typeof document !== "undefined") {
    const on = (id, ev, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(ev, fn); };
    on("lt-input", "input", () => { document.getElementById("lt-count").textContent = `${countLines(document.getElementById("lt-input").value)} lines`; });
    on("ent-input", "input", entRun);
    document.querySelectorAll("[data-ent-mode]").forEach(b => b.addEventListener("click", () => {
        document.querySelectorAll("[data-ent-mode]").forEach(x => x.classList.remove("active")); b.classList.add("active"); entRun();
    }));
    document.querySelectorAll("[data-ent-scope]").forEach(b => b.addEventListener("click", () => {
        document.querySelectorAll("[data-ent-scope]").forEach(x => x.classList.remove("active")); b.classList.add("active"); entRun();
    }));
    on("esc-input", "input", escRun);
    on("esc-lang", "change", escRun);
    on("mt-input", "input", mtFromInput);
    on("mt-header", "change", mtRender);
    on("mt-compact", "change", mtRender);
    on("mt-md-input", "input", mtReverse);
    on("mt-csv-delim", "change", mtReverse);
    if (document.getElementById("mt-grid")) { mtRenderGrid(); mtRender(); }
    on("tts-rate", "input", () => { document.getElementById("tts-rate-val").textContent = parseFloat(document.getElementById("tts-rate").value).toFixed(1); });
    on("tts-pitch", "input", () => { document.getElementById("tts-pitch-val").textContent = parseFloat(document.getElementById("tts-pitch").value).toFixed(1); });
    if ("speechSynthesis" in window) { ttsLoadVoices(); speechSynthesis.onvoiceschanged = ttsLoadVoices; }
    else if (document.getElementById("tts-voice")) { document.getElementById("tts-voice").innerHTML = "<option>Not supported in this browser</option>"; }
}
