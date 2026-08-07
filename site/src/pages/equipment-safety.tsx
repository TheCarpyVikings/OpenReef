import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "equipment-safety",
  h1: "The Safety Model",
  lede: "Automation on a reef tank has one non-negotiable: software must never be able to hurt livestock by accident. OpenReef's answer is a model you can recite: nothing is touchable until you arm it, the classic mistakes are refused by interlocks, and a Trust Check rehearses the rescue chain before the night you need it.",
  buddyLine: "I can see every switch in your house. I'm allowed to touch the four you armed. That's the entire religion.",
  buddyPose: "point",
  img: "/demos/controls.png",
  imgAlt: "OpenReef equipment controls tab in Home Assistant",
  demoLabel: "Try flipping the unarmed one in the demo",
  sections: [
    {
      heading: "Armed means armed",
      paragraphs: [
        "Every piece of equipment goes through two explicit steps: you map it to an outlet, and then you arm it. Mapped-but-unarmed equipment is visible everywhere and controllable nowhere — try to switch it and OpenReef refuses, in words: \"it has never been armed — until then the software cannot touch it.\" No import, no automation, no update can flip that for you.",
        "The rule holds without exception, including in the live demo: the frag light there is deliberately left unarmed so you can feel the refusal for yourself.",
      ],
    },
    {
      heading: "Interlocks: the classic mistakes, pre-refused",
      paragraphs: [
        "Above the arm-lock sits a set of interlocks for the accidents every reefer eventually meets:",
      ],
      list: [
        "The ATO won't run while an automatic water change is in progress — top-off fighting a fill leg is how salinity crashes happen",
        "The ATO won't run when return flow isn't confirmed — a dry return chamber must not be 'topped up' into a flood",
        "An optional ATO runtime cap: a stuck float can't run the pump until the reservoir is in your sump",
        "The heater interlock expects a live tank-temperature sensor behind any heater — heat with no thermometer is not a controlled system",
        "Optionally, skimmers switch off with the return pump — so a restart never means an overflowing cup",
        "The AWC engine carries its own layered stack on top (runtime caps, abort-latch, imbalance monitoring — it has its own deep dive)",
      ],
    },
    {
      heading: "The Trust Check: rehearsing the 2 AM save",
      paragraphs: [
        "An alert system you've never tested is a hope, not a system. The Trust Check is a one-tap audit of the whole rescue chain — the exact chain the 2 AM heater story depends on — and it deliberately nags about the step everyone skips: actually sending yourself a test notification.",
      ],
      snippet: `trust check →
  sensor trust     6/6 enabled sensors mapped, reporting   OK
  unsafe mappings  no armed device unavailable             OK
  notifications    configured — but never tested           ⚠
  heartbeat        last beat 2 minutes ago                 OK
  cameras          1 mapped, reachable                     OK`,
    },
  ],
  limits: [
    "OpenReef drives switches through Home Assistant — it is intelligence, not a hardwired failsafe. Keep mechanical protection (and your controller's fallback rules) as the last line; the DIY hardware designs put watchdogs in firmware for exactly this reason.",
    "Overtemperature response today is detection plus an immediate push alert, with the armed switch one tap away — automatic heater cut-off is on the roadmap, not shipped, because auto-acting on livestock equipment is the highest-stakes automation there is and we ship it slowly.",
    "The Trust Check reports; it doesn't repair. A red row tells you which link of the chain to fix.",
    "Safety alerts are always written dry. The panel's personality lives strictly on calm screens — a critical alert will never try to be funny.",
  ],
  faq: [
    {
      q: "Will it switch a stuck heater off by itself?",
      a: "Not yet, and that's deliberate honesty rather than a gap we're hiding: today OpenReef detects the temperature-vs-heater-state disagreement and pushes one clear alert, with the armed outlet one tap away. If you run an Apex, keep your fallback rules programmed — OpenReef adds the brain on top; it doesn't ask you to remove the reflexes underneath.",
    },
    {
      q: "What does arming actually change?",
      a: "Mapped equipment is monitored and displayed. Armed equipment is the only kind OpenReef will ever switch — from the panel, from the diagram, from anywhere. Unarmed equipment gets a refusal with the reason spelled out, every time.",
    },
    {
      q: "Why does the Trust Check nag me about notifications?",
      a: "Because the notification path is the one link that fails silently. Sensors misbehave loudly; a broken push token just says nothing, forever. The check stays amber until a real test notification has been recorded — the thirty-second chore that makes the 2 AM story possible.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
