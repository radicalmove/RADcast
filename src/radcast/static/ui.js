const projectGatewayNode = document.getElementById("project-gateway");
const workspaceNode = document.getElementById("workspace");
const switchProjectBtn = document.getElementById("switch-project-btn");
const shareProjectBtn = document.getElementById("share-project-btn");
const activeProjectChip = document.getElementById("active-project-chip");
const activeProjectLabelNode = document.getElementById("active-project-label");

const existingProjectSelectNode = document.getElementById("existing-project-select");
const recentProjectListNode = document.getElementById("recent-project-list");
const refreshProjectsBtn = document.getElementById("refresh-projects-btn");
const projectGatewayStatusNode = document.getElementById("project-gateway-status");

const audioDropzoneNode = document.getElementById("audio-dropzone");
const audioFileInputNode = document.getElementById("input-audio-file");
const audioDropzoneTitleNode = document.getElementById("audio-dropzone-title");
const audioFileNameNode = document.getElementById("audio-file-name");
const savedSourceAudioSelectNode = document.getElementById("saved-source-audio-select");
const refreshSourceAudioBtn = document.getElementById("refresh-source-audio-btn");
const savedSourceAudioStatusNode = document.getElementById("saved-source-audio-status");
const sourcePreviewLabelNode = document.getElementById("source-preview-label");
const sourceAudioPreviewNode = document.getElementById("source-audio-preview");

const outputFormatNode = document.getElementById("output-format");
const enhancementModelNode = document.getElementById("enhancement-model");
const enhancementModelStatusNode = document.getElementById("enhancement-model-status");
const reduceSilenceEnabledNode = document.getElementById("reduce-silence-enabled");
const reduceSilenceSecondsNode = document.getElementById("reduce-silence-seconds");
const reduceSilenceValueNode = document.getElementById("reduce-silence-value");
const removeFillerWordsNode = document.getElementById("remove-filler-words");
const speechCleanupStatusNode = document.getElementById("speech-cleanup-status");

const workerStatusPillNode = document.getElementById("worker-status-pill");
const workerStatusDetailNode = document.getElementById("worker-status-detail");
const workerRefreshBtn = document.getElementById("worker-refresh-btn");
const workerSetupBtn = document.getElementById("worker-setup-btn");
const workerSetupLinksNode = document.getElementById("worker-setup-links");
const workerSetupWindowsLinkNode = document.getElementById("worker-setup-windows-link");
const workerSetupMacosLinkNode = document.getElementById("worker-setup-macos-link");
const workerCopyMacosBtn = document.getElementById("worker-copy-macos-btn");
const workerCopyLinuxBtn = document.getElementById("worker-copy-linux-btn");
const workerSetupModalNode = document.getElementById("worker-setup-modal");
const workerSetupCloseBtn = document.getElementById("worker-setup-close-btn");
const workerSetupModalStatusNode = document.getElementById("worker-setup-modal-status");

const generateBtn = document.getElementById("generate-btn");
const cancelBtn = document.getElementById("cancel-btn");
const generateStatusNode = document.getElementById("generate-status");

const progressWrapNode = document.getElementById("progress-wrap");
const progressStageNode = document.getElementById("progress-stage");
const progressComputeNode = document.getElementById("progress-compute");
const progressEtaNode = document.getElementById("progress-eta");
const progressPercentNode = document.getElementById("progress-percent");
const progressFillNode = document.getElementById("progress-fill");
const progressDetailNode = document.getElementById("progress-detail");

const outputListNode = document.getElementById("output-list");

