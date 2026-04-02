"""
SIGNAL HISTORY LOGGER
Logs every signal with entry, TPs, stop loss.
Auto-tracks outcomes when price hits targets or stop.
Builds win rate data per pattern, per coin, per macro condition.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

SIGNALS_FILE = os.path.join(os.path.dirname(__file__), "../data/signals.json")


def _load() -> dict:
    os.makedirs(os.path.dirname(SIGNALS_FILE), exist_ok=True)
    if not os.path.exists(SIGNALS_FILE):
        return {"signals": [], "stats": {}}
    try:
        with open(SIGNALS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"signals": [], "stats": {}}


def _save(data: dict):
    os.makedirs(os.path.dirname(SIGNALS_FILE), exist_ok=True)
    with open(SIGNALS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def log_signal(
    user_id: int,
    ticker: str,
    direction: str,       # BUY or SELL
    trade_type: str,      # spot or perp
    entry_price: float,
    tp1: float,
    tp2: float,
    tp3: float,
    stop_loss: float,
    stage: int,
    pattern: str,
    macro_gate: str,      # GREEN / YELLOW / RED
    confidence: str,
    fng_score: int = 0,
) -> str:
    data = _load()
    signal_id = f"{ticker}_{int(datetime.now(timezone.utc).timestamp())}"

    signal = {
        "id": signal_id,
        "user_id": user_id,
        "ticker": ticker,
        "direction": direction,
        "trade_type": trade_type,
        "entry_price": entry_price,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "stop_loss": stop_loss,
        "stage": stage,
        "pattern": pattern,
        "macro_gate": macro_gate,
        "confidence": confidence,
        "fng_score": fng_score,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "outcome": "OPEN",       # OPEN / TP1_HIT / TP2_HIT / TP3_HIT / STOPPED / CANCELLED
        "outcome_price": None,
        "outcome_time": None,
        "pnl_pct": None,
    }

    data["signals"].append(signal)
    _save(data)
    return signal_id


def update_outcome(signal_id: str, outcome: str, current_price: float):
    """Update signal outcome when price hits a level"""
    data = _load()
    for s in data["signals"]:
        if s["id"] == signal_id:
            s["outcome"] = outcome
            s["outcome_price"] = current_price
            s["outcome_time"] = datetime.now(timezone.utc).isoformat()

            # Calculate PnL
            entry = s["entry_price"]
            if entry > 0:
                if s["direction"] == "BUY":
                    s["pnl_pct"] = ((current_price - entry) / entry) * 100
                else:
                    s["pnl_pct"] = ((entry - current_price) / entry) * 100

            # Update stats
            _update_stats(data, s)
            break
    _save(data)


def _update_stats(data: dict, signal: dict):
    stats = data.get("stats", {})
    ticker = signal["ticker"]
    pattern = signal["pattern"]
    macro = signal["macro_gate"]
    outcome = signal["outcome"]

    is_win = outcome in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]
    is_loss = outcome == "STOPPED"

    for key in [ticker, pattern, f"macro_{macro}"]:
        if key not in stats:
            stats[key] = {"wins": 0, "losses": 0, "open": 0, "total_pnl": 0}
        if is_win:
            stats[key]["wins"] += 1
            stats[key]["total_pnl"] += signal.get("pnl_pct", 0) or 0
        elif is_loss:
            stats[key]["losses"] += 1
            stats[key]["total_pnl"] += signal.get("pnl_pct", 0) or 0
        else:
            stats[key]["open"] += 1

    data["stats"] = stats


def get_open_signals(user_id: int) -> list:
    data = _load()
    return [s for s in data["signals"] if s["user_id"] == user_id and s["outcome"] == "OPEN"]


def get_all_signals(user_id: int, limit: int = 20) -> list:
    data = _load()
    user_signals = [s for s in data["signals"] if s["user_id"] == user_id]
    return user_signals[-limit:]


def get_stats_text(user_id: int) -> str:
    data = _load()
    user_signals = [s for s in data["signals"] if s["user_id"] == user_id]

    if not user_signals:
        return (
            "No signal history yet.\n\n"
            "Run /scan on any coin to generate your first signal.\n"
            "The bot tracks every signal outcome automatically."
        )

    total = len(user_signals)
    wins = len([s for s in user_signals if s["outcome"] in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]])
    losses = len([s for s in user_signals if s["outcome"] == "STOPPED"])
    open_count = len([s for s in user_signals if s["outcome"] == "OPEN"])
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    # Best and worst patterns
    stats = data.get("stats", {})
    pattern_stats = {k: v for k, v in stats.items() if k not in ["macro_GREEN", "macro_YELLOW", "macro_RED"]}
    best_pattern = max(pattern_stats.items(), key=lambda x: x[1]["wins"], default=(None, None))
    worst_pattern = min(pattern_stats.items(), key=lambda x: x[1]["losses"], default=(None, None))

    # Recent signals
    recent = user_signals[-5:]
    recent_lines = []
    for s in reversed(recent):
        outcome_emoji = {
            "OPEN": "⏳",
            "TP1_HIT": "🟢",
            "TP2_HIT": "🟢",
            "TP3_HIT": "🟢",
            "STOPPED": "🔴",
            "CANCELLED": "⚪"
        }.get(s["outcome"], "⚪")
        pnl = f"{s['pnl_pct']:+.1f}%" if s.get("pnl_pct") is not None else "open"
        recent_lines.append(f"  {outcome_emoji} {s['ticker']} {s['direction']} — {s['outcome']} ({pnl})")

    lines = [
        "SIGNAL PERFORMANCE TRACKER",
        "",
        f"Total Signals  : {total}",
        f"Win Rate       : {win_rate:.1f}%",
        f"Wins           : {wins}",
        f"Losses         : {losses}",
        f"Open           : {open_count}",
        "",
        "MACRO PERFORMANCE:",
        f"  GREEN gate   : {stats.get('macro_GREEN', {}).get('wins', 0)}W / {stats.get('macro_GREEN', {}).get('losses', 0)}L",
        f"  YELLOW gate  : {stats.get('macro_YELLOW', {}).get('wins', 0)}W / {stats.get('macro_YELLOW', {}).get('losses', 0)}L",
        f"  RED gate     : {stats.get('macro_RED', {}).get('wins', 0)}W / {stats.get('macro_RED', {}).get('losses', 0)}L",
        "",
    ]

    if best_pattern[0]:
        lines.append(f"Best pattern   : {best_pattern[0]} ({best_pattern[1]['wins']} wins)")
    if worst_pattern[0] and worst_pattern[0] != best_pattern[0]:
        lines.append(f"Most losses    : {worst_pattern[0]} ({worst_pattern[1]['losses']} losses)")

    lines.extend(["", "LAST 5 SIGNALS:"] + recent_lines)
    return "\n".join(lines)


def get_open_signals_text(user_id: int) -> str:
    open_sigs = get_open_signals(user_id)
    if not open_sigs:
        return "No open signals tracking right now."

    lines = [f"OPEN SIGNALS TRACKING ({len(open_sigs)})", ""]
    for s in open_sigs:
        lines.extend([
            f"{s['ticker']} {s['direction']} [{s['trade_type'].upper()}]",
            f"  Entry  : ${s['entry_price']:,.4f}",
            f"  TP1    : ${s['tp1']:,.4f}",
            f"  TP2    : ${s['tp2']:,.4f}",
            f"  Stop   : ${s['stop_loss']:,.4f}",
            f"  Stage  : {s['stage']} | Pattern: {s['pattern']}",
            f"  Signal : {s['timestamp'][:10]}",
            "",
        ])
    lines.append("Use /track [COIN] to check live status of a signal.")
    return "\n".join(lines)


async def check_open_signals(fetch_price_fn) -> list:
    """
    Check all open signals against current price.
    Returns list of triggered signals.
    """
    data = _load()
    triggered = []

    for s in data["signals"]:
        if s["outcome"] != "OPEN":
            continue

        ticker = s["ticker"]
        live_price = await fetch_price_fn(ticker)
        if not live_price:
            continue

        direction = s["direction"]
        entry = s["entry_price"]

        if direction == "BUY":
            if live_price >= s["tp3"]:
                update_outcome(s["id"], "TP3_HIT", live_price)
                triggered.append({**s, "outcome": "TP3_HIT", "live_price": live_price})
            elif live_price >= s["tp2"]:
                update_outcome(s["id"], "TP2_HIT", live_price)
                triggered.append({**s, "outcome": "TP2_HIT", "live_price": live_price})
            elif live_price >= s["tp1"]:
                update_outcome(s["id"], "TP1_HIT", live_price)
                triggered.append({**s, "outcome": "TP1_HIT", "live_price": live_price})
            elif live_price <= s["stop_loss"]:
                update_outcome(s["id"], "STOPPED", live_price)
                triggered.append({**s, "outcome": "STOPPED", "live_price": live_price})

        elif direction == "SELL":
            if live_price <= s["tp3"]:
                update_outcome(s["id"], "TP3_HIT", live_price)
                triggered.append({**s, "outcome": "TP3_HIT", "live_price": live_price})
            elif live_price <= s["tp2"]:
                update_outcome(s["id"], "TP2_HIT", live_price)
                triggered.append({**s, "outcome": "TP2_HIT", "live_price": live_price})
            elif live_price <= s["tp1"]:
                update_outcome(s["id"], "TP1_HIT", live_price)
                triggered.append({**s, "outcome": "TP1_HIT", "live_price": live_price})
            elif live_price >= s["stop_loss"]:
                update_outcome(s["id"], "STOPPED", live_price)
                triggered.append({**s, "outcome": "STOPPED", "live_price": live_price})

    return triggered
