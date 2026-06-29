/* Knowledge Base Explorer — browse, search, read, and upload the documents the
 * agent's Bedrock Knowledge Base is built from. Flat list (no scopes). Data
 * loads lazily from /api/kb/* so a slow call never blocks the page. */
(function () {
  "use strict";

  var state = { doc: null };

  // ── Helpers ────────────────────────────────────────────────────────────
  function el(id) { return document.getElementById(id); }
  // Single audited DOM-write point: callers pass static markup authored here or
  // values escaped via esc(), keeping the XSS-safety invariant in one place.
  function setHTML(node, html) {
    if (!node) return;
    node.innerHTML = html;
  }
  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function spinner(label) {
    return '<div class="h-full flex flex-col items-center justify-center gap-3 p-10" style="color: var(--text-muted);">' +
      '<div class="kb-spin"></div><p class="text-sm">' + esc(label || "Loading…") + "</p></div>";
  }
  function fmtBytes(n) {
    if (!n && n !== 0) return "";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }
  function getJSON(url) {
    return fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
  }
  function docIcon() {
    return '<svg class="w-4 h-4 shrink-0" style="color: var(--text-subtle);" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>';
  }

  // ── Documents ───────────────────────────────────────────────────────────
  function loadDocs() {
    var list = el("kb-doc-list");
    setHTML(list, spinner("Loading documents…"));
    state.doc = null;
    getJSON("/api/kb/documents").then(function (data) {
      var docs = data.documents || [];
      el("kb-doc-count").textContent = docs.length;
      if (data.error && !docs.length) {
        setHTML(list, '<div class="p-2"><div class="kb-banner kb-banner-warn">' + esc(data.error) + "</div></div>");
        return;
      }
      if (!docs.length) {
        setHTML(list, '<p class="text-xs p-3" style="color: var(--text-subtle);">No documents found. Upload a file to get started.</p>');
        return;
      }
      setHTML(list, "");
      docs.forEach(function (doc) {
        var b = document.createElement("button");
        b.className = "kb-item";
        b.dataset.key = doc.key;
        setHTML(b,
          docIcon() +
          '<span class="flex-1 min-w-0"><span class="block text-xs truncate" style="color: var(--text);">' + esc(doc.name) + "</span>" +
          '<span class="block tg-mono text-[10px] truncate" style="color: var(--text-subtle);">' + esc(fmtBytes(doc.size)) +
          (doc.readable ? "" : " · preview n/a") + "</span></span>");
        b.onclick = function () { selectDoc(doc); };
        list.appendChild(b);
      });
    }).catch(function (e) {
      setHTML(list, '<div class="p-2"><div class="kb-banner kb-banner-warn">Failed to load documents: ' + esc(e.message) + "</div></div>");
    });
  }

  function selectDoc(doc) {
    state.doc = doc.key;
    document.querySelectorAll("#kb-doc-list .kb-item").forEach(function (b) {
      b.classList.toggle("is-active", b.dataset.key === doc.key);
    });
    el("kb-doc-title").textContent = doc.name;
    el("kb-doc-sub").textContent = doc.key;
    var body = el("kb-doc-body");
    setHTML(body, spinner("Loading document…"));
    getJSON("/api/kb/document?key=" + encodeURIComponent(doc.key)).then(function (data) {
      if (data.error) {
        setHTML(body, '<div class="kb-banner kb-banner-warn">' + esc(data.error) + "</div>");
        return;
      }
      if (data.readable === false || data.notice) {
        setHTML(body, '<div class="kb-rise"><div class="kb-banner kb-banner-warn">' +
          esc(data.notice || "Preview is not available for this file type.") + "</div></div>");
        return;
      }
      setHTML(body, '<div class="kb-rise kb-doc">' + esc(data.content) + "</div>");
    }).catch(function (e) {
      setHTML(body, '<div class="kb-banner kb-banner-warn">Could not read document: ' + esc(e.message) + "</div>");
    });
  }

  // ── Semantic search ───────────────────────────────────────────────────────
  window.kbSearch = function () {
    var q = el("kb-search").value.trim();
    var panel = el("kb-results");
    if (!q) { panel.classList.add("hidden"); setHTML(panel, ""); return; }
    panel.classList.remove("hidden");
    setHTML(panel, '<div class="flex items-center gap-2 text-sm" style="color: var(--text-muted);"><div class="kb-spin"></div> Retrieving from the Knowledge Base…</div>');
    getJSON("/api/kb/search?q=" + encodeURIComponent(q)).then(function (data) {
      if (data.error) {
        setHTML(panel, '<div class="kb-banner kb-banner-warn">' + esc(data.error) + "</div>");
        return;
      }
      var results = data.results || [];
      if (!results.length) {
        setHTML(panel, '<div class="flex items-center justify-between"><span class="text-sm" style="color: var(--text-muted);">No passages retrieved for &ldquo;' + esc(q) + '&rdquo;.</span>' +
          '<button onclick="kbClearSearch()" class="tg-mono text-[11px]" style="color: var(--text-subtle);">clear ✕</button></div>');
        return;
      }
      var html = '<div class="flex items-center justify-between mb-2"><span class="tg-section-label">Top ' + results.length + ' passages</span>' +
        '<button onclick="kbClearSearch()" class="tg-mono text-[11px]" style="color: var(--text-subtle);">clear ✕</button></div>';
      html += '<div class="space-y-2 kb-scroll" style="max-height: 260px;">';
      results.forEach(function (r) {
        var fname = (r.uri || "").split("/").pop();
        html += '<div class="rounded-lg p-3" style="background: var(--surface); border: 1px solid var(--border);">' +
          '<div class="flex items-center gap-2 mb-1">' +
          '<span class="tg-mono text-[10px] px-1.5 py-0.5 rounded" style="background: rgba(var(--primary-rgb),0.14); color: var(--primary);">score ' + esc(r.score) + "</span>" +
          '<span class="tg-mono text-[10px] truncate" style="color: var(--text-subtle);">' + esc(fname) + "</span></div>" +
          '<p class="text-xs" style="color: var(--text-muted); line-height: 1.55;">' + esc((r.content || "").slice(0, 600)) + ((r.content || "").length > 600 ? "…" : "") + "</p></div>";
      });
      html += "</div>";
      setHTML(panel, html);
    }).catch(function (e) {
      setHTML(panel, '<div class="kb-banner kb-banner-warn">Search failed: ' + esc(e.message) + "</div>");
    });
  };

  window.kbClearSearch = function () {
    el("kb-search").value = "";
    var panel = el("kb-results");
    panel.classList.add("hidden");
    setHTML(panel, "");
  };

  // ── Upload ──────────────────────────────────────────────────────────────
  window.kbUpload = function (file) {
    if (!file) return;
    var status = el("kb-upload-status");
    status.classList.remove("hidden");
    setHTML(status, '<div class="kb-banner" style="border-color: var(--border); color: var(--text-muted); display:flex; align-items:center; gap:.5rem;"><div class="kb-spin"></div> Uploading ' + esc(file.name) + "…</div>");

    var form = new FormData();
    form.append("file", file);
    fetch("/api/kb/upload", { method: "POST", credentials: "same-origin", body: form })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        var d = res.data || {};
        if (!res.ok || d.error) {
          setHTML(status, '<div class="kb-banner kb-banner-warn">Upload failed: ' + esc(d.error || "unknown error") + "</div>");
          return;
        }
        var msg = "Uploaded <span class=\"tg-mono\">" + esc(d.name) + "</span>.";
        if (d.ingestion_job_id) {
          msg += " Ingestion started (job " + esc(d.ingestion_job_id) + "). New content is retrievable in a few minutes.";
        } else if (d.ingestion_error) {
          msg += " The file was stored, but ingestion could not be started automatically: " + esc(d.ingestion_error) + ". Start an ingestion job manually.";
        }
        setHTML(status, '<div class="kb-banner kb-banner-ok">' + msg + "</div>");
        loadDocs();
      })
      .catch(function (e) {
        setHTML(status, '<div class="kb-banner kb-banner-warn">Upload failed: ' + esc(e.message) + "</div>");
      })
      .finally(function () {
        var input = el("kb-file");
        if (input) input.value = "";
      });
  };

  // ── Init ───────────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", loadDocs);
})();