const stageLabels = {
  queued: "Queued",
  queued_remote: "Waiting for helper",
  worker_running: "Helper device processing",
  fallback_local: "Switching to server",
  prepare: "Preparing audio",
  enhance: "Improving audio",
  cleanup: "Cleaning speech",
  finalize: "Saving audio",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const state = {
  activeProjectRef: null,
  activeProjectLabel: null,
  selectedAudioFile: null,
  selectedAudioHash: null,
  projectSettings: null,
  projectSettingsSaveTimer: null,
  sourceAudioSamples: [],
  activeJobId: null,
  pollTimer: null,
  progressAnimator: null,
  currentStage: "queued",
  actualProgress: 0,
  displayProgress: 0,
  latestDetail: "Preparing enhancement...",
  jobStartedAtMs: null,
  etaSeconds: null,
  etaUpdatedAtMs: null,
  etaStage: null,
  canManageActiveProject: false,
  computeMode: "server",
  expectedRemoteWorker: false,
  workerFallbackTimeoutSeconds: 0,
  workerLiveCount: null,
  workerRegisteredCount: null,
  workerStaleCount: null,
  workerLastLiveSeenAt: null,
  workerOnlineCount: null,
  workerTotalCount: null,
  workerOnlineWindowSeconds: null,
  workerStatusPollTimer: null,
  workerSetupLinuxCommand: "",
  workerSetupMacosCommand: "",
  workerSetupWindowsUrl: "",
  workerSetupMacosUrl: "",
  sourcePreviewObjectUrl: null,
  jobPollErrorCount: 0,
  enhancementModels: [],
  speechCleanupAvailable: true,
  speechCleanupDetail: "",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function cleanOptional(value) {
  const trimmed = (value ?? "").trim();
  return trimmed.length ? trimmed : null;
}

function clampSilenceSeconds(value) {
  const numeric = Number(value ?? 1);
  if (!Number.isFinite(numeric)) return 1;
  return Math.max(0, Math.min(4, numeric));
}

function defaultProjectSettings() {
  return {
    selected_audio_hash: null,
    output_format: "mp3",
    enhancement_model: "resemble",
    reduce_silence_enabled: false,
    max_silence_seconds: 1,
    remove_filler_words: false,
  };
}

function normalizeProjectSettings(payload) {
  const data = payload && typeof payload === "object" ? payload : {};
  const outputFormat = cleanOptional(data.output_format);
  const enhancementModel = cleanOptional(data.enhancement_model);
  const selectedAudioHash = cleanOptional(data.selected_audio_hash);

  return {
    selected_audio_hash: selectedAudioHash && selectedAudioHash.length >= 16 ? selectedAudioHash : null,
    output_format: outputFormat === "wav" ? "wav" : "mp3",
    enhancement_model: enhancementModel || "resemble",
    reduce_silence_enabled: Boolean(data.reduce_silence_enabled),
    max_silence_seconds: clampSilenceSeconds(data.max_silence_seconds),
    remove_filler_words: Boolean(data.remove_filler_words),
  };
}

function applyProjectSettingsToControls(settings) {
  const normalized = normalizeProjectSettings(settings);
  state.projectSettings = normalized;

  if (outputFormatNode) {
    outputFormatNode.value = normalized.output_format;
  }
  if (enhancementModelNode) {
    const desiredOption = Array.from(enhancementModelNode.options).find((option) => {
      return option.value === normalized.enhancement_model && !option.disabled;
    });
    if (desiredOption) {
      enhancementModelNode.value = desiredOption.value;
    }
  }
  if (reduceSilenceEnabledNode) {
    reduceSilenceEnabledNode.checked = normalized.reduce_silence_enabled;
  }
  if (reduceSilenceSecondsNode) {
    reduceSilenceSecondsNode.value = String(normalized.max_silence_seconds);
  }
  if (removeFillerWordsNode) {
    removeFillerWordsNode.checked = normalized.remove_filler_words;
  }

  updateEnhancementModelStatusFromSelection();
  updateSpeechCleanupControls();
  updateSpeechCleanupStatusFromSelection();
}

function resetProjectSettingsControls() {
  applyProjectSettingsToControls(defaultProjectSettings());
}

function currentProjectSettingsPayload() {
  return normalizeProjectSettings({
    selected_audio_hash: state.selectedAudioHash,
    output_format: cleanOptional(outputFormatNode?.value) || "mp3",
    enhancement_model: selectedEnhancementModelId(),
    reduce_silence_enabled: Boolean(reduceSilenceEnabledNode?.checked),
    max_silence_seconds: reduceSilenceSecondsNode?.value ?? 1,
    remove_filler_words: Boolean(removeFillerWordsNode?.checked),
  });
}

function clearProjectSettingsSaveTimer() {
  if (state.projectSettingsSaveTimer) {
    clearTimeout(state.projectSettingsSaveTimer);
    state.projectSettingsSaveTimer = null;
  }
}

async function saveProjectSettings(projectRef, settings) {
  if (!projectRef) return;
  const normalized = normalizeProjectSettings(settings);
  try {
    const data = await requestJSON(`/projects/${encodeURIComponent(projectRef)}/settings`, "PUT", normalized);
    if (state.activeProjectRef === projectRef) {
      state.projectSettings = normalizeProjectSettings(data?.settings);
    }
  } catch (err) {
    console.warn("Could not save project settings", err);
  }
}

function queueProjectSettingsSave() {
  const projectRef = state.activeProjectRef;
  if (!projectRef) return;

  const settings = currentProjectSettingsPayload();
  state.projectSettings = settings;
  clearProjectSettingsSaveTimer();
  state.projectSettingsSaveTimer = setTimeout(() => {
    state.projectSettingsSaveTimer = null;
    void saveProjectSettings(projectRef, settings);
  }, 250);
}

async function loadProjectSettings(projectRef) {
  if (!projectRef) return defaultProjectSettings();
  try {
    const data = await requestJSON(`/projects/${encodeURIComponent(projectRef)}/settings`, "GET");
    return normalizeProjectSettings(data?.settings);
  } catch (err) {
    console.warn("Could not load project settings", err);
    return defaultProjectSettings();
  }
}

async function restoreProjectSettings(projectRef) {
  resetProjectSettingsControls();
  const settings = await loadProjectSettings(projectRef);
  if (state.activeProjectRef !== projectRef) return;

  applyProjectSettingsToControls(settings);
  await loadSourceAudioSamples(settings.selected_audio_hash);
  if (state.activeProjectRef !== projectRef) return;
  state.projectSettings = currentProjectSettingsPayload();
}

function setGatewayStatus(message, isError = false) {
  if (!projectGatewayStatusNode) return;
  projectGatewayStatusNode.textContent = message || "";
  projectGatewayStatusNode.style.color = isError ? "#a73527" : "#555";
}

function setGenerateStatus(message, isError = false) {
  if (!generateStatusNode) return;
  generateStatusNode.textContent = message || "";
  generateStatusNode.style.color = isError ? "#a73527" : "#444";
}

function setSavedSourceAudioStatus(message, isError = false) {
  if (!savedSourceAudioStatusNode) return;
  savedSourceAudioStatusNode.textContent = message || "";
  savedSourceAudioStatusNode.style.color = isError ? "#a73527" : "#555";
}

function setEnhancementModelStatus(message, isError = false) {
  if (!enhancementModelStatusNode) return;
  enhancementModelStatusNode.textContent = message || "";
  enhancementModelStatusNode.style.color = isError ? "#a73527" : "#555";
}

function setSpeechCleanupStatus(message, isError = false) {
  if (!speechCleanupStatusNode) return;
  speechCleanupStatusNode.textContent = message || "";
  speechCleanupStatusNode.style.color = isError ? "#a73527" : "#555";
}

function setWorkerStatus(connected, detailText = "") {
  if (workerStatusPillNode) {
    workerStatusPillNode.classList.remove("worker-pill-online", "worker-pill-offline", "worker-pill-unknown");
    if (connected === true) {
      workerStatusPillNode.classList.add("worker-pill-online");
      workerStatusPillNode.textContent = "Helper status: connected";
    } else if (connected === false) {
      workerStatusPillNode.classList.add("worker-pill-offline");
      workerStatusPillNode.textContent = "Helper status: not connected";
    } else {
      workerStatusPillNode.classList.add("worker-pill-unknown");
      workerStatusPillNode.textContent = "Helper status: checking";
    }
  }
  if (workerStatusDetailNode) {
    workerStatusDetailNode.textContent = detailText || "";
  }
}

function setWorkerSetupStatus(message, isError = false) {
  if (!workerSetupModalStatusNode) return;
  workerSetupModalStatusNode.textContent = message || "";
  workerSetupModalStatusNode.style.color = isError ? "#a73527" : "#555";
}

function workerAvailabilitySummary() {
  if (!Number.isFinite(state.workerLiveCount)) return "checking helper availability";
  const live = Math.max(0, Number(state.workerLiveCount));
  const stale = Number.isFinite(state.workerStaleCount) ? Math.max(0, Number(state.workerStaleCount)) : 0;
  const parts = [`${live} live helper device${live === 1 ? "" : "s"}`];
  if (stale > 0) parts.push(`${stale} stale registration${stale === 1 ? "" : "s"}`);
  if (state.workerLastLiveSeenAt) {
    parts.push(`last live helper seen ${new Date(state.workerLastLiveSeenAt).toLocaleTimeString()}`);
  }
  return parts.join(", ");
}

function openWorkerSetupModal() {
  if (!workerSetupModalNode) return;
  workerSetupModalNode.hidden = false;
  document.body.classList.add("modal-open");
}

function closeWorkerSetupModal() {
  if (!workerSetupModalNode) return;
  workerSetupModalNode.hidden = true;
  document.body.classList.remove("modal-open");
}

function formatDurationSeconds(seconds) {
  const totalSeconds = Math.max(0, Math.round(Number(seconds || 0)));
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function formatDisplayDateTime(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";

  let formatted = new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(parsed);

  formatted = formatted.replace(",", "");
  formatted = formatted.replace(/\s+([AP]M)$/i, (_, meridiem) => meridiem.toLowerCase());
  formatted = formatted.replace(/(\d)\s([ap]m)$/i, "$1$2");
  return formatted;
}

function formatOutputDate(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(parsed);
}

function formatOutputTime(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  let formatted = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(parsed);
  formatted = formatted.replace(/\s+([AP]M)$/i, (_, meridiem) => meridiem.toLowerCase());
  formatted = formatted.replace(/(\d)\s([ap]m)$/i, "$1$2");
  return formatted;
}

function selectedEnhancementModelId() {
  return cleanOptional(enhancementModelNode?.value) || "resemble";
}

function formatSilenceThresholdLabel(value) {
  const numeric = Number(value || 0);
  const safe = Number.isFinite(numeric) ? Math.max(0, Math.min(4, numeric)) : 0;
  return safe === 0 ? "0s" : `${safe.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1")}s`;
}

function selectedMaxSilenceSeconds() {
  if (!reduceSilenceEnabledNode?.checked || !state.speechCleanupAvailable) return null;
  const numeric = Number(reduceSilenceSecondsNode?.value ?? 1);
  if (!Number.isFinite(numeric)) return null;
  return Math.max(0, Math.min(4, numeric));
}

function updateSpeechCleanupControls() {
  const available = Boolean(state.speechCleanupAvailable);
  if (reduceSilenceSecondsNode) {
    reduceSilenceSecondsNode.disabled = !available || !reduceSilenceEnabledNode?.checked;
  }
  if (reduceSilenceEnabledNode) {
    reduceSilenceEnabledNode.disabled = !available;
  }
  if (removeFillerWordsNode) {
    removeFillerWordsNode.disabled = !available;
  }
  if (reduceSilenceValueNode) {
    reduceSilenceValueNode.textContent = formatSilenceThresholdLabel(reduceSilenceSecondsNode?.value ?? 1);
  }
  const cleanupBlock = reduceSilenceEnabledNode?.closest(".speech-cleanup-block");
  if (cleanupBlock) {
    cleanupBlock.classList.toggle("speech-cleanup-disabled", !available);
  }
  const fillerBlock = removeFillerWordsNode?.closest(".simple-check");
  if (fillerBlock) {
    fillerBlock.classList.toggle("speech-cleanup-disabled", !available);
  }
}

function updateSpeechCleanupStatusFromSelection() {
  if (!state.speechCleanupAvailable) {
    setSpeechCleanupStatus(state.speechCleanupDetail || "Speech cleanup is not available on this machine.", true);
    return;
  }
  const parts = [];
  const maxSilenceSeconds = selectedMaxSilenceSeconds();
  if (maxSilenceSeconds !== null) {
    parts.push(`Speech gaps over ${formatSilenceThresholdLabel(maxSilenceSeconds)} will be shortened.`);
  }
  if (removeFillerWordsNode?.checked) {
    parts.push("Clear standalone filler words will be removed conservatively.");
  }
  if (!parts.length) {
    parts.push(state.speechCleanupDetail || "Conservative cleanup of clear filler words between phrases.");
  } else {
    parts.push("This runs after enhancement, so the final save can take a little longer.");
  }
  setSpeechCleanupStatus(parts.join(" "));
}

function enhancementModelById(modelId) {
  return state.enhancementModels.find((item) => item && item.id === modelId) || null;
}

function updateEnhancementModelStatusFromSelection() {
  const item = enhancementModelById(selectedEnhancementModelId());
  if (!item) {
    setEnhancementModelStatus("Choose the enhancement backend to use.");
    return;
  }
  const parts = [String(item.description || "").trim(), String(item.detail || "").trim()].filter(Boolean);
  setEnhancementModelStatus(parts.join(" "));
}

async function loadEnhancementModels() {
  if (!enhancementModelNode) return;
  enhancementModelNode.disabled = true;
  enhancementModelNode.innerHTML = '<option value="resemble">Loading models...</option>';
  setEnhancementModelStatus("Checking available enhancement models...");
  setSpeechCleanupStatus("Checking speech cleanup availability...");

  try {
    const data = await requestJSON("/enhancement/models", "GET");
    const models = Array.isArray(data.models) ? data.models : [];
    state.enhancementModels = models;
    const speechCleanup = data.speech_cleanup && typeof data.speech_cleanup === "object" ? data.speech_cleanup : {};
    state.speechCleanupAvailable = speechCleanup.available !== false;
    state.speechCleanupDetail = String(speechCleanup.detail || "").trim();

    enhancementModelNode.innerHTML = "";
    for (const item of models) {
      const option = document.createElement("option");
      option.value = String(item.id || "");
      const unavailable = item.available === false ? " (not available)" : "";
      const experimental = item.experimental ? " [experimental]" : "";
      option.textContent = `${String(item.label || item.id || "model")}${experimental}${unavailable}`;
      option.disabled = item.available === false;
      enhancementModelNode.appendChild(option);
    }

    const preferred = String(data.default_model || "resemble");
    const availablePreferred = enhancementModelById(preferred);
    if (availablePreferred && availablePreferred.available !== false) {
      enhancementModelNode.value = preferred;
    } else {
      const firstEnabled = Array.from(enhancementModelNode.options).find((option) => !option.disabled);
      if (firstEnabled) enhancementModelNode.value = firstEnabled.value;
    }
    if (state.projectSettings) {
      const desiredModel = normalizeProjectSettings(state.projectSettings).enhancement_model;
      const desiredOption = Array.from(enhancementModelNode.options).find((option) => {
        return option.value === desiredModel && !option.disabled;
      });
      if (desiredOption) {
        enhancementModelNode.value = desiredOption.value;
      }
    }
    updateEnhancementModelStatusFromSelection();
    updateSpeechCleanupControls();
    updateSpeechCleanupStatusFromSelection();
  } catch (err) {
    enhancementModelNode.innerHTML = '<option value="resemble">Resemble Enhance</option>';
    state.enhancementModels = [
      {
        id: "resemble",
        label: "Resemble Enhance",
        description: "Fallback option when model discovery fails.",
        detail: "",
        available: true,
      },
    ];
    state.speechCleanupAvailable = false;
    state.speechCleanupDetail = `Could not load speech cleanup availability: ${String(err)}`;
    setEnhancementModelStatus(`Could not load enhancement models: ${String(err)}`, true);
    updateSpeechCleanupControls();
    updateSpeechCleanupStatusFromSelection();
  } finally {
    enhancementModelNode.disabled = false;
  }
}

function formatSavedSourceAudioLabel(sample) {
  const name = sample.source_filename || "audio";
  const duration = Number(sample.duration_seconds || 0);
  const durationLabel = Number.isFinite(duration) && duration > 0 ? ` (${formatDurationSeconds(duration)})` : "";
  const updated = sample.updated_at ? new Date(sample.updated_at).toLocaleString() : "Saved";
  return `${name}${durationLabel} - ${updated}`;
}

function clearSourcePreview() {
  if (state.sourcePreviewObjectUrl) {
    URL.revokeObjectURL(state.sourcePreviewObjectUrl);
    state.sourcePreviewObjectUrl = null;
  }
  if (sourceAudioPreviewNode) {
    sourceAudioPreviewNode.pause();
    sourceAudioPreviewNode.removeAttribute("src");
    sourceAudioPreviewNode.hidden = true;
    sourceAudioPreviewNode.load();
  }
  if (sourcePreviewLabelNode) sourcePreviewLabelNode.hidden = true;
}

function setSourcePreviewUrl(url) {
  if (!sourceAudioPreviewNode || !url) {
    clearSourcePreview();
    return;
  }
  sourceAudioPreviewNode.pause();
  sourceAudioPreviewNode.src = url;
  sourceAudioPreviewNode.hidden = false;
  if (sourcePreviewLabelNode) sourcePreviewLabelNode.hidden = false;
}

function setSourcePreviewFile(file) {
  clearSourcePreview();
  if (!file) return;
  state.sourcePreviewObjectUrl = URL.createObjectURL(file);
  setSourcePreviewUrl(state.sourcePreviewObjectUrl);
}

function resetAudioSelection() {
  state.selectedAudioFile = null;
  state.selectedAudioHash = null;
  clearSourcePreview();
  if (audioFileInputNode) audioFileInputNode.value = "";
  if (savedSourceAudioSelectNode) savedSourceAudioSelectNode.value = "";
  if (audioDropzoneTitleNode) audioDropzoneTitleNode.textContent = "Drop audio here or click to choose";
  if (audioFileNameNode) audioFileNameNode.textContent = "No file selected.";
}

function markWorkspaceReady(projectRef, projectLabel) {
  clearProjectSettingsSaveTimer();
  state.activeProjectRef = projectRef;
  state.activeProjectLabel = projectLabel;

  if (projectGatewayNode) projectGatewayNode.hidden = true;
  if (workspaceNode) workspaceNode.classList.remove("workspace-hidden");
  if (switchProjectBtn) switchProjectBtn.hidden = false;
  if (shareProjectBtn) shareProjectBtn.hidden = false;

  if (activeProjectChip) activeProjectChip.hidden = false;
  if (activeProjectLabelNode) activeProjectLabelNode.textContent = projectLabel;

  resetAudioSelection();
  resetProjectSettingsControls();
  setGenerateStatus("Upload an audio file, then click Enhance audio.");
  refreshProjectAccessInfo();
  void restoreProjectSettings(projectRef);
  loadOutputs();
  void fetchWorkerStatus();
  startWorkerStatusPolling();
}

function showProjectGateway() {
  clearProjectSettingsSaveTimer();
  state.activeProjectRef = null;
  state.activeProjectLabel = null;
  state.canManageActiveProject = false;
  state.projectSettings = defaultProjectSettings();

  if (workspaceNode) workspaceNode.classList.add("workspace-hidden");
  if (projectGatewayNode) projectGatewayNode.hidden = false;
  if (switchProjectBtn) switchProjectBtn.hidden = true;
  if (shareProjectBtn) shareProjectBtn.hidden = true;
  if (activeProjectChip) activeProjectChip.hidden = true;

  resetRunningState({ clearProgress: true });
  stopWorkerStatusPolling();
}

async function requestJSON(url, method = "GET", body = undefined) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });

  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return data;
}

