const STORAGE_KEY = "agent_runtime_frontend_state";
const THREAD_BOTTOM_THRESHOLD = 80;
const MAX_STREAM_EVENTS = 200;
const MENTION_MAX_ITEMS = 8;
const COMPOSER_ACTIONS = [
  {
    id: "upload_file",
    label: "上传文件",
    description: "PDF / Markdown / JSON / TXT",
    accept: ".pdf,.md,.markdown,.json,.txt",
  },
  {
    id: "upload_image",
    label: "上传图片",
    description: "PNG / JPG / JPEG / WEBP",
    accept: ".png,.jpg,.jpeg,.webp",
  },
];

const state = {
  currentSessionId: null,
  messages: [],
  sessions: [],
  isSending: false,
  isUploading: false,
  lastToolCalls: [],
  lastMemoryHits: [],
  streamEvents: [],
  sessionArtifacts: [],
  activeArtifactIds: [],
  shouldAutoFollow: true,
  uploadMenuOpen: false,
  pendingUploadActionId: "upload_file",
  mentionOpen: false,
  mentionCandidates: [],
  mentionSelectedIndex: 0,
  mentionTriggerIndex: -1,
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
  refreshArtifactsBtn: document.getElementById("refreshArtifactsBtn"),
  refreshEventsBtn: document.getElementById("refreshEventsBtn"),
  refreshMemoriesBtn: document.getElementById("refreshMemoriesBtn"),
  composerUploadBtn: document.getElementById("composerUploadBtn"),
  composerUploadMenu: document.getElementById("composerUploadMenu"),
  composerFileInput: document.getElementById("composerFileInput"),
  composerInputWrap: document.getElementById("composerInputWrap"),
  mentionMenu: document.getElementById("mentionMenu"),
  uploadStatusText: document.getElementById("uploadStatusText"),
  sessionArtifactsList: document.getElementById("sessionArtifactsList"),
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
  renderComposerUploadMenu();
  bindEvents();
  renderAll();
  setUploading(false);
  hideMentionMenu();
  void checkHealth();
  void refreshSessionArtifacts();
}

function bindEvents() {
  elements.composerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendMessage();
  });

  elements.messageInput.addEventListener("input", () => {
    autoResizeTextarea();
    updateMentionMenuFromInput();
  });
  elements.messageInput.addEventListener("click", () => {
    updateMentionMenuFromInput();
  });
  elements.messageInput.addEventListener("keyup", (event) => {
    if (event.key === "ArrowUp" || event.key === "ArrowDown" || event.key === "Enter" || event.key === "Escape") {
      return;
    }
    updateMentionMenuFromInput();
  });

  elements.messageInput.addEventListener("keydown", async (event) => {
    if (event.key === "Escape" && state.uploadMenuOpen) {
      event.preventDefault();
      closeComposerUploadMenu();
      return;
    }

    if (state.mentionOpen) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveMentionSelection(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        moveMentionSelection(-1);
        return;
      }
      if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
        event.preventDefault();
        await selectMentionCandidate(state.mentionSelectedIndex);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        hideMentionMenu();
        return;
      }
    }

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

  elements.refreshArtifactsBtn.addEventListener("click", () => {
    void refreshSessionArtifacts();
  });

  elements.refreshMemoriesBtn.addEventListener("click", () => {
    void refreshMemories();
  });

  elements.composerUploadBtn.addEventListener("click", () => {
    if (state.isSending || state.isUploading) {
      return;
    }
    toggleComposerUploadMenu();
  });

  elements.composerFileInput.addEventListener("change", () => {
    const selected = elements.composerFileInput.files?.[0];
    if (!selected) {
      return;
    }
    closeComposerUploadMenu();
    void uploadSelectedFile(selected);
  });

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Node ? event.target : null;
    if (!target) {
      return;
    }
    if (
      state.uploadMenuOpen &&
      !elements.composerUploadBtn.contains(target) &&
      !elements.composerUploadMenu.contains(target)
    ) {
      closeComposerUploadMenu();
    }
    if (
      state.mentionOpen &&
      !elements.mentionMenu.contains(target) &&
      !elements.messageInput.contains(target)
    ) {
      hideMentionMenu();
    }
  });

  for (const chip of elements.quickPrompts) {
    chip.addEventListener("click", () => {
      elements.messageInput.value = chip.dataset.prompt ?? "";
      autoResizeTextarea();
      elements.messageInput.focus();
    });
  }
}

