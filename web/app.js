// Chat page: Google sign-in through the Cognito hosted UI (authorization code + PKCE), saved chats
// from the HTTP API, and answers streamed from the chat stream URL. /config.json is written at
// deploy time.
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  config: null,
  chats: [], // [{id, title, updated_at}], newest first
  chatId: null, // open chat; null for a new, unsaved chat
  messages: [], // [{role, content, sources?, request_id?, stopped?, error?}]
  busy: false,
  requestId: null, // the answer being streamed, for Stop
  editing: false,
};

const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  del: (k) => { try { localStorage.removeItem(k); } catch { /* private mode */ } },
};

const base64url = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (n = 48) => base64url(crypto.getRandomValues(new Uint8Array(n)));

function claims(jwt) {
  const part = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(decodeURIComponent(escape(atob(part))));
}

// ---------------------------------------------------------------- sign-in

async function signIn() {
  const { authDomain, clientId, redirectUri } = state.config;
  const verifier = randomString();
  const challenge = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const oauthState = randomString(16);
  sessionStorage.setItem("pkce", JSON.stringify({ verifier, oauthState, hash: location.hash }));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: "openid email profile",
    code_challenge_method: "S256",
    code_challenge: challenge,
    state: oauthState,
    identity_provider: "Google",
  });
  location.assign(`${authDomain}/oauth2/authorize?${params}`);
}

async function tokenRequest(body) {
  const response = await fetch(`${state.config.authDomain}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: state.config.clientId, ...body }),
  });
  if (!response.ok) throw new Error(`Sign-in failed (${response.status})`);
  const tokens = await response.json();
  const session = {
    idToken: tokens.id_token,
    refreshToken: tokens.refresh_token || store.get("session")?.refreshToken,
    expiresAt: Date.now() + (tokens.expires_in - 60) * 1000,
  };
  store.set("session", session);
  return session;
}

async function completeRedirect(params) {
  const saved = JSON.parse(sessionStorage.getItem("pkce") || "null");
  sessionStorage.removeItem("pkce");
  history.replaceState(null, "", location.pathname + (saved?.hash || ""));
  if (!saved || params.get("state") !== saved.oauthState) throw new Error("Sign-in expired. Please try again.");
  return tokenRequest({
    grant_type: "authorization_code",
    code: params.get("code"),
    redirect_uri: state.config.redirectUri,
    code_verifier: saved.verifier,
  });
}

async function currentSession() {
  const session = store.get("session");
  if (!session) return null;
  if (Date.now() < session.expiresAt) return session;
  if (!session.refreshToken) return null;
  try {
    return await tokenRequest({ grant_type: "refresh_token", refresh_token: session.refreshToken });
  } catch {
    store.del("session"); // refresh refused, e.g. removed from the allowlist
    return null;
  }
}

function signOut() {
  store.del("session");
  const { authDomain, clientId, redirectUri } = state.config;
  location.assign(`${authDomain}/logout?${new URLSearchParams({ client_id: clientId, logout_uri: redirectUri })}`);
}

async function authHeaders() {
  const session = await currentSession();
  if (!session) {
    showSignedOut("Your session ended. Please sign in again.");
    throw new Error("signed out");
  }
  return { "content-type": "application/json", authorization: `Bearer ${session.idToken}` };
}

async function api(method, path, body) {
  const response = await fetch(`${state.config.apiUrl}${path}`, {
    method,
    headers: await authHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) showSignedOut("Your session ended. Please sign in again.");
  if (!response.ok) throw new Error(data.error || data.message || `Request failed (${response.status})`);
  return data;
}

// ---------------------------------------------------------------- saved chats

async function loadChats() {
  try {
    state.chats = (await api("GET", "/chats")).chats;
  } catch (error) {
    if (error.message !== "signed out") console.warn("Couldn't load chats", error);
  }
  renderChatList();
}

function renderChatList() {
  const list = $("chat-list");
  list.replaceChildren(
    ...state.chats.map((chat) => {
      const item = document.createElement("li");
      item.className = chat.id === state.chatId ? "current" : "";
      const link = document.createElement("a");
      link.href = `#c=${chat.id}`;
      link.textContent = chat.title || "Untitled chat";
      link.title = chat.title;
      if (chat.id === state.chatId) link.setAttribute("aria-current", "page");
      const rename = iconButton("Rename", "M4 20h4L18.5 9.5a2.1 2.1 0 0 0-4-4L4 16v4zM13.5 6.5l4 4", () => startRename(item, chat));
      const remove = iconButton("Delete", "M5 7h14M10 11v6M14 11v6M6 7l1 12h10l1-12M9 7V4h6v3", () => deleteChat(chat));
      item.append(link, rename, remove);
      return item;
    }),
  );
  $("chat-list-empty").hidden = state.chats.length > 0;
}