function stopWorkerStatusPolling() {
  if (state.workerStatusPollTimer) {
    clearInterval(state.workerStatusPollTimer);
    state.workerStatusPollTimer = null;
  }
}

function startWorkerStatusPolling() {
  stopWorkerStatusPolling();
  state.workerStatusPollTimer = setInterval(() => {
    void fetchWorkerStatus();
  }, 15000);
}

async function fetchWorkerStatus() {
  if (workerRefreshBtn) workerRefreshBtn.disabled = true;
  try {
    const data = await requestJSON("/workers/status", "GET");
    const online = Math.max(0, Number(data.worker_online_count || 0));
    const total = Math.max(0, Number(data.worker_total_count || 0));
    const live = Math.max(0, Number(data.worker_live_count || online));
    const registered = Math.max(live, Number(data.worker_registered_count || total));
    const stale = Math.max(0, Number(data.worker_stale_count || Math.max(0, registered - live)));
    const lastSeenAt = String(data.worker_last_live_seen_at || "").trim() || null;
    state.workerLiveCount = live;
    state.workerRegisteredCount = registered;
    state.workerStaleCount = stale;
    state.workerLastLiveSeenAt = lastSeenAt;
    state.workerOnlineCount = online;
    state.workerTotalCount = total;
    state.workerOnlineWindowSeconds = Math.max(0, Number(data.worker_online_window_seconds || 0));
    setWorkerStatus(live > 0, workerAvailabilitySummary());
    if (workerSetupBtn) workerSetupBtn.hidden = false;
  } catch (err) {
    setWorkerStatus(null, `Could not check helper status: ${String(err)}`);
    if (workerSetupBtn) workerSetupBtn.hidden = false;
  } finally {
    if (workerRefreshBtn) workerRefreshBtn.disabled = false;
  }
}

