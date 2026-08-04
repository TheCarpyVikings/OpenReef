import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { depthAt, reef } from "./reef";
import type { Tone } from "./reef";
import { GITHUB_URL, TICKER } from "./copy";
import Buddy from "./ui/Buddy";
import { Compare, Cta, Diy, Features, Hero, Lights, Meet, Sandbox, Spawning } from "./ui/Sections";

const Scene = lazy(() => import("./scene/Scene"));

function supportsWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function DepthGauge() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const y = depthAt(reef.scroll);
      if (ref.current) ref.current.textContent = `${Math.max(0, -y).toFixed(1)} m`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return (
    <div className="depth-gauge" aria-hidden="true">
      <span>DEPTH</span>
      <div ref={ref}>0.0 m</div>
    </div>
  );
}

function PriceTicker({ scroll, hidden }: { scroll: number; hidden: boolean }) {
  const items = TICKER.filter((i) => scroll >= i.t);
  if (!items.length || hidden) return null;
  const total = items.reduce((s, i) => s + i.amt, 0);
  const last = items[items.length - 1];
  return (
    <div className="ticker" aria-hidden="true">
      <div className="ticker-row">
        <span>The other quote so far</span>
        <strong>~£{total.toLocaleString()}</strong>
      </div>
      <div className="ticker-item">+ {last.label}</div>
      <div className="ticker-row ticker-us">
        <span>OpenReef software</span>
        <strong>£0.00</strong>
      </div>
    </div>
  );
}

export default function App() {
  const [tone, setTone] = useState<Tone>(
    () => (localStorage.getItem("openreef:tone") as Tone) || "cheeky"
  );
  const [hasApex, setHasApex] = useState<boolean | null>(() => {
    const v = localStorage.getItem("openreef:apex");
    return v === null ? null : v === "yes";
  });
  const [active, setActive] = useState("hero");
  const [score, setScore] = useState(92);
  const [scroll, setScroll] = useState(0);
  const [konami, setKonami] = useState(false);
  // ?og=1 renders a chrome-free frame for the social-card screenshot.
  const ogMode = useMemo(() => new URLSearchParams(window.location.search).has("og"), []);

  const show3d = useMemo(() => {
    if (typeof window === "undefined") return false;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    if (!supportsWebGL()) return false;
    const nav = navigator as Navigator & { deviceMemory?: number };
    reef.lowPower =
      (nav.deviceMemory !== undefined && nav.deviceMemory <= 4) ||
      navigator.hardwareConcurrency <= 4;
    return true;
  }, []);

  useEffect(() => {
    localStorage.setItem("openreef:tone", tone);
  }, [tone]);
  useEffect(() => {
    if (hasApex !== null) localStorage.setItem("openreef:apex", hasApex ? "yes" : "no");
  }, [hasApex]);

  useEffect(() => {
    let ticking = false;
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        const max = document.documentElement.scrollHeight - window.innerHeight;
        const t = max > 0 ? window.scrollY / max : 0;
        reef.scroll = t;
        setScroll(t);
        const mid = window.innerHeight / 2;
        let current = "hero";
        document.querySelectorAll<HTMLElement>("section[data-sec]").forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.top <= mid && r.bottom >= mid) current = el.dataset.sec || current;
        });
        setActive(current);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Konami code → the reef spawns, wherever you are.
  useEffect(() => {
    const seq = [
      "ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown",
      "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight",
      "b", "a",
    ];
    let i = 0;
    let timer: ReturnType<typeof setTimeout>;
    const onKey = (e: KeyboardEvent) => {
      i = e.key === seq[i] ? i + 1 : e.key === seq[0] ? 1 : 0;
      if (i === seq.length) {
        i = 0;
        reef.spawnPulse += 1;
        setKonami(true);
        clearTimeout(timer);
        timer = setTimeout(() => setKonami(false), 7000);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(timer);
    };
  }, []);

  return (
    <>
      {show3d ? (
        <Suspense fallback={<div className="static-bg" />}>
          <Scene />
        </Suspense>
      ) : (
        <div className="static-bg" />
      )}

      {!ogMode && (
        <nav className="topnav">
          <a className="topnav-brand" href="#top">
            <img src="/logo.png" alt="" /> OpenReef
          </a>
          <div className="topnav-links">
            <a href="/demo/">Live demo</a>
            <a href={GITHUB_URL}>GitHub</a>
            <a className="btn btn-primary btn-small" href="#cta">
              Join the beta
            </a>
          </div>
        </nav>
      )}

      {show3d && !ogMode && <DepthGauge />}
      {!ogMode && <PriceTicker scroll={scroll} hidden={active === "cta" || active === "hero"} />}

      <main id="top">
        <Hero />
        <Meet tone={tone} setTone={setTone} hasApex={hasApex} setHasApex={setHasApex} />
        <Sandbox score={score} setScore={setScore} />
        <Lights />
        <Spawning />
        <Features />
        <Diy tone={tone} />
        <Compare tone={tone} hasApex={hasApex} />
        <Cta />
      </main>

      {!ogMode && (
        <Buddy section={active} tone={tone} hasApex={hasApex} score={score} konami={konami} />
      )}
    </>
  );
}
