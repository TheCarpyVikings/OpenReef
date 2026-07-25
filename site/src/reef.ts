// Shared mutable state bridging the DOM layer (writes) and the R3F frame loop
// (reads every frame, so it must not go through React state).
export type Tone = "cheeky" | "professional";

export const reef = {
  scroll: 0, // page scroll progress 0..1
  sun: 13, // hour of day 0..24, driven by the light-beat scrubber
  score: 92, // reef health score, driven by the sandbox
  spawnPulse: 0, // incremented each time the spawn button fires
  lowPower: false,
};

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const gauss = (x: number, mu: number, sigma: number) =>
  Math.exp(-((x - mu) ** 2) / (2 * sigma * sigma));

// Sun elevation −1..1 across the day (above horizon 06:00–18:00-ish).
export const sunElevation = (h: number) => Math.sin(((h - 6) / 12) * Math.PI);

export interface Channel {
  id: string;
  label: string;
  color: string;
  curve: (h: number) => number;
}

const night = (h: number) => (h < 6.5 || h > 19.5 ? 1 : 0);

export const CHANNELS: Channel[] = [
  { id: "uv", label: "UV", color: "#5a00b0", curve: (h) => gauss(h, 13, 5.0) * 0.8 },
  { id: "violet", label: "Violet", color: "#7a2aff", curve: (h) => gauss(h, 13, 4.8) * 0.9 },
  { id: "royal", label: "Royal", color: "#2a4bff", curve: (h) => gauss(h, 13, 4.5) },
  { id: "blue", label: "Blue", color: "#2a6bff", curve: (h) => gauss(h, 13, 4.2) },
  { id: "white", label: "White", color: "#f2f6ff", curve: (h) => gauss(h, 13, 3.2) },
  { id: "green", label: "Green", color: "#22cc66", curve: (h) => gauss(h, 13, 2.8) * 0.85 },
  { id: "red", label: "Red", color: "#ff3a2a", curve: (h) => gauss(h, 13, 2.6) * 0.8 },
  { id: "moon", label: "Moon", color: "#9fb7ff", curve: (h) => night(h) * 0.35 },
];

// Camera depth keyframes: [scroll t, world y]. Shared with the DOM depth gauge.
export const DEPTH_KEYS: Array<[number, number]> = [
  [0.0, 4],
  [0.1, -2],
  [0.2, -8],
  [0.33, -14],
  [0.47, -20],
  [0.6, -26],
  [0.73, -33],
  [0.86, -40],
  [1.0, -44.5],
];

export function depthAt(t: number): number {
  const keys = DEPTH_KEYS;
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [t1, y1] = keys[i];
    const [t0, y0] = keys[i - 1];
    if (t <= t1) return lerp(y0, y1, (t - t0) / (t1 - t0));
  }
  return keys[keys.length - 1][1];
}

// Deterministic RNG so the procedural reef is identical on every visit.
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
