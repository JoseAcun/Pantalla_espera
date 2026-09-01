from datetime import datetime, timedelta, timezone
import unittest

from app.analytics import StreamSession, persist_stream_observation
from app.models import StreamState


class FakeAnalyticsRepository:
    """Durable fake: the same instance represents MariaDB across a restart."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.snapshots: list[tuple[int, int, datetime]] = []
        self.categories: list[tuple[int, str]] = []

    def get_or_create_stream_session(self, state, observed_at):
        session = self.sessions.get(state.twitch_stream_id)
        if not session:
            session = {"id": len(self.sessions) + 1, "ended_at": None}
            self.sessions[state.twitch_stream_id] = session
        else:
            # Mirror the database upsert: a confirmed live response reopens
            # this Twitch stream ID after a transient false-offline response.
            session["ended_at"] = None
        return StreamSession(id=session["id"], twitch_stream_id=state.twitch_stream_id)

    def close_open_sessions_for_broadcaster(self, broadcaster_id, ended_at):
        changed = 0
        for session in self.sessions.values():
            if session["ended_at"] is None:
                session["ended_at"] = ended_at
                changed += 1
        return changed

    def last_viewer_snapshot_at(self, stream_session_id):
        values = [captured_at for session_id, _, captured_at in self.snapshots if session_id == stream_session_id]
        return max(values) if values else None

    def record_viewer_snapshot(self, stream_session_id, viewer_count, captured_at):
        self.snapshots.append((stream_session_id, viewer_count, captured_at))

    def record_session_category(self, stream_session_id, category_id, category_name, observed_at, source):
        if self.categories and self.categories[-1] == (stream_session_id, category_id):
            return False
        self.categories.append((stream_session_id, category_id))
        return True


def live_state(stream_id="stream-1", category_id="10"):
    return StreamState(
        twitch_stream_id=stream_id, broadcaster_id="broadcaster-1", broadcaster_login="negai",
        streamer="NEGAI", is_live=True, viewer_count=14,
        stream_started_at=datetime(2026, 9, 1, 20, tzinfo=timezone.utc),
        category_id=category_id, category="Test Game", title="Test stream",
    )


class StreamAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeAnalyticsRepository()
        self.now = datetime(2026, 9, 1, 20, 5, tzinfo=timezone.utc)

    def observe(self, state, seconds=0):
        return persist_stream_observation(self.repository, state, self.now + timedelta(seconds=seconds), 300)

    def test_offline_to_online_creates_one_session_and_initial_snapshot(self) -> None:
        self.observe(StreamState(broadcaster_id="broadcaster-1", is_live=False))
        self.observe(live_state())
        self.assertEqual(len(self.repository.sessions), 1)
        self.assertEqual(self.repository.snapshots, [(1, 14, self.now)])

    def test_same_stream_and_restart_reuse_session(self) -> None:
        self.observe(live_state())
        # No tracker memory exists: this simulates a fresh container using the same DB.
        persist_stream_observation(self.repository, live_state(), self.now + timedelta(seconds=120), 300)
        self.assertEqual(len(self.repository.sessions), 1)
        self.assertEqual(len(self.repository.snapshots), 1)

    def test_online_to_offline_closes_session_and_never_snapshots_offline(self) -> None:
        self.observe(live_state())
        self.observe(StreamState(broadcaster_id="broadcaster-1", is_live=False), 60)
        self.assertEqual(self.repository.sessions["stream-1"]["ended_at"], self.now + timedelta(seconds=60))
        self.assertEqual(len(self.repository.snapshots), 1)

    def test_false_offline_then_same_live_stream_reopens_and_samples_same_session(self) -> None:
        self.observe(live_state())
        self.observe(StreamState(broadcaster_id="broadcaster-1", is_live=False), 60)
        self.observe(live_state(), 300)

        session = self.repository.sessions["stream-1"]
        self.assertEqual(session["id"], 1)
        self.assertIsNone(session["ended_at"])
        self.assertEqual(self.repository.snapshots[-1], (1, 14, self.now + timedelta(seconds=300)))
        self.assertEqual(len(self.repository.snapshots), 2)

    def test_snapshot_interval_is_durable(self) -> None:
        self.observe(live_state())
        self.observe(live_state(), 299)
        self.assertEqual(len(self.repository.snapshots), 1)
        self.observe(live_state(), 300)
        self.assertEqual(len(self.repository.snapshots), 2)

    def test_category_history_records_transitions_only(self) -> None:
        self.observe(live_state(category_id="10"))
        self.observe(live_state(category_id="10"), 60)
        self.observe(live_state(category_id="20"), 120)
        self.assertEqual(self.repository.categories, [(1, "10"), (1, "20")])
