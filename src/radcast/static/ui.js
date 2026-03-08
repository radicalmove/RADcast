const projectGatewayNode = document.getElementById("project-gateway");
const workspaceNode = document.getElementById("workspace");
const switchProjectBtn = document.getElementById("switch-project-btn");
const shareProjectBtn = document.getElementById("share-project-btn");
const activeProjectChip = document.getElementById("active-project-chip");
const activeProjectLabelNode = document.getElementById("active-project-label");

const existingProjectSelectNode = document.getElementById("existing-project-select");
const refreshProjectsBtn = document.getElementById("refresh-projects-btn");
const projectGatewayStatusNode = document.getElementById("project-gateway-status");

const audioDropzoneNode = document.getElementById("audio-dropzone");
const audioFileInputNode = document.getElementById("input-audio-file");
const audioDropzoneTitleNode = document.getElementById("audio-dropzone-title");
const audioFileNameNode = document.getElementById("audio-file-name");

const outputFormatNode = document.getElementById("output-format");

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
  prepare: "Preparing audio",
  enhance: "Improving audio",
  finalize: "Saving audio",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const state = {
  activeProjectRef: null,
  activeProjectLabel: null,
  selectedAudioFile: null,
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

function resetAudioSelection() {
  state.selectedAudioFile = null;
  if (audioFileInputNode) audioFileInputNode.value = "";
  if (audioDropzoneTitleNode) audioDropzoneTitleNode.textContent = "Drop audio here or click to choose";
  if (audioFileNameNode) audioFileNameNode.textContent = "No file selected.";
}

function markWorkspaceReady(projectRef, projectLabel) {
  state.activeProjectRef = projectRef;
  state.activeProjectLabel = projectLabel;

  if (projectGatewayNode) projectGatewayNode.hidden = true;
  if (workspaceNode) workspaceNode.classList.remove("workspace-hidden");
  if (switchProjectBtn) switchProjectBtn.hidden = false;
  if (shareProjectBtn) shareProjectBtn.hidden = false;

  if (activeProjectChip) activeProjectChip.hidden = false;
  if (activeProjectLabelNode) activeProjectLabelNode.textContent = projectLabel;

  resetAudioSelection();
  setGenerateStatus("Upload an audio file, then click Enhance audio.");
  refreshProjectAccessInfo();
  loadOutputs();
}

function showProjectGateway() {
  state.activeProjectRef = null;
  state.activeProjectLabel = null;
  state.canManageActiveProject = false;

  if (workspaceNode) workspaceNode.classList.add("workspace-hidden");
  if (projectGatewayNode) projectGatewayNode.hidden = false;
  if (switchProjectBtn) switchProjectBtn.hidden = true;
  if (shareProjectBtn) shareProjectBtn.hidden = true;
  if (activeProjectChip) activeProjectChip.hidden = true;

  resetRunningState({ clearProgress: true });
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

async function loadProjects(preferredProjectRef = null) {
  if (!existingProjectSelectNode) return;
  existingProjectSelectNode.disabled = true;
  setGatewayStatus("Loading projects...");

  try {
    const data = await requestJSON("/projects", "GET");
    const projects = Array.isArray(data.projects) ? data.projects : [];

    existingProjectSelectNode.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = projects.length ? "Select a project" : "No projects yet";
    existingProjectSelectNode.appendChild(placeholder);

    projects.forEach((project) => {
      const option = document.createElement("option");
      option.value = String(project.project_ref || "");
      const projectLabel = String(project.project_id || "");
      const shared = Boolean(project.shared);
      const ownerLabel = String(project.owner_label || "").trim();
      const sharedSuffix = shared ? ` (shared${ownerLabel ? ` from ${ownerLabel}` : ""})` : "";
      option.textContent = `${projectLabel}${sharedSuffix}`;
      existingProjectSelectNode.appendChild(option);
    });

    if (preferredProjectRef) {
      existingProjectSelectNode.value = preferredProjectRef;
    }

    setGatewayStatus(projects.length ? "Choose a project to open." : "Create your first project.");
  } catch (err) {
    existingProjectSelectNode.innerHTML = '<option value="">Unable to load projects</option>';
    setGatewayStatus(`Could not load projects: ${String(err)}`, true);
  } finally {
    existingProjectSelectNode.disabled = false;
  }
}

async function openSelectedProject() {
  const projectRef = cleanOptional(existingProjectSelectNode?.value);
  if (!projectRef) return;
  const selected = existingProjectSelectNode?.selectedOptions?.[0];
  const label = selected ? selected.textContent.replace(/\s*\(shared.*\)$/i, "") : projectRef;
  markWorkspaceReady(projectRef, label || projectRef);
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
  if (currentRemaining === null || nextEtaSeconds <= currentRemaining - 3) {
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
    const label = state.currentStage === "queued" ? "waiting to start..." : "estimating...";
    progressEtaNode.textContent = `Time left to process: ${label}`;
    return;
  }

  if (remaining <= 0) {
    progressEtaNode.textContent = "Time left to process: finishing soon";
    return;
  }

  progressEtaNode.textContent = `Time left to process: ${formatEta(remaining)}`;
}

function updateProgressVisuals() {
  const clamped = Math.max(0, Math.min(100, state.displayProgress));
  if (progressWrapNode) progressWrapNode.hidden = false;
  if (progressFillNode) progressFillNode.style.width = `${clamped}%`;
  if (progressPercentNode) progressPercentNode.textContent = `${Math.round(clamped)}%`;
  if (progressStageNode) progressStageNode.textContent = stageLabels[state.currentStage] || "Processing";
  if (progressComputeNode) progressComputeNode.textContent = "Processing on: RADcast server";

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
  state.currentStage = nextStage;
  state.latestDetail = latestLogMessage(job.logs) || stageLabels[state.currentStage] || "Processing";
  if (Number.isFinite(Number(job.progress))) {
    state.actualProgress = Math.max(state.actualProgress, Number(job.progress) * 100);
  }
  syncEtaFromJob(nextStage, Number(job.eta_seconds));
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
      state.latestDetail = String(data.error || "Enhancement failed.");
      updateProgressVisuals();
      resetRunningState({ clearProgress: false });
      setGenerateStatus(`Enhancement failed: ${state.latestDetail}`, true);
      return;
    }

    if (status === "cancelled") {
      state.currentStage = "cancelled";
      state.actualProgress = 0;
      state.latestDetail = "Enhancement cancelled.";
      updateProgressVisuals();
      resetRunningState({ clearProgress: false });
      setGenerateStatus("Enhancement cancelled.");
      return;
    }

    updateProgressVisuals();
  } catch (err) {
    resetRunningState({ clearProgress: false });
    setGenerateStatus(`Job polling failed: ${String(err)}`, true);
  }
}