async function fetchWorkerSetupOptions() {
  openWorkerSetupModal();
  setWorkerSetupStatus("Preparing setup options...");
  if (workerSetupLinksNode) workerSetupLinksNode.hidden = true;
  if (workerSetupBtn) workerSetupBtn.disabled = true;
  try {
    const data = await requestJSON("/workers/invite", "POST", { capabilities: ["enhance"] });
    state.workerSetupWindowsUrl = String(data.windows_installer_url || "").trim();
    state.workerSetupMacosUrl = String(data.macos_installer_url || "").trim();
    state.workerSetupMacosCommand = String(data.install_command_macos || data.install_command || "").trim();
    state.workerSetupLinuxCommand = String(data.install_command_linux || data.install_command || "").trim();
    if (workerSetupWindowsLinkNode && state.workerSetupWindowsUrl) workerSetupWindowsLinkNode.href = state.workerSetupWindowsUrl;
    if (workerSetupMacosLinkNode && state.workerSetupMacosUrl) workerSetupMacosLinkNode.href = state.workerSetupMacosUrl;
    if (workerSetupLinksNode) workerSetupLinksNode.hidden = false;
    setWorkerSetupStatus("Helper setup options are ready.");
  } catch (err) {
    setWorkerSetupStatus(`Could not prepare helper setup: ${String(err)}`, true);
  } finally {
    if (workerSetupBtn) workerSetupBtn.disabled = false;
  }
}

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const marker = "base64,";
      const idx = result.indexOf(marker);
      if (idx === -1) {
        reject(new Error("Could not read selected file."));
        return;
      }
      resolve(result.slice(idx + marker.length));
    };
    reader.onerror = () => reject(reader.error || new Error("Failed to read file."));
    reader.readAsDataURL(file);
  });
}

function updateAudioSelection(file) {
  state.selectedAudioFile = file || null;
  state.selectedAudioHash = null;
  if (savedSourceAudioSelectNode) {
    savedSourceAudioSelectNode.value = "";
  }
  setSourcePreviewFile(file || null);
  if (!file) {
    if (audioDropzoneTitleNode) audioDropzoneTitleNode.textContent = "Drop audio here or click to choose";
    if (audioFileNameNode) audioFileNameNode.textContent = "No file selected.";
    return;
  }

  if (audioDropzoneTitleNode) {
    audioDropzoneTitleNode.textContent = `Selected: ${file.name}`;
  }
  if (audioFileNameNode) {
    const mb = (file.size / (1024 * 1024)).toFixed(2);
    audioFileNameNode.textContent = `${file.name} (${mb} MB)`;
  }
}

function findSavedSourceAudioByHash(audioHash) {
  if (!audioHash) return null;
  for (const sample of state.sourceAudioSamples) {
    if (sample && sample.audio_hash === audioHash) {
      return sample;
    }
  }
  return null;
}

function applySavedSourceAudioSelection(audioHash) {
  const sample = findSavedSourceAudioByHash(audioHash);
  if (!sample) {
    setSavedSourceAudioStatus("Saved audio file not found. Refresh and try again.", true);
    return;
  }

  state.selectedAudioFile = null;
  state.selectedAudioHash = sample.audio_hash;
  if (audioFileInputNode) {
    audioFileInputNode.value = "";
  }
  if (audioDropzoneTitleNode) {
    audioDropzoneTitleNode.textContent = "Saved project audio selected";
  }
  setSourcePreviewUrl(String(sample.artifact_url || ""));
  if (audioFileNameNode) {
    const stamped = sample.updated_at ? new Date(sample.updated_at).toLocaleString() : "Saved in project";
    const duration = Number(sample.duration_seconds || 0);
    const durationHint = Number.isFinite(duration) && duration > 0 ? `, ${formatDurationSeconds(duration)}` : "";
    audioFileNameNode.textContent = `${sample.source_filename || "saved-audio"} (${stamped}${durationHint})`;
  }
  setSavedSourceAudioStatus(`Using saved project audio: ${sample.source_filename || sample.audio_hash.slice(0, 8)}.`);
}

async function loadSourceAudioSamples(preferredHash = null) {
  const projectId = state.activeProjectRef;
  if (!projectId || !savedSourceAudioSelectNode) return;

  savedSourceAudioSelectNode.innerHTML = '<option value="">Loading saved audio files...</option>';
  savedSourceAudioSelectNode.disabled = true;
  if (refreshSourceAudioBtn) refreshSourceAudioBtn.disabled = true;
  setSavedSourceAudioStatus("Loading saved audio files...");

  try {
    const data = await requestJSON(`/projects/${encodeURIComponent(projectId)}/source-audio`, "GET");
    const samples = Array.isArray(data.samples) ? data.samples : [];
    state.sourceAudioSamples = samples;

    savedSourceAudioSelectNode.innerHTML = "";
    if (!samples.length) {
      savedSourceAudioSelectNode.innerHTML = '<option value="">No saved audio files yet</option>';
      savedSourceAudioSelectNode.value = "";
      setSavedSourceAudioStatus("No saved audio files in this project yet.");
      return;
    }

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Choose saved project audio";
    savedSourceAudioSelectNode.appendChild(placeholder);

    for (const sample of samples) {
      const option = document.createElement("option");
      option.value = String(sample.audio_hash || "");
      option.textContent = formatSavedSourceAudioLabel(sample);
      savedSourceAudioSelectNode.appendChild(option);
    }

    const selectedHash = findSavedSourceAudioByHash(preferredHash || state.selectedAudioHash)?.audio_hash || "";
    savedSourceAudioSelectNode.value = selectedHash;
    if (selectedHash && !state.selectedAudioFile) {
      applySavedSourceAudioSelection(selectedHash);
    } else {
      setSavedSourceAudioStatus(`Loaded ${samples.length} saved audio file${samples.length === 1 ? "" : "s"}.`);
    }
  } catch (err) {
    savedSourceAudioSelectNode.innerHTML = '<option value="">Unable to load saved audio files</option>';
    setSavedSourceAudioStatus(`Could not load saved audio files: ${String(err)}`, true);
  } finally {
    savedSourceAudioSelectNode.disabled = false;
    if (refreshSourceAudioBtn) refreshSourceAudioBtn.disabled = false;
  }
}

async function saveSelectedAudioFile(file) {
  const projectId = state.activeProjectRef;
  if (!projectId || !file) {
    return null;
  }

  setSavedSourceAudioStatus("Saving uploaded audio to this project...");
  const payload = {
    filename: file.name,
    audio_b64: await fileToBase64(file),
  };
  const data = await requestJSON(`/projects/${encodeURIComponent(projectId)}/source-audio`, "POST", payload);
  const audioHash = String(data.audio_hash || "");
  state.selectedAudioFile = null;
  state.selectedAudioHash = audioHash || null;
  await loadSourceAudioSamples(audioHash);
  queueProjectSettingsSave();
  return audioHash || null;
}

