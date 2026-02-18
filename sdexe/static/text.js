/* ── Hash Routing ── */
function showTab(tab) {
    document.querySelectorAll(".pdf-section").forEach(s => s.classList.remove("active"));
    const el = document.getElementById("tab-" + tab);
    (el || document.querySelector(".pdf-section")).classList.add("active");
    window.scrollTo(0, 0);
}
showTab(location.hash.slice(1) || "wordcount");
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "wordcount"));

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
setRgb(59, 130, 246, "rgb");

/* ── Helpers ── */
function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function copyText(id) {
    const el = document.getElementById(id);
    navigator.clipboard.writeText(el.value || el.textContent).catch(() => {
        el.select && el.select();
        document.execCommand("copy");
    });
}
