import { createRoot } from "react-dom/client";
import DeepDive from "./DeepDive";
import type { DeepDiveContent } from "./DeepDive";
import "../styles.css";
import "./deepdive.css";

const content: DeepDiveContent = {
  slug: "cooling-headroom",
  h1: "Cooling Headroom",
  lede: "A tank fan is not an air conditioner. It evaporates water off a 26 °C surface, so what limits it is the gap between the water temperature and the room's dew point — not humidity, not the thermostat. OpenReef measures that gap, forecasts it, and runs the dehumidifier and the window fan only when they change the outcome.",
  buddyLine: "Your fans don't care about humidity. They care about dew point. So do I.",
  buddyPose: "concerned",
  img: "/demos/cooling.png",
  imgAlt: "OpenReef Reef Pulse wall showing the cooling headroom insight card",
  demoLabel: "See the cooling insight on the demo's Pulse wall",
  sections: [
    {
      heading: "The number that actually decides",
      paragraphs: [
        "Layer 1 is psychrometrics: from room temperature, room humidity and water temperature OpenReef computes the vapour-pressure deficit between the water surface and the air, and reports it as a fan-effect index against a reference of 28 °C at 40 % over a 26 °C tank. Good above 70 %, thin to 40, weak to 15, dead below — and reversed when the room's dew point reaches the water and the air is warmer, because then the fan is heating the tank. On a 26 °C tank the fans die at roughly 89 % relative humidity at 28 °C, 79 % at 30 °C, 71 % at 32 °C. That's why 'it was only 78 % humidity' is not a defence.",
      ],
      snippet: `room 27.6 °C · 64 % RH  →  dew point 20.2 °C
water 25.9 °C  →  margin 5.7 °C  →  VPD 0.98 kPa
fan effect 53 % · band: thin — "fan headroom thinning"
what-if @ 22 °C: 50 % RH → good · 80 % RH → weak`,
    },
    {
      heading: "Ahead of the heat, not behind it",
      paragraphs: [
        "Layer 2 reads your weather entity's hourly forecast, corrects it with the indoor offsets it has learned from its own readings hour by hour, and projects the fan-effect index 24 hours ahead. From that it classifies the day — a dry-heat day the fans will cope with, or a muggy one they won't — and plans the dehumidifier: advise mode tells you when; auto mode switches the plug, starting a lead time ahead of the first affected hour because a dehumidifier dumps hundreds of watts into the room and must run before the heat, not during it. Compressor short-cycle guards, a max-run limit with a 'check the bucket' nudge, and an override policy that respects a hand on the switch.",
      ],
    },
    {
      heading: "Free cooling first",
      paragraphs: [
        "Layer 3 is the intake fan in front of a slightly-open window: free dehumidification whenever the outdoor dew point is lower than indoors, free cooling whenever outside is simply cooler and no wetter, and a night purge through the coolest hours ahead of a hot day. Never at the same time as the dehumidifier. An optional window contact stops the fan running against closed glass, and every gate carries a deadband — because each of these switches on the very thing that erases its own reason to be on.",
      ],
      list: [
        "Metric: dew-point margin and VPD — never room RH, never wet-bulb",
        "Fan stays on its thermostat socket; 'cooling needed' is inferred, not seized",
        "Efficiency, never safety: everything fails OFF, the fan and the temperature guard stay the backstop",
        "Learned per-hour indoor offsets from OpenReef's own 5-minute readings, trusted after six samples",
      ],
    },
  ],
  limits: [
    "The projection is only as good as the weather entity's hourly forecast; in the UK a Met Office feed does well, a generic one less so.",
    "The dehumidifier is assumed to be a dumb unit on a smart plug with its humidistat turned to continuous — OpenReef is the humidistat now.",
    "Learned offsets start from zero and collect from the day you enable it — the first week's projections lean on the raw forecast.",
    "This layer never touches the heater or the chiller. It decides whether cheap air can do the job, and says so.",
  ],
  faq: [
    {
      q: "Why not just trigger on humidity like my dehumidifier does?",
      a: "Because a 60 % humidistat fires on a cool, humid evening when the fans have plenty of headroom, and sleeps through a 30 °C afternoon at 75 % when they've got none. The fan physics runs on dew-point margin; the controller should too.",
    },
    {
      q: "Will it turn the dehumidifier on by itself?",
      a: "Only in auto mode, only on an armed plug you mapped, only ahead of hours the projection says the fans won't cope with — and it fails off. Advise mode, the default, just tells you when and why.",
    },
    {
      q: "What's the window fan doing exactly?",
      a: "Pulling in outdoor air whenever it's drier or cooler than the room — which in a British summer is most nights — so the dehumidifier runs less. A window contact sensor is optional but stops it blowing at closed glass.",
    },
  ],
};

createRoot(document.getElementById("root")!).render(<DeepDive c={content} />);