function iconButton(label, path, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button small";
  button.setAttribute("aria-label", label);
  button.title = label;
  button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
  button.addEventListener("click", (event) => {
    event.preventDefault();
    onClick();
  });
  return button;
}

function startRename(item, chat) {
  if (state.busy) return;
  const input = document.createElement("input");
  input.value = chat.title;
  input.maxLength = 80;
  input.setAttribute("aria-label", "Chat name");
  item.replaceChildren(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const title = input.value.trim();
    if (save && title && title !== chat.title) {
      try {
        chat.title = (await api("PATCH", `/chats/${chat.id}`, { title })).title;
      } catch (error) {
        alertInChat(error.message);
      }
    }
    renderChatList();
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

async function deleteChat(chat) {
  if (state.busy) return;
  if (!confirm(`Delete "${chat.title}"? This can't be undone.`)) return;
  try {
    await api("DELETE", `/chats/${chat.id}`);
  } catch (error) {
    return alertInChat(error.message);
  }
  state.chats = state.chats.filter((c) => c.id !== chat.id);
  if (chat.id === state.chatId) newChat();
  else renderChatList();
}

function newChat() {
  if (state.busy) return;
  if (location.hash) history.pushState(null, "", location.pathname);
  showChatById(null);
  closeSidebar();
  $("question").focus();
}

async function showChatById(chatId) {
  if (state.busy) return;
  state.chatId = chatId;
  state.messages = [];
  state.editing = false;
  renderChatList();
  renderMessages();
  if (!chatId) return;
  const placeholder = addPlaceholder("Opening chat…");
  try {
    const chat = await api("GET", `/chats/${chatId}`);
    if (state.chatId !== chatId) return; // switched away meanwhile
    state.messages = chat.messages;
  } catch (error) {
    if (error.message === "signed out") return;
    placeholder.textContent = error.message;
    return;
  }
  renderMessages();
}

function chatIdFromHash() {
  const match = location.hash.match(/^#c=([\w-]+)$/);
  return match ? match[1] : null;
}

// ---------------------------------------------------------------- messages

function renderMessages() {
  const list = $("messages");
  list.replaceChildren(...state.messages.map((message, index) => messageElement(message, index)));
  $("examples").hidden = state.messages.length > 0;
  list.lastElementChild?.scrollIntoView({ block: "end" });
}

function messageElement(message, index) {
  const item = document.createElement("li");
  const isLast = index === state.messages.length - 1;
  const isLastQuestion = message.role === "user" && index >= state.messages.length - 2;
  if (message.role === "user") {
    item.className = "message user";
    item.innerHTML = `<p>${escapeHtml(message.content).replace(/\n/g, "<br>")}</p>`;
    if (isLastQuestion && !state.busy) {
      item.append(actions([["Edit", "M4 20h4L18.5 9.5a2.1 2.1 0 0 0-4-4L4 16v4zM13.5 6.5l4 4", () => editQuestion(item, message)]]));
    }
    return item;
  }

  item.className = "message assistant";
  if (message.error) {
    item.classList.add("error");
    item.innerHTML = `<p>${escapeHtml(message.error)}</p>`;
    if (isLast && !state.busy) item.append(actions([["Try again", RETRY_ICON, retry]], true));
    return item;
  }
  if (message.streaming && !message.content) {
    item.classList.add("pending");
    item.innerHTML = "<p>Looking through the references…</p>";
    return item;
  }
  fillAnswer(item, message);
  if (message.streaming) return item;
  const buttons = [["Copy", COPY_ICON, (button) => copyAnswer(button, message)]];
  if (isLast && !state.busy) buttons.push(["Retry", RETRY_ICON, retry]);
  const bar = actions(buttons);
  if (message.request_id) bar.append(feedbackControls(message.request_id));
  item.append(bar);
  return item;
}

const COPY_ICON = "M9 9h10v10H9zM5 15V5h10";
const RETRY_ICON = "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7";

function fillAnswer(item, message) {
  const sources = message.streaming ? message.retrieved || [] : message.sources || [];
  let html = renderMarkdown(message.content, message.streaming ? message.retrieved : message.sources);
  if (message.stopped) html += `<p class="note">Stopped.</p>`;
  if (!message.streaming) html += sourcesHtml(sources);
  item.innerHTML = html;
  if (message.streaming) item.classList.add("streaming");
}

function actions(buttons, labelled = false) {
  const bar = document.createElement("div");
  bar.className = "actions";
  for (const [label, icon, onClick] of buttons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = labelled ? "action labelled" : "action";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icon}"/></svg>${labelled ? `<span>${label}</span>` : ""}`;
    button.addEventListener("click", () => onClick(button));
    bar.append(button);
  }
  return bar;
}

function sourcesHtml(sources) {
  if (!sources.length) return "";
  const items = sources
    .map((s) => `<li><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">[${s.number}] ${escapeHtml(s.title)}</a></li>`)
    .join("");
  return `<details class="sources" open><summary>Sources</summary><ul>${items}</ul></details>`;
}

function feedbackControls(requestId) {
  const bar = document.createElement("span");
  bar.className = "feedback";
  bar.innerHTML = `<button class="action" data-rating="up" aria-label="Helpful" title="Helpful">👍</button>
    <button class="action" data-rating="down" aria-label="Not helpful" title="Not helpful">👎</button>`;
  bar.addEventListener("click", async (event) => {
    const rating = event.target.closest("button")?.dataset.rating;
    if (!rating) return;
    const comment = rating === "down" ? prompt("What was wrong or missing? (optional)") || "" : "";
    bar.textContent = "Thanks for the feedback.";
    api("POST", "/feedback", { request_id: requestId, rating, comment }).catch(() => (bar.textContent = "Couldn't send feedback."));
  });
  return bar;
}

async function copyAnswer(button, message) {
  try {
    await navigator.clipboard.writeText(message.content);
    flash(button, "Copied");
  } catch {
    flash(button, "Couldn't copy");
  }
}

function flash(button, text) {
  const tip = document.createElement("span");
  tip.className = "flash";
  tip.textContent = text;
  button.after(tip);
  setTimeout(() => tip.remove(), 1500);
}

function editQuestion(item, message) {
  if (state.busy || state.editing) return;
  state.editing = true;
  const box = document.createElement("textarea");
  box.value = message.content;
  box.maxLength = 2000;
  box.rows = Math.min(8, message.content.split("\n").length + 1);
  box.setAttribute("aria-label", "Edit your question");
  const save = button("Send", "primary", () => {
    const question = box.value.trim();
    if (!question) return;
    state.editing = false;
    const answer = state.messages.at(-1);
    if (answer?.error) {
      // That turn was never saved, so don't ask the server to replace it.
      state.messages.splice(-2, 2);
      return send(question, { replaceLast: answer.replaceLast, trimmed: true });
    }
    send(question, { replaceLast: true });
  });
  const cancel = button("Cancel", "secondary", () => {
    state.editing = false;
    renderMessages();
  });
  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      save.click();
    }
    if (event.key === "Escape") cancel.click();
  });
  const row = document.createElement("div");
  row.className = "edit-actions";
  row.append(cancel, save);
  item.classList.add("editing");
  item.replaceChildren(box, row);
  box.focus();
}

