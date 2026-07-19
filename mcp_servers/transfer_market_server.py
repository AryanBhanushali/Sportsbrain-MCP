"""
MCP Server #2: Transfer Market
Data source: Transfermarkt (508 Big 5 league players)
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
TTL = 86400  # 24 hours — valuations change slowly

mcp = FastMCP("Transfer Market Server")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def get_player_valuation(player_name: str) -> str:
    """Get market valuation details for a player.
    Returns current value, peak value, trajectory, and career stats.
    """
    cached = get_cached("get_player_valuation", player_name=player_name.lower())
    if cached:
        return cached

    conn = get_db()
    rows = conn.execute(
        """SELECT name, age, nationality, league_name,
                  current_value_eur, current_value_tier,
                  peak_value_eur, peak_value_tier, peak_date, peak_club,
                  age_at_peak, career_span_years, trajectory, is_at_peak,
                  value_cagr, post_peak_decline_pct, num_clubs_career
           FROM transfer_values WHERE name LIKE ?
           ORDER BY current_value_eur DESC""",
        (f"%{player_name}%",),
    ).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"error": f"No player found matching '{player_name}' in transfer data"})

    result = json.dumps([dict(r) for r in rows], default=str)
    set_cached("get_player_valuation", result, ttl=TTL, player_name=player_name.lower())
    return result


@mcp.tool()
def search_by_value(
    min_value_eur: int = 0,
    max_value_eur: int = 999_999_999,
    league: str = "",
    max_age: int = 99,
    trajectory: str = "",
    limit: int = 20,
) -> str:
    """Search for players by market value range and other criteria.

    Args:
        min_value_eur: minimum current market value in EUR (e.g. 20000000 for 20M)
        max_value_eur: maximum current market value in EUR
        league: filter by league, e.g. 'Premier League', 'La Liga'
        max_age: maximum age
        trajectory: 'rising star', 'growing', 'stable', 'declining', 'falling sharply'
        limit: max results (default 20)
    """
    cache_params = dict(min_v=min_value_eur, max_v=max_value_eur, league=league,
                        max_age=max_age, trajectory=trajectory, limit=limit)
    cached = get_cached("search_by_value", **cache_params)
    if cached:
        return cached

    conditions = ["current_value_eur >= ?", "current_value_eur <= ?"]
    params: list = [min_value_eur, max_value_eur]
    if league:
        conditions.append("league_name LIKE ?"); params.append(f"%{league}%")
    if max_age < 99:
        conditions.append("age <= ?"); params.append(max_age)
    if trajectory:
        conditions.append("trajectory LIKE ?"); params.append(f"%{trajectory}%")

    where = " AND ".join(conditions)
    query = f"""
        SELECT name, age, nationality, league_name,
               current_value_eur, current_value_tier,
               peak_value_eur, trajectory, peak_club
        FROM transfer_values WHERE {where}
        ORDER BY current_value_eur DESC LIMIT ?
    """
    params.append(limit)

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"error": "No players found matching those criteria"})

    result = json.dumps([dict(r) for r in rows], default=str)
    set_cached("search_by_value", result, ttl=TTL, **cache_params)
    return result


@mcp.tool()
def get_value_history(player_name: str) -> str:
    """Get the full market value history timeline for a player."""
    cached = get_cached("get_value_history", player_name=player_name.lower())
    if cached:
        return cached

    conn = get_db()
    player = conn.execute(
        "SELECT player_id, name FROM transfer_values WHERE name LIKE ? LIMIT 1",
        (f"%{player_name}%",),
    ).fetchone()

    if not player:
        conn.close()
        return json.dumps({"error": f"No player found matching '{player_name}'"})

    rows = conn.execute(
        """SELECT valuation_date, value_eur, value_display, club, age_at_date
           FROM value_history WHERE player_id = ?
           ORDER BY year DESC, month DESC""",
        (player["player_id"],),
    ).fetchall()
    conn.close()

    result = json.dumps({"player": player["name"], "history": [dict(r) for r in rows]}, default=str)
    set_cached("get_value_history", result, ttl=TTL, player_name=player_name.lower())
    return result


if __name__ == "__main__":
    mcp.run()
