"""
BACKTESTING ENGINE
Analyzes signal history to find:
- Win rate per pattern
- Win rate per macro condition
- Win rate per pump stage
- Best performing coins
- Optimal holding periods
- Average R/R achieved vs planned
Feeds results back into confidence scoring.
"""

import json
import os
from datetime import datetime, timezone
from utils.formatter import fmt_pct

SIGNALS_FILE = os.path.join(os.path.dirname(__file__), "../data/signals.json")
BACKTEST_FILE = os.path.join(os.path.dirname(__file__), "../data/backtest_results.json")


def _load_signals() -> list:
    if not os.path.exists(SIGNALS_FILE):
        return []
    try:
        with open(SIGNALS_FILE) as f:
            data = json.load(f)
            return data.get("signals", [])
    except Exception:
        return []


def _save_backtest(results: dict):
    os.makedirs(os.path.dirname(BACKTEST_FILE), exist_ok=True)
    with open(BACKTEST_FILE, "w") as f:
        json.dump(results, f, indent=2)


def _load_backtest() -> dict:
    if not os.path.exists(BACKTEST_FILE):
        return {}
    try:
        with open(BACKTEST_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def run_backtest(user_id: int = None) -> dict:
    """
    Full backtest analysis on signal history.
    If user_id provided, analyzes that user's signals only.
    """
    signals = _load_signals()
    if user_id:
        signals = [s for s in signals if s.get("user_id") == user_id]

    closed = [s for s in signals if s.get("outcome") not in ["OPEN", None]]

    if len(closed) < 5:
        return {
            "error": f"Need at least 5 closed signals for backtest. Currently have {len(closed)}.",
            "total_signals": len(signals),
            "closed_signals": len(closed),
        }

    results = {
        "total_signals": len(signals),
        "closed_signals": len(closed),
        "open_signals": len(signals) - len(closed),
        "by_pattern": {},
        "by_stage": {},
        "by_macro": {},
        "by_coin": {},
        "by_confidence": {},
        "overall": {},
        "best_setup": None,
        "worst_setup": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── OVERALL STATS ─────────────────────────────────────────────────────────
    wins = [s for s in closed if s["outcome"] in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]]
    losses = [s for s in closed if s["outcome"] == "STOPPED"]
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    pnls = [s.get("pnl_pct", 0) for s in closed if s.get("pnl_pct") is not None]
    avg_win = sum(p for p in pnls if p > 0) / max(len([p for p in pnls if p > 0]), 1)
    avg_loss = sum(p for p in pnls if p < 0) / max(len([p for p in pnls if p < 0]), 1)
    total_pnl = sum(pnls)
    profit_factor = abs(sum(p for p in pnls if p > 0)) / max(abs(sum(p for p in pnls if p < 0)), 0.01)

    results["overall"] = {
        "win_rate": round(win_rate, 1),
        "total_wins": len(wins),
        "total_losses": len(losses),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "total_pnl_pct": round(total_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round((win_rate/100 * avg_win) + ((1-win_rate/100) * avg_loss), 2),
    }

    # ── BY PATTERN ────────────────────────────────────────────────────────────
    pattern_groups = {}
    for s in closed:
        p = s.get("pattern", "Unknown")
        if p not in pattern_groups:
            pattern_groups[p] = []
        pattern_groups[p].append(s)

    for pattern, sigs in pattern_groups.items():
        w = len([s for s in sigs if s["outcome"] in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]])
        l = len([s for s in sigs if s["outcome"] == "STOPPED"])
        wr = w / len(sigs) * 100 if sigs else 0
        pnl = sum(s.get("pnl_pct", 0) or 0 for s in sigs)
        results["by_pattern"][pattern] = {
            "trades": len(sigs),
            "wins": w,
            "losses": l,
            "win_rate": round(wr, 1),
            "total_pnl": round(pnl, 2),
        }

    # ── BY PUMP STAGE ─────────────────────────────────────────────────────────
    stage_groups = {}
    for s in closed:
        stage = str(s.get("stage", "?"))
        if stage not in stage_groups:
            stage_groups[stage] = []
        stage_groups[stage].append(s)

    for stage, sigs in stage_groups.items():
        w = len([s for s in sigs if s["outcome"] in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]])
        wr = w / len(sigs) * 100 if sigs else 0
        pnl = sum(s.get("pnl_pct", 0) or 0 for s in sigs)
        results["by_stage"][f"Stage {stage}"] = {
            "trades": len(sigs),
            "wins": w,
            "win_rate": round(wr, 1),
            "total_pnl": round(pnl, 2),
        }

    # ── BY MACRO GATE ─────────────────────────────────────────────────────────
    for gate in ["GREEN", "YELLOW", "RED"]:
        gate_sigs = [s for s in closed if s.get("macro_gate") == gate]
        if not gate_sigs:
            continue
        w = len([s for s in gate_sigs if s["outcome"] in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]])
        wr = w / len(gate_sigs) * 100
        pnl = sum(s.get("pnl_pct", 0) or 0 for s in gate_sigs)
        results["by_macro"][gate] = {
            "trades": len(gate_sigs),
            "wins": w,
            "win_rate": round(wr, 1),
            "total_pnl": round(pnl, 2),
        }

    # ── BY COIN ───────────────────────────────────────────────────────────────
    coin_groups = {}
    for s in closed:
        coin = s.get("ticker", "?")
        if coin not in coin_groups:
            coin_groups[coin] = []
        coin_groups[coin].append(s)

    for coin, sigs in coin_groups.items():
        if len(sigs) < 2:
            continue
        w = len([s for s in sigs if s["outcome"] in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]])
        wr = w / len(sigs) * 100
        pnl = sum(s.get("pnl_pct", 0) or 0 for s in sigs)
        results["by_coin"][coin] = {
            "trades": len(sigs),
            "wins": w,
            "win_rate": round(wr, 1),
            "total_pnl": round(pnl, 2),
        }

    # ── BEST AND WORST SETUPS ─────────────────────────────────────────────────
    all_combos = {}
    for s in closed:
        key = f"{s.get('pattern','?')} | Stage {s.get('stage','?')} | {s.get('macro_gate','?')}"
        if key not in all_combos:
            all_combos[key] = []
        all_combos[key].append(s)

    combo_stats = {}
    for key, sigs in all_combos.items():
        if len(sigs) < 2:
            continue
        w = len([s for s in sigs if s["outcome"] in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]])
        wr = w / len(sigs) * 100
        combo_stats[key] = {"win_rate": wr, "trades": len(sigs)}

    if combo_stats:
        best_key = max(combo_stats, key=lambda k: combo_stats[k]["win_rate"])
        worst_key = min(combo_stats, key=lambda k: combo_stats[k]["win_rate"])
        results["best_setup"] = {**combo_stats[best_key], "setup": best_key}
        results["worst_setup"] = {**combo_stats[worst_key], "setup": worst_key}

    _save_backtest(results)
    return results


