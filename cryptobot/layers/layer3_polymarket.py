"""
LAYER 3 — POLYMARKET INTELLIGENCE
Live prediction market odds. Informed money moves here BEFORE price moves.
Poll every 15–30 min. Flag any +/-15% shift in 24H immediately.
"""

import asyncio
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_large
import config


CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
    "defi", "nft", "solana", "sol", "xrp", "ripple", "coinbase",
    "binance", "sec", "etf", "federal reserve", "fed", "interest rate",
    "fomc", "inflation", "recession", "stablecoin", "usdc", "usdt",
    "halving", "whale", "trump", "election", "regulation"
]

PHASE_LABEL = {
    (0, 30): ("🔵 PHASE 1 — EARLY POSITIONING", "Odds low and potentially rising. Maximum asymmetric upside. Watch carefully."),
    (30, 50): ("🟡 PHASE 1 — BUY ZONE", "Not priced in yet. Entry window is open. Prepare positions."),
    (50, 70): ("🟠 PHASE 2 — PRICING IN", "Partially priced. Reduce new entries, tighten stops."),
    (70, 85): ("🟠 PHASE 2 — LATE PRICING", "Mostly priced in. Manage existing positions only."),
    (85, 95): ("🔴 PHASE 3 — SELL THE NEWS ZONE", "Event essentially confirmed. TAKE PROFITS NOW before announcement."),
    (95, 101): ("🔴 PHASE 3 — FULLY PRICED", "Zero edge left. Sell into any remaining pump."),
}


def _phase(yes_pct: float) -> tuple:
    for (lo, hi), (label, desc) in PHASE_LABEL.items():
        if lo <= yes_pct < hi:
            return label, desc
    return "⚪ UNKNOWN", ""


def _is_crypto_relevant(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in CRYPTO_KEYWORDS)


def _parse_yes_price(market: dict) -> float:
    """Extract YES probability from Polymarket market data"""
    # Gamma API format
    outcomes = market.get("outcomes", "")
    prices = market.get("outcomePrices", "")
    if isinstance(outcomes, str):
        import json
        try:
            outcomes = json.loads(outcomes)
            prices = json.loads(prices) if prices else []
        except Exception:
            pass

    if isinstance(outcomes, list) and isinstance(prices, list):
        for i, o in enumerate(outcomes):
            if str(o).upper() == "YES" and i < len(prices):
                try:
                    return float(prices[i]) * 100
                except Exception:
                    pass

    # Fallback: try clobTokenIds structure
    tokens = market.get("tokens", [])
    for t in tokens:
        if t.get("outcome", "").upper() == "YES":
            try:
                return float(t.get("price", 0)) * 100
            except Exception:
                pass
    return 50.0


class PolymarketLayer:

    async def top_signals(self) -> str:
        ts = utc_now()
        markets = await fetcher.polymarket_markets(limit=30)

        if not markets:
            return (
                f"⚠️ *POLYMARKET — Live fetch failed*\n"
                f"🕐 {ts}\n"
                f"Cannot connect to Polymarket API right now.\n"
                f"Check polymarket.com directly for current odds."
            )

        lines = [
            f"🎯 *LIVE POLYMARKET SIGNALS*",
            f"🕐 {ts}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
        ]

        # Filter for crypto-relevant and active markets
        crypto_markets = []
        other_markets = []

        for m in markets:
            if not m.get("active", True):
                continue
            question = m.get("question", m.get("title", ""))
            vol = float(m.get("volume", m.get("volume24hr", 0)) or 0)
            yes_pct = _parse_yes_price(m)

            if vol < config.MIN_POLY_VOLUME_USD:
                continue

            entry = {
                "question": question,
                "yes_pct": yes_pct,
                "volume": vol,
                "end_date": m.get("endDate", "?")[:10] if m.get("endDate") else "?",
            }

            if _is_crypto_relevant(question):
                crypto_markets.append(entry)
            else:
                other_markets.append(entry)

        # Sort by volume descending
        crypto_markets.sort(key=lambda x: x["volume"], reverse=True)
        other_markets.sort(key=lambda x: x["volume"], reverse=True)

        if crypto_markets:
            lines.append("🔥 *CRYPTO-RELEVANT MARKETS:*\n")
            for m in crypto_markets[:5]:
                phase_label, phase_desc = _phase(m["yes_pct"])
                vol_str = fmt_large(m["volume"])
                lines.extend([
                    f"📋 *{m['question'][:80]}*",
                    f"   YES: *{m['yes_pct']:.1f}%* | Volume: ${vol_str} | Closes: {m['end_date']}",
                    f"   {phase_label}",
                    f"   _{phase_desc}_",
                    f"",
                ])
        else:
            lines.append("_No crypto-relevant Polymarket markets with sufficient volume right now._\n")

        if other_markets:
            lines.append("🌍 *TOP MACRO MARKETS (crypto impact):*\n")
            for m in other_markets[:3]:
                phase_label, _ = _phase(m["yes_pct"])
                lines.extend([
                    f"• *{m['question'][:70]}*",
                    f"  YES: *{m['yes_pct']:.1f}%* | {phase_label}",
                    f"",
                ])

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "*READING THE SIGNALS:*",
            "30–50% rising → 🟢 BUY ZONE (not priced in yet)",
            "85–95% → 🔴 SELL THE NEWS (take profits before resolve)",
            "+15% shift in 24H → 🚨 Informed money moving — act fast",
        ])

        return "\n".join(lines)

    def get_macro_correlation(self, event_type: str) -> str:
        """Return historical crypto impact for known event types"""
        correlations = {
            "fed_cut": "📈 BULLISH — Avg BTC +15% to +30% on confirmed cut. Watch for bull flags on BTC/ETH daily.",
            "fed_hike": "📉 BEARISH — Risk-off. Tighten all stops. Reduce exposure. Watch for H&S patterns.",
            "etf_approval": "🚀 EXTREMELY BULLISH — Halo effect on entire market. Ref: BTC ETF Jan 2024 → market-wide rally.",
            "election_friendly": "🟢 BULLISH — Exchange tokens, DeFi, coins with regulatory issues benefit most.",
            "election_hostile": "🔴 BEARISH — XRP, privacy coins, DeFi tokens hit hardest. BTC more resilient.",
            "exchange_shutdown": "🚨 PANIC — 30%+ market-wide drop possible. Ref: FTX collapse.",
            "stablecoin_depeg": "☠️ IMMEDIATE SELL — All positions. Ref: LUNA/UST → 70%+ market drop.",
            "recession": "⚠️ SHORT-TERM BEARISH then MEDIUM-TERM BULLISH — Liquidity injection follows. Ref: COVID crash → 10x recovery.",
        }
        return correlations.get(event_type, "⚪ No direct correlation mapped for this event type.")
