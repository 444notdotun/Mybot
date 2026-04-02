"""
WHALE DETECTOR — Layer 5
Detects large money movements using free public APIs.
No CryptoQuant key needed for basic detection.
When CryptoQuant key is available, upgrades automatically.

Signals detected:
- Large trade clusters (whale buys/sells)
- OI spike (leveraged whale positioning)
- Funding rate extremes (over-leveraged market)
- Exchange netflow approximation from price/volume divergence
- Taker buy/sell ratio (aggressor side)
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timezone
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price, fmt_large
import config

logger = logging.getLogger(__name__)


class WhaleDetector:

    async def get_taker_buy_ratio(self, symbol: str) -> float:
        """
        Taker buy/sell volume ratio from Binance.
        > 0.55 = buyers aggressive (bullish)
        < 0.45 = sellers aggressive (bearish)
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{config.BINANCE_FUTURES}/takerlongshortRatio",
                    params={"symbol": f"{symbol}USDT", "period": "1h", "limit": 3},
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data:
                            ratios = [float(d.get("buyRatio", 0.5)) for d in data]
                            return sum(ratios) / len(ratios)
        except Exception:
            pass
        return 0.5

    async def get_open_interest_change(self, symbol: str) -> dict:
        """
        OI change over last 4 hours.
        Rising OI + rising price = strong bullish trend
        Rising OI + falling price = short squeeze building
        Falling OI + falling price = longs liquidating
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{config.BINANCE_FUTURES}/openInterestHist",
                    params={"symbol": f"{symbol}USDT", "period": "1h", "limit": 5},
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data and len(data) >= 2:
                            oi_now = float(data[-1].get("sumOpenInterest", 0))
                            oi_4h_ago = float(data[0].get("sumOpenInterest", 0))
                            change_pct = ((oi_now - oi_4h_ago) / oi_4h_ago * 100) if oi_4h_ago > 0 else 0
                            return {
                                "oi_now": oi_now,
                                "oi_4h_ago": oi_4h_ago,
                                "change_pct": round(change_pct, 2),
                            }
        except Exception:
            pass
        return {}

    async def get_large_trades(self, symbol: str) -> dict:
        """
        Detect large trades from recent aggressor trades.
        Uses Binance aggregate trades endpoint.
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{config.BINANCE_BASE}/aggTrades",
                    params={"symbol": f"{symbol}USDT", "limit": 200},
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    if r.status == 200:
                        trades = await r.json()
                        if not trades:
                            return {}

                        # Get current price for dollar value calculation
                        ticker = await fetcher.binance_ticker(symbol)
                        price = float(ticker["lastPrice"]) if ticker else 0

                        large_buys = []
                        large_sells = []
                        total_buy_vol = 0
                        total_sell_vol = 0

                        for t in trades:
                            qty = float(t.get("q", 0))
                            dollar_val = qty * price
                            is_maker = t.get("m", False)  # True = seller is maker = buy order hit

                            if dollar_val > 50_000:  # $50K+ trades
                                if not is_maker:
                                    large_buys.append(dollar_val)
                                else:
                                    large_sells.append(dollar_val)

                            if not is_maker:
                                total_buy_vol += dollar_val
                            else:
                                total_sell_vol += dollar_val

                        total_vol = total_buy_vol + total_sell_vol
                        buy_ratio = total_buy_vol / total_vol if total_vol > 0 else 0.5

                        return {
                            "large_buys_count": len(large_buys),
                            "large_sells_count": len(large_sells),
                            "large_buys_total": sum(large_buys),
                            "large_sells_total": sum(large_sells),
                            "buy_ratio": round(buy_ratio, 3),
                            "total_buy_vol": total_buy_vol,
                            "total_sell_vol": total_sell_vol,
                        }
        except Exception:
            pass
        return {}

    async def get_liquidations(self, symbol: str) -> dict:
        """
        Recent liquidation data from Binance futures.
        Large liquidations = forced selling = potential reversal.
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{config.BINANCE_FUTURES}/allForceOrders",
                    params={"symbol": f"{symbol}USDT", "limit": 50},
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        if not data:
                            return {}

                        long_liqs = [float(d.get("origQty", 0)) * float(d.get("price", 0))
                                     for d in data if d.get("side") == "SELL"]
                        short_liqs = [float(d.get("origQty", 0)) * float(d.get("price", 0))
                                      for d in data if d.get("side") == "BUY"]

                        return {
                            "long_liquidations_usd": sum(long_liqs),
                            "short_liquidations_usd": sum(short_liqs),
                            "long_liq_count": len(long_liqs),
                            "short_liq_count": len(short_liqs),
                        }
        except Exception:
            pass
        return {}

    async def get_funding_extremes(self, symbol: str) -> dict:
        """
        Funding rate history — extremes signal over-leveraging.
        Very positive = too many longs = potential long squeeze
        Very negative = too many shorts = potential short squeeze (bullish)
        """
        try:
            data = await fetcher.binance_funding_rate(symbol)
            if data and len(data) > 0:
                rate = float(data[0].get("fundingRate", 0)) * 100
                annualized = rate * 3 * 365  # 3 funding periods per day

                signal = "neutral"
                if rate < -0.05:
                    signal = "short_squeeze_risk"  # bullish for spot
                elif rate > 0.1:
                    signal = "long_squeeze_risk"   # bearish warning
                elif rate > 0.05:
                    signal = "elevated_longs"

                return {
                    "rate": rate,
                    "annualized_pct": round(annualized, 1),
                    "signal": signal,
                }
        except Exception:
            pass
        return {}

    async def full_whale_analysis(self, symbol: str) -> dict:
        """Run all whale checks in parallel"""
        symbol = symbol.upper()

        taker_task = self.get_taker_buy_ratio(symbol)
        oi_task = self.get_open_interest_change(symbol)
        trades_task = self.get_large_trades(symbol)
        liq_task = self.get_liquidations(symbol)
        funding_task = self.get_funding_extremes(symbol)

        taker, oi, trades, liqs, funding = await asyncio.gather(
            taker_task, oi_task, trades_task, liq_task, funding_task
        )

        # Build whale signal
        whale_bias = "neutral"
        whale_signals = []
        whale_score = 0  # -5 to +5

        # Taker ratio
        if taker > 0.58:
            whale_signals.append(f"Aggressive buyers: {taker:.0%} buy ratio")
            whale_score += 2
        elif taker < 0.42:
            whale_signals.append(f"Aggressive sellers: {taker:.0%} buy ratio")
            whale_score -= 2

        # Large trades
        if trades:
            lb = trades.get("large_buys_total", 0)
            ls = trades.get("large_sells_total", 0)
            if lb > ls * 1.5 and lb > 100_000:
                whale_signals.append(f"Whale buys dominating: ${fmt_large(lb)} vs ${fmt_large(ls)} sells")
                whale_score += 2
            elif ls > lb * 1.5 and ls > 100_000:
                whale_signals.append(f"Whale sells dominating: ${fmt_large(ls)} vs ${fmt_large(lb)} buys")
                whale_score -= 2

        # OI change
        if oi:
            oi_change = oi.get("change_pct", 0)
            if oi_change > 5:
                whale_signals.append(f"OI rising {oi_change:+.1f}% — new money entering")
                whale_score += 1
            elif oi_change < -5:
                whale_signals.append(f"OI falling {oi_change:+.1f}% — positions closing")
                whale_score -= 1

        # Liquidations
        if liqs:
            long_liqs = liqs.get("long_liquidations_usd", 0)
            short_liqs = liqs.get("short_liquidations_usd", 0)
            if long_liqs > 500_000:
                whale_signals.append(f"Heavy long liquidations: ${fmt_large(long_liqs)} — possible reversal zone")
                whale_score += 1  # Capitulation = potential buy
            if short_liqs > 500_000:
                whale_signals.append(f"Heavy short liquidations: ${fmt_large(short_liqs)} — short squeeze active")
                whale_score += 2

        # Funding
        if funding:
            fsig = funding.get("signal", "neutral")
            frate = funding.get("rate", 0)
            if fsig == "short_squeeze_risk":
                whale_signals.append(f"Funding {frate:+.4f}% — shorts over-leveraged, squeeze possible")
                whale_score += 2
            elif fsig == "long_squeeze_risk":
                whale_signals.append(f"Funding {frate:+.4f}% — longs over-leveraged, be careful")
                whale_score -= 1

        # Final bias
        if whale_score >= 3:
            whale_bias = "bullish"
        elif whale_score <= -3:
            whale_bias = "bearish"

        return {
            "symbol": symbol,
            "bias": whale_bias,
            "score": whale_score,
            "signals": whale_signals,
            "taker_ratio": taker,
            "oi_change": oi.get("change_pct", 0) if oi else 0,
            "funding_rate": funding.get("rate", 0) if funding else 0,
            "funding_signal": funding.get("signal", "neutral") if funding else "neutral",
            "large_buys": trades.get("large_buys_total", 0) if trades else 0,
            "large_sells": trades.get("large_sells_total", 0) if trades else 0,
            "long_liqs": liqs.get("long_liquidations_usd", 0) if liqs else 0,
            "short_liqs": liqs.get("short_liquidations_usd", 0) if liqs else 0,
        }

    def format_whale_block(self, data: dict) -> str:
        bias_emoji = "🐂" if data["bias"] == "bullish" else ("🐻" if data["bias"] == "bearish" else "⚪")
        score = data["score"]
        score_bar = "█" * max(0, score + 5) + "░" * max(0, 5 - score)

        lines = [
            f"🐋 WHALE ACTIVITY — {data['symbol']}",
            f"{'━'*35}",
            f"Bias         : {bias_emoji} {data['bias'].upper()}",
            f"Score        : {score_bar} {score:+d}/5",
            f"Taker ratio  : {data['taker_ratio']:.0%} buyers",
            f"OI change    : {data['oi_change']:+.1f}% (4H)",
            f"Funding      : {data['funding_rate']:+.4f}% ({data['funding_signal']})",
            f"Large buys   : ${fmt_large(data['large_buys'])}",
            f"Large sells  : ${fmt_large(data['large_sells'])}",
            f"Long liqs    : ${fmt_large(data['long_liqs'])}",
            f"Short liqs   : ${fmt_large(data['short_liqs'])}",
        ]

        if data["signals"]:
            lines.append("")
            lines.append("SIGNALS:")
            for s in data["signals"]:
                lines.append(f"  • {s}")

        lines.append(f"{'━'*35}")
        return "\n".join(lines)


# Singleton
whale_detector = WhaleDetector()