async function loadProjects(preferredProjectRef = null) {
  if (!existingProjectSelectNode) return;
  existingProjectSelectNode.disabled = true;
  existingProjectSelectNode.innerHTML = '<option value="">Loading projects...</option>';
  if (recentProjectListNode) {
    recentProjectListNode.innerHTML = '<p class="recent-project-empty">Loading recent projects...</p>';
  }
  setGatewayStatus("Loading projects...");

  try {
    const data = await requestJSON("/projects", "GET");
    const projects = Array.isArray(data.projects) ? data.projects : [];

    existingProjectSelectNode.innerHTML = "";
    renderRecentProjects(projects);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = projects.length ? "Select a project" : "No projects yet";
    existingProjectSelectNode.appendChild(placeholder);

    projects.forEach((project) => {
      const option = document.createElement("option");
      const projectRef = String(project.project_ref || "");
      const projectLabel = String(project.project_id || "");
      const shared = Boolean(project.shared);
      const ownerLabel = String(project.owner_label || "").trim();
      const sharedSuffix = shared ? ` (shared${ownerLabel ? ` from ${ownerLabel}` : ""})` : "";
      option.value = projectRef;
      option.dataset.projectLabel = projectLabel;
      option.textContent = `${projectLabel}${sharedSuffix}`;
      existingProjectSelectNode.appendChild(option);
    });

    if (preferredProjectRef) {
      existingProjectSelectNode.value = preferredProjectRef;
    }

    setGatewayStatus(projects.length ? "Choose a project to open." : "Create your first project.");
  } catch (err) {
    existingProjectSelectNode.innerHTML = '<option value="">Unable to load projects</option>';
    if (recentProjectListNode) {
      recentProjectListNode.innerHTML = '<p class="recent-project-empty">Could not load recent projects.</p>';
    }
    setGatewayStatus(`Could not load projects: ${String(err)}`, true);
  } finally {
    existingProjectSelectNode.disabled = false;
  }
}

function openProject(projectRef, projectLabel = projectRef) {
  if (!projectRef) return;
  if (existingProjectSelectNode) {
    existingProjectSelectNode.value = projectRef;
  }
  markWorkspaceReady(projectRef, projectLabel || projectRef);
}

function renderRecentProjects(projects) {
  if (!recentProjectListNode) return;
  const items = Array.isArray(projects) ? projects.slice(0, 5) : [];

  if (!items.length) {
    recentProjectListNode.innerHTML = '<p class="recent-project-empty">No recent projects yet.</p>';
    return;
  }

  recentProjectListNode.innerHTML = "";
  for (const project of items) {
    const projectRef = String(project.project_ref || "");
    const projectLabel = String(project.project_id || projectRef);
    const shared = Boolean(project.shared);
    const ownerLabel = String(project.owner_label || "").trim();
    const updatedAt = cleanOptional(project.updated_at);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-project-btn";
    button.dataset.projectRef = projectRef;
    button.dataset.projectLabel = projectLabel;

    const title = document.createElement("span");
    title.className = "recent-project-title";
    title.textContent = projectLabel;
    button.appendChild(title);

    const metaParts = [];
    if (shared) {
      metaParts.push(`shared${ownerLabel ? ` from ${ownerLabel}` : ""}`);
    }
    if (updatedAt) {
      metaParts.push(`updated ${formatDisplayDateTime(updatedAt)}`);
    }
    if (metaParts.length) {
      const meta = document.createElement("span");
      meta.className = "recent-project-meta";
      meta.textContent = metaParts.join(" | ");
      button.appendChild(meta);
    }

    button.addEventListener("click", () => {
      openProject(projectRef, projectLabel);
    });
    recentProjectListNode.appendChild(button);
  }
}

async function openSelectedProject() {
  const projectRef = cleanOptional(existingProjectSelectNode?.value);
  if (!projectRef) return;
  const selected = existingProjectSelectNode?.selectedOptions?.[0];
  const label = selected?.dataset?.projectLabel || projectRef;
  openProject(projectRef, label);
}

async function refreshProjectAccessInfo() {
  if (!shareProjectBtn || !state.activeProjectRef) return;
  try {
    const data = await requestJSON(`/projects/${encodeURIComponent(state.activeProjectRef)}/access`, "GET");
    state.canManageActiveProject = Boolean(data.can_manage);
    shareProjectBtn.hidden = false;
    shareProjectBtn.disabled = !state.canManageActiveProject;
  } catch {
    state.canManageActiveProject = false;
    shareProjectBtn.disabled = true;
  }
}

function resetRunningState({ clearProgress = false } = {}) {
  state.activeJobId = null;
  state.currentStage = "queued";
  state.actualProgress = 0;
  state.displayProgress = 0;
  state.latestDetail = "Preparing enhancement...";
  state.jobStartedAtMs = null;
  state.etaSeconds = null;
  state.etaUpdatedAtMs = null;
  state.etaStage = null;
  state.computeMode = "server";
  state.expectedRemoteWorker = false;
  state.workerFallbackTimeoutSeconds = 0;
  state.jobPollErrorCount = 0;

  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  if (state.progressAnimator) {
    clearInterval(state.progressAnimator);
    state.progressAnimator = null;
  }

  if (generateBtn) generateBtn.disabled = false;
  if (cancelBtn) cancelBtn.hidden = true;

  if (clearProgress) {
    if (progressWrapNode) progressWrapNode.hidden = true;
    if (progressFillNode) progressFillNode.style.width = "0%";
    if (progressPercentNode) progressPercentNode.textContent = "0%";
    if (progressStageNode) progressStageNode.textContent = "Queued";
    if (progressComputeNode) progressComputeNode.textContent = "Processing on: RADcast server";
    if (progressEtaNode) progressEtaNode.textContent = "Time left to process: estimating...";
    if (progressDetailNode) progressDetailNode.textContent = "Preparing enhancement...";
  }
}

