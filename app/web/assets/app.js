const STORAGE_KEY = "agent_runtime_frontend_state_v1";
const THREAD_BOTTOM_THRESHOLD = 80;
const MAX_STREAM_EVENTS = 200;

const state = {
  currentSessionId: null,
  messages: [],
  sessions: [],
  isSending: false,
  lastToolCalls: [],
  lastMemoryHits: [],
  streamEvents: [],
  shouldAutoFollow: true,
};

const elements = {
  thread: document.getElementById("thread"),
  messageInput: document.getElementById("messageInput"),
  composerForm: document.getElementById("composerForm"),
  sendBtn: document.getElementById("sendBtn"),
  jumpToLatestBtn: document.getElementById("jumpToLatestBtn"),
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

  elements.thread.addEventListener("scroll", () => {
    state.shouldAutoFollow = isThreadNearBottom();
    updateJumpToLatestButton();
  });

  elements.jumpToLatestBtn.addEventListener("click", () => {
    scrollThreadToBottom(true);
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
  state.streamEvents = [];
  state.shouldAutoFollow = true;
  renderAll();
  persistState();
}

async function sendMessage() {
  const rawText = elements.messageInput.value;
  const message = rawText.trim();
  if (!message || state.isSending) {
    return;
  }

  state.shouldAutoFollow = true;
  appendMessage("user", message, { forceFollow: true });

  const assistantIndex = appendMessage("assistant", "", {
    thinking: "",
    streaming: true,
    forceFollow: true,
  });

  elements.messageInput.value = "";
  autoResizeTextarea();
  setSending(true);

  state.streamEvents = [];
  setJson(elements.eventsView, state.streamEvents);

  const payload = {
    session_id: state.currentSessionId,
    message,
    skill_names: getSelectedSkills(),
    max_tool_rounds: clampInt(elements.maxRoundsInput.value, 0, 10, 3),
  };

  try {
    let data;
    try {
      data = await sendMessageByStream(payload, assistantIndex);
    } catch (error) {
      if (error instanceof Error && error.allowFallback === true) {
        appendAssistantThinkingLine(assistantIndex, "流式接口不可用，已自动回退到非流式请求。");
        data = await sendMessageByJsonFallback(payload, assistantIndex);
      } else {
        throw error;
      }
    }

    state.currentSessionId = typeof data?.session_id === "string" ? data.session_id : state.currentSessionId;
    state.lastToolCalls = Array.isArray(data?.tool_calls) ? data.tool_calls : [];
    state.lastMemoryHits = Array.isArray(data?.memory_hits) ? data.memory_hits : [];

    const assistantMessage = state.messages[assistantIndex];
    if (assistantMessage) {
      assistantMessage.content = String(data?.answer ?? assistantMessage.content ?? "");
      assistantMessage.streaming = false;
      assistantMessage.ts = new Date().toISOString();
    }

    renderThread();
    setJson(elements.toolCallsView, state.lastToolCalls);
    setJson(elements.memoryHitsView, state.lastMemoryHits);

    persistCurrentSessionSnapshot();
    renderSessionHeader();
    renderSessionList();
    persistState();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    const assistantMessage = state.messages[assistantIndex];
    if (assistantMessage) {
      assistantMessage.role = "error";
      assistantMessage.content = `请求失败: ${detail}`;
      assistantMessage.streaming = false;
      assistantMessage.thinking = "";
      assistantMessage.ts = new Date().toISOString();
      renderThread();
    } else {
      appendMessage("error", `请求失败: ${detail}`);
    }
  } finally {
    setSending(false);
  }
}

async function sendMessageByStream(payload, assistantIndex) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw createStreamError(detail, true);
  }

  if (!response.body) {
    throw createStreamError("浏览器环境不支持流式读取响应体。", true);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let donePayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n").replaceAll("\r", "\n");
    const parsed = parseSseBuffer(buffer);
    buffer = parsed.rest;

    for (const item of parsed.events) {
      donePayload = handleStreamEvent(item, assistantIndex, donePayload);
    }
  }

  if (buffer.trim()) {
    const parsed = parseSseBuffer(`${buffer}\n\n`);
    for (const item of parsed.events) {
      donePayload = handleStreamEvent(item, assistantIndex, donePayload);
    }
  }

  if (!donePayload) {
    throw createStreamError("流式连接已结束，但未收到完成事件。", false);
  }

  return donePayload;
}

async function sendMessageByJsonFallback(payload, assistantIndex) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    throw new Error(String(data?.detail ?? `HTTP ${response.status}`));
  }

  const assistantMessage = state.messages[assistantIndex];
  if (assistantMessage) {
    assistantMessage.content = String(data?.answer ?? "");
    assistantMessage.streaming = false;
    assistantMessage.ts = new Date().toISOString();
    renderThread();
  }

  return data;
}

