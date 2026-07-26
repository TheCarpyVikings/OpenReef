import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { clamp, reef } from "../reef";
import type { Tone } from "../reef";
import { COMPARE_ROWS, FEATURES, GITHUB_URL, TIERS } from "../copy";
import type { FeatureCard } from "../copy";

/* ---------------------------------- hero ------------------------------------- */

export function Hero() {
  return (
    <section data-sec="hero" className="sec sec-hero">
      <div className="hero-inner">
        <img src="/logo.png" alt="OpenReef" className="hero-logo" />
        <h1>
          The intelligence layer
          <br />
          for your reef.
        </h1>
        <p className="hero-sub">
          OpenReef is a free, open-source brain for your aquarium. It watches every probe, does the
          dosing maths, and explains your tank in plain English. Runs on Home Assistant.{" "}
          <strong>Plays nicely with your Apex.</strong>
        </p>
        <div className="hero-badges">
          <span>Open source</span>
          <span>Local-first</span>
          <span>Private beta — now recruiting</span>
        </div>
        <div className="hero-ctas">
          <a className="btn btn-primary" href="#dive">
            Dive in ↓
          </a>
          <a className="btn btn-ghost" href="#cta">
            Join the beta
          </a>
        </div>
      </div>
      <div className="scroll-cue" aria-hidden="true">
        ▼
      </div>
    </section>
  );
}

/* ------------------------------ meet the buddy -------------------------------- */

interface MeetProps {
  tone: Tone;
  setTone: (t: Tone) => void;
  hasApex: boolean | null;
  setHasApex: (v: boolean) => void;
}

export function Meet({ tone, setTone, hasApex, setHasApex }: MeetProps) {
  return (
    <section data-sec="meet" id="dive" className="sec">
      <div className="card card-left">
        <h2>First, a quick calibration.</h2>
        <p>Pick a tone, and tell me what's running your tank. Every joke after this adapts.</p>
        <div className="field">
          <span className="field-label">Tour voice</span>
          <div className="seg">
            <button className={tone === "cheeky" ? "on" : ""} onClick={() => setTone("cheeky")}>
              Cheeky
            </button>
            <button
              className={tone === "professional" ? "on" : ""}
              onClick={() => setTone("professional")}
            >
              Professional
            </button>
          </div>
        </div>
        <div className="field">
          <span className="field-label">Do you run an Apex? (No judgement. Well. A little.)</span>
          <div className="seg">
            <button className={hasApex === true ? "on" : ""} onClick={() => setHasApex(true)}>
              Yes, proudly
            </button>
            <button className={hasApex === false ? "on" : ""} onClick={() => setHasApex(false)}>
              Nope
            </button>
          </div>
        </div>
        {hasApex === true && (
          <p className="callout">
            Excellent. <strong>Keep it.</strong> We're not here to take your box — we're here to give
            it a brain.
          </p>
        )}
        {hasApex === false && (
          <p className="callout">
            Even better — you're about to skip the £600 entry fee entirely.
          </p>
        )}
        <p className="fine-print">
          ⓘ This page runs the same joke-selection logic as the product — <code>_hasApex()</code> is
          real shipped code.
        </p>
      </div>
    </section>
  );
}

/* --------------------------- break-the-tank sandbox --------------------------- */

interface Param {
  id: string;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  ideal: number;
  tol: number;
}

const PARAMS: Param[] = [
  { id: "alk", label: "Alkalinity", unit: "dKH", min: 5, max: 12, step: 0.1, ideal: 8.5, tol: 1.0 },
  { id: "temp", label: "Temperature", unit: "°C", min: 22, max: 30, step: 0.1, ideal: 25.5, tol: 1.0 },
  { id: "ph", label: "pH", unit: "", min: 7.6, max: 8.6, step: 0.01, ideal: 8.15, tol: 0.25 },
  { id: "sal", label: "Salinity", unit: "ppt", min: 30, max: 40, step: 0.1, ideal: 35, tol: 1.0 },
];

function computeScore(vals: Record<string, number>): number {
  let penalty = 0;
  for (const p of PARAMS) {
    const dev = Math.abs(vals[p.id] - p.ideal) / p.tol;
    penalty += Math.min(40, dev * dev * 12);
  }
  return Math.round(clamp(100 - penalty, 0, 100));
}

