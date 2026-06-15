"""MLB-specific enum vocabulary, kept in the MLB package (not the shared enums).

`MLBStatType` is the MLB player-prop stat vocabulary. Its string values follow the
same uppercase convention as the shared `StatType` (`PTS`/`REB`/`AST`) and are the
exact values persisted in `parlay_legs.stat_type` for MLB legs.

Each member maps to a column on `MLBPlayerGameStat` (the stat-reader strategy uses
this mapping to read the reported value):

    HITS               -> mlb_player_game_stats.hits
    TOTAL_BASES        -> mlb_player_game_stats.total_bases
    RBI                -> mlb_player_game_stats.rbi
    RUNS               -> mlb_player_game_stats.runs
    STRIKEOUTS_PITCHER -> mlb_player_game_stats.strikeouts_pitcher
"""

from enum import StrEnum


class MLBStatType(StrEnum):
    HITS = "HITS"
    TOTAL_BASES = "TOTAL_BASES"
    RBI = "RBI"
    RUNS = "RUNS"
    STRIKEOUTS_PITCHER = "STRIKEOUTS_PITCHER"