function handleStreamEvent(item, assistantIndex, donePayload) {
  let payload = {};
  if (item.data) {
    try {
      payload = JSON.parse(item.data);
    } catch {
      payload = { raw: item.data };
    }
  }

  switch (item.event) {
    case "session": {
      if (typeof payload.session_id === "string" && payload.session_id) {
        state.currentSessionId = payload.session_id;
        renderSessionHeader();
      }
      return donePayload;
    }
    case "run_event": {
      onRunEvent(payload, assistantIndex);
      return donePayload;
    }
    case "answer_delta": {
      appendAssistantDelta(assistantIndex, String(payload.delta ?? ""));
      return donePayload;
    }
    case "done": {
      return payload;
    }
    case "error": {
      throw createStreamError(String(payload.detail ?? "stream error"), false);
    }
    default:
      return donePayload;
  }
}

function onRunEvent(event, assistantIndex) {
  if (!event || typeof event !== "object") {
    return;
  }

  state.streamEvents.push(event);
  if (state.streamEvents.length > MAX_STREAM_EVENTS) {
    state.streamEvents = state.streamEvents.slice(-MAX_STREAM_EVENTS);
  }
  setJson(elements.eventsView, state.streamEvents);

  const line = formatThinkingLine(event);
  if (line) {
    appendAssistantThinkingLine(assistantIndex, line);
  }
}

function formatThinkingLine(event) {
  const eventType = String(event.type ?? "");
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const time = formatTime(event.created_at);

  if (eventType === "run_started") {
    return `[${time}] 开始执行任务`;
  }

  if (eventType === "assistant_thinking") {
    return `[${time}] 模型思考: ${shortenText(payload.content, 240)}`;
  }

  if (eventType === "tool_call") {
    const toolName = String(payload.name ?? "unknown_tool");
    const argsText = shortenText(safeJson(payload.arguments), 220);
    return `[${time}] 调用工具 ${toolName}(${argsText})`;
  }

  if (eventType === "tool_result") {
    const toolName = String(payload.tool_name ?? "unknown_tool");
    const status = payload.success ? "成功" : "失败";
    return `[${time}] 工具${status} ${toolName}: ${shortenText(payload.content, 220)}`;
  }

  if (eventType === "run_finished") {
    return `[${time}] 执行完成，正在整理答案`;
  }

  return null;
}

function appendAssistantDelta(assistantIndex, delta) {
  const message = state.messages[assistantIndex];
  if (!message || message.role !== "assistant") {
    return;
  }
  message.content = `${String(message.content ?? "")}${delta}`;
  message.streaming = true;
  renderThread();
}

function appendAssistantThinkingLine(assistantIndex, line) {
  const message = state.messages[assistantIndex];
  if (!message || message.role !== "assistant") {
    return;
  }
  const content = String(line ?? "").trim();
  if (!content) {
    return;
  }
  const existing = String(message.thinking ?? "");
  message.thinking = existing ? `${existing}\n${content}` : content;
  renderThread();
}

function parseSseBuffer(buffer) {
  const events = [];
  let rest = buffer;

  while (true) {
    const separator = rest.indexOf("\n\n");
    if (separator < 0) {
      break;
    }

    const block = rest.slice(0, separator);
    rest = rest.slice(separator + 2);

    if (!block.trim()) {
      continue;
    }

    let eventName = "message";
    const dataLines = [];

    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim() || "message";
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }

    events.push({ event: eventName, data: dataLines.join("\n") });
  }

  return { events, rest };
}

function appendMessage(role, content, options = {}) {
  const message = {
    role,
    content: String(content ?? ""),
    ts: new Date().toISOString(),
    thinking: typeof options.thinking === "string" ? options.thinking : "",
    streaming: Boolean(options.streaming),
  };
  state.messages.push(message);

  if (options.forceFollow !== false) {
    state.shouldAutoFollow = true;
  }

  renderThread();
  return state.messages.length - 1;
}

function renderAll() {
  renderSessionHeader();
  renderThread();
  renderSessionList();
  setJson(elements.toolCallsView, state.lastToolCalls);
  setJson(elements.memoryHitsView, state.lastMemoryHits);
  setJson(elements.eventsView, state.streamEvents);
  if (!elements.memoriesView.textContent) {
    setJson(elements.memoriesView, []);
  }
}

function renderSessionHeader() {
  elements.sessionIdText.textContent = state.currentSessionId ?? "(尚未创建)";
}

