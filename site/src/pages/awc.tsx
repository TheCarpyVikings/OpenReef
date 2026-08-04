import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "automatic-water-change",
  h1: "Automatic Water Changes",
  lede: "Water changes are the one job every reefer agrees on — and the one most often skipped. OpenReef turns them into a volume-accounted, safety-latched routine: batch or continuous trickle, with maths you can audit.",
  buddyLine: "Bucket day used to be a personality trait. Now it's a schedule entry.",
  buddyPose: "chilled",
  img: "/demos/awc.png",
  imgAlt: "OpenReef automatic water change tab in Home Assistant",
  sections: [
    {
      heading: "Volume-first, like the expensive gear",
      paragraphs: [
        "There are two ways to build an AWC. Timers-and-hope: run the pumps for a while and trust that the level looks right. Or volume-first — the architecture Neptune's DOS and Kamoer's changers use — where every leg runs on calibrated ml/s, so the system can tell you \"4.98 litres out, 5.01 litres in\" and know when the reservoir will run dry. OpenReef is volume-first. Float and cutoff sensors are still there, but they arbitrate the estimate rather than drive the change — a stuck float can stop a cycle, it can never cause one.",
        "Calibration is two-stage, the way Kamoer does it: each pump gets a base ml/s from a measured run, then an exchange-correction factor so the drain and fill legs stay volume-matched even though one lifts higher and one runs longer tubing. The dominant real-world failure of every volume-first system is silent calibration drift, so OpenReef watches for it: when the model and the sensors disagree by more than 10 %, you get a recalibration prompt instead of a slowly-emptying sump.",
      ],
    },
    {
      heading: "Maths you can audit",
      paragraphs: [
        "Continuous trickle changes are gentler on chemistry, but every litre does slightly less work than a batch litre — new water starts diluting out the moment it goes in. Most tools quietly add the litres up and call it a percentage. OpenReef shows the real number:",
      ],
      snippet: `30 days of 1 % a day →
  naive sum:            30 % of old water removed
  actual (1 − e^−0.30): 25.9 % removed
OpenReef reports the second number —
and how many litres reach your target.`,
    },
    {
      heading: "The safety stack",
      paragraphs: [
        "Three methods — batch sequential (drain, then fill), batch simultaneous (drain and fill together, monitored every 2 seconds), and continuous micro-changes. All of them run inside the same layered safety model:",
      ],
      list: [
        "A single cycle refuses to move more than 25 % of tank volume by default — the clamp is yours to change, knowingly",
        "Every pump leg has a runtime cap sized from its own expected time; a leg running 2× expected warns, 3× aborts and latches until you clear it",
        "Simultaneous mode aborts if drain and fill diverge by more than half a litre mid-run",
        "A cumulative ledger tracks drain-vs-fill imbalance across cycles and warns before it becomes a salinity problem",
        "Your ATO is held off after every change, so top-off can't fight the fill leg",
        "A schedule slot blocked by safety for hours is consumed, not fired late into the evening",
      ],
    },
    {
      heading: "Bring your own pumps",
      paragraphs: [
        "OpenReef drives any pump Home Assistant can switch — cheap peristaltics included. For the full build there are open ESPHome reference designs in the repo, and they carry the non-negotiable rule of this feature: hard safety lives in firmware. The node has its own watchdog, float interlocks and a master power-cut path, so Wi-Fi can drop mid-change and no pump is ever stranded on. OpenReef plans, drives and accounts the litres — it is deliberately not your last line of defence.",
        "For scale: a Neptune DOS is £359.99, and the dedicated AWC bundle with reservoir is £589.95. The pumps are worth paying for. The maths never was.",
      ],
    },
  ],
  limits: [
    "OpenReef only touches pumps you have mapped and armed yourself — an AWC never runs out of the box.",
    "Volume accuracy is only as good as calibration. That's why drift detection and the recalibration prompt are first-class features, not fine print.",
    "The ESPHome nodes are reference designs to build and adapt, not a boxed product — that's the DIY manual's job.",
    "New salt water is your department: mixed, heated and salinity-matched before it goes in the reservoir.",
  ],
  faq: [
    {
      q: "Will it work with my Apex DOS?",
      a: "A DOS runs on the Neptune side, so OpenReef can't drive it directly. The usual pattern: keep the DOS for dosing, and give OpenReef a pair of inexpensive peristaltic pumps for water changes — it brings the same volume-first accounting the DOS is loved for.",
    },
    {
      q: "What happens when a line clogs or a float sticks?",
      a: "A clogged leg overruns its expected runtime: at 2× it warns, at 3× it aborts and latches until you investigate. A stuck float can block a cycle from starting but can never start one. And on the reference hardware, firmware-level watchdogs cap every run even if the network is gone.",
    },
    {
      q: "Batch or continuous — which should I run?",
      a: "The engine does both and shows honest dilution numbers for each. Continuous is gentler and slightly less efficient per litre; batch is simpler and exact. OpenReef tells you what each schedule actually removes over 30 days, so it's a decision, not a guess.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
