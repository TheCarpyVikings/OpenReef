import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "coral-spawning",
  h1: "The Coral Spawning Scheduler",
  lede: "On the Great Barrier Reef, corals broadcast-spawn 12–15 nights after the full moon — on cue, every year. OpenReef compiles that biology into a seasonal light, moon and temperature programme — and either hands it to your Apex as finished tables, or runs it itself on smart plugs.",
  buddyLine: "Your controller can count seconds. Mine counts moons.",
  buddyPose: "thinking",
  img: "/demos/spawning/1-live-program.png",
  imgAlt: "The live programme: today's reef sunrise and sunset, day length, moon phase and the seasonal temperature target",
  demoLabel: "Open Feeding → Spawning in the demo",
  gallery: [
    { src: "/demos/spawning/2-execution.png", alt: "Execute on: paste the programme into Apex Local, or switch to OpenReef execution on any smart plug" },
    { src: "/demos/spawning/3-the-reef.png", alt: "The reef: preset, seasonal offset onto your calendar, solar-noon hour and temperature unit" },
  ],
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
      heading: "Execute on Apex — or on smart plugs",
      paragraphs: [
        "Execution is a choice, not a limit. In Apex mode OpenReef compiles the Season Table values, the lighting profiles and the temperature, daylight and lunar code for Apex Local, following the documented workflow, for you to paste and verify. In OpenReef mode it runs the same programme itself: a light entity on from the reef's sunrise to its sunset, an optional moon entity following the real lunar cycle at night (below a chosen illumination the night stays genuinely dark), an override policy that either holds a hand-switched change until the next transition or reasserts the plan, and a master arm that keeps everything untouchable until you say so.",
        "Seasonal temperature is the guarded part. OpenReef will drive a heater and a cooler along the reef's seasonal curve only once you have acknowledged an independent inline thermostat as the guard and bound a sensor plus at least one actuator — with hard clamps on the range, a stale-sensor cut-off, and a minimum off-time for the chiller. The software follows the season; a dumb guard you own stops the software.",
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
    "Like everything in OpenReef: it never switches equipment you haven't mapped and armed yourself — and seasonal temperature control stays off until you've confirmed an independent inline thermostat is set as the guard.",
    "One camera capture per predicted spawn-window night is opt-in, so the night you hope for is photographed even if you're asleep — but nobody has automated noticing a spawn yet; that's still you and a torch.",
  ],
  faq: [
    {
      q: "Will it work with my Apex?",
      a: "Yes — that's the design: OpenReef compiles the reef's year into the Season Table, profiles and code your Apex runs with its own failsafes. And if you'd rather not touch Apex programming at all, switch execution to OpenReef and run the same programme on smart plugs.",
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
