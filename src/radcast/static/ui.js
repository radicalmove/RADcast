const projectGatewayNode = document.getElementById("project-gateway");
const workspaceNode = document.getElementById("workspace");
const switchProjectBtn = document.getElementById("switch-project-btn");
const shareProjectBtn = document.getElementById("share-project-btn");
const helpBtn = document.getElementById("help-btn");
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
const deleteSourceAudioBtn = document.getElementById("delete-source-audio-btn");
const savedSourceAudioStatusNode = document.getElementById("saved-source-audio-status");
const sourcePreviewLabelNode = document.getElementById("source-preview-label");
const sourceAudioPreviewNode = document.getElementById("source-audio-preview");
const trimBlockNode = document.getElementById("trim-block");
const trimRailNode = document.getElementById("trim-rail");
const trimSelectionNode = document.getElementById("trim-selection");
const trimPlayheadNode = document.getElementById("trim-playhead");
const trimStartHandleNode = document.getElementById("trim-start-handle");
const trimEndHandleNode = document.getElementById("trim-end-handle");
const trimStatusNode = document.getElementById("trim-status");
const trimStartValueNode = document.getElementById("trim-start-value");
const trimEndValueNode = document.getElementById("trim-end-value");
const trimOutputLengthValueNode = document.getElementById("trim-output-length-value");
const trimResetBtn = document.getElementById("trim-reset-btn");

const outputFormatNode = document.getElementById("output-format");
const captionFormatNode = document.getElementById("caption-format");
const captionQualityModeNode = document.getElementById("caption-quality-mode");
const captionFormatStatusNode = document.getElementById("caption-format-status");
const dontEnhanceAudioNode = document.getElementById("dont-enhance-audio");
const enhancementModelStatusNode = document.getElementById("enhancement-model-status");
const reduceSilenceEnabledNode = document.getElementById("reduce-silence-enabled");
const reduceSilenceSecondsNode = document.getElementById("reduce-silence-seconds");
const reduceSilenceValueNode = document.getElementById("reduce-silence-value");
const reduceSilenceStatusNode = document.getElementById("reduce-silence-status");
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
const shareProjectModalNode = document.getElementById("share-project-modal");
const shareProjectCloseBtn = document.getElementById("share-project-close-btn");
const shareProjectUserSelectNode = document.getElementById("share-project-user-select");
const shareProjectGrantBtn = document.getElementById("share-project-grant-btn");
const shareProjectStatusNode = document.getElementById("share-project-status");
const shareProjectOwnerNode = document.getElementById("share-project-owner");
const shareProjectMembersNode = document.getElementById("share-project-members");
const helpModalNode = document.getElementById("help-modal");
const helpTabListNode = document.getElementById("help-modal-tabs");
const helpModalBodyNode = document.getElementById("help-modal-body");
const helpCloseBtn = document.getElementById("help-close-btn");
const helpTabButtons = Array.from(document.querySelectorAll("[data-help-tab]"));
const helpPanels = Array.from(document.querySelectorAll("[data-help-panel]"));
const helpStorageKey = "radcast-help-last-tab";
const helpTabOrder = ["overview", "process-audio", "cleanup-pauses", "generate-captions", "trim-clip", "helper-processing", "troubleshooting"];

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
  captions: "Generating captions",
  finalize: "Saving audio",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const flexibleEtaStages = new Set(["enhance", "cleanup", "captions"]);
const MIN_TRIM_OUTPUT_SECONDS = 0.5;

const state = {
  activeProjectRef: null,
  activeProjectLabel: null,
  selectedAudioFile: null,
  selectedAudioHash: null,
  selectedAudioTempKey: null,
  selectedAudioDurationSeconds: null,
  projectSettings: null,
  projectSettingsSaveTimer: null,
  sourceAudioSamples: [],
  transientTrimRangesByAudioKey: {},
  activeTrimAudioKey: null,
  activeTrimStartSeconds: 0,
  activeTrimEndSeconds: null,
  trimDragMode: null,
  trimPointerId: null,
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
  optimizedEnhancementAvailable: null,
  speechCleanupAvailable: true,
  speechCleanupDetail: "",
  shareProjectUsers: [],
  shareProjectCollaborators: [],
  shareProjectOwner: null,
  helpActiveTab: "overview",
};
let helpModalReturnFocusNode = null;

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

function normalizeCaptionFormat(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "srt" || normalized === "vtt" ? normalized : null;
}

function normalizeCaptionQualityMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "fast") return "fast";
  if (normalized === "reviewed") return "reviewed";
  return "reviewed";
}

function makeTemporaryAudioKey(file) {
  if (!(file instanceof File)) return null;
  return `temp:${file.name}:${file.size}:${file.lastModified}`;
}

function normalizeTrimRangeEntry(value) {
  const payload = value && typeof value === "object" ? value : null;
  if (!payload) return null;
  const start = Number(payload.clip_start_seconds);
  const end = Number(payload.clip_end_seconds);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  if (start < 0 || end <= start) return null;
  return {
    clip_start_seconds: start,
    clip_end_seconds: end,
  };
}

function normalizeTrimRangesMap(value) {
  const payload = value && typeof value === "object" ? value : {};
  const ranges = {};
  for (const [key, entry] of Object.entries(payload)) {
    const audioHash = cleanOptional(key);
    const normalized = normalizeTrimRangeEntry(entry);
    if (!audioHash || !normalized) continue;
    ranges[audioHash] = normalized;
  }
  return ranges;
}

function getSelectedAudioDurationSeconds() {
  const duration = Number(state.selectedAudioDurationSeconds);
  return Number.isFinite(duration) && duration > 0 ? duration : null;
}

function formatTrimSeconds(value) {
  const numeric = Number(value || 0);
  const safe = Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
  return `${safe.toFixed(1)}s`;
}

function effectiveMinTrimOutputSeconds(duration) {
  const safeDuration = Number(duration || 0);
  if (!Number.isFinite(safeDuration) || safeDuration <= 0) return MIN_TRIM_OUTPUT_SECONDS;
  return Math.max(0.05, Math.min(MIN_TRIM_OUTPUT_SECONDS, safeDuration));
}

function buildClampedTrimRange(startSeconds, endSeconds, durationSeconds) {
  const duration = Number(durationSeconds || 0);
  if (!Number.isFinite(duration) || duration <= 0) return null;
  const minOutput = effectiveMinTrimOutputSeconds(duration);
  if (duration <= minOutput) {
    return {
      clip_start_seconds: 0,
      clip_end_seconds: duration,
    };
  }

  let start = Number(startSeconds);
  let end = Number(endSeconds);
  start = Number.isFinite(start) ? start : 0;
  end = Number.isFinite(end) ? end : duration;

  start = Math.max(0, Math.min(start, duration - minOutput));
  end = Math.max(minOutput, Math.min(end, duration));

  if (end - start < minOutput) {
    end = Math.min(duration, start + minOutput);
  }
  if (end - start < minOutput) {
    start = Math.max(0, end - minOutput);
  }

  return {
    clip_start_seconds: start,
    clip_end_seconds: end,
  };
}

function isFullTrimRange(range, durationSeconds) {
  const duration = Number(durationSeconds || 0);
  if (!range || !Number.isFinite(duration) || duration <= 0) return true;
  const epsilon = 0.05;
  return range.clip_start_seconds <= epsilon && range.clip_end_seconds >= duration - epsilon;
}

function currentSelectedAudioKeyInfo() {
  if (state.selectedAudioHash) {
    return { kind: "saved", key: state.selectedAudioHash };
  }
  if (state.selectedAudioTempKey) {
    return { kind: "temp", key: state.selectedAudioTempKey };
  }
  return null;
}

