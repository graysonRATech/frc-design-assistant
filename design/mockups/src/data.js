// Sample content for the mockups. Realistic, but static: nothing here talks to the app.

export const user = { name: "Alex Student", initials: "AS" };

export const chats = {
  today: [
    { title: "Gear center distance for 20T and 60T", current: true },
    { title: "Shooter wheel compression" },
  ],
  week: [
    { title: "Master sketch setup in Onshape" },
    { title: "Which bolts for most of the robot?" },
    { title: "Polycarbonate vs. aluminum guards" },
  ],
  older: [{ title: "Chain tensioning on a swerve-less drive" }, { title: "Bearing blocks for 1/2\" hex" }],
};

export const sources = [
  { n: 1, title: "Gear Basics", section: "Learning Course · Stage 1", host: "frcdesign.org" },
  { n: 2, title: "Center-to-Center Distances", section: "Learning Course · Stage 1", host: "frcdesign.org" },
  { n: 3, title: "Master Sketches", section: "Onshape · Best Practices", host: "frcdesign.org" },
];

export const suggestions = [
  { tag: "Mechanisms", text: "How much compression should a shooter have?" },
  { tag: "Onshape", text: "How should I set up a master sketch?" },
  { tag: "Fabrication", text: "What bolts should we use for most of the robot?" },
  { tag: "Gearing", text: "How do I calculate the center distance for two gears?" },
];

export const usage = { used: 12, cap: 100 };
