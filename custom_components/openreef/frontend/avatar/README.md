# OpenReef guide avatar — drop-in art

The onboarding tour looks for the guide character's poses here. Each pose falls back to a themed
emoji placeholder until its PNG exists; the panel auto-switches per pose (no code change, just a
HACS update + HA restart). Source images may have a plain background — the build step that prepared
these cut the white out to transparent and downscaled to 512px.

## Files (exact names)

| File | Pose | Used for |
|---|---|---|
| `idle.png` | relaxed wave | welcome + safety steps |
| `point.png` | presenting / pointing to his side | Reef Health + "tap for trends" |
| `smug.png` | arms crossed, confident grin | Dosing Advisor (the anti-Apex flex) |
| `facepalm.png` | palm to forehead | Attention (mocking Apex's cryptic UX) |
| `celebrate.png` | both arms up, cheering | tour finish |
| `apex-throne.png` | the brand gag image | tour finale, Cheeky mode only |

## Spec

- **1024 × 1024**, transparent PNG (alpha).
- **Full body**, centred, head ~8% from top, feet ~6% from bottom — **identical framing, scale and
  camera across all poses** (so swapping a pose never makes the character jump/resize).
- No background, no baked ground shadow, no text.
- Served at `/openreef_static/avatar/<pose>.png`.

See the image-generation prompt kit and tour script in `docs/onboarding-script.md`.
