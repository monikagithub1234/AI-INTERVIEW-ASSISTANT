const DEFAULT_BACKEND = "http://127.0.0.1:5000";

function getBackendUrl() {
  const saved = localStorage.getItem("backend_url");
  return saved || DEFAULT_BACKEND;
}

function setStatus(msg, isError = false) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.style.color = isError ? "#ff6b6b" : "";
}

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Request failed: ${res.status}`);
  }
  return data;
}

async function loadRoles() {
  const backend = getBackendUrl();
  document.getElementById("backendUrlLabel").textContent = backend;

  const data = await fetchJson(`${backend}/api/roles`);
  const select = document.getElementById("roleSelect");
  select.innerHTML = "";
  for (const r of data.roles || []) {
    const opt = document.createElement("option");
    opt.value = r;
    opt.textContent = r;
    select.appendChild(opt);
  }

  const toggleResume = () => {
    const resumeLabel = document.getElementById("resumeLabel");
    const resumeFile = document.getElementById("resumeFile");
    if (!resumeLabel || !resumeFile) return;
    const show = select.value === "HR";
    resumeLabel.style.display = show ? "" : "none";
    resumeFile.style.display = show ? "" : "none";
  };

  select.addEventListener("change", toggleResume);
  toggleResume();
}

async function healthCheck() {
  try {
    setStatus("Checking backend...");
    const backend = getBackendUrl();
    await fetchJson(`${backend}/api/health`);
    setStatus("Backend OK.");
  } catch (e) {
    setStatus(e.message || "Backend not reachable.", true);
  }
}

async function startInterview() {
  const backend = getBackendUrl();
  const role = document.getElementById("roleSelect").value;
  const questionCount = Number(document.getElementById("questionCount").value || 10);
  const resumeFileEl = document.getElementById("resumeFile");
  const resumeFile = role === "HR" && resumeFileEl && resumeFileEl.files.length > 0 ? resumeFileEl.files[0] : null;

  setStatus("Starting session...");

  const formData = new FormData();
  formData.append("role", role);
  formData.append("question_count", questionCount);
  if (resumeFile) {
    formData.append("resume", resumeFile);
  }

  const data = await fetchJson(`${backend}/api/session/start`, {
    method: "POST",
    body: formData,
  });

  localStorage.setItem("backend_url", backend);
  sessionStorage.setItem("session_id", data.session_id);
  sessionStorage.setItem("role", data.role);
  sessionStorage.setItem("question_count", String(data.question_count));
  sessionStorage.setItem("gemini_enabled", data.gemini_enabled ? "1" : "0");
  sessionStorage.setItem("current_index", String(data.current_index || 0));
  sessionStorage.setItem("current_question_json", JSON.stringify(data.current_question || null));

  window.location.href = "./interview.html";
}

document.getElementById("startBtn").addEventListener("click", () => {
  startInterview().catch((e) => setStatus(e.message || "Failed to start.", true));
});
document.getElementById("healthBtn").addEventListener("click", () => {
  healthCheck();
});

loadRoles().catch((e) => setStatus(e.message || "Failed to load roles.", true));



