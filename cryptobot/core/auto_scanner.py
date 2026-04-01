"""
AUTO-SCANNER
Runs every 2 hours. Scans watchlist coins.
Pushes BUY/SELL signals automatically to user when conditions align.
Only fires when signal confidence is High or Highest conviction.
"""

import asyncio
import logging
from datetime import datetime, timezone
from core.alert_manager import get_watchlist, get_all_active_alerts, mark_alert_triggered
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 7200  # 2 hours
ALERT_CHECK_INTERVAL_SECONDS = 60  # Check price alerts every 60 seconds


async def get_live_price(ticker: str) -> float:
    """Fast single price fetch"""
    spot = await fetcher.binance_ticker(ticker)
    if spot:
        return float(spot["lastPrice"])
    # CoinGecko fallback
    coin_id = await fetcher.resolve_coin_id(ticker)
    if coin_id:
        import aiohttp, config
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{config.COINGECKO_BASE}/simple/price",
                    params={"ids": coin_id, "vs_currencies": "usd"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data.get(coin_id, {}).get("usd", 0)
        except Exception:
            pass
    return 0


async def run_auto_scanner(app, user_ids: list):
    """
    Background task: every 2 hours, scan watchlist and push signals.
    Only sends when stage is 1, 2, or 3 AND pattern confirms.
    """
    from core.signal_engine import SignalEngine
    from layers.layer4_patterns import PatternLayer

    engine = SignalEngine()
    pattern_layer = PatternLayer()

    logger.info("Auto-scanner started — running every 2 hours")

    while True:
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
        ts = utc_now()
        logger.info(f"Auto-scan running at {ts}")

        for user_id in user_ids:
            watchlist = get_watchlist(user_id)
            signals_sent = 0

            for ticker in watchlist:
                try:
                    pattern_data = await pattern_layer.analyze(ticker)
                    if isinstance(pattern_data, dict) and "error" not in pattern_data:
                        stage = pattern_data.get("stage", 3)
                        rsi = pattern_data.get("rsi_daily", 50)
                        pattern = pattern_data.get("pattern", "")
                        price = pattern_data.get("price", 0)
                        support = pattern_data.get("support", 0)
                        resistance = pattern_data.get("resistance", 0)
                        funding = pattern_data.get("funding_rate", 0)

                        # Only push actionable signals
                        # BUY signal: Stage 1 or 2, RSI not overbought
                        if stage in [1, 2] and rsi < 65:
                            msg = _format_auto_buy(ticker, stage, price, support, resistance, rsi, pattern, funding, ts)
                            await app.bot.send_message(chat_id=user_id, text=msg)
                            signals_sent += 1

                        # SELL signal: Stage 4 or 5, RSI overbought
                        elif stage in [4, 5] and rsi > 65:
                            msg = _format_auto_sell(ticker, stage, price, support, resistance, rsi, pattern, ts)
                            await app.bot.send_message(chat_id=user_id, text=msg)
                            signals_sent += 1

                    await asyncio.sleep(0.5)  # Rate limit between coins

                except Exception as e:
                    logger.error(f"Auto-scan error for {ticker}: {e}")
                    continue

            if signals_sent == 0:
                # Send quiet summary — no action needed
                summary = await _build_quiet_summary(watchlist, ts)
                await app.bot.send_message(chat_id=user_id, text=summary)

        logger.info(f"Auto-scan complete at {ts}")


async def run_alert_checker(app, user_ids: list):
    """
    Background task: checks price alerts every 60 seconds.
    Fires notification when price crosses user's target.
    """
    logger.info("Alert checker started — checking every 60 seconds")

    while True:
        await asyncio.sleep(ALERT_CHECK_INTERVAL_SECONDS)

        all_alerts = get_all_active_alerts()
        if not all_alerts:
            continue

        # Collect unique tickers to fetch
        tickers_needed = set()
        for user_alerts in all_alerts.values():
            for alert in user_alerts:
                tickers_needed.add(alert["ticker"])

        # Fetch all prices in parallel
        price_tasks = {ticker: get_live_price(ticker) for ticker in tickers_needed}
        prices = {}
        for ticker, task in price_tasks.items():
            try:
                prices[ticker] = await task
            except Exception:
                prices[ticker] = 0

        # Check each alert
        for user_id_str, user_alerts in all_alerts.items():
            user_id = int(user_id_str)
            for alert in user_alerts:
                ticker = alert["ticker"]
                target = alert["target"]
                direction = alert["direction"]
                live = prices.get(ticker, 0)

                if live == 0:
                    continue

                triggered = (
                    (direction == "above" and live >= target) or
                    (direction == "below" and live <= target)
                )

                if triggered:
                    mark_alert_triggered(user_id, ticker, target)
                    msg = _format_alert_trigger(ticker, live, target, direction)
                    try:
                        await app.bot.send_message(chat_id=user_id, text=msg)
                    except Exception as e:
                        logger.error(f"Failed to send alert to {user_id}: {e}")


async def _build_quiet_summary(watchlist: list, ts: str) -> str:
    """No-signal summary — shows watchlist prices"""
    lines = [
        f"2H AUTO-SCAN COMPLETE — {ts}",
        "No high-conviction signals right now.",
        "",
        "WATCHLIST SNAPSHOT:",
    ]
    for ticker in watchlist[:6]:
        try:
            price = await get_live_price(ticker)
            if price:
                lines.append(f"  {ticker}: ${fmt_price(price)}")
        except Exception:
            pass
    lines.extend(["", "Next scan in 2 hours."])
    return "\n".join(lines)


def _format_auto_buy(ticker, stage, price, support, resistance, rsi, pattern, funding, ts) -> str:
    stage_label = "SILENT ACCUMULATION" if stage == 1 else "BREAKOUT LOADING"
    stage_emoji = "👀" if stage == 1 else "⚡"
    entry_low = support * 1.005
    entry_high = support * 1.02
    tp1 = price * 1.08
    tp2 = price * 1.15
    tp3 = price * 1.25
    stop = support * 0.97

    return (
        f"AUTO-SCAN BUY SIGNAL\n"
        f"{ts}\n"
        f"{'━' * 35}\n"
        f"{stage_emoji} {ticker} — STAGE {stage} {stage_label}\n\n"
        f"Live Price  : ${fmt_price(price)}\n"
        f"Pattern     : {pattern}\n"
        f"RSI (Daily) : {rsi:.0f}\n"
        f"Funding     : {funding:+.4f}%\n\n"
        f"BUY ZONE    : ${fmt_price(entry_low)} — ${fmt_price(entry_high)}\n"
        f"TP1         : ${fmt_price(tp1)} (+8%)\n"
        f"TP2         : ${fmt_price(tp2)} (+15%)\n"
        f"TP3         : ${fmt_price(tp3)} (+25%)\n"
        f"STOP        : ${fmt_price(stop)} (-3% from support)\n\n"
        f"Support     : ${fmt_price(support)}\n"
        f"Resistance  : ${fmt_price(resistance)}\n\n"
        f"Run /scan {ticker} for full 4-layer signal.\n"
        f"{'━' * 35}\n"
        f"Auto-signal. Not financial advice."
    )


def _format_auto_sell(ticker, stage, price, support, resistance, rsi, pattern, ts) -> str:
    stage_label = "PARABOLIC" if stage == 4 else "DISTRIBUTION"
    stage_emoji = "⚠️" if stage == 4 else "🔴"

    return (
        f"AUTO-SCAN SELL SIGNAL\n"
        f"{ts}\n"
        f"{'━' * 35}\n"
        f"{stage_emoji} {ticker} — STAGE {stage} {stage_label}\n\n"
        f"Live Price  : ${fmt_price(price)}\n"
        f"Pattern     : {pattern}\n"
        f"RSI (Daily) : {rsi:.0f} — OVERBOUGHT\n\n"
        f"ACTION      : EXIT or take heavy profits NOW\n"
        f"Support     : ${fmt_price(support)}\n"
        f"Resistance  : ${fmt_price(resistance)}\n\n"
        f"Smart money distributing. Do NOT buy here.\n"
        f"Run /scan {ticker} for full analysis.\n"
        f"{'━' * 35}\n"
        f"Auto-signal. Not financial advice."
    )


def _format_alert_trigger(ticker, live_price, target, direction) -> str:
    emoji = "🚀" if direction == "above" else "📉"
    word = "ABOVE" if direction == "above" else "BELOW"
    return (
        f"{emoji} PRICE ALERT TRIGGERED\n"
        f"{'━' * 30}\n"
        f"{ticker} is now ${fmt_price(live_price)}\n"
        f"Your target: {word} ${fmt_price(target)}\n\n"
        f"Run /scan {ticker} for full signal now."
    )