function worstParam(vals: Record<string, number>): { p: Param; dev: number } {
  let worst = PARAMS[0];
  let worstDev = 0;
  for (const p of PARAMS) {
    const dev = Math.abs(vals[p.id] - p.ideal) / p.tol;
    if (dev > worstDev) {
      worstDev = dev;
      worst = p;
    }
  }
  return { p: worst, dev: worstDev };
}

function alertFor(vals: Record<string, number>): { text: string; advice: string } | null {
  const { p, dev } = worstParam(vals);
  if (dev < 0.8) return null;
  const v = vals[p.id];
  const low = v < p.ideal;
  switch (p.id) {
    case "alk": {
      const delta = Math.abs(p.ideal - v);
      const ml = Math.max(1, Math.round(delta * 7));
      return {
        text: low
          ? `Alkalinity is drifting low (${v.toFixed(1)} dKH). At last week's consumption that's a falling trend, not a blip.`
          : `Alkalinity is running high (${v.toFixed(1)} dKH). Corals can't bank the surplus — but they can bleach on it.`,
        advice: low
          ? `Suggested: raise the alk dose by ~${ml} ml/day and re-test in 48 h.`
          : `Suggested: cut the alk dose by ~${ml} ml/day and re-test in 48 h.`,
      };
    }
    case "temp":
      return {
        text: low
          ? `Temperature is low (${v.toFixed(1)} °C). Check the heater and its outlet before the corals check out.`
          : `Temperature is high (${v.toFixed(1)} °C). Check heater stuck-on, room temp, and lids.`,
        advice: "OpenReef would name the exact outlet and its power draw here.",
      };
    case "ph":
      return {
        text: low
          ? `pH is depressed (${v.toFixed(2)}). Usually CO₂ — a stuffy room, or alk riding low.`
          : `pH is elevated (${v.toFixed(2)}). Check kalk or CO₂ scrubber overdrive.`,
        advice: "OpenReef cross-references alk + pH trends before it blames anything.",
      };
    default:
      return {
        text: low
          ? `Salinity is low (${v.toFixed(1)} ppt). ATO topping up with… more than water?`
          : `Salinity is high (${v.toFixed(1)} ppt). Evaporation is winning; the ATO isn't.`,
        advice: "OpenReef watches this against your AWC schedule automatically.",
      };
  }
}

export function Sandbox({ score, setScore }: { score: number; setScore: (n: number) => void }) {
  const [vals, setVals] = useState<Record<string, number>>({
    alk: 8.5,
    temp: 25.5,
    ph: 8.15,
    sal: 35,
  });
  const alert = useMemo(() => alertFor(vals), [vals]);
  const set = (id: string, v: number) => {
    const next = { ...vals, [id]: v };
    setVals(next);
    const s = computeScore(next);
    setScore(s);
    reef.score = s;
  };
  return (
    <section data-sec="sandbox" className="sec">
      <div className="card card-left">
        <h2>One honest number.</h2>
        <p>
          Every probe, trend and test folds into a single explainable Reef Health score, weighted for
          your reef type. Here's a live one. <strong>Break it.</strong>
        </p>
        <div className="sandbox-grid">
          <div className="sandbox-sliders">
            {PARAMS.map((p) => (
              <label key={p.id} className="slider-row">
                <span>
                  {p.label}
                  <em>
                    {vals[p.id].toFixed(p.step < 0.1 ? 2 : 1)} {p.unit}
                  </em>
                </span>
                <input
                  type="range"
                  min={p.min}
                  max={p.max}
                  step={p.step}
                  value={vals[p.id]}
                  onChange={(e) => set(p.id, Number(e.target.value))}
                />
              </label>
            ))}
          </div>
          <div className="sandbox-readout">
            <div
              className={
                "score-big " + (score >= 85 ? "score-ok" : score >= 60 ? "score-warn" : "score-bad")
              }
            >
              {score}
            </div>
            <div className="score-caption">Reef Health</div>
          </div>
        </div>
        {alert ? (
          <div className="alert-box">
            <p>{alert.text}</p>
            <p className="advice">{alert.advice}</p>
          </div>
        ) : (
          <div className="alert-box alert-calm">
            <p>All parameters in range. Somewhere, a coral is quietly thriving.</p>
          </div>
        )}
        <p className="fine-print">
          Advisory only — OpenReef never switches an outlet you haven't mapped and armed yourself.
        </p>
      </div>
    </section>
  );
}

