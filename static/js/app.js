const elements = {
  startBtn: document.getElementById("start-btn"),
  stopBtn: document.getElementById("stop-btn"),
  video: document.getElementById("camera-feed"),
  canvas: document.getElementById("capture-canvas"),
  backendStatus: document.getElementById("backend-status"),
  cameraStatus: document.getElementById("camera-status"),
  requestState: document.getElementById("request-state"),
  requestDetails: document.getElementById("request-details"),
  responseViewer: document.getElementById("response-viewer"),
  lastCheck: document.getElementById("last-check"),
  uiState: document.getElementById("ui-state"),
  cadenceValue: document.getElementById("cadence-value"),
  liveDetectionBadge: document.getElementById("live-detection-badge"),
  frameRateLabel: document.getElementById("frame-rate-label"),
  fireAlertBanner: document.getElementById("fire-alert-banner"),
  dismissAlertBtn: document.getElementById("dismiss-alert-btn"),
  alertModal: document.getElementById("alert-modal"),
  closeAlertModalBtn: document.getElementById("close-alert-modal-btn"),
  alertModalText: document.getElementById("alert-modal-text"),
};

let mediaStream = null;
let isUploading = false;
let alertModalVisible = false;
let fireDetectedActive = false;
let scanTimeoutId = null;
let scanSequence = 0;
const scanIntervalMs = 600;

async function checkBackendHealth() {
  try {
    const response = await fetch(window.APP_CONFIG.healthEndpoint);
    const payload = await response.json();
    elements.backendStatus.textContent = `${payload.service} online`;
  } catch (error) {
    elements.backendStatus.textContent = "Backend unreachable";
  }
}

function updateStatus(state, details, className = "") {
  elements.requestState.textContent = state;
  elements.requestState.className = className;
  elements.requestDetails.textContent = details;
}

function setUiState(label) {
  elements.uiState.textContent = label;
}

function beautifyResponse(payload) {
  return JSON.stringify(payload, null, 2);
}

function updateDetectionBadge(label, badgeClass) {
  elements.liveDetectionBadge.textContent = label;
  elements.liveDetectionBadge.className = `live-detection-badge ${badgeClass}`;
}

function showFireAlert(message) {
  elements.fireAlertBanner.hidden = false;
  elements.alertModal.hidden = false;
  elements.alertModalText.textContent = message;
  document.body.classList.add("fire-alarm");
  setUiState("Fire Alert");
  updateStatus("Fire detected", message, "status-alert");
  updateDetectionBadge("Fire detected", "badge-alert");

  if (!alertModalVisible) {
    alertModalVisible = true;
  }
}

function hideFireAlert() {
  elements.fireAlertBanner.hidden = true;
  elements.alertModal.hidden = true;
  document.body.classList.remove("fire-alarm");
  alertModalVisible = false;
}

function resolveFireMessage(payload) {
  const message =
    payload?.detection?.message ||
    payload?.detection?.result ||
    payload?.detection?.status ||
    "The latest analysis indicates a possible fire event. Please inspect the area immediately.";

  return String(message);
}

function scheduleNextScan(delay = scanIntervalMs) {
  if (!mediaStream) {
    return;
  }

  if (scanTimeoutId) {
    window.clearTimeout(scanTimeoutId);
  }

  scanTimeoutId = window.setTimeout(() => {
    sendCurrentFrame();
  }, delay);
}

