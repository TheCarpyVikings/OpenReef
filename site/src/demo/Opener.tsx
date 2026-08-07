import { useEffect, useRef, useState } from "react";

/*
 * "The 2 AM save" — a 40-second scripted incident played over the live panel
 * before the visitor gets the keys. The same event is seeded in the demo
 * tank's alert history (three nights ago), so the story and the data agree.
 */

const CRITICAL = 27.5;

interface Props {
  onDone: () => void;
}

export default function Opener({ onDone }: Props) {
  const [step, setStep] = useState(0);
  const [temp, setTemp] = useState(26.2);
  const raf = useRef(0);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const finish = () => {
    localStorage.setItem("openreef:demo:opener", "done");
    onDone();
  };

  // Step 1: the heater sticks — temperature climbs 26.2 → 27.9 over ~4 s.
  useEffect(() => {
    if (step !== 1 || reduced) return;
    const t0 = performance.now();
    const climb = (t: number) => {
      const p = Math.min((t - t0) / 4200, 1);
      setTemp(26.2 + (27.9 - 26.2) * (p * p * (3 - 2 * p)));
      if (p < 1) raf.current = requestAnimationFrame(climb);
      else setStep(2);
    };
    raf.current = requestAnimationFrame(climb);
    return () => cancelAnimationFrame(raf.current);
  }, [step, reduced]);

  // Auto-advance the talky steps; the visitor can always click through faster.
  useEffect(() => {
    if (reduced) return;
    const delays: Record<number, number> = { 0: 3200, 2: 4200, 3: 4200 };
    const ms = delays[step];
    if (ms === undefined) return;
    const id = window.setTimeout(() => setStep((s) => s + 1), ms);
    return () => window.clearTimeout(id);
  }, [step, reduced]);

  if (reduced) {
    // No animation: one honest summary card instead of the cinematic.
    return (
      <div className="opener" role="dialog" aria-modal="true">
        <div className="opener-card">
          <p className="opener-clock">02:47</p>
          <p>
            Three nights ago on this tank, a heater relay stuck closed at 2 AM. OpenReef saw
            temperature and heater state disagree and pushed one clear alert — one tap on an
            armed switch cut the heater from bed. The alert history below remembers it all.
          </p>
          <button className="btn btn-primary" onClick={finish}>
            It's your tank now — click anything
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="opener" role="dialog" aria-modal="true" data-step={step}>
      <button className="opener-skip" onClick={finish}>
        Skip intro →
      </button>

      {step === 0 && (
        <div className="opener-card" onClick={() => setStep(1)}>
          <p className="opener-clock">02:47</p>
          <p className="opener-line">You're asleep. The house is dark. The tank hums along.</p>
          <p className="opener-line opener-dim">Then a heater relay sticks closed. It happens — to every brand.</p>
        </div>
      )}

      {step === 1 && (
        <div className="opener-card">
          <p className="opener-clock">02:49</p>
          <div className={`opener-temp ${temp >= CRITICAL ? "is-critical" : ""}`}>
            <span className="opener-temp-value">{temp.toFixed(1)}</span>
            <span className="opener-temp-unit">°C</span>
          </div>
          <p className="opener-line opener-dim">max 27.5 °C · heater: ON</p>
        </div>
      )}

      {step === 2 && (
        <div className="opener-card" onClick={() => setStep(3)}>
          <p className="opener-clock">02:52</p>
          <p className="opener-line">
            OpenReef reads what temperature and heater state say <em>together</em>.
          </p>
          <p className="opener-action">🚨 Critical — 27.9 °C and the heater still says ON</p>
          <p className="opener-line opener-dim">
            Not two numbers on two screens. One conclusion, pushed to your phone.
          </p>
        </div>
      )}

      {step === 3 && (
        <div className="opener-card" onClick={() => setStep(4)}>
          <div className="opener-notification">
            <span className="opener-notification-app">OpenReef · now</span>
            <strong>🚨 Temperature critical — 27.9 °C</strong>
            <span>Heater reads ON. Its switch is armed — cut it from here, one tap.</span>
          </div>
        </div>
      )}

      {step >= 4 && (
        <div className="opener-card">
          <p className="opener-clock">07:30</p>
          <p className="opener-line">
            You wake to a calm tank at 26.1 °C. One push alert, one tap on an outlet you'd
            mapped and armed yourself, back to sleep — and the whole story kept in the history.
          </p>
          <p className="opener-line opener-dim">
            This exact save is seeded in this demo's alert history, three nights back. Go find it.
          </p>
          <button className="btn btn-primary" onClick={finish}>
            It's your tank now — click anything
          </button>
        </div>
      )}

      <div className="opener-progress" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className={i <= step ? "on" : ""} />
        ))}
      </div>
    </div>
  );
}
