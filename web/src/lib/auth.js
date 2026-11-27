// Google sign-in through the Cognito hosted UI: authorization code + PKCE, tokens kept in
// localStorage and refreshed with the refresh token. /config.json is written at deploy time.

// Falls back to memory when the browser blocks storage (private mode, or a strict browser blocking
// storage in the Onshape panel's iframe): sign-in then lasts until the page is closed.
const memory = new Map();
export const store = {
  get: (k) => {
    try {
      const value = localStorage.getItem(k);
      if (value !== null) return JSON.parse(value);
    } catch { /* blocked */ }
    return memory.get(k) ?? null;
  },
  set: (k, v) => { memory.set(k, v); try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* blocked */ } },
  del: (k) => { memory.delete(k); try { localStorage.removeItem(k); } catch { /* blocked */ } },
};

// The Onshape right panel loads this app at /onshape/index.html inside an iframe.
export const inPanel = location.pathname.startsWith("/onshape/");
const POPUP_STATE = "p."; // marks a sign-in started by the panel (backend/chat_api/handoff.py)

const base64url = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (n = 48) => base64url(crypto.getRandomValues(new Uint8Array(n)));

export function claims(jwt) {
  const part = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(decodeURIComponent(escape(atob(part))));
}

async function authorizeUrl(config, redirectUri, oauthState) {
  const verifier = randomString();
  const challenge = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: redirectUri,
    scope: "openid email profile",
    code_challenge_method: "S256",
    code_challenge: challenge,
    state: oauthState,
    identity_provider: "Google",
  });
  return { verifier, url: `${config.authDomain}/oauth2/authorize?${params}` };
}

export async function signIn(config) {
  const oauthState = randomString(16);
  const { verifier, url } = await authorizeUrl(config, config.redirectUri, oauthState);
  sessionStorage.setItem("pkce", JSON.stringify({ verifier, oauthState, hash: location.hash }));
  location.assign(url);
}

/**
 * Sign in from the Onshape panel. Google won't show its sign-in page inside an iframe, so a popup
 * signs in on our site and comes back to /onshape/index.html with an authorization code (see
 * finishPopup). The code reaches the panel by postMessage, or, when Google's pages have cut the
 * popup off from this window, through the handoff endpoint, polled here. Only this page holds the
 * PKCE verifier, so the code is useless to anyone else.
 */
export async function signInWithPopup(config, { timeoutMs = 180_000 } = {}) {
  // Open the window before any await, or browsers treat it as an unrequested popup and block it.
  const popup = window.open("about:blank", "torch-signin", "popup,width=480,height=640");
  if (!popup) throw new Error("Your browser blocked the sign-in window. Allow popups for this panel and try again.");
  const oauthState = POPUP_STATE + randomString(24);
  const { verifier, url } = await authorizeUrl(config, config.panelRedirectUri, oauthState);
  popup.location.href = url;

  const code = await new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    let done = false;
    const finish = (fn, value) => {
      if (done) return;
      done = true;
      window.removeEventListener("message", onMessage);
      clearInterval(timer);
      fn(value);
    };
    const onMessage = (event) => {
      if (event.origin !== location.origin || event.data?.type !== "torch-signin" || event.data.state !== oauthState) return;
      if (event.data.error) finish(reject, new Error(event.data.error));
      else finish(resolve, event.data.code);
    };
    window.addEventListener("message", onMessage);
    const timer = setInterval(async () => {
      if (Date.now() > deadline) return finish(reject, new Error("Sign-in timed out. Please try again."));
      try {
        const response = await fetch(`${config.handoffUrl}?${new URLSearchParams({ state: oauthState })}`, { cache: "no-store" });
        if (response.ok) finish(resolve, (await response.json()).code);
      } catch { /* offline for a moment; keep polling */ }
    }, 1500);
  });
  return tokenRequest(config, {
    grant_type: "authorization_code",
    code,
    redirect_uri: config.panelRedirectUri,
    code_verifier: verifier,
  });
}

/** True when this window is the panel's sign-in popup returning from Google (state "p.<...>"). */
export const isPopupReturn = (params) => (params.get("state") || "").startsWith(POPUP_STATE);

/** In the popup: pass the code (or error) back to the panel, both ways, then close. */
export async function finishPopup(config, params) {
  history.replaceState(null, "", location.pathname);
  const state = params.get("state");
  const error = params.get("error") ? (params.get("error_description") || params.get("error")).replace(/^.*failed with error\s*/i, "") : "";
  const code = params.get("code") || "";
  try {
    window.opener?.postMessage({ type: "torch-signin", state, code, error }, location.origin);
  } catch { /* opener gone */ }
  if (code) {
    await fetch(config.handoffUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ state, code }),
    }).catch(() => {});
  }
  if (!error) setTimeout(() => window.close(), 400);
  return error;
}

async function tokenRequest(config, body) {
  const response = await fetch(`${config.authDomain}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: config.clientId, ...body }),
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

export async function completeRedirect(config, params) {
  const saved = JSON.parse(sessionStorage.getItem("pkce") || "null");
  sessionStorage.removeItem("pkce");
  history.replaceState(null, "", location.pathname + (saved?.hash || ""));
  if (!saved || params.get("state") !== saved.oauthState) throw new Error("Sign-in expired. Please try again.");
  return tokenRequest(config, {
    grant_type: "authorization_code",
    code: params.get("code"),
    redirect_uri: config.redirectUri,
    code_verifier: saved.verifier,
  });
}

export async function currentSession(config) {
  const session = store.get("session");
  if (!session) return null;
  if (Date.now() < session.expiresAt) return session;
  if (!session.refreshToken) return null;
  try {
    return await tokenRequest(config, { grant_type: "refresh_token", refresh_token: session.refreshToken });
  } catch {
    store.del("session"); // refresh refused, e.g. removed from the allowlist
    return null;
  }
}

export function signOut(config) {
  store.del("session");
  if (inPanel) return location.reload(); // Cognito's sign-out page can't load inside Onshape
  const params = new URLSearchParams({ client_id: config.clientId, logout_uri: config.redirectUri });
  location.assign(`${config.authDomain}/logout?${params}`);
}
