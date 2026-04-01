"""
ALERT MANAGER — Price alerts + Portfolio tracker
Persistent storage using JSON files. No database needed.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

ALERTS_FILE = os.path.join(os.path.dirname(__file__), "../data/alerts.json")
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "../data/portfolio.json")
WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "../data/watchlist.json")


def _ensure_data_dir():
    os.makedirs(os.path.dirname(ALERTS_FILE), exist_ok=True)


def _load(filepath: str) -> dict:
    _ensure_data_dir()
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(filepath: str, data: dict):
    _ensure_data_dir()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# ── PRICE ALERTS ─────────────────────────────────────────────────────────────

def add_alert(user_id: int, ticker: str, target_price: float, direction: str) -> str:
    """Add a price alert. direction = 'above' or 'below'"""
    alerts = _load(ALERTS_FILE)
    key = str(user_id)
    if key not in alerts:
        alerts[key] = []

    alert = {
        "ticker": ticker.upper(),
        "target": target_price,
        "direction": direction,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered": False,
    }
    alerts[key].append(alert)
    _save(ALERTS_FILE, alerts)
    return f"Alert set: {ticker.upper()} {'above' if direction == 'above' else 'below'} ${target_price:,.4f}"


def get_alerts(user_id: int) -> list:
    alerts = _load(ALERTS_FILE)
    return [a for a in alerts.get(str(user_id), []) if not a.get("triggered")]


def get_all_active_alerts() -> dict:
    """Returns all untriggered alerts across all users"""
    alerts = _load(ALERTS_FILE)
    result = {}
    for user_id, user_alerts in alerts.items():
        active = [a for a in user_alerts if not a.get("triggered")]
        if active:
            result[user_id] = active
    return result


def mark_alert_triggered(user_id: int, ticker: str, target: float):
    alerts = _load(ALERTS_FILE)
    key = str(user_id)
    for alert in alerts.get(key, []):
        if alert["ticker"] == ticker and alert["target"] == target:
            alert["triggered"] = True
    _save(ALERTS_FILE, alerts)


def clear_alerts(user_id: int) -> str:
    alerts = _load(ALERTS_FILE)
    alerts[str(user_id)] = []
    _save(ALERTS_FILE, alerts)
    return "All your alerts cleared."


def list_alerts_text(user_id: int) -> str:
    active = get_alerts(user_id)
    if not active:
        return "No active alerts. Set one with:\n/alert BTC 90000\n/alert SOL 100"
    lines = ["YOUR ACTIVE ALERTS:", ""]
    for i, a in enumerate(active, 1):
        direction = "ABOVE" if a["direction"] == "above" else "BELOW"
        lines.append(f"{i}. {a['ticker']} {direction} ${a['target']:,.2f}")
    lines.append("\nUse /clearalerts to remove all.")
    return "\n".join(lines)


# ── PORTFOLIO TRACKER ─────────────────────────────────────────────────────────

def add_position(user_id: int, ticker: str, amount: float, entry_price: float) -> str:
    portfolio = _load(PORTFOLIO_FILE)
    key = str(user_id)
    if key not in portfolio:
        portfolio[key] = []

    position = {
        "ticker": ticker.upper(),
        "amount": amount,
        "entry_price": entry_price,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    # Update existing position if ticker already exists
    for p in portfolio[key]:
        if p["ticker"] == ticker.upper():
            # Average down/up
            total_cost = (p["amount"] * p["entry_price"]) + (amount * entry_price)
            p["amount"] += amount
            p["entry_price"] = total_cost / p["amount"]
            _save(PORTFOLIO_FILE, portfolio)
            return f"Updated {ticker.upper()} position: {p['amount']} @ avg ${p['entry_price']:,.4f}"

    portfolio[key].append(position)
    _save(PORTFOLIO_FILE, portfolio)
    return f"Added {amount} {ticker.upper()} @ ${entry_price:,.4f}"


def remove_position(user_id: int, ticker: str) -> str:
    portfolio = _load(PORTFOLIO_FILE)
    key = str(user_id)
    before = len(portfolio.get(key, []))
    portfolio[key] = [p for p in portfolio.get(key, []) if p["ticker"] != ticker.upper()]
    _save(PORTFOLIO_FILE, portfolio)
    if len(portfolio[key]) < before:
        return f"Removed {ticker.upper()} from portfolio."
    return f"{ticker.upper()} not found in portfolio."


def get_positions(user_id: int) -> list:
    portfolio = _load(PORTFOLIO_FILE)
    return portfolio.get(str(user_id), [])


async def get_portfolio_text(user_id: int, fetch_prices_fn) -> str:
    """Build portfolio summary with live prices"""
    positions = get_positions(user_id)
    if not positions:
        return (
            "Portfolio empty.\n\n"
            "Add positions with:\n"
            "/portfolio add SOL 10 85.00\n"
            "/portfolio add BTC 0.5 82000\n\n"
            "Remove with:\n"
            "/portfolio remove SOL"
        )

    lines = ["YOUR PORTFOLIO — LIVE PNL", ""]
    total_invested = 0
    total_current = 0

    for p in positions:
        ticker = p["ticker"]
        amount = p["amount"]
        entry = p["entry_price"]
        invested = amount * entry

        # Fetch live price
        live_price = await fetch_prices_fn(ticker)
        if live_price:
            current_val = amount * live_price
            pnl = current_val - invested
            pnl_pct = (pnl / invested) * 100
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"{pnl_emoji} {ticker}\n"
                f"   Amount : {amount}\n"
                f"   Entry  : ${entry:,.4f}\n"
                f"   Now    : ${live_price:,.4f}\n"
                f"   PnL    : ${pnl:+,.2f} ({pnl_pct:+.1f}%)\n"
            )
            total_invested += invested
            total_current += current_val
        else:
            lines.append(f"⚪ {ticker} — live price unavailable\n")
            total_invested += invested

    if total_invested > 0:
        total_pnl = total_current - total_invested
        total_pct = (total_pnl / total_invested) * 100
        emoji = "🟢" if total_pnl >= 0 else "🔴"
        lines.extend([
            "─────────────────────",
            f"{emoji} TOTAL PnL: ${total_pnl:+,.2f} ({total_pct:+.1f}%)",
            f"Invested : ${total_invested:,.2f}",
            f"Current  : ${total_current:,.2f}",
        ])

    return "\n".join(lines)


# ── WATCHLIST ─────────────────────────────────────────────────────────────────

DEFAULT_WATCHLIST = ["BTC", "ETH", "SOL", "TAO", "RENDER", "SUI", "DOT"]


def get_watchlist(user_id: int) -> list:
    watchlist = _load(WATCHLIST_FILE)
    return watchlist.get(str(user_id), DEFAULT_WATCHLIST)


def set_watchlist(user_id: int, tickers: list) -> str:
    watchlist = _load(WATCHLIST_FILE)
    watchlist[str(user_id)] = [t.upper() for t in tickers]
    _save(WATCHLIST_FILE, watchlist)
    return f"Watchlist updated: {', '.join(t.upper() for t in tickers)}"


def add_to_watchlist(user_id: int, ticker: str) -> str:
    watchlist = _load(WATCHLIST_FILE)
    key = str(user_id)
    current = watchlist.get(key, DEFAULT_WATCHLIST.copy())
    if ticker.upper() not in current:
        current.append(ticker.upper())
        watchlist[key] = current
        _save(WATCHLIST_FILE, watchlist)
    return f"{ticker.upper()} added to watchlist."


def remove_from_watchlist(user_id: int, ticker: str) -> str:
    watchlist = _load(WATCHLIST_FILE)
    key = str(user_id)
    current = watchlist.get(key, DEFAULT_WATCHLIST.copy())
    current = [t for t in current if t != ticker.upper()]
    watchlist[key] = current
    _save(WATCHLIST_FILE, watchlist)
    return f"{ticker.upper()} removed from watchlist."
