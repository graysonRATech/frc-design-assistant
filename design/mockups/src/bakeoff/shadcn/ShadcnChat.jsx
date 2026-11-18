// The TORCH chat screen built from shadcn/ui components (Radix + Tailwind, copied into the repo).
import "./shadcn.css";
import "../proto.css";

import { useState } from "react";
import { Copy, ExternalLink, Plus, RotateCcw, Search, Square, ThumbsDown, ThumbsUp } from "lucide-react";
import { Avatar, AvatarFallback } from "@/bakeoff/shadcn/components/ui/avatar";
import { Alert, AlertDescription } from "@/bakeoff/shadcn/components/ui/alert";
import { Badge } from "@/bakeoff/shadcn/components/ui/badge";
import { Button } from "@/bakeoff/shadcn/components/ui/button";
import { Card } from "@/bakeoff/shadcn/components/ui/card";
import { Input } from "@/bakeoff/shadcn/components/ui/input";
import { ScrollArea } from "@/bakeoff/shadcn/components/ui/scroll-area";
import { Separator } from "@/bakeoff/shadcn/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/bakeoff/shadcn/components/ui/tabs";
import { Textarea } from "@/bakeoff/shadcn/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/bakeoff/shadcn/components/ui/tooltip";

import { Logo, THEMES, chatGroups, palette, prototypeNotice, question1, question2, resolveTheme, sources } from "../shared.jsx";

const Cite = ({ n }) => (
  <Badge className="mx-0.5 h-[18px] min-w-[18px] rounded-full px-1 align-[2px] font-mono text-[11px]">{n}</Badge>
);

function IconAction({ label, children }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label} className="text-muted-foreground">{children}</Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function BotMark({ id }) {
  const p = palette[id];
  return (
    <span className="grid size-9 place-items-center rounded-md bg-sidebar">
      <Logo size={24} gear={id === "collegiate" ? "#fff" : p.text} />
    </span>
  );
}

