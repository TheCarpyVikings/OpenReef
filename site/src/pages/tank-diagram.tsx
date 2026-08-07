import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "tank-diagram",
  h1: "The Living Tank Diagram",
  lede: "Every controller shows you a list of numbers. OpenReef draws your actual system — sump, plumbing, pumps, rockwork, corals — and then runs it live. Flow follows your pumps. Alerts light up where the problem physically is. Your reef, as a diagram that's alive.",
  buddyLine: "That's not clip art. That's your return pump — and it knows it's switched on.",
  buddyPose: "idle",
  img: "/demos/diagram.png",
  imgAlt: "OpenReef living tank diagram tab in Home Assistant",
  demoLabel: "See it live in the demo",
  sections: [
    {
      heading: "Drawn from your config, not a template",
      paragraphs: [
        "The diagram isn't a stock illustration with your name on it. It's generated from your equipment mapping: your return pump draws the return line, your wavemakers sit on whichever walls you put them, your ATO gets a nozzle with mist you can actually see, your skimmer bubbles when it's running. Sump systems get a full sump; all-in-ones get an all-in-one that matches the photo of the real thing.",
        "Because it's drawn from the mapping, it stays honest: switch the skimmer off and its bubbles stop. Start a water change and you watch it happen — drain line pulling, fill line pushing, the reservoir levels moving with the real litres. When the return pump goes down, the taps it feeds answer for it.",
      ],
    },
    {
      heading: "The wall points at the problem",
      paragraphs: [
        "Live probe readings float in the water where the probes are. And when a sensor goes into warning or critical, the alert doesn't land in a list — the diagram lights up at the physical spot. A heater problem glows at the heater. A high sump level glows in the sump. At three metres, half asleep, you know where to look before you know what's wrong.",
      ],
    },
    {
      heading: "The Reef Layer: your corals on the rock",
      paragraphs: [
        "Register your livestock and the diagram grows your reef. Thirty-six species of coral art, seven aquascape presets, eight fluorescence colourways — and placement follows real reefkeeping rules: SPS go up on the crest, LPS mid-rock, softies low, gorgonians at the back, and two same-coloured colonies won't sit next to each other. You can arrange everything by hand, but the defaults are taste-by-rule.",
        "Each coral is a record, not a sticker: name, species, date added, notes, photos. The reef lives on tank time — lights down in the display means lights down in the diagram. And switching aquascapes keeps every placement, so redecorating is reversible.",
      ],
      list: [
        "36 coral species across SPS, LPS, softies, gorgonians, clams and anemones",
        "7 aquascape presets — island, twin peaks, slope, arch, pillars, peninsula, valley",
        "Zone-honouring auto-placement with a colour-spacing rule (arrange by hand any time)",
        "In-display circulation: a particle gyre and fish, spun by whichever wavemakers are actually running",
      ],
    },
  ],
  limits: [
    "It's a deliberate schematic, not a 3D render — glyph art stays readable at a glance and runs happily on an old iPad on the wall.",
    "The rockwork holds up to 16 registered corals; a 200-frag collection becomes a curated highlights reel.",
    "Coral photos live on the coral's record card — the rockwork keeps its drawn art.",
    "Motion honours prefers-reduced-motion by not starting at all, and stops the moment you leave the tab.",
  ],
  faq: [
    {
      q: "Is this a camera view of my tank?",
      a: "No — it's a live schematic drawn from your equipment mapping and livestock register. The camera tabs do the photography; the diagram does the understanding. They complement each other: one shows what the tank looks like, the other shows what the system is doing.",
    },
    {
      q: "Does it work without a sump?",
      a: "Yes. The diagram has a dedicated all-in-one mode drawn to match a real AIO layout — rear chambers included — as well as the full sump system view.",
    },
    {
      q: "Can I control things from it?",
      a: "Yes, if you allow it: tapping equipment opens its detail with full controls — the same arm-it-yourself safety model as everywhere else in OpenReef. You can also switch the diagram to look-but-don't-touch for the wall tablet.",
    },
    {
      q: "Does anything else have this?",
      a: "Dashboards with gauges, yes, everywhere. A live schematic of your specific plumbing with your specific corals on your chosen rockwork, that points at problems spatially — we haven't found one on any controller at any price.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
