const STORAGE_KEY = "agent_runtime_frontend_state_v1";

const state = {
  currentSessionId: null,
  messages: [],
  sessions: [],
  isSending: false,
  lastToolCalls: [],
  lastMemoryHits: [],
};

const elements = {
  thread: document.getElementById("thread"),
  messageInput: document.getElementById("messageInput"),
  composerForm: document.getElementById("composerForm"),
  sendBtn: document.getElementById("sendBtn"),
  newSessionBtn: document.getElementById("newSessionBtn"),
  sessionIdText: document.getElementById("sessionIdText"),
  sessionList: document.getElementById("sessionList"),
  healthBadge: document.getElementById("healthBadge"),
  maxRoundsInput: document.getElementById("maxRoundsInput"),
  refreshEventsBtn: document.getElementById("refreshEventsBtn"),
  refreshMemoriesBtn: document.getElementById("refreshMemoriesBtn"),
  toolCallsView: document.getElementById("toolCallsView"),
  memoryHitsView: document.getElementById("memoryHitsView"),
  eventsView: document.getElementById("eventsView"),
  memoriesView: document.getElementById("memoriesView"),
  messageTemplate: document.getElementById("messageTemplate"),
  skillInputs: Array.from(document.querySelectorAll('.skill-row input[type="checkbox"]')),
  quickPrompts: Array.from(document.querySelectorAll(".chip")),
};

function init() {
  hydrateState();
  bindEvents();
  renderAll();
  void checkHealth();
}

function bindEvents() {
  elements.composerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendMessage();
  });

  elements.messageInput.addEventListener("input", autoResizeTextarea);
  elements.messageInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await sendMessage();
    }
  });

  elements.newSessionBtn.addEventListener("click", () => {
    createNewSession();
  });

  elements.refreshEventsBtn.addEventListener("click", () => {
    void refreshEvents();
  });

  elements.refreshMemoriesBtn.addEventListener("click", () => {
    void refreshMemories();
  });

  for (const chip of elements.quickPrompts) {
    chip.addEventListener("click", () => {
      elements.messageInput.value = chip.dataset.prompt ?? "";
      autoResizeTextarea();
      elements.messageInput.focus();
    });
  }
}

function createNewSession() {
  if (state.currentSessionId && state.messages.length > 0) {
    persistCurrentSessionSnapshot();
  }
  state.currentSessionId = null;
  state.messages = [];
  state.lastToolCalls = [];
  state.lastMemoryHits = [];
  renderAll();
  persistState();
}

async function sendMessage() {
  const rawText = elements.messageInput.value;
  const message = rawText.trim();
  if (!message || state.isSending) {
    return;
  }

  appendMessage("user", message);
  elements.messageInput.value = "";
  autoResizeTextarea();
  setSending(true);

  const payload = {
    session_id: state.currentSessionId,
    message,
    skill_names: getSelectedSkills(),
    max_tool_rounds: clampInt(elements.maxRoundsInput.value, 0, 10, 3),
  };

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail ?? `HTTP ${response.status}`);
    }

    state.currentSessionId = data.session_id;
    state.lastToolCalls = Array.isArray(data.tool_calls) ? data.tool_calls : [];
    state.lastMemoryHits = Array.isArray(data.memory_hits) ? data.memory_hits : [];

    appendMessage("assistant", String(data.answer ?? ""));
    setJson(elements.toolCallsView, state.lastToolCalls);
    setJson(elements.memoryHitsView, state.lastMemoryHits);

    persistCurrentSessionSnapshot();
    renderSessionHeader();
    renderSessionList();
    persistState();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    appendMessage("error", `请求失败: ${detail}`);
  } finally {
    setSending(false);
  }
}

function appendMessage(role, content) {
  state.messages.push({
    role,
    content,
    ts: new Date().toISOString(),
  });
  renderThread();
}

function renderAll() {
  renderSessionHeader();
  renderThread();
  renderSessionList();
  setJson(elements.toolCallsView, state.lastToolCalls);
  setJson(elements.memoryHitsView, state.lastMemoryHits);
  if (!elements.eventsView.textContent) {
    setJson(elements.eventsView, []);
  }
  if (!elements.memoriesView.textContent) {
    setJson(elements.memoriesView, []);
  }
}

function renderSessionHeader() {
  elements.sessionIdText.textContent = state.currentSessionId ?? "(尚未创建)";
}

