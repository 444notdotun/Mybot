"""
LAYER 7 — MACRO INTELLIGENCE
DXY (US Dollar Index) correlation
US 10-Year Treasury Yield
Cumulative Volume Delta (CVD)
CoinGlass Liquidation Heatmap
Deribit Options (Put/Call ratio, Max Pain, IV)

All free APIs. No key required for basic data.
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timezone
from utils.formatter import fmt_price, fmt_large

logger = logging.getLogger(__name__)


class MacroIntelligence:

    async def _get(self, url: str, params: dict = None, headers: dict = None) -> dict:
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(url, params=params, headers=headers) as r:
                    if r.status == 200:
                        ct = r.headers.get("content-type", "")
                        if "json" in ct:
                            return await r.json()
                        return {"text": await r.text()}
            return {}
        except Exception:
            return {}

    # ── DXY — US DOLLAR INDEX ─────────────────────────────────────────────────

    async def get_dxy(self) -> dict:
        """
        DXY from Yahoo Finance API (free, no key).
        DXY rising = crypto bearish pressure.
        DXY falling = crypto bullish tailwind.
        """
        try:
            data = await self._get(
                "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB",
                params={"interval": "1d", "range": "5d"}
            )
            if data and data.get("chart", {}).get("result"):
                result = data["chart"]["result"][0]
                closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                closes = [c for c in closes if c is not None]
                if len(closes) >= 2:
                    current = closes[-1]
                    prev = closes[-2]
                    change_pct = ((current - prev) / prev) * 100
                    change_5d = ((closes[-1] - closes[0]) / closes[0]) * 100

                    signal = "neutral"
                    if change_pct < -0.3:
                        signal = "bullish"   # DXY falling = good for crypto
                    elif change_pct > 0.3:
                        signal = "bearish"   # DXY rising = bad for crypto

                    return {
                        "value": round(current, 2),
                        "change_1d": round(change_pct, 3),
                        "change_5d": round(change_5d, 3),
                        "signal": signal,
                        "score": 0.5 if signal == "bullish" else (-0.5 if signal == "bearish" else 0),
                    }
        except Exception as e:
            logger.debug(f"DXY fetch error: {e}")
        return {"value": 0, "change_1d": 0, "change_5d": 0, "signal": "neutral", "score": 0}

    # ── US 10-YEAR TREASURY YIELD ─────────────────────────────────────────────

    async def get_10y_yield(self) -> dict:
        """
        US 10Y yield from Yahoo Finance (free).
        Rising yields = risk off = crypto pressure.
        Falling yields = risk on = crypto bullish.
        """
        try:
            data = await self._get(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX",
                params={"interval": "1d", "range": "5d"}
            )
            if data and data.get("chart", {}).get("result"):
                result = data["chart"]["result"][0]
                closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                closes = [c for c in closes if c is not None]
                if len(closes) >= 2:
                    current = closes[-1]
                    prev = closes[-2]
                    change = current - prev

                    signal = "neutral"
                    if change < -0.05:
                        signal = "bullish"   # yields falling = risk on
                    elif change > 0.05:
                        signal = "bearish"   # yields rising = risk off

                    return {
                        "value": round(current, 3),
                        "change_1d": round(change, 4),
                        "signal": signal,
                        "score": 0.5 if signal == "bullish" else (-0.3 if signal == "bearish" else 0),
                    }
        except Exception as e:
            logger.debug(f"10Y yield fetch error: {e}")
        return {"value": 0, "change_1d": 0, "signal": "neutral", "score": 0}

    # ── CUMULATIVE VOLUME DELTA ───────────────────────────────────────────────

    async def get_cvd(self, symbol: str) -> dict:
        """
        CVD from Binance aggregate trades.
        Positive CVD = buyers winning (aggressor buys > sells)
        Negative CVD = sellers winning
        Rising CVD with rising price = strong trend
        Falling CVD with rising price = distribution (divergence)
        """
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(
                    f"https://api.binance.com/api/v3/aggTrades",
                    params={"symbol": f"{symbol}USDT", "limit": 500}
                ) as r:
                    if r.status != 200:
                        return {}
                    trades = await r.json()

            if not trades:
                return {}

            buy_vol = 0.0
            sell_vol = 0.0

            for t in trades:
                qty = float(t.get("q", 0))
                price = float(t.get("p", 0))
                dollar_val = qty * price
                is_maker = t.get("m", False)
                # m=True means sell side is maker = buy order came in
                if not is_maker:
                    buy_vol += dollar_val
                else:
                    sell_vol += dollar_val

            cvd = buy_vol - sell_vol
            total = buy_vol + sell_vol
            cvd_ratio = buy_vol / total if total > 0 else 0.5

            signal = "neutral"
            if cvd_ratio > 0.56:
                signal = "bullish"
            elif cvd_ratio < 0.44:
                signal = "bearish"

            return {
                "cvd": round(cvd, 2),
                "buy_vol": round(buy_vol, 2),
                "sell_vol": round(sell_vol, 2),
                "ratio": round(cvd_ratio, 3),
                "signal": signal,
                "score": 0.5 if signal == "bullish" else (-0.5 if signal == "bearish" else 0),
            }
        except Exception as e:
            logger.debug(f"CVD error for {symbol}: {e}")
        return {"cvd": 0, "ratio": 0.5, "signal": "neutral", "score": 0}

    # ── COINGLASS LIQUIDATION HEATMAP ─────────────────────────────────────────

    async def get_liquidation_levels(self, symbol: str) -> dict:
        """
        CoinGlass liquidation data — shows where clustered liquidations sit.
        Price is magnetic toward these levels.
        Large liquidation cluster above price = price will be pulled up to hunt it.
        Large liquidation cluster below = price may wick down to clear it.
        """
        try:
            data = await self._get(
                "https://open-api.coinglass.com/public/v2/liquidation_info",
                params={"symbol": symbol, "interval": "0"}
            )
            if data and data.get("data"):
                d = data["data"]
                return {
                    "long_liq_24h": d.get("longLiquidationUsd24h", 0),
                    "short_liq_24h": d.get("shortLiquidationUsd24h", 0),
                    "source": "coinglass",
                }
        except Exception:
            pass

        # Fallback: estimate from Binance futures
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
                async with s.get(
                    "https://fapi.binance.com/fapi/v1/allForceOrders",
                    params={"symbol": f"{symbol}USDT", "limit": 100}
                ) as r:
                    if r.status == 200:
                        orders = await r.json()
                        long_liqs = sum(
                            float(o.get("origQty", 0)) * float(o.get("price", 0))
                            for o in orders if o.get("side") == "SELL"
                        )
                        short_liqs = sum(
                            float(o.get("origQty", 0)) * float(o.get("price", 0))
                            for o in orders if o.get("side") == "BUY"
                        )
                        return {
                            "long_liq_24h": long_liqs,
                            "short_liq_24h": short_liqs,
                            "source": "binance_futures",
                        }
        except Exception:
            pass

        return {"long_liq_24h": 0, "short_liq_24h": 0, "source": "unavailable"}

    # ── DERIBIT OPTIONS DATA ───────────────────────────────────────────────────

    async def get_options_data(self, symbol: str) -> dict:
        """
        Deribit options — free public API, no key needed.
        Put/Call ratio, implied volatility, max pain.
        Only works for BTC and ETH (most liquid options markets).
        """
        # Deribit only has good data for BTC and ETH
        deribit_symbol = None
        if symbol.upper() == "BTC":
            deribit_symbol = "BTC"
        elif symbol.upper() == "ETH":
            deribit_symbol = "ETH"
        else:
            return {"available": False, "reason": f"Options data only available for BTC and ETH"}

        try:
            # Get all option instruments
            data = await self._get(
                "https://www.deribit.com/api/v2/public/get_instruments",
                params={"currency": deribit_symbol, "kind": "option", "expired": "false"}
            )

            if not data or not data.get("result"):
                return {"available": False}

            instruments = data["result"]

            # Get ticker summary stats
            summary = await self._get(
                "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
                params={"currency": deribit_symbol, "kind": "option"}
            )

            if not summary or not summary.get("result"):
                return {"available": False}

            results = summary["result"]

            # Calculate put/call ratio from open interest
            call_oi = sum(r.get("open_interest", 0) for r in results if "C" in r.get("instrument_name", ""))
            put_oi = sum(r.get("open_interest", 0) for r in results if "P" in r.get("instrument_name", ""))
            pc_ratio = put_oi / call_oi if call_oi > 0 else 1.0

            # Average IV
            ivs = [r.get("mark_iv", 0) for r in results if r.get("mark_iv", 0) > 0]
            avg_iv = sum(ivs) / len(ivs) if ivs else 0

            # Signal from put/call ratio
            pc_signal = "neutral"
            if pc_ratio < 0.7:
                pc_signal = "bullish"   # more calls = market expects up
            elif pc_ratio > 1.3:
                pc_signal = "bearish"   # more puts = market expects down

            # IV signal — low IV = calm before storm
            iv_signal = "low" if avg_iv < 50 else ("high" if avg_iv > 100 else "normal")

            score = 0
            if pc_signal == "bullish":
                score += 0.5
            elif pc_signal == "bearish":
                score -= 0.3

            return {
                "available": True,
                "symbol": deribit_symbol,
                "put_call_ratio": round(pc_ratio, 3),
                "call_oi": round(call_oi, 2),
                "put_oi": round(put_oi, 2),
                "avg_iv": round(avg_iv, 1),
                "pc_signal": pc_signal,
                "iv_signal": iv_signal,
                "score": score,
            }

        except Exception as e:
            logger.debug(f"Deribit options error: {e}")
            return {"available": False, "reason": str(e)[:50]}

    # ── FULL MACRO INTELLIGENCE PULL ──────────────────────────────────────────

    async def full_analysis(self, symbol: str) -> dict:
        """Run all macro checks in parallel"""
        dxy_task = self.get_dxy()
        yield_task = self.get_10y_yield()
        cvd_task = self.get_cvd(symbol)
        liq_task = self.get_liquidation_levels(symbol)
        options_task = self.get_options_data(symbol)

        dxy, yield_data, cvd, liqs, options = await asyncio.gather(
            dxy_task, yield_task, cvd_task, liq_task, options_task
        )

        # Total macro score
        total_score = (
            dxy.get("score", 0) +
            yield_data.get("score", 0) +
            cvd.get("score", 0) +
            options.get("score", 0)
        )

        bias = "neutral"
        if total_score >= 1.0:
            bias = "bullish"
        elif total_score <= -0.8:
            bias = "bearish"

        return {
            "dxy": dxy,
            "yield_10y": yield_data,
            "cvd": cvd,
            "liquidations": liqs,
            "options": options,
            "total_score": round(total_score, 2),
            "bias": bias,
        }

    def format_block(self, data: dict, symbol: str) -> str:
        dxy = data.get("dxy", {})
        y10 = data.get("yield_10y", {})
        cvd = data.get("cvd", {})
        liqs = data.get("liquidations", {})
        opts = data.get("options", {})
        bias = data.get("bias", "neutral")
        score = data.get("total_score", 0)

        bias_emoji = "🟢" if bias == "bullish" else ("🔴" if bias == "bearish" else "⚪")

        lines = [
            f"🌐 MACRO INTELLIGENCE — {symbol}",
            f"{'━'*35}",
            f"Overall Bias : {bias_emoji} {bias.upper()} ({score:+.2f})",
            f"",
            f"DXY          : {dxy.get('value', 'N/A')} ({dxy.get('change_1d', 0):+.3f}%) — {dxy.get('signal', 'N/A')}",
            f"10Y Yield    : {y10.get('value', 'N/A')}% ({y10.get('change_1d', 0):+.4f}) — {y10.get('signal', 'N/A')}",
            f"CVD          : {cvd.get('ratio', 0.5):.0%} buyers — {cvd.get('signal', 'N/A')}",
            f"Long Liqs    : ${fmt_large(liqs.get('long_liq_24h', 0))}",
            f"Short Liqs   : ${fmt_large(liqs.get('short_liq_24h', 0))}",
        ]

        if opts.get("available"):
            lines.extend([
                f"Put/Call     : {opts.get('put_call_ratio', 1):.2f} — {opts.get('pc_signal', 'N/A')}",
                f"Avg IV       : {opts.get('avg_iv', 0):.1f}% — {opts.get('iv_signal', 'N/A')}",
            ])
        else:
            lines.append(f"Options      : {opts.get('reason', 'N/A')}")

        lines.append(f"{'━'*35}")
        return "\n".join(lines)


# Singleton
macro_intel = MacroIntelligence()
