"""Unit tests for the timelapse tiered-retention ladder (`_timelapse_keepers`).

Pure logic — no Home Assistant needed (HA + voluptuous stubbed via `_ha_stubs`).
The ladder is the only genuinely tricky bit of Phase B, so it gets a real test:
feed synthetic timestamps spanning months and assert the downsampling.

Run standalone (no pytest):   python3 tests/test_timelapse_retention.py
Or with pytest if installed:   pytest tests/
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

keepers = integration._timelapse_keepers

# Daylight window 08:00–22:00 -> midpoint 15:00. The per-bucket keeper is the frame
# closest to this, so a 15:00 frame always wins its day/week/month.
WINDOW_MID = 15 * 60
RETENTION = {"detailDays": 14, "dailyUntilDays": 90, "weeklyUntilDays": 365, "monthlyUntilDays": 0}
NOW = datetime(2026, 6, 3, 15, 0, 0)


def _day(days_ago: int, hour: int = 15, minute: int = 0) -> datetime:
    return (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _frames(days_ago: int, times: list[tuple[int, int]]) -> list[datetime]:
    return [_day(days_ago, h, m) for h, m in times]


def test_recent_frames_all_kept():
    # Inside the detail window (<=14 days): every frame survives.
    frames = _frames(2, [(8, 0), (8, 30), (9, 0), (9, 30), (10, 0)])
    assert keepers(frames, NOW, RETENTION, WINDOW_MID) == set(frames)


def test_daily_tier_keeps_one_per_day_nearest_mid():
    # 30 days old (daily tier): many frames that day -> only the 15:00 one stays.
    frames = _frames(30, [(8, 0), (12, 0), (15, 0), (18, 0), (21, 30)])
    assert keepers(frames, NOW, RETENTION, WINDOW_MID) == {_day(30, 15, 0)}


def test_keeper_is_frame_nearest_window_mid():
    near = _day(30, 14, 45)  # 15 min from midpoint
    far = _day(30, 9, 0)     # 6 h from midpoint
    assert keepers([near, far], NOW, RETENTION, WINDOW_MID) == {near}


def test_weekly_tier_keeps_one_per_iso_week():
    # ~200 days old (weekly tier): one keeper per ISO week.
    frames = [_day(200 - d, 15, 0) for d in range(3)]  # 3 consecutive days
    keep = keepers(frames, NOW, RETENTION, WINDOW_MID)
    weeks = {f.isocalendar()[:2] for f in frames}
    assert len(keep) == len(weeks)


def test_monthly_tier_keeps_one_per_month():
    base = 500
    frames = [_day(base, 15, 0), _day(base - 2, 15, 0), _day(base - 10, 15, 0)]
    keep = keepers(frames, NOW, RETENTION, WINDOW_MID)
    months = {(f.year, f.month) for f in frames}
    assert len(keep) == len(months)


def test_monthly_zero_means_keep_forever():
    very_old = [_day(3000, 15, 0)]
    assert keepers(very_old, NOW, RETENTION, WINDOW_MID) == set(very_old)


def test_finite_monthly_cap_drops_beyond_limit():
    retention = dict(RETENTION, monthlyUntilDays=365)  # nothing older than 365 days
    assert keepers([_day(500, 15, 0)], NOW, retention, WINDOW_MID) == set()


def test_dense_history_collapses_but_keeps_recent_detail():
    # 120 days of 3 frames/day -> far fewer kept, recent detail intact.
    frames: list[datetime] = []
    for d in range(120):
        frames.extend(_frames(d, [(9, 0), (15, 0), (20, 0)]))
    keep = keepers(frames, NOW, RETENTION, WINDOW_MID)
    assert len(keep) < len(frames)
    # A 3-day-old frame is in the detail tier -> must be present.
    assert _day(3, 9, 0) in keep
    # A 60-day-old day (daily tier) collapses to exactly its 15:00 keeper.
    assert _day(60, 15, 0) in keep
    assert _day(60, 9, 0) not in keep


def test_future_skew_frame_is_kept():
    # Clock skew shouldn't drop a "future" frame (age negative -> within detail window).
    future = (NOW + timedelta(hours=2)).replace(second=0, microsecond=0)
    assert future in keepers([future], NOW, RETENTION, WINDOW_MID)


# --- tiny standalone runner (so this works without pytest installed) ---

def _main() -> int:
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
