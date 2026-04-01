"""
SIGNAL ENGINE — CORE ORCHESTRATOR
Runs all 4 layers in parallel, then calls Claude API to synthesize
into a complete, formatted trade signal.
"""

import asyncio
import aiohttp
from datetime import datetime, timezone

from layers.layer1_macro import MacroLayer
from layers.layer2_alpha import AlphaLayer
from layers.layer3_polymarket import PolymarketLayer
from layers.layer4_patterns import PatternLayer
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price, fmt_pct, fmt_large
import config


SYSTEM_PROMPT = """You are DOTMAN, a crypto trading signal engine. You receive live market data and output ONE direct trade signal.

RULES:
- Use ONLY the numbers provided. Never invent price levels.
- ONE signal. No scenarios. No "it depends."
- If insufficient data: say "NO TRADE — [reason]. Watch for [condition]."
- Format for Telegram. Use *bold* sparingly. No underscores in numbers.

OUTPUT FORMAT for PERPETUAL:
✅ PERP SIGNAL — [COIN] [LONG/SHORT]
Stage: [1-5] | Pattern: [name]
LEVERAGE: [X]x MAX
ENTRY: $[X] — $[Y] (limit order)
TP1: $[X] (+[Y]%) close 40%
TP2: $[X] (+[Y]%) close 40%
TP3: $[X] (+[Y]%) close 20%
STOP: $[X] ([Y]% from entry)
Invalidation: close [above/below] $[X]
Funding: [rate] [impact]
R/R: 1:[X]
Why now: [reason 1] | [reason 2] | [reason 3]
Confidence: [Low/Medium/High]
Set stop BEFORE entering. Max 2% account risk.

OUTPUT FORMAT for SPOT:
✅ SPOT SIGNAL — [COIN]
Stage: [1-5] | Pattern: [name]
BUY ZONE: $[X] — $[Y]
Entry 1 (40%): $[X]
Entry 2 (35%): $[X]
Entry 3 (25%): $[X]
TP1: $[X] (+[Y]%) sell 30%
TP2: $[X] (+[Y]%) sell 40%
TP3: $[X] (+[Y]%) moonbag 30%
STOP: $[X] hard stop on candle close
Hold: [timeframe]
R/R: 1:[X]
Why now: [reason 1] | [reason 2] | [reason 3]
Confidence: [Low/Medium/High]
Never invest more than you can afford to lose."""


class SignalEngine:

    def __init__(self):
        self.macro = MacroLayer()
        self.alpha = AlphaLayer()
        self.poly = PolymarketLayer()
        self.pattern = PatternLayer()

    async def full_scan(self, ticker: str, trade_type: str) -> str:
        ts = utc_now()
        ticker = ticker.upper()

        # Run all 4 layers in parallel
        price_task = self.macro.live_price_block(ticker)
        macro_task = self.macro.full_macro_gate()
        poly_task = self.poly.top_signals()
        pattern_task = self.pattern.analyze(ticker)

        price_block, macro_block, poly_block, pattern_data = await asyncio.gather(
            price_task, macro_task, poly_task, pattern_task
        )

        exchange_block = self.alpha.exchange_symbols(ticker)

        # Build lean context for Claude (avoid 400 token limit errors)
        context = self._build_context(
            ticker, trade_type, ts,
            price_block, macro_block, poly_block, pattern_data
        )

        signal = await self._call_claude(context, ticker, trade_type)

        return (
            f"{price_block}\n\n"
            f"{exchange_block}\n\n"
            f"{signal}"
        )

    def _build_context(self, ticker, trade_type, ts,
                       price_block, macro_block, poly_block, pattern_data) -> str:
        """Build lean context — only essential data to avoid token limit"""

        # Extract just the key macro verdict line
        macro_lines = macro_block.split('\n')
        macro_summary = '\n'.join([l for l in macro_lines if any(
            kw in l for kw in ['BTC Live', 'BTC 24H', 'Fear', 'Dominance', 'VERDICT', 'GREEN', 'YELLOW', 'RED', 'Altseason']
        )])[:600]

        # Pattern data summary
        pattern_str = ""
        if isinstance(pattern_data, dict) and "error" not in pattern_data:
            pattern_str = (
                f"RSI(14,D)={pattern_data.get('rsi_daily', 0):.1f} "
                f"RSI(4H)={pattern_data.get('rsi_4h', 0):.1f} "
                f"Support=${fmt_price(pattern_data.get('support', 0))} "
                f"Resistance=${fmt_price(pattern_data.get('resistance', 0))} "
                f"Funding={pattern_data.get('funding_rate', 0):+.4f}% "
                f"Pattern={pattern_data.get('pattern', 'N/A')} "
                f"Stage={pattern_data.get('stage', 'N/A')} "
                f"PriceVsSupport={pattern_data.get('price_vs_support_pct', 0):.1f}% "
                f"PriceVsResistance={pattern_data.get('price_vs_resistance_pct', 0):.1f}%"
            )

        # Extract price line only
        price_lines = price_block.split('\n')
        price_summary = '\n'.join(price_lines[:8])[:400]

        # Poly: first 600 chars only
        poly_summary = poly_block[:600]

        return (
            f"COIN: {ticker} | TYPE: {trade_type.upper()} | TIME: {ts}\n\n"
            f"PRICE DATA:\n{price_summary}\n\n"
            f"MACRO:\n{macro_summary}\n\n"
            f"PATTERN: {pattern_str}\n\n"
            f"POLYMARKET SNAPSHOT:\n{poly_summary}\n\n"
            f"Generate the complete {trade_type.upper()} signal for {ticker} using only the data above."
        )

    async def _call_claude(self, context: str, ticker: str, trade_type: str) -> str:
        headers = {
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": config.CLAUDE_MODEL,
            "max_tokens": config.CLAUDE_MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": context}]
        }

        timeout = aiohttp.ClientTimeout(total=30)
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
                    else:
                        err = await resp.text()
                        return (
                            f"⚠️ Claude API error ({resp.status})\n"
                            f"Live data pulled OK — signal synthesis failed.\n"
                            f"Debug: {err[:200]}"
                        )
        except asyncio.TimeoutError:
            return "⚠️ Claude API timeout. Try again."
        except Exception as e:
            return f"⚠️ Signal error: {str(e)[:150]}"

    async def claude_interpret(self, text: str) -> str:
        payload = {
            "model": config.CLAUDE_MODEL,
            "max_tokens": 300,
            "system": (
                "You are DOTMAN, a crypto trading bot on Telegram. "
                "Reply in under 100 words. If user seems to want a coin analysis, "
                "tell them to type just the ticker e.g. SOL or BTC. "
                "Main commands: /macro /scan [TICKER] /alpha /poly /fng /price [TICKER] /stage [TICKER]"
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
                    return "Try /help for available commands."
        except Exception:
            return "Try /help for available commands."
