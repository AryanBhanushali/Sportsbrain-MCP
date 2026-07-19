"""
Loads all three data sources into SQLite.

Usage:
  python scripts/load_data.py                  # load FBref + Transfermarkt only (fast)
  python scripts/load_data.py --all            # load everything including Statsbomb (slow, ~15 min)
  python scripts/load_data.py --statsbomb-only # load only Statsbomb data

Tables created:
  player_stats              (FBref — 2839 players)
  transfer_values           (Transfermarkt — 508 players)
  value_history             (Transfermarkt — 9764 valuation points)
  statsbomb_matches         (Statsbomb — match metadata)
  statsbomb_player_stats    (Statsbomb — per-player per-match event stats)
"""

import sys
import json
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path("data/sportsbrain.db")
RAW_DIR = Path("data/raw")

# ── FBref column mapping ──────────────────────────────────────────────

FBREF_COLUMN_MAP = {
    "Rk": "rank", "Player": "player", "Nation": "nation", "Pos": "position",
    "Squad": "squad", "Comp": "league", "Age": "age", "Born": "born",
    "MP": "matches_played", "Starts": "starts", "Min": "minutes", "90s": "nineties",
    "Gls": "goals", "Ast": "assists", "G+A": "goals_assists",
    "G-PK": "non_penalty_goals", "PK": "penalty_goals", "PKatt": "penalty_attempts",
    "CrdY": "yellow_cards", "CrdR": "red_cards", "G+A-PK": "non_penalty_ga_per90",
    "Sh": "shots", "SoT": "shots_on_target", "SoT%": "shot_accuracy_pct",
    "Sh/90": "shots_per90", "SoT/90": "shots_on_target_per90",
    "G/Sh": "goals_per_shot", "G/SoT": "goals_per_shot_on_target",
    "PK_stats_shooting": "pk_shooting", "PKatt_stats_shooting": "pkatt_shooting",
    "Crs": "crosses", "TklW": "tackles_won", "Int": "interceptions",
    "Fld": "fouls_drawn", "CrdY_stats_misc": "yellow_cards_misc",
    "CrdR_stats_misc": "red_cards_misc", "2CrdY": "second_yellow_cards",
    "Fls": "fouls_committed", "OG": "own_goals",
    "GA": "goals_against", "GA90": "goals_against_per90",
    "SoTA": "shots_on_target_against", "Saves": "saves", "Save%": "save_pct",
    "W": "gk_wins", "D": "gk_draws", "L": "gk_losses",
    "CS": "clean_sheets", "CS%": "clean_sheet_pct",
    "PKatt_stats_keeper": "pk_faced", "PKA": "pk_against",
    "PKsv": "pk_saved", "PKm": "pk_missed",
}


def clean_nation(val) -> str:
    if pd.isna(val):
        return ""
    parts = str(val).strip().split()
    return parts[-1] if parts else ""


def clean_league(val) -> str:
    if pd.isna(val):
        return ""
    s = str(val).strip()
    for prefix in ("eng ", "es ", "it ", "de ", "fr "):
        if s.lower().startswith(prefix):
            return s[len(prefix):]
    return s


# ── Loaders ───────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def load_player_stats():
    csv_path = RAW_DIR / "players_data_light-2025_2026.csv"
    if not csv_path.exists():
        print(f"SKIP: {csv_path} not found")
        return
    print(f"Loading FBref player stats from {csv_path}...")
    df = pd.read_csv(csv_path)
    df = df.rename(columns=FBREF_COLUMN_MAP)
    df["nation"] = df["nation"].apply(clean_nation)
    df["league"] = df["league"].apply(clean_league)
    df = df.drop(columns=["rank"], errors="ignore")

    conn = get_db()
    df.to_sql("player_stats", conn, index=False, if_exists="replace")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_player ON player_stats(player)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_position ON player_stats(position)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_squad ON player_stats(squad)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_league ON player_stats(league)")
    count = conn.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0]
    conn.close()
    print(f"  {count} players loaded into player_stats")


