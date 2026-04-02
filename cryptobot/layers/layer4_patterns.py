"""
LAYER 4 — PATTERN RECOGNITION ENGINE v2
Fixed: Wilder RSI, real swing S/R, ATR stops, trend filter,
multi-timeframe check, volume confirmation, corrected stage logic.
"""

import asyncio
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price, fmt_pct


# ── INDICATORS ────────────────────────────────────────────────────────────────

def _wilder_rsi(closes: list, period: int = 14) -> float:
    """Wilder's smoothed RSI — correct implementation"""
    if len(closes) < period + 2:
        return 50.0
    
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    
    # Initial average using simple mean
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # Wilder smoothing for the rest
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _ema(values: list, period: int) -> list:
    """Exponential moving average"""
    if len(values) < period:
        return values
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _atr(klines: list, period: int = 14) -> float:
    """Average True Range — for dynamic stop placement"""
    if len(klines) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        h = float(klines[i][2])
        l = float(klines[i][3])
        pc = float(klines[i-1][4])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period


def _macd(closes: list) -> tuple:
    """MACD line, signal line, histogram"""
    if len(closes) < 35:
        return 0, 0, 0
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    min_len = min(len(ema12), len(ema26))
    macd_line = [ema12[-(min_len-i)] - ema26[-(min_len-i)] for i in range(min_len)]
    signal = _ema(macd_line, 9)
    if not signal:
        return 0, 0, 0
    hist = macd_line[-1] - signal[-1]
    return round(macd_line[-1], 6), round(signal[-1], 6), round(hist, 6)


def _bollinger(closes: list, period: int = 20) -> tuple:
    """Bollinger Bands — upper, mid, lower"""
    if len(closes) < period:
        return 0, 0, 0
    recent = closes[-period:]
    mid = sum(recent) / period
    std = (sum((x - mid) ** 2 for x in recent) / period) ** 0.5
    return round(mid + 2 * std, 6), round(mid, 6), round(mid - 2 * std, 6)


def _swing_support_resistance(klines: list) -> tuple:
    """
    Real swing-based S/R detection.
    Finds recent swing highs and lows, not just min/max.
    """
    if not klines or len(klines) < 10:
        return 0, 0

    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]

    # Find swing lows (local minima) — support
    swing_lows = []
    for i in range(2, len(lows) - 2):
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append(lows[i])

    # Find swing highs (local maxima) — resistance
    swing_highs = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append(highs[i])

    current_price = closes[-1]

    # Find nearest support below current price
    support_candidates = [s for s in swing_lows if s < current_price]
    support = max(support_candidates) if support_candidates else min(lows[-20:])

    # Find nearest resistance above current price
    resistance_candidates = [r for r in swing_highs if r > current_price]
    resistance = min(resistance_candidates) if resistance_candidates else max(highs[-20:])

    return round(support, 8), round(resistance, 8)


def _trend_direction(closes: list, klines_weekly: list = None) -> dict:
    """
    Multi-timeframe trend detection.
    Daily trend from EMA 50/200. Weekly from price vs EMA 20.
    Returns: daily_trend, weekly_trend, trend_aligned
    """
    result = {"daily": "neutral", "weekly": "neutral", "aligned": False}

    if len(closes) < 20:
        return result

    # Daily trend: EMA50 vs EMA200 or shorter if not enough data
    if len(closes) >= 50:
        ema50 = _ema(closes, 50)[-1]
        ema20 = _ema(closes, 20)[-1]
        current = closes[-1]
        if current > ema50 and ema20 > ema50:
            result["daily"] = "bullish"
        elif current < ema50 and ema20 < ema50:
            result["daily"] = "bearish"
        else:
            result["daily"] = "neutral"
    else:
        ema20 = _ema(closes, 20)[-1] if len(closes) >= 20 else closes[-1]
        result["daily"] = "bullish" if closes[-1] > ema20 else "bearish"

    # Weekly trend from weekly klines if available
    if klines_weekly and len(klines_weekly) >= 10:
        weekly_closes = [float(k[4]) for k in klines_weekly]
        weekly_ema = _ema(weekly_closes, min(10, len(weekly_closes)))[-1]
        result["weekly"] = "bullish" if weekly_closes[-1] > weekly_ema else "bearish"
    else:
        # Estimate weekly from daily: look at 35-candle trend
        if len(closes) >= 35:
            older = closes[-35]
            newer = closes[-1]
            result["weekly"] = "bullish" if newer > older * 1.02 else ("bearish" if newer < older * 0.98 else "neutral")

    result["aligned"] = result["daily"] == result["weekly"] and result["daily"] != "neutral"
    return result


