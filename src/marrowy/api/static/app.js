const TASK_STATUSES = ["created", "planned", "in_progress", "blocked", "waiting_approval", "testing", "deploying", "done", "failed", "cancelled"];
const ACTIVE_JOB_STATUSES = new Set(["queued", "claimed", "running", "waiting"]);
const EFFORT_OPTIONS = ["low", "medium", "high", "xhigh"];

let refreshInFlight = false;
let refreshQueued = false;
let currentTasks = [];
let selectedTaskId = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function humanize(value) {
  return escapeHtml(String(value ?? "").replaceAll("_", " "));
}

function renderEmptyState(text) {
  return `<li class="empty-item">${escapeHtml(text)}</li>`;
}

function getAgentProfile(agentKey) {
  const profiles = Array.isArray(window.MARROWY_AGENT_PROFILES) ? window.MARROWY_AGENT_PROFILES : [];
  return profiles.find((profile) => profile.key === agentKey) || null;
}

function renderThinkingSection(thinking, streamState) {
  if (!Array.isArray(thinking) || thinking.length === 0) return "";
  const markdown = thinking.map((entry) => `> ${entry.text}`).join("\n\n");
  const html = (typeof marked !== "undefined")
    ? marked.parse(markdown)
    : `<pre>${escapeHtml(markdown)}</pre>`;
  const countLabel = thinking.length === 1 ? "1 update" : `${thinking.length} updates`;
  const isOpen = streamState !== "final" && streamState !== "error";
  return `
    <details class="thinking-panel" ${isOpen ? "open" : ""}>
      <summary>
        <span>Thinking</span>
        <span class="thinking-count">${escapeHtml(countLabel)}</span>
      </summary>
      <div class="thinking-body markdown-body">${html}</div>
    </details>
  `;
}

function renderStreamPlaceholder(streamState) {
  const label = streamState === "error" ? "Stopped" : "Thinking";
  return `
    <div class="stream-placeholder">
      <span class="stream-indicator ${escapeHtml(streamState || "waiting")}">
        <span class="stream-dot"></span>
        <span class="stream-dot"></span>
        <span class="stream-dot"></span>
      </span>
      <span class="stream-label">${escapeHtml(label)}</span>
    </div>
  `;
}

function renderMessage(message) {
  const icon = message.author_kind === 'user' ? 'user' : 'bot';
  const msgType = message.message_type || 'agent';
  const metadata = message.metadata_json || {};
  const streamState = metadata.streamState || "final";
  const isStreamMessage = Boolean(metadata.streamMessage);
  const thinkingHtml = renderThinkingSection(metadata.thinking || [], streamState);
  let innerHtml = '';
  
  if (message.author_kind === 'user') {
    innerHtml = `<pre>${escapeHtml(message.content)}</pre>`;
  } else {
    const rawMarkdown = message.content;
    const parsedHtml = rawMarkdown
      ? ((typeof marked !== 'undefined') ? marked.parse(rawMarkdown) : `<pre>${escapeHtml(rawMarkdown)}</pre>`)
      : "";
    const bodyHtml = parsedHtml
      ? `<div class="markdown-body">${parsedHtml}</div>`
      : renderStreamPlaceholder(streamState);
    const copyButton = rawMarkdown
      ? `
        <button class="btn-copy-msg" data-raw-content="${escapeHtml(rawMarkdown)}" title="Copy Markdown">
          <i data-lucide="copy"></i>
        </button>
      `
      : "";
    innerHtml = `
      ${thinkingHtml}
      ${bodyHtml}
      ${copyButton}
    `;
  }
  
  return `
    <article class="msg-bubble-wrapper kind-${escapeHtml(message.author_kind)} ${isStreamMessage ? "is-stream-message" : ""}" data-author-kind="${escapeHtml(message.author_kind)}" data-msg-type="${escapeHtml(msgType)}" data-stream-state="${escapeHtml(streamState)}">
      <div class="msg-avatar">
        <i data-lucide="${icon}"></i>
      </div>
      <div class="msg-content-area">
        <div class="msg-meta">
          <span class="msg-author">${escapeHtml(message.author_name)}</span>
          <span class="msg-kind">${humanize(message.author_kind)}</span>
        </div>
        <div class="msg-bubble">
          ${innerHtml}
        </div>
      </div>
    </article>
  `;
}

