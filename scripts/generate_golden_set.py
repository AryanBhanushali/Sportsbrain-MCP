"""
Generates a 163-question golden test set from actual database data.
Each question has a known ground truth answer from the DB.

Run: python scripts/generate_golden_set.py
Output: <project_root>/evaluation/golden_test_set.json

Deterministic (fixed random seed) — same questions every run.
"""

import sys
import json
import random
import sqlite3
from pathlib import Path

# ── Absolute paths anchored to the project root ───────────────────────
# scripts/ lives directly under the project root, so parent.parent is root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "sportsbrain.db"
OUTPUT = PROJECT_ROOT / "evaluation" / "golden_test_set.json"

random.seed(42)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def generate_player_stat_questions(conn, count=60):
    """Questions about specific player stats — single fact lookups."""
    questions = []

    # Top scorers per league
    leagues = ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"]
    for league in leagues:
        rows = conn.execute(
            """SELECT player, squad, goals, assists, age, position, matches_played, minutes
               FROM player_stats WHERE league = ? AND goals > 3
               ORDER BY goals DESC LIMIT 8""",
            (league,),
        ).fetchall()
        for r in rows:
            p = dict(r)
            questions.append({
                "question": f"How many goals does {p['player']} have this season?",
                "ground_truth": f"{p['player']} has {p['goals']} goals this season, playing for {p['squad']} in the {league}.",
                "category": "player_stats_lookup",
            })
            if len(questions) >= count // 3:
                break

    # Position and team lookups
    sample_players = conn.execute(
        """SELECT player, squad, league, position, age, goals, assists
           FROM player_stats WHERE minutes > 1000
           ORDER BY RANDOM() LIMIT 30"""
    ).fetchall()
    for r in sample_players:
        p = dict(r)
        q_type = random.choice(["position", "team", "age"])
        if q_type == "position":
            questions.append({
                "question": f"What position does {p['player']} play?",
                "ground_truth": f"{p['player']} plays {p['position']} for {p['squad']}.",
                "category": "player_stats_lookup",
            })
        elif q_type == "team":
            questions.append({
                "question": f"Which team does {p['player']} play for?",
                "ground_truth": f"{p['player']} plays for {p['squad']} in the {p['league']}.",
                "category": "player_stats_lookup",
            })
        else:
            questions.append({
                "question": f"How old is {p['player']}?",
                "ground_truth": f"{p['player']} is {int(p['age'])} years old, playing for {p['squad']}.",
                "category": "player_stats_lookup",
            })
        if len(questions) >= count:
            break

    return questions[:count]


def generate_search_questions(conn, count=45):
    """Questions that require searching/filtering players."""
    questions = []
    leagues = ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"]

    for league in leagues:
        # Top scorers
        top = conn.execute(
            "SELECT player, goals FROM player_stats WHERE league = ? ORDER BY goals DESC LIMIT 3",
            (league,),
        ).fetchall()
        top_str = ", ".join([f"{r['player']} ({r['goals']})" for r in top])
        questions.append({
            "question": f"Who are the top 3 scorers in {league} this season?",
            "ground_truth": f"The top 3 scorers in {league} are: {top_str}.",
            "category": "search_query",
        })

        # Young players with goals
        young = conn.execute(
            """SELECT player, goals, age, squad FROM player_stats
               WHERE league = ? AND age <= 23 AND goals >= 5
               ORDER BY goals DESC LIMIT 3""",
            (league,),
        ).fetchall()
        if young:
            y_str = ", ".join([f"{r['player']} ({r['goals']} goals, age {int(r['age'])})" for r in young])
            questions.append({
                "question": f"Which {league} players under 23 have scored 5 or more goals?",
                "ground_truth": f"Young {league} scorers with 5+ goals include: {y_str}.",
                "category": "search_query",
            })

        # By position
        for pos, pos_name in [("FW", "forwards"), ("MF", "midfielders"), ("DF", "defenders")]:
            top_pos = conn.execute(
                """SELECT player, goals, assists, squad FROM player_stats
                   WHERE league = ? AND position LIKE ? AND minutes > 500
                   ORDER BY goals_assists DESC LIMIT 3""",
                (league, f"%{pos}%"),
            ).fetchall()
            if top_pos:
                p_str = ", ".join([f"{r['player']} ({r['goals']}G, {r['assists']}A)" for r in top_pos])
                questions.append({
                    "question": f"Who are the best {pos_name} in {league} by goal contributions?",
                    "ground_truth": f"Top {pos_name} in {league} by goal contributions: {p_str}.",
                    "category": "search_query",
                })

    # Cross-league searches
    young_scorers = conn.execute(
        """SELECT player, league, goals, age, squad FROM player_stats
           WHERE age <= 21 AND goals >= 5 ORDER BY goals DESC LIMIT 5"""
    ).fetchall()
    if young_scorers:
        ys_str = ", ".join([f"{r['player']} ({r['league']}, {r['goals']} goals)" for r in young_scorers])
        questions.append({
            "question": "Who are the highest-scoring players under 21 across all Big 5 leagues?",
            "ground_truth": f"Top scorers under 21 across Big 5 leagues: {ys_str}.",
            "category": "search_query",
        })

    return questions[:count]


