"""
OPPORTUNITY SCANNER v5 — BIDIRECTIONAL
Detects BOTH buy and sell opportunities.
Same scoring system, inverted conditions for sells.
Buy alerts: accumulation, oversold, support bounces, breakouts
Sell alerts: distribution, overbought, resistance rejection, breakdown

Minimum confluence required before any alert fires.
Macro tier gates. Weekly trend hard filter.
Position size scales with score.
"""

import asyncio
import logging
from datetime import datetime, timezone
from core.data_fetcher import fetcher, utc_now
from core.alert_manager import get_watchlist
from layers.layer4_patterns import (
    _wilder_rsi, _atr, _macd, _bollinger,
    _swing_support_resistance, _volume_profile,
    _trend_direction, _pump_stage, _detect_pattern
)
from layers.layer5_whale import whale_detector
from layers.layer7_macro_intel import macro_intel
from utils.formatter import fmt_price, fmt_large

logger = logging.getLogger(__name__)

SCAN_INTERVAL    = 10 * 60
COOLDOWN_BUY     = 6 * 3600   # 6 hours cooldown for buy alerts per coin
COOLDOWN_SELL    = 4 * 3600   # 4 hours cooldown for sell alerts per coin

FNG_BUY_THRESHOLDS = {
    (0,  20):  8.0,
    (20, 35):  6.5,
    (35, 50):  5.0,
    (50, 65):  3.5,
    (65, 101): 3.0,
}

FNG_SELL_THRESHOLDS = {
    (0,  30):  8.0,   # Extreme fear — selling here needs very high conviction
    (30, 50):  7.0,
    (50, 65):  5.5,
    (65, 80):  4.0,   # Greed — easier to fire sell alerts
    (80, 101): 3.0,   # Extreme greed — most sell setups fire
}

def _fng_buy_threshold(fng: int) -> float:
    for (lo, hi), t in FNG_BUY_THRESHOLDS.items():
        if lo <= fng < hi:
            return t
    return 5.0

def _fng_sell_threshold(fng: int) -> float:
    for (lo, hi), t in FNG_SELL_THRESHOLDS.items():
        if lo <= fng < hi:
            return t
    return 5.0


