"""
MCP Server #3: Match Events
Data source: Statsbomb Open Data
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
TTL = 86400  # 24 hours — historical event data doesn't change

mcp = FastMCP("Match Events Server")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, name: str) -> bool:
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return r is not None


@mcp.tool()
def get_player_match_stats(player_name: str) -> str:
    """Get aggregated match event statistics for a player.
    Covers La Liga 2020/2021 and Bundesliga 2023/2024.
    """
    cached = get_cached("get_player_match_stats", player_name=player_name.lower())
    if cached:
        return cached

    conn = get_db()
    if not table_exists(conn, "statsbomb_player_stats"):
        conn.close()
        return json.dumps({"error": "Statsbomb data not loaded. Run: python scripts/load_data.py --all"})

    rows = conn.execute(
        """SELECT player, team, competition, season,
                  COUNT(*) as matches,
                  SUM(goals) as goals, SUM(assists) as assists,
                  SUM(shots) as shots, SUM(shots_on_target) as shots_on_target,
                  SUM(passes) as passes, SUM(passes_completed) as passes_completed,
                  SUM(tackles) as tackles, SUM(tackles_won) as tackles_won,
                  SUM(interceptions) as interceptions,
                  SUM(dribbles) as dribbles, SUM(dribbles_completed) as dribbles_completed,
                  SUM(fouls_committed) as fouls_committed, SUM(fouls_won) as fouls_won
           FROM statsbomb_player_stats WHERE player LIKE ?
           GROUP BY player, team, competition, season
           ORDER BY goals DESC""",
        (f"%{player_name}%",),
    ).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"error": f"No match data found for '{player_name}'"})

    results = []
    for r in rows:
        d = dict(r)
        if d["passes"] > 0:
            d["pass_completion_pct"] = round(d["passes_completed"] / d["passes"] * 100, 1)
        results.append(d)

    result = json.dumps(results, default=str)
    set_cached("get_player_match_stats", result, ttl=TTL, player_name=player_name.lower())
    return result


@mcp.tool()
def get_match_summary(home_team: str, away_team: str = "") -> str:
    """Get player-level event stats for a specific match.
    Search by home team, optionally narrow with away team.
    """
    cached = get_cached("get_match_summary", home=home_team.lower(), away=away_team.lower())
    if cached:
        return cached

    conn = get_db()
    if not table_exists(conn, "statsbomb_matches"):
        conn.close()
        return json.dumps({"error": "Statsbomb data not loaded. Run: python scripts/load_data.py --all"})

    if away_team:
        match = conn.execute(
            """SELECT match_id, home_team, away_team, home_score, away_score,
                      match_date, competition, season
               FROM statsbomb_matches
               WHERE home_team LIKE ? AND away_team LIKE ?
               ORDER BY match_date DESC LIMIT 1""",
            (f"%{home_team}%", f"%{away_team}%"),
        ).fetchone()
    else:
        match = conn.execute(
            """SELECT match_id, home_team, away_team, home_score, away_score,
                      match_date, competition, season
               FROM statsbomb_matches
               WHERE home_team LIKE ? OR away_team LIKE ?
               ORDER BY match_date DESC LIMIT 1""",
            (f"%{home_team}%", f"%{home_team}%"),
        ).fetchone()

    if not match:
        conn.close()
        return json.dumps({"error": f"No match found for '{home_team}' vs '{away_team}'"})

    players = conn.execute(
        """SELECT player, team, goals, assists, shots, shots_on_target,
                  passes, passes_completed, tackles, tackles_won,
                  interceptions, dribbles, dribbles_completed,
                  fouls_committed, fouls_won
           FROM statsbomb_player_stats WHERE match_id = ?
           ORDER BY goals DESC, assists DESC, shots DESC""",
        (match["match_id"],),
    ).fetchall()
    conn.close()

    result = json.dumps({"match": dict(match), "players": [dict(p) for p in players]}, default=str)
    set_cached("get_match_summary", result, ttl=TTL, home=home_team.lower(), away=away_team.lower())
    return result


@mcp.tool()
def get_competition_top_performers(
    competition: str = "La Liga",
    stat: str = "goals",
    limit: int = 15,
) -> str:
    """Get top performers in a competition by a specific stat.

    Args:
        competition: 'La Liga' or '1. Bundesliga'
        stat: 'goals', 'assists', 'shots', 'passes_completed',
              'tackles_won', 'interceptions', 'dribbles_completed'
        limit: number of results (default 15)
    """
    valid_stats = {
        "goals", "assists", "shots", "shots_on_target",
        "passes", "passes_completed", "tackles", "tackles_won",
        "interceptions", "dribbles", "dribbles_completed",
        "fouls_committed", "fouls_won",
    }
    if stat not in valid_stats:
        return json.dumps({"error": f"Invalid stat. Choose from: {sorted(valid_stats)}"})

    cached = get_cached("top_performers", comp=competition, stat=stat, limit=limit)
    if cached:
        return cached

    conn = get_db()
    if not table_exists(conn, "statsbomb_player_stats"):
        conn.close()
        return json.dumps({"error": "Statsbomb data not loaded. Run: python scripts/load_data.py --all"})

    rows = conn.execute(
        f"""SELECT player, team, COUNT(*) as matches,
                   SUM({stat}) as total,
                   ROUND(CAST(SUM({stat}) AS FLOAT) / COUNT(*), 2) as per_match
            FROM statsbomb_player_stats WHERE competition LIKE ?
            GROUP BY player, team HAVING total > 0
            ORDER BY total DESC LIMIT ?""",
        (f"%{competition}%", limit),
    ).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"error": f"No data for '{competition}'"})

    result = json.dumps({"competition": competition, "stat": stat,
                         "leaderboard": [dict(r) for r in rows]}, default=str)
    set_cached("top_performers", result, ttl=TTL, comp=competition, stat=stat, limit=limit)
    return result


if __name__ == "__main__":
    mcp.run()