def generate_transfer_questions(conn, count=40):
    """Questions about market valuations."""
    questions = []

    players = conn.execute(
        """SELECT name, age, nationality, league_name, current_value_eur,
                  current_value_tier, peak_value_eur, trajectory, peak_club
           FROM transfer_values ORDER BY current_value_eur DESC LIMIT 50"""
    ).fetchall()

    for r in players:
        p = dict(r)
        val_m = int(p["current_value_eur"] / 1_000_000)
        peak_m = int(p["peak_value_eur"] / 1_000_000)

        q_type = random.choice(["value", "trajectory", "peak"])
        if q_type == "value":
            questions.append({
                "question": f"What is {p['name']}'s current market value?",
                "ground_truth": f"{p['name']} is currently valued at €{val_m}M ({p['current_value_tier']}). Trajectory: {p['trajectory']}.",
                "category": "transfer_lookup",
            })
        elif q_type == "trajectory":
            questions.append({
                "question": f"Is {p['name']}'s market value rising or declining?",
                "ground_truth": f"{p['name']}'s trajectory is '{p['trajectory']}'. Current: €{val_m}M, Peak: €{peak_m}M at {p['peak_club']}.",
                "category": "transfer_lookup",
            })
        else:
            questions.append({
                "question": f"What was {p['name']}'s peak market value?",
                "ground_truth": f"{p['name']}'s peak value was €{peak_m}M at {p['peak_club']}. Current: €{val_m}M.",
                "category": "transfer_lookup",
            })
        if len(questions) >= count:
            break

    # Value range searches
    for league in ["Premier League", "La Liga"]:
        undervalued = conn.execute(
            """SELECT name, current_value_eur, age FROM transfer_values
               WHERE league_name = ? AND age <= 23 AND current_value_eur <= 30000000
               ORDER BY current_value_eur DESC LIMIT 3""",
            (league,),
        ).fetchall()
        if undervalued:
            u_str = ", ".join([f"{r['name']} (€{int(r['current_value_eur']/1e6)}M)" for r in undervalued])
            questions.append({
                "question": f"Which {league} players under 23 are valued at €30M or less?",
                "ground_truth": f"Young {league} players valued ≤€30M: {u_str}.",
                "category": "transfer_search",
            })

    return questions[:count]


def generate_comparison_questions(conn, count=30):
    """Player comparison questions."""
    questions = []

    pairs = conn.execute(
        """SELECT a.player as p1, b.player as p2,
                  a.goals as g1, b.goals as g2,
                  a.assists as a1, b.assists as a2,
                  a.squad as s1, b.squad as s2
           FROM player_stats a, player_stats b
           WHERE a.league = 'Premier League' AND b.league = 'Premier League'
             AND a.goals > 8 AND b.goals > 8 AND a.player < b.player
             AND a.minutes > 1500 AND b.minutes > 1500
           ORDER BY RANDOM() LIMIT 15"""
    ).fetchall()

    for r in pairs:
        p = dict(r)
        questions.append({
            "question": f"Compare {p['p1']} and {p['p2']} this season.",
            "ground_truth": f"{p['p1']} ({p['s1']}): {p['g1']} goals, {p['a1']} assists. {p['p2']} ({p['s2']}): {p['g2']} goals, {p['a2']} assists.",
            "category": "comparison",
        })

    # Cross-league comparisons
    fw_players = conn.execute(
        """SELECT player, squad, league, goals, assists FROM player_stats
           WHERE position LIKE '%FW%' AND goals > 10
           ORDER BY goals DESC LIMIT 10"""
    ).fetchall()
    for i in range(0, min(len(fw_players) - 1, 15), 2):
        a, b = dict(fw_players[i]), dict(fw_players[i + 1])
        questions.append({
            "question": f"Who is the better scorer, {a['player']} or {b['player']}?",
            "ground_truth": f"{a['player']} has {a['goals']} goals for {a['squad']}, {b['player']} has {b['goals']} goals for {b['squad']}.",
            "category": "comparison",
        })

    return questions[:count]


