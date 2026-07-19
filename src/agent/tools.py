"""
LangChain tool definitions for the scouting agent.
Each tool queries SQLite with Redis caching — same data as the MCP servers.
"""

import json
import sqlite3
from pathlib import Path
from langchain_core.tools import tool
from src.cache.redis_client import get_cached, set_cached

DB_PATH = Path(__file__).parent.parent.parent / "data" / "sportsbrain.db"
STATS_TTL = 3600
TRANSFER_TTL = 86400


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Player Stats tools (FBref) ───────────────────────────────────────

@tool
def search_players(
    position: str = "",
    league: str = "",
    nation: str = "",
    squad: str = "",
    min_goals: int = 0,
    min_assists: int = 0,
    max_age: int = 99,
    min_minutes: int = 0,
    limit: int = 15,
) -> str:
    """Search for players matching scouting criteria across Big 5 European leagues.

    Args:
        position: 'FW' for forwards, 'MF' for midfielders, 'DF' for defenders, 'GK' for keepers
        league: 'Premier League', 'La Liga', 'Serie A', 'Bundesliga', or 'Ligue 1'
        nation: nationality code like 'ENG', 'BRA', 'FRA', 'ESP', 'GER'
        squad: club name like 'Arsenal', 'Barcelona', 'Bayern Munich'
        min_goals: minimum goals this season
        min_assists: minimum assists this season
        max_age: maximum player age
        min_minutes: minimum minutes played (filter small samples)
        limit: max results to return
    """
    params = dict(position=position, league=league, nation=nation, squad=squad,
                  min_goals=min_goals, min_assists=min_assists, max_age=max_age,
                  min_minutes=min_minutes, limit=limit)
    cached = get_cached("agent_search_players", **params)
    if cached:
        return cached

    conditions, qparams = [], []
    if position:
        conditions.append("position LIKE ?"); qparams.append(f"%{position}%")
    if league:
        conditions.append("league LIKE ?"); qparams.append(f"%{league}%")
    if nation:
        conditions.append("nation LIKE ?"); qparams.append(f"%{nation}%")
    if squad:
        conditions.append("squad LIKE ?"); qparams.append(f"%{squad}%")
    if min_goals > 0:
        conditions.append("goals >= ?"); qparams.append(min_goals)
    if min_assists > 0:
        conditions.append("assists >= ?"); qparams.append(min_assists)
    if max_age < 99:
        conditions.append("age <= ?"); qparams.append(max_age)
    if min_minutes > 0:
        conditions.append("minutes >= ?"); qparams.append(min_minutes)

    where = " AND ".join(conditions) if conditions else "1=1"
    conn = _db()
    rows = conn.execute(f"""
        SELECT player, position, squad, league, nation, age,
               matches_played, minutes, goals, assists, goals_assists,
               shots_on_target, tackles_won, interceptions, yellow_cards
        FROM player_stats WHERE {where}
        ORDER BY goals_assists DESC LIMIT ?
    """, qparams + [limit]).fetchall()
    conn.close()

    result = json.dumps([dict(r) for r in rows], default=str) if rows else json.dumps([])
    set_cached("agent_search_players", result, ttl=STATS_TTL, **params)
    return result


@tool
def get_player_stats(player_name: str) -> str:
    """Get full season statistics for a specific player by name.

    Args:
        player_name: full or partial player name, e.g. 'Salah', 'Haaland', 'Mbappe'
    """
    cached = get_cached("agent_player_stats", name=player_name.lower())
    if cached:
        return cached

    conn = _db()
    rows = conn.execute(
        """SELECT player, position, squad, league, nation, age,
                  matches_played, starts, minutes, goals, assists, goals_assists,
                  non_penalty_goals, shots, shots_on_target, shot_accuracy_pct,
                  shots_per90, goals_per_shot, crosses, tackles_won, interceptions,
                  fouls_drawn, fouls_committed, yellow_cards, red_cards
           FROM player_stats WHERE player LIKE ? ORDER BY minutes DESC""",
        (f"%{player_name}%",),
    ).fetchall()
    conn.close()

    result = json.dumps([dict(r) for r in rows], default=str) if rows else json.dumps({"error": "Player not found"})
    set_cached("agent_player_stats", result, ttl=STATS_TTL, name=player_name.lower())
    return result


@tool
def compare_players(player_a: str, player_b: str) -> str:
    """Compare two players side by side on key stats.

    Args:
        player_a: first player name
        player_b: second player name
    """
    conn = _db()
    cols = """player, position, squad, league, age,
              matches_played, minutes, goals, assists, goals_assists,
              shots, shots_on_target, shots_per90, goals_per_shot,
              tackles_won, interceptions, yellow_cards"""

    a = conn.execute(f"SELECT {cols} FROM player_stats WHERE player LIKE ? ORDER BY minutes DESC LIMIT 1",
                     (f"%{player_a}%",)).fetchone()
    b = conn.execute(f"SELECT {cols} FROM player_stats WHERE player LIKE ? ORDER BY minutes DESC LIMIT 1",
                     (f"%{player_b}%",)).fetchone()
    conn.close()

    if not a:
        return json.dumps({"error": f"'{player_a}' not found"})
    if not b:
        return json.dumps({"error": f"'{player_b}' not found"})
    return json.dumps({"player_a": dict(a), "player_b": dict(b)}, default=str)