function formatEta(seconds) {
  const rounded = Math.max(0, Math.round(seconds));
  const m = String(Math.floor(rounded / 60)).padStart(2, "0");
  const s = String(rounded % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function currentEtaRemainingSeconds() {
  if (!Number.isFinite(state.etaSeconds) || !state.etaUpdatedAtMs) return null;
  return Math.max(0, Math.round(state.etaSeconds - (Date.now() - state.etaUpdatedAtMs) / 1000));
}

function syncEtaFromJob(nextStage, nextEtaSeconds) {
  if (!Number.isFinite(nextEtaSeconds) || nextEtaSeconds <= 0) {
    if (state.etaStage !== nextStage) {
      state.etaSeconds = null;
      state.etaUpdatedAtMs = null;
      state.etaStage = nextStage;
    }
    return;
  }

  if (state.etaStage !== nextStage || !Number.isFinite(state.etaSeconds) || !state.etaUpdatedAtMs) {
    state.etaSeconds = nextEtaSeconds;
    state.etaUpdatedAtMs = Date.now();
    state.etaStage = nextStage;
    return;
  }

  const currentRemaining = currentEtaRemainingSeconds();
  const allowEtaIncrease = nextStage === "cleanup" || state.etaStage === "cleanup";
  if (
    currentRemaining === null ||
    nextEtaSeconds <= currentRemaining - 3 ||
    (allowEtaIncrease && nextEtaSeconds >= currentRemaining + 4)
  ) {
    state.etaSeconds = nextEtaSeconds;
    state.etaUpdatedAtMs = Date.now();
  }
}

function renderEtaText() {
  if (!progressEtaNode) return;

  if (["completed", "failed", "cancelled"].includes(state.currentStage)) {
    progressEtaNode.textContent = "Time left to process: 00:00";
    return;
  }

  const remaining = currentEtaRemainingSeconds();
  if (remaining === null) {
    if (state.currentStage === "queued_remote" && state.workerFallbackTimeoutSeconds > 0 && state.jobStartedAtMs) {
      const fallbackRemaining = Math.max(
        0,
        Math.round(state.workerFallbackTimeoutSeconds - (Date.now() - state.jobStartedAtMs) / 1000)
      );
      progressEtaNode.textContent = `Time left to process: ${formatEta(fallbackRemaining)}`;
      return;
    }
    const label = state.currentStage === "queued" ? "waiting to start..." : "estimating...";
    progressEtaNode.textContent = `Time left to process: ${label}`;
    return;
  }

  if (remaining <= 0) {
    if (state.currentStage === "cleanup") {
      progressEtaNode.textContent = "Time left to process: recalculating...";
      return;
    }
    progressEtaNode.textContent = "Time left to process: finishing soon";
    return;
  }

  progressEtaNode.textContent = `Time left to process: ${formatEta(remaining)}`;
}

function runningStatusText() {
  if (state.currentStage === "queued_remote" && state.computeMode === "waiting_worker") {
    return `Waiting for helper pickup (${workerAvailabilitySummary()}).`;
  }
  if (state.currentStage === "cleanup") {
    return "Helper enhancement is done. Applying speech cleanup on the RADcast server (Mac mini).";
  }
  if (state.computeMode === "worker") {
    if (state.currentStage === "prepare") return "Helper connected. Preparing enhancement on your local helper device.";
    if (state.currentStage === "enhance") return "Helper connected. Improving audio on your local helper device.";
    if (state.currentStage === "finalize") return "Helper connected. Saving enhanced audio from your local helper device.";
    return "Helper connected. Processing on your local helper device.";
  }
  if (state.currentStage === "fallback_local") {
    return "No helper pulled this job in time. Running on the RADcast server (Mac mini).";
  }
  if (state.computeMode === "server" && state.activeJobId) {
    return "Processing on the RADcast server (Mac mini).";
  }
  return "";
}

function inferComputeMode(stage, logs) {
  const joinedLogs = Array.isArray(logs) ? logs.map((entry) => String(entry || "").toLowerCase()).join(" ") : "";
  const normalizedStage = String(stage || "").toLowerCase();
  if (normalizedStage === "queued_remote") return "waiting_worker";
  if (normalizedStage === "cleanup") return "server";
  if (normalizedStage === "worker_running") return "worker";
  if (joinedLogs.includes("worker ") && joinedLogs.includes("started processing")) return "worker";
  if (joinedLogs.includes("local server fallback") || normalizedStage === "fallback_local") return "server";
  if (state.expectedRemoteWorker && !["completed", "failed", "cancelled"].includes(normalizedStage) && state.computeMode !== "server") {
    return "waiting_worker";
  }
  return "server";
}

function computeLabelForMode() {
  if (state.computeMode === "worker") return "Processing on: local helper device";
  if (state.computeMode === "waiting_worker") return "Processing on: waiting for local helper";
  return "Processing on: RADcast server (Mac mini)";
}

function updateProgressVisuals() {
  const clamped = Math.max(0, Math.min(100, state.displayProgress));
  if (progressWrapNode) progressWrapNode.hidden = false;
  if (progressFillNode) progressFillNode.style.width = `${clamped}%`;
  if (progressPercentNode) progressPercentNode.textContent = `${Math.round(clamped)}%`;
  if (progressStageNode) progressStageNode.textContent = stageLabels[state.currentStage] || "Processing";
  if (progressComputeNode) progressComputeNode.textContent = computeLabelForMode();

  renderEtaText();

  if (progressDetailNode) progressDetailNode.textContent = state.latestDetail;
}

function progressAnimationTick() {
  if (state.displayProgress < state.actualProgress) {
    const delta = state.actualProgress - state.displayProgress;
    state.displayProgress = Math.min(state.actualProgress, state.displayProgress + Math.max(0.2, Math.min(0.9, delta * 0.12)));
  } else if (state.displayProgress > state.actualProgress) {
    state.displayProgress = Math.max(state.actualProgress, state.displayProgress - 0.4);
  }

  updateProgressVisuals();
}

function startProgressAnimation() {
  if (state.progressAnimator) clearInterval(state.progressAnimator);
  state.progressAnimator = setInterval(progressAnimationTick, 120);
}

function updateFromJob(job) {
  const nextStage = String(job.stage || state.currentStage || "queued");
  state.jobPollErrorCount = 0;
  state.currentStage = nextStage;
  state.computeMode = inferComputeMode(nextStage, job.logs);
  state.latestDetail = latestLogMessage(job.logs) || stageLabels[state.currentStage] || "Processing";
  if (state.currentStage === "queued_remote" && state.computeMode === "waiting_worker") {
    const availability = workerAvailabilitySummary();
    state.latestDetail = `Waiting up to ${Math.round(state.workerFallbackTimeoutSeconds || 0)}s for a live helper to pull this job (${availability}).`;
  } else if (state.currentStage === "prepare" && state.computeMode === "worker") {
    state.latestDetail = state.latestDetail || "Loading enhancement runtime on helper device";
  } else if (state.currentStage === "enhance" && state.computeMode === "worker" && !state.latestDetail) {
    state.latestDetail = "Enhancing audio on helper device";
  }
  if (Number.isFinite(Number(job.progress))) {
    state.actualProgress = Math.max(state.actualProgress, Number(job.progress) * 100);
  }
  syncEtaFromJob(nextStage, Number(job.eta_seconds));
  const statusText = runningStatusText();
  if (statusText) setGenerateStatus(statusText);
}

function latestLogMessage(logs) {
  if (!Array.isArray(logs) || !logs.length) return "";
  const raw = String(logs[logs.length - 1] || "").trim();
  const parts = raw.split(" ");
  if (parts.length > 2 && /^\d{4}-\d{2}-\d{2}T/.test(parts[0])) {
    return parts.slice(1).join(" ");
  }
  return raw;
}

async function pollJob() {
  if (!state.activeJobId || !state.activeProjectRef) return;

  try {
    const data = await requestJSON(
      `/jobs/${encodeURIComponent(state.activeJobId)}?project_id=${encodeURIComponent(state.activeProjectRef)}`,
      "GET"
    );

    updateFromJob(data);

    const status = String(data.status || "").toLowerCase();
    if (status === "completed") {
      state.actualProgress = 100;
      state.displayProgress = 100;
      state.currentStage = "completed";
      state.latestDetail = "Enhancement finished.";
      updateProgressVisuals();
      resetRunningState({ clearProgress: false });
      setGenerateStatus("Audio enhancement complete.");
      await loadOutputs();
      return;
    }

    if (status === "failed") {
      state.currentStage = "failed";
      state.actualProgress = 100;
      state.displayProgress = 100;
      state.latestDetail = String(data.error || "Enhancement failed.");
      updateProgressVisuals();
      resetRunningState({ clearProgress: false });
      setGenerateStatus(`Enhancement failed: ${state.latestDetail}`, true);
      return;
    }

    if (status === "cancelled") {
      state.currentStage = "cancelled";
      state.actualProgress = 0;
      state.displayProgress = 0;
      state.latestDetail = "Enhancement cancelled.";
      updateProgressVisuals();
      resetRunningState({ clearProgress: false });
      setGenerateStatus("Enhancement cancelled.");
      return;
    }

    updateProgressVisuals();
  } catch (err) {
    const message = String(err || "");
    if (/job not found/i.test(message) && state.jobPollErrorCount < 3) {
      state.jobPollErrorCount += 1;
      setGenerateStatus("Waiting for latest job status...");
      return;
    }
    resetRunningState({ clearProgress: false });
    setGenerateStatus(`Job polling failed: ${message}`, true);
  }
}

function startJobTracking(payload) {
  resetRunningState({ clearProgress: false });
  state.activeJobId = String(payload.job_id || "");
  state.jobStartedAtMs = Date.now();
  state.currentStage = String(payload.stage || "queued");
  state.actualProgress = 0;
  state.displayProgress = 0;
  state.latestDetail = state.currentStage === "queued_remote" ? "Queued for helper execution" : "Queued for enhancement";
  state.etaStage = state.currentStage;
  state.expectedRemoteWorker = Boolean(payload.worker_mode);
  state.workerFallbackTimeoutSeconds = Number(payload.worker_fallback_timeout_seconds || 0);
  state.workerOnlineCount = Number.isFinite(Number(payload.worker_online_count)) ? Number(payload.worker_online_count) : state.workerOnlineCount;
  state.workerTotalCount = Number.isFinite(Number(payload.worker_total_count)) ? Number(payload.worker_total_count) : state.workerTotalCount;
  state.workerLiveCount = Number.isFinite(Number(payload.worker_live_count)) ? Number(payload.worker_live_count) : state.workerLiveCount;
  state.workerRegisteredCount = Number.isFinite(Number(payload.worker_registered_count))
    ? Number(payload.worker_registered_count)
    : state.workerRegisteredCount;
  state.workerStaleCount = Number.isFinite(Number(payload.worker_stale_count)) ? Number(payload.worker_stale_count) : state.workerStaleCount;
  state.workerLastLiveSeenAt = String(payload.worker_last_live_seen_at || "").trim() || state.workerLastLiveSeenAt;
  state.workerOnlineWindowSeconds = Number.isFinite(Number(payload.worker_online_window_seconds))
    ? Number(payload.worker_online_window_seconds)
    : state.workerOnlineWindowSeconds;
  state.jobPollErrorCount = 0;
  state.computeMode = state.expectedRemoteWorker ? "waiting_worker" : "server";

  if (generateBtn) generateBtn.disabled = true;
  if (cancelBtn) cancelBtn.hidden = false;
  if (progressWrapNode) progressWrapNode.hidden = false;

  if (state.expectedRemoteWorker) {
    setGenerateStatus(`Waiting for helper pickup (${workerAvailabilitySummary()}).`);
  } else {
    setGenerateStatus("Enhancement started. First run on a server can take longer while the model loads.");
  }
  startProgressAnimation();
  state.pollTimer = setInterval(pollJob, 2000);
  void pollJob();
}

async function handleGenerate() {
  if (!state.activeProjectRef) {
    setGenerateStatus("Open a project first.", true);
    return;
  }
  if (!state.selectedAudioFile && !state.selectedAudioHash) {
    setGenerateStatus("Select an audio file first.", true);
    return;
  }

  try {
    let selectedAudioHash = state.selectedAudioHash;
    let selectedAudioFile = state.selectedAudioFile;

    if (selectedAudioFile && !selectedAudioHash) {
      selectedAudioHash = await saveSelectedAudioFile(selectedAudioFile);
      state.selectedAudioHash = selectedAudioHash;
      selectedAudioFile = null;
      state.selectedAudioFile = null;
    }

    setGenerateStatus("Queueing enhancement...");
    const payload = {
      project_id: state.activeProjectRef,
      output_format: String(outputFormatNode?.value || "mp3"),
      enhancement_model: selectedEnhancementModelId(),
      max_silence_seconds: selectedMaxSilenceSeconds(),
      remove_filler_words: Boolean(removeFillerWordsNode?.checked && state.speechCleanupAvailable),
    };
    if (selectedAudioHash) {
      payload.input_audio_hash = selectedAudioHash;
    } else if (selectedAudioFile) {
      payload.input_audio_b64 = await fileToBase64(selectedAudioFile);
      payload.input_audio_filename = selectedAudioFile.name;
    }

    const data = await requestJSON("/enhance/simple", "POST", payload);
    startJobTracking(data);
  } catch (err) {
    setGenerateStatus(`Enhancement failed to start: ${String(err)}`, true);
  }
}

async function handleCancel() {
  if (!state.activeJobId || !state.activeProjectRef) return;
  try {
    await requestJSON(
      `/jobs/${encodeURIComponent(state.activeJobId)}/cancel?project_id=${encodeURIComponent(state.activeProjectRef)}`,
      "POST"
    );
    setGenerateStatus("Cancelling enhancement...");
  } catch (err) {
    setGenerateStatus(`Cancel failed: ${String(err)}`, true);
  }
}

async function loadOutputs() {
  if (!state.activeProjectRef || !outputListNode) return;
  outputListNode.innerHTML = '<li class="output-item">Loading outputs...</li>';

  try {
    const data = await requestJSON(`/projects/${encodeURIComponent(state.activeProjectRef)}/outputs`, "GET");
    const outputs = Array.isArray(data.outputs) ? data.outputs : [];

    if (!outputs.length) {
      outputListNode.innerHTML = '<li class="output-item">No enhanced files in this project yet.</li>';
      return;
    }

    const rows = outputs.map((item, index) => {
      const actions = [];
      const outputId = `output-${index}`;
      const playUrl = String(item.play_url || item.download_url || "");
      const versionNumber = Number(item.version_number || 0);
      const summaryLabel = formatOutputSummary(item);

      if (item.download_url) {
        if (playUrl) {
          actions.push(
            `<button class="play-audio-btn" data-output-id="${escapeHtml(outputId)}" type="button" aria-expanded="false">Play audio</button>`
          );
        }
        actions.push(`<a href="${escapeHtml(item.download_url)}" download>Save audio as</a>`);
      }
      if (item.folder_path) {
        actions.push(`<button class="copy-folder-btn" data-folder="${escapeHtml(item.folder_path)}" type="button">Copy folder path</button>`);
      }

      return `
        <li class="output-item">
          <div class="output-meta">
            <div class="output-meta-main">
              <span class="output-name">${escapeHtml(item.output_name || "enhanced-audio")}</span>
              ${versionNumber > 0 ? `<span class="output-version-badge">Version ${escapeHtml(versionNumber)}</span>` : ""}
            </div>
            ${summaryLabel ? `<span class="output-summary">${escapeHtml(summaryLabel)}</span>` : ""}
          </div>
          <div class="output-actions">${actions.join(" ")}</div>
          ${
            playUrl
              ? `<div class="output-audio-player" data-output-id="${escapeHtml(outputId)}" hidden>
                   <audio controls preload="metadata" src="${escapeHtml(playUrl)}"></audio>
                 </div>`
              : ""
          }
          <div class="folder-line">${escapeHtml(item.folder_path || item.output_path || "")}</div>
        </li>
      `;
    });

    outputListNode.innerHTML = rows.join("");
  } catch (err) {
    outputListNode.innerHTML = `<li class="output-item">Could not load outputs: ${escapeHtml(String(err))}</li>`;
  }
}

function formatOutputSummary(item) {
  const parts = [];
  const duration = Number(item.duration_seconds || 0);
  if (Number.isFinite(duration) && duration > 0) {
    parts.push(formatDurationSeconds(duration));
  }
  const dateText = formatOutputDate(item.created_at);
  if (dateText) {
    parts.push(dateText);
  }
  const timeText = formatOutputTime(item.created_at);
  if (timeText) {
    parts.push(timeText);
  }
  return parts.join(" | ");
}

function toggleOutputAudioPlayer(button) {
  if (!outputListNode) return;
  const outputId = button.dataset.outputId || "";
  if (!outputId) return;

  const playerWrap = Array.from(outputListNode.querySelectorAll(".output-audio-player")).find((node) => {
    return node instanceof HTMLElement && node.dataset.outputId === outputId;
  });
  if (!(playerWrap instanceof HTMLElement)) return;
  const audio = playerWrap.querySelector("audio");
  if (!(audio instanceof HTMLAudioElement)) return;

  const isOpen = !playerWrap.hidden;
  if (isOpen) {
    audio.pause();
    playerWrap.hidden = true;
    button.textContent = "Play audio";
    button.setAttribute("aria-expanded", "false");
    return;
  }

  for (const wrapNode of outputListNode.querySelectorAll(".output-audio-player")) {
    if (!(wrapNode instanceof HTMLElement)) continue;
    if (wrapNode.dataset.outputId === outputId) continue;
    const otherAudio = wrapNode.querySelector("audio");
    if (otherAudio instanceof HTMLAudioElement) {
      otherAudio.pause();
    }
    wrapNode.hidden = true;
  }

  for (const otherBtn of outputListNode.querySelectorAll(".play-audio-btn")) {
    if (!(otherBtn instanceof HTMLButtonElement)) continue;
    if (otherBtn.dataset.outputId === outputId) continue;
    otherBtn.textContent = "Play audio";
    otherBtn.setAttribute("aria-expanded", "false");
  }

  playerWrap.hidden = false;
  button.textContent = "Hide player";
  button.setAttribute("aria-expanded", "true");
  const playPromise = audio.play();
  if (playPromise && typeof playPromise.catch === "function") {
    playPromise.catch(() => {});
  }
}

function bindOutputActions() {
  if (!outputListNode) return;

  outputListNode.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const playButton = target.closest(".play-audio-btn");
    if (playButton instanceof HTMLButtonElement) {
      toggleOutputAudioPlayer(playButton);
      return;
    }

    const copyButton = target.closest(".copy-folder-btn");
    if (!(copyButton instanceof HTMLButtonElement)) return;

    const folderPath = copyButton.dataset.folder || "";
    if (!folderPath) return;

    navigator.clipboard
      .writeText(folderPath)
      .then(() => {
        setGenerateStatus("Folder path copied to clipboard.");
      })
      .catch(() => {
        setGenerateStatus("Could not copy folder path.", true);
      });
  });
}

