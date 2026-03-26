const DEFAULT_BACKEND = "http://127.0.0.1:5000";
const INTERVIEW_SECONDS = 30 * 60;
const MAX_TAB_SWITCHES = 3;
const YOLO_INTERVAL_MS = 2500;

function getBackendUrl() {
  return localStorage.getItem("backend_url") || DEFAULT_BACKEND;
}

function getSessionId() {
  return sessionStorage.getItem("session_id") || "";
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function formatTime(seconds) {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${pad2(m)}:${pad2(r)}`;
}

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Request failed: ${res.status}`);
  }
  return data;
}

function scoreClass(score) {
  if (score >= 8) return "ok";
  if (score >= 5) return "mid";
  return "bad";
}

let state = {
  role: sessionStorage.getItem("role") || "",
  questionCount: Number(sessionStorage.getItem("question_count") || 10),
  currentIndex: 0,
  currentQuestion: null,
  lastEvaluation: null,
  tabSwitches: 0,
  endAtMs: Date.now() + INTERVIEW_SECONDS * 1000,
  recognition: null,
  voiceActive: false,
  cameraStream: null,
  lastTabEventAt: 0,
  yoloTimer: null,
  voiceBaseText: "",
  mediaRecorder: null,
  recordedChunks: [],
  recordedVideoUrl: "",
  finishInProgress: false,
  frameBuffer: [],
  frameTimer: null,
};

function setAiTag() {
  const enabled = sessionStorage.getItem("gemini_enabled") === "1";
  const el = document.getElementById("aiTag");
  el.textContent = enabled ? "AI: Gemini enabled" : "AI: fallback mode";
  el.className = "tag " + (enabled ? "ok" : "warn");
}

function renderQuestion() {
  document.getElementById("title").textContent = `Interview — ${state.role}`;
  document.getElementById("subtitle").textContent = `Session: ${getSessionId()}`;
  document.getElementById("qIndex").textContent = String(state.currentIndex + 1);
  document.getElementById("qTotal").textContent = String(state.questionCount);

  const q = state.currentQuestion || {};
  document.getElementById("qDifficulty").textContent = (q.difficulty || "medium").toUpperCase();
  document.getElementById("qCategory").textContent = q.category || "general";
  document.getElementById("questionText").textContent = q.question || "";
}

function renderLastEval() {
  const wrap = document.getElementById("lastEvalWrap");
  if (!state.lastEvaluation) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "block";
  const score = Number(state.lastEvaluation.score || 0);
  const scoreEl = document.getElementById("lastScore");
  scoreEl.textContent = `${score}/10`;
  scoreEl.className = `score ${scoreClass(score)}`;

  document.getElementById("lastSaved").textContent = `saved ${new Date().toLocaleTimeString()}`;
  document.getElementById("lastEmotion").textContent = state.lastEvaluation.emotion || "Neutral";
  document.getElementById("lastFeedback").textContent = state.lastEvaluation.feedback || "";
  document.getElementById("lastCommunication").textContent = state.lastEvaluation.communication || "";

  const suggestionsBox = document.getElementById("lastSuggestions");
  if (suggestionsBox) {
    if (state.lastEvaluation.suggestions && state.lastEvaluation.suggestions.length > 0) {
      const ul = document.createElement("ul");
      ul.style.margin = "4px 0 0 16px";
      ul.style.padding = "0";
      state.lastEvaluation.suggestions.forEach(s => {
        const li = document.createElement("li");
        li.textContent = s;
        ul.appendChild(li);
      });
      suggestionsBox.innerHTML = "";
      suggestionsBox.appendChild(ul);
    } else {
      suggestionsBox.textContent = "-";
    }
  }

  const solutionBox = document.getElementById("lastSolution");
  if (solutionBox) {
    solutionBox.textContent = state.lastEvaluation.solution || "-";
  }

  const sentEl = document.getElementById("lastSentimentFeedback");
  if (sentEl) {
    sentEl.textContent = state.lastEvaluation.sentiment_feedback || "No visual/audio sentiment recorded.";
  }
}

function tickTimer() {
  const left = Math.ceil((state.endAtMs - Date.now()) / 1000);
  const timeLeftEl = document.getElementById("timeLeft");
  const timePillEl = document.getElementById("timePill");
  timeLeftEl.textContent = formatTime(left);
  timePillEl.classList.toggle("critical", left <= 300);
  if (left <= 0) {
    finishInterview();
  }
}

function bumpTabSwitches() {
  const now = Date.now();
  if (now - state.lastTabEventAt < 900) return; // debounce blur + visibilitychange double-fire
  state.lastTabEventAt = now;

  state.tabSwitches += 1;
  document.getElementById("tabSwitches").textContent = String(state.tabSwitches);
  showTabWarning(state.tabSwitches);
  if (state.tabSwitches >= MAX_TAB_SWITCHES) forceEndDueToProctoring();
}

