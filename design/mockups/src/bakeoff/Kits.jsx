// Component kits: the same set of controls from each system, in a TORCH theme, so the variety of
// buttons, inputs, toggles, badges, banners and type can be compared directly.
import "./kit.css";

import { useState } from "react";
import { Copy, Plus, Send, Trash2 } from "lucide-react";

// Astryx
import { AstryxScope } from "./astryx/AstryxChat.jsx";
import { Button as AxButton } from "@astryxdesign/core/Button";
import { IconButton as AxIconButton } from "@astryxdesign/core/IconButton";
import { TextInput as AxTextInput } from "@astryxdesign/core/TextInput";
import { TextArea as AxTextArea } from "@astryxdesign/core/TextArea";
import { Switch as AxSwitch } from "@astryxdesign/core/Switch";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Badge as AxBadge } from "@astryxdesign/core/Badge";
import { Token as AxToken } from "@astryxdesign/core/Token";
import { Avatar as AxAvatar } from "@astryxdesign/core/Avatar";
import { Banner as AxBanner } from "@astryxdesign/core/Banner";
import { ProgressBar as AxProgress } from "@astryxdesign/core/ProgressBar";
import { Spinner as AxSpinner } from "@astryxdesign/core/Spinner";
import { Kbd as AxKbd } from "@astryxdesign/core/Kbd";
import { Heading as AxHeading } from "@astryxdesign/core/Heading";
import { Text as AxText } from "@astryxdesign/core/Text";

// Web Awesome
import "@awesome.me/webawesome/dist/styles/themes/default.css";
import "@awesome.me/webawesome/dist/styles/utilities/text.css";
import "./webawesome/webawesome.css";
import WaAvatar from "@awesome.me/webawesome/dist/react/avatar/index.js";
import WaBadge from "@awesome.me/webawesome/dist/react/badge/index.js";
import WaButton from "@awesome.me/webawesome/dist/react/button/index.js";
import WaCallout from "@awesome.me/webawesome/dist/react/callout/index.js";
import WaInput from "@awesome.me/webawesome/dist/react/input/index.js";
import WaProgressBar from "@awesome.me/webawesome/dist/react/progress-bar/index.js";
import WaRadio from "@awesome.me/webawesome/dist/react/radio/index.js";
import WaRadioGroup from "@awesome.me/webawesome/dist/react/radio-group/index.js";
import WaSpinner from "@awesome.me/webawesome/dist/react/spinner/index.js";
import WaSwitch from "@awesome.me/webawesome/dist/react/switch/index.js";
import WaTag from "@awesome.me/webawesome/dist/react/tag/index.js";
import WaTextarea from "@awesome.me/webawesome/dist/react/textarea/index.js";

// shadcn/ui
import "./shadcn/shadcn.css";
import { Alert, AlertDescription, AlertTitle } from "@/bakeoff/shadcn/components/ui/alert";
import { Avatar, AvatarFallback } from "@/bakeoff/shadcn/components/ui/avatar";
import { Badge } from "@/bakeoff/shadcn/components/ui/badge";
import { Button } from "@/bakeoff/shadcn/components/ui/button";
import { Input } from "@/bakeoff/shadcn/components/ui/input";
import { Progress } from "@/bakeoff/shadcn/components/ui/progress";
import { Switch } from "@/bakeoff/shadcn/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/bakeoff/shadcn/components/ui/tabs";
import { Textarea } from "@/bakeoff/shadcn/components/ui/textarea";

import { palette } from "./shared.jsx";

const Header = ({ name, note }) => (
  <header>
    <h3 className="kit-title">{name}</h3>
    <p className="kit-sub">{note}</p>
  </header>
);

