# SportsBrain Evaluation Results

**Total questions**: 163  
**Average latency**: 25.8s per query  
**Evaluation method**: RAGAS (Faithfulness + Answer Relevancy, qwen3:8b judge)  
**Agent**: LangGraph ReAct, tools loaded from 3 MCP servers (stdio)  
**LLM**: qwen3:8b via Ollama (local)

## Scores

| Metric                    | Value  |
| ------------------------- | ------ |
| faithfulness              | 0.6603 |
| answer_relevancy          | 0.8322 |
| faithfulness_scored_n     | 159    |
| answer_relevancy_scored_n | 162    |
| samples_attempted         | 162    |

## Per-Category Breakdown

| Category            | Count | Errors | Avg Latency | Avg Tool Calls |
| ------------------- | ----- | ------ | ----------- | -------------- |
| comparison          | 20    | 0      | 43.5s       | 2.3            |
| edge_case           | 10    | 0      | 23.5s       | 1.1            |
| multi_source        | 15    | 0      | 26.4s       | 2.0            |
| player_stats_lookup | 52    | 0      | 17.3s       | 1.0            |
| search_query        | 26    | 1      | 46.2s       | 1.6            |
| transfer_lookup     | 40    | 0      | 15.1s       | 1.0            |

## Sample Results (first 10)

### Q1: How old is Ísak Jóhannesson?

**Status**: OK | **Latency**: 24.5s | **Tools used**: 1  
**Answer preview**: I don't have access to Ísak Jóhannesson's age through the available tools. My player databases (FBref, Transfermarkt, Statsbomb) don't show any entries for this player. You might want to check official club websites or Icelandic league sources for his age and career information.  
**Expected**: Ísak Jóhannesson is 22 years old, playing for Köln.

### Q2: What is Enzo Fernández's current market value?

**Status**: OK | **Latency**: 14.71s | **Tools used**: 1  
**Answer preview**: Enzo Fernández's current market value is **€85 million** (Elite tier: 50-100M). His peak value was also **€85 million** at Chelsea FC when he was 22 years old.

Key insights:

- **Trajectory**: "Growing" (though he's already at his peak value)
- **Age**: 25 years old (played 4.83 seasons professiona  
  **Expected**: Enzo Fernández is currently valued at €85M (Elite (50-100M)). Trajectory: growing.

### Q3: How many goals does Vedat Muriqi have this season?

**Status**: OK | **Latency**: 14.52s | **Tools used**: 1  
**Answer preview**: Vedat Muriqi has scored **23 goals** in La Liga this season (2024/25), with 18 non-penalty goals and 5 penalties. He's been a key striker for Rayo Vallecano (Mallorca), averaging 0.62 goals per 90 minutes. His shot conversion rate is strong at 43.9% (50 shots on target from 114 total shots).  
**Expected**: Vedat Muriqi has 23 goals this season, playing for Mallorca in the La Liga.

### Q4: Give me Mason Greenwood's stats and market value.

**Status**: OK | **Latency**: 28.11s | **Tools used**: 2  
**Answer preview**: **Mason Greenwood's Stats & Market Value**

### 🏆 **Player Stats (Ligue 1 2024/25)**

- **Club**: Marseille (Ligue 1)
- **Age**: 23
- **League Appearances**: 32 matches (29 starts), 2,462 minutes
- **Goals**: 16 (10 non-penalty, 6 penalties)
- **Assists**: 7
- **Shot Accuracy**: 41.4% (  
  **Expected**: Mason Greenwood (Marseille): 16 goals, 7 assists. Valued at €50M, trajectory: growing.

### Q5: How old is David Carmo?

**Status**: OK | **Latency**: 19.11s | **Tools used**: 1  
**Answer preview**: David Carmo is **26 years old** (born in 1999). He plays as a defender for Oviedo in La Liga.  
**Expected**: David Carmo is 26 years old, playing for Oviedo.

### Q6: What position does Fer López play?

**Status**: OK | **Latency**: 15.89s | **Tools used**: 1  
**Answer preview**: Fer López primarily plays as a **midfielder (MF)**, with the ability to operate as a **forward (FW)** when needed. At Celta Vigo (La Liga), he's listed as a "MF,FW," while at Wolves (Premier League), he's registered as a "MF." His versatility allows him to contribute in both central midfield and att  
**Expected**: Fer López plays MF,FW for Celta Vigo.

### Q7: Who is the better scorer, Kylian Mbappé or Vedat Muriqi?

**Status**: OK | **Latency**: 37.24s | **Tools used**: 2  
**Answer preview**: **Kylian Mbappé vs. Vedat Muriqi: Scoring Efficiency & Output**

### **Key Stats**

- **Mbappé (26, Real Madrid, La Liga):**
  - **Goals:** 25 (0.76 G/90 mins)
  - **Shots:** 146 (43.2% accuracy)
  - **Goals per shot on target:** 0.27
  - **Penalties:** 8 scored (9 attempts)

- **Muriqi (31, Mallorca  
  **Expected\*\*: Kylian Mbappé has 25 goals for Real Madrid, Vedat Muriqi has 23 goals for Mallorca.

### Q8: How many goals does the goalkeeper Alisson have?

**Status**: OK | **Latency**: 12.14s | **Tools used**: 1  
**Answer preview**: Alisson the goalkeeper has **0 goals** in the Premier League this season. The data shows he's a goalkeeper (GK) for Liverpool with no goals scored. There's also a player named Alisson Santos in Serie A, but he's a midfielder/forward (MF,FW) with 4 goals, which is unrelated to the goalkeeper position  
**Expected**: Alisson is a goalkeeper; goalkeepers typically have 0 goals.

### Q9: What was Jude Bellingham's peak market value?

**Status**: OK | **Latency**: 12.79s | **Tools used**: 1  
**Answer preview**: Jude Bellingham's peak market value was **€180 million** (World Class tier), achieved on **December 21, 2023** while playing for **Real Madrid** at age 20. His current valuation is €160 million, showing an 11.1% decline since his peak. This makes him a "growing" trajectory player with a 9.66% CAGR o  
**Expected**: Jude Bellingham's peak value was €180M at Real Madrid. Current: €160M.

### Q10: What position does Víctor Chust play?

**Status**: OK | **Latency**: 11.93s | **Tools used**: 1  
**Answer preview**: Víctor Chust is not listed in the search results for Real Betis players in La Liga. The players found include forwards like Cucho and Antony, but Chust's name does not appear. Could you double-check the spelling of his name or provide additional details (e.g., position, league, or club)? I can refin  
**Expected**: Víctor Chust plays DF for Elche.
