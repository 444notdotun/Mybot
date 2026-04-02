"""
SIGNAL ENGINE — FULL 6-LAYER ORCHESTRATOR
Layer 1: Macro gate (BTC, ETH, F&G, dominance)
Layer 2: Alpha + exchange symbols
Layer 3: Polymarket event odds
Layer 4: Pattern recognition (Wilder RSI, swing S/R, ATR, MACD, BB, trend)
Layer 5: Whale detection (taker ratio, OI, large trades, liquidations, funding)
Layer 6: Liquidity depth (order book, spread, walls, position sizing)
+ Backtest confidence boost from signal history
"""

import asyncio
import aiohttp
from datetime import datetime, timezone

from layers.layer1_macro import MacroLayer
from layers.layer2_alpha import AlphaLayer
from layers.layer3_polymarket import PolymarketLayer
from layers.layer4_patterns import PatternLayer
from layers.layer5_whale import whale_detector
from layers.layer6_liquidity import liquidity_checker
from core.data_fetcher import fetcher, utc_now
from core.backtest_engine import get_pattern_confidence_boost
from utils.formatter import fmt_price, fmt_large
import config


SYSTEM_PROMPT = """You are DOTMAN, an elite crypto trading signal engine with 6 layers of live data.

DATA YOU RECEIVE:
- Layer 1: Live price, macro gate (BTC dominance, Fear & Greed, funding, OI)
- Layer 2: Exchange symbols
- Layer 3: Polymarket event odds
- Layer 4: Technical patterns (Wilder RSI, swing support/resistance, ATR, MACD, Bollinger Bands, pump stage, multi-timeframe trend)
- Layer 5: Whale activity (taker buy ratio, OI change, large trades, liquidations, funding signal)
- Layer 6: Order book liquidity (depth, spread, bid/ask walls, position size recommendation)

ABSOLUTE RULES:
1. Use ONLY numbers from the data provided. Never invent levels.
2. ONE direct signal. No "it depends." No multiple scenarios.
3. If macro gate is RED and whale bias is bearish: output NO TRADE with clear reason.
4. Include whale and liquidity data in your reasoning — these are the edge.
5. Position size from Layer 6 liquidity rating overrides any default sizing.
6. ATR-based stop from Layer 4 overrides fixed % stops.
7. If confidence boost from backtest is below 0.7: reduce confidence rating.
8. Format for Telegram plain text. No markdown symbols except for signal headers.

SPOT SIGNAL FORMAT:
✅ SPOT SIGNAL — [COIN]
[timestamp]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stage     : [1-5] | Pattern: [name]
Trend     : Daily [bullish/bearish] | Weekly [bullish/bearish]
Whale     : [bias] — [key whale signal]
Liquidity : [rating] — [position guidance]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUY ZONE  : $[X] — $[Y]
Entry 1 (40%) : $[X]
Entry 2 (35%) : $[X]
Entry 3 (25%) : $[X]
TP1 : $[X] (+[Y]%) — sell 30%
TP2 : $[X] (+[Y]%) — sell 40%
TP3 : $[X] (+[Y]%) — moonbag 30%
STOP : $[X] (ATR-based, hard stop on candle close)
Hold : [timeframe]
R/R  : 1:[X]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why now:
1. [Pattern reason with specific price level]
2. [Whale/on-chain reason]
3. [Macro/sentiment reason]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Confidence : [Low/Medium/High/Highest]
Position   : [from liquidity layer — e.g. "Max $5K — moderate liquidity"]
Not financial advice.

PERP SIGNAL FORMAT:
✅ PERP SIGNAL — [COIN] [LONG/SHORT]
[timestamp]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stage     : [1-5] | Pattern: [name]
Trend     : Daily [direction] | Weekly [direction]
Whale     : [bias] — [key signal]
Funding   : [rate]% — [long/short paying]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LEVERAGE : [X]x MAX
ENTRY    : $[X] — $[Y] (LIMIT ORDER only)
TP1 : $[X] (+[Y]%) close 40%
TP2 : $[X] (+[Y]%) close 40%
TP3 : $[X] (+[Y]%) close 20%
STOP : $[X] — set BEFORE opening position
Liq  : $[X] at [Y]x with 2% account
R/R  : 1:[X]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why now:
1. [Technical reason]
2. [Whale/funding reason]
3. [Macro reason]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Confidence : [Low/Medium/High/Highest]
Max 2% account risk. Set stop first.
Not financial advice."""