function button(text, kind, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = kind;
  b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

function retry() {
  const last = state.messages[state.messages.length - 1];
  const question = [...state.messages].reverse().find((m) => m.role === "user")?.content;
  if (!question) return;
  if (last?.error) {
    // A failed turn was never saved: drop it here and ask again the way it was first sent.
    state.messages.splice(-2, 2);
    return send(question, { replaceLast: last.replaceLast, trimmed: true });
  }
  send(question, { replaceLast: true });
}

function addPlaceholder(text) {
  const item = document.createElement("li");
  item.className = "message assistant pending";
  item.textContent = text;
  $("messages").append(item);
  return item;
}

function alertInChat(text) {
  addPlaceholder(text).classList.replace("pending", "error");
}

// ---------------------------------------------------------------- streaming

async function send(question, { replaceLast = false, trimmed = false } = {}) {
  if (state.busy) return;
  if (replaceLast && !trimmed) {
    if (state.messages.at(-1)?.role === "assistant") state.messages.pop();
    if (state.messages.at(-1)?.role === "user") state.messages.pop();
  }
  const answer = { role: "assistant", content: "", streaming: true };
  state.messages.push({ role: "user", content: question }, answer);
  setBusy(true);
  renderMessages();
  const view = () => $("messages").lastElementChild;

  let frame = 0;
  const redraw = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const item = view();
      item.classList.remove("pending");
      fillAnswer(item, answer);
      const nearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 160;
      if (nearBottom) item.scrollIntoView({ block: "end" });
    });
  };

  try {
    const response = await fetch(state.config.streamUrl, {
      method: "POST",
      headers: await authHeaders(),
      body: JSON.stringify({ question, chat_id: state.chatId, replace_last: replaceLast }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (response.status === 401) showSignedOut(data.error);
      throw new Error(data.error || `Request failed (${response.status})`);
    }
    for await (const event of ndjson(response.body)) {
      if (event.type === "start") {
        state.requestId = event.request_id;
        answer.retrieved = event.sources;
        if (!state.chatId) {
          state.chatId = event.chat_id;
          history.replaceState(null, "", `#c=${event.chat_id}`);
        }
      } else if (event.type === "delta") {
        answer.content += event.text;
        redraw();
      } else if (event.type === "replace") {
        answer.content = event.text;
        redraw();
      } else if (event.type === "done") {
        Object.assign(answer, { sources: event.sources, request_id: event.request_id, stopped: event.stopped });
        rememberChat(event.chat_id, event.title);
        if (!event.saved) answer.content += "\n\n*This chat is full, so this answer wasn't saved. Start a new chat to keep going.*";
      } else if (event.type === "error") {
        throw Object.assign(new Error(event.error), { unsaved: true });
      }
    }
    if (!answer.request_id) throw new Error("The answer was cut off. Try again.");
  } catch (error) {
    if (error.message === "signed out") {
      state.messages.splice(-2, 2);
    } else if (!answer.content || error.unsaved) {
      Object.assign(answer, { error: error.message, replaceLast });
    } else {
      answer.stopped = true;
    }
  } finally {
    cancelAnimationFrame(frame);
    delete answer.streaming;
    delete answer.retrieved;
    state.requestId = null;
    setBusy(false);
    renderMessages();
  }
}

async function* ndjson(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) if (line.trim()) yield JSON.parse(line);
    if (done) {
      if (buffer.trim()) yield JSON.parse(buffer);
      return;
    }
  }
}

