// Google sign-in through the Cognito hosted UI: authorization code + PKCE, tokens kept in
// localStorage and refreshed with the refresh token. /config.json is written at deploy time.

export const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  del: (k) => { try { localStorage.removeItem(k); } catch { /* private mode */ } },
};

const base64url = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (n = 48) => base64url(crypto.getRandomValues(new Uint8Array(n)));

export function claims(jwt) {
  const part = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(decodeURIComponent(escape(atob(part))));
}

export async function signIn(config) {
  const verifier = randomString();
  const challenge = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const oauthState = randomString(16);
  sessionStorage.setItem("pkce", JSON.stringify({ verifier, oauthState, hash: location.hash }));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: "openid email profile",
    code_challenge_method: "S256",
    code_challenge: challenge,
    state: oauthState,
    identity_provider: "Google",
  });
  location.assign(`${config.authDomain}/oauth2/authorize?${params}`);
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
  const params = new URLSearchParams({ client_id: config.clientId, logout_uri: config.redirectUri });
  location.assign(`${config.authDomain}/logout?${params}`);
}