def get_pattern_confidence_boost(pattern: str, stage: int, macro_gate: str) -> float:
    """
    Returns confidence multiplier based on historical performance.
    1.0 = no change, 1.3 = 30% boost, 0.7 = 30% reduction.
    Used by signal engine to adjust confidence dynamically.
    """
    results = _load_backtest()
    if not results:
        return 1.0

    pattern_data = results.get("by_pattern", {}).get(pattern, {})
    stage_data = results.get("by_stage", {}).get(f"Stage {stage}", {})
    macro_data = results.get("by_macro", {}).get(macro_gate, {})

    boosts = []

    if pattern_data.get("trades", 0) >= 3:
        wr = pattern_data.get("win_rate", 50)
        boosts.append(wr / 50)  # 50% win rate = 1.0 multiplier

    if stage_data.get("trades", 0) >= 3:
        wr = stage_data.get("win_rate", 50)
        boosts.append(wr / 50)

    if macro_data.get("trades", 0) >= 3:
        wr = macro_data.get("win_rate", 50)
        boosts.append(wr / 50)

    if not boosts:
        return 1.0

    avg_boost = sum(boosts) / len(boosts)
    return round(max(0.5, min(2.0, avg_boost)), 2)


def format_backtest_report(results: dict, user_id: int = None) -> str:
    if results.get("error"):
        return (
            f"BACKTEST ENGINE\n\n"
            f"{results['error']}\n\n"
            f"Total signals logged: {results.get('total_signals', 0)}\n"
            f"Closed signals: {results.get('closed_signals', 0)}\n\n"
            f"Keep running /scan to generate signals.\n"
            f"Bot tracks outcomes automatically."
        )

    overall = results.get("overall", {})
    lines = [
        "BACKTEST RESULTS",
        f"{'━'*35}",
        f"",
        f"OVERALL PERFORMANCE:",
        f"  Total signals  : {results['closed_signals']}",
        f"  Win rate       : {overall.get('win_rate', 0):.1f}%",
        f"  Avg win        : +{overall.get('avg_win_pct', 0):.1f}%",
        f"  Avg loss       : {overall.get('avg_loss_pct', 0):.1f}%",
        f"  Total PnL      : {overall.get('total_pnl_pct', 0):+.1f}%",
        f"  Profit factor  : {overall.get('profit_factor', 0):.2f}x",
        f"  Expectancy     : {overall.get('expectancy', 0):+.2f}% per trade",
        f"",
    ]

    # By macro gate
    if results.get("by_macro"):
        lines.append("BY MACRO GATE:")
        for gate, data in results["by_macro"].items():
            emoji = "✅" if gate == "GREEN" else ("⚠️" if gate == "YELLOW" else "🔴")
            lines.append(f"  {emoji} {gate}: {data['win_rate']:.0f}% WR ({data['trades']} trades)")
        lines.append("")

    # By stage
    if results.get("by_stage"):
        lines.append("BY PUMP STAGE:")
        for stage, data in sorted(results["by_stage"].items()):
            lines.append(f"  {stage}: {data['win_rate']:.0f}% WR ({data['trades']} trades, {data['total_pnl']:+.1f}% PnL)")
        lines.append("")

    # By pattern (top 5)
    if results.get("by_pattern"):
        sorted_patterns = sorted(
            results["by_pattern"].items(),
            key=lambda x: x[1]["win_rate"],
            reverse=True
        )
        lines.append("TOP PATTERNS:")
        for pattern, data in sorted_patterns[:5]:
            if data["trades"] >= 2:
                lines.append(f"  {pattern}: {data['win_rate']:.0f}% WR ({data['trades']} trades)")
        lines.append("")

    # Best coin
    if results.get("by_coin"):
        best_coin = max(results["by_coin"].items(), key=lambda x: x[1]["win_rate"])
        lines.append(f"BEST COIN: {best_coin[0]} — {best_coin[1]['win_rate']:.0f}% WR")

    # Best setup
    if results.get("best_setup"):
        bs = results["best_setup"]
        lines.extend([
            f"",
            f"BEST SETUP ({bs['win_rate']:.0f}% WR, {bs['trades']} trades):",
            f"  {bs['setup']}",
        ])

    if results.get("worst_setup"):
        ws = results["worst_setup"]
        lines.extend([
            f"",
            f"AVOID ({ws['win_rate']:.0f}% WR, {ws['trades']} trades):",
            f"  {ws['setup']}",
        ])

    lines.extend([
        f"",
        f"{'━'*35}",
        f"Run /backtest to refresh anytime.",
    ])

    return "\n".join(lines)