/* -------------------------------- light beat ---------------------------------- */

const phaseName = (h: number) =>
  h < 5.5
    ? "Deep night"
    : h < 8
      ? "Sunrise ramp"
      : h < 11
        ? "Morning blues"
        : h < 15
          ? "Full spectrum"
          : h < 18.5
            ? "Afternoon"
            : h < 20.5
              ? "Sunset ramp"
              : "Moonlight";

interface ScheduleRow {
  label: string;
  value: string;
  on: boolean;
}

// What OpenReef derives from the visitor's (simulated) lighting schedule at a
// given hour — honest: OpenReef reads schedules, it does not run lights.
function scheduleReadout(h: number): ScheduleRow[] {
  const night = h < 6.5 || h >= 20.5;
  const golden = (h >= 6.5 && h < 9) || (h >= 17 && h < 19.5);
  return [
    { label: "Photoperiod (from your schedule)", value: phaseName(h), on: !night },
    {
      label: "Feed-watch window",
      value: h >= 9 && h < 18 ? "open — camera armed" : "closed until lights-on",
      on: h >= 9 && h < 18,
    },
    {
      label: "Spawning dusk ramp",
      value: h >= 18.5 && h < 20.5 ? "running now" : "scheduled 19:42",
      on: h >= 18.5 && h < 20.5,
    },
    {
      label: "Quiet alerts",
      value: night ? "on — lights-out, phone stays quiet" : "off — normal alerting",
      on: night,
    },
    {
      label: "Timelapse capture",
      value: golden ? "golden-hour frame" : "hourly frame",
      on: golden,
    },
  ];
}