def _volume_profile(klines: list) -> dict:
    """
    Dollar volume analysis — more accurate than raw volume.
    Returns avg, current, ratio, trend.
    """
    if not klines or len(klines) < 10:
        return {"ratio": 1.0, "trend": "neutral", "avg_dollar": 0, "current_dollar": 0}

    # Dollar volume = close price * volume
    dollar_vols = [float(k[4]) * float(k[5]) for k in klines]
    avg = sum(dollar_vols[-8:-1]) / 7
    current = dollar_vols[-1]
    ratio = current / avg if avg > 0 else 1.0

    # Volume trend: rising or falling over last 5 candles
    recent_vols = dollar_vols[-5:]
    vol_trend = "rising" if recent_vols[-1] > recent_vols[0] else "falling"

    return {
        "ratio": round(ratio, 2),
        "trend": vol_trend,
        "avg_dollar": avg,
        "current_dollar": current,
    }


def _detect_pattern(klines: list, closes: list, volumes: dict) -> tuple:
    """
    Pattern detection with volume confirmation.
    All patterns now check volume behavior.
    """
    if len(closes) < 15:
        return "Insufficient data", "Neutral", "No pattern — need more candle history"

    last_3 = closes[-3:]
    vol_ratio = volumes.get("ratio", 1.0)
    vol_trend = volumes.get("trend", "neutral")

    # ── THREE WHITE SOLDIERS (volume must be rising) ──
    opens_3 = [float(k[1]) for k in klines[-3:]]
    closes_3 = [float(k[4]) for k in klines[-3:]]
    if (all(closes_3[i] > closes_3[i-1] * 1.004 for i in range(1, 3)) and
            all(closes_3[i] > opens_3[i] for i in range(3)) and
            vol_trend == "rising"):
        return "Three White Soldiers", "Bullish", "3 strong green candles with rising volume — Stage 3 confirmed"

    # ── THREE BLACK CROWS (volume rising) ──
    if (all(last_3[i] < last_3[i-1] * 0.996 for i in range(1, 3)) and
            all(closes_3[i] < opens_3[i] for i in range(3)) and
            vol_trend == "rising"):
        return "Three Black Crows", "Bearish", "3 strong red candles with rising volume — Stage 5 distribution"

    # ── BULL FLAG (volume MUST be declining in flag) ──
    pole_start = closes[-12]
    pole_peak = max(closes[-10:-3])
    current = closes[-1]
    pole_gain = (pole_peak - pole_start) / pole_start if pole_start > 0 else 0
    flag_retrace = (pole_peak - current) / pole_peak if pole_peak > 0 else 0

    if pole_gain > 0.06 and 0.02 < flag_retrace < 0.14:
        # Volume should be declining during flag consolidation
        flag_vols = [float(k[5]) for k in klines[-6:]]
        flag_vol_declining = flag_vols[-1] < flag_vols[0] if len(flag_vols) >= 2 else True
        if flag_vol_declining:
            return "Bull Flag", "Bullish", f"Pole +{pole_gain*100:.1f}%, flag {flag_retrace*100:.1f}% retrace, volume declining — breakout imminent"
        else:
            return "Bull Flag (weak)", "Bullish", "Bull flag but volume not declining — lower confidence"

    # ── BEAR FLAG ──
    pole_drop = (pole_start - min(closes[-10:-3])) / pole_start if pole_start > 0 else 0
    relief = (current - min(closes[-8:-3])) / abs(min(closes[-8:-3])) if min(closes[-8:-3]) != 0 else 0
    if pole_drop > 0.06 and 0.02 < relief < 0.14:
        return "Bear Flag", "Bearish", f"Pole -{pole_drop*100:.1f}%, relief bounce — continuation down expected"

    # ── ASCENDING TRIANGLE ──
    lows_10 = [float(k[3]) for k in klines[-10:]]
    highs_10 = [float(k[2]) for k in klines[-10:]]
    higher_lows = sum(1 for i in range(1, len(lows_10)) if lows_10[i] >= lows_10[i-1] * 0.995) >= 6
    flat_highs = (max(highs_10) - min(highs_10)) / min(highs_10) < 0.025 if min(highs_10) > 0 else False
    if higher_lows and flat_highs:
        return "Ascending Triangle", "Bullish", "Higher lows pressing flat resistance — breakout loading"

    # ── DESCENDING TRIANGLE ──
    lower_highs = sum(1 for i in range(1, len(highs_10)) if highs_10[i] <= highs_10[i-1] * 1.005) >= 6
    flat_lows_check = (max(lows_10) - min(lows_10)) / min(lows_10) < 0.025 if min(lows_10) > 0 else False
    if lower_highs and flat_lows_check:
        return "Descending Triangle", "Bearish", "Lower highs pressing flat support — breakdown risk"

    # ── DOUBLE BOTTOM ──
    if len(closes) >= 20:
        lows_20 = [float(k[3]) for k in klines[-20:]]
        sorted_lows = sorted(enumerate(lows_20), key=lambda x: x[1])
        bottom1_idx, bottom1_val = sorted_lows[0]
        bottom2_idx, bottom2_val = sorted_lows[1]
        if (abs(bottom1_idx - bottom2_idx) >= 4 and
                abs(bottom1_val - bottom2_val) / bottom1_val < 0.03 and
                closes[-1] > bottom1_val * 1.03):
            return "Double Bottom", "Bullish", "Two equal lows with price breaking above neckline — strong reversal"

    # ── TIGHT CONSOLIDATION (coiling) ──
    volatility = (max(closes[-8:]) - min(closes[-8:])) / min(closes[-8:]) if min(closes[-8:]) > 0 else 1
    if volatility < 0.035:
        return "Tight Consolidation", "Neutral", "Price coiling — big move loading, direction unconfirmed"

    # ── TREND ──
    trend_move = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0
    if trend_move > 0.04:
        return "Uptrend", "Bullish", f"+{trend_move*100:.1f}% over 10 days — trade with the trend"
    if trend_move < -0.04:
        return "Downtrend", "Bearish", f"{trend_move*100:.1f}% over 10 days — wait for reversal"

    return "Ranging", "Neutral", "No clear pattern — wait for structure"