export function ShadcnChat({ initialTheme = "auto" }) {
  const [choice, setChoice] = useState(initialTheme);
  const id = resolveTheme(choice);
  const p = palette[id];

  return (
    <TooltipProvider>
      <div className={`shadcn-root torch-${id} ${p.mode === "dark" ? "dark" : ""} grid h-screen grid-cols-[280px_1fr] grid-rows-[auto_minmax(0,1fr)]`}>
        <Alert className={`proto ${id} col-span-2 rounded-none border-x-0 border-t-0 py-2 pl-6`} style={{ background: id === "collegiate" ? "#fecc07" : "var(--secondary)", color: id === "collegiate" ? "#0d4641" : "var(--secondary-foreground)" }}>
          <AlertDescription className="text-inherit"><span><span className="proto-label">{prototypeNotice.label[id]}</span>{prototypeNotice.text}</span></AlertDescription>
        </Alert>
        <aside className="flex min-h-0 flex-col gap-3 border-r bg-sidebar p-3 text-sidebar-foreground">
          <div className="flex items-center gap-2.5">
            <Logo size={30} gear={id === "blueprint" ? "#0d4641" : id === "collegiate" ? "#fff" : p.text} />
            <div className="leading-tight">
              <div className="font-[family-name:var(--font-display)] text-[19px] font-bold tracking-wider uppercase">
                TORCH <span className={id === "blueprint" ? "text-[#e2700b]" : "text-[#fecc07]"}>5804</span>
              </div>
              <div className="text-xs opacity-75">Design Assistant</div>
            </div>
          </div>
          <Button className="w-full font-[family-name:var(--font-display)] text-base font-bold tracking-wider uppercase" style={{ background: "var(--flame)", color: id === "collegiate" ? "#0d4641" : undefined }}>
            <Plus /> New chat
          </Button>
          <div className="relative">
            <Search className="absolute top-2.5 left-2.5 size-4 opacity-60" />
            <Input placeholder="Search chats" className="h-9 border-transparent bg-white/5 pl-8 text-inherit placeholder:text-current/60" />
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <nav className="flex flex-col gap-3.5">
              {chatGroups.map(([title, items]) => (
                <section key={title}>
                  <h3 className="mb-1 ml-2 text-[11px] font-semibold tracking-widest uppercase opacity-60">{title}</h3>
                  {items.map((c) => (
                    <a
                      key={c.title}
                      href="#"
                      className={`block truncate rounded-md px-2 py-1.5 text-sm text-inherit no-underline hover:bg-current/10 ${c.current ? "bg-current/10 shadow-[inset_3px_0_0_#fd9727]" : ""}`}
                    >
                      {c.title}
                    </a>
                  ))}
                </section>
              ))}
            </nav>
          </ScrollArea>
          <Separator className="bg-current/15" />
          <div className="flex flex-col gap-1.5 text-xs opacity-75">
            <div className="flex justify-between"><span>Today</span><span>12 of ~100 questions</span></div>
            <div className="h-1.5 overflow-hidden rounded-full bg-current/15"><div className="h-full w-[12%] rounded-full" style={{ background: "var(--flame)" }} /></div>
            <span>Chats are deleted 90 days after your last message.</span>
          </div>
        </aside>

        <main className="flex min-w-0 flex-col">
          <header className="flex items-center gap-4 border-b bg-card px-5 py-2.5">
            <h2 className="flex-1 truncate font-[family-name:var(--font-display)] text-lg font-bold tracking-wide uppercase">
              Gear center distance for 20T and 60T
            </h2>
            <Tabs value={choice} onValueChange={setChoice}>
              <TabsList>
                {THEMES.map((t) => (
                  <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <Avatar><AvatarFallback className="bg-primary text-primary-foreground font-bold">AS</AvatarFallback></Avatar>
          </header>

          <div className="flex-1 overflow-auto px-6 py-6">
            <div className="mx-auto flex max-w-[760px] flex-col gap-6">
              <div className="flex justify-end"><div className="max-w-[80%] rounded-xl border bg-user px-4 py-3 text-user-foreground">{question1}</div></div>
              <div className="grid grid-cols-[36px_minmax(0,1fr)] gap-3.5">
                <BotMark id={id} />
                <div className="flex flex-col gap-3 leading-relaxed">
                  <p>Add the two pitch diameters and divide by two. For spur gears that's <Cite n={1} />:</p>
                  <Card className="gap-1 border-l-4 border-l-[var(--ring)] px-4 py-3 shadow-none">
                    <span className="text-xs font-semibold tracking-widest text-muted-foreground uppercase">Center distance</span>
                    <code className="font-mono text-lg">C = (N₁ + N₂) / (2 × DP)</code>
                  </Card>
                  <p>Most FRC gears are <strong>20 DP</strong>, so for your pair:</p>
                  <div className="overflow-hidden rounded-lg border">
                    <table className="w-full border-collapse text-sm">
                      <thead className="bg-muted text-xs tracking-wider text-muted-foreground uppercase">
                        <tr><th className="px-3.5 py-2 text-left">Gear</th><th className="px-3.5 py-2 text-left">Teeth</th><th className="px-3.5 py-2 text-right">Pitch diameter</th></tr>
                      </thead>
                      <tbody className="[&_td]:border-t [&_td]:px-3.5 [&_td]:py-2">
                        <tr><td>Pinion</td><td>20</td><td className="text-right font-mono">1.000 in</td></tr>
                        <tr><td>Driven</td><td>60</td><td className="text-right font-mono">3.000 in</td></tr>
                        <tr className="font-bold text-accent-foreground"><td colSpan={2}>Center distance</td><td className="text-right font-mono">2.000 in</td></tr>
                      </tbody>
                    </table>
                  </div>
                  <p>Put the bearing holes exactly that far apart in your plates <Cite n={2} />, and check the mesh on a test print before you cut aluminum.</p>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-2">
                    {sources.slice(0, 2).map((s) => (
                      <Card key={s.n} className="flex-row items-center gap-2.5 px-3 py-2.5 shadow-none">
                        <Badge variant="secondary" className="font-mono">{s.n}</Badge>
                        <div className="flex min-w-0 flex-1 flex-col">
                          <span className="text-sm font-semibold">{s.title}</span>
                          <span className="truncate text-xs text-muted-foreground">{s.host} · {s.section}</span>
                        </div>
                        <ExternalLink className="size-3.5 text-muted-foreground" />
                      </Card>
                    ))}
                  </div>
                  <div className="flex gap-0.5">
                    <IconAction label="Copy"><Copy /></IconAction>
                    <IconAction label="Retry"><RotateCcw /></IconAction>
                    <IconAction label="Helpful"><ThumbsUp /></IconAction>
                    <IconAction label="Not helpful"><ThumbsDown /></IconAction>
                  </div>
                </div>
              </div>
              <div className="flex justify-end"><div className="max-w-[80%] rounded-xl border bg-user px-4 py-3 text-user-foreground">{question2}</div></div>
              <div className="grid grid-cols-[36px_minmax(0,1fr)] gap-3.5">
                <BotMark id={id} />
                <div className="leading-relaxed">
                  <p>Start with a <strong>master sketch</strong> <Cite n={3} /> so both plates share one source of truth:</p>
                  <ol className="mt-2 list-decimal pl-5">
                    <li>Draw two construction circles at the pitch diameters, tangent to each other.</li>
                    <li>Dimension the center distance to <code className="rounded bg-muted px-1 font-mono text-sm">2.000 in</code> and lock it<span className="sc-cursor" /></li>
                  </ol>
                </div>
              </div>
            </div>
          </div>

          <div className="px-6 pt-2 pb-5">
            <div className="mx-auto max-w-[760px] rounded-xl border bg-card p-2.5 shadow-sm">
              <Textarea rows={2} placeholder="Ask a design, CAD or fabrication question" className="min-h-0 resize-none border-0 shadow-none focus-visible:ring-0" />
              <div className="mt-1 flex items-center gap-3 px-1">
                <span className="flex-1 text-xs text-muted-foreground">Answers come from FRCDesign.org. Check the sources before you cut metal.</span>
                <Button variant="outline" size="sm"><Square className="fill-current" /> Stop</Button>
              </div>
            </div>
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
