// One page structure for every direction; each variant's CSS (src/variants/*.css) restyles it.
// Elements a variant doesn't use (e.g. the drawing title block) are hidden by base.css.

import { chats, sources, suggestions, usage, user } from "./data.js";

const icon = (d, extra = "") => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" ${extra}><path d="${d}"/></svg>`;
export const icons = {
  plus: icon("M12 5v14M5 12h14"),
  search: icon("M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14zM20 20l-4-4"),
  menu: icon("M4 7h16M4 12h16M4 17h16"),
  copy: icon("M9 9h10v10H9zM5 15V5h10"),
  retry: icon("M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"),
  edit: icon("M4 20h4L18.5 9.5a2.1 2.1 0 0 0-4-4L4 16v4zM13.5 6.5l4 4"),
  up: icon("M7 11v9H4v-9zM7 11l4-8a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 6.6a2 2 0 0 1-2 1.6H7"),
  down: icon("M17 13V4h3v9zM17 13l-4 8a2 2 0 0 1-2-2v-4H5.5a2 2 0 0 1-2-2.3l1.2-6.6a2 2 0 0 1 2-1.6H17"),
  stop: icon("M7 7h10v10H7z"),
  send: icon("M5 12h14M13 6l6 6-6 6"),
  external: icon("M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"),
  book: icon("M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 21V5M8 7h7"),
  chevron: icon("M9 6l6 6-6 6"),
  more: icon("M5 12h.01M12 12h.01M19 12h.01"),
};

let logoCount = 0;

/** Placeholder mark: a flame inside a gear, drawn for these mockups (swap in the team's real logo). */
export function logo(size = 36) {
  const id = `flame-${++logoCount}`;
  return `<svg class="logo" width="${size}" height="${size}" viewBox="0 0 64 64" role="img" aria-label="TORCH 5804">
    <defs>
      <linearGradient id="${id}" x1="0" y1="1" x2="0" y2="0">
        <stop offset="0" stop-color="var(--flame-1, #FD9727)"/><stop offset="1" stop-color="var(--flame-2, #FECC07)"/>
      </linearGradient>
    </defs>
    <circle cx="32" cy="32" r="26" fill="none" stroke="var(--gear, #fff)" stroke-width="9" stroke-dasharray="7.6 8.73"/>
    <circle cx="32" cy="32" r="22" fill="var(--gear, #fff)"/>
    <circle cx="32" cy="32" r="17" fill="var(--gear-hole, #0D4641)"/>
    <path d="M32 13c5 7 10 11 9 19-.6 5-4.4 9-9 9s-8.6-3.5-9-8.4c-.4-5 2.6-7.6 4.3-11.1.9 2.8 2 4.3 3.4 5.3.5-5 .2-9.4 1.3-13.8z" fill="url(#${id})"/>
    <path d="M32 27c2.2 3 4.3 5 3.8 8.3-.3 2.1-1.9 3.7-3.8 3.7s-3.6-1.4-3.8-3.4c-.2-2.2 1.3-3.5 2.1-5.2.6 1 1.1 1.5 1.7 1.8z" fill="var(--flame-core, #FFF4C2)"/>
  </svg>`;
}

function brand() {
  return `<a class="brand" href="#">
      ${logo()}
      <span class="brand-words"><span class="brand-name">TORCH <b>5804</b></span><span class="brand-sub">Design Assistant</span></span>
    </a>`;
}

function chatGroup(label, items, open) {
  const rows = items
    .map(
      (c) => `<li class="${c.current && open ? "current" : ""}"><a href="#">${c.title}</a>${c.current && open ? `<button class="icon-btn small" aria-label="More">${icons.more}</button>` : ""}</li>`,
    )
    .join("");
  return `<div class="chat-group"><h3>${label}</h3><ol>${rows}</ol></div>`;
}

function sidebar(open) {
  const pct = Math.round((usage.used / usage.cap) * 100);
  return `<aside class="sidebar">
      <button class="new-chat">${icons.plus}<span>New chat</span><kbd>Ctrl K</kbd></button>
      <label class="search">${icons.search}<input placeholder="Search chats" /></label>
      <nav class="chats" aria-label="Saved chats">
        ${chatGroup("Today", chats.today, open)}
        ${chatGroup("Previous 7 days", chats.week, open)}
        ${chatGroup("Older", chats.older, open)}
      </nav>
      <div class="sidebar-foot">
        <div class="meter" style="--pct:${pct}%">
          <div class="meter-label"><span>Today</span><span>${usage.used} of ~${usage.cap} questions</span></div>
          <div class="meter-track"><div class="meter-fill"></div></div>
        </div>
        <p class="fine">Chats are deleted 90 days after your last message.</p>
      </div>
    </aside>`;
}

function topbar(title) {
  return `<header class="topbar">
      <button class="icon-btn menu" aria-label="Show chats">${icons.menu}</button>
      ${brand()}
      <div class="topbar-title">${title}</div>
      <div class="account"><span class="avatar">${user.initials}</span></div>
    </header>`;
}

const cite = (n) => `<a class="cite" href="#" title="${sources[n - 1].title}">${n}</a>`;

function sourceCards(list) {
  return `<div class="sources">
      <div class="sources-label">${icons.book}<span>Sources</span></div>
      <ol>${list
        .map(
          (s) => `<li><a href="#"><span class="src-n">${s.n}</span><span class="src-body"><span class="src-title">${s.title}</span><span class="src-meta">${s.host} · ${s.section}</span></span>${icons.external}</a></li>`,
        )
        .join("")}</ol>
    </div>`;
}