function renderComposerUploadMenu() {
  elements.composerUploadMenu.innerHTML = "";
  for (const action of COMPOSER_ACTIONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "composer-upload-item";
    button.setAttribute("role", "menuitem");
    button.dataset.actionId = action.id;

    const title = document.createElement("span");
    title.className = "composer-upload-item-title";
    title.textContent = action.label;

    const desc = document.createElement("span");
    desc.className = "composer-upload-item-desc";
    desc.textContent = action.description;

    button.appendChild(title);
    button.appendChild(desc);
    button.addEventListener("click", () => {
      openUploadPicker(action.id);
    });
    elements.composerUploadMenu.appendChild(button);
  }
  closeComposerUploadMenu();
}

function toggleComposerUploadMenu() {
  if (state.uploadMenuOpen) {
    closeComposerUploadMenu();
    return;
  }
  openComposerUploadMenu();
}

function openComposerUploadMenu() {
  if (state.isSending || state.isUploading) {
    return;
  }
  hideMentionMenu();
  state.uploadMenuOpen = true;
  elements.composerUploadMenu.classList.add("show");
  elements.composerUploadMenu.setAttribute("aria-hidden", "false");
  elements.composerUploadBtn.setAttribute("aria-expanded", "true");
}

function closeComposerUploadMenu() {
  state.uploadMenuOpen = false;
  elements.composerUploadMenu.classList.remove("show");
  elements.composerUploadMenu.setAttribute("aria-hidden", "true");
  elements.composerUploadBtn.setAttribute("aria-expanded", "false");
}

function openUploadPicker(actionId) {
  if (state.isSending || state.isUploading) {
    return;
  }
  const action = getComposerAction(actionId);
  state.pendingUploadActionId = action.id;
  elements.composerFileInput.accept = action.accept;
  closeComposerUploadMenu();
  elements.composerFileInput.click();
}

function getComposerAction(actionId) {
  for (const action of COMPOSER_ACTIONS) {
    if (action.id === actionId) {
      return action;
    }
  }
  return COMPOSER_ACTIONS[0];
}

function updateMentionMenuFromInput() {
  const text = elements.messageInput.value;
  const cursor = elements.messageInput.selectionStart ?? text.length;
  const mentionContext = extractMentionContext(text, cursor);
  if (!mentionContext) {
    hideMentionMenu();
    return;
  }
  const candidates = buildMentionCandidates(mentionContext.query);
  if (candidates.length === 0) {
    hideMentionMenu();
    return;
  }
  state.mentionOpen = true;
  state.mentionCandidates = candidates;
  state.mentionSelectedIndex = 0;
  state.mentionTriggerIndex = mentionContext.triggerIndex;
  renderMentionMenu();
}

