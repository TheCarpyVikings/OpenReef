// All narrative copy for the dive. Same shape as the panel's onboarding script:
// cheeky (Apex detected), cheekyNoApex, professional — the buddy picks per visitor.
import type { Tone } from "./reef";

export const GITHUB_URL = "https://github.com/TheCarpyVikings/OpenReef";

export type Pose =
  | "idle"
  | "point"
  | "smug"
  | "facepalm"
  | "celebrate"
  | "concerned"
  | "thinking"
  | "chilled";

export const POSE_EMOJI: Record<Pose, string> = {
  idle: "👋",
  point: "👉",
  smug: "😏",
  facepalm: "🤦",
  celebrate: "🎉",
  concerned: "😟",
  thinking: "🤔",
  chilled: "😎",
};

export interface BuddyStep {
  pose: Pose;
  cheeky: string;
  cheekyNoApex?: string;
  professional: string;
}

export const BUDDY_SCRIPT: Record<string, BuddyStep> = {
  hero: {
    pose: "idle",
    cheeky:
      "Hey — I'm the little reefer who lives in the OpenReef dashboard. Scroll down. The water's lovely.",
    professional: "Welcome to OpenReef. Scroll down to take the dive.",
  },
  meet: {
    pose: "point",
    cheeky:
      "Two quick questions and I'll tailor the whole tour. This is the same joke-selection logic the real dashboard runs — I never waste good material.",
    professional:
      "Choose a tone and tell me about your controller. The tour adapts to both — this is the same logic the product uses.",
  },
  sandbox: {
    pose: "smug",
    cheeky:
      "Go on, break something. Fusion would show you a graph and wish you luck — I'll tell you what's wrong, in English, with the dose to fix it.",
    cheekyNoApex:
      "Go on, break something. I'll catch it, explain it in plain English, and tell you exactly what to dose.",
    professional:
      "Adjust the sliders. The Reef Health score, the alert, and the dosing advice all react live — this is real product logic.",
  },
  lights: {
    pose: "chilled",
    cheeky:
      "I don't run your lights — yet. I read their schedule, then time everything else around your reef's day. Drag the sun and watch me keep up.",
    professional:
      "OpenReef doesn't control lighting yet — it reads your existing schedule and times its own features around your reef's day. Drag the time of day to see what shifts.",
  },
  spawning: {
    pose: "thinking",
    cheeky:
      "Wind the moon to nights 12–15 after full. Your Apex can do many things; counting moons isn't one of them.",
    cheekyNoApex:
      "Wind the moon to nights 12–15 after the full moon — that's when Great Barrier Reef corals let go. Biology, compiled.",
    professional:
      "Coral spawning follows the lunar calendar — GBR broadcast spawners release 12–15 nights after the full moon. OpenReef compiles that into your light schedule.",
  },
  features: {
    pose: "point",
    cheeky:
      "Everything here is shipped code, not roadmap. No renders, no artist's impressions, no marketing tank with suspiciously perfect acros.",
    professional: "Everything below is shipped and running in the current Home Assistant integration.",
  },
  diy: {
    pose: "celebrate",
    cheeky:
      "Every part number, every wire, free forever — that's the open in OpenReef. The kits just save you the soldering.",
    professional:
      "The full DIY manual will be free. The kits are the same build with the shopping and soldering done for you.",
  },
  compare: {
    pose: "smug",
    cheeky:
      "Keep the box — it's a very good box, see, we gave it a throne. It just needed a brain. And yes, Trident reagents really are the printer ink of the sea.",
    cheekyNoApex:
      "Some controllers sell you Insight. We'd rather your problems weren't out of sight. The maths is free either way.",
    professional:
      "Three honest paths. If you already own an Apex, the middle column costs you nothing but an evening with Home Assistant.",
  },
  cta: {
    pose: "celebrate",
    cheeky:
      "That's the dive. Leave an email, get the manual the day it ships, maybe grab a beta seat. Now go show your tank who's boss. 🪸",
    professional:
      "That's the tour. Leave an email to get the manual on release day, and to apply for the private beta. 🪸",
  },
};

export function buddyLine(section: string, tone: Tone, hasApex: boolean | null): BuddyStep & { text: string } {
  const step = BUDDY_SCRIPT[section] ?? BUDDY_SCRIPT.hero;
  const text =
    tone === "professional"
      ? step.professional
      : hasApex === false && step.cheekyNoApex
        ? step.cheekyNoApex
        : step.cheeky;
  return { ...step, text };
}

export interface FeatureCard {
  title: string;
  body: string;
  img?: string;
}

