// The TORCH chat screen built from Web Awesome web components (via their React wrappers).
import "@awesome.me/webawesome/dist/styles/themes/default.css";
import "./webawesome.css";
import "../proto.css";

import { useState } from "react";
import WaAvatar from "@awesome.me/webawesome/dist/react/avatar/index.js";
import WaBadge from "@awesome.me/webawesome/dist/react/badge/index.js";
import WaButton from "@awesome.me/webawesome/dist/react/button/index.js";
import WaCallout from "@awesome.me/webawesome/dist/react/callout/index.js";
import WaCard from "@awesome.me/webawesome/dist/react/card/index.js";
import WaDivider from "@awesome.me/webawesome/dist/react/divider/index.js";
import WaInput from "@awesome.me/webawesome/dist/react/input/index.js";
import WaProgressBar from "@awesome.me/webawesome/dist/react/progress-bar/index.js";
import WaRadio from "@awesome.me/webawesome/dist/react/radio/index.js";
import WaRadioGroup from "@awesome.me/webawesome/dist/react/radio-group/index.js";
import WaTag from "@awesome.me/webawesome/dist/react/tag/index.js";
import WaTextarea from "@awesome.me/webawesome/dist/react/textarea/index.js";
import WaTooltip from "@awesome.me/webawesome/dist/react/tooltip/index.js";
import { Copy, ExternalLink, Plus, RotateCcw, Search, Square, ThumbsDown, ThumbsUp } from "lucide-react";

import { Logo, THEMES, chatGroups, palette, prototypeNotice, question1, question2, resolveTheme, sources } from "../shared.jsx";

function IconAction({ id, label, icon }) {
  return (
    <>
      <WaButton id={id} appearance="plain" size="s" aria-label={label}>{icon}</WaButton>
      <WaTooltip for={id}>{label}</WaTooltip>
    </>
  );
}

function Answer() {
  return (
    <div className="wa-answer">
      <p>
        Add the two pitch diameters and divide by two. For spur gears that's <WaBadge variant="brand" appearance="filled" pill>1</WaBadge>:
      </p>
      <WaCallout variant="brand" appearance="filled-outlined" size="s">
        <span className="wa-formula-label">Center distance</span>
        <code className="wa-formula">C = (N₁ + N₂) / (2 × DP)</code>
      </WaCallout>
      <p>Most FRC gears are <strong>20 DP</strong>, so for your pair:</p>
      <table className="wa-table">
        <thead><tr><th>Gear</th><th>Teeth</th><th>Pitch diameter</th></tr></thead>
        <tbody>
          <tr><td>Pinion</td><td>20</td><td>1.000 in</td></tr>
          <tr><td>Driven</td><td>60</td><td>3.000 in</td></tr>
          <tr className="total"><td colSpan={2}>Center distance</td><td>2.000 in</td></tr>
        </tbody>
      </table>
      <p>
        Put the bearing holes exactly that far apart in your plates <WaBadge variant="brand" appearance="filled" pill>2</WaBadge>, and check the mesh on a test print before you cut aluminum.
      </p>
      <div className="wa-sources">
        {sources.slice(0, 2).map((s) => (
          <WaCard key={s.n} appearance="outlined" className="wa-source">
            <div className="wa-source-row">
              <WaTag variant="brand" size="s" appearance="filled">{s.n}</WaTag>
              <div><strong>{s.title}</strong><small>{s.host} · {s.section}</small></div>
              <ExternalLink size={14} />
            </div>
          </WaCard>
        ))}
      </div>
      <div className="wa-actions">
        <IconAction id="wa-copy" label="Copy" icon={<Copy size={16} />} />
        <IconAction id="wa-retry" label="Retry" icon={<RotateCcw size={16} />} />
        <IconAction id="wa-up" label="Helpful" icon={<ThumbsUp size={16} />} />
        <IconAction id="wa-down" label="Not helpful" icon={<ThumbsDown size={16} />} />
      </div>
    </div>
  );
}

export function WaChat({ initialTheme = "auto" }) {
  const [choice, setChoice] = useState(initialTheme);
  const id = resolveTheme(choice);
  const p = palette[id];

  return (
    <div className={`wa-root wa-theme-default wa-${p.mode} torch-${id}`}>
      <WaCallout variant="warning" appearance="filled" size="s" className={`wa-proto proto ${id}`}>
        <span className="proto-label">{prototypeNotice.label[id]}</span>{prototypeNotice.text}
      </WaCallout>
      <aside className="wa-side">
        <div className="wa-brand">
          <Logo size={30} gear={id === "blueprint" ? "#0d4641" : id === "collegiate" ? "#fff" : p.text} />
          <div><b>TORCH <em>5804</em></b><span>Design Assistant</span></div>
        </div>
        <WaButton variant="brand" appearance="accent" className="wa-new"><Plus slot="start" size={16} />New chat</WaButton>
        <WaInput placeholder="Search chats" size="s" appearance="filled" aria-label="Search chats"><Search slot="start" size={15} /></WaInput>
        <nav className="wa-chats">
          {chatGroups.map(([title, items]) => (
            <section key={title}>
              <h3>{title}</h3>
              {items.map((c) => (
                <a key={c.title} href="#" className={c.current ? "current" : ""}>{c.title}</a>
              ))}
            </section>
          ))}
        </nav>
        <WaDivider />
        <div className="wa-usage">
          <div><span>Today</span><span>12 of ~100 questions</span></div>
          <WaProgressBar value={12} label="Questions used today" />
          <small>Chats are deleted 90 days after your last message.</small>
        </div>
      </aside>

      <main className="wa-main">
        <header className="wa-top">
          <h2>Gear center distance for 20T and 60T</h2>
          <WaRadioGroup orientation="horizontal" size="s" value={choice} aria-label="Theme" onChange={(e) => setChoice(e.target.value)}>
            {THEMES.map((t) => (
              <WaRadio key={t.id} value={t.id} appearance="button">{t.label}</WaRadio>
            ))}
          </WaRadioGroup>
          <WaAvatar initials="AS" label="Alex Student" shape={id === "blueprint" ? "square" : "circle"} />
        </header>

        <div className="wa-thread">
          <div className="wa-user"><div>{question1}</div></div>
          <div className="wa-bot"><span className="wa-bot-mark"><Logo size={24} gear={id === "collegiate" ? "#fff" : p.text} /></span><Answer /></div>
          <div className="wa-user"><div>{question2}</div></div>
          <div className="wa-bot">
            <span className="wa-bot-mark"><Logo size={24} gear={id === "collegiate" ? "#fff" : p.text} /></span>
            <div className="wa-answer">
              <p>Start with a <strong>master sketch</strong> <WaBadge variant="brand" appearance="filled" pill>3</WaBadge> so both plates share one source of truth:</p>
              <ol><li>Draw two construction circles at the pitch diameters, tangent to each other.</li><li>Dimension the center distance to <code>2.000 in</code> and lock it<span className="wa-cursor" /></li></ol>
            </div>
          </div>
        </div>

        <div className="wa-composer">
          <WaTextarea rows={2} resize="none" appearance="outlined" placeholder="Ask a design, CAD or fabrication question" aria-label="Your question" />
          <div className="wa-composer-row">
            <small>Answers come from FRCDesign.org. Check the sources before you cut metal.</small>
            <WaButton variant="neutral" appearance="outlined" size="s"><Square slot="start" size={12} fill="currentColor" />Stop</WaButton>
          </div>
        </div>
      </main>
    </div>
  );
}