function extractMentionContext(text, cursor) {
  if (!text || cursor <= 0) {
    return null;
  }
  const prefix = text.slice(0, cursor);
  const triggerIndex = prefix.lastIndexOf("@");
  if (triggerIndex < 0) {
    return null;
  }
  const prev = triggerIndex === 0 ? "" : prefix[triggerIndex - 1];
  if (prev && !/\s|[([{|,，。:：]/.test(prev)) {
    return null;
  }
  const query = prefix.slice(triggerIndex + 1);
  if (/\s/.test(query)) {
    return null;
  }
  return { triggerIndex, query: query.replaceAll("[", "").replaceAll("]", "") };
}

function buildMentionCandidates(rawQuery) {
  const query = String(rawQuery ?? "").trim().toLowerCase();
  const activeSet = new Set(state.activeArtifactIds);
  const items = Array.isArray(state.sessionArtifacts) ? state.sessionArtifacts : [];
  const filtered = items.filter((item) => {
    const title = String(item?.title ?? "");
    const artifactId = String(item?.artifact_id ?? "");
    if (!title || !artifactId) {
      return false;
    }
    if (!query) {
      return true;
    }
    return title.toLowerCase().includes(query) || artifactId.toLowerCase().includes(query);
  });

  filtered.sort((left, right) => {
    const leftActive = activeSet.has(left.artifact_id) ? 1 : 0;
    const rightActive = activeSet.has(right.artifact_id) ? 1 : 0;
    if (leftActive !== rightActive) {
      return rightActive - leftActive;
    }
    const leftTime = Date.parse(String(left.created_at ?? "")) || 0;
    const rightTime = Date.parse(String(right.created_at ?? "")) || 0;
    return rightTime - leftTime;
  });

  return filtered.slice(0, MENTION_MAX_ITEMS);
}

function renderMentionMenu() {
  elements.mentionMenu.innerHTML = "";
  if (!state.mentionOpen || state.mentionCandidates.length === 0) {
    hideMentionMenu();
    return;
  }

  for (let index = 0; index < state.mentionCandidates.length; index += 1) {
    const candidate = state.mentionCandidates[index];
    const item = document.createElement("button");
    item.type = "button";
    item.className = "mention-item";
    if (index === state.mentionSelectedIndex) {
      item.classList.add("active");
    }
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", index === state.mentionSelectedIndex ? "true" : "false");

    const title = document.createElement("span");
    title.className = "mention-item-title";
    title.textContent = candidate.title;

    const meta = document.createElement("span");
    meta.className = "mention-item-meta";
    const mediaTag = String(candidate.media_type ?? "").startsWith("image/") ? "图片" : "资料";
    meta.textContent = `${mediaTag} · ${candidate.artifact_id} · ${candidate.status}`;

    item.appendChild(title);
    item.appendChild(meta);

    item.addEventListener("mousedown", (event) => {
      event.preventDefault();
    });
    item.addEventListener("click", () => {
      void selectMentionCandidate(index);
    });
    elements.mentionMenu.appendChild(item);
  }

  elements.mentionMenu.classList.add("show");
  elements.mentionMenu.setAttribute("aria-hidden", "false");
}

function moveMentionSelection(offset) {
  if (!state.mentionOpen || state.mentionCandidates.length === 0) {
    return;
  }
  const size = state.mentionCandidates.length;
  state.mentionSelectedIndex = (state.mentionSelectedIndex + offset + size) % size;
  renderMentionMenu();
}

async function selectMentionCandidate(index) {
  const candidate = state.mentionCandidates[index];
  if (!candidate) {
    return;
  }
  const area = elements.messageInput;
  const currentValue = area.value;
  const selectionStart = area.selectionStart ?? currentValue.length;
  const start = state.mentionTriggerIndex >= 0 ? state.mentionTriggerIndex : selectionStart;
  const mentionToken = `@[${candidate.title}] `;
  area.value = `${currentValue.slice(0, start)}${mentionToken}${currentValue.slice(selectionStart)}`;
  const cursor = start + mentionToken.length;
  area.focus();
  area.setSelectionRange(cursor, cursor);
  autoResizeTextarea();
  hideMentionMenu();

  if (state.currentSessionId && !state.activeArtifactIds.includes(candidate.artifact_id)) {
    await updateActiveArtifacts(candidate.artifact_id, true);
  }
}

function hideMentionMenu() {
  state.mentionOpen = false;
  state.mentionCandidates = [];
  state.mentionSelectedIndex = 0;
  state.mentionTriggerIndex = -1;
  elements.mentionMenu.classList.remove("show");
  elements.mentionMenu.setAttribute("aria-hidden", "true");
  elements.mentionMenu.innerHTML = "";
}

function createNewSession() {
  if (state.currentSessionId && state.messages.length > 0) {
    persistCurrentSessionSnapshot();
  }
  closeComposerUploadMenu();
  hideMentionMenu();
  state.currentSessionId = null;
  state.messages = [];
  state.lastToolCalls = [];
  state.lastMemoryHits = [];
  state.streamEvents = [];
  state.sessionArtifacts = [];
  state.activeArtifactIds = [];
  state.shouldAutoFollow = true;
  elements.uploadStatusText.textContent = "";
  renderAll();
  persistState();
}

async function deleteSession(sessionId) {
  if (state.isSending || state.isUploading) {
    return;
  }
  const targetSessionId = typeof sessionId === "string" && sessionId ? sessionId : state.currentSessionId;
  if (!targetSessionId) {
    elements.uploadStatusText.textContent = "当前没有可删除的会话。";
    return;
  }
  const confirmed = window.confirm(`确认删除会话 ${targetSessionId} 吗？此操作不可撤销。`);
  if (!confirmed) {
    return;
  }

  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(targetSessionId)}`, { method: "DELETE" });
    if (!response.ok && response.status !== 404) {
      const detail = await readErrorDetail(response);
      throw new Error(detail);
    }
    removeSessionSnapshot(targetSessionId);

    if (state.currentSessionId === targetSessionId) {
      const fallback = state.sessions[0];
      if (fallback) {
        switchToSession(fallback.sessionId);
      } else {
        closeComposerUploadMenu();
        hideMentionMenu();
        state.currentSessionId = null;
        state.messages = [];
        state.lastToolCalls = [];
        state.lastMemoryHits = [];
        state.streamEvents = [];
        state.sessionArtifacts = [];
        state.activeArtifactIds = [];
        state.shouldAutoFollow = true;
        renderAll();
        persistState();
      }
    } else {
      renderSessionList();
      persistState();
    }

    elements.uploadStatusText.textContent = `已删除会话: ${targetSessionId}`;
  } catch (error) {
    elements.uploadStatusText.textContent = `删除会话失败: ${String(error)}`;
  }
}

async function sendMessage() {
  const rawText = elements.messageInput.value;
  const message = rawText.trim();
  if (!message || state.isSending) {
    return;
  }

  closeComposerUploadMenu();
  hideMentionMenu();
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
    max_tool_rounds: clampInt(elements.maxRoundsInput.value, 0, 20, 10),
    active_artifact_ids: state.activeArtifactIds,
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
    await refreshSessionArtifacts();

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
        const changed = state.currentSessionId !== payload.session_id;
        state.currentSessionId = payload.session_id;
        renderSessionHeader();
        if (changed) {
          void refreshSessionArtifacts();
        }
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
    case "answer_reset": {
      resetAssistantAnswer(assistantIndex);
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

function resetAssistantAnswer(assistantIndex) {
  const message = state.messages[assistantIndex];
  if (!message || message.role !== "assistant") {
    return;
  }
  message.content = "";
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
  renderSessionArtifacts();
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
    empty.innerHTML = [
      '<div class="session-item-main">',
      '<div class="session-item-head">无历史</div>',
      '<div class="session-item-body">开始一次对话后会记录在本地。</div>',
      "</div>",
    ].join("");
    elements.sessionList.appendChild(empty);
    return;
  }

  for (const snapshot of state.sessions) {
    const li = document.createElement("li");
    li.className = "session-item";
    if (snapshot.sessionId === state.currentSessionId) {
      li.classList.add("active");
    }

    const main = document.createElement("div");
    main.className = "session-item-main";

    const title = document.createElement("div");
    title.className = "session-item-head";
    title.textContent = (snapshot.preview || "").trim() || "(empty)";

    const sub = document.createElement("div");
    sub.className = "session-item-body";
    sub.textContent = snapshot.sessionId;

    main.appendChild(title);
    main.appendChild(sub);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "session-delete-btn";
    deleteBtn.title = `删除 ${snapshot.sessionId}`;
    deleteBtn.setAttribute("aria-label", `删除会话 ${snapshot.sessionId}`);
    deleteBtn.innerHTML = [
      '<svg viewBox="0 0 24 24" aria-hidden="true">',
      "<path d='M3 6h18'></path>",
      "<path d='M8 6V4h8v2'></path>",
      "<path d='M19 6l-1 14H6L5 6'></path>",
      "<path d='M10 11v6'></path>",
      "<path d='M14 11v6'></path>",
      "</svg>",
    ].join("");
    deleteBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      void deleteSession(snapshot.sessionId);
    });

    li.addEventListener("click", () => {
      switchToSession(snapshot.sessionId);
    });

    li.appendChild(main);
    li.appendChild(deleteBtn);
    elements.sessionList.appendChild(li);
  }
}

function switchToSession(sessionId) {
  const snapshot = state.sessions.find((item) => item.sessionId === sessionId);
  if (!snapshot) {
    return;
  }
  state.currentSessionId = snapshot.sessionId;
  state.messages = normalizeMessages(snapshot.messages);
  state.streamEvents = [];
  state.sessionArtifacts = [];
  state.activeArtifactIds = [];
  state.shouldAutoFollow = true;
  renderAll();
  persistState();
  void refreshSessionArtifacts();
}

function removeSessionSnapshot(sessionId) {
  state.sessions = state.sessions.filter((item) => item.sessionId !== sessionId);
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
      state.sessionArtifacts = Array.isArray(parsed.sessionArtifacts) ? parsed.sessionArtifacts : [];
      state.activeArtifactIds = Array.isArray(parsed.activeArtifactIds) ? parsed.activeArtifactIds : [];
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
    sessionArtifacts: state.sessionArtifacts,
    activeArtifactIds: state.activeArtifactIds,
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

async function uploadSelectedFile(selectedFile) {
  const selected = selectedFile;
  if (!selected || state.isUploading) {
    return;
  }
  const action = getComposerAction(state.pendingUploadActionId);
  const isImage = isLikelyImageUpload(selected);
  if (action.id === "upload_image" && !isImage) {
    elements.uploadStatusText.textContent = "当前选择的是“上传图片”，请重新选择图片文件。";
    elements.composerFileInput.value = "";
    return;
  }
  if (action.id === "upload_file" && isImage) {
    elements.uploadStatusText.textContent = "当前选择的是“上传文件”，如需上传图片请使用“上传图片”。";
    elements.composerFileInput.value = "";
    return;
  }

  const sessionId = ensureSessionIdForUpload();
  setUploading(true, `${action.label}中...`);

  try {
    const fileBuffer = await selected.arrayBuffer();
    const base64Payload = arrayBufferToBase64(fileBuffer);
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/artifacts/upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: selected.name,
        content_base64: base64Payload,
        auto_activate: true,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail ?? `HTTP ${response.status}`);
    }
    elements.composerFileInput.value = "";
    elements.uploadStatusText.textContent = `上传完成: ${data.title} (${data.status})`;
    await refreshSessionArtifacts();
  } catch (error) {
    elements.uploadStatusText.textContent = `上传失败: ${String(error)}`;
  } finally {
    // 清空 input，允许重复上传同名文件时仍能触发 change 事件。
    elements.composerFileInput.value = "";
    setUploading(false);
  }
}

async function refreshSessionArtifacts() {
  if (!state.currentSessionId) {
    state.sessionArtifacts = [];
    state.activeArtifactIds = [];
    renderSessionArtifacts();
    return;
  }
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/artifacts`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail ?? `HTTP ${response.status}`);
    }
    applySessionArtifactsResponse(data);
  } catch (error) {
    elements.uploadStatusText.textContent = `读取会话资料失败: ${String(error)}`;
  }
}

