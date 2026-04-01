"""
LAYER 4 — PATTERN RECOGNITION ENGINE
Live kline analysis. Detects patterns, pump stages, RSI, support/resistance.
Every level comes from real candles. Nothing assumed.
"""

import asyncio
import math
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price, fmt_pct


def _calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _support_resistance(klines: list) -> tuple:
    """Find recent key support and resistance from klines"""
    if not klines or len(klines) < 5:
        return 0, 0
    highs = [float(k[2]) for k in klines[-30:]]
    lows = [float(k[3]) for k in klines[-30:]]
    resistance = max(highs)
    support = min(lows)
    return support, resistance


def _detect_pattern(klines: list, closes: list) -> tuple:
    """Simple pattern detection from last N candles"""
    if len(closes) < 10:
        return "Insufficient data", "Neutral", "⚪ Indeterminate"

    recent = closes[-10:]
    last_5 = closes[-5:]
    last_3 = closes[-3:]

    # Three White Soldiers
    if all(last_3[i] > last_3[i-1] * 1.005 for i in range(1, 3)):
        o3 = [float(k[1]) for k in klines[-3:]]
        c3 = [float(k[4]) for k in klines[-3:]]
        if all(c3[i] > o3[i] for i in range(3)):
            return "Three White Soldiers", "Bullish Continuation", "🟢 Strong bullish momentum — Stage 3 signal"

    # Three Black Crows
    if all(last_3[i] < last_3[i-1] * 0.995 for i in range(1, 3)):
        o3 = [float(k[1]) for k in klines[-3:]]
        c3 = [float(k[4]) for k in klines[-3:]]
        if all(c3[i] < o3[i] for i in range(3)):
            return "Three Black Crows", "Bearish Continuation", "🔴 Strong bearish momentum — Stage 5 signal"

    # Higher lows (ascending triangle / accumulation)
    lows = [float(k[3]) for k in klines[-10:]]
    highs = [float(k[2]) for k in klines[-10:]]
    higher_lows = all(lows[i] >= lows[i-1] * 0.99 for i in range(1, len(lows)))
    flat_highs = max(highs) / min(highs) < 1.03 if min(highs) > 0 else False

    if higher_lows and flat_highs:
        return "Ascending Triangle", "Bullish Continuation", "🟡 Breakout loading — watch for volume explosion above resistance"

    # Lower highs (descending triangle / distribution)
    lower_highs = all(highs[i] <= highs[i-1] * 1.01 for i in range(1, len(highs)))
    flat_lows = max(lows) / min(lows) < 1.03 if min(lows) > 0 else False
    if lower_highs and flat_lows:
        return "Descending Triangle", "Bearish", "🔴 Breakdown risk — watch for volume on support break"

    # Bull flag: sharp rise then tight consolidation
    pole_start = closes[-10]
    pole_peak = max(closes[-8:-3])
    current = closes[-1]
    pole_gain = (pole_peak - pole_start) / pole_start if pole_start > 0 else 0
    flag_retrace = (pole_peak - current) / pole_peak if pole_peak > 0 else 0

    if pole_gain > 0.05 and 0.02 < flag_retrace < 0.15:
        return "Bull Flag", "Bullish Continuation", "⚡ Flag forming after strong pole — breakout target: pole height added to flag low"

    # Bear flag
    if pole_gain < -0.05 and 0.02 < (current - min(closes[-8:-3])) / abs(min(closes[-8:-3])) < 0.15:
        return "Bear Flag", "Bearish Continuation", "🔴 Bear flag — continuation downward expected"

    # Consolidation / indecision
    volatility = (max(recent) - min(recent)) / min(recent) if min(recent) > 0 else 0
    if volatility < 0.04:
        return "Tight Consolidation", "Indecision", "⚪ Coiling — big move loading in either direction"

    # Default: trending
    trend_strength = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0
    if trend_strength > 0.03:
        return "Uptrend", "Bullish", "🟢 Trending up — trade with the trend"
    if trend_strength < -0.03:
        return "Downtrend", "Bearish", "🔴 Trending down — wait for reversal confirmation"

    return "Neutral Range", "Neutral", "⚪ No clear pattern — no trade right now"


