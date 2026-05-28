from datetime import datetime, timezone

import requests

from config import ODDS_API_BASE, SPORT, REGIONS, ODDS_FORMAT, V1_MARKETS


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_events(api_key: str) -> list[dict]:
    """Fetch today's MLB event list."""
    url = f"{ODDS_API_BASE}/sports/{SPORT}/events"
    resp = requests.get(url, params={"apiKey": api_key}, timeout=30)
    resp.raise_for_status()
    _log_quota(resp)
    return resp.json()


def _get_event_odds(api_key: str, event_id: str) -> dict:
    """Fetch player prop odds for a single event."""
    url = f"{ODDS_API_BASE}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey":     api_key,
        "regions":    REGIONS,
        "markets":    ",".join(V1_MARKETS),
        "oddsFormat": ODDS_FORMAT,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    _log_quota(resp)
    return resp.json()


def _log_quota(resp: requests.Response) -> None:
    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used", "?")
    print(f"  quota — used: {used}  remaining: {remaining}")


def parse_snapshots(
    events: list[dict],
    pulled_at: str,
    markets: list[str] | None = None,
) -> list[dict]:
    """
    Flatten a list of event objects into rows for props_snapshots insert.
    Accepts the full event list from /events/{id}/odds or a fixture list.

    markets: if None, accept all market keys; if a list, only include those keys.
    """
    rows: list[dict] = []
    for event in events:
        event_id      = event["id"]
        commence_time = event["commence_time"]
        home_team     = event["home_team"]
        away_team     = event["away_team"]
        for book in event.get("bookmakers", []):
            bookmaker_key = book["key"]
            last_update   = book.get("last_update")
            for market in book.get("markets", []):
                if markets is not None and market["key"] not in markets:
                    continue
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "pulled_at":     pulled_at,
                        "event_id":      event_id,
                        "commence_time": commence_time,
                        "home_team":     home_team,
                        "away_team":     away_team,
                        "bookmaker_key": bookmaker_key,
                        "last_update":   last_update,
                        "market_key":    market["key"],
                        "player_name":   outcome.get("description", ""),
                        "selection":     outcome["name"],
                        "point":         float(outcome.get("point", 0.0)),
                        "price":         int(outcome["price"]),
                    })
    return rows


def pull_and_store(api_key: str, conn) -> tuple[str, int]:
    """
    Pull today's MLB player prop odds and store in props_snapshots.
    Returns (pulled_at timestamp, total rows stored).
    """
    from db import insert_snapshots

    pulled_at = _now_utc()
    print(f"  Fetching event list...")
    events = _get_events(api_key)
    print(f"  Found {len(events)} events today")

    all_rows: list[dict] = []
    for event in events:
        event_id = event["id"]
        home     = event.get("home_team", "")
        away     = event.get("away_team", "")
        print(f"  Pulling odds: {away} @ {home}")
        odds_event = _get_event_odds(api_key, event_id)
        rows = parse_snapshots([odds_event], pulled_at)
        all_rows.extend(rows)

    count = insert_snapshots(conn, all_rows)
    return pulled_at, count