function renderParticipant(participant) {
  const profile = participant.agent_key ? getAgentProfile(participant.agent_key) : null;
  const effortValue = profile?.effort || "medium";
  const effortControl = participant.agent_key
    ? `
      <label class="agent-effort-control">
        <span>Reasoning</span>
        <select class="agent-effort-select" data-agent-key="${escapeHtml(participant.agent_key)}">
          ${EFFORT_OPTIONS.map((option) => `<option value="${option}" ${option === effortValue ? "selected" : ""}>${option}</option>`).join("")}
        </select>
      </label>
    `
    : "";
  return `
    <li class="mini-card card-participant">
      <div class="card-head">
        <strong>${escapeHtml(participant.display_name)}</strong>
        <span class="status-dot ${escapeHtml(participant.activity_state)}" title="${humanize(participant.activity_state)}"></span>
      </div>
      <div class="card-sub">${participant.activity_summary ? escapeHtml(participant.activity_summary) : "Idle"}</div>
      ${effortControl}
    </li>
  `;
}

function renderApproval(approval) {
  return `
    <li class="mini-card card-approval">
      <div class="card-head"><strong>${escapeHtml(approval.summary)}</strong></div>
      <div class="approval-btns">
        <button class="btn-sm btn-approve" data-approval-id="${escapeHtml(approval.id)}" data-decision="approve"><i data-lucide="check"></i> Approve</button>
        <button class="btn-sm btn-reject" data-approval-id="${escapeHtml(approval.id)}" data-decision="reject"><i data-lucide="x"></i> Reject</button>
      </div>
    </li>
  `;
}

function getTaskById(taskId) {
  return currentTasks.find((task) => task.id === taskId) || null;
}

function renderTaskCardMeta(task) {
  const chips = [];
  if (task.assigned_agent_key) chips.push(`<span>${escapeHtml(task.assigned_agent_key)}</span>`);
  if (task.repository_name) chips.push(`<span>${escapeHtml(task.repository_name)}</span>`);
  if (task.environment_name) chips.push(`<span>${escapeHtml(task.environment_name)}</span>`);
  return chips.join("");
}

function renderTaskSubtasks(taskId) {
  const subtasks = currentTasks.filter((task) => task.parent_task_id === taskId);
  if (!subtasks.length) {
    return `<div class="empty-item">No subtasks.</div>`;
  }
  return `
    <ul class="detail-subtask-list">
      ${subtasks.map((task) => `
        <li>
          <strong>${escapeHtml(task.title)}</strong>
          <span>${humanize(task.status)}</span>
          ${task.assigned_agent_key ? `<small>${escapeHtml(task.assigned_agent_key)}</small>` : ""}
        </li>
      `).join("")}
    </ul>
  `;
}

function renderTaskColumn(status, tasks) {
  return `
    <div class="kanban-col" data-status="${escapeHtml(status)}">
      <div class="kanban-col-header">
        <span class="col-title">${humanize(status).replace(/\b\w/g, c => c.toUpperCase())}</span>
        <span class="col-count">${tasks.length}</span>
      </div>
      <div class="kanban-cards">
        ${tasks.length ? tasks.map((task) => `
          <button type="button" class="kanban-card" data-task-id="${escapeHtml(task.id)}">
            <div class="k-card-title">${escapeHtml(task.title)}</div>
            <div class="k-card-meta">
              ${renderTaskCardMeta(task)}
            </div>
          </button>
        `).join("") : `<div class="empty-item">Empty</div>`}
      </div>
    </div>
  `;
}

function renderJob(job) {
  const statusEl = `<span class="status-dot ${job.status}"></span>`;
  const errorMsg = job.last_error ? `<div class="job-error">${escapeHtml(job.last_error)}</div>` : '';
  let cancelBtn = '';
  const isCancellable = ["queued", "claimed", "running", "waiting"].includes(job.status);
  if (isCancellable) {
    cancelBtn = `<button class="btn-cancel-job" data-job-id="${job.id}" title="Cancel Job"><i data-lucide="x-circle"></i></button>`;
  }
  
  return `
    <li class="mini-card card-job">
      <div class="card-head">
        <strong>${escapeHtml(job.worker_key)}</strong>
        <div style="display: flex; gap: 8px; align-items: center;">${cancelBtn}${statusEl}</div>
      </div>
      <div class="card-sub">${escapeHtml(job.summary || "No description")}</div>
      ${errorMsg}
    </li>
  `;
}