# ── Transfer Market tools (Transfermarkt) ─────────────────────────────

@tool
def get_player_valuation(player_name: str) -> str:
    """Get market valuation for a player: current value, peak value, and career trajectory.

    Args:
        player_name: full or partial player name
    """
    cached = get_cached("agent_valuation", name=player_name.lower())
    if cached:
        return cached

    conn = _db()
    rows = conn.execute(
        """SELECT name, age, nationality, league_name,
                  current_value_eur, current_value_tier,
                  peak_value_eur, peak_value_tier, peak_club,
                  trajectory, age_at_peak, career_span_years
           FROM transfer_values WHERE name LIKE ?
           ORDER BY current_value_eur DESC""",
        (f"%{player_name}%",),
    ).fetchall()
    conn.close()

    result = json.dumps([dict(r) for r in rows], default=str) if rows else json.dumps({"error": "Not in transfer database"})
    set_cached("agent_valuation", result, ttl=TRANSFER_TTL, name=player_name.lower())
    return result


@tool
def search_by_value(
    min_value_eur: int = 0,
    max_value_eur: int = 999_999_999,
    league: str = "",
    max_age: int = 99,
    limit: int = 15,
) -> str:
    """Search for players by market value range.

    Args:
        min_value_eur: minimum value in EUR, e.g. 20000000 for 20M euros
        max_value_eur: maximum value in EUR, e.g. 50000000 for 50M euros
        league: 'Premier League', 'La Liga', 'Serie A', 'Bundesliga', 'Ligue 1'
        max_age: maximum age
        limit: max results
    """
    params = dict(min_v=min_value_eur, max_v=max_value_eur, league=league, max_age=max_age, limit=limit)
    cached = get_cached("agent_search_value", **params)
    if cached:
        return cached

    conditions = ["current_value_eur >= ?", "current_value_eur <= ?"]
    qparams: list = [min_value_eur, max_value_eur]
    if league:
        conditions.append("league_name LIKE ?"); qparams.append(f"%{league}%")
    if max_age < 99:
        conditions.append("age <= ?"); qparams.append(max_age)

    conn = _db()
    rows = conn.execute(f"""
        SELECT name, age, nationality, league_name,
               current_value_eur, current_value_tier, peak_value_eur, trajectory, peak_club
        FROM transfer_values WHERE {" AND ".join(conditions)}
        ORDER BY current_value_eur DESC LIMIT ?
    """, qparams + [limit]).fetchall()
    conn.close()

    result = json.dumps([dict(r) for r in rows], default=str) if rows else json.dumps([])
    set_cached("agent_search_value", result, ttl=TRANSFER_TTL, **params)
    return result


# ── Match Events tools (Statsbomb) ────────────────────────────────────

@tool
def get_player_match_stats(player_name: str) -> str:
    """Get detailed match event statistics for a player from Statsbomb data.
    Covers La Liga 2020/2021 and Bundesliga 2023/2024.
    Includes: goals, assists, shots, passes, tackles, dribbles per competition.

    Args:
        player_name: full or partial player name
    """
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT player, team, competition, season,
                      COUNT(*) as matches,
                      SUM(goals) as goals, SUM(assists) as assists,
                      SUM(shots) as shots, SUM(passes_completed) as passes_completed,
                      SUM(tackles_won) as tackles_won, SUM(interceptions) as interceptions,
                      SUM(dribbles_completed) as dribbles_completed
               FROM statsbomb_player_stats WHERE player LIKE ?
               GROUP BY player, team, competition, season
               ORDER BY goals DESC""",
            (f"%{player_name}%",),
        ).fetchall()
    except Exception:
        conn.close()
        return json.dumps({"error": "Statsbomb data not loaded"})
    conn.close()

    return json.dumps([dict(r) for r in rows], default=str) if rows else json.dumps({"error": "No match event data found"})


@tool
def get_competition_top_performers(
    competition: str = "La Liga",
    stat: str = "goals",
    limit: int = 10,
) -> str:
    """Get top performers in a competition for a specific stat.

    Args:
        competition: 'La Liga' or '1. Bundesliga'
        stat: 'goals', 'assists', 'shots', 'passes_completed', 'tackles_won', 'interceptions', 'dribbles_completed'
        limit: how many players to return
    """
    valid = {"goals", "assists", "shots", "passes_completed", "tackles_won", "interceptions", "dribbles_completed"}
    if stat not in valid:
        return json.dumps({"error": f"Invalid stat. Choose: {sorted(valid)}"})

    conn = _db()
    try:
        rows = conn.execute(f"""
            SELECT player, team, COUNT(*) as matches, SUM({stat}) as total,
                   ROUND(CAST(SUM({stat}) AS FLOAT) / COUNT(*), 2) as per_match
            FROM statsbomb_player_stats WHERE competition LIKE ?
            GROUP BY player, team HAVING total > 0
            ORDER BY total DESC LIMIT ?
        """, (f"%{competition}%", limit)).fetchall()
    except Exception:
        conn.close()
        return json.dumps({"error": "Statsbomb data not loaded"})
    conn.close()

    return json.dumps([dict(r) for r in rows], default=str) if rows else json.dumps([])


# ── Export all tools ──────────────────────────────────────────────────

ALL_TOOLS = [
    search_players,
    get_player_stats,
    compare_players,
    get_player_valuation,
    search_by_value,
    get_player_match_stats,
    get_competition_top_performers,
]