async function stop() {
  if (!state.requestId) return;
  $("stop").disabled = true;
  $("stop").textContent = "Stopping…";
  // The server checks for this about once a second, then finishes and saves what it has.
  api("POST", "/chats/stop", { request_id: state.requestId }).catch(() => {
    $("stop").disabled = false;
    $("stop").textContent = "Stop";
  });
}

function rememberChat(id, title) {
  const existing = state.chats.find((c) => c.id === id);
  const chat = { ...existing, id, title: existing?.title || title, updated_at: new Date().toISOString() };
  state.chats = [chat, ...state.chats.filter((c) => c.id !== id)];
  renderChatList();
}

function setBusy(busy) {
  state.busy = busy;
  $("send").hidden = busy;
  $("stop").hidden = !busy;
  $("stop").disabled = false;
  $("stop").textContent = "Stop";
  document.body.classList.toggle("busy", busy);
}

// ---------------------------------------------------------------- layout

function openSidebar() {
  document.body.classList.add("sidebar-open");
  $("menu").setAttribute("aria-expanded", "true");
  $("scrim").hidden = false;
}

function closeSidebar() {
  document.body.classList.remove("sidebar-open");
  $("menu").setAttribute("aria-expanded", "false");
  $("scrim").hidden = true;
}

function showSignedOut(message) {
  $("chat").hidden = true;
  $("account").hidden = true;
  $("sidebar").hidden = true;
  $("menu").hidden = true;
  $("signed-out").hidden = false;
  $("auth-error").hidden = !message;
  $("auth-error").textContent = message || "";
}

