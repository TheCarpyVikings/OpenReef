import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "reef-pulse",
  h1: "Reef Pulse",
  lede: "Controllers have dashboards — pages you visit at a desk when something's wrong. Reef Pulse is the opposite: a full-screen wall mode for the tank room, built into the controller itself. Health ring, live tiles, insights, your reef breathing on an old iPad. Press ✨ Present and the panel becomes the wall.",
  buddyLine: "Your controller has a login page. Your reef deserves a showing-off mode.",
  buddyPose: "celebrate",
  img: "/demos/pulse.png",
  imgAlt: "OpenReef Reef Pulse present mode — full-screen wall display",
  demoLabel: "Press Present in the demo",
  sections: [
    {
      heading: "Built for the room, not the desk",
      paragraphs: [
        "One tap takes the whole panel full-screen: the reef health ring with its grade, live tiles for every probe with sparklines and range markers, a health breakdown, equipment status dots, today's tasks, and a quietly scrolling activity ticker. Everything sized to be read from the sofa, not the office chair.",
        "It's genuinely kiosk-grade: it keeps the screen awake, can auto-start into present mode for a dedicated wall tablet, dims itself at night on a schedule — or, if you give it a lux sensor, when the room actually gets dark, like the tank's own moonlight.",
      ],
    },
    {
      heading: "Pick your backdrop",
      paragraphs: [
        "The wall can be whatever tells your reef's story best: the live camera feed behind the stats, the growth timelapse playing through, the living tank diagram animating your actual system — or a clean stat wall when you want the numbers to be the show. Tap any tile and it opens into its full trend, right there on the wall.",
      ],
    },
    {
      heading: "Insights, sharing, and a summonable Viking",
      paragraphs: [
        "A rotating insight card reads your tank's recent story — consumption trends, drift, what changed this week — so the wall isn't just current values, it's context. The share button captures the wall you're actually looking at, ready for the group chat or the forum thread.",
        "And if you run the Lagertha avatar, she's summon-only on the wall: present mode never burns avatar minutes in the background — she appears when asked and leaves when dismissed.",
      ],
      snippet: `the wall, in one tap →
  health ring · A · 100
  five live tiles, sparklines breathing
  backdrop: your diagram, animating
  insight: "alk consumption up 8 % this fortnight"
  02:00  night dim — the room goes dark, so does the wall`,
    },
  ],
  limits: [
    "The camera backdrop needs a mapped, online camera; without one, Pulse falls back to the stat wall or diagram gracefully.",
    "Keep-awake uses the browser's wake-lock — a cheap wall tablet in kiosk mode is the reliable setup, and that's the intended home.",
    "Night dim by ambient light needs a lux entity in Home Assistant; without one you still get the schedule.",
    "The Lagertha avatar is optional, needs its own API keys, and is summon-only in Pulse by design — live avatar minutes are billed, and a wall display should cost nothing to leave running.",
  ],
  faq: [
    {
      q: "What hardware does the wall need?",
      a: "Anything with a browser. The reference setup is an old iPad in kiosk mode running the Home Assistant app pointed at the panel — Pulse keeps it awake, auto-starts if you want, and dims at night.",
    },
    {
      q: "Doesn't Apex Fusion already do this?",
      a: "Fusion has dashboards you log into and arrange — built for checking, not displaying. Pulse is a present mode built into the controller: full-screen, kiosk-aware, glanceable at three metres. As far as we can tell, no shipping reef controller has one.",
    },
    {
      q: "Can it show my camera and my stats at once?",
      a: "Yes — that's the camera backdrop: the live feed fills the wall and the tiles float over it. Swap to the timelapse backdrop and the wall plays your reef's growth instead.",
    },
    {
      q: "Is this the same thing as the tank diagram?",
      a: "They're partners. The diagram is a tab you interact with; Pulse is the full-screen mode the room sees — and the diagram is one of its backdrops, so the wall can be your living schematic.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