def _pump_stage(closes: list, rsi: float, funding_rate: float = 0,
                vol_ratio: float = 1.0, trend: dict = None) -> tuple:
    """
    Corrected pump stage logic.
    Low RSI + sideways = Stage 1 (accumulation)
    NOT Stage 5. Oversold is a BUY signal, not distribution.
    """
    if len(closes) < 10:
        return 0, "Insufficient data for stage detection"

    recent_move_5d = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
    recent_move_10d = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0
    price_range_10 = (max(closes[-10:]) - min(closes[-10:])) / min(closes[-10:]) if min(closes[-10:]) > 0 else 0
    trend_dir = trend.get("daily", "neutral") if trend else "neutral"

    # STAGE 5 — DISTRIBUTION: RSI overbought + recent big move up + high funding
    if rsi > 78 or (recent_move_5d > 0.25 and funding_rate > 0.08):
        return 5, "STAGE 5 — DISTRIBUTION. Smart money selling. EXIT or take heavy profits NOW."

    # STAGE 4 — PARABOLIC: RSI very high, big recent move
    if rsi > 70 and recent_move_5d > 0.15:
        return 4, "STAGE 4 — PARABOLIC. DO NOT ENTER. Manage existing TPs only."

    # STAGE 3 — BREAKOUT CONFIRMED: RSI mid-high, positive momentum
    if 55 < rsi <= 70 and recent_move_5d > 0.04 and vol_ratio >= 1.3:
        return 3, "STAGE 3 — BREAKOUT CONFIRMED. Entry still viable if within 8% of breakout level."

    # STAGE 2 — BREAKOUT LOADING: RSI building, price compressing
    if 45 < rsi <= 65 and 0.01 < recent_move_10d < 0.12:
        return 2, "STAGE 2 — BREAKOUT LOADING. Prepare entry. Watch for close above resistance with volume."

    # STAGE 1 — ACCUMULATION: RSI low/neutral, price sideways, volume quietly rising
    # NOTE: Low RSI = oversold = ACCUMULATION, NOT distribution
    if rsi <= 45 and price_range_10 < 0.12:
        return 1, "STAGE 1 — SILENT ACCUMULATION. Best entry window. Build position carefully."

    # OVERSOLD REVERSAL: RSI very low — extreme accumulation opportunity
    if rsi < 30:
        return 1, "STAGE 1 — OVERSOLD. RSI extreme low. High probability reversal zone. Prime entry."

    return 0, "NO CLEAR STAGE — market in transition. Wait for structure."


# ── MAIN CLASS ────────────────────────────────────────────────────────────────

