const chatEl = document.getElementById("chat");
const formEl = document.getElementById("composer");
const questionEl = document.getElementById("question");
const roleEl = document.getElementById("role");
const apiBaseEl = document.getElementById("apiBase");

let history = []; // [{role: "user"|"assistant", content: "..."}]

function addMessage(role, html) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = html;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.innerText = str;
  return d.innerHTML;
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionEl.value.trim();
  if (!question) return;

  addMessage("user", escapeHtml(question));
  history.push({ role: "user", content: question });
  questionEl.value = "";

  const loadingDiv = addMessage("assistant", "<em>Thinking...</em>");

  try {
    const res = await fetch(`${apiBaseEl.value}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        conversation_history: history.slice(0, -1),
        user_role: roleEl.value,
      }),
    });

    if (!res.ok) {
      loadingDiv.innerHTML = `<strong>Error:</strong> ${res.status} ${res.statusText}`;
      return;
    }

    const data = await res.json();
    history.push({ role: "assistant", content: data.answer });

    const citationsHtml = data.citations.length
      ? `<div class="citations">${data.citations
          .map(
            (c) =>
              `<div>&bull; ${escapeHtml(c.source_document)}${
                c.hierarchy_path ? " &mdash; " + escapeHtml(c.hierarchy_path) : ""
              }${c.page_number ? ` (p. ${c.page_number})` : ""}</div>`
          )
          .join("")}</div>`
      : "";

    loadingDiv.innerHTML = `
      ${escapeHtml(data.answer)}
      <div class="meta">
        <span class="confidence ${data.confidence}">Confidence: ${data.confidence} (${data.confidence_score})</span>
        &nbsp;|&nbsp; Intent: ${data.intent} &nbsp;|&nbsp; Model: ${data.model_used}
        ${citationsHtml}
        <div style="margin-top:6px; opacity:0.7;">Rewritten query: "${escapeHtml(data.rewritten_query)}"</div>
      </div>
    `;
  } catch (err) {
    loadingDiv.innerHTML = `<strong>Connection error:</strong> ${escapeHtml(String(err))}. Is the backend running at ${apiBaseEl.value}?`;
  }
});
