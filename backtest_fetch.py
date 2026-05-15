import requests
from config import SPORT, REGIONS, ODDS_FORMAT, ALL_PROP_MARKETS
from pull_props import parse_snapshots

_HIST_BASE = "https://api.the-odds-api.com/v4/historical"
_TIMEOUT   = 30


def _log_quota(resp: requests.Response) -> None:
    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used", "?")
    print(f"    quota — used: {used}  remaining: {remaining}")


def fetch_historical_events(
    api_key: str,
    date_str: str,
    odds_time: str = "12:00:00",
) -> list[dict]:
    """
    Fetch MLB events for date_str (YYYY-MM-DD) as of odds_time UTC.
    Returns list of event dicts: {id, commence_time, home_team, away_team}.
    """
    url = f"{_HIST_BASE}/sports/{SPORT}/events"
    resp = requests.get(
        url,
        params={"apiKey": api_key, "date": f"{date_str}T{odds_time}Z"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    _log_quota(resp)
    return resp.json().get("data", [])


def fetch_historical_event_odds(
    api_key: str,
    event_id: str,
    date_iso: str,
    markets: list[str] | None = None,
) -> dict:
    """
    Fetch player prop odds for a single event at date_iso (full ISO timestamp).
    Returns event dict with bookmakers (same structure as live endpoint).

    markets: if None, defaults to ALL_PROP_MARKETS.
    """
    if markets is None:
        markets = ALL_PROP_MARKETS
    url = f"{_HIST_BASE}/sports/{SPORT}/events/{event_id}/odds"
    resp = requests.get(
        url,
        params={
            "apiKey":     api_key,
            "date":       date_iso,
            "regions":    REGIONS,
            "markets":    ",".join(markets),
            "oddsFormat": ODDS_FORMAT,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    _log_quota(resp)
    return resp.json()["data"]


def pull_historical_snapshots(
    api_key: str,
    date_str: str,
    odds_time: str = "12:00:00",
    markets: list[str] | None = None,
) -> tuple[str, list[dict]]:
    """
    Pull all player prop snapshots for date_str.
    Returns (pulled_at_iso, list_of_snapshot_rows).
    pulled_at_iso is the ISO timestamp used (date + odds_time).

    markets: if None, defaults to ALL_PROP_MARKETS.
    """
    if markets is None:
        markets = ALL_PROP_MARKETS
    date_iso = f"{date_str}T{odds_time}Z"
    events = fetch_historical_events(api_key, date_str, odds_time)
    print(f"  {date_str}: {len(events)} events found")

    all_rows: list[dict] = []
    for event in events:
        event_id = event["id"]
        home     = event.get("home_team", "")
        away     = event.get("away_team", "")
        print(f"    {away} @ {home}")
        odds_event = fetch_historical_event_odds(api_key, event_id, date_iso, markets=markets)
        rows = parse_snapshots([odds_event], date_iso)
        all_rows.extend(rows)

    return date_iso, all_rows