def load_transfer_values():
    csv_players = RAW_DIR / "transfermarkt_player_values.csv"
    csv_history = RAW_DIR / "transfermarkt_value_history.csv"
    if not csv_players.exists():
        print(f"SKIP: {csv_players} not found")
        return

    print(f"Loading Transfermarkt valuations...")

    # ── Player values ──
    df = pd.read_csv(csv_players)
    # Drop columns with known data quality issues + metadata
    drop_cols = ["position", "position_group", "current_club",
                 "data_source", "dataset_built_at"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

    conn = get_db()
    df.to_sql("transfer_values", conn, index=False, if_exists="replace")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tv_name ON transfer_values(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tv_league ON transfer_values(league_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tv_value ON transfer_values(current_value_eur)")
    count = conn.execute("SELECT COUNT(*) FROM transfer_values").fetchone()[0]
    print(f"  {count} players loaded into transfer_values")

    # ── Value history ──
    if csv_history.exists():
        df_h = pd.read_csv(csv_history)
        df_h.to_sql("value_history", conn, index=False, if_exists="replace")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vh_pid ON value_history(player_id)")
        count_h = conn.execute("SELECT COUNT(*) FROM value_history").fetchone()[0]
        print(f"  {count_h} valuation points loaded into value_history")

    conn.close()


def load_statsbomb_events():
    try:
        from statsbombpy import sb
    except ImportError:
        print("SKIP: statsbombpy not installed (pip install statsbombpy)")
        return

    print("Loading Statsbomb match events (this takes ~10-15 minutes)...")

    # Get available competitions
    comps = sb.competitions()

    # Pick competitions with good Big 5 league overlap
    targets = [
        ("La Liga", "2020/2021"),
        ("1. Bundesliga", "2023/2024"),
    ]

    all_matches = []
    all_player_stats = []

    for comp_name, season_name in targets:
        match = comps[
            (comps["competition_name"] == comp_name) &
            (comps["season_name"] == season_name)
        ]
        if match.empty:
            print(f"  SKIP: {comp_name} {season_name} not found")
            continue

        comp_id = match.iloc[0]["competition_id"]
        season_id = match.iloc[0]["season_id"]

        print(f"  Fetching {comp_name} {season_name}...")
        matches = sb.matches(competition_id=comp_id, season_id=season_id)
        print(f"    {len(matches)} matches found")

        for i, (_, m) in enumerate(matches.iterrows()):
            match_id = m["match_id"]
            home = m["home_team"]
            away = m["away_team"]
            match_date = m.get("match_date", "")
            home_score = m.get("home_score", 0)
            away_score = m.get("away_score", 0)

            all_matches.append({
                "match_id": int(match_id),
                "competition": comp_name,
                "season": season_name,
                "match_date": str(match_date),
                "home_team": home,
                "away_team": away,
                "home_score": int(home_score) if pd.notna(home_score) else 0,
                "away_score": int(away_score) if pd.notna(away_score) else 0,
            })

            # Fetch and aggregate events
            try:
                events = sb.events(match_id=match_id)
            except Exception as e:
                print(f"    WARN: match {match_id} failed: {e}")
                continue

            # Aggregate per player
            for player_name, pev in events.groupby("player"):
                if pd.isna(player_name):
                    continue
                team = pev["team"].iloc[0] if "team" in pev.columns else ""

                stats = {
                    "match_id": int(match_id),
                    "player": str(player_name),
                    "team": str(team) if pd.notna(team) else "",
                    "competition": comp_name,
                    "season": season_name,
                    "goals": 0, "assists": 0, "shots": 0, "shots_on_target": 0,
                    "passes": 0, "passes_completed": 0,
                    "tackles": 0, "tackles_won": 0,
                    "interceptions": 0,
                    "dribbles": 0, "dribbles_completed": 0,
                    "fouls_committed": 0, "fouls_won": 0,
                }

                for _, ev in pev.iterrows():
                    t = ev.get("type", "")
                    if t == "Shot":
                        stats["shots"] += 1
                        outcome = ev.get("shot_outcome", "")
                        if outcome == "Goal":
                            stats["goals"] += 1
                        if outcome in ("Goal", "Saved"):
                            stats["shots_on_target"] += 1
                    elif t == "Pass":
                        stats["passes"] += 1
                        if pd.isna(ev.get("pass_outcome")):
                            stats["passes_completed"] += 1
                        if ev.get("pass_goal_assist") is True:
                            stats["assists"] += 1
                    elif t == "Dribble":
                        stats["dribbles"] += 1
                        if ev.get("dribble_outcome") == "Complete":
                            stats["dribbles_completed"] += 1
                    elif t == "Duel":
                        if ev.get("duel_type") == "Tackle":
                            stats["tackles"] += 1
                            if ev.get("duel_outcome") in ("Won", "Success"):
                                stats["tackles_won"] += 1
                    elif t == "Interception":
                        stats["interceptions"] += 1
                    elif t == "Foul Committed":
                        stats["fouls_committed"] += 1
                    elif t == "Foul Won":
                        stats["fouls_won"] += 1

                all_player_stats.append(stats)

            if (i + 1) % 25 == 0:
                print(f"    {i+1}/{len(matches)} matches processed...")

        print(f"    Done: {len(matches)} matches")

    if not all_matches:
        print("  No Statsbomb data fetched")
        return

    # Write to SQLite
    conn = get_db()
    pd.DataFrame(all_matches).to_sql("statsbomb_matches", conn, index=False, if_exists="replace")
    pd.DataFrame(all_player_stats).to_sql("statsbomb_player_stats", conn, index=False, if_exists="replace")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sb_player ON statsbomb_player_stats(player)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sb_match ON statsbomb_player_stats(match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sb_comp ON statsbomb_player_stats(competition)")

    m_count = conn.execute("SELECT COUNT(*) FROM statsbomb_matches").fetchone()[0]
    ps_count = conn.execute("SELECT COUNT(*) FROM statsbomb_player_stats").fetchone()[0]
    conn.close()
    print(f"  {m_count} matches, {ps_count} player-match rows loaded")


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--statsbomb-only" in args:
        load_statsbomb_events()
    elif "--all" in args:
        load_player_stats()
        load_transfer_values()
        load_statsbomb_events()
    else:
        load_player_stats()
        load_transfer_values()
        print("\nTip: run with --all to also load Statsbomb events (~15 min)")

    print("\nDone. Database at:", DB_PATH)
