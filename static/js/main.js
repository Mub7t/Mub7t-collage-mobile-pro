/**
 * main.js  v5
 * ───────────
 * Upload page     : drag-drop, single image preview, loading state
 * Review page     : dynamic task table, add/delete/validate, POST to /report-preview
 * Report preview  : copies inline-styled HTML (Outlook-compatible) to clipboard
 * Combine photos  : multi-file accumulator, 1-30 photos, thumbnails, form submit
 */

"use strict";

/* ═══════════════════════════════════════════════════════════════
   UPLOAD PAGE (single image)
   ═══════════════════════════════════════════════════════════════ */
(function initUploadPage() {
  const dropZone    = document.getElementById("drop-zone");
  const fileInput   = document.getElementById("image-input");
  const dropPrompt  = document.getElementById("drop-prompt");
  const previewWrap = document.getElementById("image-preview");
  const previewImg  = document.getElementById("preview-img");
  const removeBtn   = document.getElementById("remove-img");
  const extractBtn  = document.getElementById("extract-btn");
  const uploadForm  = document.getElementById("upload-form");
  const loadingOv   = document.getElementById("loading-overlay");

  if (!dropZone || !fileInput) return;  // not on this page

  // Drag events
  ["dragenter", "dragover"].forEach(e =>
    dropZone.addEventListener(e, ev => { ev.preventDefault(); dropZone.classList.add("drag-over"); })
  );
  ["dragleave", "drop"].forEach(e =>
    dropZone.addEventListener(e, () => dropZone.classList.remove("drag-over"))
  );
  dropZone.addEventListener("drop", ev => {
    ev.preventDefault();
    const file = ev.dataTransfer.files[0];
    if (file) applyFile(file);
  });

  // Click-to-browse
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) applyFile(fileInput.files[0]);
  });

  if (removeBtn) {
    removeBtn.addEventListener("click", e => { e.stopPropagation(); clearPreview(); });
  }

  if (uploadForm) {
    uploadForm.addEventListener("submit", () => {
      if (loadingOv) loadingOv.style.display = "flex";
    });
  }

  function applyFile(file) {
    const allowed = ["image/png", "image/jpeg", "image/jpg"];
    if (!allowed.includes(file.type)) {
      alert("Please upload a PNG, JPG, or JPEG image.");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      alert("File is too large. Maximum 50 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = ev => {
      previewImg.src            = ev.target.result;
      dropPrompt.style.display  = "none";
      previewWrap.style.display = "block";
      if (extractBtn) extractBtn.disabled = false;
    };
    reader.readAsDataURL(file);

    // Assign file to input so the form sends it
    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
    } catch (_) {
      // DataTransfer not supported — the drop case won't work, but
      // click-to-browse still uses the native input.files
    }
  }

  function clearPreview() {
    previewImg.src            = "";
    previewWrap.style.display = "none";
    dropPrompt.style.display  = "flex";
    if (extractBtn) extractBtn.disabled = true;
    fileInput.value = "";
  }
})();


/* ═══════════════════════════════════════════════════════════════
   REVIEW PAGE
   ═══════════════════════════════════════════════════════════════ */
