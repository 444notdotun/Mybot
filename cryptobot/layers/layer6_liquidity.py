"""
ORDER BOOK LIQUIDITY CHECKER — Layer 6
Checks real order book depth before any signal fires.
Thin liquidity = higher slippage = signal gets downgraded.
Also detects bid/ask walls (large orders blocking price).
"""

import asyncio
import aiohttp
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price, fmt_large
import config


class LiquidityChecker:

    async def get_order_book(self, symbol: str, depth: int = 20) -> dict:
        """Fetch order book from Binance — no API key needed"""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{config.BINANCE_BASE}/depth",
                    params={"symbol": f"{symbol}USDT", "limit": depth},
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    if r.status == 200:
                        return await r.json()
        except Exception:
            pass
        return {}

    async def analyze_liquidity(self, symbol: str) -> dict:
        """
        Full liquidity analysis:
        - Bid/ask spread
        - Depth within 1%, 2%, 3% of price
        - Large walls (orders 5x+ average)
        - Buy/sell wall imbalance
        """
        symbol = symbol.upper()
        book = await self.get_order_book(symbol, 50)

        if not book or not book.get("bids") or not book.get("asks"):
            return {"error": "No order book data", "symbol": symbol}

        ticker = await fetcher.binance_ticker(symbol)
        if not ticker:
            return {"error": "No price data", "symbol": symbol}

        price = float(ticker["lastPrice"])
        bids = [(float(b[0]), float(b[1])) for b in book["bids"]]
        asks = [(float(a[0]), float(a[1])) for a in book["asks"]]

        if not bids or not asks:
            return {"error": "Empty order book", "symbol": symbol}

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        spread_pct = ((best_ask - best_bid) / price) * 100

        # Dollar depth within price levels
        def depth_within(orders, price_ref, pct, is_bid):
            total = 0
            for p, q in orders:
                if is_bid:
                    if p >= price_ref * (1 - pct / 100):
                        total += p * q
                else:
                    if p <= price_ref * (1 + pct / 100):
                        total += p * q
            return total

        bid_depth_1pct = depth_within(bids, price, 1, True)
        bid_depth_2pct = depth_within(bids, price, 2, True)
        ask_depth_1pct = depth_within(asks, price, 1, False)
        ask_depth_2pct = depth_within(asks, price, 2, False)

        # Find walls (orders significantly larger than average)
        avg_bid_size = sum(q * p for p, q in bids) / len(bids) if bids else 0
        avg_ask_size = sum(q * p for p, q in asks) / len(asks) if asks else 0

        bid_walls = [(p, q * p) for p, q in bids if q * p > avg_bid_size * 5]
        ask_walls = [(p, q * p) for p, q in asks if q * p > avg_ask_size * 5]

        # Imbalance: ratio of bid to ask depth within 2%
        total_bid_2 = bid_depth_2pct
        total_ask_2 = ask_depth_2pct
        total_both = total_bid_2 + total_ask_2
        imbalance = total_bid_2 / total_both if total_both > 0 else 0.5

        # Liquidity quality rating
        if bid_depth_1pct > 500_000 and spread_pct < 0.1:
            liquidity_rating = "EXCELLENT"
            liquidity_score = 10
        elif bid_depth_1pct > 200_000 and spread_pct < 0.3:
            liquidity_rating = "GOOD"
            liquidity_score = 7
        elif bid_depth_1pct > 50_000 and spread_pct < 1.0:
            liquidity_rating = "MODERATE"
            liquidity_score = 5
        elif bid_depth_1pct > 10_000:
            liquidity_rating = "LOW"
            liquidity_score = 3
        else:
            liquidity_rating = "VERY LOW — HIGH SLIPPAGE RISK"
            liquidity_score = 1

        # Recommended position size based on liquidity
        if liquidity_score >= 7:
            max_position = "Full size — no slippage concern"
        elif liquidity_score >= 5:
            max_position = "Max $10K — moderate slippage above this"
        elif liquidity_score >= 3:
            max_position = "Max $2K — significant slippage above this"
        else:
            max_position = "Max $500 — very thin book, high slippage"

        return {
            "symbol": symbol,
            "price": price,
            "spread_pct": round(spread_pct, 4),
            "bid_depth_1pct": bid_depth_1pct,
            "bid_depth_2pct": bid_depth_2pct,
            "ask_depth_1pct": ask_depth_1pct,
            "ask_depth_2pct": ask_depth_2pct,
            "imbalance": round(imbalance, 3),
            "bid_walls": bid_walls[:3],
            "ask_walls": ask_walls[:3],
            "liquidity_rating": liquidity_rating,
            "liquidity_score": liquidity_score,
            "max_position": max_position,
        }

    def format_liquidity_block(self, data: dict) -> str:
        if data.get("error"):
            return f"Liquidity check failed: {data['error']}"

        score = data["liquidity_score"]
        rating = data["liquidity_rating"]
        imbalance = data["imbalance"]
        imb_label = "Buyers dominating" if imbalance > 0.55 else ("Sellers dominating" if imbalance < 0.45 else "Balanced")
        imb_emoji = "🟢" if imbalance > 0.55 else ("🔴" if imbalance < 0.45 else "⚪")

        lines = [
            f"📊 LIQUIDITY DEPTH — {data['symbol']}",
            f"{'━'*35}",
            f"Rating       : {rating}",
            f"Score        : {score}/10",
            f"Spread       : {data['spread_pct']:.4f}%",
            f"Bid depth 1% : ${fmt_large(data['bid_depth_1pct'])}",
            f"Ask depth 1% : ${fmt_large(data['ask_depth_1pct'])}",
            f"Bid depth 2% : ${fmt_large(data['bid_depth_2pct'])}",
            f"Imbalance    : {imb_emoji} {imbalance:.0%} bids — {imb_label}",
            f"Max position : {data['max_position']}",
        ]

        if data["bid_walls"]:
            lines.append("")
            lines.append("BID WALLS (support):")
            for p, v in data["bid_walls"][:2]:
                lines.append(f"  ${fmt_price(p)} — ${fmt_large(v)}")

        if data["ask_walls"]:
            lines.append("")
            lines.append("ASK WALLS (resistance):")
            for p, v in data["ask_walls"][:2]:
                lines.append(f"  ${fmt_price(p)} — ${fmt_large(v)}")

        lines.append(f"{'━'*35}")
        return "\n".join(lines)

    def get_position_size_recommendation(self, liquidity_score: int, portfolio_pct: float = 0.05) -> str:
        """
        Adjust position size recommendation based on liquidity.
        Lower liquidity = smaller position.
        """
        if liquidity_score >= 8:
            return f"Full {portfolio_pct*100:.0f}% position — excellent liquidity"
        elif liquidity_score >= 6:
            return f"{portfolio_pct*0.7*100:.0f}% position — good liquidity, slight reduction"
        elif liquidity_score >= 4:
            return f"{portfolio_pct*0.4*100:.0f}% position — moderate liquidity, reduce size"
        else:
            return f"{portfolio_pct*0.15*100:.0f}% position — thin liquidity, small position only"


# Singleton
liquidity_checker = LiquidityChecker()