// img paths match the output of site/tools/capture-demos.mjs — cards hide their
// image until the corresponding screenshot exists in public/demos/.
export const FEATURES: FeatureCard[] = [
  {
    title: "Mission Control",
    body: "Every sensor, switch and safety interlock on one screen — with an explainable Reef Health score up top.",
    img: "/demos/mission-control.png",
  },
  {
    title: "Live monitoring",
    body: "Tap any reading for its full trend, from 1 hour to 30 days. Apex probes, Trident results and cheap third-party sensors, side by side.",
    img: "/demos/live-stats.png",
  },
  {
    title: "Equipment control",
    body: "Map an outlet, arm it yourself, and only then can OpenReef touch it. Your livestock is never automated behind your back.",
    img: "/demos/controls.png",
  },
  {
    title: "Schedule-aware intelligence",
    body: "OpenReef doesn't run your lights (yet) — it reads your lighting schedule and times spawning windows, feed-watch and quiet hours around your reef's day.",
  },
  {
    title: "Energy & maintenance",
    body: "Power monitoring plus HA-native maintenance reminders — fixed-day schedules, skip and snooze included.",
    img: "/demos/maintenance.png",
  },
  {
    title: "Spawning & water changes",
    body: "The coral spawning scheduler and the automatic water change engine — volume-first, with layered safety.",
    img: "/demos/awc.png",
  },
  {
    title: "Dosing advisor",
    body: "Alk, calcium and magnesium consumption worked out from your history, with projections and suggested dose changes. Advisory only, always.",
    img: "/demos/dosing.png",
  },
  {
    title: "ICP import",
    body: "Drop in a Triton CSV or an ATI PDF. OpenReef normalises it, flags what's off, and folds it into your trends.",
    img: "/demos/icp.png",
  },
  {
    title: "Camera intelligence",
    body: "Event capture, timelapses, shareable overlays and feed-watch — a cheap USB camera doing expensive-camera things.",
    img: "/demos/cameras.png",
  },
];

export interface Tier {
  name: string;
  subtitle: string;
  body: string;
  cheekyTagline: string;
}

export const TIERS: Tier[] = [
  {
    name: "Frag",
    subtitle: "The Starter",
    body: "Monitoring-only: temperature, leak, level and pH on an ESP32. See everything before you automate anything.",
    cheekyTagline: "Every reef starts as a frag. This one sees everything — for less than a year of reagents.",
  },
  {
    name: "Colony",
    subtitle: "The Grower",
    body: "Monitor + control: adds relays, ATO and dosing outputs with the full arm-it-yourself safety model.",
    cheekyTagline: "You map the outlet, you arm the outlet. Growth, with guardrails.",
  },
  {
    name: "Reef",
    subtitle: "The Ecosystem",
    body: "The whole build: sensors, control, dosing pumps, display and enclosure. Everything in the manual, in one box.",
    cheekyTagline: "The full ecosystem. Elsewhere, that word costs four figures.",
  },
];

export interface CompareRow {
  label: string;
  apex: string;
  both: string;
  diy: string;
}

export const COMPARE_ROWS: CompareRow[] = [
  { label: "Up-front hardware", apex: "£1,000 (A3 Pro system)", both: "£0 — keeps your Apex", diy: "~£150–£300 in parts" },
  { label: "Automated alk/Ca/Mg testing", apex: "£775 Trident + £252/yr reagents", both: "Your Trident, plus the maths", diy: "Manual tests, logged" },
  { label: "Software", apex: "Fusion (cloud)", both: "Free, open source", diy: "Free, open source" },
  { label: "Consumption-based dosing advice", apex: "—", both: "✓ from your existing tests", diy: "✓ from any test log" },
  { label: "Alerts", apex: "Fault codes + forums", both: "Plain English", diy: "Plain English" },
  { label: "Coral spawning scheduler", apex: "—", both: "✓", diy: "✓" },
  { label: "ICP import (Triton CSV, ATI PDF)", apex: "—", both: "✓", diy: "✓" },
  { label: "Automatic water changes", apex: "DOS + DDR, £590", both: "✓ via Home Assistant", diy: "✓ full engine" },
  { label: "Camera timelapse & feed watch", apex: "—", both: "✓", diy: "✓" },
  { label: "Local-first, no cloud account", apex: "—", both: "✓ Home Assistant", diy: "✓ Home Assistant" },
  { label: "Open source", apex: "—", both: "✓", diy: "✓" },
];

export interface TickerItem {
  t: number; // scroll threshold
  label: string;
  amt: number;
}

// UK street prices verified 2026-07-25 (All Things Aquatic / Charterhouse Aquatics).
// Keep these honest — they are the one place the site makes a hard money claim.
export const TICKER: TickerItem[] = [
  { t: 0.16, label: "Apex A3 Pro system", amt: 1000 },
  { t: 0.31, label: "Trident", amt: 775 },
  { t: 0.45, label: "Trident reagents, year one", amt: 252 },
  { t: 0.6, label: "DOS + DDR combo", amt: 590 },
  { t: 0.72, label: "Extra Energy Bar 632", amt: 325 },
];