function renderThread() {
  const shouldFollow = state.shouldAutoFollow || isThreadNearBottom();

  elements.thread.innerHTML = "";

  if (state.messages.length === 0) {
    const placeholder = document.createElement("article");
    placeholder.className = "message assistant";
    placeholder.innerHTML = [
      '<div class="avatar"></div>',
      '<div class="content-wrap">',
      '<div class="meta">assistant</div>',
      '<div class="content">欢迎使用测试前端。你可以直接发消息测试 /api/chat/stream，右侧查看 tool_calls、memory_hits、events 与 memories。</div>',
      "</div>",
    ].join("");
    elements.thread.appendChild(placeholder);
    updateJumpToLatestButton();
    return;
  }

  for (const message of state.messages) {
    const node = elements.messageTemplate.content.firstElementChild.cloneNode(true);
    node.classList.add(message.role);

    const meta = node.querySelector(".meta");
    const content = node.querySelector(".content");
    const thinkingBlock = node.querySelector(".thinking-block");
    const thinkingContent = node.querySelector(".thinking-content");

    const streamTag = message.streaming && message.role === "assistant" ? " · 输出中" : "";
    meta.textContent = `${message.role} · ${formatTime(message.ts)}${streamTag}`;
    content.textContent = String(message.content ?? "");

    const thinkingText = String(message.thinking ?? "").trim();
    if (message.role === "assistant" && thinkingText) {
      thinkingContent.textContent = thinkingText;
      thinkingBlock.open = Boolean(message.streaming);
    } else {
      thinkingBlock.remove();
    }

    elements.thread.appendChild(node);
  }

  if (shouldFollow) {
    scrollThreadToBottom(false);
  } else {
    updateJumpToLatestButton();
  }
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
      state.messages = normalizeMessages(snapshot.messages);
      state.streamEvents = [];
      state.shouldAutoFollow = true;
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

  const preview = [...state.messages].reverse().find((item) => item.role === "user")?.content;

  const existingIndex = state.sessions.findIndex((item) => item.sessionId === state.currentSessionId);
  const snapshot = {
    sessionId: state.currentSessionId,
    preview: (preview ?? "").slice(0, 100),
    updatedAt: new Date().toISOString(),
    messages: state.messages.map((item) => ({ ...item, streaming: false })),
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
      state.messages = normalizeMessages(parsed.messages);
      state.sessions = normalizeSessions(parsed.sessions);
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
    messages: state.messages.map((item) => ({ ...item, streaming: false })),
    sessions: state.sessions,
    lastToolCalls: state.lastToolCalls,
    lastMemoryHits: state.lastMemoryHits,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

async function refreshEvents() {
  if (!state.currentSessionId) {
    state.streamEvents = [];
    setJson(elements.eventsView, state.streamEvents);
    return;
  }

  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/events`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail ?? `HTTP ${response.status}`);
    }
    state.streamEvents = Array.isArray(data) ? data : [];
    setJson(elements.eventsView, state.streamEvents);
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

function isThreadNearBottom(threshold = THREAD_BOTTOM_THRESHOLD) {
  const { scrollHeight, scrollTop, clientHeight } = elements.thread;
  const gap = scrollHeight - scrollTop - clientHeight;
  return gap <= threshold;
}

function scrollThreadToBottom(smooth) {
  elements.thread.scrollTo({ top: elements.thread.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  state.shouldAutoFollow = true;
  updateJumpToLatestButton();
}

function updateJumpToLatestButton() {
  const shouldShow = state.messages.length > 0 && !isThreadNearBottom();
  elements.jumpToLatestBtn.classList.toggle("show", shouldShow);
}

function normalizeMessages(items) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      role: typeof item.role === "string" ? item.role : "assistant",
      content: String(item.content ?? ""),
      ts: typeof item.ts === "string" ? item.ts : new Date().toISOString(),
      thinking: typeof item.thinking === "string" ? item.thinking : "",
      streaming: false,
    }));
}

function normalizeSessions(items) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      sessionId: typeof item.sessionId === "string" ? item.sessionId : "",
      preview: typeof item.preview === "string" ? item.preview : "",
      updatedAt: typeof item.updatedAt === "string" ? item.updatedAt : new Date().toISOString(),
      messages: normalizeMessages(item.messages),
    }))
    .filter((item) => item.sessionId);
}

function shortenText(value, maxLen) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "";
  }
  if (text.length <= maxLen) {
    return text;
  }
  return `${text.slice(0, maxLen)}...`;
}

function safeJson(value) {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function readErrorDetail(response) {
  const text = await response.text();
  if (!text) {
    return `HTTP ${response.status}`;
  }
  try {
    const data = JSON.parse(text);
    return String(data?.detail ?? text);
  } catch {
    return text;
  }
}

function createStreamError(message, allowFallback) {
  const error = new Error(message);
  error.allowFallback = allowFallback;
  return error;
}

init();
