// The signed-in app: saved chats in the side nav, the thread, the composer, and the account menu
// (theme picker, sign out). Answers stream from the stream URL; chats are saved by the server.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { ChatComposer, ChatLayout, ChatMessageList } from "@astryxdesign/core/Chat";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from "@astryxdesign/core/DropdownMenu";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { IconButton } from "@astryxdesign/core/IconButton";
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { TopNav } from "@astryxdesign/core/TopNav";
import { VStack } from "@astryxdesign/core/VStack";
import { ChevronRight, LogOut, MoreHorizontal, Plus } from "lucide-react";
import { SignedOut, api, streamAnswer } from "../lib/api.js";
import { claims, signOut } from "../lib/auth.js";
import { THEMES } from "../lib/theme.js";
import { Logo, PrototypeBanner } from "./Brand.jsx";
import { Answer, Question } from "./Messages.jsx";

const SUGGESTIONS = [
  { tag: "Gearing", text: "How do I calculate the center distance for two gears?" },
  { tag: "Fabrication", text: "What bolts should we use for most of the robot?" },
  { tag: "Onshape", text: "How should I set up a master sketch in Onshape?" },
  { tag: "Mechanisms", text: "How much compression should a shooter have?" },
];

const chatIdFromHash = () => location.hash.match(/^#c=([\w-]+)$/)?.[1] || null;

function groupChats(chats) {
  const now = Date.now();
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  const groups = [["Today", []], ["Previous 7 days", []], ["Older", []]];
  for (const chat of chats) {
    const t = Date.parse(chat.updated_at) || 0;
    groups[t >= startOfToday ? 0 : t >= now - 7 * 864e5 ? 1 : 2][1].push(chat);
  }
  return groups.filter(([, items]) => items.length);
}

/** "alex.student@school.org" -> "Alex Student", so the avatar shows sensible initials. */
function displayName(email) {
  const parts = (email || "").split("@")[0].split(/[._-]+/).filter(Boolean);
  return parts.map((p) => p[0].toUpperCase() + p.slice(1)).join(" ") || email;
}

export function ChatApp({ config, session, themeId, themeChoice, onThemeChange, onSignedOut }) {
  const email = useMemo(() => claims(session.idToken).email || "", [session]);
  const [chats, setChats] = useState([]);
  const [chatId, setChatId] = useState(chatIdFromHash);
  const [messages, setMessages] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [renaming, setRenaming] = useState(null); // {id, title}
  const [deleting, setDeleting] = useState(null); // chat
  const requestId = useRef(null);
  const [stopping, setStopping] = useState(false);

  const handle = useCallback(
    (error) => {
      if (error instanceof SignedOut) onSignedOut(error.message);
      return error;
    },
    [onSignedOut],
  );
  const call = useCallback((method, path, body) => api(config, method, path, body).catch((e) => Promise.reject(handle(e))), [config, handle]);

  useEffect(() => {
    call("GET", "/chats").then((d) => setChats(d.chats)).catch(() => {});
  }, [call]);

  // Open the chat in the URL (and follow back/forward).
  useEffect(() => {
    const onNav = () => !busy && setChatId(chatIdFromHash());
    window.addEventListener("hashchange", onNav);
    window.addEventListener("popstate", onNav);
    return () => {
      window.removeEventListener("hashchange", onNav);
      window.removeEventListener("popstate", onNav);
    };
  }, [busy]);

  const openedId = useRef(null);
  useEffect(() => {
    if (busy || openedId.current === chatId) return;
    openedId.current = chatId;
    setLoadError("");
    setMessages([]);
    if (!chatId) return;
    call("GET", `/chats/${chatId}`)
      .then((chat) => openedId.current === chatId && setMessages(chat.messages))
      .catch((e) => openedId.current === chatId && setLoadError(e.message));
  }, [chatId, busy, call]);

  const goTo = (id) => {
    if (busy) return;
    if (id) location.hash = `c=${id}`;
    else history.pushState(null, "", location.pathname);
    setChatId(id);
  };

  const rememberChat = (id, title) =>
    setChats((list) => {
      const existing = list.find((c) => c.id === id);
      return [{ ...existing, id, title: existing?.title || title, updated_at: new Date().toISOString() }, ...list.filter((c) => c.id !== id)];
    });

  /** Ask a question. replaceLast re-asks the last turn (retry / edit); trimmed means the caller already removed it locally. */
  const send = async (question, { replaceLast = false, trimmed = false } = {}) => {
    if (busy || !question.trim()) return;
    let base = messages;
    if (replaceLast && !trimmed) {
      base = [...messages];
      if (base.at(-1)?.role === "assistant") base.pop();
      if (base.at(-1)?.role === "user") base.pop();
    }
    let answer = { role: "assistant", content: "", streaming: true };
    const update = (patch) => {
      answer = { ...answer, ...patch };
      setMessages((list) => [...list.slice(0, -1), answer]);
    };
    setMessages([...base, { role: "user", content: question }, answer]);
    setBusy(true);
    setStopping(false);
    let currentChat = chatId;
    try {
      for await (const event of streamAnswer(config, { question, chat_id: chatId, replace_last: replaceLast })) {
        if (event.type === "start") {
          requestId.current = event.request_id;
          update({ retrieved: event.sources });
          if (!currentChat) {
            currentChat = event.chat_id;
            openedId.current = currentChat;
            history.replaceState(null, "", `#c=${currentChat}`);
            setChatId(currentChat);
          }
        } else if (event.type === "delta") {
          update({ content: answer.content + event.text });
        } else if (event.type === "replace") {
          update({ content: event.text });
        } else if (event.type === "done") {
          update({
            sources: event.sources,
            request_id: event.request_id,
            stopped: event.stopped,
            content: event.saved ? answer.content : `${answer.content}\n\n*This chat is full, so this answer wasn't saved. Start a new chat to keep going.*`,
          });
          rememberChat(event.chat_id, event.title);
        } else if (event.type === "error") {
          throw Object.assign(new Error(event.error), { unsaved: true });
        }
      }
      if (!answer.request_id) throw new Error("The answer was cut off. Try again.");
    } catch (error) {
      if (error instanceof SignedOut) {
        handle(error);
      } else if (!answer.content || error.unsaved) {
        update({ error: error.message, replaceLast });
      } else {
        update({ stopped: true });
      }
    } finally {
      update({ streaming: false, retrieved: undefined });
      requestId.current = null;
      setBusy(false);
    }
  };

  const stop = () => {
    if (!requestId.current) return;
    setStopping(true);
    // The server checks for this about once a second, then finishes and saves what it has.
    call("POST", "/chats/stop", { request_id: requestId.current }).catch(() => setStopping(false));
  };

  const lastQuestion = [...messages].reverse().find((m) => m.role === "user")?.content;
  const retry = () => {
    const last = messages.at(-1);
    if (!lastQuestion) return;
    if (last?.error) {
      // A failed turn was never saved: drop it here and ask again the way it was first sent.
      setMessages(messages.slice(0, -2));
      send(lastQuestion, { replaceLast: last.replaceLast, trimmed: true });
      return;
    }
    send(lastQuestion, { replaceLast: true });
  };
  const edit = (question) => {
    const last = messages.at(-1);
    if (last?.error) {
      setMessages(messages.slice(0, -2));
      send(question, { replaceLast: last.replaceLast, trimmed: true });
      return;
    }
    send(question, { replaceLast: true });
  };

  const rename = async () => {
    const { id, title } = renaming;
    setRenaming(null);
    if (!title.trim()) return;
    const result = await call("PATCH", `/chats/${id}`, { title: title.trim() }).catch(() => null);
    if (result) setChats((list) => list.map((c) => (c.id === id ? { ...c, title: result.title } : c)));
  };

  const remove = async () => {
    const chat = deleting;
    setDeleting(null);
    await call("DELETE", `/chats/${chat.id}`).catch(() => null);
    setChats((list) => list.filter((c) => c.id !== chat.id));
    if (chat.id === chatId) goTo(null);
  };

  const visibleChats = search.trim() ? chats.filter((c) => c.title.toLowerCase().includes(search.trim().toLowerCase())) : chats;
  const current = chats.find((c) => c.id === chatId);
  const lastIndex = messages.length - 1;

  const sideNav = (
    <SideNav
      header={<SideNavHeading heading="TORCH 5804" subheading="Design Assistant" icon={<Logo size={30} />} />}
      topContent={
        <VStack gap={2}>
          <Button variant="primary" label="New chat" icon={<Plus size={16} />} width="100%" isDisabled={busy} onClick={() => goTo(null)} />
          <TextInput label="Search chats" isLabelHidden type="search" size="sm" value={search} onChange={setSearch} placeholder="Search chats" />
        </VStack>
      }
      footer={<Text type="supporting" size="xsm">Chats are deleted {config.chatRetentionDays || 90} days after your last message.</Text>}
    >
      {visibleChats.length === 0 ? (
        <Text type="supporting" className="nav-empty">{search ? "No chats match." : "Your chats will show up here."}</Text>
      ) : (
        groupChats(visibleChats).map(([title, items]) => (
          <SideNavSection key={title} title={title}>
            {items.map((chat) => (
              <SideNavItem
                key={chat.id}
                label={chat.title || "Untitled chat"}
                href={`#c=${chat.id}`}
                isSelected={chat.id === chatId}
                isDisabled={busy && chat.id !== chatId}
                onClick={(e) => {
                  e.preventDefault();
                  goTo(chat.id);
                }}
                actions={
                  <DropdownMenu
                    hasChevron={false}
                    renderTrigger={(props) => <IconButton {...props} variant="ghost" size="sm" label={`More for ${chat.title}`} icon={<MoreHorizontal size={16} />} />}
                    items={[
                      { label: "Rename", onClick: () => setRenaming({ id: chat.id, title: chat.title }) },
                      { label: "Delete", variant: "destructive", onClick: () => setDeleting(chat) },
                    ]}
                  />
                }
              />
            ))}
          </SideNavSection>
        ))
      )}
    </SideNav>
  );

  const accountMenu = (
    <DropdownMenu
      hasChevron={false}
      alignment="end"
      menuWidth={300}
      menuMaxHeight={460}
      renderTrigger={(props) => <Avatar {...props} name={displayName(email)} alt={`Account: ${email}`} size="sm" tooltip={false} />}
    >
      <DropdownMenuGroup title={email}>
        <DropdownMenuRadioGroup label="Theme" value={themeChoice} onChange={onThemeChange}>
          {THEMES.map((t) => (
            <DropdownMenuRadioItem key={t.id} value={t.id} label={t.label} description={t.description} />
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuGroup>
      <DropdownMenuDivider />
      <DropdownMenuItem label="Sign out" icon={<LogOut size={16} />} onClick={() => signOut(config)} />
    </DropdownMenu>
  );

  const topNav = (
    <TopNav
      heading={
        <Heading level={2} maxLines={1} className="chat-title">
          {current?.title || messages.find((m) => m.role === "user")?.content || "New chat"}
        </Heading>
      }
      endContent={accountMenu}
    />
  );

  const welcome = (
    <section className="welcome">
      <Logo size={64} />
      <Text type="label" color="accent" className="eyebrow">TORCH 5804 · Design Assistant</Text>
      <Heading level={1} justify="center">What are we building today?</Heading>
      <Text color="secondary" justify="center" as="p">
        Ask about mechanisms, Onshape CAD and fabrication. Every answer links back to the FRCDesign.org pages it came from.
      </Text>
      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s.text} type="button" className="suggestion" onClick={() => send(s.text)}>
            <span className="suggestion-tag">{s.tag}</span>
            <span className="suggestion-text">{s.text}</span>
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        ))}
      </div>
    </section>
  );

  return (
    <>
      <AppShell sideNav={sideNav} topNav={topNav} variant="section" height="fill" banner={<PrototypeBanner themeId={themeId} />}>
        <div className="chat-area">
        <ChatLayout
          emptyState={loadError ? <Banner status="error" title={loadError} /> : welcome}
          composer={
            <ChatComposer
              value={draft}
              onChange={setDraft}
              onSubmit={(value) => {
                setDraft("");
                send(value);
              }}
              isStopShown={busy}
              onStop={stop}
              placeholder="Ask a design, CAD or fabrication question"
              footerActions={
                <Text type="supporting" size="xsm">
                  {stopping ? "Stopping…" : "Answers can be wrong. Check the sources, and ask a mentor before you cut metal."}
                </Text>
              }
            />
          }
        >
          {messages.length ? (
            <ChatMessageList isStreaming={busy}>
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <Question key={`${i}-${m.content}`} message={m} canEdit={!busy && i >= lastIndex - 1} onEdit={edit} />
                ) : (
                  <Answer
                    key={i}
                    message={m}
                    isLast={i === lastIndex}
                    busy={busy}
                    onRetry={retry}
                    onFeedback={(request_id, rating, comment) => call("POST", "/feedback", { request_id, rating, comment })}
                  />
                ),
              )}
            </ChatMessageList>
          ) : null}
        </ChatLayout>
        </div>
      </AppShell>

      <Dialog isOpen={!!renaming} onOpenChange={(open) => !open && setRenaming(null)} purpose="form" padding={4} width={420}>
        <DialogHeader title="Rename chat" onOpenChange={() => setRenaming(null)} />
        <VStack gap={3}>
          <TextInput label="Name" value={renaming?.title || ""} onChange={(title) => setRenaming((r) => ({ ...r, title }))} onEnter={rename} />
          <HStack gap={2} justify="end">
            <Button variant="secondary" label="Cancel" onClick={() => setRenaming(null)} />
            <Button variant="primary" label="Save" onClick={rename} />
          </HStack>
        </VStack>
      </Dialog>

      <AlertDialog
        isOpen={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this chat?"
        description={`"${deleting?.title || ""}" will be deleted for good.`}
        actionLabel="Delete"
        onAction={remove}
      />
    </>
  );
}