function setupProctoring() {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) bumpTabSwitches();
  });
  window.addEventListener("blur", () => bumpTabSwitches());
}

function forceEndDueToProctoring() {
  const status = document.getElementById("voiceStatus");
  status.textContent = `Interview ended: tab switched ${MAX_TAB_SWITCHES} times.`;
  status.style.color = "#ff6b6b";
  finishInterview();
}

function showTabWarning(count) {
  const banner = document.getElementById("proctorBanner");
  const text = document.getElementById("proctorBannerText");
  banner.style.display = "block";
  banner.classList.remove("alert");
  if (count >= MAX_TAB_SWITCHES) {
    text.textContent = `Tab switch #${count}. Limit reached — ending interview.`;
    banner.style.borderColor = "rgba(255,107,107,.45)";
  } else {
    text.textContent = `Tab switch #${count}. Warning: after ${MAX_TAB_SWITCHES} tab switches, the interview will end automatically.`;
    banner.style.borderColor = "rgba(251,191,36,.35)";
  }
}

function setupVoice() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = document.getElementById("voiceBtn");
  const status = document.getElementById("voiceStatus");

  if (!SpeechRecognition) {
    btn.disabled = true;
    status.textContent = "Voice input not supported in this browser. Try Chrome or Edge.";
    return;
  }

  const rec = new SpeechRecognition();
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.continuous = true;
  rec.maxAlternatives = 1;

  rec.onstart = () => {
    status.textContent = "Listening...";
  };

  rec.onresult = (event) => {
    let finalTranscript = "";
    let interimTranscript = "";
    for (let i = 0; i < event.results.length; i++) {
      const spoken = event.results[i][0].transcript || "";
      if (event.results[i].isFinal) {
        finalTranscript += spoken + " ";
      } else {
        interimTranscript += spoken + " ";
      }
    }
    const box = document.getElementById("answerBox");
    const combined = [state.voiceBaseText, finalTranscript.trim(), interimTranscript.trim()].filter(Boolean).join(" ");
    box.value = combined;
  };

  rec.onerror = (e) => {
    status.textContent = `Voice error: ${e.error || "unknown"}`;
    state.voiceActive = false;
    btn.textContent = "Start voice";
  };

  rec.onend = () => {
    state.voiceActive = false;
    btn.textContent = "Start voice";
    status.textContent = "Recording stopped";
    state.voiceBaseText = "";
  };

  state.recognition = rec;

  btn.addEventListener("click", () => {
    if (!state.recognition) return;
    if (!state.voiceActive) {
      state.voiceActive = true;
      state.voiceBaseText = document.getElementById("answerBox").value.trim();
      btn.textContent = "Stop voice";
      status.textContent = "Listening...";
      try {
        state.recognition.start();
      } catch (e) {
        state.voiceActive = false;
        btn.textContent = "Start voice";
        status.textContent = `Voice error: ${e.message || "failed to start"}`;
      }
    } else {
      state.voiceActive = false;
      btn.textContent = "Start voice";
      status.textContent = "Recording stopped";
      state.recognition.stop();
    }
  });
}

async function setupCamera() {
  const video = document.getElementById("camPreview");
  const status = document.getElementById("camStatus");
  const yoloStatus = document.getElementById("yoloStatus");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    status.textContent = "Camera not supported in this browser.";
    status.style.color = "#ff6b6b";
    if (yoloStatus) {
      yoloStatus.textContent = "Vision proctoring off (no camera). Tab switch detection still runs.";
      yoloStatus.style.color = "#fbbf24";
    }
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    state.cameraStream = stream;
    video.srcObject = stream;
    status.textContent = "Camera is ON (local preview only).";
    if (yoloStatus) {
      yoloStatus.textContent = "Vision proctoring: waiting for frames…";
      yoloStatus.style.color = "";
    }

    startRecording(stream);
  } catch (e) {
    status.textContent = "Camera permission denied (interview can continue).";
    status.style.color = "#fbbf24";
    if (yoloStatus) {
      yoloStatus.textContent =
        "Vision proctoring off (camera blocked). Tab switch detection still runs. Allow camera to enable person/phone checks.";
      yoloStatus.style.color = "#fbbf24";
    }
  }
}

function pickMediaRecorderMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  const candidates = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  for (const t of candidates) {
    try {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) return t;
    } catch {}
  }
  return "";
}

