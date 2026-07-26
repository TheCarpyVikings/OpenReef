import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "coral-spawning",
  h1: "The Coral Spawning Scheduler",
  lede: "On the Great Barrier Reef, corals broadcast-spawn 12–15 nights after the full moon — on cue, every year. OpenReef compiles that biology into a light and pump programme your own controller runs.",
  buddyLine: "Your controller can count seconds. Mine counts moons.",
  buddyPose: "thinking",
  img: "/demos/spawning.png",
  imgAlt: "OpenReef spawning tab in Home Assistant",
  sections: [
    {
      heading: "Biology first, buttons second",
      paragraphs: [
        "Captive coral spawning isn't a mystery any more — the method is published and repeatable, and the hard part is discipline: the right dusk cue at the right minute, the right moonlight level, night after night, in the right lunar window. Humans are bad at that for months on end. Controllers are great at it — if someone does the maths.",
        "OpenReef follows the published broadcast-spawning approach: it tracks the lunar calendar for your chosen reef and identifies the spawning window — for the Great Barrier Reef, nights 12–15 after the full moon.",
      ],
    },
    {
      heading: "From reef location to running programme",
      paragraphs: [
        "You pick the reef. The engine works out the next windows and generates the evening programme for each night in them:",
      ],
      list: [
        "Dusk ramp — lights step down to a natural sunset at the biologically right time",
        "Moonlight — dim lunar-level light held through the window",
        "Pump slick mode — flow drops so gamete bundles can rise and collect",
        "Resume — the tank returns to its normal programme automatically",
      ],
    },
    {
      heading: "What a compiled window looks like",
      paragraphs: [
        "This is the point: not a PDF of advice, but a schedule your hardware executes.",
      ],
      snippet: `spawning window compiled →
  19:42  dusk ramp to 4 %
  20:10  moonlight 0.8 lx (waning gibbous)
  20:30  return pumps → 20 % (slick mode)
  02:00  resume normal programme
export → your controller's schedule`,
    },
  ],
  limits: [
    "The scheduler removes timing errors — it does not condition broodstock. Successful spawning still needs mature colonies, stable chemistry and months of preparation.",
    "Moonlight levels depend on how low your fixture can actually dim; some can't do lunar levels well.",
    "Curated reef presets shipped first (Great Barrier Reef and Singapore, validated against published spawning profiles); more locations to come.",
    "Like everything in OpenReef: it never switches equipment you haven't mapped and armed yourself.",
  ],
  faq: [
    {
      q: "Will it work with my Apex?",
      a: "Yes — that's the design. OpenReef compiles the window into a programme your existing controller can run. Keep the box; give it a brain.",
    },
    {
      q: "Do I need special lights?",
      a: "No specific brand. Anything with a dimmable channel your controller or Home Assistant can drive works — the value is the schedule, not the fixture.",
    },
    {
      q: "Is this actually realistic in a home tank?",
      a: "Captive broadcast spawning has been done repeatedly using exactly this kind of lunar-cue discipline. It's not guaranteed — but the timing part is no longer the reason you'd fail.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