def generate_multisource_questions(conn, count=15):
    """Questions requiring both stats and transfer data."""
    questions = []

    # Players in both datasets
    overlap = conn.execute(
        """SELECT ps.player, ps.goals, ps.assists, ps.squad, ps.league, ps.age,
                  tv.current_value_eur, tv.trajectory
           FROM player_stats ps
           JOIN transfer_values tv ON ps.player LIKE '%' || tv.name || '%'
           WHERE ps.goals > 5 AND ps.minutes > 1000
           ORDER BY ps.goals DESC LIMIT 20"""
    ).fetchall()

    for r in overlap:
        p = dict(r)
        val_m = int(p["current_value_eur"] / 1e6)
        questions.append({
            "question": f"Give me {p['player']}'s stats and market value.",
            "ground_truth": f"{p['player']} ({p['squad']}): {p['goals']} goals, {p['assists']} assists. Valued at €{val_m}M, trajectory: {p['trajectory']}.",
            "category": "multi_source",
        })
        if len(questions) >= count:
            break

    return questions[:count]


def generate_edge_cases(count=10):
    """Edge cases and error handling."""
    return [
        {"question": "Tell me about a player named Xyznotreal.", "ground_truth": "No player found matching that name.", "category": "edge_case"},
        {"question": "How many goals does the goalkeeper Alisson have?", "ground_truth": "Alisson is a goalkeeper; goalkeepers typically have 0 goals.", "category": "edge_case"},
        {"question": "What is the market value of a random League Two player?", "ground_truth": "Transfer data only covers Big 5 league players. No data available.", "category": "edge_case"},
        {"question": "Who scored the most goals in the Championship?", "ground_truth": "Data only covers Big 5 European leagues. No Championship data.", "category": "edge_case"},
        {"question": "Compare Messi and Ronaldo this season.", "ground_truth": "Messi and Ronaldo are not in the Big 5 leagues 2025-2026 dataset.", "category": "edge_case"},
        {"question": "Which Premier League player has exactly 7 goals?", "ground_truth": "Look up players with exactly 7 goals in the database.", "category": "edge_case"},
        {"question": "Find me defenders who score goals in Ligue 1.", "ground_truth": "Search for DF position in Ligue 1 with goals > 0.", "category": "edge_case"},
        {"question": "What is Erling Haaland's transfer history?", "ground_truth": "Haaland's value history is available from Transfermarkt data.", "category": "edge_case"},
        {"question": "Who are the oldest players still playing in Serie A?", "ground_truth": "Search Serie A players sorted by age descending.", "category": "edge_case"},
        {"question": "Find left-backs under 25 with 5+ assists in any league.", "ground_truth": "Search for DF position players with assists >= 5 and age <= 25.", "category": "edge_case"},
    ][:count]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        print("Load it first: python scripts/load_data.py --all")
        sys.exit(1)

    conn = db()
    all_questions = []

    print("Generating golden test set...")
    stats_qs = generate_player_stat_questions(conn, 60)
    print(f"  Player stats lookups: {len(stats_qs)}")
    all_questions.extend(stats_qs)

    search_qs = generate_search_questions(conn, 45)
    print(f"  Search queries: {len(search_qs)}")
    all_questions.extend(search_qs)

    transfer_qs = generate_transfer_questions(conn, 40)
    print(f"  Transfer market: {len(transfer_qs)}")
    all_questions.extend(transfer_qs)

    comparison_qs = generate_comparison_questions(conn, 30)
    print(f"  Comparisons: {len(comparison_qs)}")
    all_questions.extend(comparison_qs)

    multi_qs = generate_multisource_questions(conn, 15)
    print(f"  Multi-source: {len(multi_qs)}")
    all_questions.extend(multi_qs)

    edge_qs = generate_edge_cases(10)
    print(f"  Edge cases: {len(edge_qs)}")
    all_questions.extend(edge_qs)

    conn.close()

    # Shuffle to mix categories
    random.shuffle(all_questions)

    # Number them
    for i, q in enumerate(all_questions):
        q["id"] = i + 1

    # Save (ensure the evaluation/ directory exists)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_questions, f, indent=2, ensure_ascii=False)

    print(f"\nTotal: {len(all_questions)} questions -> {OUTPUT}")

    # Category summary
    cats = {}
    for q in all_questions:
        cats[q["category"]] = cats.get(q["category"], 0) + 1
    for cat, count in sorted(cats.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()