function startRecording(stream) {
  const modal = document.getElementById("recordingModal");
  const statusEl = document.getElementById("recordingStatus");
  if (modal) modal.style.display = "none";

  if (typeof MediaRecorder === "undefined") {
    if (statusEl) statusEl.textContent = "Recording not supported in this browser.";
    return;
  }
  try {
    state.recordedChunks = [];
    state.recordedVideoUrl = "";
    const mimeType = pickMediaRecorderMimeType();
    const options = mimeType ? { mimeType } : undefined;
    state.mediaRecorder = new MediaRecorder(stream, options);

    if (statusEl) statusEl.textContent = "Recording in progress…";

    state.mediaRecorder.ondataavailable = (e) => {
      if (e && e.data && e.data.size > 0) state.recordedChunks.push(e.data);
    };

    state.mediaRecorder.onstop = () => {
      try {
        const blob = new Blob(state.recordedChunks, { type: "video/webm" });
        state.recordedVideoUrl = URL.createObjectURL(blob);
        const recordedVideo = document.getElementById("recordedVideo");
        if (recordedVideo) {
          recordedVideo.src = state.recordedVideoUrl;
        }
        if (statusEl) statusEl.textContent = "Recording ready.";
      } catch (err) {
        if (statusEl) statusEl.textContent = "Recording failed to generate playback.";
      }
    };

    state.mediaRecorder.start(2000); // emit chunks every ~2s
  } catch (e) {
    if (statusEl) statusEl.textContent = `Recording error: ${e.message || "unknown"}`;
  }
}

function captureFrameBase64(videoEl, maxW = 320) {
  const w = videoEl.videoWidth || 0;
  const h = videoEl.videoHeight || 0;
  if (!w || !h) return null;
  const scale = Math.min(1, maxW / w);
  const cw = Math.max(1, Math.round(w * scale));
  const ch = Math.max(1, Math.round(h * scale));
  const canvas = document.createElement("canvas");
  canvas.width = cw;
  canvas.height = ch;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(videoEl, 0, 0, cw, ch);
  return canvas.toDataURL("image/jpeg", 0.7);
}

function captureSnapshot() {
  const video = document.getElementById("camPreview");
  if (!state.cameraStream || document.hidden) return;
  const dataUrl = captureFrameBase64(video, 480);
  if (dataUrl) {
    state.frameBuffer.push(dataUrl);
    if (state.frameBuffer.length > 3) {
      state.frameBuffer.shift(); 
    }
  }
}

function startFrameSampler() {
  if (state.frameTimer) return;
  state.frameTimer = setInterval(captureSnapshot, 4000);
}

function stopFrameSampler() {
  if (state.frameTimer) clearInterval(state.frameTimer);
  state.frameTimer = null;
}