function getStoredTrimRangeForKey(keyInfo) {
  if (!keyInfo?.key) return null;
  if (keyInfo.kind === "saved") {
    return normalizeTrimRangeEntry(state.projectSettings?.trim_ranges_by_audio_hash?.[keyInfo.key]);
  }
  return normalizeTrimRangeEntry(state.transientTrimRangesByAudioKey[keyInfo.key]);
}

function defaultProjectSettings() {
  return {
    selected_audio_hash: null,
    trim_ranges_by_audio_hash: {},
    output_format: "mp3",
    caption_format: null,
    caption_quality_mode: "reviewed",
    enhancement_model: "studio_v18",
    reduce_silence_enabled: false,
    max_silence_seconds: 1,
    remove_filler_words: false,
    filler_removal_mode: "aggressive",
  };
}

function setupThemeToggle() {
  const themeToggle = document.getElementById("themeToggle");
  if (!themeToggle) return;

  const icon = themeToggle.querySelector(".theme-icon");
  const storageKey = "radcast-theme";
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  let currentTheme = localStorage.getItem(storageKey) || (prefersDark ? "dark" : "light");

  function applyTheme(theme) {
    if (theme === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
      themeToggle.setAttribute("aria-label", "Switch to light mode");
      themeToggle.setAttribute("aria-pressed", "true");
      themeToggle.dataset.icon = "light";
      if (icon) icon.dataset.iconState = "light";
    } else {
      document.documentElement.removeAttribute("data-theme");
      themeToggle.setAttribute("aria-label", "Switch to dark mode");
      themeToggle.setAttribute("aria-pressed", "false");
      themeToggle.dataset.icon = "dark";
      if (icon) icon.dataset.iconState = "dark";
    }
    localStorage.setItem(storageKey, theme);
  }

  applyTheme(currentTheme);
  themeToggle.addEventListener("click", () => {
    currentTheme = currentTheme === "dark" ? "light" : "dark";
    applyTheme(currentTheme);
  });
}

function normalizeProjectSettings(payload) {
  const data = payload && typeof payload === "object" ? payload : {};
  const outputFormat = cleanOptional(data.output_format);
  const captionFormat = normalizeCaptionFormat(data.caption_format);
  const captionQualityMode = normalizeCaptionQualityMode(data.caption_quality_mode);
  const enhancementModel = String(cleanOptional(data.enhancement_model) || "").trim().toLowerCase() === "none"
    ? "none"
    : "studio_v18";
  const selectedAudioHash = cleanOptional(data.selected_audio_hash);

  return {
    selected_audio_hash: selectedAudioHash && selectedAudioHash.length >= 16 ? selectedAudioHash : null,
    trim_ranges_by_audio_hash: normalizeTrimRangesMap(data.trim_ranges_by_audio_hash),
    output_format: outputFormat === "wav" ? "wav" : "mp3",
    caption_format: captionFormat,
    caption_quality_mode: captionQualityMode,
    enhancement_model: enhancementModel,
    reduce_silence_enabled: Boolean(data.reduce_silence_enabled),
    max_silence_seconds: clampSilenceSeconds(data.max_silence_seconds),
    remove_filler_words: Boolean(data.remove_filler_words),
    filler_removal_mode: "aggressive",
  };
}