async function shareProjectPrompt() {
  if (!state.activeProjectRef) return;
  if (!state.canManageActiveProject) {
    setGenerateStatus("Only project owners can share this project.", true);
    return;
  }

  const emailInput = window.prompt("Share project with user email:");
  const email = cleanOptional(emailInput)?.toLowerCase();
  if (!email) return;

  try {
    const result = await requestJSON(
      `/projects/${encodeURIComponent(state.activeProjectRef)}/access/grant`,
      "POST",
      { email }
    );
    const count = Array.isArray(result.collaborators) ? result.collaborators.length : 0;
    setGenerateStatus(`Access granted to ${email}. Collaborators: ${count}.`);
  } catch (err) {
    setGenerateStatus(`Share failed: ${String(err)}`, true);
  }
}

function wireDragAndDrop() {
  if (!audioDropzoneNode || !audioFileInputNode) return;

  ["dragenter", "dragover"].forEach((type) => {
    audioDropzoneNode.addEventListener(type, (event) => {
      event.preventDefault();
      audioDropzoneNode.classList.add("dropzone-active");
    });
  });

  ["dragleave", "drop"].forEach((type) => {
    audioDropzoneNode.addEventListener(type, (event) => {
      event.preventDefault();
      audioDropzoneNode.classList.remove("dropzone-active");
    });
  });

  audioDropzoneNode.addEventListener("drop", (event) => {
    const dt = event.dataTransfer;
    const file = dt && dt.files && dt.files.length ? dt.files[0] : null;
    if (file) {
      updateAudioSelection(file);
      void saveSelectedAudioFile(file).catch((err) => {
        setSavedSourceAudioStatus(`Could not save uploaded audio: ${String(err)}`, true);
      });
    }
  });

  audioFileInputNode.addEventListener("change", () => {
    const file = audioFileInputNode.files && audioFileInputNode.files.length ? audioFileInputNode.files[0] : null;
    updateAudioSelection(file || null);
    if (file) {
      void saveSelectedAudioFile(file).catch((err) => {
        setSavedSourceAudioStatus(`Could not save uploaded audio: ${String(err)}`, true);
      });
    }
  });
}

