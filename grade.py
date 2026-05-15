import re
import unicodedata
from datetime import datetime, timezone

import requests


def normalize_name(name: str) -> str:
    """Lowercase, strip accents, remove all non-alpha characters."""
    nfkd  = unicodedata.normalize("NFKD", name)
    ascii = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", ascii.lower())


def grade_outcome(selection: str, point: float, actual_stat: float) -> str:
    if selection == "Over":
        if actual_stat > point:  return "WIN"
        if actual_stat < point:  return "LOSS"
        return "PUSH"
    # Under
    if actual_stat < point:  return "WIN"
    if actual_stat > point:  return "LOSS"
    return "PUSH"


def calc_profit(result: str, price: int) -> float:
    if result == "PUSH": return  0.0
    if result == "LOSS": return -1.0
    # WIN
    if price > 0: return  price / 100.0
    return 100.0 / abs(price)


def _fetch_boxscore(game_pk: int) -> dict:
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"  Boxscore fetch failed for gamePk={game_pk}: {exc}")
        return {}


def get_game_results(date_str: str) -> list[dict]:
    """
    Returns one dict per player per market with keys:
    player_name, player_name_norm, market_key, stat_value

    date_str: 'YYYY-MM-DD'
    Only includes games with status 'Final'.
    """
    url = "https://statsapi.mlb.com/api/v1/schedule"
    resp = requests.get(url, params={"sportId": 1, "date": date_str}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results: list[dict] = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {}).get("abstractGameState", "")
            if status != "Final":
                continue
            game_pk  = game["gamePk"]
            boxscore = _fetch_boxscore(game_pk)
            if not boxscore:
                continue
            for side in ("home", "away"):
                players = boxscore.get("teams", {}).get(side, {}).get("players", {})
                for pdata in players.values():
                    person    = pdata.get("person", {})
                    full_name = person.get("fullName", "").strip()
                    if not full_name:
                        continue
                    norm  = normalize_name(full_name)
                    stats = pdata.get("stats", {})

                    bstats  = stats.get("batting",  {})
                    pstats  = stats.get("pitching", {})

                    _extracts = [
                        (bstats.get("hits"),          "batter_hits"),
                        (bstats.get("totalBases"),    "batter_total_bases"),
                        (bstats.get("homeRuns"),      "batter_home_runs"),
                        (bstats.get("rbi"),           "batter_rbis"),
                        (bstats.get("runs"),          "batter_runs_scored"),
                        (bstats.get("stolenBases"),   "batter_stolen_bases"),
                        (bstats.get("baseOnBalls"),   "batter_walks"),
                        (pstats.get("strikeOuts"),    "pitcher_strikeouts"),
                        (pstats.get("hits"),          "pitcher_hits_allowed"),
                        (pstats.get("earnedRuns"),    "pitcher_earned_runs"),
                        (pstats.get("baseOnBalls"),   "pitcher_walks"),
                        (pstats.get("outs"),          "pitcher_outs"),
                    ]
                    for val, mkt in _extracts:
                        if val is not None:
                            results.append({
                                "player_name":      full_name,
                                "player_name_norm": norm,
                                "market_key":       mkt,
                                "stat_value":       int(val),
                            })
    return results


def grade_pending_picks(conn, results_date: str) -> int:
    """
    Grade all PENDING picks for results_date using live MLB Stats API.
    Returns count of picks graded.
    """
    from db import get_pending_picks, update_pick_result

    print(f"  Fetching MLB results for {results_date}...")
    results = get_game_results(results_date)
    print(f"  Got {len(results)} player stat lines")

    index: dict[tuple[str, str], float] = {}
    for r in results:
        index[(r["player_name_norm"], r["market_key"])] = r["stat_value"]

    pending = get_pending_picks(conn, results_date)
    graded  = 0
    for pick in pending:
        key = (normalize_name(pick["player_name"]), pick["market_key"])
        if key not in index:
            continue
        actual  = index[key]
        result  = grade_outcome(pick["selection"], pick["point"], actual)
        profit  = calc_profit(result, pick["bovada_price"])
        update_pick_result(conn, pick["id"], result, actual, profit)
        graded += 1

    return graded