class SignalEngine:

    def __init__(self):
        self.macro  = MacroLayer()
        self.alpha  = AlphaLayer()
        self.poly   = PolymarketLayer()
        self.pattern = PatternLayer()

    async def full_scan(self, ticker: str, trade_type: str) -> str:
        ts = utc_now()
        ticker = ticker.upper()

        # ── RUN ALL 6 LAYERS IN PARALLEL ─────────────────────────────────────
        results = await asyncio.gather(
            self.macro.live_price_block(ticker),
            self.macro.full_macro_gate(),
            self.poly.top_signals(),
            self.pattern.analyze(ticker),
            whale_detector.full_whale_analysis(ticker),
            liquidity_checker.analyze_liquidity(ticker),
            return_exceptions=True
        )

        price_block  = results[0] if not isinstance(results[0], Exception) else "Price data unavailable"
        macro_block  = results[1] if not isinstance(results[1], Exception) else "Macro data unavailable"
        poly_block   = results[2] if not isinstance(results[2], Exception) else "Polymarket unavailable"
        pattern_data = results[3] if not isinstance(results[3], Exception) else {}
        whale_data   = results[4] if not isinstance(results[4], Exception) else {}
        liq_data     = results[5] if not isinstance(results[5], Exception) else {}

        # ── EXCHANGE SYMBOLS ──────────────────────────────────────────────────
        exchange_block = self.alpha.exchange_symbols(ticker)

        # ── BACKTEST CONFIDENCE BOOST ─────────────────────────────────────────
        stage   = pattern_data.get("stage", 1)   if isinstance(pattern_data, dict) else 1
        pattern = pattern_data.get("pattern", "") if isinstance(pattern_data, dict) else ""
        conf_boost = get_pattern_confidence_boost(pattern, stage, "GREEN")

        # ── BUILD CONTEXT ─────────────────────────────────────────────────────
        context = self._build_context(
            ticker, trade_type, ts,
            price_block, macro_block, poly_block,
            pattern_data, whale_data, liq_data, conf_boost
        )

        # ── CALL CLAUDE ───────────────────────────────────────────────────────
        signal = await self._call_claude(context, ticker, trade_type)

        # ── ASSEMBLE FULL OUTPUT ──────────────────────────────────────────────
        whale_block = whale_detector.format_whale_block(whale_data) if whale_data and not whale_data.get("error") else ""
        liq_block   = liquidity_checker.format_liquidity_block(liq_data) if liq_data and not liq_data.get("error") else ""

        parts = [price_block, exchange_block]
        if whale_block:
            parts.append(whale_block)
        if liq_block:
            parts.append(liq_block)
        parts.append(signal)

        return "\n\n".join(p for p in parts if p)

    def _build_context(self, ticker, trade_type, ts,
                       price_block, macro_block, poly_block,
                       pattern_data, whale_data, liq_data, conf_boost=1.0) -> str:

        # Macro summary — key lines only
        macro_lines = macro_block.split('\n') if macro_block else []
        macro_summary = '\n'.join(l for l in macro_lines if any(
            kw in l for kw in ['BTC', 'Fear', 'Dominance', 'VERDICT', 'GREEN', 'YELLOW', 'RED', 'Altseason']
        ))[:500]

        # Pattern summary
        p = pattern_data if isinstance(pattern_data, dict) else {}
        pattern_str = (
            f"Stage={p.get('stage','?')} "
            f"Pattern={p.get('pattern','?')} "
            f"RSI_D={p.get('rsi_daily',0):.1f} "
            f"RSI_4H={p.get('rsi_4h',0):.1f} "
            f"Support=${fmt_price(p.get('support',0))} "
            f"Resistance=${fmt_price(p.get('resistance',0))} "
            f"ATR=${fmt_price(p.get('atr',0))} "
            f"ATR_Stop=${fmt_price(p.get('atr_stop',0))} "
            f"Trend_D={p.get('trend_daily','?')} "
            f"Trend_W={p.get('trend_weekly','?')} "
            f"TrendAligned={p.get('trend_aligned',False)} "
            f"MACD_hist={p.get('macd_hist',0):+.5f} "
            f"BB={p.get('bb_position','?')} "
            f"Vol_ratio={p.get('vol_ratio',1):.1f}x "
            f"Vol_trend={p.get('vol_trend','?')} "
            f"Funding={p.get('funding_rate',0):+.4f}% "
            f"PvsSupport={p.get('price_vs_support_pct',0):.1f}% "
            f"PvsResistance={p.get('price_vs_resistance_pct',0):.1f}%"
        )

        # Whale summary
        w = whale_data if isinstance(whale_data, dict) else {}
        whale_str = (
            f"Bias={w.get('bias','neutral')} "
            f"Score={w.get('score',0):+d} "
            f"TakerRatio={w.get('taker_ratio',0.5):.0%} "
            f"OI_4h={w.get('oi_change',0):+.1f}% "
            f"Funding={w.get('funding_rate',0):+.4f}% ({w.get('funding_signal','neutral')}) "
            f"LargeBuys=${fmt_large(w.get('large_buys',0))} "
            f"LargeSells=${fmt_large(w.get('large_sells',0))} "
            f"LongLiqs=${fmt_large(w.get('long_liqs',0))} "
            f"ShortLiqs=${fmt_large(w.get('short_liqs',0))}"
        ) if w else "No whale data"

        # Liquidity summary
        liq = liq_data if isinstance(liq_data, dict) and not liq_data.get("error") else {}
        liq_str = (
            f"Rating={liq.get('liquidity_rating','?')} "
            f"Score={liq.get('liquidity_score',5)}/10 "
            f"Spread={liq.get('spread_pct',0):.4f}% "
            f"BidDepth1%=${fmt_large(liq.get('bid_depth_1pct',0))} "
            f"AskDepth1%=${fmt_large(liq.get('ask_depth_1pct',0))} "
            f"Imbalance={liq.get('imbalance',0.5):.0%}bids "
            f"MaxPos={liq.get('max_position','unknown')}"
        ) if liq else "No liquidity data"

        # Price summary — first 6 lines
        price_summary = '\n'.join(price_block.split('\n')[:7])[:350]

        return (
            f"COIN: {ticker} | TRADE: {trade_type.upper()} | TIME: {ts}\n"
            f"BACKTEST_CONF_BOOST: {conf_boost}x\n\n"
            f"=L1= PRICE:\n{price_summary}\n\n"
            f"=L1= MACRO:\n{macro_summary}\n\n"
            f"=L3= POLYMARKET:\n{poly_block[:400]}\n\n"
            f"=L4= PATTERN: {pattern_str}\n\n"
            f"=L5= WHALE: {whale_str}\n\n"
            f"=L6= LIQUIDITY: {liq_str}\n\n"
            f"Generate ONE complete {trade_type.upper()} signal for {ticker}. "
            f"Use ONLY the numbers above. Apply liquidity position guidance. "
            f"Apply ATR stop. Whale bias must appear in your reasoning."
        )

    async def _call_claude(self, context: str, ticker: str, trade_type: str) -> str:
        headers = {
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": config.CLAUDE_MODEL,
            "max_tokens": 1200,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": context}]
        }
        timeout = aiohttp.ClientTimeout(total=35)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["content"][0]["text"]
                    err = await resp.text()
                    return (
                        f"Signal synthesis failed ({resp.status}).\n"
                        f"Live data pulled successfully — see price and whale blocks above.\n"
                        f"Error: {err[:150]}"
                    )
        except asyncio.TimeoutError:
            return "Claude API timeout. Live data above is valid for manual analysis."
        except Exception as e:
            return f"Signal error: {str(e)[:120]}"

    async def claude_interpret(self, text: str) -> str:
        """Natural language fallback for unrecognized messages"""
        payload = {
            "model": config.CLAUDE_MODEL,
            "max_tokens": 350,
            "system": (
                "You are DOTMAN, an elite crypto trading bot on Telegram. "
                "Be direct and concise — under 150 words. "
                "If the user seems to want a coin analysis, tell them to type just the ticker. "
                "If they ask how to use the bot, list key commands: "
                "/scan [TICKER], /macro, /whale [TICKER], /liq [TICKER], "
                "/signals, /backtest, /ask, /alert [TICKER] [PRICE], /portfolio."
            ),
            "messages": [{"role": "user", "content": text}]
        }
        headers = {
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["content"][0]["text"]
                    return "Try /help for all commands."
        except Exception:
            return "Try /help for all commands."