async function init() {
  showProjectGateway();
  await loadProjects();

  if (refreshProjectsBtn) {
    refreshProjectsBtn.addEventListener("click", () => {
      void loadProjects(existingProjectSelectNode ? existingProjectSelectNode.value : null);
    });
  }

  if (existingProjectSelectNode) {
    existingProjectSelectNode.addEventListener("change", () => {
      void openSelectedProject();
    });
  }

  const createForm = document.getElementById("create-form");
  if (createForm) {
    createForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(createForm);
      const projectId = cleanOptional(form.get("project_id"));
      if (!projectId) {
        setGatewayStatus("Project ID is required.", true);
        return;
      }

      const payload = {
        project_id: projectId,
        course: cleanOptional(form.get("course")),
        module: cleanOptional(form.get("module")),
        lesson: cleanOptional(form.get("lesson")),
      };

      try {
        setGatewayStatus("Creating project...");
        const created = await requestJSON("/projects", "POST", payload);
        await loadProjects(String(created.project_ref || ""));
        if (existingProjectSelectNode) {
          existingProjectSelectNode.value = String(created.project_ref || "");
          await openSelectedProject();
        }
      } catch (err) {
        setGatewayStatus(`Create project failed: ${String(err)}`, true);
      }
    });
  }

  if (switchProjectBtn) {
    switchProjectBtn.addEventListener("click", async () => {
      showProjectGateway();
      await loadProjects();
    });
  }

  if (shareProjectBtn) {
    shareProjectBtn.addEventListener("click", () => {
      void shareProjectPrompt();
    });
  }

  if (refreshSourceAudioBtn) {
    refreshSourceAudioBtn.addEventListener("click", () => {
      void loadSourceAudioSamples(savedSourceAudioSelectNode ? savedSourceAudioSelectNode.value : null);
    });
  }

  if (workerRefreshBtn) {
    workerRefreshBtn.addEventListener("click", () => {
      void fetchWorkerStatus();
    });
  }

  if (workerSetupBtn) {
    workerSetupBtn.addEventListener("click", () => {
      void fetchWorkerSetupOptions();
    });
  }

  if (workerSetupCloseBtn) {
    workerSetupCloseBtn.addEventListener("click", () => {
      closeWorkerSetupModal();
    });
  }

  if (workerSetupModalNode) {
    workerSetupModalNode.addEventListener("click", (event) => {
      if (event.target === workerSetupModalNode) closeWorkerSetupModal();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && workerSetupModalNode && !workerSetupModalNode.hidden) {
      closeWorkerSetupModal();
    }
  });

  if (workerCopyMacosBtn) {
    workerCopyMacosBtn.addEventListener("click", async () => {
      if (!state.workerSetupMacosCommand) await fetchWorkerSetupOptions();
      if (!state.workerSetupMacosCommand) return;
      await navigator.clipboard.writeText(state.workerSetupMacosCommand);
      setWorkerSetupStatus("Copied Mac setup command.");
    });
  }

  if (workerCopyLinuxBtn) {
    workerCopyLinuxBtn.addEventListener("click", async () => {
      if (!state.workerSetupLinuxCommand) await fetchWorkerSetupOptions();
      if (!state.workerSetupLinuxCommand) return;
      await navigator.clipboard.writeText(state.workerSetupLinuxCommand);
      setWorkerSetupStatus("Copied Linux setup command.");
    });
  }

  if (savedSourceAudioSelectNode) {
    savedSourceAudioSelectNode.addEventListener("change", () => {
      const audioHash = cleanOptional(savedSourceAudioSelectNode.value);
      if (!audioHash) {
        state.selectedAudioHash = null;
        if (!state.selectedAudioFile) {
          clearSourcePreview();
          if (audioDropzoneTitleNode) audioDropzoneTitleNode.textContent = "Drop audio here or click to choose";
          if (audioFileNameNode) audioFileNameNode.textContent = "No file selected.";
        }
        setSavedSourceAudioStatus("Uploaded audio files are saved to this project for reuse.");
        queueProjectSettingsSave();
        return;
      }
      applySavedSourceAudioSelection(audioHash);
      queueProjectSettingsSave();
    });
  }

  if (generateBtn) generateBtn.addEventListener("click", () => void handleGenerate());
  if (cancelBtn) cancelBtn.addEventListener("click", () => void handleCancel());
  if (outputFormatNode) {
    outputFormatNode.addEventListener("change", () => {
      queueProjectSettingsSave();
    });
  }
  if (enhancementModelNode) {
    enhancementModelNode.addEventListener("change", () => {
      updateEnhancementModelStatusFromSelection();
      queueProjectSettingsSave();
    });
  }
  if (reduceSilenceEnabledNode) {
    reduceSilenceEnabledNode.addEventListener("change", () => {
      updateSpeechCleanupControls();
      updateSpeechCleanupStatusFromSelection();
      queueProjectSettingsSave();
    });
  }
  if (reduceSilenceSecondsNode) {
    reduceSilenceSecondsNode.addEventListener("input", () => {
      updateSpeechCleanupControls();
      updateSpeechCleanupStatusFromSelection();
      queueProjectSettingsSave();
    });
  }
  if (removeFillerWordsNode) {
    removeFillerWordsNode.addEventListener("change", () => {
      updateSpeechCleanupStatusFromSelection();
      queueProjectSettingsSave();
    });
  }
  bindOutputActions();
  state.projectSettings = defaultProjectSettings();
  resetProjectSettingsControls();

  void fetchWorkerStatus();
  void loadEnhancementModels();
  startWorkerStatusPolling();
  wireDragAndDrop();
}

void init();
