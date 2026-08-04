import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "camera-intelligence",
  h1: "Camera Intelligence",
  lede: "A £30 USB camera and a lot of software: live view in the panel, snapshots when something happens, growth timelapses with a retention ladder, shareable stat cards — and, with Frigate, a second pair of eyes that knows your fish.",
  buddyLine: "I noticed the tang skipped breakfast before you did. That is the entire point of me.",
  buddyPose: "concerned",
  img: "/demos/cameras.png",
  imgAlt: "OpenReef cameras tab in Home Assistant",
  sections: [
    {
      heading: "Live view for pocket money",
      paragraphs: [
        "The development tank runs an ELP USB camera — the kind that costs less than a bag of salt — served through go2rtc and streamed straight into the OpenReef panel over WebRTC. No cloud account, no subscription, no footage leaving your house. Any camera Home Assistant or go2rtc can serve works the same way.",
        "The expensive ecosystems will happily sell you a camera as an accessory. Here the camera is the cheap part, on purpose — the intelligence is software, and software is free.",
      ],
    },
    {
      heading: "A memory of everything",
      paragraphs: [
        "When something happens on the tank — an alert, a feed, a water change — snapshots are captured around the event, so the notification on your phone comes with pictures instead of homework.",
        "And underneath it all, the timelapse engine quietly photographs your reef on a cadence (every 30 minutes through the day by default) and manages its own history with a retention ladder, so you get the whole story of your tank without ever thinking about disk space:",
      ],
      snippet: `timelapse retention ladder →
  every frame      for 14 days
  one per day      to 90 days
  one per week     to a year
  one per month    forever
two years of coral growth, bounded disk`,
    },
    {
      heading: "Feed-watch and the fish layer",
      paragraphs: [
        "Start a feed and feed-watch captures a frame every 10 seconds for the session, keeping your last 25 feeds — the moments you actually rewatch. The overlay tool burns your live parameters onto any snapshot, so the picture you post to the forum carries its own alk, temperature and salinity.",
        "Run a Frigate NVR alongside and OpenReef folds its fish detections into real intelligence:",
      ],
      list: [
        "Per-species last-seen tracking — \"the yellow tang hasn't been seen for 6 hours\" as a notification, with cooldowns so it never spams you",
        "Zone visits — which fish actually visit which coral, counted properly (one visit per fish per pass, not one per video frame)",
        "Surface-distress alerts — a fish loitering at the surface for five continuous minutes is worth interrupting your meeting for",
        "A feeding report card — who responded to food and how fast, per fish, so appetite loss shows up as data before it shows up as a problem",
      ],
    },
  ],
  limits: [
    "The fish layer (missing fish, zone visits, feeding report card) needs an external Frigate NVR you run yourself, with detection zones you draw — OpenReef consumes its events, it doesn't replace it.",
    "Species recognition is Frigate's classifier, trained on your fish; OpenReef aggregates what it reports honestly rather than adding magic on top.",
    "Everything is local. That's the point — but it also means you own the disk the footage lives on; the retention ladders manage it, they don't multiply it.",
    "Camera placement decides everything. A lens pointing at the rockwork's best side sees fish; a lens pointing at glare sees glare.",
  ],
  faq: [
    {
      q: "What camera do I need?",
      a: "The reference setup is a ~£30 ELP USB camera through go2rtc. Any camera Home Assistant or go2rtc can serve — USB, RTSP, ONVIF — plugs into the same live view, snapshots and timelapse machinery.",
    },
    {
      q: "Do I need to run Frigate?",
      a: "No. Live view, event snapshots, timelapses, overlays and feed-watch all work with just a camera. Frigate is the optional add-on that upgrades footage into per-fish intelligence.",
    },
    {
      q: "Will it really notice a missing fish?",
      a: "It reports \"not seen since\" per species from actual sightings, survives Home Assistant restarts, and won't cry wolf — alerts carry cooldowns, and time when the camera was offline is never counted against a fish. How sharp it is depends on your camera placement and Frigate's detection quality. It's a second pair of eyes, not a guarantee.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
