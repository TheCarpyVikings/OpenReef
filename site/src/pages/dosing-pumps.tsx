import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "dosing-pumps",
  h1: "Dosing Pumps",
  lede: "Multi-channel dosing where the firmware runs the schedule and the guard chain, and Home Assistant owns everything the firmware can't: the missed-dose ledger, the reservoir, the calibration history, tube wear, and the honest word 'behind'. Built from the research on why people stop trusting their doser.",
  buddyLine: "The firmware runs the schedule. I keep the receipts.",
  buddyPose: "idle",
  img: "/demos/dosing/1-channels.png",
  imgAlt: "Two channels on schedule: today's progress, the split, reservoir runway, integrity, and bounded manual actions",
  demoLabel: "Open Water → Dosing in the demo",
  gallery: [
    { src: "/demos/dosing/2-tomorrow-s-plan.png", alt: "Tomorrow's plan: the schedule computed dose-by-dose, exactly as the firmware will deliver it" },
    { src: "/demos/dosing/3-advisory.png", alt: "The advisor absorbed into the tab: per-parameter trend, projection and the suggested daily total — advisory only" },
  ],
  sections: [
    {
      heading: "Who does what — and why it fails safe",
      paragraphs: [
        "On the OpenReef firmware nodes, the pump executes the schedule and the full per-dose guard chain itself — enabled, not suspended by HA, reservoir not empty, calibrated, inside the window, pH in bounds, under the daily cap — so dosing keeps running and keeps refusing correctly when Home Assistant is offline. OpenReef compiles your schedule into the firmware's numbers, writes them, reads them back and verifies (write-then-verify: a schedule that didn't land is reported, not assumed), and mirrors the guard chain for display.",
        "No firmware? An HA-timed driver runs cheap pumps on smart plugs from Home Assistant's own schedule, with the same guard chain as enforcement and the same honesty about crashes — an interrupted dose counts its real elapsed time, never the planned one.",
      ],
    },
    {
      heading: "Daily total first",
      paragraphs: [
        "You say 45 ml a day, in a window, and the engine splits it: continuous for kalk, a set number of doses for two-part, with a night-weighting slider that inherits your lighting window if you like. Two-part channels are spaced apart so alk and calcium never land in the same litre. A new-tank ramp brings a channel up over days; a dry run previews exactly what tomorrow will do before a drop moves.",
      ],
      snippet: `All-For-Reef · 45 ml/day · 12 doses of 3.75 ml · every 120 min
  today 0.0 / 45 ml · next in 34 min
  reservoir 1.35 L · ~30 days left
kalk · continuous · pH guard: pause above 8.45, resume below 8.30
  missed volume → skipped (never a catch-up bolus)`,
    },
    {
      heading: "The trust problem, solved on purpose",
      paragraphs: [
        "The research was blunt: missed-dose false alarms are the number-one reason people stop believing their doser, and 'days until empty' is the number-two demand. So the missed-dose watcher is trust-aware — it owns the word 'missed' via a plan baseline and sensor availability, and when it can't be sure it says 'behind' or 'unknown', never 'missed'. The reservoir is software-first with an optional float, forecasts days-to-empty, and is never a disabling limit. Kalk missed volume defaults to skip, because an automatic catch-up bolus is how a pH spike happens. Calibration — a hundred revolutions for a stepper, a thirty-second burst for a brushed head — is stored with history and a recalibration-due clock, and every manual action is bounded.",
      ],
    },
  ],
  limits: [
    "Three drivers today: OpenReef's ESPHome stepper and brushed nodes, and the HA-timed smart-plug driver. Other dosers can't be driven; their reservoirs and doses can still be logged.",
    "Kalk is refused on the HA-timed driver — a kalk reactor needs the firmware's pH failsafe under it, not a plug timer.",
    "pH pause-above/resume-below is a failsafe, not a controller: 'dose until pH equals X' is deliberately unbuildable here.",
    "Chemistry stays advisory: the dosing advisor proposes a daily-total change from your test trend; you apply it. Nothing changes a dose from a reading on its own.",
  ],
  faq: [
    {
      q: "Can it drive my existing doser?",
      a: "If the doser is a dumb pump you can put on a smart plug, yes — the HA-timed driver runs it with the same schedule maths and guard chain. Proprietary dosers with their own apps can't be driven, only logged.",
    },
    {
      q: "What happens when HA goes down mid-schedule?",
      a: "On a firmware node, nothing you'd notice: the pump keeps its schedule and its guards. On the HA-timed driver, dosing stops with HA and the crash recovery counts the real elapsed time of any interrupted dose — then reports honestly what was and wasn't dosed.",
    },
    {
      q: "Why does it refuse to catch up a missed kalk dose?",
      a: "Because a stacked kalk bolus is the classic pH-spike accident. Missed kalk defaults to skip; for two-part you're asked before any respread — missed is alert-and-ask, never act.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
