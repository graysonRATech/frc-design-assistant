// The TORCH chat screen built from Astryx (Meta) components.
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@astryxdesign/theme-neutral/theme.css";
import "./astryx.css";
import "../proto.css";

import { useMemo, useState } from "react";
import { Theme, defineTheme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral";
import { AppShell } from "@astryxdesign/core/AppShell";
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { TopNav } from "@astryxdesign/core/TopNav";
import { ChatComposer, ChatLayout, ChatMessage, ChatMessageBubble, ChatMessageList } from "@astryxdesign/core/Chat";
import { Markdown } from "@astryxdesign/core/Markdown";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { TextInput } from "@astryxdesign/core/TextInput";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Avatar } from "@astryxdesign/core/Avatar";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Text } from "@astryxdesign/core/Text";
import { Heading } from "@astryxdesign/core/Heading";
import { Badge } from "@astryxdesign/core/Badge";
import { Card } from "@astryxdesign/core/Card";
import { Banner } from "@astryxdesign/core/Banner";
import { HStack } from "@astryxdesign/core/HStack";
import { VStack } from "@astryxdesign/core/VStack";
import { Copy, ExternalLink, Plus, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";

import {
  Logo, THEMES, prototypeNotice, answer1Markdown, answer2Partial, chatGroups, fonts, palette, question1, question2, resolveTheme, sources,
} from "../shared.jsx";

export function torchTheme(id) {
  const p = palette[id];
  const both = (v) => [v, v];
  return defineTheme({
    name: `torch-${id}`,
    extends: neutralTheme,
    typography: {
      scale: { base: 15, ratio: 1.2 },
      body: { family: "Barlow", fallbacks: "system-ui, sans-serif" },
      heading: { family: "Barlow Condensed", fallbacks: "Barlow, sans-serif" },
      code: { family: "IBM Plex Mono", fallbacks: "ui-monospace, monospace" },
    },
    radius: { base: Math.max(p.radius - 2, 0), multiplier: p.radius <= 2 ? 0 : 1 },
    tokens: {
      "--color-accent": both(p.accent),
      "--color-on-accent": both(p.onAccent),
      "--color-accent-muted": both(p.accentSoft),
      "--color-text-accent": both(id === "forge" ? p.accent : p.accent),
      "--color-icon-accent": both(p.accent),
      "--color-background-body": both(p.bg),
      "--color-background-surface": both(p.surface),
      "--color-background-card": both(p.surface),
      "--color-background-popover": both(p.surface),
      "--color-background-muted": both(p.raised),
      "--color-text-primary": both(p.text),
      "--color-text-secondary": both(p.muted),
      "--color-icon-primary": both(p.text),
      "--color-icon-secondary": both(p.muted),
      "--color-border": both(p.border),
      "--color-border-emphasized": both(id === "blueprint" ? "#0d4641" : p.border),
    },
  });
}

const markdownSources = Object.fromEntries(
  sources.map((s) => [String(s.n), { title: s.title, url: `https://www.frcdesign.org/#${s.n}` }]),
);

function SourceCards() {
  return (
    <div className="ax-sources">
      {sources.slice(0, 2).map((s) => (
        <Card key={s.n} padding={2} elevation="none">
          <HStack gap={2} align="center">
            <Badge variant="neutral" label={String(s.n)} />
            <VStack gap={0}>
              <Text type="label">{s.title}</Text>
              <Text type="supporting">{s.host} · {s.section}</Text>
            </VStack>
            <span className="ax-push" />
            <ExternalLink size={14} />
          </HStack>
        </Card>
      ))}
    </div>
  );
}

function AnswerActions() {
  return (
    <HStack gap={0.5}>
      <IconButton variant="ghost" size="sm" label="Copy" tooltip="Copy" icon={<Copy size={16} />} />
      <IconButton variant="ghost" size="sm" label="Retry" tooltip="Retry" icon={<RotateCcw size={16} />} />
      <IconButton variant="ghost" size="sm" label="Helpful" tooltip="Helpful" icon={<ThumbsUp size={16} />} />
      <IconButton variant="ghost" size="sm" label="Not helpful" tooltip="Not helpful" icon={<ThumbsDown size={16} />} />
    </HStack>
  );
}

function BotAvatar({ id }) {
  const p = palette[id];
  return (
    <span className="ax-bot" style={{ background: id === "collegiate" ? "#0d4641" : p.raised }}>
      <Logo size={26} gear={id === "collegiate" ? "#fff" : p.text} />
    </span>
  );
}

/** Applies a TORCH theme to Astryx components (used by the component kit). */
export function AstryxScope({ id, children }) {
  const theme = useMemo(() => torchTheme(id), [id]);
  return (
    <Theme theme={theme} mode={palette[id].mode}>
      <div className={`kit ax-${id}`} style={{ background: "var(--color-background-body)", color: "var(--color-text-primary)" }}>{children}</div>
    </Theme>
  );
}

export function AstryxChat({ initialTheme = "auto" }) {
  const [choice, setChoice] = useState(initialTheme);
  const id = resolveTheme(choice);
  const theme = useMemo(() => torchTheme(id), [id]);
  const p = palette[id];

  const sideNav = (
    <SideNav
      header={<SideNavHeading heading="TORCH 5804" subheading="Design Assistant" icon={<Logo size={28} gear={p.text} />} />}
      topContent={
        <VStack gap={2}>
          <Button variant="primary" label="New chat" icon={<Plus size={16} />} width="100%" />
          <TextInput label="Search chats" isLabelHidden type="search" value="" onChange={() => {}} placeholder="Search chats" size="sm" />
        </VStack>
      }
      footer={
        <VStack gap={1}>
          <ProgressBar label="Today: 12 of ~100 questions" value={12} max={100} />
          <Text type="supporting" size="xsm">Chats are deleted 90 days after your last message.</Text>
        </VStack>
      }
    >
      {chatGroups.map(([title, items]) => (
        <SideNavSection key={title} title={title}>
          {items.map((c) => (
            <SideNavItem key={c.title} label={c.title} isSelected={!!c.current} href="#" />
          ))}
        </SideNavSection>
      ))}
    </SideNav>
  );

  const topNav = (
    <TopNav
      heading={<Heading level={2} weight="semibold">Gear center distance for 20T and 60T</Heading>}
      endContent={
        <HStack gap={2} align="center">
          <SegmentedControl label="Theme" size="sm" value={choice} onChange={setChoice}>
            {THEMES.map((t) => (
              <SegmentedControlItem key={t.id} value={t.id} label={t.label} />
            ))}
          </SegmentedControl>
          <Avatar name="Alex Student" size="sm" />
        </HStack>
      }
    />
  );

  return (
    <Theme theme={theme} mode={p.mode}>
      <div className={`ax-root ax-${id}`} style={{ "--ax-font-display": fonts.display }}>
        <AppShell
          sideNav={sideNav}
          topNav={topNav}
          variant="section"
          height="fill"
          banner={
            <div className={`proto ${id}`}>
              <Banner
                status="warning"
                container="section"
                isDismissable
                collapsible={false}
                title={<><span className="proto-label">{prototypeNotice.label[id]}</span>{prototypeNotice.text}</>}
              />
            </div>
          }
        >
          <ChatLayout
            composer={
              <ChatComposer
                onSubmit={() => {}}
                isStopShown
                onStop={() => {}}
                placeholder="Ask a design, CAD or fabrication question"
                footerActions={<Text type="supporting" size="xsm">Answers come from FRCDesign.org. Check the sources before you cut metal.</Text>}
              />
            }
          >
            <ChatMessageList isStreaming>
              <ChatMessage sender="user">
                <ChatMessageBubble>{question1}</ChatMessageBubble>
              </ChatMessage>
              <ChatMessage sender="assistant" avatar={<BotAvatar id={id} />}>
                <ChatMessageBubble variant="ghost" metadata={<AnswerActions />}>
                  <Markdown sources={markdownSources} citationStyle="number">{answer1Markdown}</Markdown>
                  <SourceCards />
                </ChatMessageBubble>
              </ChatMessage>
              <ChatMessage sender="user">
                <ChatMessageBubble>{question2}</ChatMessageBubble>
              </ChatMessage>
              <ChatMessage sender="assistant" avatar={<BotAvatar id={id} />}>
                <ChatMessageBubble variant="ghost">
                  <Markdown sources={markdownSources} citationStyle="number" isStreaming>{answer2Partial}</Markdown>
                </ChatMessageBubble>
              </ChatMessage>
            </ChatMessageList>
          </ChatLayout>
        </AppShell>
      </div>
    </Theme>
  );
}