function actions() {
  return `<div class="msg-actions">
      <button class="act" aria-label="Copy">${icons.copy}<span>Copy</span></button>
      <button class="act" aria-label="Retry">${icons.retry}<span>Retry</span></button>
      <span class="act-sep"></span>
      <button class="act" aria-label="Helpful">${icons.up}</button>
      <button class="act" aria-label="Not helpful">${icons.down}</button>
    </div>`;
}

function conversation() {
  return `<ol class="thread">
      <li class="msg user"><div class="bubble">How do I calculate the center distance for two gears? We're pairing a 20T pinion with a 60T gear.</div>
        <button class="act edit" aria-label="Edit">${icons.edit}</button></li>
      <li class="msg assistant">
        <div class="avatar-bot">${logo(28)}</div>
        <div class="answer">
          <p>Add the two pitch diameters and divide by two. For spur gears that's the same as ${cite(1)}:</p>
          <div class="formula"><span class="formula-label">Center distance</span><code>C = (N<sub>1</sub> + N<sub>2</sub>) / (2 × DP)</code></div>
          <p>Most FRC gears are <strong>20 DP</strong>, so for your pair:</p>
          <div class="table-wrap"><table>
            <thead><tr><th>Gear</th><th>Teeth</th><th>Pitch diameter</th></tr></thead>
            <tbody><tr><td>Pinion</td><td>20</td><td>1.000 in</td></tr><tr><td>Driven</td><td>60</td><td>3.000 in</td></tr><tr class="total"><td colspan="2">Center distance</td><td>2.000 in</td></tr></tbody>
          </table></div>
          <p>Put the bearing holes exactly that far apart in your plates ${cite(2)}, and check the mesh on a test print before you cut aluminum.</p>
          ${sourceCards(sources.slice(0, 2))}
          ${actions()}
        </div>
      </li>
      <li class="msg user"><div class="bubble">How should I set that up in Onshape?</div></li>
      <li class="msg assistant streaming">
        <div class="avatar-bot">${logo(28)}</div>
        <div class="answer">
          <p>Start with a <strong>master sketch</strong> ${cite(3)} so both plates share one source of truth:</p>
          <ol><li>Draw two construction circles at the pitch diameters, tangent to each other.</li><li>Dimension the center distance to <code>2.000 in</code> and lock it<span class="cursor"></span></li></ol>
        </div>
      </li>
    </ol>`;
}

function composer(busy) {
  return `<form class="composer">
      <textarea rows="1" placeholder="Ask a design, CAD or fabrication question"></textarea>
      <div class="composer-row">
        <span class="composer-hint">Answers come from FRCDesign.org. Check the sources, and ask a mentor before you cut metal.</span>
        ${busy ? `<button type="button" class="stop">${icons.stop}<span>Stop</span></button>` : `<button type="submit" class="send" aria-label="Ask">${icons.send}</button>`}
      </div>
    </form>`;
}

function emptyState() {
  return `<section class="empty">
      <div class="empty-mark">${logo(64)}</div>
      <p class="eyebrow">TORCH 5804 · Design Assistant</p>
      <h1>What are we building today?</h1>
      <p class="lede">Ask about mechanisms, Onshape CAD and fabrication. Every answer links back to the FRCDesign.org pages it came from.</p>
      <div class="suggestions">${suggestions
        .map((s) => `<button class="suggestion"><span class="tag">${s.tag}</span><span class="s-text">${s.text}</span>${icons.chevron}</button>`)
        .join("")}</div>
    </section>`;
}

function titleBlock() {
  return `<div class="title-block" aria-hidden="true">
      <div><span>Team</span><b>TORCH 5804</b></div>
      <div><span>Drawing</span><b>DA-0412</b></div>
      <div><span>Sheet</span><b>1 of 1</b></div>
      <div><span>Ref</span><b>FRCDesign.org</b></div>
    </div>`;
}

/** Full app page. screen: "conversation" | "empty". */
export function appPage(variant, { screen = "conversation", mobile = false, drawer = false } = {}) {
  const busy = screen === "conversation";
  const classes = ["app", `v-${variant}`, mobile ? "is-mobile" : "", drawer ? "drawer-open" : ""].join(" ");
  return `<div class="${classes}">
      ${topbar(busy ? "Gear center distance for 20T and 60T" : "New chat")}
      <div class="body">
        ${sidebar(busy)}
        <div class="scrim"></div>
        <main class="main">
          <div class="main-inner">${screen === "empty" ? emptyState() : conversation()}</div>
          <div class="composer-wrap">${composer(busy)}</div>
          ${titleBlock()}
        </main>
      </div>
    </div>`;
}

export function signInPage(variant) {
  return `<div class="app signin v-${variant}">
      <div class="signin-art" aria-hidden="true"><div class="signin-glow"></div></div>
      <section class="signin-card">
        ${logo(72)}
        <p class="eyebrow">FRC Team 5804 · Collegiate School</p>
        <h1>TORCH Design Assistant</h1>
        <p class="lede">Mechanism design, Onshape CAD and fabrication answers from team-approved references like FRCDesign.org.</p>
        <button class="google">
          <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.7v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z"/><path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z"/><path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8z"/><path fill="#EA4335" d="M12 4.8c1.8 0 3.4.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z"/></svg>
          Sign in with Google
        </button>
        <p class="fine">For TORCH students and mentors. Use your school Google account.</p>
      </section>
      <footer class="signin-foot"><span>2022 World Championship · 3rd place</span><span>2023 Newton Division winners</span></footer>
    </div>`;
}

/** A phone-sized frame around a page, for the mobile stories. */
export function phone(html) {
  return `<div class="phone-stage"><div class="phone">${html}</div></div>`;
}
