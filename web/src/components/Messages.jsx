// One question or answer in the thread.
import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { ChatMessage, ChatMessageBubble } from "@astryxdesign/core/Chat";
import { Citation } from "@astryxdesign/core/Citation";
import { Dialog } from "@astryxdesign/core/Dialog";
import { DialogHeader } from "@astryxdesign/core/Dialog";
import { HStack } from "@astryxdesign/core/HStack";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Markdown } from "@astryxdesign/core/Markdown";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { VStack } from "@astryxdesign/core/VStack";
import { BookOpen, Check, Copy, ExternalLink, Pencil, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { Logo } from "./Brand.jsx";

function BotAvatar() {
  return (
    <span className="bot-avatar">
      <Logo size={26} />
    </span>
  );
}

/** Keeps the server's [n] numbers on the chips, so they match the numbered source cards. */
export function NumberedCitation({ source, number }) {
  return <Citation source={source} number={source.n ?? number} variant="number" />;
}

export function sourceMap(list) {
  return Object.fromEntries((list || []).map((s) => [String(s.number), { title: s.title, url: s.url, n: s.number }]));
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function SourceCards({ sources }) {
  if (!sources?.length) return null;
  return (
    <div className="sources">
      <div className="sources-label">
        <BookOpen size={14} aria-hidden="true" />
        <span>Sources</span>
      </div>
      <ol>
        {sources.map((s) => (
          <li key={s.number}>
            <a href={s.url} target="_blank" rel="noopener noreferrer">
              <span className="src-n">{s.number}</span>
              <span className="src-body">
                <span className="src-title">{s.title}</span>
                <span className="src-meta">{hostOf(s.url)}</span>
              </span>
              <ExternalLink size={14} aria-hidden="true" />
            </a>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Feedback({ onSend }) {
  const [state, setState] = useState("idle"); // idle | asking | sent | failed
  const [comment, setComment] = useState("");
  const send = (rating, text = "") => {
    setState("sent");
    onSend(rating, text).catch(() => setState("failed"));
  };
  if (state === "sent") return <Text type="supporting">Thanks for the feedback.</Text>;
  if (state === "failed") return <Text type="supporting">Couldn't send feedback.</Text>;
  return (
    <>
      <IconButton variant="ghost" size="sm" label="Helpful" tooltip="Helpful" icon={<ThumbsUp size={16} />} onClick={() => send("up")} />
      <IconButton variant="ghost" size="sm" label="Not helpful" tooltip="Not helpful" icon={<ThumbsDown size={16} />} onClick={() => setState("asking")} />
      <Dialog isOpen={state === "asking"} onOpenChange={(open) => !open && setState("idle")} purpose="form" padding={4} width={440}>
        <DialogHeader title="What was wrong or missing?" onOpenChange={() => setState("idle")} />
        <VStack gap={3}>
          <TextArea label="Comment (optional)" value={comment} onChange={setComment} placeholder="The answer missed…" />
          <HStack gap={2} justify="end">
            <Button variant="secondary" label="Cancel" onClick={() => setState("idle")} />
            <Button variant="primary" label="Send feedback" onClick={() => send("down", comment)} />
          </HStack>
        </VStack>
      </Dialog>
    </>
  );
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <IconButton
      variant="ghost"
      size="sm"
      label={copied ? "Copied" : "Copy"}
      tooltip={copied ? "Copied" : "Copy"}
      icon={copied ? <Check size={16} /> : <Copy size={16} />}
      onClick={() =>
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        })
      }
    />
  );
}

export function Question({ message, canEdit, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  if (editing) {
    return (
      <ChatMessage sender="user">
        <ChatMessageBubble width="min(640px, 100%)">
          <VStack gap={2}>
            <TextArea label="Edit your question" isLabelHidden value={draft} onChange={setDraft} />
            <HStack gap={2} justify="end">
              <Button variant="secondary" size="sm" label="Cancel" onClick={() => setEditing(false)} />
              <Button
                variant="primary"
                size="sm"
                label="Send"
                isDisabled={!draft.trim()}
                onClick={() => {
                  setEditing(false);
                  onEdit(draft.trim());
                }}
              />
            </HStack>
          </VStack>
        </ChatMessageBubble>
      </ChatMessage>
    );
  }
  return (
    <ChatMessage sender="user">
      <ChatMessageBubble
        metadata={
          canEdit ? (
            <IconButton variant="ghost" size="sm" label="Edit question" tooltip="Edit" icon={<Pencil size={14} />} onClick={() => { setDraft(message.content); setEditing(true); }} />
          ) : null
        }
      >
        <span className="question-text">{message.content}</span>
      </ChatMessageBubble>
    </ChatMessage>
  );
}

export function Answer({ message, isLast, busy, onRetry, onFeedback }) {
  if (message.error) {
    return (
      <ChatMessage sender="assistant" avatar={<BotAvatar />}>
        <ChatMessageBubble variant="ghost" width="100%">
          <Banner
            status="error"
            title={message.error}
            collapsible={false}
            endContent={isLast && !busy ? <Button size="sm" variant="secondary" label="Try again" icon={<RotateCcw size={14} />} onClick={onRetry} /> : null}
          />
        </ChatMessageBubble>
      </ChatMessage>
    );
  }
  if (message.streaming && !message.content) {
    return (
      <ChatMessage sender="assistant" avatar={<BotAvatar />}>
        <ChatMessageBubble variant="ghost">
          <HStack gap={2} align="center">
            <Spinner size="sm" />
            <Text color="secondary">Looking through the references…</Text>
          </HStack>
        </ChatMessageBubble>
      </ChatMessage>
    );
  }
  const sources = message.streaming ? message.retrieved : message.sources;
  const actions = message.streaming ? null : (
    <HStack gap={0.5} align="center">
      <CopyButton text={message.content} />
      {isLast && !busy ? <IconButton variant="ghost" size="sm" label="Retry" tooltip="Retry" icon={<RotateCcw size={16} />} onClick={onRetry} /> : null}
      {message.request_id ? <Feedback onSend={(rating, comment) => onFeedback(message.request_id, rating, comment)} /> : null}
    </HStack>
  );
  return (
    <ChatMessage sender="assistant" avatar={<BotAvatar />}>
      <ChatMessageBubble variant="ghost" width="100%" metadata={actions}>
        <div className={message.streaming ? "answer streaming" : "answer"}>
          <Markdown sources={sourceMap(sources)} citationStyle="number" components={{ citation: NumberedCitation }} isStreaming={!!message.streaming}>
            {message.content}
          </Markdown>
          {message.stopped ? <Text type="supporting" as="p">Stopped.</Text> : null}
          {message.streaming ? null : <SourceCards sources={message.sources} />}
        </div>
      </ChatMessageBubble>
    </ChatMessage>
  );
}
