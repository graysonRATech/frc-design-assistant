// Calls to the HTTP API (saved chats, feedback, settings) and the streaming chat URL.
import { currentSession } from "./auth.js";

export class SignedOut extends Error {
  constructor(message = "Your session ended. Please sign in again.") {
    super(message);
  }
}

async function headers(config) {
  const session = await currentSession(config);
  if (!session) throw new SignedOut();
  return { "content-type": "application/json", authorization: `Bearer ${session.idToken}` };
}

export async function api(config, method, path, body) {
  const response = await fetch(`${config.apiUrl}${path}`, {
    method,
    headers: await headers(config),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) throw new SignedOut();
  if (!response.ok) throw new Error(data.error || data.message || `Request failed (${response.status})`);
  return data;
}

/** POST a question to the stream URL and yield its NDJSON events (see backend/chat_api/streaming.py). */
export async function* streamAnswer(config, body) {
  const response = await fetch(config.streamUrl, { method: "POST", headers: await headers(config), body: JSON.stringify(body) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) throw new SignedOut(data.error);
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  const reader = response.body.getReader();
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