class OpportunityScanner:

    def __init__(self):
        self._cooldowns_buy  = {}  # ticker -> datetime
        self._cooldowns_sell = {}  # ticker -> datetime

    def _on_cooldown(self, ticker: str, direction: str) -> bool:
        cooldowns = self._cooldowns_buy if direction == "BUY" else self._cooldowns_sell
        secs = COOLDOWN_BUY if direction == "BUY" else COOLDOWN_SELL
        if ticker not in cooldowns:
            return False
        elapsed = (datetime.now(timezone.utc) - cooldowns[ticker]).total_seconds()
        return elapsed < secs

    def _mark(self, ticker: str, direction: str):
        if direction == "BUY":
            self._cooldowns_buy[ticker] = datetime.now(timezone.utc)
        else:
            self._cooldowns_sell[ticker] = datetime.now(timezone.utc)

    # ── BUY SCORING ───────────────────────────────────────────────────────────

    def _score_buy_technical(self, rsi_daily, rsi_4h, klines, closes,
                              vol_data, trend, stage, macd_hist, bb_position) -> tuple:
        score = 0.0
        signals = []

        if rsi_daily < 25:
            score += 1.0
            signals.append(f"RSI {rsi_daily:.0f} daily — extreme oversold (+1.0)")
        elif rsi_daily < 35:
            score += 0.7
            signals.append(f"RSI {rsi_daily:.0f} daily — oversold (+0.7)")
        elif rsi_daily < 45:
            score += 0.3
            signals.append(f"RSI {rsi_daily:.0f} daily — low (+0.3)")

        if rsi_4h < 25:
            score += 0.5
            signals.append(f"RSI {rsi_4h:.0f} 4H — oversold (+0.5)")

        if macd_hist > 0:
            score += 0.5
            signals.append(f"MACD bullish ({macd_hist:+.5f}) (+0.5)")

        if bb_position == "lower":
            score += 0.5
            signals.append(f"Price at Bollinger lower band (+0.5)")

        if stage == 1:
            score += 1.0
            signals.append(f"Stage 1 — silent accumulation (+1.0)")
        elif stage == 2:
            score += 0.5
            signals.append(f"Stage 2 — breakout loading (+0.5)")

        vol_ratio = vol_data.get("ratio", 1.0)
        if vol_ratio >= 2.5:
            score += 0.5
            signals.append(f"Volume {vol_ratio:.1f}x surge on green candle (+0.5)")
        elif vol_ratio >= 1.8:
            score += 0.3
            signals.append(f"Volume {vol_ratio:.1f}x pickup (+0.3)")

        pattern_name = "N/A"
        if klines and len(closes) >= 15:
            p_name, _, _ = _detect_pattern(klines, closes, vol_data)
            bullish = ["Bull Flag", "Double Bottom", "Inverse", "Ascending", "Three White", "Cup"]
            if any(b.lower() in p_name.lower() for b in bullish):
                score += 1.0
                signals.append(f"Pattern: {p_name} (+1.0)")
                pattern_name = p_name

        return min(score, 3.0), signals, pattern_name

    def _score_buy_whale(self, whale_data: dict) -> tuple:
        score = 0.0
        signals = []
        if not whale_data or whale_data.get("error"):
            return 0.0, []

        ws = whale_data.get("score", 0)
        if ws >= 3:
            score += 1.0
            signals.append(f"Whale strongly bullish (score {ws:+d}) (+1.0)")
        elif ws >= 1:
            score += 0.5
            signals.append(f"Whale mildly bullish (score {ws:+d}) (+0.5)")
        elif ws <= -2:
            score -= 0.5
            signals.append(f"Whale bearish (score {ws:+d}) (-0.5)")

        taker = whale_data.get("taker_ratio", 0.5)
        if taker > 0.60:
            score += 0.5
            signals.append(f"Taker {taker:.0%} — aggressive buyers (+0.5)")
        elif taker > 0.55:
            score += 0.3
            signals.append(f"Taker {taker:.0%} — buyers leading (+0.3)")

        if whale_data.get("funding_signal") == "short_squeeze_risk":
            score += 0.5
            signals.append(f"Shorts over-leveraged — squeeze potential (+0.5)")

        long_liqs = whale_data.get("long_liqs", 0)
        if long_liqs > 1_000_000:
            score += 0.3
            signals.append(f"Long liquidation flush ${fmt_large(long_liqs)} — capitulation (+0.3)")

        return min(score, 2.0), signals

    def _score_buy_macro(self, dxy, yield_data, fng, btc_dom) -> tuple:
        score = 0.0
        signals = []

        if dxy.get("signal") == "bullish":
            score += 0.5
            signals.append(f"DXY falling {dxy.get('change_1d',0):+.3f}% — tailwind (+0.5)")
        elif dxy.get("signal") == "bearish":
            score -= 0.5
            signals.append(f"DXY rising {dxy.get('change_1d',0):+.3f}% — headwind (-0.5)")

        if yield_data.get("signal") == "bullish":
            score += 0.5
            signals.append(f"10Y yield falling — risk-on (+0.5)")
        elif yield_data.get("signal") == "bearish":
            score -= 0.3
            signals.append(f"10Y yield rising — risk-off (-0.3)")

        if fng <= 20:
            score += 0.5
            signals.append(f"Extreme fear {fng}/100 — best buy zone (+0.5)")
        elif fng <= 35:
            score += 0.3
            signals.append(f"Fear {fng}/100 — good buy conditions (+0.3)")
        elif fng >= 70:
            score -= 0.3
            signals.append(f"Greed {fng}/100 — elevated risk (-0.3)")

        if btc_dom < 44:
            score += 0.5
            signals.append(f"BTC.D {btc_dom:.1f}% — altseason active (+0.5)")
        elif btc_dom > 56:
            score -= 0.3
            signals.append(f"BTC.D {btc_dom:.1f}% rising — alts weak (-0.3)")

        return min(max(score, -1.0), 2.0), signals

    # ── SELL SCORING ──────────────────────────────────────────────────────────

    def _score_sell_technical(self, rsi_daily, rsi_4h, klines, closes,
                               vol_data, trend, stage, macd_hist, bb_position) -> tuple:
        score = 0.0
        signals = []

        # RSI overbought
        if rsi_daily > 78:
            score += 1.0
            signals.append(f"RSI {rsi_daily:.0f} daily — extreme overbought (+1.0)")
        elif rsi_daily > 70:
            score += 0.7
            signals.append(f"RSI {rsi_daily:.0f} daily — overbought (+0.7)")
        elif rsi_daily > 65:
            score += 0.3
            signals.append(f"RSI {rsi_daily:.0f} daily — elevated (+0.3)")

        if rsi_4h > 75:
            score += 0.5
            signals.append(f"RSI {rsi_4h:.0f} 4H — overbought (+0.5)")

        # Bearish divergence: price higher high but RSI lower high
        if len(closes) >= 20:
            recent_price_high = max(closes[-5:])
            prev_price_high = max(closes[-15:-5])
            recent_rsi = rsi_daily
            # Approximate: if price made new high but RSI didn't recover
            if recent_price_high > prev_price_high and rsi_daily < 65:
                score += 0.7
                signals.append(f"Bearish RSI divergence — price new high but RSI weak (+0.7)")

        # MACD bearish
        if macd_hist < 0:
            score += 0.5
            signals.append(f"MACD bearish ({macd_hist:+.5f}) (+0.5)")

        # Bollinger upper band
        if bb_position == "upper":
            score += 0.5
            signals.append(f"Price at Bollinger upper band — overbought (+0.5)")

        # Stage
        if stage == 5:
            score += 1.0
            signals.append(f"Stage 5 — active distribution (+1.0)")
        elif stage == 4:
            score += 0.7
            signals.append(f"Stage 4 — parabolic, no entries (+0.7)")

        # Volume on red candle
        vol_ratio = vol_data.get("ratio", 1.0)
        if klines:
            last = klines[-1]
            is_red = float(last[4]) < float(last[1])
            if vol_ratio >= 2.0 and is_red:
                score += 0.5
                signals.append(f"Volume {vol_ratio:.1f}x surge on RED candle — selling pressure (+0.5)")

        # Bearish patterns
        pattern_name = "N/A"
        if klines and len(closes) >= 15:
            p_name, _, _ = _detect_pattern(klines, closes, vol_data)
            bearish = ["Head and Shoulders", "Double Top", "Bear Flag",
                       "Three Black", "Descending", "Rising Wedge"]
            if any(b.lower() in p_name.lower() for b in bearish):
                score += 1.0
                signals.append(f"Pattern: {p_name} (+1.0)")
                pattern_name = p_name

        return min(score, 3.0), signals, pattern_name

    def _score_sell_whale(self, whale_data: dict) -> tuple:
        score = 0.0
        signals = []
        if not whale_data or whale_data.get("error"):
            return 0.0, []

        ws = whale_data.get("score", 0)
        if ws <= -3:
            score += 1.0
            signals.append(f"Whale strongly bearish (score {ws:+d}) (+1.0)")
        elif ws <= -1:
            score += 0.5
            signals.append(f"Whale mildly bearish (score {ws:+d}) (+0.5)")
        elif ws >= 2:
            score -= 0.5
            signals.append(f"Whale bullish — contradicts sell (-0.5)")

        taker = whale_data.get("taker_ratio", 0.5)
        if taker < 0.40:
            score += 0.5
            signals.append(f"Taker {taker:.0%} — aggressive sellers (+0.5)")
        elif taker < 0.45:
            score += 0.3
            signals.append(f"Taker {taker:.0%} — sellers leading (+0.3)")

        if whale_data.get("funding_signal") == "long_squeeze_risk":
            score += 0.5
            signals.append(f"Longs over-leveraged — squeeze risk (+0.5)")

        large_sells = whale_data.get("large_sells", 0)
        large_buys = whale_data.get("large_buys", 0)
        if large_sells > large_buys * 1.5 and large_sells > 200_000:
            score += 0.5
            signals.append(f"Whale sells ${fmt_large(large_sells)} dominating (+0.5)")

        short_liqs = whale_data.get("short_liqs", 0)
        if short_liqs > 1_000_000:
            score += 0.3
            signals.append(f"Short squeeze done ${fmt_large(short_liqs)} — reversal possible (+0.3)")

        return min(score, 2.0), signals

    def _score_sell_macro(self, dxy, yield_data, fng, btc_dom) -> tuple:
        score = 0.0
        signals = []

        if dxy.get("signal") == "bearish":
            score += 0.5
            signals.append(f"DXY rising {dxy.get('change_1d',0):+.3f}% — crypto headwind (+0.5)")
        elif dxy.get("signal") == "bullish":
            score -= 0.3
            signals.append(f"DXY falling — contradicts sell (-0.3)")

        if yield_data.get("signal") == "bearish":
            score += 0.5
            signals.append(f"10Y yield rising — risk-off environment (+0.5)")

        if fng >= 80:
            score += 0.5
            signals.append(f"Extreme greed {fng}/100 — historically best sell zone (+0.5)")
        elif fng >= 65:
            score += 0.3
            signals.append(f"Greed {fng}/100 — elevated risk (+0.3)")
        elif fng <= 20:
            score -= 0.5
            signals.append(f"Extreme fear {fng}/100 — selling into panic is risky (-0.5)")

        if btc_dom > 58:
            score += 0.5
            signals.append(f"BTC.D {btc_dom:.1f}% rising sharply — alts bleeding (+0.5)")

        return min(max(score, -1.0), 2.0), signals

    def _score_options_sell(self, options: dict) -> tuple:
        score = 0.0
        signals = []
        if not options or not options.get("available"):
            return 0.0, []
        pc_signal = options.get("pc_signal", "neutral")
        pc_ratio = options.get("put_call_ratio", 1.0)
        iv_signal = options.get("iv_signal", "normal")
        if pc_signal == "bearish":
            score += 0.5
            signals.append(f"P/C {pc_ratio:.2f} — more puts (bearish options) (+0.5)")
        if iv_signal == "high":
            score += 0.3
            signals.append(f"High IV — elevated fear (+0.3)")
        return min(score, 1.5), signals

    def _score_options_buy(self, options: dict) -> tuple:
        score = 0.0
        signals = []
        if not options or not options.get("available"):
            return 0.0, []
        pc_signal = options.get("pc_signal", "neutral")
        pc_ratio = options.get("put_call_ratio", 1.0)
        iv_signal = options.get("iv_signal", "normal")
        if pc_signal == "bullish":
            score += 0.5
            signals.append(f"P/C {pc_ratio:.2f} — more calls (bullish options) (+0.5)")
        if iv_signal == "low":
            score += 0.5
            signals.append(f"Low IV — calm before storm (+0.5)")
        return min(score, 1.5), signals

    def _score_cvd(self, cvd: dict, direction: str) -> tuple:
        score = 0.0
        signals = []
        if not cvd:
            return 0.0, []
        cvd_signal = cvd.get("signal", "neutral")
        ratio = cvd.get("ratio", 0.5)
        if direction == "BUY":
            if cvd_signal == "bullish":
                score += 0.5
                signals.append(f"CVD {ratio:.0%} buyers — accumulation (+0.5)")
            elif cvd_signal == "bearish":
                score -= 0.3
                signals.append(f"CVD {ratio:.0%} sellers — contradicts buy (-0.3)")
        else:
            if cvd_signal == "bearish":
                score += 0.5
                signals.append(f"CVD {ratio:.0%} sellers — distribution (+0.5)")
            elif cvd_signal == "bullish":
                score -= 0.3
                signals.append(f"CVD {ratio:.0%} buyers — contradicts sell (-0.3)")
        return min(score, 1.0), signals

    def _position_size(self, score: float, direction: str) -> str:
        action = "BUY" if direction == "BUY" else "SELL/EXIT"
        if score >= 9.0:
            return f"Full size — HIGHEST CONVICTION {action}"
        elif score >= 8.0:
            return f"5% to 8% portfolio — HIGH CONVICTION {action}"
        elif score >= 6.5:
            return f"3% to 5% portfolio — STANDARD {action}"
        elif score >= 5.0:
            return f"2% portfolio — CAUTIOUS {action}"
        else:
            return f"1% portfolio — SMALL {action}"

    # ── MAIN SCAN — BOTH DIRECTIONS ───────────────────────────────────────────

    async def scan_coin(self, ticker: str, fng: int, btc_dom: float,
                        dxy: dict, yield_data: dict) -> list:
        """
        Scans for BOTH buy and sell opportunities.
        Returns list of results — can be 0, 1, or 2 alerts per coin.
        """
        alerts = []

        # Fetch all data in parallel
        spot_task      = fetcher.get_ticker(ticker)
        klines_task    = fetcher.get_klines(ticker, 60)
        klines_4h_task = fetcher.binance_klines(ticker, "4h", 60)
        klines_wk_task = fetcher.binance_klines(ticker, "1w", 20)
        whale_task     = whale_detector.full_whale_analysis(ticker)
        cvd_task       = macro_intel.get_cvd(ticker)
        options_task   = macro_intel.get_options_data(ticker)

        spot, klines, klines_4h, klines_wk, whale_data, cvd, options = await asyncio.gather(
            spot_task, klines_task, klines_4h_task, klines_wk_task,
            whale_task, cvd_task, options_task,
            return_exceptions=True
        )

        # Handle exceptions from gather
        spot       = spot       if not isinstance(spot, Exception)       else None
        klines     = klines     if not isinstance(klines, Exception)     else None
        klines_4h  = klines_4h  if not isinstance(klines_4h, Exception)  else None
        klines_wk  = klines_wk  if not isinstance(klines_wk, Exception)  else None
        whale_data = whale_data if not isinstance(whale_data, Exception) else {}
        cvd        = cvd        if not isinstance(cvd, Exception)        else {}
        options    = options    if not isinstance(options, Exception)    else {}

        if not spot or not klines:
            return []

        price = float(spot.get("lastPrice", 0))
        if price == 0:
            return []

        klines_4h = klines_4h or klines
        closes    = [float(k[4]) for k in klines]
        closes_4h = [float(k[4]) for k in klines_4h]

        rsi_daily = _wilder_rsi(closes)
        rsi_4h    = _wilder_rsi(closes_4h)
        support, resistance = _swing_support_resistance(klines)
        vol_data  = _volume_profile(klines)
        trend     = _trend_direction(closes, klines_wk)
        atr       = _atr(klines)
        _, _, macd_hist = _macd(closes)
        bb_upper, bb_mid, bb_lower = _bollinger(closes)
        bb_position = "lower" if price < bb_lower * 1.02 else ("upper" if price > bb_upper * 0.98 else "middle")
        stage, _ = _pump_stage(closes, rsi_daily, 0, vol_data.get("ratio", 1), trend)

        # ── CHECK BUY SETUP ───────────────────────────────────────────────────
        if not self._on_cooldown(ticker, "BUY"):
            # Hard filter: both timeframes bearish = no buy
            if not (trend.get("weekly") == "bearish" and trend.get("daily") == "bearish"):
                if stage not in [4, 5]:
                    tech_s, tech_sig, pattern = self._score_buy_technical(
                        rsi_daily, rsi_4h, klines, closes, vol_data, trend, stage, macd_hist, bb_position
                    )
                    whale_s, whale_sig = self._score_buy_whale(whale_data)
                    macro_s, macro_sig = self._score_buy_macro(dxy, yield_data, fng, btc_dom)
                    opts_s,  opts_sig  = self._score_options_buy(options)
                    cvd_s,   cvd_sig   = self._score_cvd(cvd, "BUY")

                    total = round(max(0, tech_s + whale_s + macro_s + opts_s + cvd_s), 2)
                    if trend.get("weekly") == "neutral":
                        total = max(0, total - 0.5)

                    threshold = _fng_buy_threshold(fng)
                    all_pos = [s for s in tech_sig + whale_sig + macro_sig + opts_sig + cvd_sig if "(+" in s]
                    all_neg = [s for s in tech_sig + whale_sig + macro_sig + opts_sig + cvd_sig if "(-" in s]

                    if total >= threshold and len(all_pos) >= 2:
                        entry_low  = max(support * 1.003, price * 0.995) if support > 0 else price * 0.995
                        entry_high = price * 1.012
                        tp1  = resistance if resistance > price * 1.04 else price + (atr * 2.5)
                        tp2  = tp1 + (atr * 3.0)
                        tp3  = tp2 + (atr * 4.0)
                        stop = entry_low - (atr * 1.5) if atr > 0 else (support * 0.97 if support > 0 else price * 0.93)
                        rr   = round((tp1 - entry_low) / (entry_low - stop), 1) if (entry_low - stop) > 0 else 0

                        alerts.append({
                            "direction": "BUY",
                            "ticker": ticker, "price": price,
                            "score": total, "threshold": threshold,
                            "pattern": pattern, "stage": stage,
                            "rsi_daily": rsi_daily,
                            "trend_daily": trend.get("daily"), "trend_weekly": trend.get("weekly"),
                            "vol_ratio": vol_data.get("ratio", 1),
                            "entry_low": entry_low, "entry_high": entry_high,
                            "tp1": tp1, "tp2": tp2, "tp3": tp3, "stop": stop, "rr": rr,
                            "fng": fng, "btc_dom": btc_dom,
                            "position_size": self._position_size(total, "BUY"),
                            "positive_signals": all_pos,
                            "negative_signals": all_neg,
                            "source": spot.get("source", "Binance"),
                            "tech_score": tech_s, "whale_score": whale_s,
                            "macro_score": macro_s, "opts_score": opts_s, "cvd_score": cvd_s,
                        })

        # ── CHECK SELL SETUP ──────────────────────────────────────────────────
        if not self._on_cooldown(ticker, "SELL"):
            # Hard filter: both timeframes bullish = no sell
            if not (trend.get("weekly") == "bullish" and trend.get("daily") == "bullish"):
                tech_s, tech_sig, pattern = self._score_sell_technical(
                    rsi_daily, rsi_4h, klines, closes, vol_data, trend, stage, macd_hist, bb_position
                )
                whale_s, whale_sig = self._score_sell_whale(whale_data)
                macro_s, macro_sig = self._score_sell_macro(dxy, yield_data, fng, btc_dom)
                opts_s,  opts_sig  = self._score_options_sell(options)
                cvd_s,   cvd_sig   = self._score_cvd(cvd, "SELL")

                total = round(max(0, tech_s + whale_s + macro_s + opts_s + cvd_s), 2)
                if trend.get("weekly") == "neutral":
                    total = max(0, total - 0.5)

                threshold = _fng_sell_threshold(fng)
                all_pos = [s for s in tech_sig + whale_sig + macro_sig + opts_sig + cvd_sig if "(+" in s]
                all_neg = [s for s in tech_sig + whale_sig + macro_sig + opts_sig + cvd_sig if "(-" in s]

                if total >= threshold and len(all_pos) >= 2:
                    # Sell levels — target is support, stop is above resistance
                    tp1  = support if support < price * 0.96 else price - (atr * 2.5)
                    tp2  = tp1 - (atr * 2.5)
                    tp3  = tp2 - (atr * 3.0)
                    stop = price + (atr * 1.5)
                    rr   = round((price - tp1) / (stop - price), 1) if (stop - price) > 0 else 0

                    alerts.append({
                        "direction": "SELL",
                        "ticker": ticker, "price": price,
                        "score": total, "threshold": threshold,
                        "pattern": pattern, "stage": stage,
                        "rsi_daily": rsi_daily,
                        "trend_daily": trend.get("daily"), "trend_weekly": trend.get("weekly"),
                        "vol_ratio": vol_data.get("ratio", 1),
                        "tp1": tp1, "tp2": tp2, "tp3": tp3,
                        "stop": stop, "rr": rr,
                        "fng": fng, "btc_dom": btc_dom,
                        "position_size": self._position_size(total, "SELL"),
                        "positive_signals": all_pos,
                        "negative_signals": all_neg,
                        "source": spot.get("source", "Binance"),
                        "tech_score": tech_s, "whale_score": whale_s,
                        "macro_score": macro_s, "opts_score": opts_s, "cvd_score": cvd_s,
                    })

        return alerts

    # ── ALERT FORMATTER ───────────────────────────────────────────────────────

    def format_alert(self, result: dict) -> str:
        score     = result["score"]
        ticker    = result["ticker"]
        direction = result["direction"]
        is_buy    = direction == "BUY"

        if score >= 9.0:
            conviction = "HIGHEST CONVICTION"
            emoji = "🔥" if is_buy else "🔥"
        elif score >= 8.0:
            conviction = "HIGH CONVICTION"
            emoji = "⚡" if is_buy else "⚡"
        elif score >= 6.5:
            conviction = "STRONG SETUP"
            emoji = "✅" if is_buy else "🔴"
        else:
            conviction = "WATCH"
            emoji = "👀"

        direction_emoji = "📈 BUY" if is_buy else "📉 SELL"
        score_bar = "█" * int(score) + "░" * (10 - int(score))

        lines = [
            f"{emoji} SPOT {direction_emoji} ALERT — {ticker}",
            f"{utc_now()}",
            f"{'━'*38}",
            f"",
            f"SCORE    : {score_bar} {score:.1f}/10",
            f"SIGNAL   : {conviction}",
            f"Threshold: {result['threshold']:.1f} (F&G={result['fng']})",
            f"",
            f"Price    : ${fmt_price(result['price'])}",
            f"Stage    : {result['stage']} | Pattern: {result['pattern']}",
            f"Trend    : Daily {result['trend_daily']} | Weekly {result['trend_weekly']}",
            f"Volume   : {result['vol_ratio']:.1f}x average",
            f"",
            f"SCORE BREAKDOWN:",
            f"  Technical : {result['tech_score']:.1f}/3.0",
            f"  Whale     : {result['whale_score']:.1f}/2.0",
            f"  Macro     : {result['macro_score']:.1f}/2.0",
            f"  Options   : {result['opts_score']:.1f}/1.5",
            f"  CVD       : {result['cvd_score']:.1f}/1.0",
            f"",
            f"SIGNALS:",
        ]

        for s in result["positive_signals"][:6]:
            lines.append(f"  {'✅' if is_buy else '🔴'} {s}")

        if result.get("negative_signals"):
            for s in result["negative_signals"][:2]:
                lines.append(f"  ⚠️ {s}")

        lines.append(f"")
        lines.append(f"{'━'*38}")

        if is_buy:
            lines.extend([
                f"ENTRY    : ${fmt_price(result['entry_low'])} — ${fmt_price(result['entry_high'])}",
                f"TP1      : ${fmt_price(result['tp1'])}",
                f"TP2      : ${fmt_price(result['tp2'])}",
                f"TP3      : ${fmt_price(result['tp3'])}",
                f"STOP     : ${fmt_price(result['stop'])} (ATR-based)",
                f"R/R      : 1:{result['rr']}",
            ])
        else:
            lines.extend([
                f"EXIT/SHORT TARGET:",
                f"TP1      : ${fmt_price(result['tp1'])} (sell 40%)",
                f"TP2      : ${fmt_price(result['tp2'])} (sell 40%)",
                f"TP3      : ${fmt_price(result['tp3'])} (final 20%)",
                f"STOP     : ${fmt_price(result['stop'])} (if wrong)",
                f"R/R      : 1:{result['rr']}",
            ])

        lines.extend([
            f"",
            f"POSITION : {result['position_size']}",
            f"Source   : {result['source']}",
            f"",
            f"Run /scan {ticker} for full 6-layer signal.",
            f"{'━'*38}",
            f"Not financial advice.",
        ])

        return "\n".join(lines)