function openTaskModal(taskId) {
  const task = getTaskById(taskId);
  const modal = document.getElementById("task-detail-modal");
  if (!task || !modal) return;
  selectedTaskId = taskId;
  populateTaskModal(task);
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
}

function closeTaskModal() {
  const modal = document.getElementById("task-detail-modal");
  if (!modal) return;
  selectedTaskId = null;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

function populateTaskModal(task) {
  const setValue = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.value = value ?? "";
  };
  const setText = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value ?? "";
  };
  const setHtml = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.innerHTML = value;
  };

  setText("task-detail-title", task.title || "Task Details");
  setText("task-detail-subtitle", `${humanize(task.kind)} · ${humanize(task.status)}`);
  setValue("task-detail-id", task.id);
  setText("task-detail-goal", task.goal || "");
  setHtml(
    "task-detail-overview",
    `
      <div><label>ID</label><code>${escapeHtml(task.id)}</code></div>
      <div><label>Status</label><span>${humanize(task.status)}</span></div>
      <div><label>Kind</label><span>${humanize(task.kind)}</span></div>
      <div><label>Assigned</label><span>${escapeHtml(task.assigned_agent_key || "unassigned")}</span></div>
      <div><label>Created</label><span>${escapeHtml(task.created_at || "")}</span></div>
      <div><label>Updated</label><span>${escapeHtml(task.updated_at || "")}</span></div>
    `,
  );
  setHtml("task-detail-subtasks", renderTaskSubtasks(task.id));

  setValue("task-detail-scope", task.scope || "");
  setValue("task-detail-acceptance", task.acceptance_criteria_markdown || "");
  setValue("task-detail-repository", task.repository_name || "");
  setValue("task-detail-branch", task.branch_name || "");
  setValue("task-detail-environment", task.environment_name || "");
  setValue("task-detail-agent", task.assigned_agent_key || "");
  const approvalCheckbox = document.getElementById("task-detail-approval-required");
  if (approvalCheckbox) approvalCheckbox.checked = Boolean(task.approval_required);
  setValue("task-detail-updates", task.updates_markdown || "");
  setValue("task-detail-blockers", task.blockers_markdown || "");
  setValue("task-detail-result", task.result_markdown || "");
  setValue("task-detail-observations", task.observations_markdown || "");
  setValue("task-detail-evidence", task.evidence_markdown || "");
  setValue("task-detail-gmud", task.gmud_reference || "");
}

function renderAgentRoster(profiles, participants) {
  const activeKeys = new Set(participants.map((p) => p.agent_key).filter(Boolean));
  return profiles
    .filter((profile) => profile.key !== "principal")
    .map((profile) => `
      <button
        type="button"
        class="roster-btn"
        data-agent-key="${escapeHtml(profile.key)}"
        ${activeKeys.has(profile.key) ? "disabled" : ""}
      >
        <i data-lucide="plus-circle"></i> ${escapeHtml(profile.display_name)}
      </button>
    `)
    .join("");
}

function updateMetricCards(participants, approvals, tasks) {
  const metrics = {
    participants: participants.length,
    approvals: approvals.length,
    tasks: tasks.length,
  };

  Object.entries(metrics).forEach(([metric, value]) => {
    const nodes = document.querySelectorAll(`[data-metric="${metric}"]`);
    nodes.forEach(node => {
      node.textContent = String(value);
    });
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  return response.json();
}

async function refreshConversation(conversationId) {
  const [messages, tasks, participants, approvals, jobs] = await Promise.all([
    fetchJson(`/api/conversations/${conversationId}/messages`),
    fetchJson(`/api/conversations/${conversationId}/tasks`),
    fetchJson(`/api/conversations/${conversationId}/participants`),
    fetchJson(`/api/conversations/${conversationId}/approvals`),
    fetchJson(`/api/conversations/${conversationId}/jobs`),
  ]);
  currentTasks = tasks;

  const log = document.getElementById("chat-log");
  if (log) {
    const shouldStickToBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 120;
    log.innerHTML = messages.length
      ? messages.map(renderMessage).join("")
      : `<div class="empty-feed"><i data-lucide="message-square"></i><p>No messages yet. Send a prompt to start orchestrating.</p></div>`;
    if (shouldStickToBottom) log.scrollTop = log.scrollHeight;
  }

  const participantsList = document.getElementById("participants-list");
  if (participantsList) {
    participantsList.innerHTML = participants.length
      ? participants.map(renderParticipant).join("")
      : renderEmptyState("No agents joined yet.");
  }

  const agentRoster = document.getElementById("agent-roster");
  if (agentRoster && Array.isArray(window.MARROWY_AGENT_PROFILES)) {
    agentRoster.innerHTML = renderAgentRoster(window.MARROWY_AGENT_PROFILES, participants);
  }

  const approvalsList = document.getElementById("approvals-list");
  if (approvalsList) {
    approvalsList.innerHTML = approvals.length
      ? approvals.map(renderApproval).join("")
      : renderEmptyState("No pending approvals.");
  }

  const taskBoard = document.getElementById("task-board");
  if (taskBoard) {
    taskBoard.innerHTML = TASK_STATUSES.map((status) => renderTaskColumn(status, tasks.filter((t) => t.status === status))).join("");
  }

  const jobsList = document.getElementById("jobs-list");
  if (jobsList) {
    const activeJobs = jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status));
    jobsList.innerHTML = activeJobs.length
      ? activeJobs.map(renderJob).join("")
      : renderEmptyState("Listening for jobs...");
  }

  updateMetricCards(participants, approvals, tasks);
  if (selectedTaskId) {
    const selectedTask = getTaskById(selectedTaskId);
    if (selectedTask) {
      populateTaskModal(selectedTask);
    } else {
      closeTaskModal();
    }
  }
  
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
}

