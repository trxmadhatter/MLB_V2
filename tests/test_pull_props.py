import json
from pathlib import Path
from pull_props import parse_snapshots

FIXTURE = Path(__file__).parent / "fixtures" / "sample_odds.json"


def load_fixture() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestParseSnapshots:
    def test_returns_list_of_dicts(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        assert isinstance(rows, list)
        assert len(rows) > 0

    def test_row_has_required_fields(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        required = {
            "pulled_at", "event_id", "commence_time", "home_team", "away_team",
            "bookmaker_key", "last_update", "market_key", "player_name",
            "selection", "point", "price",
        }
        for row in rows:
            assert required.issubset(row.keys()), f"Missing keys in: {row.keys()}"

    def test_event_id_preserved(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        assert all(r["event_id"] == "evt_abc123" for r in rows)

    def test_bovada_rows_present(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        bovada_rows = [r for r in rows if r["bookmaker_key"] == "bovada"]
        assert len(bovada_rows) == 2

    def test_player_name_from_description(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        names = {r["player_name"] for r in rows}
        assert "Gerrit Cole" in names
        assert "Aaron Judge" in names

    def test_only_v1_markets_included(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        from config import V1_MARKETS
        for row in rows:
            assert row["market_key"] in V1_MARKETS

    def test_pulled_at_set_on_all_rows(self):
        events = load_fixture()
        ts = "2026-05-14T09:00:00Z"
        rows = parse_snapshots(events, pulled_at=ts)
        assert all(r["pulled_at"] == ts for r in rows)

    def test_point_is_float(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        for row in rows:
            assert isinstance(row["point"], float)

    def test_price_is_int(self):
        events = load_fixture()
        rows = parse_snapshots(events, pulled_at="2026-05-14T05:00:00Z")
        for row in rows:
            assert isinstance(row["price"], int)