# ── BACKGROUND RUNNER ─────────────────────────────────────────────────────────

async def run_opportunity_scanner(app, user_ids_fn):
    scanner = OpportunityScanner()
    logger.info("Opportunity scanner v5 (bidirectional) started")
    await asyncio.sleep(90)

    while True:
        try:
            user_ids = user_ids_fn()
            if not user_ids:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            fng_data, global_data, dxy, yield_data = await asyncio.gather(
                fetcher.fear_and_greed(),
                fetcher.coingecko_global(),
                macro_intel.get_dxy(),
                macro_intel.get_10y_yield()
            )

            fng = 50
            btc_dom = 50
            if fng_data and fng_data.get("data"):
                fng = int(fng_data["data"][0]["value"])
            if global_data and global_data.get("data"):
                btc_dom = global_data["data"].get("market_cap_percentage", {}).get("btc", 50)

            logger.info(f"Bidirectional scan: F&G={fng} BTC.D={btc_dom:.1f}%")

            for user_id in user_ids:
                watchlist = get_watchlist(user_id)
                for ticker in watchlist:
                    try:
                        alerts = await scanner.scan_coin(ticker, fng, btc_dom, dxy, yield_data)
                        for alert in alerts:
                            scanner._mark(ticker, alert["direction"])
                            msg = scanner.format_alert(alert)
                            try:
                                await app.bot.send_message(chat_id=user_id, text=msg)
                                logger.info(f"Alert: {ticker} {alert['direction']} score={alert['score']}")
                            except Exception as e:
                                logger.error(f"Send error: {e}")
                        await asyncio.sleep(0.8)
                    except Exception as e:
                        logger.error(f"Scan error {ticker}: {e}")

        except Exception as e:
            logger.error(f"Scanner error: {e}")

        await asyncio.sleep(SCAN_INTERVAL)


async def run_single_coin_scan(ticker: str, user_id: int, app):
    """Called by WebSocket fast lane"""
    scanner = OpportunityScanner()
    try:
        fng_data, global_data, dxy, yield_data = await asyncio.gather(
            fetcher.fear_and_greed(),
            fetcher.coingecko_global(),
            macro_intel.get_dxy(),
            macro_intel.get_10y_yield()
        )
        fng = 50
        btc_dom = 50
        if fng_data and fng_data.get("data"):
            fng = int(fng_data["data"][0]["value"])
        if global_data and global_data.get("data"):
            btc_dom = global_data["data"].get("market_cap_percentage", {}).get("btc", 50)

        alerts = await scanner.scan_coin(ticker, fng, btc_dom, dxy, yield_data)
        for alert in alerts:
            msg = scanner.format_alert(alert)
            await app.bot.send_message(chat_id=user_id, text=msg)
            logger.info(f"WebSocket signal: {ticker} {alert['direction']} score={alert['score']}")

    except Exception as e:
        logger.error(f"Single coin scan error {ticker}: {e}")