export function Lights() {
  const [hour, setHour] = useState(13);
  const set = (h: number) => {
    setHour(h);
    reef.sun = h;
  };
  const hh = Math.floor(hour);
  const mm = Math.round((hour - hh) * 60);
  return (
    <section data-sec="lights" className="sec">
      <div className="card card-right">
        <h2>Drag the sun.</h2>
        <p>
          Your lights already have a schedule. OpenReef doesn't run them (yet) — it{" "}
          <strong>reads</strong> that schedule and times everything else around your reef's day.
          Drag the sun; watch what shifts.
        </p>
        <label className="slider-row sun-slider">
          <span>
            Time of day
            <em>
              {String(hh).padStart(2, "0")}:{String(mm).padStart(2, "0")} — {phaseName(hour)}
            </em>
          </span>
          <input
            type="range"
            min={0}
            max={24}
            step={0.1}
            value={hour}
            onChange={(e) => set(Number(e.target.value))}
          />
        </label>
        <ul className="schedule-readout" aria-label="Settings derived from the lighting schedule">
          {scheduleReadout(hour).map((r) => (
            <li key={r.label} className={r.on ? "sr-on" : ""}>
              <span className="sr-dot" aria-hidden="true" />
              <span className="sr-label">{r.label}</span>
              <span className="sr-value">{r.value}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ------------------------------- spawning beat -------------------------------- */

export function Spawning() {
  const [night, setNight] = useState(3);
  const [fired, setFired] = useState(false);
  const inWindow = night >= 12 && night <= 15;
  const fire = () => {
    reef.spawnPulse += 1;
    setFired(true);
  };
  return (
    <section data-sec="spawning" className="sec">
      <div className="card card-left">
        <h2>Your controller can't count moons.</h2>
        <p>
          Great Barrier Reef corals broadcast-spawn 12–15 nights after the full moon, on cue, every
          year. OpenReef's spawning engine compiles that biology — dusk dims, moonlight lux, pump
          slick-mode — into a programme for <em>your</em> controller to run.
        </p>
        <label className="slider-row">
          <span>
            Nights after full moon
            <em>
              {night} {inWindow ? "🌕 spawning window!" : ""}
            </em>
          </span>
          <input
            type="range"
            min={0}
            max={29}
            step={1}
            value={night}
            onChange={(e) => setNight(Number(e.target.value))}
          />
        </label>
        <button className="btn btn-primary" disabled={!inWindow} onClick={fire}>
          {inWindow ? "Release the bundles" : "Wind the moon to nights 12–15"}
        </button>
        {fired && (
          <pre className="code-snippet">{`spawning window compiled →
  19:42  dusk ramp to 4 %
  20:10  moonlight 0.8 lx (waning gibbous)
  20:30  return pumps → 20 % (slick mode)
  02:00  resume normal programme
export → your controller's schedule`}</pre>
        )}
      </div>
    </section>
  );
}

/* --------------------------------- features ----------------------------------- */

function Feature({ f, onZoom }: { f: FeatureCard; onZoom: (f: FeatureCard) => void }) {
  // Screenshots land via site/tools/capture-demos.mjs — until a file exists,
  // the card simply renders without an image.
  const [imgOk, setImgOk] = useState(true);
  const hasImg = Boolean(f.img) && imgOk;
  return (
    <article className="feature">
      {hasImg && (
        <button className="feature-shot" onClick={() => onZoom(f)} aria-label={`Enlarge ${f.title} screenshot`}>
          <img
            src={f.img}
            alt={`${f.title} screenshot`}
            loading="lazy"
            onError={() => setImgOk(false)}
          />
          <span className="feature-zoom" aria-hidden="true">
            ⤢
          </span>
        </button>
      )}
      <h3>{f.title}</h3>
      <p>{f.body}</p>
      {f.href && (
        <a className="feature-more" href={f.href}>
          Deep dive →
        </a>
      )}
    </article>
  );
}

export function Features() {
  const [zoom, setZoom] = useState<FeatureCard | null>(null);
  return (
    <section data-sec="features" className="sec sec-wide">
      <div className="card card-wide">
        <h2>The greatest hits.</h2>
        <p className="lede">
          Real screenshots from the current Home Assistant integration. Click any of them to look
          properly.
        </p>
        <div className="features-grid">
          {FEATURES.map((f) => (
            <Feature key={f.title} f={f} onZoom={setZoom} />
          ))}
        </div>
      </div>
      {zoom && (
        <div
          className="lightbox"
          role="dialog"
          aria-modal="true"
          aria-label={`${zoom.title} screenshot`}
          onClick={() => setZoom(null)}
        >
          <figure onClick={(e) => e.stopPropagation()}>
            <img src={zoom.img} alt={`${zoom.title} screenshot, enlarged`} />
            <figcaption>
              {zoom.title}
              <button onClick={() => setZoom(null)} aria-label="Close">
                ×
              </button>
            </figcaption>
          </figure>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------ DIY ------------------------------------- */

export function Diy({ tone }: { tone: Tone }) {
  return (
    <section data-sec="diy" className="sec sec-wide">
      <div className="card card-wide">
        <h2>Free as in manual.</h2>
        <p className="lede">
          The full DIY build manual — every part number, every wire, every flashing step — will be
          free forever. That's the <strong>open</strong> in OpenReef. The kits are the same build
          with the shopping and soldering done for you.
        </p>
        <div className="tiers">
          {TIERS.map((t) => (
            <article key={t.name} className="tier">
              <h3>
                {t.name} <span>{t.subtitle}</span>
              </h3>
              <p>{t.body}</p>
              {tone === "cheeky" && <p className="tier-tag">“{t.cheekyTagline}”</p>}
              <a className="btn btn-ghost" href="#cta">
                Join the kit waitlist
              </a>
            </article>
          ))}
        </div>
        <p className="fine-print">
          Kits are in research — components, safety and certification are being worked out properly
          before anything goes on sale. The waitlist gets a vote on what's inside.
        </p>
      </div>
    </section>
  );
}

/* --------------------------------- comparison --------------------------------- */

export function Compare({ tone, hasApex }: { tone: Tone; hasApex: boolean | null }) {
  const [stickerOk, setStickerOk] = useState(true);
  // Deliberately click-to-reveal: the gag is aimed at owners who opted into
  // Cheeky mode, and it shouldn't ambush anyone reading the price table.
  const [revealed, setRevealed] = useState(false);
  const showSticker = tone === "cheeky" && hasApex === true && stickerOk;
  return (
    <section data-sec="compare" className="sec sec-wide sec-compare">
      <div className="card card-wide">
        <h2>Pick your path.</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Apex alone</th>
                <th className="col-star">Apex + OpenReef ⭐</th>
                <th>Full DIY OpenReef</th>
              </tr>
            </thead>
            <tbody>
              {COMPARE_ROWS.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td>{r.apex}</td>
                  <td className="col-star">{r.both}</td>
                  <td>{r.diy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {showSticker && (
          <div className="throne-reveal">
            {revealed ? (
              <>
                <img
                  className="throne-sticker"
                  src="/avatar/apex-throne.png"
                  alt="The OpenReef guide sitting on an Apex energy bar like a throne, gesturing rudely"
                  onError={() => setStickerOk(false)}
                />
                <p className="throne-caption">
                  Affectionately. Mostly. <button onClick={() => setRevealed(false)}>Hide that</button>
                </p>
              </>
            ) : (
              <button className="btn btn-ghost btn-small" onClick={() => setRevealed(true)}>
                View OpenReef's professional assessment of the competition
              </button>
            )}
          </div>
        )}
        <p className="fine-print">
          UK retail prices checked July 2026 (All Things Aquatic, Charterhouse Aquatics) and
          rounded — they move, so check before you buy. Apex, Fusion, Trident and DOS are
          trademarks of Neptune Systems, named here for factual comparison. Your Apex works fine
          with us. That's the point.
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------ CTA ------------------------------------- */

const FORM_ENDPOINT = ""; // wire to Buttondown/Formspree/Tally before launch

export function Cta() {
  const [email, setEmail] = useState("");
  const [wants, setWants] = useState({ manual: true, beta: true, kits: false });
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const interests = Object.entries(wants)
      .filter(([, v]) => v)
      .map(([k]) => k)
      .join(", ");
    if (FORM_ENDPOINT) {
      try {
        await fetch(FORM_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, interests }),
        });
        setDone(true);
      } catch {
        setDone(false);
      }
    } else {
      window.location.href = `mailto:thecarpyvikings@gmail.com?subject=${encodeURIComponent(
        "OpenReef: manual + beta signup"
      )}&body=${encodeURIComponent(`Email: ${email}\nInterested in: ${interests}`)}`;
      setDone(true);
    }
  };
  return (
    <section data-sec="cta" id="cta" className="sec">
      <div className="card card-center">
        <h2>Get the manual first.</h2>
        <p>
          The manual is being rewritten as OpenReef stabilises — leave an email and it lands in your
          inbox the day it ships. Beta seats go to people who like finding bugs almost as much as
          finding pods.
        </p>
        {done ? (
          <p className="callout">Cheers — you're on the list. Go feed your fish. 🐟</p>
        ) : (
          <form onSubmit={submit} className="cta-form">
            <input
              type="email"
              required
              placeholder="you@reefmail.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-label="Email address"
            />
            <div className="cta-checks">
              <label>
                <input
                  type="checkbox"
                  checked={wants.manual}
                  onChange={(e) => setWants({ ...wants, manual: e.target.checked })}
                />
                The free manual
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={wants.beta}
                  onChange={(e) => setWants({ ...wants, beta: e.target.checked })}
                />
                Private beta seat
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={wants.kits}
                  onChange={(e) => setWants({ ...wants, kits: e.target.checked })}
                />
                Kit waitlist
              </label>
            </div>
            <button className="btn btn-primary" type="submit">
              Count me in
            </button>
          </form>
        )}
        <p className="fine-print">
          Or skip the queue: <a href={GITHUB_URL}>read the source on GitHub</a>. It's all there.
        </p>
      </div>
      <footer className="footer">
        <p>
          Built in the open by one reefer and a soldering iron. © 2026 OpenReef.{" "}
          <a href={GITHUB_URL}>GitHub</a>
        </p>
        <p className="footer-joke">
          No corals were harmed in the making of this website. One Apex had its feelings hurt, but
          it's fine — we gave it a throne.
        </p>
      </footer>
    </section>
  );
}