async function sendCurrentFrame() {
  if (!mediaStream) {
    return;
  }

  if (isUploading) {
    scheduleNextScan(120);
    return;
  }

  const width = elements.video.videoWidth;
  const height = elements.video.videoHeight;
  if (!width || !height) {
    scheduleNextScan(120);
    return;
  }

  isUploading = true;
  scanSequence += 1;
  const startedAt = performance.now();
  const context = elements.canvas.getContext("2d");
  elements.canvas.width = width;
  elements.canvas.height = height;
  context.drawImage(elements.video, 0, 0, width, height);

  const image = elements.canvas.toDataURL("image/jpeg", 0.82);
  updateStatus("Scanning", `Frame ${scanSequence} is being analyzed by the Flask relay.`, "status-live");
  updateDetectionBadge("Analyzing live frame", "badge-live");

  try {
    const response = await fetch(window.APP_CONFIG.analyzeEndpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ image }),
    });

    const payload = await response.json();
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (!response.ok) {
      throw new Error(payload.details || payload.error || "Unexpected response from server");
    }

    elements.responseViewer.textContent = beautifyResponse(payload);
    const elapsedMs = Math.max(1, Math.round(performance.now() - startedAt));
    const checkedAt = new Date();
    elements.lastCheck.textContent = `Last check: ${checkedAt.toLocaleTimeString()} • ${elapsedMs}ms`;

    if (payload.fire_detected) {
      const fireMessage = resolveFireMessage(payload);
      if (!fireDetectedActive) {
        showFireAlert(fireMessage);
        fireDetectedActive = true;
      }
      if (navigator.vibrate) {
        navigator.vibrate([180, 120, 180, 120, 260]);
      }
    } else {
      if (fireDetectedActive) {
        fireDetectedActive = false;
      }
      hideFireAlert();
      updateStatus("Area clear", "The latest AWS result does not indicate a fire event.", "status-ok");
      setUiState("Monitoring");
      updateDetectionBadge("No fire detected", "badge-safe");
    }
  } catch (error) {
    hideFireAlert();
    elements.responseViewer.textContent = beautifyResponse({ error: error.message });
    updateStatus("Detection failed", error.message, "status-error");
    updateDetectionBadge("Detection error", "badge-error");
  } finally {
    isUploading = false;
    scheduleNextScan();
  }
}

async function startScan() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: "environment",
      },
      audio: false,
    });

    elements.video.srcObject = mediaStream;
    elements.startBtn.disabled = true;
    elements.stopBtn.disabled = false;
    elements.cameraStatus.textContent = "Camera online";
    setUiState("Live");
    elements.cadenceValue.textContent = `${(scanIntervalMs / 1000).toFixed(1)}s`;
    elements.frameRateLabel.textContent = `Frame relay every ${(scanIntervalMs / 1000).toFixed(1)}s`;
    updateDetectionBadge("Live stream connected", "badge-live");

    updateStatus("Camera connected", "Continuous capture is active and frames will be sent about every 0.6 seconds.", "status-ok");

    await elements.video.play();
    await sendCurrentFrame();
  } catch (error) {
    updateStatus("Camera access denied", error.message, "status-error");
    elements.cameraStatus.textContent = "Camera blocked";
    setUiState("Error");
    updateDetectionBadge("Camera unavailable", "badge-error");
  }
}

function stopScan() {
  if (scanTimeoutId) {
    window.clearTimeout(scanTimeoutId);
    scanTimeoutId = null;
  }

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  elements.video.srcObject = null;
  elements.startBtn.disabled = false;
  elements.stopBtn.disabled = true;
  elements.cameraStatus.textContent = "Camera offline";
  elements.lastCheck.textContent = "Awaiting first scan";
  hideFireAlert();
  updateStatus("Monitoring paused", "Restart the live scan at any time.", "");
  setUiState("Idle");
  updateDetectionBadge("Awaiting scan", "badge-idle");
}

function enableTiltEffects() {
  const cards = document.querySelectorAll(".tilt-card");

  cards.forEach((card) => {
    card.addEventListener("mousemove", (event) => {
      const rect = card.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width;
      const py = (event.clientY - rect.top) / rect.height;
      const rotateY = (px - 0.5) * 10;
      const rotateX = (0.5 - py) * 10;
      card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-4px)`;
    });

    card.addEventListener("mouseleave", () => {
      card.style.transform = "";
    });
  });
}

elements.startBtn.addEventListener("click", startScan);
elements.stopBtn.addEventListener("click", stopScan);
elements.dismissAlertBtn.addEventListener("click", () => {
  elements.fireAlertBanner.hidden = true;
});
elements.closeAlertModalBtn.addEventListener("click", async () => {
  elements.alertModal.hidden = true;
  alertModalVisible = false;

  // Send acknowledgement SNS notification
  try {
    const response = await fetch(window.APP_CONFIG.acknowledgeEndpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        detection: JSON.parse(elements.responseViewer.textContent || "{}"),
      }),
    });

    if (response.ok) {
      const result = await response.json();
      console.log("Acknowledgement:", result.message);
    } else {
      console.error("Acknowledgement failed");
    }
  } catch (error) {
    console.error("Error sending acknowledgement:", error);
  }
});
window.addEventListener("beforeunload", stopScan);

checkBackendHealth();
enableTiltEffects();