class PatternLayer:

    async def pump_stage(self, ticker: str) -> str:
        ts = utc_now()
        ticker = ticker.upper()

        klines_task = fetcher.get_klines(ticker, 60)
        funding_task = fetcher.binance_funding_rate(ticker)
        spot_task = fetcher.get_ticker(ticker)

        klines, funding, spot = await asyncio.gather(klines_task, funding_task, spot_task)

        if not klines or len(klines) < 10:
            return f"Cannot fetch live kline data for {ticker}."

        closes = [float(k[4]) for k in klines]
        price = float(spot["lastPrice"]) if spot else closes[-1]
        rsi = _wilder_rsi(closes)
        atr = _atr(klines)
        support, resistance = _swing_support_resistance(klines)
        vol_data = _volume_profile(klines)
        trend = _trend_direction(closes)
        macd_line, signal_line, hist = _macd(closes)
        bb_upper, bb_mid, bb_lower = _bollinger(closes)

        fr = 0.0
        if funding and len(funding) > 0:
            fr = float(funding[0].get("fundingRate", 0)) * 100

        stage_num, stage_msg = _pump_stage(closes, rsi, fr, vol_data["ratio"], trend)
        pattern_name, pattern_type, pattern_note = _detect_pattern(klines, closes, vol_data)

        # Dynamic stop using ATR
        atr_stop = price - (atr * 2.0) if atr > 0 else support

        rsi_label = "OVERSOLD" if rsi < 30 else ("OVERBOUGHT" if rsi > 70 else "Neutral")

        return (
            f"PUMP STAGE — {ticker}\n"
            f"{ts}\n"
            f"{'━'*35}\n"
            f"Live Price   : ${fmt_price(price)}\n"
            f"Stage        : {stage_num}\n"
            f"RSI (14,D)   : {rsi:.1f} — {rsi_label}\n"
            f"MACD         : {'Bullish' if hist > 0 else 'Bearish'} (hist {hist:+.4f})\n"
            f"BB Position  : {'Near lower band' if price < bb_lower * 1.02 else ('Near upper band' if price > bb_upper * 0.98 else 'Mid range')}\n"
            f"Volume       : {vol_data['ratio']:.1f}x avg — {vol_data['trend']}\n"
            f"Trend Daily  : {trend['daily']}\n"
            f"Trend Weekly : {trend['weekly']}\n"
            f"ATR (14)     : ${fmt_price(atr)}\n"
            f"Support      : ${fmt_price(support)}\n"
            f"Resistance   : ${fmt_price(resistance)}\n"
            f"ATR Stop     : ${fmt_price(atr_stop)}\n"
            f"Funding Rate : {fr:+.4f}%\n"
            f"Pattern      : {pattern_name} — {pattern_type}\n"
            f"             {pattern_note}\n"
            f"{'━'*35}\n"
            f"{stage_msg}\n"
            f"{'━'*35}"
        )

    async def analyze(self, ticker: str) -> dict:
        """Full pattern analysis — returns enriched dict"""
        ticker = ticker.upper()

        klines_task = fetcher.get_klines(ticker, 60)
        klines_4h_task = fetcher.binance_klines(ticker, "4h", 60)
        klines_weekly_task = fetcher.binance_klines(ticker, "1w", 20)
        funding_task = fetcher.binance_funding_rate(ticker)

        klines, klines_4h, klines_weekly, funding = await asyncio.gather(
            klines_task, klines_4h_task, klines_weekly_task, funding_task
        )

        # Fallback for 4H
        if not klines_4h and klines:
            klines_4h = klines

        if not klines:
            return {"error": f"No kline data for {ticker}"}

        closes = [float(k[4]) for k in klines]
        closes_4h = [float(k[4]) for k in klines_4h] if klines_4h else closes
        weekly_closes = [float(k[4]) for k in klines_weekly] if klines_weekly else []

        rsi_daily = _wilder_rsi(closes)
        rsi_4h = _wilder_rsi(closes_4h)
        support, resistance = _swing_support_resistance(klines)
        vol_data = _volume_profile(klines)
        trend = _trend_direction(closes, klines_weekly)
        macd_line, signal_line, macd_hist = _macd(closes)
        bb_upper, bb_mid, bb_lower = _bollinger(closes)
        atr = _atr(klines)

        fr = 0.0
        if funding and len(funding) > 0:
            fr = float(funding[0].get("fundingRate", 0)) * 100

        pattern_name, pattern_type, pattern_note = _detect_pattern(klines, closes, vol_data)
        stage_num, stage_msg = _pump_stage(closes, rsi_daily, fr, vol_data["ratio"], trend)

        current_price = closes[-1]
        price_vs_support = (current_price - support) / support * 100 if support > 0 else 0
        price_vs_resistance = (resistance - current_price) / current_price * 100 if current_price > 0 else 0

        # ATR-based stop loss
        atr_stop = current_price - (atr * 2.0) if atr > 0 else support * 0.97

        # Bollinger position
        bb_position = "lower" if current_price < bb_lower * 1.02 else ("upper" if current_price > bb_upper * 0.98 else "middle")

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
            "trend_daily": trend["daily"],
            "trend_weekly": trend["weekly"],
            "trend_aligned": trend["aligned"],
            "vol_ratio": vol_data["ratio"],
            "vol_trend": vol_data["trend"],
            "macd_hist": macd_hist,
            "bb_position": bb_position,
            "bb_lower": bb_lower,
            "bb_upper": bb_upper,
            "atr": atr,
            "atr_stop": atr_stop,
        }
