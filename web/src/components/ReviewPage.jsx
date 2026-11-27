// Mentor-only: answers students rated, with the question, answer, sources and what search found,
// so each thumbs-down gets a look. A mentor marks an item done (with a note) or copies it as a
// starting point for a case in evals/answers.yaml. Served by GET/POST /review (backend/chat_api/review.py).
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Blockquote } from "@astryxdesign/core/Blockquote";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Markdown } from "@astryxdesign/core/Markdown";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { TopNav } from "@astryxdesign/core/TopNav";
import { VStack } from "@astryxdesign/core/VStack";
import { ArrowLeft, Check, ClipboardCopy, Inbox, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { PrototypeBanner } from "./Brand.jsx";
import { NumberedCitation, SourceCards, sourceMap } from "./Messages.jsx";

const when = (iso) => {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : new Date(t).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
};

/** A starting point for evals/answers.yaml. JSON strings are valid YAML, so quoting is safe. */
export function evalCase(item) {
  const id = (item.question || "case")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(" ")
    .slice(0, 4)
    .join("-");
  const lines = [
    `  - id: ${id}`,
    "    tags: []",
    `    question: ${JSON.stringify(item.question || "")}`,
    "    rubric:",
    `      - ${JSON.stringify(item.comment ? `TODO, from the student's feedback: ${item.comment}` : "TODO: what a correct answer must say")}`,
  ];
  return lines.join("\n") + "\n";
}

function ReviewItem({ item, call, onChanged }) {
  const [note, setNote] = useState(item.note || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const done = item.status === "done";

  const mark = async (status) => {
    setSaving(true);
    setError("");
    try {
      onChanged({ ...item, ...(await call("POST", "/review", { id: item.id, status, note })) });
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const copy = () =>
    navigator.clipboard.writeText(evalCase(item)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });

  return (
    <Card padding={4} variant={done ? "muted" : "default"}>
      <VStack gap={3}>
        <HStack gap={2} align="center" wrap="wrap">
          {item.rating === "up" ? (
            <Badge variant="success" icon={<ThumbsUp size={12} />} label="Helpful" />
          ) : (
            <Badge variant="error" icon={<ThumbsDown size={12} />} label="Not helpful" />
          )}
          {done ? <Badge variant="neutral" icon={<Check size={12} />} label="Reviewed" /> : null}
          <Text type="supporting">
            {item.user} · {when(item.rated_at)}
            {item.model ? ` · ${item.model}` : ""}
          </Text>
        </HStack>

        {item.comment ? <Blockquote cite="Student's comment">{item.comment}</Blockquote> : null}

        {item.question ? (
          <>
            <Heading level={3}>{item.question}</Heading>
            <div className="answer review-answer">
              <Markdown sources={sourceMap(item.sources)} citationStyle="number" components={{ citation: NumberedCitation }}>
                {item.answer || "*(No answer text was recorded.)*"}
              </Markdown>
            </div>
            <SourceCards sources={item.sources?.filter((s) => s.url)?.map((s) => ({ ...s, title: s.title || s.url }))} />
            {item.retrieved?.length ? (
              <Collapsible defaultIsOpen={false} trigger={<Text type="label">What search found ({item.retrieved.length})</Text>}>
                <ol className="review-retrieved">
                  {item.retrieved.map((r, i) => (
                    <li key={i}>
                      <a href={r.url} target="_blank" rel="noopener noreferrer">{r.url}</a>
                      {r.score != null ? <Text type="supporting"> · score {Number(r.score).toFixed(2)}</Text> : null}
                    </li>
                  ))}
                </ol>
              </Collapsible>
            ) : null}
          </>
        ) : (
          <Text color="secondary">
            The answer for this rating wasn't found (it may be older than the chat retention period). Request {item.request_id}.
          </Text>
        )}

        {done && item.reviewed_by ? (
          <Text type="supporting">
            Reviewed by {item.reviewed_by}
            {item.note ? `: ${item.note}` : ""}
          </Text>
        ) : null}
        {error ? <Banner status="error" title={error} /> : null}

        <HStack gap={2} align="end" wrap="wrap">
          {!done ? (
            <div className="review-note">
              <TextInput label="Note (optional)" size="sm" value={note} onChange={setNote} placeholder="e.g. added eval case, fixed source" onEnter={() => mark("done")} />
            </div>
          ) : null}
          {done ? (
            <Button variant="secondary" size="sm" label="Reopen" icon={<RotateCcw size={14} />} isDisabled={saving} onClick={() => mark("open")} />
          ) : (
            <Button variant="primary" size="sm" label="Mark reviewed" icon={<Check size={14} />} isDisabled={saving} onClick={() => mark("done")} />
          )}
          {item.question ? (
            <Button variant="secondary" size="sm" label={copied ? "Copied" : "Copy as test case"} icon={<ClipboardCopy size={14} />} onClick={copy} />
          ) : null}
        </HStack>
      </VStack>
    </Card>
  );
}

export function ReviewPage({ call, themeId, accountMenu, onBack }) {
  const [rating, setRating] = useState("down");
  const [status, setStatus] = useState("open");
  const [items, setItems] = useState(null); // null while loading
  const [next, setNext] = useState(null);
  const [error, setError] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(
    (cursor) => {
      const params = new URLSearchParams({ rating, status, ...(cursor ? { cursor } : {}) });
      return call("GET", `/review?${params}`);
    },
    [call, rating, status],
  );

  useEffect(() => {
    let current = true;
    setItems(null);
    setError("");
    load(null)
      .then((page) => current && (setItems(page.items), setNext(page.next)))
      .catch((e) => current && (setError(e.message), setItems([])));
    return () => {
      current = false;
    };
  }, [load]);

  const more = async () => {
    setLoadingMore(true);
    try {
      const page = await load(next);
      setItems((list) => [...list, ...page.items]);
      setNext(page.next);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingMore(false);
    }
  };

  const changed = (updated) =>
    setItems((list) => (status !== "all" && updated.status !== status ? list.filter((i) => i.id !== updated.id) : list.map((i) => (i.id === updated.id ? { ...i, ...updated } : i))));

  const topNav = (
    <TopNav
      startContent={<Button variant="ghost" size="sm" label="Back to chat" icon={<ArrowLeft size={16} />} onClick={onBack} />}
      heading={<Heading level={2} className="chat-title">Feedback review</Heading>}
      endContent={accountMenu}
    />
  );

  return (
    <AppShell topNav={topNav} variant="section" height="fill" banner={<PrototypeBanner themeId={themeId} />}>
      <div className="review-page">
        <VStack gap={4}>
          <Text color="secondary" as="p">
            Answers students rated. Read what went wrong, fix the source or the prompt if needed, then mark it reviewed. "Copy as test case"
            gives a starting point for evals/answers.yaml, so the fix stays fixed.
          </Text>
          <HStack gap={3} wrap="wrap">
            <SegmentedControl label="Rating" size="sm" value={rating} onChange={setRating}>
              <SegmentedControlItem value="down" label="Not helpful" />
              <SegmentedControlItem value="up" label="Helpful" />
              <SegmentedControlItem value="all" label="All" />
            </SegmentedControl>
            <SegmentedControl label="Status" size="sm" value={status} onChange={setStatus}>
              <SegmentedControlItem value="open" label="To review" />
              <SegmentedControlItem value="done" label="Reviewed" />
              <SegmentedControlItem value="all" label="All" />
            </SegmentedControl>
          </HStack>
          {error ? <Banner status="error" title={error} /> : null}
          {items === null ? (
            <HStack gap={2} align="center">
              <Spinner size="sm" />
              <Text color="secondary">Loading feedback…</Text>
            </HStack>
          ) : items.length === 0 && !error ? (
            <EmptyState
              icon={<Inbox size={32} />}
              title={status === "open" ? "Nothing to review" : "No feedback here"}
              description={status === "open" ? "New ratings from students will show up here." : "Try another filter."}
            />
          ) : (
            items.map((item) => <ReviewItem key={item.id} item={item} call={call} onChanged={changed} />)
          )}
          {next ? (
            <HStack justify="center">
              <Button variant="secondary" label="Load more" isDisabled={loadingMore} onClick={more} />
            </HStack>
          ) : null}
        </VStack>
      </div>
    </AppShell>
  );
}