(function initReviewPage() {
  const tbody      = document.getElementById("task-tbody");
  const addRowBtn  = document.getElementById("add-row-btn");
  const genBtn     = document.getElementById("generate-btn");
  const loadingOv  = document.getElementById("loading-overlay");
  const valBanner  = document.getElementById("validation-banner");
  const valList    = document.getElementById("validation-errors");
  const reportForm = document.getElementById("report-form");

  if (!tbody) return;  // not on this page

  let tasks  = (window.INITIAL_TASKS || []).map((t, i) => ({ ...t, _id: i }));
  let nextId = tasks.length;

  renderAllRows();

  addRowBtn.addEventListener("click", () => {
    const t = { ...emptyTask(), _id: nextId++ };
    tasks.push(t);
    appendRow(t);
    renumber();
  });

  genBtn.addEventListener("click", () => {
    collectData();
    const errors = validate();
    if (errors.length) {
      showErrors(errors);
      return;
    }
    hideErrors();
    submitPreview();
  });

  // ── Render ────────────────────────────────────────────────────
  function renderAllRows() {
    tbody.innerHTML = "";
    tasks.forEach(t => appendRow(t));
  }

  function appendRow(task) {
    const tr      = document.createElement("tr");
    tr.dataset.id = task._id;
    tr.innerHTML  = rowHTML(task);
    tbody.appendChild(tr);

    tr.querySelectorAll("textarea").forEach(ta => {
      ta.addEventListener("input", () => autoGrow(ta));
      autoGrow(ta);
    });

    const sel = tr.querySelector(".status-select");
    if (sel) {
      updateStatusColor(sel);
      sel.addEventListener("change", () => updateStatusColor(sel));
    }

    tr.querySelector(".del-row-btn").addEventListener("click", () => {
      tasks = tasks.filter(t => t._id !== Number(tr.dataset.id));
      tr.remove();
      renumber();
    });
  }

  function rowHTML(task) {
    const opts = ["Solved", "Pending"]
      .map(s => `<option value="${s}"${task.current_status === s ? " selected" : ""}>${s}</option>`)
      .join("");
    return `
      <td class="col-num">
        <div class="row-num-cell row-num-display">${task.row_num || ""}</div>
      </td>
      <td class="col-task">
        <input type="text" value="${esc(task.task)}"
               placeholder="Field Service" data-field="task" />
      </td>
      <td class="col-site">
        <input type="text" value="${esc(task.site_id)}"
               placeholder="Site ID" data-field="site_id" />
      </td>
      <td class="col-approach">
        <input type="text" value="${esc(task.approach)}"
               placeholder="A1" data-field="approach" />
      </td>
      <td class="col-problem">
        <textarea placeholder="Problem description"
                  data-field="problem" rows="2">${esc(task.problem)}</textarea>
      </td>
      <td class="col-vendor">
        <input type="text" value="${esc(task.vendor)}"
               placeholder="N/A" data-field="vendor" />
      </td>
      <td class="col-sap">
        <input type="text" value="${esc(task.sap_notification)}"
               placeholder="SAP number" data-field="sap_notification" />
      </td>
      <td class="col-action">
        <textarea placeholder="Enter action taken…"
                  data-field="action_taken" rows="2">${esc(task.action_taken)}</textarea>
      </td>
      <td class="col-status">
        <select class="status-select" data-field="current_status">${opts}</select>
      </td>
      <td class="col-comments">
        <textarea placeholder="Comments"
                  data-field="comments" rows="2">${esc(task.comments)}</textarea>
      </td>
      <td class="col-del">
        <button type="button" class="btn btn-danger del-row-btn" title="Delete row">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
               style="width:14px;height:14px;" aria-hidden="true">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14H6L5 6"/>
            <path d="M10 11v6"/><path d="M14 11v6"/>
            <path d="M9 6V4h6v2"/>
          </svg>
        </button>
      </td>`;
  }

  function renumber() {
    tbody.querySelectorAll("tr").forEach((tr, i) => {
      const b = tr.querySelector(".row-num-display");
      if (b) b.textContent = i + 1;
    });
  }

  // ── Collect DOM values → tasks[] ──────────────────────────────
  function collectData() {
    const updated = [];
    tbody.querySelectorAll("tr").forEach((tr, i) => {
      const t = { row_num: i + 1 };
      tr.querySelectorAll("[data-field]").forEach(el => {
        t[el.dataset.field] = el.value.trim();
      });
      updated.push(t);
    });
    tasks = updated;
  }

  // ── Validation ────────────────────────────────────────────────
  function validate() {
    const errors = [];
    document.querySelectorAll(".invalid").forEach(el => el.classList.remove("invalid"));

    const sv = document.getElementById("supervisor");
    const tm = document.getElementById("team");
    if (sv && !sv.value.trim()) {
      errors.push("Supervisor Name is required.");
      sv.classList.add("invalid");
    }
    if (tm && !tm.value.trim()) {
      errors.push("Team / Technicians is required.");
      tm.classList.add("invalid");
    }

    tbody.querySelectorAll("tr").forEach((tr, i) => {
      const n      = i + 1;
      const siteEl = tr.querySelector("[data-field='site_id']");
      const probEl = tr.querySelector("[data-field='problem']");
      const actEl  = tr.querySelector("[data-field='action_taken']");
      if (siteEl && !siteEl.value.trim()) {
        errors.push(`Row ${n}: Site ID is required.`);
        siteEl.classList.add("invalid");
      }
      if (probEl && !probEl.value.trim()) {
        errors.push(`Row ${n}: Problem is required.`);
        probEl.classList.add("invalid");
      }
      if (actEl && !actEl.value.trim()) {
        errors.push(`Row ${n}: Action Taken is required.`);
        actEl.classList.add("invalid");
      }
    });

    return errors;
  }

  function showErrors(errors) {
    valBanner.style.display = "flex";
    valList.innerHTML = errors.map(e => `<li>${e}</li>`).join("");
    valBanner.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function hideErrors() {
    valBanner.style.display = "none";
    valList.innerHTML = "";
  }

  // ── Submit to /report-preview ─────────────────────────────────
  function submitPreview() {
    if (loadingOv) loadingOv.style.display = "flex";

    document.getElementById("f-supervisor").value  = document.getElementById("supervisor").value;
    document.getElementById("f-team").value        = document.getElementById("team").value;
    document.getElementById("f-shift").value       = document.getElementById("shift").value;
    document.getElementById("f-time-range").value  = document.getElementById("time_range").value;
    document.getElementById("f-date").value        = document.getElementById("date").value;
    document.getElementById("f-tasks-json").value  = JSON.stringify(tasks);

    reportForm.submit();
  }

  // ── Helpers ───────────────────────────────────────────────────
  function emptyTask() {
    return {
      row_num: 0, task: "Field Service", site_id: "", approach: "N/A",
      problem: "", vendor: "N/A", sap_notification: "", action_taken: "",
      current_status: "Solved", comments: "Waiting for RM confirmation",
    };
  }
  function autoGrow(el) {
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }
  function updateStatusColor(sel) {
    sel.classList.remove("status-solved", "status-pending");
    sel.classList.add(sel.value === "Solved" ? "status-solved" : "status-pending");
  }
  function esc(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();


/* ═══════════════════════════════════════════════════════════════
   REPORT PREVIEW — Copy Report (Outlook-compatible HTML)
   ═══════════════════════════════════════════════════════════════ */
(function initReportPreviewPage() {
  const copyBtn       = document.getElementById("copy-btn");
  const backEditBtn   = document.getElementById("back-edit-btn");
  const successBanner = document.getElementById("copy-success");
  // The clipboard HTML is in the HIDDEN div with inline styles
  const clipboardDiv  = document.getElementById("report-clipboard-html");

  if (!copyBtn) return;  // not on this page

  copyBtn.addEventListener("click", async () => {
    if (!clipboardDiv) return;

    const htmlContent = clipboardDiv.innerHTML;
    const plainText   = buildPlainText();

    let copied = false;

    // Method 1: ClipboardItem API (best — preserves HTML in Outlook/Word)
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      try {
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html":  new Blob([htmlContent], { type: "text/html" }),
            "text/plain": new Blob([plainText],   { type: "text/plain" }),
          })
        ]);
        copied = true;
      } catch (_) { /* fall through */ }
    }

    // Method 2: execCommand on a contenteditable div with the HTML
    if (!copied) {
      try {
        const el = document.createElement("div");
        el.setAttribute("contenteditable", "true");
        el.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
        el.innerHTML = htmlContent;
        document.body.appendChild(el);
        const range = document.createRange();
        range.selectNodeContents(el);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        copied = document.execCommand("copy");
        sel.removeAllRanges();
        document.body.removeChild(el);
      } catch (_) { /* fall through */ }
    }

    // Method 3: plain text fallback
    if (!copied) {
      try {
        await navigator.clipboard.writeText(plainText);
        copied = true;
      } catch (_) { /* ignore */ }
    }

    // Show toast
    if (successBanner) {
      successBanner.style.display = "flex";
      successBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
      setTimeout(() => { successBanner.style.display = "none"; }, 7000);
    }
  });

  if (backEditBtn) {
    backEditBtn.addEventListener("click", () => history.back());
  }

  function buildPlainText() {
    const lines = [];
    // Pull visible text from the screen-preview section
    const screenDiv = document.getElementById("report-screen-preview");
    if (!screenDiv) return "";

    const sal = screenDiv.querySelector(".report-salutation");
    if (sal) lines.push(sal.textContent.trim(), "");
    const intro = screenDiv.querySelector(".report-intro");
    if (intro) lines.push(intro.textContent.trim(), "");
    const title = screenDiv.querySelector(".report-title");
    if (title) lines.push(title.textContent.trim(), "");

    // Info table
    const infoRows = screenDiv.querySelectorAll(".rpt-info-table tr");
    infoRows.forEach(tr => {
      const cells = [...tr.cells].map(c => c.textContent.trim());
      for (let i = 0; i < cells.length; i += 2) {
        if (cells[i] && cells[i + 1]) lines.push(`${cells[i]}: ${cells[i + 1]}`);
      }
    });
    lines.push("");

    // Main table
    const mainRows = screenDiv.querySelectorAll(".rpt-main-table tr");
    mainRows.forEach((tr, i) => {
      const cells = [...tr.cells].map(c => c.textContent.trim());
      lines.push(cells.join(" | "));
      if (i === 0) lines.push("-".repeat(80));
    });
    lines.push("");

    const closing = screenDiv.querySelector(".report-closing");
    if (closing) lines.push(closing.textContent.trim());

    return lines.join("\n");
  }
})();