function applySessionArtifactsResponse(data) {
  state.sessionArtifacts = Array.isArray(data?.artifacts) ? data.artifacts : [];
  state.activeArtifactIds = Array.isArray(data?.active_artifact_ids) ? data.active_artifact_ids : [];
  renderSessionArtifacts();
  updateMentionMenuFromInput();
  persistState();
}

function renderSessionArtifacts() {
  elements.sessionArtifactsList.innerHTML = "";
  if (!state.currentSessionId) {
    elements.uploadStatusText.textContent = "请先发送一条消息或上传资料创建会话。";
    return;
  }
  if (state.sessionArtifacts.length === 0) {
    const empty = document.createElement("li");
    empty.className = "file-item";
    empty.textContent = "当前会话暂无资料。";
    elements.sessionArtifactsList.appendChild(empty);
    return;
  }

  for (const artifact of state.sessionArtifacts) {
    const li = document.createElement("li");
    li.className = "file-item";

    const head = document.createElement("div");
    head.className = "file-item-head";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.activeArtifactIds.includes(artifact.artifact_id);
    checkbox.disabled = artifact.status !== "ready" || state.isSending || state.isUploading;
    checkbox.addEventListener("change", () => {
      void updateActiveArtifacts(artifact.artifact_id, checkbox.checked);
    });

    const name = document.createElement("span");
    name.textContent = `${artifact.title} (${artifact.status})`;
    head.appendChild(checkbox);
    head.appendChild(name);

    const meta = document.createElement("div");
    meta.className = "file-item-meta";
    meta.textContent = `${artifact.media_type} · ${artifact.size_bytes} bytes${artifact.error ? ` · ${artifact.error}` : ""}`;

    li.appendChild(head);
    li.appendChild(meta);
    elements.sessionArtifactsList.appendChild(li);
  }
}