async function yoloTick() {
  const status = document.getElementById("yoloStatus");
  const video = document.getElementById("camPreview");
  if (!state.cameraStream || document.hidden) return;
  const dataUrl = captureFrameBase64(video);
  if (!dataUrl) return;

  try {
    const backend = getBackendUrl();
    const res = await fetchJson(`${backend}/api/proctor/detect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_base64: dataUrl, conf: 0.35 }),
    });
    if (!res.ok) {
      status.textContent = `YOLO: error (${res.error || "unknown"})`;
      status.style.color = "#fbbf24";
      return;
    }
    const counts = res.counts || {};
    const person = counts.person || 0;
    const phone = (counts["cell phone"] || 0) + (counts.phone || 0);
    const top = (res.detections || []).slice(0, 3).map((d) => `${d.name} (${Math.round(d.conf * 100)}%)`).join(", ");
    status.style.color = "";
    status.textContent = `YOLO: person=${person}, phone=${phone}${top ? ` • top: ${top}` : ""}`;

    // Strong warning when multiple people appear in camera frame.
    if (person > 1) {
      const banner = document.getElementById("proctorBanner");
      const text = document.getElementById("proctorBannerText");
      banner.style.display = "block";
      banner.classList.add("alert");
      banner.style.borderColor = "rgba(255,107,107,.65)";
      text.textContent = `ALERT: ${person} people detected in camera view. Only one person is allowed during the interview.`;
      return;
    }

    // Optional integrity hint (no auto-terminate here—only tab-switch terminates per your requirement)
    if (phone > 0) {
      const banner = document.getElementById("proctorBanner");
      const text = document.getElementById("proctorBannerText");
      banner.style.display = "block";
      banner.classList.remove("alert");
      banner.style.borderColor = "rgba(251,191,36,.35)";
      text.textContent = "Proctoring note: phone detected in camera view. Please keep the interview area clear.";
    }
  } catch (e) {
    status.textContent = `YOLO: unavailable (${e.message || "request failed"})`;
    status.style.color = "#fbbf24";
  }
}

function startYoloLoop() {
  if (state.yoloTimer) return;
  state.yoloTimer = setInterval(yoloTick, YOLO_INTERVAL_MS);
}

function stopYoloLoop() {
  if (!state.yoloTimer) return;
  clearInterval(state.yoloTimer);
  state.yoloTimer = null;
}

async function loadInitialQuestionFromSession() {
  const backend = getBackendUrl();
  const sessionId = getSessionId();
  if (!sessionId) {
    window.location.href = "./index.html";
    return;
  }

  // We already got the first question from /start, but we stored only session_id.
  // To keep the frontend simple, we re-start if missing; otherwise we ask report for the list size.
  // However, the backend doesn’t expose a “get current question” endpoint. So we rely on starting
  // and keeping state in memory for the duration of the session.
  //
  // This page is intended to be opened immediately after /start.
  const role = state.role;
  if (!role) {
    // If role was lost (e.g. refresh), we can’t reconstruct the session.
    window.location.href = "./index.html";
    return;
  }

  // Fetch roles just to confirm backend is reachable.
  await fetchJson(`${backend}/api/roles`);

  // We can’t fetch the question again without an endpoint, so we store it in sessionStorage on start.
  const q = JSON.parse(sessionStorage.getItem("current_question_json") || "null");
  if (!q) {
    window.location.href = "./index.html";
    return;
  }
  state.currentQuestion = q;
  state.currentIndex = Number(sessionStorage.getItem("current_index") || 0);
}

async function submitAnswer() {
  const backend = getBackendUrl();
  const sessionId = getSessionId();
  const answer = document.getElementById("answerBox").value || "";

  captureSnapshot();
  const imagesToSend = [...state.frameBuffer];
  state.frameBuffer = [];

  document.getElementById("submitBtn").disabled = true;
  document.getElementById("finishBtn").disabled = true;

  try {
    const data = await fetchJson(`${backend}/api/session/next`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        answer,
        images_b64: imagesToSend,
        proctoring: { tab_switches: state.tabSwitches },
      }),
    });

    if (data.last_evaluation) {
      state.lastEvaluation = data.last_evaluation;
      renderLastEval();
    }

    document.getElementById("answerBox").value = "";

    if (data.done) {
      window.location.href = `./result.html?session_id=${encodeURIComponent(sessionId)}`;
      return;
    }

    state.currentIndex = Number(data.current_index || 0);
    state.currentQuestion = data.current_question;
    sessionStorage.setItem("current_index", String(state.currentIndex));
    sessionStorage.setItem("current_question_json", JSON.stringify(state.currentQuestion));

    renderQuestion();
  } finally {
    document.getElementById("submitBtn").disabled = false;
    document.getElementById("finishBtn").disabled = false;
  }
}

async function finishInterview() {
  if (state.finishInProgress) return;
  state.finishInProgress = true;

  const sessionId = getSessionId();
  if (!sessionId) {
    window.location.href = "./index.html";
    return;
  }
  stopYoloLoop();
  stopFrameSampler();

  // Stop recording first so we can show playback.
  await new Promise((resolve) => {
    try {
      if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
        const prevOnStop = state.mediaRecorder.onstop;
        state.mediaRecorder.onstop = () => {
          try {
            if (typeof prevOnStop === "function") prevOnStop();
          } finally {
            resolve();
          }
        };
        state.mediaRecorder.stop();
      } else {
        resolve();
      }
    } catch {
      resolve();
    }
  });

  if (state.cameraStream) {
    for (const t of state.cameraStream.getTracks()) t.stop();
    state.cameraStream = null;
  }

  const modal = document.getElementById("recordingModal");
  const viewBtn = document.getElementById("viewResultsBtn");
  const shouldShowModal = modal && state.recordedVideoUrl;

  const redirect = () => {
    window.location.href = `./result.html?session_id=${encodeURIComponent(sessionId)}`;
  };

  if (shouldShowModal) {
    modal.style.display = "flex";
    if (viewBtn) {
      viewBtn.onclick = redirect;
    }
  } else {
    redirect();
  }
}

document.getElementById("submitBtn").addEventListener("click", () => {
  submitAnswer().catch((e) => {
    document.getElementById("voiceStatus").textContent = e.message || "Failed to submit.";
  });
});
document.getElementById("finishBtn").addEventListener("click", () => finishInterview());

setupProctoring();
setupVoice();
setupCamera().then(() => {
  startYoloLoop();
  startFrameSampler();
});
setAiTag();

setInterval(tickTimer, 250);
tickTimer();

loadInitialQuestionFromSession()
  .then(() => {
    renderQuestion();
    renderLastEval();
    document.getElementById("tabSwitches").textContent = String(state.tabSwitches);
  })
  .catch((e) => {
    document.getElementById("voiceStatus").textContent = e.message || "Failed to load session.";
  });

