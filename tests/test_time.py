"""Tests for application record timestamp helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from app.infra.storage.session_io import from_iso, to_iso, utc_now


def test_session_record_time_helpers_use_shanghai_timezone() -> None:
    assert to_iso(datetime(2026, 5, 8, 0, 0, tzinfo=UTC)) == "2026-05-08T08:00:00+08:00"
    assert from_iso("2026-05-08T00:00:00Z").isoformat() == "2026-05-08T08:00:00+08:00"
    now = utc_now()
    offset = now.utcoffset()
    assert now.tzinfo is not None
    assert offset is not None
    assert offset.total_seconds() == 8 * 60 * 60