export function AstryxKit({ theme }) {
  const [seg, setSeg] = useState("collegiate");
  const [on, setOn] = useState(true);
  return (
    <AstryxScope id={theme}>
      <Header name="Astryx" note="173 components · React + StyleX · tokens via defineTheme" />
      <section><h4>Buttons</h4>
        <div className="row">
          <AxButton variant="primary" label="Ask" icon={<Send size={16} />} />
          <AxButton variant="secondary" label="New chat" icon={<Plus size={16} />} />
          <AxButton variant="ghost" label="Retry" />
          <AxButton variant="destructive" label="Delete chat" icon={<Trash2 size={16} />} />
          <AxButton variant="primary" label="Saving" isLoading />
          <AxButton variant="secondary" label="Disabled" isDisabled />
          <AxIconButton variant="ghost" label="Copy" tooltip="Copy" icon={<Copy size={16} />} />
        </div>
        <div className="row">
          <AxButton variant="primary" size="sm" label="Small" />
          <AxButton variant="primary" size="md" label="Medium" />
          <AxButton variant="primary" size="lg" label="Large" />
        </div>
      </section>
      <section><h4>Inputs</h4>
        <div className="col">
          <AxTextInput label="Team number" value="5804" onChange={() => {}} description="Shown on your profile" />
          <AxTextInput label="Search chats" type="search" value="" onChange={() => {}} placeholder="gear ratio…" />
          <AxTextArea label="Question" value="" onChange={() => {}} placeholder="Ask a design, CAD or fabrication question" />
        </div>
      </section>
      <section><h4>Toggles</h4>
        <div className="row">
          <AxSwitch label="Stream answers" value={on} onChange={setOn} />
          <SegmentedControl label="Theme" value={seg} onChange={setSeg}>
            <SegmentedControlItem value="auto" label="Auto" />
            <SegmentedControlItem value="forge" label="Forge" />
            <SegmentedControlItem value="collegiate" label="Collegiate" />
            <SegmentedControlItem value="blueprint" label="Blueprint" />
          </SegmentedControl>
        </div>
      </section>
      <section><h4>Badges, tokens, avatars</h4>
        <div className="row">
          <AxBadge variant="success" label="Indexed" /><AxBadge variant="warning" label="Over limit" /><AxBadge variant="info" label="Mentor" />
          <AxBadge variant="orange" label="Mechanisms" /><AxBadge variant="teal" label="Onshape" />
          <AxToken label="frcdesign.org" /><AxToken label="Stage 1" color="green" />
          <AxAvatar name="Alex Student" /><AxAvatar name="Sam Mentor" shape="rounded" />
          <AxKbd keys="mod+k" /> <AxSpinner />
        </div>
      </section>
      <section><h4>Feedback</h4>
        <div className="stack">
          <AxBanner status="info" title="Sonnet 5.5 isn't enabled yet" description="Answers use Claude Haiku 4.5 for now." />
          <AxBanner status="warning" title="You've used 90% of today's questions" />
          <AxProgress label="Today: 12 of ~100 questions" value={12} hasValueLabel />
        </div>
      </section>
      <section><h4>Type</h4>
        <div className="stack">
          <AxHeading level={1}>What are we building today?</AxHeading>
          <AxHeading level={3}>Center distance</AxHeading>
          <AxText type="large">Add the two pitch diameters and divide by two.</AxText>
          <AxText>Put the bearing holes exactly that far apart in your plates.</AxText>
          <AxText type="supporting">frcdesign.org · Learning Course · Stage 1</AxText>
          <AxText type="code">C = (N1 + N2) / (2 × DP)</AxText>
        </div>
      </section>
    </AstryxScope>
  );
}

export function WebAwesomeKit({ theme }) {
  const p = palette[theme];
  return (
    <div className={`kit wa-theme-default wa-${p.mode} torch-${theme}`} style={{ background: "var(--wa-color-surface-default)", color: "var(--wa-color-text-normal)" }}>
      <Header name="Web Awesome" note="~60 web components · framework-free · tokens via --wa-* CSS variables" />
      <section><h4>Buttons</h4>
        <div className="row">
          <WaButton variant="brand"><Send slot="start" size={16} />Ask</WaButton>
          <WaButton variant="neutral" appearance="outlined"><Plus slot="start" size={16} />New chat</WaButton>
          <WaButton variant="brand" appearance="plain">Retry</WaButton>
          <WaButton variant="danger" appearance="filled-outlined"><Trash2 slot="start" size={16} />Delete chat</WaButton>
          <WaButton variant="brand" loading>Saving</WaButton>
          <WaButton disabled>Disabled</WaButton>
          <WaButton variant="brand" pill>Pill</WaButton>
          <WaButton variant="neutral" appearance="filled" withCaret>Menu</WaButton>
        </div>
        <div className="row">
          <WaButton variant="brand" size="s">Small</WaButton>
          <WaButton variant="brand" size="m">Medium</WaButton>
          <WaButton variant="brand" size="l">Large</WaButton>
        </div>
      </section>
      <section><h4>Inputs</h4>
        <div className="col">
          <WaInput label="Team number" value="5804" hint="Shown on your profile" />
          <WaInput label="Search chats" placeholder="gear ratio…" appearance="filled" />
          <WaTextarea label="Question" rows={3} placeholder="Ask a design, CAD or fabrication question" />
        </div>
      </section>
      <section><h4>Toggles</h4>
        <div className="row">
          <WaSwitch checked>Stream answers</WaSwitch>
          <WaRadioGroup orientation="horizontal" value="collegiate" aria-label="Theme">
            <WaRadio value="auto" appearance="button">Auto</WaRadio>
            <WaRadio value="forge" appearance="button">Forge</WaRadio>
            <WaRadio value="collegiate" appearance="button">Collegiate</WaRadio>
            <WaRadio value="blueprint" appearance="button">Blueprint</WaRadio>
          </WaRadioGroup>
        </div>
      </section>
      <section><h4>Badges, tags, avatars</h4>
        <div className="row">
          <WaBadge variant="success">Indexed</WaBadge><WaBadge variant="warning">Over limit</WaBadge><WaBadge variant="brand" pill>Mentor</WaBadge>
          <WaTag variant="brand">Mechanisms</WaTag><WaTag>Onshape</WaTag><WaTag variant="success" pill>Stage 1</WaTag>
          <WaAvatar initials="AS" label="Alex Student" /><WaAvatar initials="SM" label="Sam Mentor" shape="rounded" />
          <WaSpinner />
        </div>
      </section>
      <section><h4>Feedback</h4>
        <div className="stack">
          <WaCallout variant="brand"><strong>Sonnet 5.5 isn't enabled yet.</strong> Answers use Claude Haiku 4.5 for now.</WaCallout>
          <WaCallout variant="warning" appearance="filled-outlined">You've used 90% of today's questions.</WaCallout>
          <WaProgressBar value={12} label="Questions used today">12%</WaProgressBar>
        </div>
      </section>
      <section><h4>Type (Web Awesome ships tokens and utility classes for type, not components)</h4>
        <div className="stack">
          <h1 className="wa-heading-2xl" style={{ margin: 0 }}>What are we building today?</h1>
          <h3 className="wa-heading-m" style={{ margin: 0 }}>Center distance</h3>
          <p className="wa-body-l" style={{ margin: 0 }}>Add the two pitch diameters and divide by two.</p>
          <p className="wa-body-m" style={{ margin: 0 }}>Put the bearing holes exactly that far apart in your plates.</p>
          <p className="wa-caption-m" style={{ margin: 0, color: "var(--wa-color-text-quiet)" }}>frcdesign.org · Learning Course · Stage 1</p>
          <code style={{ fontFamily: "var(--wa-font-family-code)" }}>C = (N1 + N2) / (2 × DP)</code>
        </div>
      </section>
    </div>
  );
}

