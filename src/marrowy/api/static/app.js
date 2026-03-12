async function refreshConversation(conversationId) {
  const [messagesRes, tasksRes, participantsRes, approvalsRes, jobsRes] = await Promise.all([
    fetch(`/api/conversations/${conversationId}/messages`),
    fetch(`/api/conversations/${conversationId}/tasks`),
    fetch(`/api/conversations/${conversationId}/participants`),
    fetch(`/api/conversations/${conversationId}/approvals`),
    fetch(`/api/conversations/${conversationId}/jobs`),
  ]);
  const messages = await messagesRes.json();
  const tasks = await tasksRes.json();
  const participants = await participantsRes.json();
  const approvals = await approvalsRes.json();
  const jobs = await jobsRes.json();

  const log = document.getElementById("chat-log");
  if (log) {
    log.innerHTML = messages.map((message) => `
      <article class="message message-${message.author_kind}">
        <header>${message.author_name}</header>
        <pre>${message.content}</pre>
      </article>
    `).join("");
    log.scrollTop = log.scrollHeight;
  }

  const participantsList = document.getElementById("participants-list");
  if (participantsList) {
    participantsList.innerHTML = participants.map((participant) => `
      <li>
        <strong>${participant.display_name}</strong><br>
        <span class="muted">${participant.activity_state}</span>
        ${participant.activity_summary ? `<div class="muted">${participant.activity_summary}</div>` : ""}
      </li>
    `).join("");
  }

  const approvalsList = document.getElementById("approvals-list");
  if (approvalsList) {
    approvalsList.innerHTML = approvals.length
      ? approvals.map((approval) => `
        <li>
          <strong>${approval.summary}</strong><br>
          <button data-approval-id="${approval.id}" data-decision="approve">Approve</button>
          <button data-approval-id="${approval.id}" data-decision="reject">Reject</button>
        </li>
      `).join("")
      : `<li class="muted">No approvals pending.</li>`;
  }

  const taskBoard = document.getElementById("task-board");
  if (taskBoard) {
    const statuses = ["created","planned","in_progress","blocked","waiting_approval","testing","deploying","done","failed","cancelled"];
    taskBoard.innerHTML = statuses.map((status) => `
      <section class="task-column">
        <h3>${status}</h3>
        ${tasks.filter((task) => task.status === status).map((task) => `
          <article class="task-card">
            <strong>${task.title}</strong><br>
            <span class="muted">${task.id}</span>
          </article>
        `).join("")}
      </section>
    `).join("");
  }

  const jobsList = document.getElementById("jobs-list");
  if (jobsList) {
    const activeJobs = jobs.filter((job) => ["queued","claimed","running","waiting"].includes(job.status));
    jobsList.innerHTML = activeJobs.length
      ? activeJobs.map((job) => `
        <li>
          <strong>${job.summary}</strong><br>
          <span class="muted">${job.worker_key} · ${job.status}</span>
          ${job.result_json?.latest ? `<div class="muted">${job.result_json.latest}</div>` : ""}
        </li>
      `).join("")
      : `<li class="muted">No active jobs.</li>`;
  }
}

async function postMessage(conversationId, content) {
  await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({content, author_name: "Browser User"}),
  });
}

async function resolveApproval(approvalId, decision) {
  await fetch(`/api/conversations/approvals/${approvalId}/resolve`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({decision, actor_name: "Browser User"}),
  });
}

document.addEventListener("submit", async (event) => {
  if (event.target.id !== "chat-form") return;
  event.preventDefault();
  const conversationId = window.MARROWY_CONVERSATION_ID;
  const input = document.getElementById("chat-input");
  if (!conversationId || !input || !input.value.trim()) return;
  await postMessage(conversationId, input.value.trim());
  input.value = "";
  await refreshConversation(conversationId);
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-approval-id]");
  if (!button) return;
  const approvalId = button.dataset.approvalId;
  const decision = button.dataset.decision;
  if (!approvalId || !decision) return;
  await resolveApproval(approvalId, decision);
  await refreshConversation(window.MARROWY_CONVERSATION_ID);
});

document.addEventListener("DOMContentLoaded", () => {
  const createConversationForm = document.getElementById("conversation-create-form");
  if (createConversationForm) {
    createConversationForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const title = document.getElementById("conversation-title")?.value?.trim();
      const projectId = document.getElementById("conversation-project-id")?.value || null;
      if (!title) return;
      const response = await fetch("/api/conversations", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({title, project_id: projectId, channel: "browser"}),
      });
      const conversation = await response.json();
      window.location.href = `/conversations/${conversation.id}`;
    });
  }
  const conversationId = window.MARROWY_CONVERSATION_ID;
  if (!conversationId) return;
  refreshConversation(conversationId);
  const stream = new EventSource(`/api/conversations/${conversationId}/events`);
  stream.onmessage = async () => {
    await refreshConversation(conversationId);
  };
  stream.addEventListener("conversation.message.created", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("task.status.updated", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("approval.requested", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("job.queued", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("job.started", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("job.progress", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("job.completed", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("job.failed", async () => {
    await refreshConversation(conversationId);
  });
  stream.addEventListener("participant.activity.updated", async () => {
    await refreshConversation(conversationId);
  });
});
