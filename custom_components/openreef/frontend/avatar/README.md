# OpenReef guide avatar — drop-in art

The onboarding tour looks for the guide character's poses here. Until these files exist, the tour
shows a themed emoji placeholder; the moment a real `idle.png` is present, the panel auto-switches
to the PNGs (no code change, just a HACS update + HA restart).

## Files (exact names)

| File | Pose | Used for |
|---|---|---|
| `idle.png` | relaxed wave | welcome, attention, safety steps |
| `point.png` | presenting / pointing to his side | Reef Health, "tap for trends" |
| `smug.png` | arms crossed, confident grin | Dosing Advisor |
| `facepalm.png` | palm to forehead | (reserved — Phase 3 reactions) |
| `celebrate.png` | both arms up, cheering | tour finish, grade A |

## Spec

- **1024 × 1024**, transparent PNG (alpha).
- **Full body**, centred, head ~8% from top, feet ~6% from bottom — **identical framing, scale and
  camera across all poses** (so swapping a pose never makes the character jump/resize).
- No background, no baked ground shadow, no text.
- Served at `/openreef_static/avatar/<pose>.png`.

See the image-generation prompt kit and tour script in `docs/onboarding-script.md`.
