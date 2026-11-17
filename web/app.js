// Chat page: Google sign-in through the Cognito hosted UI (authorization code + PKCE), then
// questions to the chat API with the ID token. /config.json is written at deploy time.
"use strict";

const HISTORY_TURNS = 3; // question/answer pairs sent back as context
const $ = (id) => document.getElementById(id);
const state = { config: null, history: [], busy: false };

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

async function signIn() {
  const { authDomain, clientId, redirectUri } = state.config;
  const verifier = randomString();
  const challenge = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const oauthState = randomString(16);
  sessionStorage.setItem("pkce", JSON.stringify({ verifier, oauthState }));
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
  history.replaceState(null, "", location.pathname);
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

async function api(path, body) {
  const session = await currentSession();
  if (!session) {
    showSignedOut("Your session ended. Please sign in again.");
    throw new Error("signed out");
  }
  const response = await fetch(`${state.config.apiUrl}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${session.idToken}` },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || `Request failed (${response.status})`);
  return data;
}

function addMessage(role, html) {
  const item = document.createElement("li");
  item.className = `message ${role}`;
  item.innerHTML = html;
  $("messages").append(item);
  item.scrollIntoView({ behavior: "smooth", block: "end" });
  return item;
}

function sourcesHtml(sources) {
  if (!sources.length) return "";
  const items = sources
    .map((s) => `<li><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">[${s.number}] ${escapeHtml(s.title)}</a></li>`)
    .join("");
  return `<details class="sources" open><summary>Sources</summary><ul>${items}</ul></details>`;
}

function feedbackControls(item, requestId) {
  const bar = document.createElement("div");
  bar.className = "feedback";
  bar.innerHTML = `<span>Helpful?</span>
    <button class="link" data-rating="up" aria-label="Helpful">👍</button>
    <button class="link" data-rating="down" aria-label="Not helpful">👎</button>`;
  bar.addEventListener("click", async (event) => {
    const rating = event.target.closest("button")?.dataset.rating;
    if (!rating) return;
    const comment = rating === "down" ? prompt("What was wrong or missing? (optional)") || "" : "";
    bar.textContent = "Thanks for the feedback.";
    api("/feedback", { request_id: requestId, rating, comment }).catch(() => (bar.textContent = "Couldn't send feedback."));
  });
  item.append(bar);
}

async function ask(question) {
  if (state.busy) return;
  state.busy = true;
  $("send").disabled = true;
  $("examples").hidden = true;
  addMessage("user", `<p>${escapeHtml(question).replace(/\n/g, "<br>")}</p>`);
  const pending = addMessage("assistant pending", "<p>Looking through the references…</p>");
  try {
    const data = await api("/chat", { question, history: state.history.slice(-HISTORY_TURNS * 2) });
    pending.classList.remove("pending");
    pending.innerHTML = renderMarkdown(data.answer, data.sources) + sourcesHtml(data.sources);
    feedbackControls(pending, data.request_id);
    state.history.push({ role: "user", content: question }, { role: "assistant", content: data.answer });
  } catch (error) {
    if (error.message === "signed out") return pending.remove();
    pending.className = "message assistant error";
    pending.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
  } finally {
    state.busy = false;
    $("send").disabled = false;
  }
}

function showSignedOut(message) {
  $("chat").hidden = true;
  $("account").hidden = true;
  $("signed-out").hidden = false;
  $("auth-error").hidden = !message;
  $("auth-error").textContent = message || "";
}

function showChat(session) {
  $("signed-out").hidden = true;
  $("chat").hidden = false;
  $("account").hidden = false;
  $("user-email").textContent = claims(session.idToken).email || "";
  $("question").focus();
}

async function main() {
  state.config = await (await fetch("config.json", { cache: "no-store" })).json();
  $("sign-in").addEventListener("click", signIn);
  $("sign-out").addEventListener("click", signOut);
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const question = $("question").value.trim();
    if (!question) return;
    $("question").value = "";
    ask(question);
  });
  $("question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  document.querySelectorAll(".example").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));

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