function startJobTracking(jobId) {
  resetRunningState({ clearProgress: false });
  state.activeJobId = jobId;
  state.jobStartedAtMs = Date.now();
  state.currentStage = "queued";
  state.actualProgress = 0;
  state.displayProgress = 0;
  state.latestDetail = "Queued for enhancement";
  state.etaStage = "queued";

  if (generateBtn) generateBtn.disabled = true;
  if (cancelBtn) cancelBtn.hidden = false;
  if (progressWrapNode) progressWrapNode.hidden = false;

  setGenerateStatus("Enhancement started. First run on a server can take longer while the model loads.");
  startProgressAnimation();
  state.pollTimer = setInterval(pollJob, 2000);
  void pollJob();
}

async function handleGenerate() {
  if (!state.activeProjectRef) {
    setGenerateStatus("Open a project first.", true);
    return;
  }
  if (!state.selectedAudioFile) {
    setGenerateStatus("Select an audio file first.", true);
    return;
  }

  try {
    setGenerateStatus("Uploading and queueing enhancement...");
    const payload = {
      project_id: state.activeProjectRef,
      input_audio_b64: await fileToBase64(state.selectedAudioFile),
      input_audio_filename: state.selectedAudioFile.name,
      output_format: String(outputFormatNode?.value || "mp3"),
    };

    const data = await requestJSON("/enhance/simple", "POST", payload);
    startJobTracking(String(data.job_id));
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

    outputListNode.innerHTML = outputs
      .map((item, idx) => {
        const created = item.created_at ? new Date(item.created_at).toLocaleString() : "";
        const playId = `play-${idx}`;
        const playerId = `player-${idx}`;
        return `
          <li class="output-item">
            <div class="output-header">
              <strong>${escapeHtml(item.output_name || "enhanced-audio")}</strong>
              <span>${escapeHtml(created)}</span>
            </div>
            <div class="output-actions">
              <button type="button" class="output-play-btn" data-play-id="${playId}" data-player-id="${playerId}" data-src="${escapeHtml(item.play_url || "")}">Play audio</button>
              <a href="${escapeHtml(item.download_url || "#")}" target="_blank" rel="noopener">Save audio as</a>
            </div>
            <audio id="${playerId}" controls hidden></audio>
            <code>${escapeHtml(item.output_path || "")}</code>
          </li>
        `;
      })
      .join("");

    bindOutputPlayButtons();
  } catch (err) {
    outputListNode.innerHTML = `<li class="output-item">Could not load outputs: ${escapeHtml(String(err))}</li>`;
  }
}

function bindOutputPlayButtons() {
  document.querySelectorAll(".output-play-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const playerId = String(btn.getAttribute("data-player-id") || "");
      const src = String(btn.getAttribute("data-src") || "");
      if (!playerId || !src) return;

      const player = document.getElementById(playerId);
      if (!(player instanceof HTMLAudioElement)) return;

      if (player.hidden || !player.src) {
        player.src = src;
        player.hidden = false;
        void player.play().catch(() => {});
        btn.textContent = "Hide player";
      } else {
        player.pause();
        player.hidden = true;
        btn.textContent = "Play audio";
      }
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
    if (file) updateAudioSelection(file);
  });

  audioFileInputNode.addEventListener("change", () => {
    const file = audioFileInputNode.files && audioFileInputNode.files.length ? audioFileInputNode.files[0] : null;
    updateAudioSelection(file || null);
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

  if (generateBtn) generateBtn.addEventListener("click", () => void handleGenerate());
  if (cancelBtn) cancelBtn.addEventListener("click", () => void handleCancel());

  wireDragAndDrop();
}

void init();