async function updateActiveArtifacts(artifactId, checked) {
  if (!state.currentSessionId) {
    return;
  }
  const current = new Set(state.activeArtifactIds);
  if (checked) {
    current.add(artifactId);
  } else {
    current.delete(artifactId);
  }

  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/active-artifacts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artifact_ids: [...current] }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail ?? `HTTP ${response.status}`);
    }
    applySessionArtifactsResponse(data);
  } catch (error) {
    elements.uploadStatusText.textContent = `更新 active 资料失败: ${String(error)}`;
    await refreshSessionArtifacts();
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
  elements.composerUploadBtn.disabled = isSending || state.isUploading;
  renderSessionHeader();
  if (isSending) {
    closeComposerUploadMenu();
  }
  renderSessionArtifacts();
}

function setUploading(isUploading, text = "") {
  state.isUploading = isUploading;
  elements.composerUploadBtn.disabled = isUploading || state.isSending;
  elements.composerUploadBtn.textContent = isUploading ? "…" : "+";
  renderSessionHeader();
  if (isUploading) {
    closeComposerUploadMenu();
  }
  if (text) {
    elements.uploadStatusText.textContent = text;
  }
  renderSessionArtifacts();
}

function ensureSessionIdForUpload() {
  if (state.currentSessionId) {
    return state.currentSessionId;
  }
  state.currentSessionId = `sess_${Math.random().toString(16).slice(2, 14)}`;
  renderSessionHeader();
  persistState();
  return state.currentSessionId;
}

function isLikelyImageUpload(file) {
  if (!file || typeof file !== "object") {
    return false;
  }
  const mediaType = String(file.type ?? "").toLowerCase();
  if (mediaType.startsWith("image/")) {
    return true;
  }
  const fileName = String(file.name ?? "").toLowerCase();
  return (
    fileName.endsWith(".png") ||
    fileName.endsWith(".jpg") ||
    fileName.endsWith(".jpeg") ||
    fileName.endsWith(".webp")
  );
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

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

init();