function applyProjectSettingsToControls(settings) {
  const normalized = normalizeProjectSettings(settings);
  state.projectSettings = normalized;

  if (outputFormatNode) {
    outputFormatNode.value = normalized.output_format;
  }
  if (captionFormatNode) {
    captionFormatNode.value = normalized.caption_format || "";
  }
  if (captionQualityModeNode) {
    captionQualityModeNode.value = normalized.caption_quality_mode;
  }
  if (dontEnhanceAudioNode) {
    dontEnhanceAudioNode.checked = normalized.enhancement_model === "none";
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
  updateCaptionFormatStatus();
  updateGenerateButtonLabel();
  renderTrimRail();
}

function resetProjectSettingsControls() {
  applyProjectSettingsToControls(defaultProjectSettings());
  renderTrimRail();
}

function setTrimStatus(message, isError = false) {
  if (!trimStatusNode) return;
  trimStatusNode.textContent = message || "";
  trimStatusNode.style.color = isError ? "#a73527" : "#555";
}

function trimPercentForSeconds(seconds) {
  const duration = getSelectedAudioDurationSeconds();
  if (!duration) return 0;
  const safeSeconds = Math.max(0, Math.min(duration, Number(seconds || 0)));
  return (safeSeconds / duration) * 100;
}

function currentPreviewTimeSeconds() {
  const duration = getSelectedAudioDurationSeconds();
  if (!duration) return 0;
  if (sourceAudioPreviewNode) {
    const current = Number(sourceAudioPreviewNode.currentTime);
    if (Number.isFinite(current)) {
      return Math.max(0, Math.min(duration, current));
    }
  }
  return Math.max(0, Math.min(duration, Number(state.activeTrimStartSeconds || 0)));
}

function currentActiveTrimRange() {
  const duration = getSelectedAudioDurationSeconds();
  if (!duration) return null;
  return buildClampedTrimRange(
    state.activeTrimStartSeconds,
    state.activeTrimEndSeconds ?? duration,
    duration
  );
}

function currentTrimRangePayload() {
  const duration = getSelectedAudioDurationSeconds();
  const range = currentActiveTrimRange();
  if (!duration || !range || isFullTrimRange(range, duration)) {
    return null;
  }
  return range;
}

function buildTrimRangesPayload() {
  const trimRanges = normalizeTrimRangesMap(state.projectSettings?.trim_ranges_by_audio_hash);
  const keyInfo = currentSelectedAudioKeyInfo();
  if (keyInfo?.kind !== "saved") {
    return trimRanges;
  }
  const activeRange = currentTrimRangePayload();
  if (activeRange) {
    trimRanges[keyInfo.key] = activeRange;
  } else {
    delete trimRanges[keyInfo.key];
  }
  return trimRanges;
}

function renderTrimRail() {
  const duration = getSelectedAudioDurationSeconds();
  const activeKeyInfo = currentSelectedAudioKeyInfo();
  const hasAudio = Boolean(activeKeyInfo?.key);
  const range = currentActiveTrimRange();
  const enabled = Boolean(hasAudio && duration && range);

  if (trimBlockNode) {
    trimBlockNode.classList.toggle("trim-block-disabled", !enabled);
  }
  if (trimResetBtn) {
    trimResetBtn.disabled = !enabled || !currentTrimRangePayload();
  }

  if (!enabled) {
    if (trimSelectionNode) {
      trimSelectionNode.style.left = "0%";
      trimSelectionNode.style.width = "100%";
    }
    if (trimPlayheadNode) {
      trimPlayheadNode.style.left = "0%";
    }
    if (trimStartHandleNode) {
      trimStartHandleNode.style.left = "0%";
    }
    if (trimEndHandleNode) {
      trimEndHandleNode.style.left = "100%";
    }
    if (trimStartValueNode) trimStartValueNode.textContent = "0.0s";
    if (trimEndValueNode) trimEndValueNode.textContent = "0.0s";
    if (trimOutputLengthValueNode) trimOutputLengthValueNode.textContent = "0.0s";
    setTrimStatus(hasAudio ? "Loading clip length..." : "Select audio to enable trimming.");
    return;
  }

  const startPercent = trimPercentForSeconds(range.clip_start_seconds);
  const endPercent = trimPercentForSeconds(range.clip_end_seconds);
  const playheadPercent = trimPercentForSeconds(currentPreviewTimeSeconds());

  if (trimSelectionNode) {
    trimSelectionNode.style.left = `${startPercent}%`;
    trimSelectionNode.style.width = `${Math.max(0, endPercent - startPercent)}%`;
  }
  if (trimPlayheadNode) {
    trimPlayheadNode.style.left = `${playheadPercent}%`;
  }
  if (trimStartHandleNode) {
    trimStartHandleNode.style.left = `${startPercent}%`;
  }
  if (trimEndHandleNode) {
    trimEndHandleNode.style.left = `${endPercent}%`;
  }
  if (trimStartValueNode) {
    trimStartValueNode.textContent = formatTrimSeconds(range.clip_start_seconds);
  }
  if (trimEndValueNode) {
    trimEndValueNode.textContent = formatTrimSeconds(range.clip_end_seconds);
  }
  if (trimOutputLengthValueNode) {
    trimOutputLengthValueNode.textContent = formatTrimSeconds(
      Math.max(0, range.clip_end_seconds - range.clip_start_seconds)
    );
  }

  if (currentTrimRangePayload()) {
    setTrimStatus("Drag the ends to trim. Click the bar to audition.");
  } else {
    setTrimStatus("Click the bar to audition. Drag the ends to trim.");
  }
}

function setSelectedAudioDuration(durationSeconds, { restoreStored = false } = {}) {
  const duration = Number(durationSeconds || 0);
  state.selectedAudioDurationSeconds = Number.isFinite(duration) && duration > 0 ? duration : null;
  const currentKey = currentSelectedAudioKeyInfo()?.key || null;

  if (!currentKey) {
    state.activeTrimAudioKey = null;
    state.activeTrimStartSeconds = 0;
    state.activeTrimEndSeconds = state.selectedAudioDurationSeconds;
    renderTrimRail();
    return;
  }

  if (restoreStored || state.activeTrimAudioKey !== currentKey) {
    const storedRange = getStoredTrimRangeForKey(currentSelectedAudioKeyInfo());
    const range = buildClampedTrimRange(
      storedRange?.clip_start_seconds ?? 0,
      storedRange?.clip_end_seconds ?? state.selectedAudioDurationSeconds,
      state.selectedAudioDurationSeconds
    );
    state.activeTrimAudioKey = currentKey;
    state.activeTrimStartSeconds = range?.clip_start_seconds ?? 0;
    state.activeTrimEndSeconds = range?.clip_end_seconds ?? state.selectedAudioDurationSeconds;
    renderTrimRail();
    return;
  }

  const nextRange = currentActiveTrimRange();
  state.activeTrimStartSeconds = nextRange?.clip_start_seconds ?? 0;
  state.activeTrimEndSeconds = nextRange?.clip_end_seconds ?? state.selectedAudioDurationSeconds;
  renderTrimRail();
}

function persistTrimRangeForCurrentAudio({ queueSave = true } = {}) {
  const keyInfo = currentSelectedAudioKeyInfo();
  const duration = getSelectedAudioDurationSeconds();
  if (!keyInfo?.key || !duration) {
    renderTrimRail();
    return;
  }

  const activeRange = currentTrimRangePayload();
  if (keyInfo.kind === "saved") {
    const nextSettings = normalizeProjectSettings({
      ...(state.projectSettings || defaultProjectSettings()),
      trim_ranges_by_audio_hash: normalizeTrimRangesMap(state.projectSettings?.trim_ranges_by_audio_hash),
    });
    if (activeRange) {
      nextSettings.trim_ranges_by_audio_hash[keyInfo.key] = activeRange;
    } else {
      delete nextSettings.trim_ranges_by_audio_hash[keyInfo.key];
    }
    state.projectSettings = nextSettings;
    if (queueSave) {
      queueProjectSettingsSave();
    }
  } else if (activeRange) {
    state.transientTrimRangesByAudioKey[keyInfo.key] = activeRange;
  } else {
    delete state.transientTrimRangesByAudioKey[keyInfo.key];
  }

  renderTrimRail();
}

function seekPreviewTo(seconds) {
  const duration = getSelectedAudioDurationSeconds();
  if (!duration || !sourceAudioPreviewNode) {
    renderTrimRail();
    return;
  }
  const nextSeconds = Math.max(0, Math.min(duration, Number(seconds || 0)));
  try {
    sourceAudioPreviewNode.currentTime = nextSeconds;
  } catch {
    // Ignore seek errors until metadata is ready.
  }
  renderTrimRail();
}

function trimSecondsFromClientX(clientX) {
  const duration = getSelectedAudioDurationSeconds();
  const rect = trimRailNode?.getBoundingClientRect();
  if (!duration || !rect || rect.width <= 0) return 0;
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  return duration * ratio;
}

function applyTrimHandlePosition(mode, seconds) {
  const duration = getSelectedAudioDurationSeconds();
  const range = currentActiveTrimRange();
  if (!duration || !range) return;

  const minOutput = effectiveMinTrimOutputSeconds(duration);
  if (mode === "start") {
    const nextStart = Math.max(0, Math.min(range.clip_end_seconds - minOutput, seconds));
    state.activeTrimStartSeconds = nextStart;
    state.activeTrimEndSeconds = range.clip_end_seconds;
    seekPreviewTo(nextStart);
  } else if (mode === "end") {
    const nextEnd = Math.min(duration, Math.max(range.clip_start_seconds + minOutput, seconds));
    state.activeTrimStartSeconds = range.clip_start_seconds;
    state.activeTrimEndSeconds = nextEnd;
    seekPreviewTo(nextEnd);
  }
  persistTrimRangeForCurrentAudio();
}

function resetTrimRange() {
  const duration = getSelectedAudioDurationSeconds();
  if (!duration) return;
  state.activeTrimStartSeconds = 0;
  state.activeTrimEndSeconds = duration;
  seekPreviewTo(0);
  persistTrimRangeForCurrentAudio();
}

function enforcePreviewTrimBounds() {
  const range = currentActiveTrimRange();
  if (!range || !sourceAudioPreviewNode) {
    renderTrimRail();
    return;
  }
  if (sourceAudioPreviewNode.currentTime > range.clip_end_seconds + 0.01) {
    sourceAudioPreviewNode.pause();
    sourceAudioPreviewNode.currentTime = range.clip_end_seconds;
  } else if (sourceAudioPreviewNode.currentTime < range.clip_start_seconds) {
    sourceAudioPreviewNode.currentTime = range.clip_start_seconds;
  }
  renderTrimRail();
}

function currentProjectSettingsPayload() {
  return normalizeProjectSettings({
    selected_audio_hash: state.selectedAudioHash,
    trim_ranges_by_audio_hash: buildTrimRangesPayload(),
    output_format: cleanOptional(outputFormatNode?.value) || "mp3",
    caption_format: selectedCaptionFormat(),
    caption_quality_mode: selectedCaptionQualityMode(),
    enhancement_model: selectedEnhancementModelId(),
    reduce_silence_enabled: Boolean(reduceSilenceEnabledNode?.checked),
    max_silence_seconds: reduceSilenceSecondsNode?.value ?? 1,
    remove_filler_words: Boolean(removeFillerWordsNode?.checked),
    filler_removal_mode: "aggressive",
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

function setReduceSilenceStatus(message, isError = false) {
  if (!reduceSilenceStatusNode) return;
  reduceSilenceStatusNode.textContent = message || "";
  reduceSilenceStatusNode.style.color = isError ? "#a73527" : "#555";
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

function syncModalOpenState() {
  const anyModalOpen = [workerSetupModalNode, shareProjectModalNode, helpModalNode].some((node) => node && !node.hidden);
  document.body.classList.toggle("modal-open", anyModalOpen);
}

function normalizeHelpTab(tab) {
  const value = String(tab || "").trim();
  return helpTabOrder.includes(value) ? value : "overview";
}

function readStoredHelpTab() {
  try {
    return localStorage.getItem(helpStorageKey);
  } catch (err) {
    return null;
  }
}

function helpTabButtonFor(tab) {
  const normalizedTab = normalizeHelpTab(tab);
  return helpTabButtons.find((button) => normalizeHelpTab(button.dataset.helpTab) === normalizedTab) || null;
}

function focusHelpTabButton(tab) {
  const button = helpTabButtonFor(tab);
  if (button) {
    button.focus();
  }
}

function helpTabNavigationTarget(currentTab, key) {
  const currentIndex = helpTabOrder.indexOf(normalizeHelpTab(currentTab));
  if (!helpTabOrder.length) return "overview";
  if (key === "Home") return helpTabOrder[0];
  if (key === "End") return helpTabOrder[helpTabOrder.length - 1];
  if (key === "ArrowRight" || key === "ArrowDown") {
    const nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % helpTabOrder.length;
    return helpTabOrder[nextIndex];
  }
  if (key === "ArrowLeft" || key === "ArrowUp") {
    const previousIndex = currentIndex < 0 ? 0 : (currentIndex - 1 + helpTabOrder.length) % helpTabOrder.length;
    return helpTabOrder[previousIndex];
  }
  return null;
}

function setHelpTab(tab, { persist = true, focus = false } = {}) {
  const activeTab = normalizeHelpTab(tab);
  state.helpActiveTab = activeTab;

  for (const button of helpTabButtons) {
    const buttonTab = normalizeHelpTab(button.dataset.helpTab);
    const isActive = buttonTab === activeTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
    button.tabIndex = isActive ? 0 : -1;
  }

  for (const panel of helpPanels) {
    const panelTab = normalizeHelpTab(panel.dataset.helpPanel);
    panel.hidden = panelTab !== activeTab;
  }

  if (helpModalBodyNode && !helpModalNode?.hidden) {
    helpModalBodyNode.scrollTop = 0;
  }

  if (persist) {
    try {
      localStorage.setItem(helpStorageKey, activeTab);
    } catch (err) {
      // Ignore storage failures.
    }
  }

  if (focus) {
    focusHelpTabButton(activeTab);
  }
}

function handleHelpTabKeydown(event) {
  const currentButton = event.target instanceof HTMLElement ? event.target.closest("[data-help-tab]") : null;
  if (!(currentButton instanceof HTMLButtonElement)) return;
  const nextTab = helpTabNavigationTarget(currentButton.dataset.helpTab, event.key);
  if (!nextTab) return;
  event.preventDefault();
  setHelpTab(nextTab, { focus: true });
}

function helpModalElementHidden(node) {
  let currentNode = node;
  while (currentNode instanceof HTMLElement && currentNode !== helpModalNode) {
    if (currentNode.hidden) return true;
    if (typeof currentNode.getAttribute === "function" && currentNode.getAttribute("aria-hidden") === "true") return true;
    currentNode = currentNode.parentNode;
  }
  return false;
}

function isHelpModalFocusable(node) {
  if (!(node instanceof HTMLElement)) return false;
  if (helpModalElementHidden(node)) return false;
  if ("disabled" in node && node.disabled) return false;
  if (node.tabIndex < 0) return false;
  const tagName = String(node.tagName || "").toLowerCase();
  if (tagName === "button" || tagName === "input" || tagName === "select" || tagName === "textarea" || tagName === "summary") {
    return true;
  }
  if (tagName === "a") {
    return typeof node.getAttribute === "function" && node.getAttribute("href") !== null;
  }
  return typeof node.getAttribute === "function" && node.getAttribute("tabindex") !== null;
}

function getHelpModalFocusableNodes() {
  if (!(helpModalNode instanceof HTMLElement)) return [];
  const focusableNodes = [];
  const stack = Array.from(helpModalNode.children || []);
  while (stack.length) {
    const node = stack.shift();
    if (!(node instanceof HTMLElement)) continue;
    if (isHelpModalFocusable(node)) {
      focusableNodes.push(node);
    }
    stack.unshift(...Array.from(node.children || []));
  }
  return focusableNodes;
}

function handleHelpModalKeydown(event) {
  if (event.key !== "Tab" || !helpModalNode || helpModalNode.hidden) return;
  const focusableNodes = getHelpModalFocusableNodes();
  if (focusableNodes.length < 2) return;
  const firstNode = focusableNodes[0];
  const lastNode = focusableNodes[focusableNodes.length - 1];
  const activeNode = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  if (event.shiftKey) {
    if (activeNode !== firstNode) return;
    event.preventDefault();
    lastNode.focus();
    return;
  }
  if (activeNode !== lastNode) return;
  event.preventDefault();
  firstNode.focus();
}

function openHelpModal() {
  if (!helpModalNode) return;
  const storedTab = readStoredHelpTab();
  const activeTab = normalizeHelpTab(storedTab);
  helpModalReturnFocusNode = document.activeElement instanceof HTMLElement ? document.activeElement : helpBtn;
  helpModalNode.hidden = false;
  setHelpTab(activeTab, { persist: storedTab !== activeTab, focus: true });
  syncModalOpenState();
}

function closeHelpModal() {
  if (!helpModalNode) return;
  helpModalNode.hidden = true;
  syncModalOpenState();
  const returnFocusNode = helpModalReturnFocusNode;
  helpModalReturnFocusNode = null;
  if (returnFocusNode instanceof HTMLElement && typeof returnFocusNode.focus === "function") {
    returnFocusNode.focus();
  } else if (helpBtn) {
    helpBtn.focus();
  }
}

function openWorkerSetupModal() {
  if (!workerSetupModalNode) return;
  workerSetupModalNode.hidden = false;
  syncModalOpenState();
}

function closeWorkerSetupModal() {
  if (!workerSetupModalNode) return;
  workerSetupModalNode.hidden = true;
  syncModalOpenState();
}

function setShareProjectStatus(message, isError = false) {
  if (!shareProjectStatusNode) return;
  shareProjectStatusNode.textContent = message || "";
  shareProjectStatusNode.style.color = isError ? "#a73527" : "#555";
}

function formatShareProjectUserLabel(user) {
  const email = cleanOptional(user?.email) || "";
  const displayName = cleanOptional(user?.display_name) || email || "User";
  const username = cleanOptional(user?.username);
  const details = [];
  if (username) details.push(`@${username}`);
  if (email && displayName.toLowerCase() !== email.toLowerCase()) details.push(email);
  return details.length ? `${displayName} (${details.join(" · ")})` : displayName;
}

function renderShareProjectOwner(owner) {
  if (!shareProjectOwnerNode) return;
  const label = formatShareProjectUserLabel(owner || {});
  shareProjectOwnerNode.textContent = label === "User" ? "Unknown owner" : label;
}

function renderShareableUserOptions(users, collaborators) {
  if (!shareProjectUserSelectNode) return;
  const collaboratorEmails = new Set(
    (Array.isArray(collaborators) ? collaborators : [])
      .map((row) => cleanOptional(row?.email)?.toLowerCase())
      .filter(Boolean)
  );
  const availableUsers = (Array.isArray(users) ? users : []).filter((candidate) => {
    const email = cleanOptional(candidate?.email)?.toLowerCase();
    return Boolean(email) && !collaboratorEmails.has(email);
  });

  state.shareProjectUsers = availableUsers;
  shareProjectUserSelectNode.innerHTML = "";

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = availableUsers.length ? "Select a user..." : "No additional users available";
  placeholder.disabled = true;
  placeholder.selected = true;
  shareProjectUserSelectNode.appendChild(placeholder);

  for (const candidate of availableUsers) {
    const option = document.createElement("option");
    option.value = String(candidate.email || "");
    option.textContent = formatShareProjectUserLabel(candidate);
    shareProjectUserSelectNode.appendChild(option);
  }

  shareProjectUserSelectNode.disabled = !availableUsers.length;
  if (shareProjectGrantBtn) {
    shareProjectGrantBtn.disabled = !availableUsers.length;
  }
}

function renderShareProjectMembers(collaborators) {
  if (!shareProjectMembersNode) return;
  const rows = Array.isArray(collaborators) ? collaborators : [];
  state.shareProjectCollaborators = rows;

  if (!rows.length) {
    shareProjectMembersNode.innerHTML = '<p class="share-project-empty">No collaborators yet.</p>';
    return;
  }

  shareProjectMembersNode.innerHTML = rows
    .map((row) => {
      const email = cleanOptional(row?.email) || "";
      const grantedAt = cleanOptional(row?.granted_at);
      const grantedBy = cleanOptional(row?.granted_by);
      const details = [];
      if (grantedAt) details.push(`Granted ${new Date(grantedAt).toLocaleString()}`);
      if (grantedBy) details.push(`by ${grantedBy}`);
      return `
        <div class="share-project-member-row">
          <div class="share-project-member-meta">
            <div class="share-project-member-name">${escapeHtml(email)}</div>
            <div class="share-project-member-detail">${escapeHtml(details.join(" · ") || "Collaborator")}</div>
          </div>
          <button type="button" class="worker-mini-btn share-project-remove-btn" data-email="${escapeHtml(email)}">Remove</button>
        </div>
      `;
    })
    .join("");
}

async function refreshShareProjectModal({ successMessage = "" } = {}) {
  if (!state.activeProjectRef) return;
  setShareProjectStatus("Loading sharing options...");
  if (shareProjectGrantBtn) shareProjectGrantBtn.disabled = true;
  if (shareProjectUserSelectNode) shareProjectUserSelectNode.disabled = true;

  try {
    const [accessData, usersData] = await Promise.all([
      requestJSON(`/projects/${encodeURIComponent(state.activeProjectRef)}/access`, "GET"),
      requestJSON(`/projects/${encodeURIComponent(state.activeProjectRef)}/shareable-users`, "GET"),
    ]);
    state.canManageActiveProject = Boolean(accessData.can_manage);
    if (shareProjectBtn) shareProjectBtn.disabled = !state.canManageActiveProject;
    state.shareProjectOwner = accessData.owner && typeof accessData.owner === "object" ? accessData.owner : {};
    renderShareProjectOwner(state.shareProjectOwner);
    renderShareProjectMembers(accessData.collaborators);
    renderShareableUserOptions(usersData.users, accessData.collaborators);
    setShareProjectStatus(successMessage);
  } catch (err) {
    if (shareProjectBtn) shareProjectBtn.disabled = true;
    renderShareProjectOwner({});
    renderShareProjectMembers([]);
    renderShareableUserOptions([], []);
    setShareProjectStatus(`Could not load sharing options: ${String(err)}`, true);
  }
}

function openShareProjectModal() {
  if (!shareProjectModalNode) return;
  shareProjectModalNode.hidden = false;
  syncModalOpenState();
  void refreshShareProjectModal();
}

function closeShareProjectModal() {
  if (!shareProjectModalNode) return;
  shareProjectModalNode.hidden = true;
  syncModalOpenState();
}

async function handleShareProjectGrant() {
  if (!state.activeProjectRef || !shareProjectUserSelectNode) return;
  const email = cleanOptional(shareProjectUserSelectNode.value)?.toLowerCase();
  if (!email) {
    setShareProjectStatus("Select a user to share with.", true);
    return;
  }

  if (shareProjectGrantBtn) shareProjectGrantBtn.disabled = true;
  try {
    await requestJSON(
      `/projects/${encodeURIComponent(state.activeProjectRef)}/access/grant`,
      "POST",
      { email }
    );
    const message = `Access granted to ${email}.`;
    setGenerateStatus(message);
    await refreshShareProjectModal({ successMessage: message });
  } catch (err) {
    setShareProjectStatus(`Share failed: ${String(err)}`, true);
  } finally {
    if (shareProjectGrantBtn && state.shareProjectUsers.length) {
      shareProjectGrantBtn.disabled = false;
    }
  }
}

async function handleShareProjectRemove(email) {
  if (!state.activeProjectRef || !email) return;
  try {
    await requestJSON(
      `/projects/${encodeURIComponent(state.activeProjectRef)}/access/revoke`,
      "POST",
      { email }
    );
    const message = `Access removed for ${email}.`;
    setGenerateStatus(message);
    await refreshShareProjectModal({ successMessage: message });
  } catch (err) {
    setShareProjectStatus(`Remove failed: ${String(err)}`, true);
  }
}

function bindProjectSharing() {
  if (shareProjectBtn) {
    shareProjectBtn.addEventListener("click", () => {
      if (!state.activeProjectRef) return;
      if (!state.canManageActiveProject) {
        setGenerateStatus("Only project owners can share this project.", true);
        return;
      }
      openShareProjectModal();
    });
  }

  if (shareProjectCloseBtn) {
    shareProjectCloseBtn.addEventListener("click", () => {
      closeShareProjectModal();
    });
  }

  if (shareProjectModalNode) {
    shareProjectModalNode.addEventListener("click", (event) => {
      if (event.target === shareProjectModalNode) {
        closeShareProjectModal();
      }
    });
  }

  if (shareProjectGrantBtn) {
    shareProjectGrantBtn.addEventListener("click", () => {
      void handleShareProjectGrant();
    });
  }

  if (shareProjectMembersNode) {
    shareProjectMembersNode.addEventListener("click", (event) => {
      const removeButton = event.target instanceof Element
        ? event.target.closest(".share-project-remove-btn")
        : null;
      if (!(removeButton instanceof HTMLButtonElement)) return;
      const email = cleanOptional(removeButton.dataset.email)?.toLowerCase();
      if (!email) return;
      void handleShareProjectRemove(email);
    });
  }
}

function bindHelpModal() {
  if (helpBtn) {
    helpBtn.addEventListener("click", () => {
      openHelpModal();
    });
  }

  if (helpCloseBtn) {
    helpCloseBtn.addEventListener("click", () => {
      closeHelpModal();
    });
  }

  if (helpModalNode) {
    helpModalNode.addEventListener("click", (event) => {
      if (event.target === helpModalNode) {
        closeHelpModal();
      }
    });
    helpModalNode.addEventListener("keydown", handleHelpModalKeydown);
  }

  if (helpTabListNode) {
    helpTabListNode.addEventListener("keydown", handleHelpTabKeydown);
  }

  for (const button of helpTabButtons) {
    button.addEventListener("click", () => {
      setHelpTab(button.dataset.helpTab || "overview", { focus: true });
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && helpModalNode && !helpModalNode.hidden) {
      closeHelpModal();
    }
  });
}

if (typeof window !== "undefined") {
  window.__radcastHelp = {
    bindHelpModal,
    focusHelpTabButton,
    handleHelpModalKeydown,
    handleHelpTabKeydown,
    helpTabNavigationTarget,
    normalizeHelpTab,
    setHelpTab,
  };
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
  return dontEnhanceAudioNode?.checked ? "none" : "studio_v18";
}

function selectedCaptionFormat() {
  if (!state.speechCleanupAvailable) return null;
  return normalizeCaptionFormat(captionFormatNode?.value);
}

function selectedCaptionQualityMode() {
  return normalizeCaptionQualityMode(captionQualityModeNode?.value);
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

function selectedFillerRemovalMode() {
  return "aggressive";
}

function updateSpeechCleanupControls() {
  const available = Boolean(state.speechCleanupAvailable);
  if (captionFormatNode) {
    captionFormatNode.disabled = !available;
  }
  if (captionQualityModeNode) {
    captionQualityModeNode.disabled = !available || !selectedCaptionFormat();
  }
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
  const cleanupBlock = reduceSilenceEnabledNode?.closest(".cleanup-block");
  if (cleanupBlock) {
    cleanupBlock.classList.toggle("speech-cleanup-disabled", !available);
  }
}

function updateCaptionFormatStatus() {
  if (!captionFormatStatusNode) return;
  if (!state.speechCleanupAvailable) {
    captionFormatStatusNode.textContent = state.speechCleanupDetail || "Caption export is not available on this machine.";
    return;
  }
  const format = selectedCaptionFormat();
  if (format === "srt") {
    captionFormatStatusNode.textContent = "Creates reviewed SRT captions from the final audio.";
    return;
  }
  if (format === "vtt") {
    captionFormatStatusNode.textContent = "Creates reviewed VTT captions from the final audio.";
    return;
  }
  captionFormatStatusNode.textContent = "Creates reviewed captions from the final audio.";
}

function updateGenerateButtonLabel() {
  if (!generateBtn) return;
  generateBtn.textContent = selectedEnhancementModelId() === "none" ? "Process audio" : "Enhance audio";
}

function updateSpeechCleanupStatusFromSelection() {
  if (!state.speechCleanupAvailable) {
    const unavailableMessage = state.speechCleanupDetail || "Speech cleanup is not available on this machine.";
    setReduceSilenceStatus(unavailableMessage, true);
    setSpeechCleanupStatus(unavailableMessage, true);
    return;
  }
  const maxSilenceSeconds = selectedMaxSilenceSeconds();
  setReduceSilenceStatus(
    maxSilenceSeconds !== null
      ? `Cuts longer pauses back to ${formatSilenceThresholdLabel(maxSilenceSeconds)}.`
      : "Cuts longer pauses back to the chosen length."
  );
  if (removeFillerWordsNode?.checked) {
    setSpeechCleanupStatus("Uses aggressive cleanup for filler words and hesitation runs.");
  } else {
    setSpeechCleanupStatus("Removes filler words and hesitation runs.");
  }
}

function updateEnhancementModelStatusFromSelection() {
  if (selectedEnhancementModelId() === "none") {
    setEnhancementModelStatus("Keeps the original audio quality.");
    return;
  }
  if (state.optimizedEnhancementAvailable === false) {
    setEnhancementModelStatus("RADcast Optimized is selected by default.");
    return;
  }
  setEnhancementModelStatus("Uses RADcast Optimized by default.");
}

async function loadEnhancementModels() {
  setEnhancementModelStatus("Uses RADcast Optimized by default.");
  setReduceSilenceStatus("Checking speech cleanup availability...");
  setSpeechCleanupStatus("Checking speech cleanup availability...");

  try {
    const data = await requestJSON("/enhancement/models", "GET");
    const models = Array.isArray(data.models) ? data.models : [];
    const optimizedModel = models.find((item) => item && item.id === "studio_v18");
    state.optimizedEnhancementAvailable = optimizedModel ? optimizedModel.available !== false : null;
    const speechCleanup = data.speech_cleanup && typeof data.speech_cleanup === "object" ? data.speech_cleanup : {};
    state.speechCleanupAvailable = speechCleanup.available !== false;
    state.speechCleanupDetail = String(speechCleanup.detail || "").trim();
    updateEnhancementModelStatusFromSelection();
    updateSpeechCleanupControls();
    updateSpeechCleanupStatusFromSelection();
    updateCaptionFormatStatus();
    updateGenerateButtonLabel();
  } catch (err) {
    state.optimizedEnhancementAvailable = null;
    state.speechCleanupAvailable = false;
    state.speechCleanupDetail = `Could not load speech cleanup availability: ${String(err)}`;
    updateEnhancementModelStatusFromSelection();
    updateSpeechCleanupControls();
    updateSpeechCleanupStatusFromSelection();
    updateCaptionFormatStatus();
    updateGenerateButtonLabel();
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
  state.selectedAudioDurationSeconds = null;
  renderTrimRail();
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
  state.selectedAudioTempKey = null;
  state.activeTrimAudioKey = null;
  state.activeTrimStartSeconds = 0;
  state.activeTrimEndSeconds = null;
  clearSourcePreview();
  if (audioFileInputNode) audioFileInputNode.value = "";
  if (savedSourceAudioSelectNode) savedSourceAudioSelectNode.value = "";
  if (audioDropzoneTitleNode) audioDropzoneTitleNode.textContent = "Drop audio here or click to choose";
  if (audioFileNameNode) audioFileNameNode.textContent = "No file selected.";
}

function markWorkspaceReady(projectRef, projectLabel) {
  clearProjectSettingsSaveTimer();
  closeShareProjectModal();
  state.activeProjectRef = projectRef;
  state.activeProjectLabel = projectLabel;

  if (projectGatewayNode) projectGatewayNode.hidden = true;
  if (workspaceNode) workspaceNode.classList.remove("workspace-hidden");
  if (switchProjectBtn) switchProjectBtn.hidden = false;
  if (shareProjectBtn) {
    shareProjectBtn.hidden = false;
    shareProjectBtn.disabled = true;
  }

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
  closeShareProjectModal();
  state.activeProjectRef = null;
  state.activeProjectLabel = null;
  state.canManageActiveProject = false;
  state.projectSettings = defaultProjectSettings();

  if (workspaceNode) workspaceNode.classList.add("workspace-hidden");
  if (projectGatewayNode) projectGatewayNode.hidden = false;
  if (switchProjectBtn) switchProjectBtn.hidden = true;
  if (shareProjectBtn) {
    shareProjectBtn.hidden = true;
    shareProjectBtn.disabled = true;
  }
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
  state.selectedAudioTempKey = makeTemporaryAudioKey(file);
  if (savedSourceAudioSelectNode) {
    savedSourceAudioSelectNode.value = "";
  }
  updateSourceAudioDeleteButtonState();
  setSourcePreviewFile(file || null);
  state.activeTrimAudioKey = null;
  state.activeTrimStartSeconds = 0;
  state.activeTrimEndSeconds = null;
  setSelectedAudioDuration(null, { restoreStored: true });
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

function selectUploadedAudioFile(file) {
  if (!file) {
    updateAudioSelection(null);
    setSavedSourceAudioStatus("Uploaded audio files are saved to this project for reuse.");
    queueProjectSettingsSave();
    return;
  }

  updateAudioSelection(file);
  if (audioFileInputNode) {
    // Allow choosing the same file again later if needed.
    audioFileInputNode.value = "";
  }
  setSavedSourceAudioStatus(`Using uploaded audio: ${file.name}. Saving it to this project...`);
  queueProjectSettingsSave();
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

function updateSourceAudioDeleteButtonState() {
  if (!deleteSourceAudioBtn || !savedSourceAudioSelectNode) return;
  deleteSourceAudioBtn.disabled = !cleanOptional(savedSourceAudioSelectNode.value);
}

function applySavedSourceAudioSelection(audioHash) {
  const sample = findSavedSourceAudioByHash(audioHash);
  if (!sample) {
    setSavedSourceAudioStatus("Saved audio file not found. Refresh and try again.", true);
    updateSourceAudioDeleteButtonState();
    return;
  }

  state.selectedAudioFile = null;
  state.selectedAudioHash = sample.audio_hash;
  state.selectedAudioTempKey = null;
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
  setSelectedAudioDuration(sample.duration_seconds, { restoreStored: true });
  updateSourceAudioDeleteButtonState();
}

async function loadSourceAudioSamples(preferredHash = null) {
  const projectId = state.activeProjectRef;
  if (!projectId || !savedSourceAudioSelectNode) return;

  savedSourceAudioSelectNode.innerHTML = '<option value="">Loading saved audio files...</option>';
  savedSourceAudioSelectNode.disabled = true;
  if (refreshSourceAudioBtn) refreshSourceAudioBtn.disabled = true;
  if (deleteSourceAudioBtn) deleteSourceAudioBtn.disabled = true;
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
      updateSourceAudioDeleteButtonState();
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
      updateSourceAudioDeleteButtonState();
    }
  } catch (err) {
    savedSourceAudioSelectNode.innerHTML = '<option value="">Unable to load saved audio files</option>';
    setSavedSourceAudioStatus(`Could not load saved audio files: ${String(err)}`, true);
  } finally {
    savedSourceAudioSelectNode.disabled = false;
    if (refreshSourceAudioBtn) refreshSourceAudioBtn.disabled = false;
    updateSourceAudioDeleteButtonState();
  }
}

async function handleDeleteSavedSourceAudio() {
  if (!state.activeProjectRef || !savedSourceAudioSelectNode) return;

  const selectedHash = cleanOptional(savedSourceAudioSelectNode.value);
  if (!selectedHash) return;
  const sample = findSavedSourceAudioByHash(selectedHash);
  if (!sample) {
    setSavedSourceAudioStatus("Saved audio file not found. Refresh and try again.", true);
    updateSourceAudioDeleteButtonState();
    return;
  }

  const sampleLabel = sample.source_filename || sample.audio_hash?.slice(0, 8) || "selected audio";
  const confirmed = window.confirm(`Delete this saved audio file?\n\n${sampleLabel}`);
  if (!confirmed) return;

  if (deleteSourceAudioBtn) deleteSourceAudioBtn.disabled = true;
  setSavedSourceAudioStatus("Deleting saved audio file...");

  try {
    await requestJSON(
      `/projects/${encodeURIComponent(state.activeProjectRef)}/source-audio/delete`,
      "POST",
      { audio_hash: sample.audio_hash }
    );

    const nextSettings = normalizeProjectSettings({
      ...(state.projectSettings || defaultProjectSettings()),
      trim_ranges_by_audio_hash: normalizeTrimRangesMap(state.projectSettings?.trim_ranges_by_audio_hash),
    });
    delete nextSettings.trim_ranges_by_audio_hash[sample.audio_hash];
    state.projectSettings = nextSettings;

    if (state.selectedAudioHash === sample.audio_hash) {
      state.selectedAudioHash = null;
      state.selectedAudioTempKey = null;
      state.activeTrimAudioKey = null;
      state.activeTrimStartSeconds = 0;
      state.activeTrimEndSeconds = null;
      if (!state.selectedAudioFile) {
        if (savedSourceAudioSelectNode) {
          savedSourceAudioSelectNode.value = "";
        }
        if (audioDropzoneTitleNode) {
          audioDropzoneTitleNode.textContent = "Drop audio here or click to choose";
        }
        if (audioFileNameNode) {
          audioFileNameNode.textContent = "No file selected.";
        }
        setSourcePreviewFile(null);
      }
      queueProjectSettingsSave();
    } else {
      queueProjectSettingsSave();
    }

    await loadSourceAudioSamples();
    setSavedSourceAudioStatus("Saved audio file deleted.");
  } catch (err) {
    setSavedSourceAudioStatus(`Could not delete saved audio file: ${String(err)}`, true);
    updateSourceAudioDeleteButtonState();
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
  const tempKey = state.selectedAudioTempKey;
  const tempTrimRange = tempKey ? normalizeTrimRangeEntry(state.transientTrimRangesByAudioKey[tempKey]) : null;
  state.selectedAudioFile = null;
  state.selectedAudioTempKey = null;
  state.selectedAudioHash = audioHash || null;
  if (audioHash && tempTrimRange) {
    const nextSettings = normalizeProjectSettings({
      ...(state.projectSettings || defaultProjectSettings()),
      trim_ranges_by_audio_hash: normalizeTrimRangesMap(state.projectSettings?.trim_ranges_by_audio_hash),
    });
    nextSettings.trim_ranges_by_audio_hash[audioHash] = tempTrimRange;
    state.projectSettings = nextSettings;
    delete state.transientTrimRangesByAudioKey[tempKey];
  }
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
    if (!state.canManageActiveProject) closeShareProjectModal();
  } catch {
    state.canManageActiveProject = false;
    shareProjectBtn.disabled = true;
    closeShareProjectModal();
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
  const allowEtaIncrease = flexibleEtaStages.has(nextStage) || flexibleEtaStages.has(state.etaStage);
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
    if (flexibleEtaStages.has(state.currentStage)) {
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
    if (state.computeMode === "worker") {
      return "Helper connected. Applying speech cleanup on your local helper device.";
    }
    return "Helper enhancement is done. Applying speech cleanup on the RADcast server (Mac mini).";
  }
  if (state.currentStage === "captions") {
    if (state.computeMode === "worker") {
      return "Helper connected. Generating captions on your local helper device.";
    }
    return "Audio processing is done. Generating captions on the RADcast server (Mac mini).";
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
  const rows = Array.isArray(logs) ? logs.map((entry) => String(entry || "").toLowerCase()) : [];
  const joinedLogs = rows.join(" ");
  const latestLog = rows.length ? rows[rows.length - 1] : "";
  const normalizedStage = String(stage || "").toLowerCase();
  if (normalizedStage === "queued_remote") return "waiting_worker";
  if (normalizedStage === "cleanup") {
    if (latestLog.includes("local helper device")) return "worker";
    if (latestLog.includes("radcast server")) return "server";
    return state.computeMode === "worker" ? "worker" : "server";
  }
  if (normalizedStage === "captions") {
    if (latestLog.includes("local helper device")) return "worker";
    if (latestLog.includes("radcast server")) return "server";
    return "server";
  }
  if (normalizedStage === "worker_running") return "worker";
  if (latestLog.includes("local helper device")) return "worker";
  if (latestLog.includes("radcast server")) return "server";
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
    const flexibleStage = flexibleEtaStages.has(state.currentStage);
    const increment = flexibleStage
      ? Math.max(0.04, Math.min(0.18, delta * 0.012))
      : Math.max(0.2, Math.min(0.9, delta * 0.12));
    state.displayProgress = Math.min(state.actualProgress, state.displayProgress + increment);
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
    setGenerateStatus(
      selectedEnhancementModelId() === "none"
        ? "Audio processing started. First run on a server can take longer while the model loads."
        : "Enhancement started. First run on a server can take longer while the model loads."
    );
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

    setGenerateStatus(selectedEnhancementModelId() === "none" ? "Queueing audio processing..." : "Queueing enhancement...");
    const payload = {
      project_id: state.activeProjectRef,
      output_format: String(outputFormatNode?.value || "mp3"),
      caption_format: selectedCaptionFormat(),
      caption_quality_mode: selectedCaptionQualityMode(),
      enhancement_model: selectedEnhancementModelId(),
      clip_start_seconds: currentTrimRangePayload()?.clip_start_seconds ?? null,
      clip_end_seconds: currentTrimRangePayload()?.clip_end_seconds ?? null,
      max_silence_seconds: selectedMaxSilenceSeconds(),
      remove_filler_words: Boolean(removeFillerWordsNode?.checked && state.speechCleanupAvailable),
      filler_removal_mode: selectedFillerRemovalMode(),
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
      const captionFormat = String(item.caption_format || "").trim().toLowerCase();
      const versionNumber = Number(item.version_number || 0);
      const summaryLabel = formatOutputSummary(item);
      const reviewNote = formatCaptionReviewNote(item);

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
      if (item.caption_download_url) {
        const captionLabel = captionFormat === "vtt" ? "Save VTT captions" : "Save SRT captions";
        actions.push(`<a href="${escapeHtml(item.caption_download_url)}" download>${escapeHtml(captionLabel)}</a>`);
      }
      if (item.caption_review_download_url) {
        actions.push(`<a href="${escapeHtml(item.caption_review_download_url)}" download>Save caption review</a>`);
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
          ${reviewNote ? `<div class="output-review-note">${escapeHtml(reviewNote)}</div>` : ""}
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

function formatCaptionReviewNote(item) {
  if (!item || !item.caption_review_required) return "";
  const lowConfidenceCount = Number(item.caption_low_confidence_segments || 0);
  const averageProbability = Number(item.caption_average_probability);
  if (lowConfidenceCount > 0 && Number.isFinite(averageProbability) && averageProbability > 0) {
    return `Caption review suggested: ${lowConfidenceCount} low-confidence lines (${Math.round(
      averageProbability * 100
    )}% average confidence).`;
  }
  if (lowConfidenceCount > 0) {
    return `Caption review suggested: ${lowConfidenceCount} low-confidence lines.`;
  }
  if (Number.isFinite(averageProbability) && averageProbability > 0) {
    return `Caption review suggested (${Math.round(averageProbability * 100)}% average confidence).`;
  }
  return "Caption review suggested.";
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
      selectUploadedAudioFile(file);
      void saveSelectedAudioFile(file).catch((err) => {
        setSavedSourceAudioStatus(`Could not save uploaded audio: ${String(err)}`, true);
      });
    }
  });

  audioFileInputNode.addEventListener("change", () => {
    const file = audioFileInputNode.files && audioFileInputNode.files.length ? audioFileInputNode.files[0] : null;
    selectUploadedAudioFile(file || null);
    if (file) {
      void saveSelectedAudioFile(file).catch((err) => {
        setSavedSourceAudioStatus(`Could not save uploaded audio: ${String(err)}`, true);
      });
    }
  });
}

function wireTrimRail() {
  if (!trimRailNode) return;

  const beginDrag = (mode, event) => {
    if (!getSelectedAudioDurationSeconds()) return;
    event.preventDefault();
    state.trimDragMode = mode;
    state.trimPointerId = event.pointerId;
  };

  if (trimStartHandleNode) {
    trimStartHandleNode.addEventListener("pointerdown", (event) => beginDrag("start", event));
  }
  if (trimEndHandleNode) {
    trimEndHandleNode.addEventListener("pointerdown", (event) => beginDrag("end", event));
  }

  trimRailNode.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Element)) return;
    if (event.target.closest(".trim-handle")) return;
    if (!getSelectedAudioDurationSeconds()) return;
    seekPreviewTo(trimSecondsFromClientX(event.clientX));
  });

  document.addEventListener("pointermove", (event) => {
    if (!state.trimDragMode) return;
    applyTrimHandlePosition(state.trimDragMode, trimSecondsFromClientX(event.clientX));
  });

  document.addEventListener("pointerup", (event) => {
    if (state.trimPointerId !== null && event.pointerId !== state.trimPointerId) return;
    state.trimDragMode = null;
    state.trimPointerId = null;
  });

  if (trimResetBtn) {
    trimResetBtn.addEventListener("click", () => {
      resetTrimRange();
    });
  }

  if (sourceAudioPreviewNode) {
    sourceAudioPreviewNode.addEventListener("loadedmetadata", () => {
      setSelectedAudioDuration(sourceAudioPreviewNode.duration, {
        restoreStored: state.activeTrimAudioKey !== (currentSelectedAudioKeyInfo()?.key || null),
      });
    });
    sourceAudioPreviewNode.addEventListener("durationchange", () => {
      if (!Number.isFinite(sourceAudioPreviewNode.duration)) return;
      setSelectedAudioDuration(sourceAudioPreviewNode.duration, {
        restoreStored: state.activeTrimAudioKey !== (currentSelectedAudioKeyInfo()?.key || null),
      });
    });
    sourceAudioPreviewNode.addEventListener("timeupdate", () => {
      enforcePreviewTrimBounds();
    });
    sourceAudioPreviewNode.addEventListener("seeking", () => {
      renderTrimRail();
    });
    sourceAudioPreviewNode.addEventListener("play", () => {
      const range = currentActiveTrimRange();
      if (!range) return;
      if (sourceAudioPreviewNode.currentTime < range.clip_start_seconds) {
        sourceAudioPreviewNode.currentTime = range.clip_start_seconds;
      } else if (sourceAudioPreviewNode.currentTime >= range.clip_end_seconds) {
        sourceAudioPreviewNode.currentTime = Math.max(
          range.clip_start_seconds,
          range.clip_end_seconds - Math.min(1, range.clip_end_seconds - range.clip_start_seconds)
        );
      }
      renderTrimRail();
    });
  }
}

async function init() {
  setupThemeToggle();
  setHelpTab(normalizeHelpTab(readStoredHelpTab()), { persist: false });
  bindHelpModal();
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

  bindProjectSharing();

  if (refreshSourceAudioBtn) {
    refreshSourceAudioBtn.addEventListener("click", () => {
      void loadSourceAudioSamples(savedSourceAudioSelectNode ? savedSourceAudioSelectNode.value : null);
    });
  }

  if (deleteSourceAudioBtn) {
    deleteSourceAudioBtn.addEventListener("click", () => {
      void handleDeleteSavedSourceAudio();
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
        state.selectedAudioTempKey = null;
        state.activeTrimAudioKey = null;
        state.activeTrimStartSeconds = 0;
        state.activeTrimEndSeconds = null;
        if (!state.selectedAudioFile) {
          clearSourcePreview();
          if (audioDropzoneTitleNode) audioDropzoneTitleNode.textContent = "Drop audio here or click to choose";
          if (audioFileNameNode) audioFileNameNode.textContent = "No file selected.";
        }
        setSavedSourceAudioStatus("Uploaded audio files are saved to this project for reuse.");
        updateSourceAudioDeleteButtonState();
        queueProjectSettingsSave();
        return;
      }
      applySavedSourceAudioSelection(audioHash);
      updateSourceAudioDeleteButtonState();
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
  if (captionFormatNode) {
    captionFormatNode.addEventListener("change", () => {
      updateSpeechCleanupControls();
      updateCaptionFormatStatus();
      queueProjectSettingsSave();
    });
  }
  if (dontEnhanceAudioNode) {
    dontEnhanceAudioNode.addEventListener("change", () => {
      updateEnhancementModelStatusFromSelection();
      updateSpeechCleanupStatusFromSelection();
      updateGenerateButtonLabel();
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
      updateSpeechCleanupControls();
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
  wireTrimRail();
}

if (!(typeof window !== "undefined" && window.__RADCAST_DISABLE_AUTOINIT__)) {
  void init();
}