async function enqueueRefresh(conversationId) {
  if (refreshInFlight) { refreshQueued = true; return; }
  refreshInFlight = true;
  try {
    do {
      refreshQueued = false;
      await refreshConversation(conversationId);
    } while (refreshQueued);
  } finally {
    refreshInFlight = false;
  }
}

async function postMessage(conversationId, content) {
  await fetchJson(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({content, author_name: "User"}),
  });
}

async function deleteConversation(conversationId) {
  return fetchJson(`/api/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

document.addEventListener("submit", async (event) => {
  if (event.target.id === "chat-form") {
    event.preventDefault();
    const conversationId = window.MARROWY_CONVERSATION_ID;
    const input = document.getElementById("chat-input");
    if (!conversationId || !input || !input.value.trim()) return;
    try {
      await postMessage(conversationId, input.value.trim());
      input.value = "";
      await enqueueRefresh(conversationId);
    } catch (e) { console.error(e); }
  } else if (event.target.id === "conversation-create-form") {
    event.preventDefault();
    const title = document.getElementById("conversation-title")?.value?.trim();
    const projectId = document.getElementById("conversation-project-id")?.value || null;
    if (!title) return;
    try {
      const conversation = await fetchJson("/api/conversations", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({title, project_id: projectId, channel: "browser"}),
      });
      // also optionally send the title as the first message so it acts like a prompt
      await fetchJson(`/api/conversations/${conversation.id}/messages`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({content: title, author_name: "User"}),
      });
      window.location.href = `/conversations/${conversation.id}`;
    } catch (e) { console.error(e); }
  }
});

// Submit on enter for textareas
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    const target = e.target;
    if (target.id === 'chat-input' || target.id === 'conversation-title') {
      e.preventDefault();
      target.closest('form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    }
  }
});

document.addEventListener("click", async (event) => {
  const approvalButton = event.target.closest("button[data-approval-id]");
  if (approvalButton) {
    const approvalId = approvalButton.dataset.approvalId;
    const decision = approvalButton.dataset.decision;
    if (!approvalId || !decision) return;
    try {
      await fetchJson(`/api/conversations/approvals/${approvalId}/resolve`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({decision, actor_name: "User"}),
      });
      await enqueueRefresh(window.MARROWY_CONVERSATION_ID);
    } catch (e) { console.error(e); }
    return;
  }

  const deleteConversationButton = event.target.closest("button[data-delete-conversation-id]");
  if (deleteConversationButton) {
    const conversationId = deleteConversationButton.dataset.deleteConversationId;
    if (!conversationId) return;
    const confirmed = window.confirm("Delete this room and all of its messages, tasks, approvals, and jobs?");
    if (!confirmed) return;
    try {
      await deleteConversation(conversationId);
      const shouldRedirectHome = deleteConversationButton.dataset.redirectHome === "true";
      if (shouldRedirectHome || window.MARROWY_CONVERSATION_ID === conversationId) {
        window.location.href = "/";
      } else {
        deleteConversationButton.closest("li")?.remove();
      }
    } catch (e) {
      console.error(e);
    }
    return;
  }

  const agentButton = event.target.closest("button[data-agent-key]");
  if (agentButton) {
    const agentKey = agentButton.dataset.agentKey;
    const conversationId = window.MARROWY_CONVERSATION_ID;
    if (!agentKey || !conversationId || agentButton.disabled) return;
    agentButton.disabled = true;
    try {
      await fetchJson(`/api/conversations/${conversationId}/participants`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({agent_key: agentKey}),
      });
      await enqueueRefresh(conversationId);
    } catch (e) {
      agentButton.disabled = false;
      console.error(e);
    }
    return;
  }

  const taskCard = event.target.closest(".kanban-card[data-task-id]");
  if (taskCard) {
    const taskId = taskCard.dataset.taskId;
    if (taskId) openTaskModal(taskId);
    return;
  }

  const closeTaskModalButton = event.target.closest("[data-close-task-modal]");
  if (closeTaskModalButton) {
    closeTaskModal();
    return;
  }

  // Handle Cancel Job
  const cancelJobBtn = event.target.closest(".btn-cancel-job");
  if (cancelJobBtn) {
    const jobId = cancelJobBtn.dataset.jobId;
    const conversationId = window.MARROWY_CONVERSATION_ID;
    if (!jobId || !conversationId) return;
    try {
      await fetchJson(`/api/conversations/${conversationId}/jobs/${jobId}/cancel`, {
        method: "POST"
      });
      await enqueueRefresh(conversationId);
    } catch (e) {
      console.error(e);
    }
    return;
  }

  // Handle copy text
  const copyBtn = event.target.closest(".btn-copy-msg");
  if (copyBtn) {
    const rawContent = copyBtn.dataset.rawContent;
    if (rawContent && navigator.clipboard) {
      navigator.clipboard.writeText(rawContent).then(() => {
        const icon = copyBtn.querySelector('i');
        const oldIconName = icon.getAttribute('data-lucide');
        icon.setAttribute('data-lucide', 'check');
        if (typeof lucide !== 'undefined') lucide.createIcons({ icons: { check: lucide.icons.Check } });
        setTimeout(() => {
          icon.setAttribute('data-lucide', oldIconName);
          if (typeof lucide !== 'undefined') lucide.createIcons({ icons: { copy: lucide.icons.Copy } });
        }, 1500);
      });
    }
  }

  // Handle panel toggles
  const toggleBtn = event.target.closest(".toggle-btn");
  if (toggleBtn) {
    const isAgents = toggleBtn.id === 'btn-toggle-agents';
    const isTasks = toggleBtn.id === 'btn-toggle-tasks';
    const panelAgents = document.getElementById('panel-agents');
    const panelTasks = document.getElementById('panel-tasks');
    
    // reset panel toggle tags (but NOT system msg toggle)
    document.querySelectorAll('.toggle-btn:not(#btn-toggle-system-msgs)').forEach(b => b.classList.remove('active'));

    if (isAgents) {
      if (panelAgents.classList.contains('hidden')) {
        panelAgents.classList.remove('hidden');
        panelTasks.classList.add('hidden');
        toggleBtn.classList.add('active');
      } else {
        panelAgents.classList.add('hidden');
      }
    } else if (isTasks) {
       if (panelTasks.classList.contains('hidden')) {
        panelTasks.classList.remove('hidden');
        panelAgents.classList.add('hidden');
        toggleBtn.classList.add('active');
      } else {
        panelTasks.classList.add('hidden');
      }
    }
  }

  // Handle close cross inside panels
  const clsBtn = event.target.closest(".close-panel");
  if (clsBtn) {
    document.getElementById(clsBtn.dataset.target).classList.add('hidden');
    document.querySelectorAll('.toggle-btn:not(#btn-toggle-system-msgs)').forEach(b => b.classList.remove('active'));
  }

  // Handle system messages toggle
  if (event.target.closest('#btn-toggle-system-msgs')) {
    const btn = document.getElementById('btn-toggle-system-msgs');
    const chatFeed = document.getElementById('chat-log');
    btn.classList.toggle('active');
    chatFeed.classList.toggle('system-msgs-hidden');
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) return;

  if (target.classList.contains("agent-effort-select")) {
    const agentKey = target.dataset.agentKey;
    if (!agentKey) return;
    try {
      const updated = await fetchJson(`/api/agents/${agentKey}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ effort: target.value }),
      });
      window.MARROWY_AGENT_PROFILES = (window.MARROWY_AGENT_PROFILES || []).map((profile) =>
        profile.key === updated.key ? updated : profile
      );
      await enqueueRefresh(window.MARROWY_CONVERSATION_ID);
    } catch (e) {
      console.error(e);
      await enqueueRefresh(window.MARROWY_CONVERSATION_ID);
    }
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const conversationId = window.MARROWY_CONVERSATION_ID;
  if (!conversationId) return;

  enqueueRefresh(conversationId).catch(console.error);

  const stream = new EventSource(`/api/conversations/${conversationId}/events`);
  const refreshFromStream = () => enqueueRefresh(conversationId).catch(console.error);
  stream.onmessage = refreshFromStream;
  stream.addEventListener("conversation.message.created", refreshFromStream);
  stream.addEventListener("conversation.message.updated", refreshFromStream);
  stream.addEventListener("task.updated", refreshFromStream);
  stream.addEventListener("task.status.updated", refreshFromStream);
  stream.addEventListener("approval.requested", refreshFromStream);
  stream.addEventListener("job.queued", refreshFromStream);
  stream.addEventListener("job.started", refreshFromStream);
  stream.addEventListener("job.progress", refreshFromStream);
  stream.addEventListener("job.completed", refreshFromStream);
  stream.addEventListener("job.failed", refreshFromStream);
  stream.addEventListener("participant.activity.updated", refreshFromStream);
  stream.addEventListener("agent.joined", refreshFromStream);

  // Create Agent form
  const agentForm = document.getElementById('create-agent-form');
  if (agentForm) {
    agentForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const key = document.getElementById('new-agent-key')?.value?.trim();
      const displayName = document.getElementById('new-agent-name')?.value?.trim();
      const summary = document.getElementById('new-agent-summary')?.value?.trim();
      const instructions = document.getElementById('new-agent-instructions')?.value?.trim() || summary;
      const effort = document.getElementById('new-agent-effort')?.value || 'medium';
      if (!key || !displayName || !summary) return;
      try {
        await fetchJson('/api/agents', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ key, display_name: displayName, summary, instructions, effort }),
        });
        // Update local profiles list
        const profiles = await fetchJson('/api/agents');
        window.MARROWY_AGENT_PROFILES = profiles;
        agentForm.reset();
        await enqueueRefresh(conversationId);
      } catch (err) { console.error(err); }
    });
  }

  // Create Task form
  const taskForm = document.getElementById('create-task-form');
  if (taskForm) {
    taskForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const title = document.getElementById('new-task-title')?.value?.trim();
      const goal = document.getElementById('new-task-goal')?.value?.trim();
      const agentKey = document.getElementById('new-task-agent')?.value || null;
      if (!title || !goal) return;
      try {
        await fetchJson(`/api/conversations/${conversationId}/tasks`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ title, goal, assigned_agent_key: agentKey }),
        });
        taskForm.reset();
        await enqueueRefresh(conversationId);
      } catch (err) { console.error(err); }
    });
  }

  const taskDetailForm = document.getElementById("task-detail-form");
  if (taskDetailForm) {
    taskDetailForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const taskId = document.getElementById("task-detail-id")?.value;
      if (!taskId) return;
      try {
        await fetchJson(`/api/conversations/${conversationId}/tasks/${taskId}`, {
          method: "PATCH",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            scope: document.getElementById("task-detail-scope")?.value || null,
            acceptance_criteria_markdown: document.getElementById("task-detail-acceptance")?.value || null,
            repository_name: document.getElementById("task-detail-repository")?.value || null,
            branch_name: document.getElementById("task-detail-branch")?.value || null,
            environment_name: document.getElementById("task-detail-environment")?.value || null,
            assigned_agent_key: document.getElementById("task-detail-agent")?.value || null,
            updates_markdown: document.getElementById("task-detail-updates")?.value || null,
            blockers_markdown: document.getElementById("task-detail-blockers")?.value || null,
            approval_required: Boolean(document.getElementById("task-detail-approval-required")?.checked),
            result_markdown: document.getElementById("task-detail-result")?.value || null,
            observations_markdown: document.getElementById("task-detail-observations")?.value || null,
            evidence_markdown: document.getElementById("task-detail-evidence")?.value || null,
            gmud_reference: document.getElementById("task-detail-gmud")?.value || null,
          }),
        });
        await enqueueRefresh(conversationId);
      } catch (err) {
        console.error(err);
      }
    });
  }
});
