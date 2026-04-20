const state = {
  jobs: [],
  health: null,
  upload: null,
  match: null,
  selectedMatch: null,
  optimization: null,
  pollers: {
    match: null,
    optimization: null,
  },
};

const elements = {
  uploadForm: document.querySelector("#upload-form"),
  matchForm: document.querySelector("#match-form"),
  optimizationForm: document.querySelector("#optimization-form"),
  resumeFile: document.querySelector("#resume-file"),
  candidateId: document.querySelector("#candidate-id"),
  resumeId: document.querySelector("#resume-id"),
  matchResumeId: document.querySelector("#match-resume-id"),
  optimizationResumeId: document.querySelector("#optimization-resume-id"),
  targetCity: document.querySelector("#target-city"),
  targetJobId: document.querySelector("#target-job-id"),
  matchTaskId: document.querySelector("#match-task-id"),
  matchStage: document.querySelector("#match-stage"),
  optimizationTaskId: document.querySelector("#optimization-task-id"),
  reviewStatus: document.querySelector("#review-status"),
  healthStatus: document.querySelector("#health-status"),
  healthMeta: document.querySelector("#health-meta"),
  jobCount: document.querySelector("#job-count"),
  matchResults: document.querySelector("#match-results"),
  selectedJobPill: document.querySelector("#selected-job-pill"),
  markdownPreview: document.querySelector("#markdown-preview"),
  rawMarkdown: document.querySelector("#raw-markdown"),
  reviewPanel: document.querySelector("#review-panel"),
  timeline: document.querySelector("#event-timeline"),
  jobLibrary: document.querySelector("#job-library"),
  copyMarkdown: document.querySelector("#copy-markdown"),
  toast: document.querySelector("#toast"),
};

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `request_failed: ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "blocked"]);

function setText(node, value) {
  node.textContent = value ?? "-";
}

function showToast(message, tone = "normal") {
  elements.toast.textContent = message;
  elements.toast.className = "toast visible";
  if (tone === "error") {
    elements.toast.style.background = "rgba(159, 46, 18, 0.96)";
  } else {
    elements.toast.style.background = "rgba(19, 17, 14, 0.95)";
  }
  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => {
    elements.toast.className = "toast";
  }, 2600);
}

function formatDate(value) {
  try {
    return new Date(value).toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return value;
  }
}

function renderHealth() {
  if (!state.health) {
    setText(elements.healthStatus, "Unavailable");
    setText(elements.healthMeta, "Health endpoint not loaded.");
    return;
  }
  setText(elements.healthStatus, state.health.status.toUpperCase());
  const checks = Object.entries(state.health.checks)
    .map(([key, ok]) => `${key}:${ok ? "ok" : "fail"}`)
    .join(" / ");
  setText(elements.healthMeta, checks);
}

function renderJobLibrary() {
  elements.jobCount.textContent = String(state.jobs.length);
  if (!state.jobs.length) {
    elements.jobLibrary.className = "job-library empty-state";
    elements.jobLibrary.textContent = "No jobs loaded.";
    return;
  }

  elements.jobLibrary.className = "job-library";
  elements.jobLibrary.innerHTML = state.jobs
    .map(
      (job) => `
        <article class="library-card">
          <div class="card-head">
            <div>
              <h3>${escapeHtml(job.title)}</h3>
              <p class="library-copy">${escapeHtml(job.company_name)}</p>
            </div>
            <button class="ghost-button" type="button" data-library-select="${job.id}">Use</button>
          </div>
          <div class="library-meta">
            <span class="chip">${escapeHtml(job.city ?? "N/A")}</span>
            <span class="chip">${escapeHtml(job.education_requirement ?? "N/A")}</span>
            <span class="chip">${job.experience_min_years ?? 0}+ years</span>
          </div>
          <p class="library-copy">${job.skills.map((item) => item.name).join(" / ")}</p>
        </article>
      `,
    )
    .join("");

  elements.jobLibrary.querySelectorAll("[data-library-select]").forEach((button) => {
    button.addEventListener("click", () => {
      const jobId = button.getAttribute("data-library-select");
      elements.targetJobId.value = jobId;
      const job = state.jobs.find((item) => item.id === jobId);
      setText(elements.selectedJobPill, job ? `${job.company_name} / ${job.title}` : jobId);
      showToast("Target job selected from seeded library.");
    });
  });
}

function renderUpload() {
  setText(elements.candidateId, state.upload?.candidate_id ?? "-");
  setText(elements.resumeId, state.upload?.resume_id ?? "-");
}

function renderMatches() {
  const match = state.match;
  setText(elements.matchTaskId, match?.task_id ?? "-");
  setText(
    elements.matchStage,
    match ? `${match.stage} / ${match.task_status ?? "unknown"}` : "-",
  );
  if (!match?.matches?.length) {
    elements.matchResults.className = "cards-grid empty-state";
    if (match?.task_id) {
      elements.matchResults.textContent = `任务已创建，当前状态 ${match.task_status}，当前阶段 ${match.stage}。${match.failure_reason ? ` 失败原因：${match.failure_reason}` : " worker 处理后结果会显示在这里。"}`;
      renderTimeline(match.events || []);
    } else {
      elements.matchResults.textContent = "先上传简历并运行匹配任务，结果会显示在这里。";
      elements.timeline.className = "timeline empty-state";
      elements.timeline.textContent = "任务执行事件会按时间写在这里。";
    }
    return;
  }

  elements.matchResults.className = "cards-grid";
  elements.matchResults.innerHTML = match.matches
    .map((item) => {
      const isSelected = state.selectedMatch?.job_posting_id === item.job_posting_id;
      return `
        <article class="job-card ${isSelected ? "selected" : ""}">
          <div class="card-head">
            <div>
              <h3>${escapeHtml(item.job_title)}</h3>
              <p class="card-copy">${escapeHtml(item.company_name)}</p>
            </div>
            <div class="score-badge">${Math.round(item.score_card.overall_score * 100)}</div>
          </div>
          <div class="card-meta">
            <span class="chip">${escapeHtml(item.city ?? "N/A")}</span>
            <span class="chip">skill ${Math.round(item.score_card.skill_score * 100)}</span>
            <span class="chip">exp ${Math.round(item.score_card.experience_score * 100)}</span>
          </div>
          <p class="card-copy">Matched: ${escapeHtml((item.explanation.matched_required_skills || []).join(", ") || "none")}</p>
          <p class="card-copy">Gap: ${escapeHtml((item.gap.missing_required_skills || []).join(", ") || "none")}</p>
          <div class="card-actions">
            <button class="ghost-button" type="button" data-select-job="${item.job_posting_id}">Select</button>
            <span class="strip-label">Rank ${item.rank_no}</span>
          </div>
        </article>
      `;
    })
    .join("");

  elements.matchResults.querySelectorAll("[data-select-job]").forEach((button) => {
    button.addEventListener("click", () => {
      const jobId = button.getAttribute("data-select-job");
      state.selectedMatch = state.match.matches.find((item) => item.job_posting_id === jobId);
      elements.targetJobId.value = jobId;
      renderSelectedJob();
      renderMatches();
      showToast("Target job selected from match results.");
    });
  });

  renderTimeline([...(match.events || []), ...(state.optimization?.events || [])]);
}

function renderSelectedJob() {
  if (!state.selectedMatch) {
    setText(elements.selectedJobPill, "No job selected");
    return;
  }
  setText(
    elements.selectedJobPill,
    `${state.selectedMatch.company_name} / ${state.selectedMatch.job_title}`,
  );
}

function renderOptimization() {
  const optimization = state.optimization;
  setText(elements.optimizationTaskId, optimization?.task_id ?? "-");
  setText(
    elements.reviewStatus,
    optimization
      ? `${optimization.review_report?.risk_level ?? optimization.task_status ?? optimization.status ?? "-"}`
      : "-",
  );
  if (!optimization?.optimized_resume_markdown) {
    elements.markdownPreview.className = "markdown-preview empty-state";
    elements.markdownPreview.textContent = optimization?.task_id
      ? `任务已创建，当前状态 ${optimization.task_status ?? optimization.status}，当前阶段 ${optimization.stage}。${optimization.failure_reason ? ` 失败原因：${optimization.failure_reason}` : " worker 处理后优化稿会显示在这里。"}`
      : "选择岗位并运行优化任务后，这里会显示优化版简历。";
    elements.reviewPanel.className = "review-panel empty-state";
    elements.reviewPanel.textContent = optimization?.task_id
      ? "ReviewGuard 结果会在任务完成后显示。"
      : "ReviewGuard 结果会显示在这里。";
    elements.rawMarkdown.textContent = "# optimized_resume.md";
    renderTimeline([...(state.match?.events || []), ...(optimization?.events || [])]);
    return;
  }

  elements.markdownPreview.className = "markdown-preview";
  elements.markdownPreview.innerHTML = renderMarkdown(optimization.optimized_resume_markdown);
  elements.rawMarkdown.textContent = optimization.optimized_resume_markdown;

  const reviewReport = optimization.review_report || {};
  const issues = reviewReport.issues || [];
  const badgeTone = reviewReport.allow_delivery ? reviewReport.risk_level || "low" : "blocked";
  elements.reviewPanel.className = "review-panel";
  elements.reviewPanel.innerHTML = `
    <span class="review-badge ${badgeTone}">${reviewReport.allow_delivery ? "allow delivery" : "blocked"} / ${
      reviewReport.risk_level || "unknown"
    }</span>
    <p>${escapeHtml(
      issues.length
        ? `发现 ${issues.length} 个审核项。`
        : "未发现明显证据越界问题，可用于人工复核。",
    )}</p>
    ${
      issues.length
        ? issues
            .map(
              (issue) => `
                <article class="review-item">
                  <strong>${escapeHtml(issue.level)}</strong>
                  <p>${escapeHtml(issue.message)}</p>
                </article>
              `,
            )
            .join("")
        : ""
    }
    <article class="review-item">
      <strong>Change Summary</strong>
      <p>${escapeHtml((optimization.change_summary || []).map((item) => `${item.section} / ${item.action}`).join(" | ") || "No changes listed.")}</p>
    </article>
  `;
  renderTimeline([...(state.match?.events || []), ...(optimization.events || [])]);
}

function renderTimeline(events) {
  if (!events?.length) {
    elements.timeline.className = "timeline empty-state";
    elements.timeline.textContent = "任务执行事件会按时间写在这里。";
    return;
  }
  elements.timeline.className = "timeline";
  elements.timeline.innerHTML = [...events]
    .sort((left, right) => new Date(right.created_at) - new Date(left.created_at))
    .map(
      (event) => `
        <article class="timeline-item">
          <strong>${escapeHtml(event.event_type)}</strong>
          <p>${escapeHtml(JSON.stringify(event.payload, null, 0))}</p>
          <time>${escapeHtml(formatDate(event.created_at))}</time>
        </article>
      `,
    )
    .join("");
}

function renderMarkdown(source) {
  const lines = source.split("\n");
  let html = "";
  let inList = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      continue;
    }

    if (line.startsWith("# ")) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<h1>${escapeHtml(line.slice(2))}</h1>`;
      continue;
    }
    if (line.startsWith("## ")) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<h2>${escapeHtml(line.slice(3))}</h2>`;
      continue;
    }
    if (line.startsWith("### ")) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<h3>${escapeHtml(line.slice(4))}</h3>`;
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${escapeHtml(line.slice(2))}</li>`;
      continue;
    }

    if (inList) {
      html += "</ul>";
      inList = false;
    }
    html += `<p>${escapeHtml(line)}</p>`;
  }

  if (inList) {
    html += "</ul>";
  }
  return html;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadInitialState() {
  try {
    const [health, jobs] = await Promise.all([request("/api/v1/health"), request("/api/v1/jobs")]);
    state.health = health;
    state.jobs = jobs;
    renderHealth();
    renderJobLibrary();
  } catch (error) {
    showToast(error.message, "error");
    setText(elements.healthStatus, "Error");
    setText(elements.healthMeta, error.message);
  }
}

async function onUploadSubmit(event) {
  event.preventDefault();
  const file = elements.resumeFile.files?.[0];
  if (!file) {
    showToast("请选择一个 PDF 或 DOCX 文件。", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  try {
    showToast("Uploading resume...");
    const payload = await request("/api/v1/resumes/upload", {
      method: "POST",
      body: formData,
    });
    state.upload = payload;
    elements.matchResumeId.value = payload.resume_id;
    elements.optimizationResumeId.value = payload.resume_id;
    renderUpload();
    showToast("Resume uploaded.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function onMatchSubmit(event) {
  event.preventDefault();
  const resumeId = elements.matchResumeId.value.trim();
  if (!resumeId) {
    showToast("需要先提供 resume_id。", "error");
    return;
  }

  try {
    clearPolling("match");
    showToast("Match task queued...");
    const payload = await request("/api/v1/match-tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_id: resumeId,
        target_city: elements.targetCity.value.trim() || null,
      }),
    });
    state.match = { ...payload, matches: [], events: [] };
    state.selectedMatch = null;
    renderMatches();
    renderSelectedJob();
    startPolling({
      kind: "match",
      taskId: payload.task_id,
      endpoint: "/api/v1/match-tasks",
      onUpdate(snapshot) {
        state.match = snapshot;
        if (!state.selectedMatch && snapshot.matches?.length) {
          state.selectedMatch = snapshot.matches[0];
          elements.targetJobId.value = snapshot.matches[0].job_posting_id;
        }
        renderMatches();
        renderSelectedJob();
      },
    });
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function onOptimizationSubmit(event) {
  event.preventDefault();
  const resumeId = elements.optimizationResumeId.value.trim();
  const targetJobId = elements.targetJobId.value.trim();
  if (!resumeId || !targetJobId) {
    showToast("需要 resume_id 和 target_job_id。", "error");
    return;
  }

  try {
    clearPolling("optimization");
    showToast("Optimization task queued...");
    const payload = await request("/api/v1/optimization-tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_id: resumeId,
        target_job_id: targetJobId,
        mode: "targeted",
      }),
    });
    state.optimization = {
      ...payload,
      status: payload.task_status,
      optimized_resume_markdown: "",
      change_summary: [],
      risk_notes: [],
      review_report: {},
      events: [],
    };
    renderOptimization();
    startPolling({
      kind: "optimization",
      taskId: payload.task_id,
      endpoint: "/api/v1/optimization-tasks",
      onUpdate(snapshot) {
        state.optimization = snapshot;
        renderOptimization();
      },
    });
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function copyMarkdown() {
  const markdown = state.optimization?.optimized_resume_markdown;
  if (!markdown) {
    showToast("当前没有可复制的优化稿。", "error");
    return;
  }
  await navigator.clipboard.writeText(markdown);
  showToast("Markdown copied.");
}

function clearPolling(kind) {
  if (state.pollers[kind]) {
    window.clearTimeout(state.pollers[kind]);
    state.pollers[kind] = null;
  }
}

function startPolling({ kind, taskId, endpoint, onUpdate }) {
  clearPolling(kind);

  const poll = async () => {
    try {
      const snapshot = await request(`${endpoint}/${taskId}`);
      onUpdate(snapshot);
      const taskStatus = snapshot.task_status ?? snapshot.status;
      if (TERMINAL_STATUSES.has(taskStatus)) {
        showToast(`${kind} task ${taskStatus}.`);
        clearPolling(kind);
        return;
      }
      state.pollers[kind] = window.setTimeout(poll, 1500);
    } catch (error) {
      showToast(error.message, "error");
      clearPolling(kind);
    }
  };

  state.pollers[kind] = window.setTimeout(poll, 250);
}

function bindEvents() {
  elements.uploadForm.addEventListener("submit", onUploadSubmit);
  elements.matchForm.addEventListener("submit", onMatchSubmit);
  elements.optimizationForm.addEventListener("submit", onOptimizationSubmit);
  elements.copyMarkdown.addEventListener("click", () => {
    copyMarkdown().catch((error) => showToast(error.message, "error"));
  });
}

bindEvents();
loadInitialState();