/* ═══════════════════════════════════════════════════════════════
   COMBINE PHOTOS PAGE
   Handles 1–30 photos; name="photos" matches Flask backend.
   ═══════════════════════════════════════════════════════════════ */
(function initCombinePhotosPage() {
  const multiDrop      = document.getElementById("multi-drop-zone");
  const photosInput    = document.getElementById("photos-input");
  const thumbStrip     = document.getElementById("thumb-strip");
  const thumbGrid      = document.getElementById("thumb-grid");
  const clearBtn       = document.getElementById("clear-photos-btn");
  const previewBtn     = document.getElementById("preview-btn");
  const combineForm    = document.getElementById("combine-form");
  const loadingOv      = document.getElementById("loading-overlay");
  const wmText         = document.getElementById("watermark_text");
  const wmControls     = document.getElementById("watermark-controls");
  const opacitySlider  = document.getElementById("watermark_opacity");
  const opacityDisplay = document.getElementById("opacity-display");
  const countBar       = document.getElementById("photo-count-bar");
  const countText      = document.getElementById("photo-count-text");

  if (!multiDrop || !photosInput) return;  // not on this page

  const MAX_PHOTOS = 30;
  // Internal accumulator — survives multiple browse/drop events
  let fileList = new DataTransfer();

  // ── Drag events ────────────────────────────────────────────────
  ["dragenter", "dragover"].forEach(e =>
    multiDrop.addEventListener(e, ev => {
      ev.preventDefault();
      multiDrop.classList.add("drag-over");
    })
  );
  ["dragleave", "drop"].forEach(e =>
    multiDrop.addEventListener(e, () => multiDrop.classList.remove("drag-over"))
  );
  multiDrop.addEventListener("drop", ev => {
    ev.preventDefault();
    addFiles(ev.dataTransfer.files);
  });

  // ── Browse (click) ──────────────────────────────────────────────
  photosInput.addEventListener("change", () => {
    const selectedFiles = Array.from(photosInput.files || []);
    if (selectedFiles.length) {
      addFiles(selectedFiles);
    }
    // Do NOT clear photosInput.value here. Flask reads files from this input.
  });

  // ── Watermark controls ──────────────────────────────────────────
  if (wmText) {
    wmText.addEventListener("input", () => {
      if (wmControls) {
        wmControls.style.display = wmText.value.trim() ? "block" : "none";
      }
    });
  }
  if (opacitySlider && opacityDisplay) {
    opacitySlider.addEventListener("input", () => {
      opacityDisplay.textContent = opacitySlider.value;
    });
  }

  // ── Clear all ───────────────────────────────────────────────────
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      fileList = new DataTransfer();
      syncInputAndUI();
    });
  }

  // ── Show loading on submit ──────────────────────────────────────
  if (combineForm) {
    combineForm.addEventListener("submit", ev => {
      // Final sync: make sure the native input has all accumulated files
      syncInputAndUI();

      // Double-check count before letting the form submit
      console.log("Combine Photos files before submit:", photosInput.files.length);
      const count = fileList.files.length;
      if (count === 0) {
        ev.preventDefault();
        alert("Please upload at least one photo.");
        return;
      }
      if (count > MAX_PHOTOS) {
        ev.preventDefault();
        alert(`You can upload a maximum of ${MAX_PHOTOS} photos. Currently selected: ${count}.`);
        return;
      }

      if (loadingOv) loadingOv.style.display = "flex";
    });
  }

  // ── Add files to accumulator ────────────────────────────────────
  function addFiles(incoming) {
    const allowed = ["image/png", "image/jpeg", "image/jpg"];
    let skipped = 0;

    Array.from(incoming).forEach(file => {
      if (!allowed.includes(file.type)) {
        skipped++;
        return;
      }
      if (fileList.files.length >= MAX_PHOTOS) {
        alert(`Maximum ${MAX_PHOTOS} photos allowed. Extra files were not added.`);
        return;
      }
      fileList.items.add(file);
      appendThumb(file);
    });

    if (skipped) {
      alert(`${skipped} file(s) were skipped (not PNG/JPG/JPEG).`);
    }

    syncInputAndUI();
  }

  // ── Sync DataTransfer → native input & update UI ────────────────
  function syncInputAndUI() {
    // Assign accumulated files back to the native input
    // (This is the critical step — the form reads from photosInput.files)
    try {
      photosInput.files = fileList.files;
    } catch (e) {
      console.warn("Could not assign DataTransfer to input.files:", e);
    }

    const count = fileList.files.length;

    if (count === 0) {
      if (thumbStrip)   thumbStrip.style.display   = "none";
      if (countBar)     countBar.style.display      = "none";
      if (thumbGrid)    thumbGrid.innerHTML          = "";
      if (previewBtn)   previewBtn.disabled          = true;
    } else {
      if (thumbStrip)   thumbStrip.style.display   = "flex";
      if (countBar)     countBar.style.display      = "flex";
      if (previewBtn)   previewBtn.disabled          = false;
      if (countText) {
        countText.textContent = `${count} photo${count !== 1 ? "s" : ""} selected`;
      }
    }
  }

  // ── Thumbnail tile ──────────────────────────────────────────────
  function appendThumb(file) {
    const reader = new FileReader();
    reader.onload = ev => {
      if (!thumbGrid) return;
      const item       = document.createElement("div");
      item.className   = "thumb-item";
      item.dataset.name = file.name;
      item.innerHTML = `
        <img src="${ev.target.result}" alt="${esc(file.name)}" />
        <div class="thumb-item__label">${esc(file.name)}</div>
        <button type="button" class="thumb-item__remove" title="Remove">&#x2715;</button>`;
      item.querySelector(".thumb-item__remove")
          .addEventListener("click", () => removeFile(file.name, item));
      thumbGrid.appendChild(item);
    };
    reader.readAsDataURL(file);
  }

  // ── Remove one file ─────────────────────────────────────────────
  function removeFile(name, element) {
    const newDt = new DataTransfer();
    Array.from(fileList.files).forEach(f => {
      if (f.name !== name) newDt.items.add(f);
    });
    fileList = newDt;
    element.remove();
    syncInputAndUI();
  }

  function esc(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