function renderThread() {
  elements.thread.innerHTML = "";

  if (state.messages.length === 0) {
    const placeholder = document.createElement("article");
    placeholder.className = "message assistant";
    placeholder.innerHTML = [
      '<div class="avatar"></div>',
      '<div class="content-wrap">',
      '<div class="meta">assistant</div>',
      '<div class="content">欢迎使用测试前端。你可以直接发消息测试 /api/chat，右侧查看 tool_calls、memory_hits、events 与 memories。</div>',
      "</div>",
    ].join("");
    elements.thread.appendChild(placeholder);
    return;
  }

  for (const message of state.messages) {
    const node = elements.messageTemplate.content.firstElementChild.cloneNode(true);
    node.classList.add(message.role);

    const meta = node.querySelector(".meta");
    const content = node.querySelector(".content");

    meta.textContent = `${message.role} · ${formatTime(message.ts)}`;
    content.textContent = message.content;

    elements.thread.appendChild(node);
  }

  elements.thread.scrollTop = elements.thread.scrollHeight;
}

function renderSessionList() {
  elements.sessionList.innerHTML = "";
  if (state.sessions.length === 0) {
    const empty = document.createElement("li");
    empty.className = "session-item";
    empty.innerHTML = '<div class="session-item-head">无历史</div><div class="session-item-body">开始一次对话后会记录在本地。</div>';
    elements.sessionList.appendChild(empty);
    return;
  }

  for (const snapshot of state.sessions) {
    const li = document.createElement("li");
    li.className = "session-item";
    if (snapshot.sessionId === state.currentSessionId) {
      li.classList.add("active");
    }
    li.innerHTML = [
      `<div class="session-item-head">${snapshot.sessionId}</div>`,
      `<div class="session-item-body">${escapeHtml(snapshot.preview || "(empty)")}</div>`,
    ].join("");
    li.addEventListener("click", () => {
      state.currentSessionId = snapshot.sessionId;
      state.messages = Array.isArray(snapshot.messages) ? snapshot.messages : [];
      renderAll();
      persistState();
    });
    elements.sessionList.appendChild(li);
  }
}

function persistCurrentSessionSnapshot() {
  if (!state.currentSessionId) {
    return;
  }

  const preview = [...state.messages]
    .reverse()
    .find((item) => item.role === "user")?.content;

  const existingIndex = state.sessions.findIndex((item) => item.sessionId === state.currentSessionId);
  const snapshot = {
    sessionId: state.currentSessionId,
    preview: (preview ?? "").slice(0, 100),
    updatedAt: new Date().toISOString(),
    messages: state.messages,
  };

  if (existingIndex >= 0) {
    state.sessions[existingIndex] = snapshot;
  } else {
    state.sessions.unshift(snapshot);
  }

  state.sessions.sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
  state.sessions = state.sessions.slice(0, 18);
}

function hydrateState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      state.currentSessionId = typeof parsed.currentSessionId === "string" ? parsed.currentSessionId : null;
      state.messages = Array.isArray(parsed.messages) ? parsed.messages : [];
      state.sessions = Array.isArray(parsed.sessions) ? parsed.sessions : [];
      state.lastToolCalls = Array.isArray(parsed.lastToolCalls) ? parsed.lastToolCalls : [];
      state.lastMemoryHits = Array.isArray(parsed.lastMemoryHits) ? parsed.lastMemoryHits : [];
    }
  } catch (error) {
    console.warn("Failed to restore local state", error);
  }
}

function persistState() {
  const payload = {
    currentSessionId: state.currentSessionId,
    messages: state.messages,
    sessions: state.sessions,
    lastToolCalls: state.lastToolCalls,
    lastMemoryHits: state.lastMemoryHits,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

async function refreshEvents() {
  if (!state.currentSessionId) {
    setJson(elements.eventsView, []);
    return;
  }

  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/events`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail ?? `HTTP ${response.status}`);
    }
    setJson(elements.eventsView, data);
  } catch (error) {
    setJson(elements.eventsView, { error: String(error) });
  }
}

async function refreshMemories() {
  try {
    const response = await fetch("/api/memories?limit=20");
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail ?? `HTTP ${response.status}`);
    }
    setJson(elements.memoriesView, data);
  } catch (error) {
    setJson(elements.memoriesView, { error: String(error) });
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    if (!response.ok || data.status !== "ok") {
      throw new Error("backend unhealthy");
    }
    elements.healthBadge.textContent = "在线";
    elements.healthBadge.className = "health-badge health-ok";
  } catch {
    elements.healthBadge.textContent = "离线";
    elements.healthBadge.className = "health-badge health-error";
  }
}

function setSending(isSending) {
  state.isSending = isSending;
  elements.sendBtn.disabled = isSending;
  elements.sendBtn.textContent = isSending ? "发送中..." : "发送";
}

function setJson(target, value) {
  target.textContent = JSON.stringify(value, null, 2);
}

function getSelectedSkills() {
  return elements.skillInputs.filter((item) => item.checked).map((item) => item.value);
}

function autoResizeTextarea() {
  const area = elements.messageInput;
  area.style.height = "auto";
  area.style.height = `${Math.min(area.scrollHeight, 190)}px`;
}

function clampInt(raw, min, max, fallback) {
  const parsed = Number.parseInt(String(raw), 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

function formatTime(raw) {
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return "--:--";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

init();
