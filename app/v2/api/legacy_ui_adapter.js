(function () {
  "use strict";

  if (window.FLAIRLAB_PIPELINE_VERSION !== "v2") return;

  let v2Session = null;
  let v2UploadQueue = Promise.resolve();
  let v2ImageUploadInFlight = 0;
  let v2WorkbookStatus = null;
  let v2WakeLock = null;
  let v2RecordedVoiceQueue = [];
  const v2LocalImagePreviewUrls = new Map();

  function v2UserId() {
    return (document.getElementById("clientId").value || "flairlab").trim();
  }

  function selectedPostTypeKey() {
    return (document.getElementById("postType").value || "").trim().toLowerCase();
  }

  function renderVoiceInstructionsForSelectedPostType() {
    const target = document.getElementById("voiceInstructions");
    const select = document.getElementById("postType");
    if (!target || !select) return;
    const html = select.selectedOptions[0]?.dataset.voiceInstructions || "";
    target.innerHTML = html.trim()
      ? html
      : "Für diesen Beitragstyp sind keine Aufnahmehinweise in der Database Datei hinterlegt.";
  }

  function renderPostTypeOptions(version) {
    const select = document.getElementById("postType");
    if (!select || !Array.isArray(version.post_types) || !version.post_types.length) return;
    const previous = selectedPostTypeKey();
    select.innerHTML = "";
    for (const postType of version.post_types) {
      const key = String(postType.post_type_key || "").trim();
      if (!key) continue;
      const option = document.createElement("option");
      option.value = key;
      option.textContent = postType.display_name_de || key;
      option.dataset.category = postType.wp_category_name || "";
      option.dataset.voiceInstructions = postType.voice_instructions || "";
      select.appendChild(option);
    }
    const selected = version.selected_post_type_key || previous || select.options[0]?.value || "";
    select.value = [...select.options].some(option => option.value === selected)
      ? selected
      : (select.options[0]?.value || "");
    const selectedOption = select.selectedOptions[0];
    if (selectedOption?.dataset.category) {
      const category = document.getElementById("category");
      if (category && !category.value.trim()) category.value = selectedOption.dataset.category;
    }
    renderVoiceInstructionsForSelectedPostType();
  }

  function v2Headers(json = true) {
    return {
      "X-API-Key": key(),
      "X-User-ID": v2UserId(),
      ...(json ? {"Content-Type": "application/json"} : {}),
    };
  }

  window.headers = function headers(json = true) {
    return v2Headers(json);
  };

  async function v2Api(path, options = {}) {
    const response = await fetch(path, options);
    const text = await response.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
    if (!response.ok) {
      const message = data && typeof data === "object"
        ? formatV2ApiError(data)
        : String(data || `HTTP ${response.status}`);
      const error = new Error(message);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function formatV2ApiError(data) {
    const detail = data.detail || data.message || data.error || data;
    if (Array.isArray(detail)) {
      return detail.map(item => {
        if (!item || typeof item !== "object") return String(item);
        const location = Array.isArray(item.loc) ? item.loc.join(".") : "";
        const message = item.msg || item.message || JSON.stringify(item);
        return location ? `${location}: ${message}` : message;
      }).join("; ");
    }
    if (detail && typeof detail === "object") return JSON.stringify(detail);
    return String(detail || "HTTP request failed");
  }

  async function acquireV2WakeLock() {
    if (!("wakeLock" in navigator) || v2WakeLock) return;
    try {
      v2WakeLock = await navigator.wakeLock.request("screen");
      v2WakeLock.addEventListener("release", () => {
        v2WakeLock = null;
      });
    } catch (error) {
      console.warn("Wake lock unavailable", error);
    }
  }

  async function releaseV2WakeLock() {
    if (!v2WakeLock) return;
    try {
      await v2WakeLock.release();
    } catch (error) {
      console.warn("Wake lock release failed", error);
    } finally {
      v2WakeLock = null;
    }
  }

  async function waitForV2Job(job, statusText) {
    await acquireV2WakeLock();
    const startedAt = Date.now();
    try {
      let current = job;
      while (["queued", "running"].includes(current.status)) {
        status(`${statusText} (Dauer: ${formatElapsedDuration(Date.now() - startedAt)})`);
        await waitMs(document.hidden ? 5000 : 1500);
        current = await v2Api(`/api/content-sessions/jobs/${current.job_id}`, {
          headers: v2Headers(false),
        });
      }
      if (current.status !== "complete") {
        throw new Error(current.error || `Job ${current.job_id} ist fehlgeschlagen.`);
      }
      if (!current.session) {
        throw new Error(`Job ${current.job_id} lieferte keine Session zurück.`);
      }
      return current.session;
    } finally {
      await releaseV2WakeLock();
    }
  }

  async function startV2SessionJob(path, body, statusText) {
    const job = await v2Api(path, {
      method: "POST",
      headers: v2Headers(),
      body: JSON.stringify(body),
    });
    return waitForV2Job(job, statusText);
  }

  async function refreshV2Session(statusText = null) {
    if (!v2Session) return null;
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}`,
      {headers: v2Headers(false)}
    );
    await renderV2(data.session, statusText ? {statusText} : {});
    return v2Session;
  }

  async function loadActiveV2Session(statusText = null) {
    if (v2Session) return refreshV2Session(statusText);
    if (!sessionId) return null;
    const data = await v2Api(
      `/api/content-sessions/${sessionId}`,
      {headers: v2Headers(false)}
    );
    await renderV2(data.session, statusText ? {statusText} : {});
    return v2Session;
  }

  function hasV2DraftReadyForWordPress() {
    return ["needs_review", "ready_to_publish", "published"].includes(v2Session?.state);
  }

  function encodedDraftValue(value) {
    if (Array.isArray(value) || (value && typeof value === "object")) {
      return JSON.stringify(value);
    }
    return value == null ? "" : String(value);
  }

  function draftCsv(session) {
    const shared = session.shared_fields || {};
    const acf = session.acf_source_fields || {};
    const headers = [...Object.keys(shared), ...Object.keys(acf)];
    if (!headers.length) return "";
    return csvFromRows([
      headers,
      headers.map(field => encodedDraftValue(
        Object.prototype.hasOwnProperty.call(shared, field) ? shared[field] : acf[field]
      )),
    ]);
  }

  function mediaItem(reference) {
    return {
      filename: reference.filename,
      original_filename: reference.filename,
      content_type: reference.content_type,
      size_bytes: reference.size_bytes,
      media_id: reference.media_id,
    };
  }

  function adaptSession(session) {
    v2Session = session;
    const processedByMedia = Object.fromEntries(
      (session.processed_images || []).map(item => [item.media_id, item])
    );
    const metadataByMedia = Object.fromEntries(
      (session.image_metadata || []).map(item => [item.media_id, item])
    );
    const images = (session.image_refs || []).map(reference => {
      const processed = processedByMedia[reference.media_id];
      const metadata = metadataByMedia[reference.media_id] || {};
      return {
        ...mediaItem(reference),
        filename: processed?.filename || reference.filename,
        original_filename: reference.filename,
        original_path: reference.storage_uri,
        hasOriginal: true,
        isProcessed: !!processed,
        processed_at: processed ? session.updated_at : null,
        applied_operations: processed?.operations || [],
        wp_metadata: {
          alt_text: metadata.image_alt || metadata.alt_text || "",
          title: metadata.image_title || metadata.title || "",
          caption: metadata.image_caption || metadata.caption || "",
          description: metadata.image_description || metadata.description || metadata.image_description_wp || "",
        },
      };
    });
    const featuredMetadata = (session.image_metadata || []).find(
      item => item && item.image_usage === "featured"
    );
    const featuredReference = (session.image_refs || []).find(
      reference => reference.media_id === featuredMetadata?.media_id
    );
    const featuredImageMediaId = featuredReference?.media_id || "";
    const featuredImageFilename = featuredReference
      ? (processedByMedia[featuredReference.media_id]?.filename || featuredReference.filename)
      : "";
    const imageProcessingStatus = v2ImageUploadInFlight
      ? "processing"
      : (session.image_refs?.length || 0) > 0
        && session.image_refs?.length === session.processed_images?.length
        ? "complete"
        : "idle";
    const result = session.wordpress_result || {};
    return {
      session_id: session.session_id,
      client_id: session.user_id,
      post_type: session.post_type_key,
      status: session.state,
      files: {
        voices: (session.audio_refs || []).map(mediaItem),
        images,
        videos: [],
        featured_image_media_id: featuredImageMediaId,
        featured_image_filename: featuredImageFilename || images[0]?.filename || "",
      },
      transcript: {
        text: session.transcript || session.manual_text || "",
        source: session.transcript ? "v2_transcription" : "v2_manual_text",
      },
      draft: {
        csv_text: draftCsv(session),
        category: session.shared_fields?.category || "",
        chat: session.draft_chat || [],
        generation_trace: session.generation_trace || {},
      },
      wordpress_post: result.post_id ? {
        post_id: result.post_id,
        status: result.status,
        view_url: result.link || result.view_url,
        edit_url: result.edit_url,
        post_write_mode: "v2",
      } : {},
      image_processing: {
        status: imageProcessingStatus,
        processed_count: session.processed_images?.length || 0,
        total_count: session.image_refs?.length || 0,
      },
      ai_usage: session.ai_usage || {},
      _v2_session: session,
    };
  }

  async function renderV2(session, options = {}) {
    await renderFreshSession(adaptSession(session));
    renderV2Clarifications(session);
    if (options.statusText) status(options.statusText);
  }

  schedulePillowStatusPoll = function schedulePillowStatusPoll() {
    if (!v2Session || !key()) return;
    clearTimeout(pillowStatusPollTimer);
    const startedAt = Date.now();
    const poll = async () => {
      if (!v2Session || !key()) return;
      try {
        await refreshV2Session();
        const adapted = adaptSession(v2Session);
        const processing = adapted.image_processing || {};
        const statusValue = String(processing.status || "").trim().toLowerCase();
        if (statusValue === "complete") {
          lastPillowProgressKey = "";
          pillowRecoveryTriggered = false;
          status("Pillow processing finished. Click 'Edits anzeigen' on a processed image.");
          return;
        }
        if (statusValue === "processing" && Date.now() - startedAt < 180000) {
          pillowStatusPollTimer = setTimeout(
            () => poll().catch(error => console.warn("Pillow poll failed", error)),
            2200
          );
        }
      } catch (error) {
        console.warn("Pillow status poll failed", error);
      }
    };
    poll().catch(error => console.warn("Pillow poll failed", error));
  };

  function factValues(session) {
    const values = {};
    for (const [field, fact] of Object.entries(session.extracted_facts || {})) {
      values[field] = fact.value;
    }
    for (const [field, fact] of Object.entries(session.confirmed_facts || {})) {
      values[field] = fact.value;
    }
    return values;
  }

  function factSchema() {
    return (v2WorkbookStatus?.fact_schema || []).map(row => ({
      field_key: row.field_key,
      label: row.label || row.field_key,
      required: !!row.required,
    }));
  }

  function renderFactTable(session) {
    const values = factValues(session);
    const requiredMissing = new Set(
      (session.clarification_questions || []).map(question => String(question || "").toLowerCase())
    );
    const rows = factSchema();
    const tableRows = rows.length
      ? rows
      : Object.keys(values).map(field => ({field_key: field, label: field, required: false}));
    const body = document.getElementById("v2FactsTableBody");
    body.innerHTML = "";
    for (const row of tableRows) {
      const value = values[row.field_key] ?? "";
      const missingRequired = row.required
        && (value == null || value === "" || (Array.isArray(value) && !value.length));
      const tr = document.createElement("tr");
      if (missingRequired) {
        tr.className = "v2-fact-missing-required";
        tr.style.background = "#fee2e2";
        tr.style.color = "#991b1b";
      }
      const label = document.createElement("td");
      label.textContent = row.label || row.field_key;
      const inputCell = document.createElement("td");
      const input = document.createElement("input");
      input.type = "text";
      input.dataset.factKey = row.field_key;
      input.dataset.valueType = Array.isArray(value) ? "list" : typeof value;
      input.value = Array.isArray(value) ? value.join("; ") : String(value ?? "");
      input.placeholder = row.required ? "Pflichtangabe fehlt" : "Optional";
      inputCell.appendChild(input);
      tr.appendChild(label);
      tr.appendChild(inputCell);
      body.appendChild(tr);
    }
    const hidden = document.getElementById("v2ConfirmedFacts");
    if (hidden) hidden.value = JSON.stringify(factsFromTable(), null, 2);
  }

  function factsFromTable() {
    const values = {};
    document.querySelectorAll("#v2FactsTableBody input[data-fact-key]").forEach(input => {
      const raw = input.value.trim();
      if (!raw) return;
      values[input.dataset.factKey] = input.dataset.valueType === "list"
        ? raw.split(";").map(item => item.trim()).filter(Boolean)
        : raw;
    });
    return values;
  }

  function ensureClarificationPanel() {
    let panel = document.getElementById("v2FactConfirmation");
    if (panel) return panel;
    panel = document.createElement("details");
    panel.id = "v2FactConfirmation";
    panel.className = "summary";
    panel.style.marginTop = "14px";
    panel.style.borderColor = "#f59e0b";
    panel.innerHTML = `
      <summary style="cursor:pointer;font-weight:800;color:#1f2933;">Fakten anzeigen / bearbeiten</summary>
      <p id="v2ClarificationQuestions"></p>
      <table class="v2-facts-table" style="width:100%;border-collapse:collapse;margin:10px 0;">
        <thead><tr><th style="text-align:left;">Fakt</th><th style="text-align:left;">Wert</th></tr></thead>
        <tbody id="v2FactsTableBody"></tbody>
      </table>
      <textarea id="v2ConfirmedFacts" style="display:none;">{}</textarea>
      <button type="button" id="v2ConfirmFactsButton">Fakten speichern & erneut analysieren</button>
    `;
    const transcriptPanel = document.querySelector("#panelTranscript .panel-body");
    transcriptPanel.appendChild(panel);
    document.getElementById("v2ConfirmFactsButton").addEventListener(
      "click",
      () => run(confirmV2Facts)
    );
    panel.addEventListener("input", () => {
      const hidden = document.getElementById("v2ConfirmedFacts");
      if (hidden) hidden.value = JSON.stringify(factsFromTable(), null, 2);
    });
    return panel;
  }

  function renderV2Clarifications(session) {
    const panel = ensureClarificationPanel();
    const questions = session.clarification_questions || [];
    const hasKnownFacts = Object.keys(factValues(session)).length > 0;
    const hasTranscript = !!String(session.transcript || session.manual_text || "").trim();
    const shouldShow = session.state === "needs_input"
      || questions.length > 0
      || hasKnownFacts
      || (hasTranscript && factSchema().length > 0);
    panel.style.display = shouldShow ? "block" : "none";
    document.getElementById("v2ClarificationQuestions").textContent =
      questions.length
        ? questions.map((question, index) => `${index + 1}. ${question}`).join("\n")
        : "Erkannte Fakten prüfen, bei Bedarf korrigieren und speichern.";
    if (shouldShow) {
      renderFactTable(session);
      panel.open = session.state === "needs_input" || questions.length > 0 || panel.open;
      if (session.state === "needs_input" || questions.length > 0) {
        openPanel("panelTranscript", true);
      }
    }
  }

  async function confirmV2Facts() {
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    let corrections;
    try {
      corrections = factsFromTable();
      document.getElementById("v2ConfirmedFacts").value = JSON.stringify(corrections, null, 2);
    } catch {
      throw new Error("Die bestätigten Fakten enthalten ungültiges JSON.");
    }
    let data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/answers`,
      {
        method: "POST",
        headers: v2Headers(),
        body: JSON.stringify({
          expected_version: v2Session.version,
          corrections,
        }),
      }
    );
    v2Session = data.session;
    data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/analyze`,
      {
        method: "POST",
        headers: v2Headers(),
        body: JSON.stringify({expected_version: v2Session.version}),
      }
    );
    await renderV2(data.session, {statusText: "Fakten bestätigt und Analyse aktualisiert."});
  }
  window.confirmV2Facts = confirmV2Facts;

  function useVisionOnUpload() {
    const checkbox = document.getElementById("v2UseVisionOnUpload");
    return !!(checkbox && checkbox.checked);
  }

  function imageUploadActionLabel() {
    return useVisionOnUpload()
      ? "mit späterer Vision-Metadatenanalyse und direkt mit Pillow verarbeitet"
      : "ohne Vision direkt mit Pillow verarbeitet";
  }

  function rememberLocalImagePreview(file) {
    if (!file || v2LocalImagePreviewUrls.has(file.name)) return;
    const url = URL.createObjectURL(file);
    v2LocalImagePreviewUrls.set(file.name, url);
    imagePreviewUrls.push(url);
  }

  function clearV2LocalMediaUi() {
    v2LocalImagePreviewUrls.clear();
    imagePreviewUrls.forEach(url => setTimeout(() => URL.revokeObjectURL(url), 1500));
    imagePreviewUrls = [];
    const imagePreviews = document.getElementById("imagePreviews");
    if (imagePreviews) imagePreviews.innerHTML = "";
    const featuredChoices = document.getElementById("featuredChoices");
    if (featuredChoices) {
      featuredChoices.innerHTML = "";
      featuredChoices.style.display = "none";
    }
    const videoPreviews = document.getElementById("videoPreviews");
    if (videoPreviews) videoPreviews.innerHTML = "";
    const playback = document.getElementById("recordingPlayback");
    if (playback) {
      playback.removeAttribute("src");
      playback.style.display = "none";
    }
    recordedVoiceBlob = null;
    recordedVoiceName = "";
    v2RecordedVoiceQueue = [];
    v2ImageUploadInFlight = 0;
    clearUploadInputs({voices: true, images: true, videos: true});
  }

  function queuedRecordedVoiceFiles() {
    if (v2RecordedVoiceQueue.length) return [...v2RecordedVoiceQueue];
    if (!recordedVoiceBlob) return [];
    return [
      new File(
        [recordedVoiceBlob],
        recordedVoiceName || "recording.webm",
        {type: recordedVoiceBlob.type || "audio/webm"}
      ),
    ];
  }

  function clearQueuedRecordings() {
    v2RecordedVoiceQueue = [];
    recordedVoiceBlob = null;
    recordedVoiceName = "";
    renderVoiceChoices();
  }

  const baseRenderVoiceList = renderVoiceList;
  renderVoiceList = function renderVoiceList(uploadedVoices = [], localVoices = []) {
    baseRenderVoiceList(uploadedVoices, [
      ...localVoices,
      ...queuedRecordedVoiceFiles(),
    ]);
  };

  const baseRemoveLocalVoice = removeLocalVoice;
  removeLocalVoice = function removeLocalVoice(filename) {
    const before = v2RecordedVoiceQueue.length;
    v2RecordedVoiceQueue = v2RecordedVoiceQueue.filter(file => file.name !== filename);
    if (before !== v2RecordedVoiceQueue.length) {
      if (recordedVoiceName === filename) {
        recordedVoiceBlob = v2RecordedVoiceQueue.length ? v2RecordedVoiceQueue[v2RecordedVoiceQueue.length - 1] : null;
        recordedVoiceName = v2RecordedVoiceQueue.length ? v2RecordedVoiceQueue[v2RecordedVoiceQueue.length - 1].name : "";
      }
      renderVoiceChoices();
      updateButtons();
      return;
    }
    baseRemoveLocalVoice(filename);
  }

  async function uploadV2File(file, kind) {
    if (!v2Session || !Number.isInteger(Number(v2Session.version))) {
      await loadActiveV2Session();
    }
    if (!v2Session || !Number.isInteger(Number(v2Session.version))) {
      throw new Error("Session-Version fehlt. Bitte Session neu laden und Upload erneut versuchen.");
    }
    const form = new FormData();
    form.append("expected_version", String(Number(v2Session.version)));
    form.append("kind", kind);
    if (kind === "image") form.append("use_vision", "0");
    form.append("upload", file);
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/uploads`,
      {method: "POST", headers: v2Headers(false), body: form}
    );
    v2Session = data.session;
  }

  function v2ImageUrl(filename, original = false) {
    const suffix = original ? "/original" : "";
    return `/api/content-sessions/${v2Session.session_id}/media/images/${encodeURIComponent(filename)}${suffix}`;
  }

  fetchOriginalImageBlobWithRetry = async function fetchOriginalImageBlobWithRetry(filename) {
    if (!v2Session) await loadActiveV2Session();
    const response = await fetch(v2ImageUrl(filename, true), {headers: v2Headers(false)});
    if (!response.ok) {
      const imageItem = findSessionImageItem(filename);
      const localUrl = v2LocalImagePreviewUrls.get(imageItem?.original_filename || filename);
      if (localUrl) return await (await fetch(localUrl)).blob();
      throw new Error("Originalbild konnte nicht aus der Session geladen werden.");
    }
    return await response.blob();
  };

  renderUploadedImagePreviews = async function renderUploadedImagePreviews(images, featuredValue = "") {
    if (!v2Session || !images || !images.length || !key()) return;
    const items = [];
    for (const image of images) {
      try {
        const response = await fetch(v2ImageUrl(image.filename), {headers: v2Headers(false)});
        let url = "";
        let isProcessed = !!image.processed_at;
        if (response.ok) {
          const blob = await response.blob();
          url = URL.createObjectURL(blob);
          imagePreviewUrls.push(url);
        } else {
          url = v2LocalImagePreviewUrls.get(image.original_filename || image.filename) || "";
          isProcessed = false;
        }
        if (!url) continue;
        items.push({
          url,
          name: image.original_filename || image.filename,
          value: image.filename,
          media_id: image.media_id || "",
          persisted: true,
          hasOriginal: !!image.original_path,
          isProcessed,
        });
      } catch (error) {
        console.warn("Image preview failed", error);
      }
    }
    if (!items.length) return;
    document.getElementById("imagePreviews").innerHTML = "";
    if (items.length) renderImagePreviewItems(items, {
      selectable: true,
      removable: true,
      kind: "images",
      selectedValue: featuredValue,
      selectedMediaId: (((currentSessionData || {}).files || {}).featured_image_media_id) || "",
      compareable: true,
      onCompare: async (filename) => {
        const beforeBlob = await fetchOriginalImageBlobWithRetry(filename);
        const beforeUrl = URL.createObjectURL(beforeBlob);
        const afterResponse = await fetch(v2ImageUrl(filename), {headers: v2Headers(false)});
        if (!afterResponse.ok) throw new Error("Bearbeitetes Bild konnte nicht geladen werden.");
        const afterBlob = await afterResponse.blob();
        const afterUrl = URL.createObjectURL(afterBlob);
        const images = (((currentSessionData || {}).files || {}).images || []);
        const imageItem = images.find(img => img.filename === filename);
        const appliedOps = (imageItem || {}).applied_operations || [];
        openImageCompareModal(filename, beforeUrl, afterUrl, appliedOps, imageItem);
      },
    });
  };

  removeUploadedMedia = async function removeUploadedMedia(kind, filename) {
    if (!v2Session) await loadActiveV2Session();
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/media/${kind}/${encodeURIComponent(filename)}`,
      {
        method: "DELETE",
        headers: v2Headers(),
        body: JSON.stringify({expected_version: v2Session.version}),
      }
    );
    await renderV2(data.session, {
      statusText: kind === "images" ? "Bild aus der Session entfernt." : "Sprachnachricht aus der Session entfernt.",
    });
  };

  setFeaturedImage = async function setFeaturedImage(filename) {
    if (!filename) return;
    if (!v2Session) await loadActiveV2Session();
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/featured-image`,
      {
        method: "PUT",
        headers: v2Headers(),
        body: JSON.stringify({
          expected_version: v2Session.version,
          filename,
        }),
      }
    );
    await renderV2(data.session, {statusText: "Titelbild gespeichert."});
  };

  function appendPendingV2ImageCards(files) {
    const wrap = document.getElementById("imagePreviews");
    if (!wrap || !files.length) return;
    files.forEach(file => {
      rememberLocalImagePreview(file);
      const url = v2LocalImagePreviewUrls.get(file.name);
      if (!url) return;
      const existing = [...wrap.querySelectorAll(".image-preview")].find(card => (
        (card.dataset.mediaValue || "") === file.name
      ));
      if (existing) return;
      const card = document.createElement("div");
      card.className = "image-preview";
      card.dataset.mediaKind = "images";
      card.dataset.mediaValue = file.name;
      const image = document.createElement("img");
      image.src = url;
      image.alt = file.name;
      card.appendChild(image);
      const selected = document.createElement("div");
      selected.className = "media-select-label";
      selected.textContent = "In Verarbeitung";
      card.appendChild(selected);
      const label = document.createElement("span");
      label.className = "image-preview-label";
      label.textContent = file.name;
      label.title = file.name;
      card.appendChild(label);
      const controls = document.createElement("div");
      controls.className = "image-card-controls";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pillow-status-btn loading";
      button.disabled = true;
      button.innerHTML = '<span class="pillow-spinner" aria-hidden="true"></span><span>Wird optimiert</span>';
      controls.appendChild(button);
      card.appendChild(controls);
      wrap.appendChild(card);
    });
  }

  function markLocalImageCardsProcessing(files) {
    files.forEach(rememberLocalImagePreview);
    appendPendingV2ImageCards(files);
    const names = new Set(files.map(file => file.name));
    document.querySelectorAll("#imagePreviews .image-preview").forEach(card => {
      const name = card.dataset.mediaValue || "";
      if (!names.has(name)) return;
      let controls = card.querySelector(".image-card-controls");
      if (!controls) {
        controls = document.createElement("div");
        controls.className = "image-card-controls";
        card.appendChild(controls);
      }
      controls.innerHTML = "";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pillow-status-btn loading";
      button.disabled = true;
      button.innerHTML = '<span class="pillow-spinner" aria-hidden="true"></span><span>Wird optimiert</span>';
      controls.appendChild(button);
    });
  }

  function decodeEditedValue(value, original) {
    if (Array.isArray(original) || (original && typeof original === "object")) {
      try {
        return JSON.parse(value);
      } catch {
        return Array.isArray(original)
          ? value.split(",").map(item => item.trim()).filter(Boolean)
          : value;
      }
    }
    if (typeof original === "number") return Number(value);
    if (typeof original === "boolean") return value === "true";
    return value;
  }

  function editedFieldMaps() {
    syncDraftCsvFromTable();
    const rows = parseCsv(document.getElementById("draftCsv").value || "");
    const headers = rows[0] || [];
    const values = rows[1] || [];
    const shared = {};
    const acf = {};
    headers.forEach((field, index) => {
      if (Object.prototype.hasOwnProperty.call(v2Session.shared_fields || {}, field)) {
        shared[field] = decodeEditedValue(values[index] || "", v2Session.shared_fields[field]);
      } else if (Object.prototype.hasOwnProperty.call(v2Session.acf_source_fields || {}, field)) {
        acf[field] = decodeEditedValue(values[index] || "", v2Session.acf_source_fields[field]);
      }
    });
    shared.status = document.getElementById("postStatus").value || shared.status || "draft";
    return {shared, acf};
  }

  createSession = async function createSession(options = {}) {
    saveKey();
    const selected = selectedPostTypeKey();
    if (!selected) throw new Error("Bitte zuerst einen Beitragstyp auswählen.");
    if (!options.preservePendingUploads) clearV2LocalMediaUi();
    const data = await v2Api("/api/content-sessions", {
      method: "POST",
      headers: v2Headers(),
      body: JSON.stringify({user_id: v2UserId(), post_type_key: selected}),
    });
    sessionId = data.session.session_id;
    sessionStorage.setItem("flairlab_session_id", sessionId);
    clearSessionRecoveryBanner();
    await renderV2(data.session, {statusText: "Session erstellt."});
    openPanel("panelUpload", true);
  };

  restoreSession = async function restoreSession() {
    if (!sessionId || !key()) return;
    try {
      const data = await v2Api(`/api/content-sessions/${sessionId}`, {
        headers: v2Headers(false),
      });
      await renderV2(data.session);
    } catch (error) {
      if (![403, 404].includes(error.status)) throw error;
      sessionStorage.removeItem("flairlab_session_id");
      sessionId = "";
      currentSessionData = null;
      await createSession();
      status("Eine nicht kompatible ältere Browser-Session wurde durch eine neue Session ersetzt.");
    }
  };

  saveUiCache = async function saveUiCache() {
    saveUiCacheLocal();
  };

  loadRecentSessions = async function loadRecentSessions() {
    if (!key()) throw new Error("Bitte zuerst API-Schlüssel eingeben.");
    const data = await v2Api(`/api/content-sessions/recent?${recentSessionsQueryString()}`, {
      headers: v2Headers(false),
    });
    renderRecentSessions(data);
  };

  deleteSelectedRecentSessions = async function deleteSelectedRecentSessions() {
    if (!key()) throw new Error("Bitte zuerst API-Schlüssel eingeben.");
    const sessionIds = [...recentSelectedSessionIds];
    if (!sessionIds.length) throw new Error("Bitte zuerst mindestens eine Session auswählen.");
    const data = await v2Api("/api/content-sessions/delete", {
      method: "POST",
      headers: v2Headers(),
      body: JSON.stringify({session_ids: sessionIds}),
    });
    if (sessionIds.includes(sessionId)) {
      sessionId = "";
      v2Session = null;
      currentSessionData = null;
      sessionStorage.removeItem("flairlab_session_id");
      document.getElementById("sessionSummary").textContent = "Keine aktive Session.";
    }
    recentSelectedSessionIds = new Set();
    await loadRecentSessions();
    status(`${Number(data.deleted || 0)} Session(s) gelöscht.`);
  };

  openSessionLogsById = async function openSessionLogsById(targetSessionId) {
    const id = String(targetSessionId || "").trim();
    if (!id) throw new Error("Session-ID fehlt.");
    const data = await v2Api(`/api/content-sessions/${encodeURIComponent(id)}`, {
      headers: v2Headers(false),
    });
    renderSessionLogsWindow(id, {
      session_state: data.session,
      v2_session: data.session,
      wordpress_import_logs: [],
    });
  };

  loadKnowledgeStatus = async function loadKnowledgeStatus() {
    if (!key()) {
      document.getElementById("knowledgeSummary").textContent =
        "Bitte zuerst den API-Schlüssel eingeben. Danach wird die aktive Database Datei geprüft.";
      document.getElementById("knowledgeActions").innerHTML = "";
      return;
    }
    const selected = selectedPostTypeKey();
    const suffix = selected ? `?post_type_key=${encodeURIComponent(selected)}` : "";
    const version = await v2Api(`/api/content-sessions/_workbook${suffix}`, {
      headers: v2Headers(false),
    });
    v2WorkbookStatus = version;
    renderPostTypeOptions(version);
    sessionStorage.setItem("flairlab_knowledge_status", JSON.stringify(version));
    const target = document.getElementById("knowledgeSummary");
    target.innerHTML =
      `<strong>Database Datei:</strong> ${esc(version.filename || "")}<br>` +
      `${version.selected_post_type_key ? `<strong>Beitragstyp:</strong> ${esc(version.selected_post_type_key)}<br>` : ""}` +
      `${version.storage_mode ? `<strong>Speicher:</strong> ${esc(version.storage_mode)}<br>` : ""}` +
      `${version.gcs_uri ? `<strong>GCS:</strong> ${esc(version.gcs_uri)}<br>` : ""}` +
      `<strong>SHA-256:</strong> ${esc(version.sha256 || "")}<br>` +
      `<strong>Validiert:</strong> ja`;
    document.getElementById("knowledgeActions").innerHTML = "";
  };

  uploadKnowledgeWorkbook = async function uploadKnowledgeWorkbook() {
    const file = document.getElementById("knowledgeWorkbook").files[0];
    if (!file) throw new Error("Bitte zuerst eine Database Datei auswählen.");
    const postTypeElement = document.getElementById("postType");
    const postType = (postTypeElement && postTypeElement.value) || "";
    const form = new FormData();
    form.append("workbook", file);
    if (postType) form.append("post_type", postType);
    const data = await api("/app/knowledge/workbook", {
      method: "POST",
      headers: {"X-API-Key": key()},
      body: form,
    });
    await v2Api("/api/content-sessions/_workbook/reload", {
      method: "POST",
      headers: v2Headers(false),
    });
    sessionStorage.removeItem("flairlab_knowledge_status");
    await loadKnowledgeStatus();
    status(data);
  };

  autoUploadSelectedImages = async function autoUploadSelectedImages() {
    const images = [...document.getElementById("images").files];
    if (!images.length) {
      updateButtons();
      return;
    }
    v2UploadQueue = v2UploadQueue.catch(() => {}).then(async () => {
      if (!sessionId) await createSession({preservePendingUploads: true});
      v2ImageUploadInFlight += images.length;
      markLocalImageCardsProcessing(images);
      status(`Bilder werden hochgeladen und ${imageUploadActionLabel()}...`);
      try {
        await uploadPendingMediaFiles();
      } finally {
        v2ImageUploadInFlight = Math.max(0, v2ImageUploadInFlight - images.length);
        if (v2Session) await renderV2(v2Session);
      }
    });
    await v2UploadQueue;
  };

  uploadPendingMediaFiles = async function uploadPendingMediaFiles() {
    const videos = [...document.getElementById("videos").files];
    if (videos.length) throw new Error("Video-Uploads sind im aktuellen Workflow nicht vorgesehen.");
    const images = [...document.getElementById("images").files];
    markLocalImageCardsProcessing(images);
    for (const [index, image] of images.entries()) {
      await uploadV2File(image, "image");
      await renderV2(v2Session, {
        statusText: `Bild ${index + 1}/${images.length} ist verarbeitet. Weitere Bilder laufen noch...`,
      });
      appendPendingV2ImageCards(images.slice(index + 1));
    }
    if (images.length) {
      await renderV2(v2Session, {
        statusText: `Bilder gespeichert und ${imageUploadActionLabel()}.`,
      });
      clearUploadInputs({images: true, videos: true});
      if (v2Session.state === "needs_review") {
        status("Bilder werden per Pillow verarbeitet und der Entwurf wird aktualisiert...");
        await saveDraft();
      }
    }
    return v2Session;
  };

  uploadFiles = async function uploadFiles() {
    if (!sessionId) await createSession({preservePendingUploads: true});
    const videos = [...document.getElementById("videos").files];
    if (videos.length) throw new Error("Video-Uploads sind im aktuellen Workflow nicht vorgesehen.");
    const voices = [...queuedRecordedVoiceFiles(), ...document.getElementById("voice").files];
    for (const voice of voices) await uploadV2File(voice, "audio");
    for (const image of [...document.getElementById("images").files]) {
      await uploadV2File(image, "image");
    }
    clearUploadInputs({voices: true, images: true, videos: true});
    clearQueuedRecordings();
    await renderV2(v2Session, {statusText: "Dateien gespeichert."});
    if (voices.length) {
      status("Sprachnachrichten gespeichert. Klicke „Sprache transkribieren“, wenn die Faktenanalyse starten soll.");
    } else if (v2Session.state === "needs_review" && document.getElementById("draftCsv").value.trim()) {
      status("Bilder werden per Pillow verarbeitet und der Entwurf wird aktualisiert...");
      await saveDraft();
    }
  };

  uploadRecordedVoiceAndRetranscribe = async function uploadRecordedVoiceAndRetranscribe() {
    const queuedVoices = queuedRecordedVoiceFiles();
    if (!queuedVoices.length) return;
    if (!key()) {
      showApiKeyModal();
      throw new Error("Vor dem Upload der Aufnahme ist ein API-Schlüssel erforderlich.");
    }
    if (!sessionId) await createSession({preservePendingUploads: true});
    else await loadActiveV2Session();
    for (const voice of queuedVoices) await uploadV2File(voice, "audio");
    clearQueuedRecordings();
    await renderV2(v2Session, {statusText: "Aufnahme gespeichert. Klicke „Sprache transkribieren“, wenn die Faktenanalyse starten soll."});
    openPanel("panelUpload");
  };

  startRecording = async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new Error("Dieser Browser unterstützt die Aufnahme in der App nicht.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.addEventListener("dataavailable", event => {
      if (event.data.size) recordedChunks.push(event.data);
    });
    mediaRecorder.addEventListener("stop", () => {
      stream.getTracks().forEach(track => track.stop());
      recordedVoiceBlob = new Blob(recordedChunks, {type: mediaRecorder.mimeType || "audio/webm"});
      recordedVoiceName = `recording-${new Date().toISOString().replace(/[:.]/g, "-")}.webm`;
      v2RecordedVoiceQueue.push(new File(
        [recordedVoiceBlob],
        recordedVoiceName,
        {type: recordedVoiceBlob.type || "audio/webm"}
      ));
      const playback = document.getElementById("recordingPlayback");
      playback.src = URL.createObjectURL(recordedVoiceBlob);
      playback.style.display = "block";
      document.body.classList.remove("is-recording");
      document.getElementById("startRecordingButton").disabled = false;
      document.getElementById("stopRecordingButton").disabled = true;
      status(`${v2RecordedVoiceQueue.length} Aufnahme(n) bereit. Klicke „Sprache transkribieren“, um sie hochzuladen und zu transkribieren.`);
      renderVoiceChoices();
      updateButtons();
    });
    mediaRecorder.start();
    document.body.classList.add("is-recording");
    document.getElementById("startRecordingButton").disabled = true;
    document.getElementById("stopRecordingButton").disabled = false;
  };

  stopRecording = function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      status("Aufnahme wird gespeichert...");
      mediaRecorder.stop();
    }
  };

  transcribeDraftChatVoice = async function transcribeDraftChatVoice() {
    if (!draftChatRecordedVoiceBlob) return;
    if (!key()) {
      showApiKeyModal();
      throw new Error("Vor der Transkription ist ein API-Schlüssel erforderlich.");
    }
    if (!sessionId) await createSession({preservePendingUploads: true});
    else await loadActiveV2Session();
    status("Sprachnachricht wird transkribiert...");
    const voice = new File(
      [draftChatRecordedVoiceBlob],
      draftChatRecordedVoiceName || "draft-chat-recording.webm",
      {type: draftChatRecordedVoiceBlob.type || "audio/webm"}
    );
    const form = new FormData();
    form.append("upload", voice);
    const transcriptData = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/draft-chat/transcribe`,
      {method: "POST", headers: v2Headers(false), body: form}
    );
    draftChatRecordedVoiceBlob = null;
    const transcribedText = (transcriptData && transcriptData.text) || "";
    if (transcribedText) {
      const inputField = document.getElementById("draftChatInput");
      inputField.value = inputField.value.trim()
        ? `${inputField.value.trim()} ${transcribedText}`
        : transcribedText;
      updateButtons();
      scheduleUiCacheSave();
      status("Sprachnachricht transkribiert und zur Nachricht hinzugefügt.");
    } else {
      status("Sprachnachricht transkribiert, aber kein Text erkannt.");
    }
  };

  transcribe = async function transcribe() {
    if (!v2Session && !sessionId) await createSession({preservePendingUploads: true});
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    const pendingVoices = [...queuedRecordedVoiceFiles(), ...document.getElementById("voice").files];
    if (pendingVoices.length) {
      for (const voice of pendingVoices) await uploadV2File(voice, "audio");
      clearUploadInputs({voices: true});
      clearQueuedRecordings();
      await renderV2(v2Session, {statusText: "Sprachnachrichten gespeichert. Transkription läuft..."});
    }
    await refreshV2Session();
    if (v2Session.state === "needs_input") {
      renderV2Clarifications(v2Session);
      status(
        "Der Workflow wartet auf bestätigte Fakten. Bitte im Abschnitt „Faktenprüfung“ prüfen und bestätigen."
      );
      return;
    }
    let data;
    try {
      data = await v2Api(
        `/api/content-sessions/${v2Session.session_id}/analyze`,
        {
          method: "POST",
          headers: v2Headers(),
          body: JSON.stringify({expected_version: v2Session.version}),
        }
      );
    } catch (error) {
      if (error.status !== 409) throw error;
      await refreshV2Session();
      if (v2Session && v2Session.state === "needs_review") {
        status("Transkription/Fakten wurden aktualisiert. Der bestehende Entwurf bleibt aktiv.");
        return;
      }
      if (v2Session && v2Session.state === "needs_input") {
        renderV2Clarifications(v2Session);
        status(
          "Der Workflow wartet auf bestätigte Fakten. Bitte im Abschnitt „Faktenprüfung“ prüfen und bestätigen."
        );
        return;
      }
      data = await v2Api(
        `/api/content-sessions/${v2Session.session_id}/analyze`,
        {
          method: "POST",
          headers: v2Headers(),
          body: JSON.stringify({expected_version: v2Session.version}),
        }
      );
    }
    await renderV2(data.session, {statusText: "Transkription und Faktenanalyse abgeschlossen."});
  };

  saveTranscript = async function saveTranscript() {
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/inputs`,
      {
        method: "POST",
        headers: v2Headers(),
        body: JSON.stringify({
          expected_version: v2Session.version,
          manual_text: document.getElementById("transcript").value,
          confirmed_facts: {},
        }),
      }
    );
    await renderV2(data.session, {statusText: "Transkript gespeichert."});
  };

  generateFactsFromTranscript = async function generateFactsFromTranscript() {
    if (!v2Session && !sessionId) await createSession({preservePendingUploads: true});
    if (!v2Session) await loadActiveV2Session();
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    if (!document.getElementById("transcript").value.trim()) {
      throw new Error("Bitte zuerst ein Transkript oder Testnotizen eintragen.");
    }
    await saveTranscript();
    status("Fakten werden aus dem gespeicherten Transkript generiert...");
    let data;
    try {
      data = await v2Api(
        `/api/content-sessions/${v2Session.session_id}/analyze`,
        {
          method: "POST",
          headers: v2Headers(),
          body: JSON.stringify({expected_version: v2Session.version}),
        }
      );
    } catch (error) {
      if (error.status !== 409) throw error;
      await refreshV2Session();
      data = {session: v2Session};
    }
    await renderV2(data.session, {
      statusText: "Fakten aus dem gespeicherten Transkript generiert. Bitte Tabelle prüfen.",
    });
    const panel = ensureClarificationPanel();
    panel.open = true;
    openPanel("panelTranscript", true);
  };

  generateDraft = async function generateDraft() {
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    if (!document.getElementById("transcript").value.trim()) {
      throw new Error("Bitte zuerst transkribieren oder Notizen eintragen.");
    }
    await saveTranscript();
    if (["created", "uploading", "analyzing"].includes(v2Session.state)) {
      const analyzed = await v2Api(
        `/api/content-sessions/${v2Session.session_id}/analyze`,
        {
          method: "POST",
          headers: v2Headers(),
          body: JSON.stringify({expected_version: v2Session.version}),
        }
      );
      v2Session = analyzed.session;
      await renderV2(v2Session);
    }
    if (v2Session.state === "needs_input") {
      renderV2Clarifications(v2Session);
      status(
        "Der Workflow benötigt bestätigte Fakten. Bitte im Abschnitt „Faktenprüfung“ prüfen und bestätigen."
      );
      return;
    }
    if (v2Session.state !== "ready_to_generate") {
      throw new Error(`Der Workflow kann aus dem Status „${v2Session.state}“ keinen neuen Entwurf starten.`);
    }
    const generated = await startV2SessionJob(
      `/api/content-sessions/${v2Session.session_id}/generate-job`,
      {
        expected_version: v2Session.version,
        shared_fields: {},
        acf_source_fields: {},
        selected_links: [],
        current_url: null,
        use_vision_for_image_metadata: useVisionOnUpload(),
      },
      "Entwurf wird im Hintergrund erstellt. Du kannst den Browser kurz verlassen; der Status wird beim Zurückkehren aktualisiert."
    );
    await renderV2(generated, {statusText: "Entwurf erstellt."});
    openPanel("panelDraft", true);
  };

  saveDraft = async function saveDraft() {
    if (!v2Session || !hasV2DraftReadyForWordPress()) {
      throw new Error("Bitte zuerst einen Entwurf erstellen.");
    }
    const {shared, acf} = editedFieldMaps();
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/draft-fields`,
      {
        method: "PUT",
        headers: v2Headers(),
        body: JSON.stringify({
          expected_version: v2Session.version,
          shared_fields: shared,
          acf_source_fields: acf,
        }),
      }
    );
    await renderV2(data.session, {statusText: "Bearbeitete Felder gespeichert."});
  };

  sendDraftChat = async function sendDraftChat() {
    await loadActiveV2Session();
    if (!v2Session || v2Session.state !== "needs_review") {
      throw new Error("Bitte zuerst einen Entwurf erstellen.");
    }
    const input = document.getElementById("draftChatInput");
    const message = input.value.trim();
    if (!message) throw new Error("Bitte eine Nachricht an den Entwurfs-Agenten schreiben.");
    await saveDraft();
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/draft-chat`,
      {
        method: "POST",
        headers: v2Headers(),
        body: JSON.stringify({
          expected_version: v2Session.version,
          shared_fields: {},
          acf_source_fields: {},
          selected_links: v2Session.selected_links || [],
          current_url: null,
          use_vision_for_image_metadata: useVisionOnUpload(),
          message,
        }),
      }
    );
    input.value = "";
    await renderV2(data.session, {statusText: "Entwurf wurde mit dem Agenten aktualisiert."});
    openPanel("panelDraft", true);
  };

  goToWordPressStep = async function goToWordPressStep() {
    await loadActiveV2Session();
    if (!v2Session || !hasV2DraftReadyForWordPress()) {
      throw new Error("Bitte zuerst einen Entwurf erstellen.");
    }
    openPanel("panelWordPress", true);
    status("Entwurf bereit. Vor dem WordPress-Schritt Änderungen mit „Entwurf speichern“ übernehmen.");
  };

  async function approveV2SessionIfNeeded() {
    if (v2Session.state !== "needs_review") return;
    const approved = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/approve`,
      {
        method: "POST",
        headers: v2Headers(),
        body: JSON.stringify({
          expected_version: v2Session.version,
          user_id: v2UserId(),
        }),
      }
    );
    v2Session = approved.session;
  }

  async function publishV2ToWordPress({
    targetPostId = null,
    forceCreateNew = false,
    statusText = "WordPress-Beitrag wird im Hintergrund verarbeitet. Bitte Seite möglichst offen lassen; bei Mobile-Sleep wird danach weiter gepollt.",
  } = {}) {
    if (!v2Session) await loadActiveV2Session();
    if (!v2Session || !hasV2DraftReadyForWordPress()) {
      throw new Error("Bitte zuerst einen Entwurf erstellen.");
    }
    const edits = editedFieldMaps();
    if (v2Session.state === "needs_review") {
      await saveDraft();
      await approveV2SessionIfNeeded();
    }
    const postIdPart = targetPostId ? `update-${targetPostId}` : "create";
    const modePart = forceCreateNew ? "new" : "idempotent";
    const published = await startV2SessionJob(
      `/api/content-sessions/${v2Session.session_id}/publish-job`,
      {
        expected_version: v2Session.version,
        idempotency_key: `${v2Session.session_id}-${postIdPart}-${modePart}-${Date.now()}`,
        target_post_id: targetPostId,
        force_create_new: forceCreateNew,
        shared_fields: edits.shared,
        acf_source_fields: edits.acf,
      },
      statusText
    );
    await renderV2(published, {statusText: "WordPress-Schritt abgeschlossen."});
    showResultModal(adaptSession(published).wordpress_post);
  }

  createWordPressPost = async function createWordPressPost() {
    await publishV2ToWordPress({
      forceCreateNew: true,
      statusText: "Neuer WordPress-Beitrag wird im Hintergrund erstellt. Bitte Seite möglichst offen lassen; bei Mobile-Sleep wird danach weiter gepollt.",
    });
  };

  updateExistingWordPressPost = async function updateExistingWordPressPost() {
    await loadActiveV2Session();
    const post = adaptSession(v2Session).wordpress_post || {};
    if (!post.post_id) throw new Error("Es gibt noch keinen zuvor erstellten WordPress-Beitrag in dieser Session.");
    await publishV2ToWordPress({
      targetPostId: Number(post.post_id),
      statusText: `Verknüpfter WordPress-Beitrag ${post.post_id} wird mit dem aktuellen Session-Inhalt aktualisiert.`,
    });
  };

  uploadWordPressMediaLibrary = async function uploadWordPressMediaLibrary() {
    throw new Error("Bilder werden zusammen mit dem freigegebenen Beitrag übertragen.");
  };

  const baseUpdateButtons = updateButtons;
  updateButtons = function updateButtons() {
    baseUpdateButtons();
    const hasSession = !!v2Session;
    const hasText = !!document.getElementById("transcript").value.trim();
    const hasDraft = hasV2DraftReadyForWordPress();
    const hasDraftMessage = !!document.getElementById("draftChatInput").value.trim();
    const hasPending = !!queuedRecordedVoiceFiles().length
      || !!document.getElementById("voice").files.length
      || !!document.getElementById("images").files.length
      || !!document.getElementById("videos").files.length;
    const hasPendingVoice = !!queuedRecordedVoiceFiles().length || !!document.getElementById("voice").files.length;
    document.getElementById("uploadButton").disabled = !hasSession || !hasPending;
    document.getElementById("transcribeButton").disabled =
      !hasSession || (!hasPendingVoice && !(v2Session.audio_refs || []).length);
    document.getElementById("saveTranscriptButton").disabled = !hasSession || !hasText;
    document.getElementById("generateFactsButton").disabled = !hasSession || !hasText;
    document.getElementById("generateDraftButton").disabled = !hasSession || !hasText;
    document.getElementById("transcriptNextButton").disabled = !hasSession || !hasText;
    document.getElementById("saveDraftButton").disabled = !hasDraft;
    document.getElementById("sendDraftChatButton").disabled = !hasDraft || !hasDraftMessage;
    document.getElementById("createPostButton").disabled = !hasDraft;
    document.getElementById("updatePostButton").disabled = !(v2Session?.wordpress_result?.edit_url);
    document.getElementById("uploadWpMediaButton").disabled = true;
  };

  const basePopulateImageCompareMetadataForm = populateImageCompareMetadataForm;
  populateImageCompareMetadataForm = function populateImageCompareMetadataForm(filename) {
    basePopulateImageCompareMetadataForm(filename);
    const target = document.getElementById("imageCompareVisionFeedback");
    if (!target) return;
    const warning = document.createElement("div");
    warning.style.marginTop = "10px";
    warning.style.padding = "10px";
    warning.style.border = "1px solid #f59e0b";
    warning.style.borderRadius = "8px";
    warning.style.background = "#fffbeb";
    warning.innerHTML = "<strong>Hinweis:</strong> Diese Bildmetadaten sind ein Zwischenstand. Sie werden nach Entwurfserstellung und vor der Veröffentlichung nochmals mit allen bestätigten Fakten und dem finalen Kontext verfeinert.";
    target.style.display = "block";
    target.appendChild(warning);
  };

  persistImageMetadata = async function persistImageMetadata(useSuggestions = false) {
    if (!v2Session) await loadActiveV2Session();
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    if (!currentCompareImageFilename) throw new Error("Kein Bild im Vergleichsfenster ausgewählt.");
    if (useSuggestions) {
      throw new Error("Automatische Legacy-Metadatenvorschläge sind durch die strukturierte Bildmetadaten-Generierung ersetzt.");
    }
    const metadata = {
      alt_text: document.getElementById("imageCompareAlt").value.trim(),
      title: document.getElementById("imageCompareMetaTitle").value.trim(),
      caption: document.getElementById("imageCompareCaption").value.trim(),
      description: document.getElementById("imageCompareDescription").value.trim(),
    };
    const data = await v2Api(
      `/api/content-sessions/${v2Session.session_id}/image-metadata`,
      {
        method: "PUT",
        headers: v2Headers(),
        body: JSON.stringify({
          expected_version: v2Session.version,
          filename: currentCompareImageFilename,
          metadata,
        }),
      }
    );
    await renderV2(data.session, {statusText: "Bildmetadaten gespeichert."});
    populateImageCompareMetadataForm(currentCompareImageFilename);
  };

  saveImageMetadata = async function saveImageMetadata() {
    await persistImageMetadata(false);
  };

  applyVisionMetadataFromCompare = async function applyVisionMetadataFromCompare() {
    await loadActiveV2Session("Bildanalyse und Metadaten wurden aus der Session aktualisiert.");
    if (currentCompareImageFilename) populateImageCompareMetadataForm(currentCompareImageFilename);
  };

  openImageOptimizationPrompt = function openImageOptimizationPrompt() {
    if (!currentCompareImageFilename) throw new Error("Kein Bild im Vergleichsfenster ausgewählt.");
    const wrap = document.getElementById("imageOptimizePromptWrap");
    const input = document.getElementById("imageOptimizePrompt");
    if (!wrap || !input) return;
    wrap.style.display = "block";
    if (!input.value.trim()) {
      input.value = "Halte das Hauptmotiv vollständig im Bild, verbessere die Schärfe am Motiv, reduziere Hintergrundablenkung und behalte natürliche Farben.";
    }
    setTimeout(() => input.focus(), 0);
  };

  sendImageOptimizationPrompt = async function sendImageOptimizationPrompt() {
    if (!v2Session) await loadActiveV2Session();
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    if (!currentCompareImageFilename) throw new Error("Kein Bild im Vergleichsfenster ausgewählt.");
    const promptInput = document.getElementById("imageOptimizePrompt");
    const prompt = (promptInput && promptInput.value ? promptInput.value : "").trim();
    if (!prompt) throw new Error("Bitte einen Prompt für die Bildoptimierung eingeben.");
    setImageCompareOptimizeLoading(true, "OpenAI Bildoptimierung läuft...");
    status("OpenAI Bildoptimierung läuft...");
    try {
      const data = await v2Api(
        `/api/content-sessions/${v2Session.session_id}/images/optimize`,
        {
          method: "POST",
          headers: v2Headers(),
          body: JSON.stringify({
            expected_version: v2Session.version,
            filename: currentCompareImageFilename,
            prompt,
          }),
        }
      );
      await renderV2(data.session, {statusText: "OpenAI Bildoptimierung abgeschlossen. Ergebnis ersetzt das Pillow-Bild."});
      const refreshedImage = await fetch(v2ImageUrl(currentCompareImageFilename), {headers: v2Headers(false)});
      if (refreshedImage.ok) {
        const blob = await refreshedImage.blob();
        const afterUrl = URL.createObjectURL(blob);
        const after = document.getElementById("imageCompareAfter");
        if (after) after.src = trackImageCompareUrl(afterUrl);
      }
      populateImageCompareMetadataForm(currentCompareImageFilename);
      closeImageOptimizationPrompt();
      updateButtons();
      scheduleUiCacheSave();
    } finally {
      setImageCompareOptimizeLoading(false);
    }
  };

  restoreComparedImageToOriginal = async function restoreComparedImageToOriginal() {
    if (!v2Session) await loadActiveV2Session();
    if (!v2Session) throw new Error("Bitte zuerst eine Session erstellen.");
    if (!currentCompareImageFilename) throw new Error("Kein Bild im Vergleichsfenster ausgewählt.");
    setImageCompareOptimizeLoading(true, "Originalbild wird wiederhergestellt...");
    status("Originalbild wird wiederhergestellt...");
    try {
      const data = await v2Api(
        `/api/content-sessions/${v2Session.session_id}/images/restore-original?filename=${encodeURIComponent(currentCompareImageFilename)}`,
        {
          method: "POST",
          headers: v2Headers(),
          body: JSON.stringify({expected_version: v2Session.version}),
        }
      );
      await renderV2(data.session, {statusText: "Bearbeitetes Bild wurde verworfen. Das Original ist wiederhergestellt."});
      const refreshedImage = await fetch(v2ImageUrl(currentCompareImageFilename), {headers: v2Headers(false)});
      if (refreshedImage.ok) {
        const blob = await refreshedImage.blob();
        const afterUrl = URL.createObjectURL(blob);
        const after = document.getElementById("imageCompareAfter");
        if (after) after.src = trackImageCompareUrl(afterUrl);
      }
      populateImageCompareMetadataForm(currentCompareImageFilename);
      updateButtons();
      scheduleUiCacheSave();
    } finally {
      setImageCompareOptimizeLoading(false);
    }
  };

  document.querySelector("header p").textContent =
    "WordPress-Beiträge mit KI-Inhalten und Single-Post Vorlagen.";
  document.getElementById("generateDraftButton").textContent = "Entwurf erstellen";
  document.getElementById("transcriptNextButton").textContent = "Weiter: Entwurf erstellen";
  document.getElementById("sendDraftChatButton").title =
    "Sprachnachrichten können transkribiert werden; der Agent kann den Entwurf strukturiert überarbeiten.";
  document.getElementById("postType").addEventListener("change", renderVoiceInstructionsForSelectedPostType);
  document.getElementById("uploadKnowledgeButton").disabled = false;
  document.getElementById("uploadKnowledgeButton").title =
    "Neue Database Datei hochladen, validieren und für neue Sessions aktivieren.";
  document.getElementById("videos").disabled = true;
  document.getElementById("videos").title =
    "Video ist nicht Teil des aktuellen Content Workflows.";
  for (const id of [
    "uploadWpMediaButton",
  ]) {
    const control = document.getElementById(id);
    if (control) control.disabled = true;
  }
  for (const id of [
    "v2ConfirmFactsButton",
    "createPostButton",
    "saveDraftButton",
  ]) {
    const control = document.getElementById(id);
    if (control) control.dataset.pipeline = "v2";
  }
  ensureClarificationPanel().style.display = "none";

  initializeApp().catch(error => {
    console.error(error);
    showErrorModal(error);
    status("Fehler: " + readableError(error));
  });
})();
