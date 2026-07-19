"""
MCP Server #1: Player Stats
Data source: FBref (Big 5 European Leagues 2025-2026)
Storage: SQLite · Cache: Redis
"""

import sys
import json
import sqlite3
from pathlib import Path
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.cache.redis_client import get_cached, set_cached

DB_PATH = Path(__file__).parent.parent / "data" / "sportsbrain.db"
TTL = 3600

mcp = FastMCP("Player Stats Server")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def format_player(player: dict) -> dict:
    cleaned = {}
    is_keeper = player.get("position", "").startswith("GK")
    keeper_cols = {
        "goals_against", "goals_against_per90", "shots_on_target_against",
        "saves", "save_pct", "gk_wins", "gk_draws", "gk_losses",
        "clean_sheets", "clean_sheet_pct", "pk_faced", "pk_against",
        "pk_saved", "pk_missed",
    }
    for k, v in player.items():
        if v is None:
            continue
        if not is_keeper and k in keeper_cols:
            continue
        cleaned[k] = v
    return cleaned


@mcp.tool()
def get_player_stats(player_name: str) -> str:
    """Get detailed statistics for a player by name.
    Uses case-insensitive partial matching so 'salah' finds 'Mohamed Salah'.
    """
    cached = get_cached("get_player_stats", player_name=player_name.lower())
    if cached:
        return cached

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM player_stats WHERE player LIKE ? ORDER BY minutes DESC",
        (f"%{player_name}%",),
    ).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"error": f"No player found matching '{player_name}'"})

    result = json.dumps([format_player(dict(r)) for r in rows], default=str)
    set_cached("get_player_stats", result, ttl=TTL, player_name=player_name.lower())
    return result


@mcp.tool()
def search_players(
    position: str = "",
    league: str = "",
    squad: str = "",
    nation: str = "",
    min_goals: int = 0,
    min_assists: int = 0,
    max_age: int = 99,
    min_minutes: int = 0,
    limit: int = 20,
) -> str:
    """Search for players matching specified scouting criteria.

    Args:
        position: filter by position, e.g. 'FW', 'MF', 'DF', 'GK'
        league: filter by league, e.g. 'Premier League', 'La Liga'
        squad: filter by club name, e.g. 'Arsenal', 'Barcelona'
        nation: filter by nationality code, e.g. 'ENG', 'BRA'
        min_goals: minimum goals scored
        min_assists: minimum assists
        max_age: maximum age
        min_minutes: minimum minutes played
        limit: max results (default 20)
    """
    cache_params = dict(position=position, league=league, squad=squad, nation=nation,
                        min_goals=min_goals, min_assists=min_assists, max_age=max_age,
                        min_minutes=min_minutes, limit=limit)
    cached = get_cached("search_players", **cache_params)
    if cached:
        return cached

    conditions, params = [], []
    if position:
        conditions.append("position LIKE ?"); params.append(f"%{position}%")
    if league:
        conditions.append("league LIKE ?"); params.append(f"%{league}%")
    if squad:
        conditions.append("squad LIKE ?"); params.append(f"%{squad}%")
    if nation:
        conditions.append("nation LIKE ?"); params.append(f"%{nation}%")
    if min_goals > 0:
        conditions.append("goals >= ?"); params.append(min_goals)
    if min_assists > 0:
        conditions.append("assists >= ?"); params.append(min_assists)
    if max_age < 99:
        conditions.append("age <= ?"); params.append(max_age)
    if min_minutes > 0:
        conditions.append("minutes >= ?"); params.append(min_minutes)

    where = " AND ".join(conditions) if conditions else "1=1"
    query = f"""
        SELECT player, position, squad, league, nation, age,
               matches_played, minutes, goals, assists, goals_assists,
               shots, shots_on_target, shot_accuracy_pct,
               tackles_won, interceptions, crosses, yellow_cards, red_cards
        FROM player_stats WHERE {where}
        ORDER BY goals_assists DESC LIMIT ?
    """
    params.append(limit)

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"error": "No players found matching those criteria"})

    result = json.dumps(rows_to_dicts(rows), default=str)
    set_cached("search_players", result, ttl=TTL, **cache_params)
    return result


@mcp.tool()
def compare_players(player_a: str, player_b: str) -> str:
    """Compare two players side by side."""
    cached = get_cached("compare_players", a=player_a.lower(), b=player_b.lower())
    if cached:
        return cached

    conn = get_db()
    cols = """player, position, squad, league, nation, age,
              matches_played, starts, minutes, nineties,
              goals, assists, goals_assists, non_penalty_goals,
              shots, shots_on_target, shot_accuracy_pct,
              shots_per90, goals_per_shot,
              crosses, tackles_won, interceptions,
              fouls_drawn, fouls_committed, yellow_cards, red_cards"""

    row_a = conn.execute(
        f"SELECT {cols} FROM player_stats WHERE player LIKE ? ORDER BY minutes DESC LIMIT 1",
        (f"%{player_a}%",),
    ).fetchone()
    row_b = conn.execute(
        f"SELECT {cols} FROM player_stats WHERE player LIKE ? ORDER BY minutes DESC LIMIT 1",
        (f"%{player_b}%",),
    ).fetchone()
    conn.close()

    if not row_a:
        return json.dumps({"error": f"Player '{player_a}' not found"})
    if not row_b:
        return json.dumps({"error": f"Player '{player_b}' not found"})

    result = json.dumps({"player_a": dict(row_a), "player_b": dict(row_b)}, default=str)
    set_cached("compare_players", result, ttl=TTL, a=player_a.lower(), b=player_b.lower())
    return result


if __name__ == "__main__":
    mcp.run()