function showChat(session) {
  $("signed-out").hidden = true;
  $("chat").hidden = false;
  $("account").hidden = false;
  $("sidebar").hidden = false;
  $("menu").hidden = false;
  $("user-email").textContent = claims(session.idToken).email || "";
  const days = state.config.chatRetentionDays;
  $("retention").textContent = days ? `Chats are deleted ${days} days after your last message.` : "";
  loadChats();
  showChatById(chatIdFromHash());
  $("question").focus();
}

async function main() {
  state.config = await (await fetch("config.json", { cache: "no-store" })).json();
  $("sign-in").addEventListener("click", signIn);
  $("sign-out").addEventListener("click", signOut);
  $("new-chat").addEventListener("click", newChat);
  $("stop").addEventListener("click", stop);
  $("menu").addEventListener("click", () => (document.body.classList.contains("sidebar-open") ? closeSidebar() : openSidebar()));
  $("scrim").addEventListener("click", closeSidebar);
  $("chat-list").addEventListener("click", (event) => {
    if (state.busy && event.target.closest("a")) event.preventDefault();
    else if (event.target.closest("a")) closeSidebar();
  });
  window.addEventListener("hashchange", () => {
    if (!state.busy && chatIdFromHash() !== state.chatId) showChatById(chatIdFromHash());
  });
  window.addEventListener("popstate", () => {
    if (!state.busy && chatIdFromHash() !== state.chatId) showChatById(chatIdFromHash());
  });
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const question = $("question").value.trim();
    if (!question || state.busy) return;
    $("question").value = "";
    send(question);
  });
  $("question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  document.querySelectorAll(".example").forEach((b) => b.addEventListener("click", () => send(b.textContent)));

  const params = new URLSearchParams(location.search);
  if (params.has("error")) {
    history.replaceState(null, "", location.pathname);
    // Cognito prefixes trigger errors, e.g. "PreSignUp failed with error <message>."
    const detail = (params.get("error_description") || params.get("error")).replace(/^.*failed with error\s*/i, "");
    return showSignedOut(detail);
  }
  try {
    const session = params.has("code") ? await completeRedirect(params) : await currentSession();
    session ? showChat(session) : showSignedOut();
  } catch (error) {
    showSignedOut(error.message);
  }
}

main();
