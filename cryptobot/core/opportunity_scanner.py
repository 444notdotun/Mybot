"""
OPPORTUNITY SCANNER v3
Uses fixed pattern engine: Wilder RSI, swing S/R, ATR stops,
multi-timeframe trend filter, volume confirmation.
Fires when ANY trigger fires AND trend is not strongly against it.
4-hour cooldown per trigger per coin.
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
from utils.formatter import fmt_price

logger = logging.getLogger(__name__)

SCAN_INTERVAL    = 10 * 60        # 10 minutes
COOLDOWN_SECONDS = 4 * 3600       # 4 hours per trigger per coin


class OpportunityScanner:

    def __init__(self):
        self._cooldowns = {}

    def _on_cooldown(self, ticker: str, trigger: str) -> bool:
        key = (ticker, trigger)
        if key not in self._cooldowns:
            return False
        elapsed = (datetime.now(timezone.utc) - self._cooldowns[key]).total_seconds()
        return elapsed < COOLDOWN_SECONDS

    def _mark(self, ticker: str, trigger: str):
        self._cooldowns[(ticker, trigger)] = datetime.now(timezone.utc)

    # ── TRIGGER CHECKS ────────────────────────────────────────────────────────

    def _check_rsi_oversold(self, rsi_daily: float, rsi_4h: float, trend: dict) -> dict:
        """RSI oversold on daily or 4H — NOT bearish if trend is down"""
        # Don't fire if weekly trend is strongly down
        if trend.get("weekly") == "bearish" and trend.get("daily") == "bearish":
            return {}
        if rsi_daily < 28:
            return {
                "trigger": "RSI_EXTREME_OVERSOLD",
                "title": "EXTREME OVERSOLD",
                "emoji": "🔥",
                "reason": f"Daily RSI {rsi_daily:.0f} — extreme oversold. High probability reversal zone.",
                "urgency": "HIGH",
                "confidence": 8,
            }
        if rsi_4h < 25:
            return {
                "trigger": "RSI_4H_OVERSOLD",
                "title": "4H RSI OVERSOLD",
                "emoji": "📈",
                "reason": f"4H RSI {rsi_4h:.0f} — oversold on 4H with daily not overbought.",
                "urgency": "HIGH",
                "confidence": 7,
            }
        if rsi_daily < 35 and trend.get("daily") != "bearish":
            return {
                "trigger": "RSI_LOW",
                "title": "RSI ENTERING OVERSOLD",
                "emoji": "👀",
                "reason": f"Daily RSI {rsi_daily:.0f} approaching oversold in non-bearish trend.",
                "urgency": "MEDIUM",
                "confidence": 6,
            }
        return {}

    def _check_support_bounce(self, price: float, support: float, klines: list, trend: dict) -> dict:
        """Price bouncing off swing support with a bullish candle"""
        if support == 0:
            return {}
        if trend.get("weekly") == "bearish":
            return {}  # Don't buy bounces in weekly downtrend

        pct_above = ((price - support) / support) * 100
        if pct_above > 4:
            return {}

        # Check last candle type
        if not klines:
            return {}
        last = klines[-1]
        o, h, l, c = float(last[1]), float(last[2]), float(last[3]), float(last[4])
        body = abs(c - o)
        lower_wick = min(o, c) - l
        total_range = h - l

        is_hammer = lower_wick > body * 2 and total_range > 0
        is_bullish = c > o and body / total_range > 0.4 if total_range > 0 else False

        if pct_above <= 2 and is_hammer:
            return {
                "trigger": "HAMMER_SUPPORT",
                "title": "HAMMER AT SUPPORT",
                "emoji": "🔨",
                "reason": f"Hammer candle at swing support ${fmt_price(support)} — strong rejection of lows",
                "urgency": "HIGH",
                "confidence": 8,
            }
        if pct_above <= 3 and is_bullish:
            return {
                "trigger": "SUPPORT_BOUNCE",
                "title": "SUPPORT BOUNCE",
                "emoji": "🛡️",
                "reason": f"Bullish candle {pct_above:.1f}% above swing support ${fmt_price(support)}",
                "urgency": "HIGH",
                "confidence": 7,
            }
        return {}

    def _check_bollinger_squeeze(self, price: float, bb_lower: float, bb_upper: float,
                                  rsi: float, trend: dict) -> dict:
        """Price at or below Bollinger lower band — mean reversion signal"""
        if bb_lower == 0:
            return {}
        if trend.get("weekly") == "bearish":
            return {}

        if price <= bb_lower and rsi < 40:
            return {
                "trigger": "BB_LOWER_BAND",
                "title": "BOLLINGER LOWER BAND",
                "emoji": "📉→📈",
                "reason": f"Price at lower Bollinger Band with RSI {rsi:.0f} — mean reversion setup",
                "urgency": "HIGH",
                "confidence": 7,
            }
        if price < bb_lower * 1.015 and rsi < 45:
            return {
                "trigger": "BB_NEAR_LOWER",
                "title": "NEAR BOLLINGER LOWER",
                "emoji": "📊",
                "reason": f"Price near lower BB, RSI {rsi:.0f} — watch for bounce",
                "urgency": "MEDIUM",
                "confidence": 6,
            }
        return {}

    def _check_macd_cross(self, klines: list, trend: dict) -> dict:
        """MACD bullish crossover — momentum turning"""
        if not klines or len(klines) < 35:
            return {}
        closes = [float(k[4]) for k in klines]

        # Need current and previous MACD
        hist_now = _macd(closes)[2]
        hist_prev = _macd(closes[:-1])[2]

        # Bullish crossover: histogram flips from negative to positive
        if hist_prev < 0 and hist_now > 0:
            if trend.get("daily") != "bearish" or trend.get("weekly") == "bullish":
                return {
                    "trigger": "MACD_CROSS_BULLISH",
                    "title": "MACD BULLISH CROSSOVER",
                    "emoji": "⚡",
                    "reason": "MACD crossed above signal line — momentum turning bullish",
                    "urgency": "HIGH",
                    "confidence": 8,
                }
        # Histogram growing from deeply negative — early momentum shift
        if hist_prev < -0.005 and hist_now > hist_prev * 0.5 and hist_now < 0:
            return {
                "trigger": "MACD_RECOVERING",
                "title": "MACD MOMENTUM RECOVERING",
                "emoji": "📈",
                "reason": "MACD histogram contracting from negative — selling pressure easing",
                "urgency": "MEDIUM",
                "confidence": 5,
            }
        return {}

    def _check_volume_accumulation(self, vol_data: dict, klines: list, trend: dict) -> dict:
        """Unusual volume on green candle — smart money entering"""
        if not klines:
            return {}
        ratio = vol_data.get("ratio", 1.0)
        last = klines[-1]
        is_green = float(last[4]) > float(last[1])

        if ratio >= 2.5 and is_green and trend.get("weekly") != "bearish":
            return {
                "trigger": "VOLUME_SURGE",
                "title": "VOLUME SURGE",
                "emoji": "🌊",
                "reason": f"Volume {ratio:.1f}x average on green candle — institutional accumulation signal",
                "urgency": "HIGH",
                "confidence": 8,
            }
        if ratio >= 1.8 and is_green and trend.get("daily") == "bullish":
            return {
                "trigger": "VOLUME_PICKUP",
                "title": "VOLUME PICKUP",
                "emoji": "📦",
                "reason": f"Volume {ratio:.1f}x average with bullish candle in uptrend",
                "urgency": "MEDIUM",
                "confidence": 6,
            }
        return {}

    def _check_bull_flag(self, klines: list, vol_data: dict, trend: dict) -> dict:
        """Bull flag handle completing with volume confirmation"""
        if not klines or len(klines) < 15:
            return {}
        if trend.get("weekly") == "bearish":
            return {}

        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        pole_start = closes[-12]
        pole_peak = max(closes[-10:-3])
        current = closes[-1]
        pole_gain = (pole_peak - pole_start) / pole_start if pole_start > 0 else 0
        flag_retrace = (pole_peak - current) / pole_peak if pole_peak > 0 else 0

        if pole_gain > 0.07 and 0.03 < flag_retrace < 0.13:
            # Volume MUST be declining in flag
            flag_vols = volumes[-5:]
            declining = flag_vols[-1] < flag_vols[0] * 0.8
            if declining:
                return {
                    "trigger": "BULL_FLAG",
                    "title": "BULL FLAG CONFIRMED",
                    "emoji": "🏁",
                    "reason": f"Bull flag: {pole_gain*100:.1f}% pole, {flag_retrace*100:.1f}% retrace, volume declining — breakout imminent",
                    "urgency": "HIGH",
                    "confidence": 9,
                }
        return {}

    def _check_stage1(self, stage: int, rsi: float, vol_data: dict, trend: dict) -> dict:
        """Stage 1 accumulation — quietest and best entry"""
        if stage == 1 and rsi < 45 and vol_data.get("trend") == "rising":
            if trend.get("weekly") != "bearish":
                return {
                    "trigger": "STAGE1_ACCUMULATION",
                    "title": "STAGE 1 SILENT ACCUMULATION",
                    "emoji": "🐋",
                    "reason": f"Stage 1 with RSI {rsi:.0f} and rising volume — smart money accumulating. Best entry window.",
                    "urgency": "MEDIUM",
                    "confidence": 8,
                }
        return {}

    def _check_macro_alignment(self, fng: int, btc_dom: float) -> dict:
        """Macro conditions turning favorable"""
        if fng <= 20:
            return {
                "trigger": "EXTREME_FEAR",
                "title": "EXTREME FEAR — BUY ZONE",
                "emoji": "😱",
                "reason": f"Fear and Greed at {fng}/100 — extreme fear historically = best buying opportunity",
                "urgency": "HIGH",
                "confidence": 7,
                "market_wide": True,
            }
        if btc_dom < 44 and fng > 40:
            return {
                "trigger": "ALTSEASON_SIGNAL",
                "title": "ALTSEASON SIGNAL",
                "emoji": "🌊",
                "reason": f"BTC dominance {btc_dom:.1f}% — capital rotating into alts",
                "urgency": "MEDIUM",
                "confidence": 7,
                "market_wide": True,
            }
        return {}

    # ── ENTRY LEVEL CALCULATOR ────────────────────────────────────────────────

    def _calc_levels(self, price: float, support: float, resistance: float, atr: float) -> dict:
        """ATR-based dynamic entry, TP, stop levels"""
        # Entry: current price or slight dip
        entry_low = max(support * 1.005, price * 0.995) if support > 0 else price * 0.995
        entry_high = price * 1.012

        # TPs based on resistance and ATR extension
        tp1 = resistance if resistance > price * 1.04 else price + (atr * 2.5)
        tp2 = tp1 + (atr * 3.0)
        tp3 = tp2 + (atr * 4.0)

        # ATR-based stop: 1.5x ATR below entry (tighter than 2x for spot)
        stop = entry_low - (atr * 1.5) if atr > 0 else (support * 0.97 if support > 0 else price * 0.93)

        # Risk/reward
        risk = entry_low - stop
        reward_tp1 = tp1 - entry_low
        rr = reward_tp1 / risk if risk > 0 else 0

        return {
            "entry_low": entry_low,
            "entry_high": entry_high,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "stop": stop,
            "rr": round(rr, 1),
        }

    # ── MAIN COIN SCAN ────────────────────────────────────────────────────────

    async def scan_coin(self, ticker: str, fng: int, btc_dom: float) -> list:
        alerts = []

        # Fetch all data in parallel
        spot_task = fetcher.get_ticker(ticker)
        klines_task = fetcher.get_klines(ticker, 60)
        klines_4h_task = fetcher.binance_klines(ticker, "4h", 60)
        klines_weekly_task = fetcher.binance_klines(ticker, "1w", 20)

        spot, klines, klines_4h, klines_weekly = await asyncio.gather(
            spot_task, klines_task, klines_4h_task, klines_weekly_task
        )

        if not spot or not klines:
            return []

        price = float(spot.get("lastPrice", 0))
        if price == 0:
            return []

        # Use fallback for 4H
        if not klines_4h:
            klines_4h = klines

        closes = [float(k[4]) for k in klines]
        closes_4h = [float(k[4]) for k in klines_4h]

        rsi_daily = _wilder_rsi(closes)
        rsi_4h = _wilder_rsi(closes_4h)
        support, resistance = _swing_support_resistance(klines)
        vol_data = _volume_profile(klines)
        trend = _trend_direction(closes, klines_weekly)
        atr = _atr(klines)
        bb_upper, bb_mid, bb_lower = _bollinger(closes)
        stage, _ = _pump_stage(closes, rsi_daily, 0, vol_data["ratio"], trend)

        levels = self._calc_levels(price, support, resistance, atr)

        # Run all trigger checks
        trigger_checks = [
            self._check_rsi_oversold(rsi_daily, rsi_4h, trend),
            self._check_support_bounce(price, support, klines, trend),
            self._check_bollinger_squeeze(price, bb_lower, bb_upper, rsi_daily, trend),
            self._check_macd_cross(klines, trend),
            self._check_volume_accumulation(vol_data, klines, trend),
            self._check_bull_flag(klines, vol_data, trend),
            self._check_stage1(stage, rsi_daily, vol_data, trend),
        ]

        for result in trigger_checks:
            if not result:
                continue
            trigger_id = result.get("trigger", "")
            if self._on_cooldown(ticker, trigger_id):
                continue
            # Skip if stage 4/5 (distribution) — no spot entries
            if stage in [4, 5] and trigger_id not in ["RSI_EXTREME_OVERSOLD"]:
                continue

            self._mark(ticker, trigger_id)
            alerts.append({
                **result,
                **levels,
                "ticker": ticker,
                "price": price,
                "rsi_daily": rsi_daily,
                "rsi_4h": rsi_4h,
                "stage": stage,
                "trend_daily": trend["daily"],
                "trend_weekly": trend["weekly"],
                "vol_ratio": vol_data["ratio"],
                "fng": fng,
                "btc_dom": btc_dom,
                "atr": atr,
                "source": spot.get("source", "Binance"),
            })

        # Market-wide macro check
        macro = self._check_macro_alignment(fng, btc_dom)
        if macro and macro.get("market_wide") and not self._on_cooldown("MARKET", macro["trigger"]):
            self._mark("MARKET", macro["trigger"])
            alerts.append({
                **macro,
                "ticker": "MARKET",
                "price": 0,
                "entry_low": 0, "entry_high": 0,
                "tp1": 0, "tp2": 0, "tp3": 0, "stop": 0, "rr": 0,
                "fng": fng, "btc_dom": btc_dom,
            })

        return alerts

    def format_alert(self, alert: dict) -> str:
        ticker = alert["ticker"]
        price = alert["price"]
        urgency = alert.get("urgency", "MEDIUM")
        confidence = alert.get("confidence", 5)
        urgency_flag = "🚨" if urgency == "HIGH" else "⚠️"

        if ticker == "MARKET":
            return (
                f"{alert['emoji']} {alert['title']}\n"
                f"{utc_now()}\n"
                f"{'━'*35}\n"
                f"{alert['reason']}\n\n"
                f"Check watchlist for entries.\n"
                f"/macro for full picture."
            )

        trend_daily = alert.get("trend_daily", 'neutral')
        trend_weekly = alert.get("trend_weekly", 'neutral')
        rr = alert.get("rr", 0)
        conf_bar = "█" * confidence + "░" * (10 - confidence)

        lines = [
            f"{alert['emoji']} SPOT OPPORTUNITY — {ticker}",
            f"{urgency_flag} {alert['title']}",
            f"{utc_now()}",
            f"{'━'*35}",
            f"",
            f"Signal   : {alert['reason']}",
            f"",
            f"Price    : ${fmt_price(price)}",
            f"Stage    : {alert.get('stage', '?')} | RSI: {alert.get('rsi_daily', 0):.0f}",
            f"Trend    : Daily {trend_daily} | Weekly {trend_weekly}",
            f"Volume   : {alert.get('vol_ratio', 1):.1f}x average",
            f"F&G      : {alert.get('fng', 50)}/100",
            f"ATR      : ${fmt_price(alert.get('atr', 0))}",
            f"",
            f"ENTRY    : ${fmt_price(alert['entry_low'])} — ${fmt_price(alert['entry_high'])}",
            f"TP1      : ${fmt_price(alert['tp1'])}",
            f"TP2      : ${fmt_price(alert['tp2'])}",
            f"TP3      : ${fmt_price(alert['tp3'])}",
            f"STOP     : ${fmt_price(alert['stop'])} (ATR-based)",
            f"R/R      : 1:{rr}" if rr > 0 else "",
            f"",
            f"Confidence: {conf_bar} {confidence}/10",
            f"Source   : {alert.get('source', 'Binance')}",
            f"",
            f"/scan {ticker} for full 4-layer signal.",
            f"{'━'*35}",
            f"Not financial advice.",
        ]
        return "\n".join(l for l in lines if l is not None)


async def run_opportunity_scanner(app, user_ids_fn):
    scanner = OpportunityScanner()
    logger.info("Opportunity scanner v3 started — scanning every 10 minutes")
    await asyncio.sleep(60)

    while True:
        try:
            user_ids = user_ids_fn()
            if not user_ids:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # Shared macro data
            fng_data = await fetcher.fear_and_greed()
            global_data = await fetcher.coingecko_global()
            fng = 50
            btc_dom = 50

            if fng_data and fng_data.get("data"):
                fng = int(fng_data["data"][0]["value"])
            if global_data and global_data.get("data"):
                btc_dom = global_data["data"].get("market_cap_percentage", {}).get("btc", 50)

            for user_id in user_ids:
                watchlist = get_watchlist(user_id)
                for ticker in watchlist:
                    try:
                        alerts = await scanner.scan_coin(ticker, fng, btc_dom)
                        for alert in alerts:
                            msg = scanner.format_alert(alert)
                            try:
                                await app.bot.send_message(chat_id=user_id, text=msg)
                                logger.info(f"Alert: {ticker} — {alert['trigger']}")
                            except Exception as e:
                                logger.error(f"Send error: {e}")
                        await asyncio.sleep(0.8)
                    except Exception as e:
                        logger.error(f"Error scanning {ticker}: {e}")
                        continue

        except Exception as e:
            logger.error(f"Scanner error: {e}")

        await asyncio.sleep(SCAN_INTERVAL)
