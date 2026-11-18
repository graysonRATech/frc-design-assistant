import { AstryxKit, ShadcnKit, WebAwesomeKit } from "../bakeoff/Kits.jsx";
import { AstryxChat } from "../bakeoff/astryx/AstryxChat.jsx";
import { ShadcnChat } from "../bakeoff/shadcn/ShadcnChat.jsx";
import { WaChat } from "../bakeoff/webawesome/WaChat.jsx";

const themeArg = {
  args: { theme: "forge" },
  argTypes: { theme: { control: "inline-radio", options: ["auto", "forge", "collegiate", "blueprint"] } },
};

export default { title: "Bake-off" };

export const Astryx = { ...themeArg, render: ({ theme }) => <AstryxChat key={theme} initialTheme={theme} /> };
export const WebAwesome = { ...themeArg, name: "Web Awesome", render: ({ theme }) => <WaChat key={theme} initialTheme={theme} /> };
export const Shadcn = { ...themeArg, name: "shadcn-ui", render: ({ theme }) => <ShadcnChat key={theme} initialTheme={theme} /> };

export const ComponentKit = {
  name: "Component kit",
  args: { system: "Astryx", theme: "collegiate" },
  argTypes: {
    system: { control: "inline-radio", options: ["Astryx", "Web Awesome", "shadcn-ui"] },
    theme: { control: "inline-radio", options: ["forge", "collegiate", "blueprint"] },
  },
  render: ({ system, theme }) =>
    system === "Astryx" ? <AstryxKit theme={theme} /> : system === "Web Awesome" ? <WebAwesomeKit theme={theme} /> : <ShadcnKit theme={theme} />,
};