export function ShadcnKit({ theme }) {
  const p = palette[theme];
  return (
    <div className={`kit shadcn-root torch-${theme} ${p.mode === "dark" ? "dark" : ""}`}>
      <Header name="shadcn/ui" note="Copy-in components on Radix + Tailwind · you own and edit the source · tokens via CSS variables" />
      <section><h4>Buttons</h4>
        <div className="row">
          <Button><Send /> Ask</Button>
          <Button variant="outline"><Plus /> New chat</Button>
          <Button variant="ghost">Retry</Button>
          <Button variant="destructive"><Trash2 /> Delete chat</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="link">Link</Button>
          <Button disabled>Disabled</Button>
          <Button variant="ghost" size="icon" aria-label="Copy"><Copy /></Button>
        </div>
        <div className="row">
          <Button size="sm">Small</Button>
          <Button>Default</Button>
          <Button size="lg">Large</Button>
        </div>
      </section>
      <section><h4>Inputs</h4>
        <div className="col">
          <label className="flex flex-col gap-1.5 text-sm font-medium">Team number<Input defaultValue="5804" /><span className="text-xs font-normal text-muted-foreground">Shown on your profile</span></label>
          <label className="flex flex-col gap-1.5 text-sm font-medium">Search chats<Input placeholder="gear ratio…" /></label>
          <label className="flex flex-col gap-1.5 text-sm font-medium">Question<Textarea placeholder="Ask a design, CAD or fabrication question" /></label>
        </div>
      </section>
      <section><h4>Toggles</h4>
        <div className="row">
          <label className="flex items-center gap-2 text-sm"><Switch defaultChecked /> Stream answers</label>
          <Tabs defaultValue="collegiate"><TabsList>
            <TabsTrigger value="auto">Auto</TabsTrigger><TabsTrigger value="forge">Forge</TabsTrigger>
            <TabsTrigger value="collegiate">Collegiate</TabsTrigger><TabsTrigger value="blueprint">Blueprint</TabsTrigger>
          </TabsList></Tabs>
        </div>
      </section>
      <section><h4>Badges, avatars</h4>
        <div className="row">
          <Badge>Indexed</Badge><Badge variant="secondary">Mentor</Badge><Badge variant="outline">Onshape</Badge><Badge variant="destructive">Over limit</Badge>
          <Avatar><AvatarFallback className="bg-primary font-bold text-primary-foreground">AS</AvatarFallback></Avatar>
          <Avatar className="rounded-md"><AvatarFallback className="rounded-md">SM</AvatarFallback></Avatar>
        </div>
      </section>
      <section><h4>Feedback</h4>
        <div className="stack">
          <Alert><AlertTitle>Sonnet 5.5 isn't enabled yet</AlertTitle><AlertDescription>Answers use Claude Haiku 4.5 for now.</AlertDescription></Alert>
          <Alert variant="destructive"><AlertTitle>You've used 90% of today's questions</AlertTitle></Alert>
          <Progress value={12} />
        </div>
      </section>
      <section><h4>Type (shadcn styles type with Tailwind classes, not components)</h4>
        <div className="stack">
          <h1 className="font-[family-name:var(--font-display)] text-5xl font-bold uppercase">What are we building today?</h1>
          <h3 className="text-xl font-semibold">Center distance</h3>
          <p className="text-lg">Add the two pitch diameters and divide by two.</p>
          <p>Put the bearing holes exactly that far apart in your plates.</p>
          <p className="text-sm text-muted-foreground">frcdesign.org · Learning Course · Stage 1</p>
          <code className="font-mono">C = (N1 + N2) / (2 × DP)</code>
        </div>
      </section>
    </div>
  );
}
