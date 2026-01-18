/* global Dropzone */

(function () {
  "use strict";

  // Important: disable Dropzone auto-discovery before DOMContentLoaded.
  // Otherwise Dropzone will attach itself automatically to any <form class="dropzone">,
  // and our manual initialization will throw "Dropzone already attached".
  if (typeof Dropzone !== "undefined") {
    Dropzone.autoDiscover = false;
  }

  function formatBytes(bytes) {
    if (!bytes && bytes !== 0) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let i = 0;
    while (value >= 1024 && i < units.length - 1) {
      value /= 1024;
      i += 1;
    }
    return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }

  async function loadProjectsIntoList() {
    const list = document.getElementById("projects-list");
    if (!list) return;

    const resp = await fetch("/api/projects", { headers: { Accept: "application/json" } });
    const data = await resp.json();

    list.innerHTML = "";
    const items = data.items || [];
    if (items.length === 0) {
      list.innerHTML = '<div class="list-group-item text-muted">No projects yet.</div>';
      return;
    }

    for (const p of items) {
      const a = document.createElement("a");
      a.className = "list-group-item list-group-item-action";
      a.href = `/projects/${p.id}`;
      a.innerHTML = `
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <div class="fw-semibold">${p.title}</div>
            <div class="text-muted small" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 36rem;">${(p.intent_text || "").replace(/\n/g, " ")}</div>
          </div>
          <div class="text-muted small">#${p.id}</div>
        </div>
      `;
      list.appendChild(a);
    }
  }

  function initCreateProjectForm() {
    const form = document.getElementById("create-project-form");
    if (!form) return;

    const status = document.getElementById("create-project-status");
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      status.textContent = "";

      const title = document.getElementById("project-title").value;
      const intentText = document.getElementById("project-intent").value;

      try {
        const resp = await fetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ title: title, intent_text: intentText })
        });

        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `Request failed (${resp.status})`);
        }

        const data = await resp.json();
        status.className = "text-success";
        status.textContent = "Created.";

        // Redirect straight into the project.
        window.location.href = `/projects/${data.project.id}`;
      } catch (err) {
        status.className = "text-danger";
        status.textContent = String(err.message || err);
      }
    });
  }

  function buildIntentFromBuilderInputs() {
    const focus = (document.getElementById("focus")?.value || "").trim();
    const audience = (document.getElementById("audience")?.value || "").trim();
    const tone = (document.getElementById("tone")?.value || "").trim();
    const tags = (document.getElementById("tags")?.value || "").trim();

    const lines = [];
    lines.push(`Focus: ${focus}`);
    if (audience) lines.push(`Audience: ${audience}`);
    if (tone) lines.push(`Tone: ${tone}`);
    if (tags) lines.push(`Tags: ${tags}`);
    return lines.join("\n");
  }

  function getBuilderFocus() {
    return (document.getElementById("focus")?.value || "").trim();
  }

  function setBuilderStatus(html) {
    const el = document.getElementById("builder-status");
    if (el) el.innerHTML = html;
  }

  function showToast(message, variant) {
    const container = document.getElementById("toast-container");
    if (!container || !window.bootstrap || !window.bootstrap.Toast) return;

    const v = variant || "secondary";
    const el = document.createElement("div");
    el.className = `toast align-items-center text-bg-${v} border-0`;
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.setAttribute("aria-atomic", "true");
    el.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">${String(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    container.appendChild(el);

    const t = new window.bootstrap.Toast(el, { delay: 2500 });
    el.addEventListener("hidden.bs.toast", function () {
      try { el.remove(); } catch (_e) {}
    });
    t.show();
  }

  function initTooltips(scope) {
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    const root = scope || document;
    const els = root.querySelectorAll('[data-bs-toggle="tooltip"]');
    els.forEach(function (el) {
      // Idempotent: avoid double-init if called multiple times.
      if (el.dataset.hmTooltipInit === "1") return;
      try {
        // Allow per-element overrides via data attributes.
        new window.bootstrap.Tooltip(el);
        el.dataset.hmTooltipInit = "1";
      } catch (_e) {
        // no-op
      }
    });
  }

  function setButtonLoading(btn, loading, label) {
    if (!btn) return;
    if (!btn.dataset.hmLabel) {
      btn.dataset.hmLabel = btn.textContent || "";
    }

    if (loading) {
      btn.disabled = true;
      const txt = label || btn.dataset.hmLabel || "Loading";
      btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${txt}`;
    } else {
      btn.disabled = false;
      btn.textContent = btn.dataset.hmLabel;
    }
  }

  function setResultsVisible(hasResults) {
    const root = document.getElementById("builder-results");
    if (!root) return;
    const empty = document.getElementById("builder-results-empty");
    const body = document.getElementById("builder-results-body");
    if (empty) empty.classList.toggle("d-none", !!hasResults);
    if (body) body.classList.toggle("d-none", !hasResults);
  }

  function updateBlueskyCharCounter(text) {
    const counter = document.getElementById("bluesky-char-counter");
    const over = document.getElementById("bluesky-over-limit");
    if (!counter) return;

    const raw = String(text || "");
    const n = raw.length;
    const remaining = 300 - n;
    counter.textContent = `Characters: ${n} / 300 · Remaining: ${remaining}`;

    // Visual cue:
    // - normal under 260
    // - warning 260–300
    // - danger >300
    counter.classList.remove("text-muted", "text-warning", "text-danger");
    if (n > 300) {
      counter.classList.add("text-danger");
      if (over) over.style.display = "";
    } else if (n >= 260) {
      counter.classList.add("text-warning");
      if (over) over.style.display = "none";
    } else {
      counter.classList.add("text-muted");
      if (over) over.style.display = "none";
    }
  }

  function setBuilderBadgeState(state) {
    const ready = document.getElementById("builder-ready-indicator");
    const posted = document.getElementById("builder-posted-indicator");
    if (ready) ready.style.display = state === "ready" ? "" : "none";
    if (posted) posted.style.display = state === "posted" ? "" : "none";
  }

  function setVisible(id, visible) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = visible ? "" : "none";
  }

  function initMediaPreviewModal() {
    const modalEl = document.getElementById("hm-media-preview");
    if (!modalEl || !window.bootstrap || !window.bootstrap.Modal) return;

    const titleEl = document.getElementById("hm-media-preview-title");
    const bodyEl = document.getElementById("hm-media-preview-body");
    const metaEl = document.getElementById("hm-media-preview-meta");
    const openEl = document.getElementById("hm-media-preview-open");
    const prevEl = document.getElementById("hm-media-preview-prev");
    const nextEl = document.getElementById("hm-media-preview-next");

    const modal = new window.bootstrap.Modal(modalEl);

    let currentItems = [];
    let currentIndex = -1;

    function isModalShown() {
      return modalEl.classList.contains("show");
    }

    function extractItemsFromContext(btn) {
      const table = btn && btn.closest ? btn.closest("table") : null;
      const scope = table || document;
      const btns = Array.from(scope.querySelectorAll('[data-hm-preview="1"]'));
      return btns.map(function (b) {
        return {
          url: String(b.getAttribute("data-url") || ""),
          contentType: String(b.getAttribute("data-content-type") || "").toLowerCase(),
          name: String(b.getAttribute("data-name") || "")
        };
      }).filter(function (x) {
        return !!x.url;
      });
    }

    function setNavVisible(visible) {
      if (prevEl) prevEl.style.display = visible ? "" : "none";
      if (nextEl) nextEl.style.display = visible ? "" : "none";
    }

    function setNavEnabled(prevEnabled, nextEnabled) {
      if (prevEl) prevEl.disabled = !prevEnabled;
      if (nextEl) nextEl.disabled = !nextEnabled;
    }

    function renderItemAt(idx) {
      if (!bodyEl) {
        modal.show();
        return;
      }
      if (!currentItems || currentItems.length === 0) return;

      const safeIdx = Math.max(0, Math.min(idx, currentItems.length - 1));
      currentIndex = safeIdx;
      const item = currentItems[safeIdx];

      const url = item.url;
      const contentType = item.contentType;
      const name = item.name;

      if (titleEl) titleEl.textContent = name || "Media preview";

      const countText = currentItems.length > 1 ? ` · ${safeIdx + 1} / ${currentItems.length}` : "";
      if (metaEl) metaEl.textContent = (contentType ? contentType : "") + countText;

      if (openEl && url) {
        openEl.href = url;
        openEl.style.display = "";
      }

      bodyEl.innerHTML = "";
      if (contentType.startsWith("image/")) {
        const img = document.createElement("img");
        img.src = url;
        img.alt = name || "Image preview";
        img.className = "img-fluid rounded-3";
        img.style.maxHeight = "70vh";
        img.style.objectFit = "contain";
        bodyEl.appendChild(img);
      } else if (contentType.startsWith("video/")) {
        const vid = document.createElement("video");
        vid.src = url;
        vid.controls = true;
        vid.className = "w-100 rounded-3";
        vid.style.maxHeight = "70vh";
        bodyEl.appendChild(vid);
      } else {
        const div = document.createElement("div");
        div.className = "text-muted";
        div.textContent = "Preview not available for this file type.";
        bodyEl.appendChild(div);
      }

      const hasNav = currentItems.length > 1;
      setNavVisible(hasNav);
      setNavEnabled(safeIdx > 0, safeIdx < currentItems.length - 1);
    }

    function goPrev() {
      if (!currentItems || currentItems.length <= 1) return;
      if (currentIndex <= 0) return;
      renderItemAt(currentIndex - 1);
    }

    function goNext() {
      if (!currentItems || currentItems.length <= 1) return;
      if (currentIndex >= currentItems.length - 1) return;
      renderItemAt(currentIndex + 1);
    }

    function clear() {
      if (bodyEl) bodyEl.innerHTML = "";
      if (metaEl) metaEl.textContent = "";
      if (openEl) {
        openEl.href = "#";
        openEl.style.display = "none";
      }
      if (titleEl) titleEl.textContent = "Media preview";

      currentItems = [];
      currentIndex = -1;
      setNavVisible(false);
    }

    modalEl.addEventListener("hidden.bs.modal", function () {
      clear();
    });

    if (prevEl) {
      prevEl.addEventListener("click", function () {
        goPrev();
      });
    }
    if (nextEl) {
      nextEl.addEventListener("click", function () {
        goNext();
      });
    }

    document.addEventListener("keydown", function (e) {
      if (!isModalShown()) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goNext();
      }
    });

    document.addEventListener("click", function (e) {
      const btn = e.target && e.target.closest ? e.target.closest('[data-hm-preview="1"]') : null;
      if (!btn) return;
      e.preventDefault();

      currentItems = extractItemsFromContext(btn);

      const url = String(btn.getAttribute("data-url") || "");
      currentIndex = currentItems.findIndex(function (x) {
        return x.url === url;
      });
      if (currentIndex < 0) currentIndex = 0;

      renderItemAt(currentIndex);
      modal.show();
    });
  }

  async function copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_e) {
      return false;
    }
  }

  async function refreshProjectMediaTable(projectId) {
    const tbody = document.querySelector("#project-media-table tbody");
    if (!tbody) return;

    const resp = await fetch(`/api/projects/${projectId}/media`, { headers: { Accept: "application/json" } });
    const data = await resp.json();
    const items = data.items || [];

    tbody.innerHTML = "";

    if (items.length === 0) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="5" class="text-muted">No uploads yet.</td>';
      tbody.appendChild(tr);
      return;
    }

    for (const item of items) {
      const tr = document.createElement("tr");
      const type = item.content_type || "";
      tr.innerHTML = `
        <td>
          <input class="form-check-input media-check" type="checkbox" data-media-id="${item.id}" />
        </td>
        <td>${item.original_name}</td>
        <td class="text-muted">${type}</td>
        <td class="text-end">${formatBytes(item.size_bytes)}</td>
        <td class="text-end">
          <div class="btn-group btn-group-sm" role="group" aria-label="Media actions">
            <button
              type="button"
              class="btn btn-outline-secondary"
              data-hm-preview="1"
              data-url="${item.url}"
              data-content-type="${type}"
              data-name="${String(item.original_name || "")}"
            ><i class="bi bi-eye me-1" aria-hidden="true"></i>View</button>
            <button
              type="button"
              class="btn btn-outline-danger project-media-delete"
              data-project-id="${projectId}"
              data-media-id="${item.id}"
              data-name="${String(item.original_name || "")}"
            ><i class="bi bi-trash3 me-1" aria-hidden="true"></i>Delete</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    }

    // Delete buttons
    tbody.querySelectorAll(".project-media-delete").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const pid = parseInt(btn.getAttribute("data-project-id"), 10);
        const mid = parseInt(btn.getAttribute("data-media-id"), 10);
        const name = String(btn.getAttribute("data-name") || "this file");
        if (!pid || !mid) return;
        if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return;

        try {
          const resp = await fetch(`/api/projects/${pid}/media/${mid}`, { method: "DELETE", headers: { Accept: "application/json" } });
          if (!resp.ok) {
            const text = await resp.text();
            throw new Error(text || `Request failed (${resp.status})`);
          }
          showToast("Deleted", "success");
          refreshProjectMediaTable(pid).catch(function () {});
        } catch (err) {
          showToast("Delete failed", "danger");
        }
      });
    });
  }

  async function refreshProjectPlansList(projectId) {
    const list = document.getElementById("plans-list");
    if (!list) return;

    const resp = await fetch(`/api/projects/${projectId}/plans`, { headers: { Accept: "application/json" } });
    const data = await resp.json();
    const items = data.items || [];

    list.innerHTML = "";
    if (items.length === 0) {
      list.innerHTML = '<div class="list-group-item text-muted">No plans yet.</div>';
      return;
    }

    for (const p of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "list-group-item list-group-item-action";
      btn.setAttribute("data-plan-id", String(p.id));
      const modelLabel = p.is_template ? "Template Draft" : p.model;
      btn.innerHTML = `
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <div class="fw-semibold">${p.created_at}</div>
            <div class="text-muted small">${modelLabel}</div>
          </div>
          <div class="text-muted small">#${p.id}</div>
        </div>
      `;
      btn.addEventListener("click", function () {
        loadPlanDetail(projectId, p.id).catch(function () {});
      });
      list.appendChild(btn);
    }
  }

  async function loadPlanDetail(projectId, planId) {
    const pre = document.getElementById("plan-detail");
    if (!pre) return;
    pre.textContent = "Loading…";

    const resp = await fetch(`/api/projects/${projectId}/plans/${planId}`, { headers: { Accept: "application/json" } });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || `Request failed (${resp.status})`);
    }
    const data = await resp.json();
    pre.textContent = JSON.stringify(data, null, 2);
  }

  function getSelectedMediaIds() {
    const checks = document.querySelectorAll(".media-check");
    const ids = [];
    for (const el of checks) {
      if (el.checked) {
        ids.push(parseInt(el.getAttribute("data-media-id"), 10));
      }
    }
    return ids;
  }

  function initProjectSelectionButtons() {
    const btnAll = document.getElementById("select-all");
    const btnNone = document.getElementById("select-none");
    if (!btnAll || !btnNone) return;

    btnAll.addEventListener("click", function () {
      document.querySelectorAll(".media-check").forEach(function (el) {
        el.checked = true;
      });
    });

    btnNone.addEventListener("click", function () {
      document.querySelectorAll(".media-check").forEach(function (el) {
        el.checked = false;
      });
    });
  }

  function initProjectDropzone(projectId) {
    Dropzone.autoDiscover = false;

    const el = document.getElementById("project-upload-dropzone");
    if (!el) return;

    const dz = new Dropzone(el, {
      url: `/api/projects/${projectId}/upload`,
      maxFilesize: 512, // MB
      timeout: 10 * 60 * 1000,
      parallelUploads: 2,
      addRemoveLinks: false
    });

    dz.on("success", function () {
      refreshProjectMediaTable(projectId).catch(function () {});
    });

    dz.on("error", function (_file, message) {
      const status = document.getElementById("project-generate-status");
      if (status) status.innerHTML = `<div class="text-danger">Upload error: ${String(message)}</div>`;
    });
  }

  async function generateProjectPlans(projectId) {
    const status = document.getElementById("project-generate-status");
    const btn = document.getElementById("project-generate-btn");
    const intentOverride = document.getElementById("project-intent").value;
    const selectedMediaIds = getSelectedMediaIds();
    const modelSelect = document.getElementById("ai-model");
    const selectedModel = modelSelect ? modelSelect.value : null;

    status.innerHTML = '<div class="text-muted">Generating…</div>';
    btn.disabled = true;

    try {
      const resp = await fetch(`/api/projects/${projectId}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        // Backend already accepts `model`; keep request structure unchanged beyond adding it.
        body: JSON.stringify({ intent_text: intentOverride, selected_media_ids: selectedMediaIds, model: selectedModel })
      });

      const data = await resp.json().catch(function () {
        return null;
      });

      if (!resp.ok) {
        if (data && data.ok === false && data.error && data.error.human_message) {
          status.innerHTML = `<div class="text-danger">${data.error.human_message}</div>`;
          return;
        }
        const text = data ? JSON.stringify(data) : await resp.text();
        throw new Error(text || `Request failed (${resp.status})`);
      }

      if (data && data.ok === false && data.error && data.error.human_message) {
        status.innerHTML = `<div class="text-danger">${data.error.human_message}</div>`;
        return;
      }

      document.getElementById("project-result").textContent = JSON.stringify(data, null, 2);
      status.innerHTML = '<div class="text-success">Done.</div>';
      refreshProjectPlansList(projectId).catch(function () {});
    } catch (err) {
      status.innerHTML = `<div class="text-danger">Error: ${String(err.message || err)}</div>`;
    } finally {
      btn.disabled = false;
    }
  }

  function initPostBuilder() {
    const root = document.getElementById("builder-root");
    if (!root) return;

    let projectId = null;
    let projectPromise = null;
    const selectedMediaIds = new Set();
    // Keep a tiny index of media content types so we can do platform gating.
    const mediaTypeById = {};

    // Most recent successful generation payload from /generate.
    let lastPlan = null;

    function addAudienceSuggestion(suggestionRaw) {
      const input = document.getElementById("audience");
      if (!input) return;

      const suggestion = String(suggestionRaw || "").trim();
      if (!suggestion) return;

      const current = String(input.value || "").trim();
      if (!current) {
        input.value = suggestion;
        return;
      }

      const parts = current
        .split(",")
        .map(function (p) { return p.trim(); })
        .filter(Boolean);

      const lower = parts.map(function (p) { return p.toLowerCase(); });
      if (lower.includes(suggestion.toLowerCase())) return;

      parts.push(suggestion);
      input.value = parts.join(", ");
    }

    function addTagSuggestion(suggestionRaw) {
      const input = document.getElementById("tags");
      if (!input) return;

      const suggestion = String(suggestionRaw || "").trim();
      if (!suggestion) return;

      const current = String(input.value || "").trim();
      if (!current) {
        input.value = suggestion;
        return;
      }

      const parts = current
        .split(",")
        .map(function (p) { return p.trim(); })
        .filter(Boolean);

      const lower = parts.map(function (p) { return p.toLowerCase(); });
      if (lower.includes(suggestion.toLowerCase())) return;

      parts.push(suggestion);
      input.value = parts.join(", ");
    }

    function setToneSuggestion(toneRaw) {
      const sel = document.getElementById("tone");
      if (!sel) return;
      const tone = String(toneRaw || "").trim();
      if (!tone) return;

      // Ensure option exists (in case the suggestion list includes custom tones).
      let found = false;
      for (const opt of sel.options) {
        if (String(opt.value) === tone) {
          found = true;
          break;
        }
      }
      if (!found) {
        const opt = document.createElement("option");
        opt.value = tone;
        opt.textContent = tone;
        sel.appendChild(opt);
      }
      sel.value = tone;
    }

    function setCtaValidationState(isValid, message) {
      const ctaInput = document.getElementById("builder-cta-target");
      if (!ctaInput) return;

      const msgEl = document.getElementById("builder-cta-invalid");
      if (msgEl && message) msgEl.textContent = String(message);

      if (isValid) {
        ctaInput.classList.remove("is-invalid");
      } else {
        ctaInput.classList.add("is-invalid");
      }
    }

    function normalizeCtaTarget(raw) {
      const v = String(raw || "").trim();
      if (!v) return "";
      if (v.startsWith("@")) return v;
      if (/^https?:\/\//i.test(v)) return v;
      // If it looks like a bare domain (no spaces, has a dot), assume https.
      if (!/\s/.test(v) && v.includes(".")) return `https://${v}`;
      return v;
    }

    function validateCtaTargetFormat(raw) {
      const v = String(raw || "").trim();
      if (!v) return { ok: true, normalized: "" };

      const normalized = normalizeCtaTarget(v);

      if (normalized.startsWith("@")) {
        if (normalized.length < 2) return { ok: false, normalized, message: "Handle looks incomplete (try @name)." };
        if (/\s/.test(normalized)) return { ok: false, normalized, message: "Handles can’t contain spaces." };
        return { ok: true, normalized };
      }

      try {
        const u = new URL(normalized);
        const proto = String(u.protocol || "").toLowerCase();
        if (proto !== "http:" && proto !== "https:") {
          return { ok: false, normalized, message: "URL must start with http:// or https://" };
        }
        if (!u.hostname) {
          return { ok: false, normalized, message: "URL looks incomplete." };
        }
        return { ok: true, normalized };
      } catch (_e) {
        return { ok: false, normalized, message: "Enter an @handle or a full URL (https://…)." };
      }
    }

    function validateCtaOrShowError() {
      const ctaCheck = document.getElementById("builder-include-cta");
      const ctaInput = document.getElementById("builder-cta-target");
      if (!ctaCheck || !ctaInput) return true;

      const include = !!ctaCheck.checked;
      const vRaw = String(ctaInput.value || "").trim();

      if (include && !vRaw) {
        setCtaValidationState(false, "CTA is enabled — please enter a link or handle.");
        ctaInput.focus();
        setBuilderStatus('<div class="text-danger">CTA is enabled — please enter a link or handle.</div>');
        showToast("CTA needs a link/handle", "warning");
        return false;
      }

      // Validate format whenever there is a value, even if the checkbox is off.
      if (vRaw) {
        const res = validateCtaTargetFormat(vRaw);
        if (res.normalized && res.normalized !== vRaw) {
          ctaInput.value = res.normalized;
        }
        if (!res.ok) {
          setCtaValidationState(false, res.message || "Enter an @handle or a full URL (https://…)." );
          ctaInput.focus();
          setBuilderStatus(`<div class="text-danger">CTA target is invalid: ${String(res.message || "Enter an @handle or a full URL (https://…).")}</div>`);
          showToast("CTA target is invalid", "warning");
          return false;
        }
      }

      setCtaValidationState(true);
      return true;
    }

    root.addEventListener("click", function (e) {
      const btn = (e.target && e.target.closest) ? e.target.closest("[data-hm-audience-suggestion]") : null;
      if (!btn) return;
      e.preventDefault();
      addAudienceSuggestion(btn.getAttribute("data-hm-audience-suggestion"));
      const input = document.getElementById("audience");
      if (input) input.focus();
    });

    root.addEventListener("click", function (e) {
      const btn = (e.target && e.target.closest) ? e.target.closest("[data-hm-tag-suggestion]") : null;
      if (!btn) return;
      e.preventDefault();
      addTagSuggestion(btn.getAttribute("data-hm-tag-suggestion"));
      const input = document.getElementById("tags");
      if (input) input.focus();
    });

    root.addEventListener("click", function (e) {
      const btn = (e.target && e.target.closest) ? e.target.closest("[data-hm-tone-suggestion]") : null;
      if (!btn) return;
      e.preventDefault();
      setToneSuggestion(btn.getAttribute("data-hm-tone-suggestion"));
    });

    function updateBuilderPlatformAvailability() {
      const btnBoth = document.getElementById("gen-both");
      const note = document.getElementById("builder-youtube-note");
      if (!btnBoth) return;

      const platform = (document.querySelector('input[name="builder-platform"]:checked') || {}).value || "bluesky";
      const cardYouTube = document.getElementById("card-youtube");

      // Bluesky-first: only show YouTube UI if the user explicitly selected "Both".
      if (platform !== "both") {
        btnBoth.style.display = "none";
        if (note) note.style.display = "none";
        if (cardYouTube) cardYouTube.style.display = "none";
      } else {
        btnBoth.style.display = "";
      }

      let hasSelectedVideo = false;
      selectedMediaIds.forEach(function (id) {
        const ct = String(mediaTypeById[id] || "");
        if (ct.toLowerCase().startsWith("video/")) {
          hasSelectedVideo = true;
        }
      });

      // YouTube requires a selected video (for now).
      btnBoth.disabled = (platform === "both") ? !hasSelectedVideo : false;
      if (note) note.style.display = (platform === "both" && !hasSelectedVideo) ? "" : "none";

      // Bluesky posting (images only): enable if we have a plan+project and selected media is 1-4 images.
      const postBtn = document.getElementById("builder-bsky-post-btn");
      const limitNote = document.getElementById("builder-bsky-limit");
      if (postBtn) {
        let selectedCount = 0;
        let allSelectedAreImages = true;
        selectedMediaIds.forEach(function (id) {
          const ct = String(mediaTypeById[id] || "").toLowerCase();
          if (!ct.startsWith("image/")) {
            allSelectedAreImages = false;
            return;
          }
          if (ct === "image/gif") {
            allSelectedAreImages = false;
            return;
          }
          selectedCount += 1;
        });

        const hasProject = !!projectId;
        const hasPlanText = !!(lastPlan && lastPlan.bluesky && lastPlan.bluesky.text);

        const tooMany = selectedCount > 4;
        if (limitNote) limitNote.style.display = tooMany ? "" : "none";

        const okImages = selectedCount >= 1 && selectedCount <= 4 && allSelectedAreImages;
        postBtn.disabled = !(hasProject && hasPlanText && okImages) || tooMany;
      }
    }

    async function ensureProject() {
      if (projectId) return projectId;

      // If a creation request is already in-flight (e.g. multiple files added quickly),
      // wait for it instead of creating duplicate projects.
      if (projectPromise) return await projectPromise;

      const focus = getBuilderFocus();
      const title = focus || "Untitled Project";
      let intentText = buildIntentFromBuilderInputs();
      if (!focus) {
        // Keep server-side requirement satisfied while allowing upload-first flow.
        intentText = "Focus: (TBD)";
      }

      projectPromise = (async function () {
        setBuilderStatus('<div class="text-muted">Creating project…</div>');
        const resp = await fetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ title: title, intent_text: intentText })
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `Request failed (${resp.status})`);
        }
        const data = await resp.json();
        projectId = data.project.id;
        try {
          window.localStorage.setItem("hm_builder_project_id", String(projectId));
        } catch (_e) {}
        setBuilderStatus('');
        return projectId;
      })();

      try {
        return await projectPromise;
      } finally {
        projectPromise = null;
      }
    }

    function getSelectedIdsFromTable() {
      const checks = document.querySelectorAll(".builder-media-check");
      const ids = [];
      for (const el of checks) {
        if (el.checked) ids.push(parseInt(el.getAttribute("data-media-id"), 10));
      }
      return ids;
    }

    async function refreshBuilderMedia() {
      const tbody = document.querySelector("#builder-media-table tbody");
      if (!tbody) return;

      if (!projectId) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-muted">No uploads yet.</td></tr>';
        return;
      }

      const resp = await fetch(`/api/projects/${projectId}/media`, { headers: { Accept: "application/json" } });
      if (!resp.ok) {
        // If the project was deleted or the stored id is stale, reset.
        if (resp.status === 404) {
          projectId = null;
          try { window.localStorage.removeItem("hm_builder_project_id"); } catch (_e) {}
          tbody.innerHTML = '<tr><td colspan="5" class="text-muted">No uploads yet.</td></tr>';
          return;
        }
        const text = await resp.text();
        throw new Error(text || `Request failed (${resp.status})`);
      }
      const data = await resp.json();
      const items = data.items || [];

      tbody.innerHTML = "";

      if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-muted">No uploads yet.</td></tr>';
        return;
      }

      // Default behavior: all media selected. For newly uploaded items, auto-select.
      for (const item of items) {
        if (!selectedMediaIds.has(item.id)) {
          selectedMediaIds.add(item.id);
        }
      }

      for (const item of items) {
        const tr = document.createElement("tr");
        const type = item.content_type || "";
        // Persist content-type for platform gating.
        mediaTypeById[item.id] = type;
        const checked = selectedMediaIds.has(item.id) ? "checked" : "";
        tr.innerHTML = `
          <td>
            <input class="form-check-input builder-media-check" type="checkbox" data-media-id="${item.id}" ${checked} />
          </td>
          <td>${item.original_name}</td>
          <td class="text-muted">${type}</td>
          <td class="text-end">${formatBytes(item.size_bytes)}</td>
          <td class="text-end">
            <div class="btn-group btn-group-sm" role="group" aria-label="Media actions">
              <button
                type="button"
                class="btn btn-outline-secondary"
                data-hm-preview="1"
                data-url="${item.url}"
                data-content-type="${type}"
                data-name="${String(item.original_name || "")}"
              ><i class="bi bi-eye me-1" aria-hidden="true"></i>View</button>
              <button
                type="button"
                class="btn btn-outline-danger builder-media-delete"
                data-media-id="${item.id}"
                data-name="${String(item.original_name || "")}"
              ><i class="bi bi-trash3 me-1" aria-hidden="true"></i>Delete</button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      }

      document.querySelectorAll(".builder-media-check").forEach(function (el) {
        el.addEventListener("change", function () {
          const id = parseInt(el.getAttribute("data-media-id"), 10);
          if (el.checked) selectedMediaIds.add(id);
          else selectedMediaIds.delete(id);
          updateBuilderPlatformAvailability();
        });
      });

      tbody.querySelectorAll(".builder-media-delete").forEach(function (btn) {
        btn.addEventListener("click", async function () {
          const mid = parseInt(btn.getAttribute("data-media-id"), 10);
          const name = String(btn.getAttribute("data-name") || "this file");
          if (!projectId || !mid) return;
          if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return;

          try {
            const resp = await fetch(`/api/projects/${projectId}/media/${mid}`, { method: "DELETE", headers: { Accept: "application/json" } });
            if (!resp.ok) {
              const text = await resp.text();
              throw new Error(text || `Request failed (${resp.status})`);
            }

            selectedMediaIds.delete(mid);
            try { delete mediaTypeById[mid]; } catch (_e) {}
            showToast("Deleted", "success");
            refreshBuilderMedia().catch(function () {});
          } catch (_e) {
            showToast("Delete failed", "danger");
          }
        });
      });

      updateBuilderPlatformAvailability();
    }

    function renderPlanToCards(plan) {
      lastPlan = plan;
      setVisible("builder-results", true);
      setResultsVisible(true);
      setBuilderBadgeState("ready");

      // Template indicator
      const templateIndicator = document.getElementById("builder-template-indicator");
      const isTemplate = !!(plan && plan.meta && plan.meta.is_template);
      if (templateIndicator) templateIndicator.style.display = isTemplate ? "" : "none";

      // Bluesky
      const bluesky = plan.bluesky || null;
      const cardBluesky = document.getElementById("card-bluesky");
      if (cardBluesky) cardBluesky.style.display = bluesky ? "" : "none";
      document.getElementById("bluesky-post").textContent = bluesky ? (bluesky.text || "") : "";
      updateBlueskyCharCounter(bluesky ? (bluesky.text || "") : "");

      const altBox = document.getElementById("bluesky-alt");
      if (bluesky && Array.isArray(bluesky.alt_text) && bluesky.alt_text.length > 0) {
        // Render as a simple numbered list.
        const lines = bluesky.alt_text.map(function (t, i) {
          return `${i + 1}. ${t}`;
        });
        altBox.textContent = lines.join("\n");
      } else {
        altBox.textContent = "(none)";
      }

      // YouTube
      const youtube = plan.youtube || null;
      const cardYouTube = document.getElementById("card-youtube");
      if (cardYouTube) cardYouTube.style.display = youtube ? "" : "none";

      const tags = (youtube && Array.isArray(youtube.tags)) ? youtube.tags.join(", ") : (youtube && youtube.tags ? youtube.tags : "");
      document.getElementById("youtube-title").textContent = youtube ? (youtube.title || "") : "";
      document.getElementById("youtube-desc").textContent = youtube ? (youtube.description || "") : "";
      document.getElementById("youtube-tags").textContent = youtube ? tags : "";
      document.getElementById("youtube-category").textContent = youtube ? (youtube.category ? youtube.category : "(none)") : "";

      // Advanced
      document.getElementById("builder-json").textContent = JSON.stringify(plan, null, 2);

      // Copy buttons
      document.getElementById("copy-bluesky").onclick = async function () {
        const ok = await copyToClipboard(bluesky ? (bluesky.text || "") : "");
        showToast(ok ? "Copied to clipboard" : "Copy failed", ok ? "success" : "danger");
      };
      document.getElementById("copy-youtube-title").onclick = async function () {
        const ok = await copyToClipboard(youtube ? (youtube.title || "") : "");
        showToast(ok ? "Copied to clipboard" : "Copy failed", ok ? "success" : "danger");
      };
      document.getElementById("copy-youtube-desc").onclick = async function () {
        const ok = await copyToClipboard(youtube ? (youtube.description || "") : "");
        showToast(ok ? "Copied to clipboard" : "Copy failed", ok ? "success" : "danger");
      };
      document.getElementById("copy-youtube-tags").onclick = async function () {
        const ok = await copyToClipboard(youtube ? (tags || "") : "");
        showToast(ok ? "Copied to clipboard" : "Copy failed", ok ? "success" : "danger");
      };
    }

    async function postToBluesky() {
      const statusEl = document.getElementById("builder-bsky-post-status");
      const btn = document.getElementById("builder-bsky-post-btn");
      if (!btn) return;

      const identifier = String(document.getElementById("builder-bsky-identifier")?.value || "").trim();
      const appPassword = String(document.getElementById("builder-bsky-app-password")?.value || "").trim();
      if (!identifier || !appPassword) {
        if (statusEl) statusEl.innerHTML = '<div class="alert alert-warning mb-0">Enter your handle and app password.</div>';
        return;
      }

      if (!projectId || !lastPlan || !lastPlan.bluesky || !lastPlan.bluesky.text) {
        if (statusEl) statusEl.innerHTML = '<div class="alert alert-warning mb-0">Generate a Bluesky plan first.</div>';
        return;
      }

      // Selected media must be 1-4 images (no GIF).
      const selectedIds = getSelectedIdsFromTable();
      const imageIds = [];
      for (const id of selectedIds) {
        const ct = String(mediaTypeById[id] || "").toLowerCase();
        if (!ct.startsWith("image/") || ct === "image/gif") {
          if (statusEl) statusEl.innerHTML = '<div class="alert alert-warning mb-0">Only images are supported for Bluesky posting (no video/GIF yet).</div>';
          return;
        }
        imageIds.push(id);
      }
      if (imageIds.length === 0) {
        if (statusEl) statusEl.innerHTML = '<div class="alert alert-warning mb-0">Select at least one image.</div>';
        return;
      }
      if (imageIds.length > 4) {
        if (statusEl) statusEl.innerHTML = '<div class="alert alert-warning mb-0">Bluesky supports up to 4 images per post.</div>';
        return;
      }

      // Alt text is optional; only send it if the selection matches the plan's selection (so alignment is safe).
      let altText = null;
      try {
        const planSelected = Array.isArray(lastPlan.selected_media_ids) ? lastPlan.selected_media_ids : [];
        const sameSelection = planSelected.length === imageIds.length && planSelected.every(function (v, i) { return v === imageIds[i]; });
        if (sameSelection && lastPlan.bluesky && Array.isArray(lastPlan.bluesky.alt_text)) {
          altText = lastPlan.bluesky.alt_text;
        }
      } catch (_e) {
        altText = null;
      }

      setButtonLoading(btn, true, "Posting…");
      if (statusEl) statusEl.innerHTML = '<div class="alert alert-info mb-0">Posting…</div>';

      try {
        const payload = {
          identifier: identifier,
          app_password: appPassword,
          text: String(lastPlan.bluesky.text || ""),
          selected_media_ids: imageIds
        };
        if (altText) payload.alt_text = altText;

        const resp = await fetch(`/api/projects/${projectId}/bluesky_post`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await resp.json().catch(function () { return null; });
        if (!resp.ok) {
          const msg = (data && data.error && typeof data.error === "object" && data.error.human_message)
            ? String(data.error.human_message)
            : ((data && data.error) ? String(data.error) : (data && data.message ? String(data.message) : `Request failed (${resp.status})`));
          if (statusEl) statusEl.innerHTML = `<div class="alert alert-danger mb-0">${msg}</div>`;
          showToast("Post failed", "danger");
          return;
        }

        if (data && data.ok) {
          const uri = data.uri || "";
          // Public URL format is not guaranteed; show uri/cid and link to bsky.app search if possible.
          const link = uri ? `<a href="https://bsky.app/" target="_blank" rel="noreferrer">View on Bluesky</a>` : "";
          let optNote = "";
          if (data.optimization && data.optimization.compressed_images) {
            optNote = `<div class="small text-muted">Compressed ${data.optimization.compressed_images} image(s) to fit Bluesky’s 1MB limit.</div>`;
          }
          if (statusEl) statusEl.innerHTML = `<div class="alert alert-success mb-0">Posted successfully. ${link}${optNote}<div class="small text-muted">uri: ${uri} cid: ${data.cid || ""}</div></div>`;
          showToast("Posted successfully", "success");
          setBuilderBadgeState("posted");
        } else {
          const msg = (data && data.error && typeof data.error === "object" && data.error.human_message)
            ? String(data.error.human_message)
            : ((data && data.error) ? String(data.error) : "Posting failed.");
          if (statusEl) statusEl.innerHTML = `<div class="alert alert-danger mb-0">${msg}</div>`;
          showToast("Post failed", "danger");
        }
      } catch (err) {
        if (statusEl) statusEl.innerHTML = `<div class="alert alert-danger mb-0">Error: ${String(err.message || err)}</div>`;
        showToast("Post failed", "danger");
      } finally {
        setButtonLoading(btn, false);
        updateBuilderPlatformAvailability();
      }
    }

    async function generate(which) {
      const focus = getBuilderFocus();
      if (!focus) {
        setBuilderStatus('<div class="text-danger">Please fill the focus field first.</div>');
        return;
      }

      if (!validateCtaOrShowError()) return;

      try {
        const genBtn = (which === "both") ? document.getElementById("gen-both") : document.getElementById("gen-bluesky");
        setButtonLoading(genBtn, true, "Generating…");
        const pid = await ensureProject();
        const ids = getSelectedIdsFromTable();
        if (ids.length === 0) {
          setBuilderStatus('<div class="text-danger">Select at least one uploaded file.</div>');
          return;
        }

        // Guardrail: even if the user triggers generation via keyboard/etc, enforce YouTube gating.
        if (which === "youtube" || which === "both") {
          let hasSelectedVideo = false;
          selectedMediaIds.forEach(function (id) {
            const ct = String(mediaTypeById[id] || "");
            if (ct.toLowerCase().startsWith("video/")) hasSelectedVideo = true;
          });
          if (!hasSelectedVideo) {
            setBuilderStatus('<div class="text-warning">YouTube generation requires a video (for now).</div>');
            return;
          }
        }

        setBuilderStatus('<div class="text-muted">Generating…</div>');
        const templateMode = !!document.getElementById("builder-template-mode")?.checked;
        const addEmojis = !!document.getElementById("builder-add-emojis")?.checked;
        let includeCta = !!document.getElementById("builder-include-cta")?.checked;
        const ctaTargetRaw = document.getElementById("builder-cta-target")?.value || "";
        const ctaTarget = String(ctaTargetRaw).trim();
        if (ctaTarget) includeCta = true;

        const targets = (which === "bluesky") ? ["bluesky"] : ((which === "youtube") ? ["youtube"] : ["bluesky", "youtube"]);
        const resp = await fetch(`/api/projects/${pid}/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            intent_text: buildIntentFromBuilderInputs(),
            selected_media_ids: ids,
            generate_targets: targets,
            template_mode: templateMode,
            add_emojis: addEmojis,
            include_cta: includeCta,
            cta_target: ctaTarget
          })
        });

        let payload = null;
        try {
          payload = await resp.json();
        } catch (_e) {
          payload = null;
        }

        if (!resp.ok) {
          // If backend returns structured error, show the human message.
          if (payload && payload.ok === false && payload.error && payload.error.human_message) {
            setBuilderStatus(`<div class="text-danger">${payload.error.human_message}</div>`);
            return;
          }
          const text = payload ? JSON.stringify(payload) : await resp.text();
          throw new Error(text || `Request failed (${resp.status})`);
        }

        if (payload && payload.ok === false && payload.error && payload.error.human_message) {
          setBuilderStatus(`<div class="text-danger">${payload.error.human_message}</div>`);
          return;
        }

        renderPlanToCards(payload);
        updateBuilderPlatformAvailability();

        setBuilderStatus('<div class="text-success">Done.</div>');
        showToast("Draft ready", "success");
      } catch (err) {
        setBuilderStatus(`<div class="text-danger">Error: ${String(err.message || err)}</div>`);
        showToast("Generation failed", "danger");
      } finally {
        const genBtn = (which === "both") ? document.getElementById("gen-both") : document.getElementById("gen-bluesky");
        setButtonLoading(genBtn, false);
      }
    }

    // Dropzone setup (project is created on first upload attempt).
    Dropzone.autoDiscover = false;
    const dzEl = document.getElementById("builder-dropzone");
    const dz = new Dropzone(dzEl, {
      url: "/api/upload", // placeholder; will be replaced after project creation
      autoProcessQueue: false,
      maxFilesize: 512,
      timeout: 10 * 60 * 1000,
      parallelUploads: 2,
      addRemoveLinks: false
    });

    dz.on("addedfile", async function () {
      try {
        const pid = await ensureProject();
        dz.options.url = `/api/projects/${pid}/upload`;
        // Flush any queued files immediately once the project exists.
        if (dz.getQueuedFiles().length > 0 && dz.getUploadingFiles().length === 0) {
          dz.processQueue();
        }
        refreshBuilderMedia().catch(function () {});
        updateBuilderPlatformAvailability();
      } catch (_e) {
        setBuilderStatus('<div class="text-danger">Could not start upload. Please try again.</div>');
        showToast("Upload could not start", "danger");
      }
    });

    dz.on("success", function () {
      refreshBuilderMedia().catch(function () {});
    });

    dz.on("error", function (_file, message) {
      setBuilderStatus(`<div class="text-danger">Upload error: ${String(message)}</div>`);
    });

    // CTA input: keep it editable; if the user types a link/handle, treat that as
    // explicit intent to include a CTA even if they forgot the checkbox.
    const ctaCheck = document.getElementById("builder-include-cta");
    const ctaInput = document.getElementById("builder-cta-target");
    if (ctaCheck && ctaInput) {
      ctaInput.disabled = false;
      ctaInput.addEventListener("input", function () {
        const v = String(ctaInput.value || "").trim();
        if (v) ctaCheck.checked = true;
        if (v) {
          const res = validateCtaTargetFormat(v);
          if (res.ok) setCtaValidationState(true);
        } else {
          setCtaValidationState(true);
        }
      });

      // Toggle required UI state when CTA is enabled.
      const sync = function () {
        ctaInput.required = !!ctaCheck.checked;
        if (!ctaCheck.checked) setCtaValidationState(true);
      };
      ctaCheck.addEventListener("change", function () {
        sync();
        // If turned on, validate immediately so it’s obvious what’s missing.
        if (ctaCheck.checked) validateCtaOrShowError();
      });
      sync();
    }

    document.getElementById("builder-select-all").addEventListener("click", function () {
      document.querySelectorAll(".builder-media-check").forEach(function (el) {
        el.checked = true;
        selectedMediaIds.add(parseInt(el.getAttribute("data-media-id"), 10));
      });
      updateBuilderPlatformAvailability();
    });
    document.getElementById("builder-select-none").addEventListener("click", function () {
      document.querySelectorAll(".builder-media-check").forEach(function (el) {
        el.checked = false;
        selectedMediaIds.delete(parseInt(el.getAttribute("data-media-id"), 10));
      });
      updateBuilderPlatformAvailability();
    });

    document.getElementById("gen-bluesky").addEventListener("click", function () {
      generate("bluesky");
    });
    document.getElementById("gen-both").addEventListener("click", function () {
      generate("both");
    });

    // Platform selector affects which buttons/cards are visible.
    document.querySelectorAll('input[name="builder-platform"]').forEach(function (el) {
      el.addEventListener("change", function () {
        updateBuilderPlatformAvailability();
      });
    });

    // Initial state for platform-scoped UI.
    updateBuilderPlatformAvailability();

    // Results: show empty-state until first generation.
    setVisible("builder-results", true);
    setResultsVisible(false);
    setBuilderBadgeState("none");
    updateBlueskyCharCounter("");

    // Initial state
    try {
      const stored = window.localStorage.getItem("hm_builder_project_id");
      if (stored) {
        const pid = parseInt(stored, 10);
        if (!Number.isNaN(pid) && pid > 0) {
          projectId = pid;
        }
      }
    } catch (_e) {}

    refreshBuilderMedia().catch(function () {});

    const postBtn = document.getElementById("builder-bsky-post-btn");
    if (postBtn) {
      postBtn.addEventListener("click", function () {
        postToBluesky();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initMediaPreviewModal();

    initTooltips();

    // Post Builder (landing)
    initPostBuilder();

    // Projects list page
    loadProjectsIntoList().catch(function () {});

    // Project page
    const root = document.getElementById("project-root");
    if (root) {
      const projectId = parseInt(root.getAttribute("data-project-id"), 10);
      initProjectDropzone(projectId);
      initProjectSelectionButtons();
      refreshProjectMediaTable(projectId).catch(function () {});
      refreshProjectPlansList(projectId).catch(function () {});

      const btn = document.getElementById("project-generate-btn");
      btn.addEventListener("click", function () {
        generateProjectPlans(projectId);
      });
    }
  });
})();