def _pump_stage(closes: list, rsi: float, funding_rate: float = 0) -> tuple:
    """Determine pump stage from price action + RSI + funding"""
    if len(closes) < 10:
        return 1, "👀 STAGE 1 — Insufficient data for confident stage detection"

    recent_move = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
    vol_trend = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0

    if rsi > 80 or (recent_move > 0.20 and funding_rate > 0.05):
        return 4, (
            "⚠️ *STAGE 4 — LIVE PARABOLIC*\n"
            f"Price up {fmt_pct(recent_move*100)} recently. RSI: {rsi:.0f}.\n"
            "DO NOT ENTER. If already in — START TAKING PROFITS NOW.\n"
            "Smart money from Stage 1 is selling to you right now."
        )
    if rsi > 70 and recent_move > 0.10:
        return 3, (
            "🚀 *STAGE 3 — BREAKOUT CONFIRMED*\n"
            f"Strong momentum. RSI: {rsi:.0f}. Recent: {fmt_pct(recent_move*100)}.\n"
            "Entry still viable — do NOT chase if >10% above last support.\n"
            "Wait for live retest of breakout level."
        )
    if 50 < rsi < 70 and recent_move > 0.03:
        return 2, (
            "⚡ *STAGE 2 — BREAKOUT LOADING*\n"
            f"Building momentum. RSI: {rsi:.0f}. Price compressing.\n"
            "Prepare entry. Watch for candle CLOSE above resistance with volume."
        )
    if rsi < 40 or (vol_trend < 0 and recent_move > -0.05):
        return 5, (
            "🔴 *STAGE 5 — DISTRIBUTION*\n"
            f"RSI: {rsi:.0f}. Price weakening.\n"
            "Smart money offloading into retail. EXIT or take heavy profits NOW."
        )

    return 1, (
        "👀 *STAGE 1 — SILENT ACCUMULATION*\n"
        f"Price sideways. RSI: {rsi:.0f}. No major move yet.\n"
        "Highest quality entry window. Build position carefully with split entries."
    )


class PatternLayer:

    async def pump_stage(self, ticker: str) -> str:
        ts = utc_now()
        ticker = ticker.upper()

        klines_task = fetcher.binance_klines(ticker, "1d", 50)
        funding_task = fetcher.binance_funding_rate(ticker)
        spot_task = fetcher.binance_ticker(ticker)

        klines, funding, spot = await asyncio.gather(klines_task, funding_task, spot_task)

        if not klines or len(klines) < 5:
            return f"❌ Cannot fetch live kline data for {ticker}. No pattern analysis possible."

        closes = [float(k[4]) for k in klines]
        price = float(spot["lastPrice"]) if spot else closes[-1]
        rsi = _calc_rsi(closes)

        fr = 0.0
        if funding and len(funding) > 0:
            fr = float(funding[0].get("fundingRate", 0)) * 100

        stage_num, stage_msg = _pump_stage(closes, rsi, fr)
        pattern_name, pattern_type, pattern_note = _detect_pattern(klines, closes)
        support, resistance = _support_resistance(klines)

        return (
            f"🔍 *PUMP STAGE — {ticker}*\n"
            f"🕐 {ts}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Live Price   : *${fmt_price(price)}*\n"
            f"RSI (14, D)  : {rsi:.1f} {'🟢' if rsi < 40 else ('🔴' if rsi > 70 else '⚪')}\n"
            f"Funding Rate : {fr:+.4f}%\n"
            f"Support      : ${fmt_price(support)}\n"
            f"Resistance   : ${fmt_price(resistance)}\n"
            f"Pattern      : {pattern_name} — {pattern_type}\n"
            f"             {pattern_note}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{stage_msg}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    async def analyze(self, ticker: str) -> dict:
        """Full pattern analysis — returns dict for signal engine use"""
        ticker = ticker.upper()

        klines_task = fetcher.binance_klines(ticker, "1d", 50)
        klines_4h_task = fetcher.binance_klines(ticker, "4h", 50)
        funding_task = fetcher.binance_funding_rate(ticker)
        oi_task = fetcher.binance_open_interest("BTC")  # BTC as proxy if ticker futures unavailable

        klines, klines_4h, funding, oi = await asyncio.gather(
            klines_task, klines_4h_task, funding_task, oi_task
        )

        if not klines:
            return {"error": f"No kline data for {ticker}"}

        closes = [float(k[4]) for k in klines]
        closes_4h = [float(k[4]) for k in klines_4h] if klines_4h else closes

        rsi_daily = _calc_rsi(closes)
        rsi_4h = _calc_rsi(closes_4h)
        support, resistance = _support_resistance(klines)

        fr = 0.0
        if funding and len(funding) > 0:
            fr = float(funding[0].get("fundingRate", 0)) * 100

        pattern_name, pattern_type, pattern_note = _detect_pattern(klines, closes)
        stage_num, stage_msg = _pump_stage(closes, rsi_daily, fr)

        current_price = closes[-1]
        price_vs_support = (current_price - support) / support * 100 if support > 0 else 0
        price_vs_resistance = (resistance - current_price) / current_price * 100 if current_price > 0 else 0

        return {
            "ticker": ticker,
            "price": current_price,
            "rsi_daily": rsi_daily,
            "rsi_4h": rsi_4h,
            "support": support,
            "resistance": resistance,
            "funding_rate": fr,
            "pattern": pattern_name,
            "pattern_type": pattern_type,
            "pattern_note": pattern_note,
            "stage": stage_num,
            "stage_msg": stage_msg,
            "price_vs_support_pct": price_vs_support,
            "price_vs_resistance_pct": price_vs_resistance,
        }
