"""
LAYER 2 — ALPHA HUNTING
Live trending + DEX token discovery.
Finds low-cap plays before they move. Early or nothing.
"""

import asyncio
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price, fmt_pct, fmt_large


# Known futures-listed tickers (avoid flagging large caps as "alpha")
LARGE_CAP_SKIP = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT",
    "LINK", "MATIC", "UNI", "AAVE", "DOGE", "SHIB", "TRX",
    "LTC", "BCH", "ETC", "ATOM", "NEAR", "FTM", "APT", "ARB", "OP"
}


class AlphaLayer:

    async def hunt_alpha(self) -> str:
        ts = utc_now()

        # Pull trending from CoinGecko + DEXScreener in parallel
        trending_task = fetcher.coingecko_trending()
        global_task = fetcher.coingecko_global()

        trending, global_data = await asyncio.gather(trending_task, global_task)

        lines = [
            f"🚀 *LIVE ALPHA HUNT*",
            f"🕐 {ts}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
        ]

        # BTC dominance check for altseason
        dom = 0
        if global_data and global_data.get("data"):
            dom = global_data["data"].get("market_cap_percentage", {}).get("btc", 0)

        if dom < 45:
            lines.append(f"🌊 *ALTSEASON ACTIVE* — BTC.D at {dom:.1f}%. Low caps are the play right now.\n")
        elif dom < 50:
            lines.append(f"🌡️ *ALTSEASON WARMING* — BTC.D at {dom:.1f}%. Capital starting to rotate.\n")

        # CoinGecko trending
        if trending and trending.get("coins"):
            lines.append("📈 *TRENDING NOW (CoinGecko):*")
            candidates = []
            for item in trending["coins"][:7]:
                coin = item.get("item", {})
                name = coin.get("name", "?")
                symbol = coin.get("symbol", "?").upper()
                rank = coin.get("market_cap_rank", "?")
                score = coin.get("score", 0)
                data_24h = coin.get("data", {})
                price_str = data_24h.get("price", "N/A")
                change_str = data_24h.get("price_change_percentage_24h", {})
                change_val = change_str.get("usd", 0) if isinstance(change_str, dict) else 0

                if symbol in LARGE_CAP_SKIP:
                    continue  # Skip large caps

                change_emoji = "🟢" if change_val > 0 else "🔴"
                candidates.append(
                    f"  • *{symbol}* ({name}) — Rank #{rank} — {change_emoji} {fmt_pct(change_val)} 24H"
                )

            if candidates:
                lines.extend(candidates[:5])
            else:
                lines.append("  _Large caps dominating trending — no clear low-cap alpha right now._")

        lines.append("")

        # NFT trending (gives signal on ecosystem activity)
        if trending and trending.get("nfts"):
            top_nft = trending["nfts"][0] if trending["nfts"] else None
            if top_nft:
                lines.append(f"🖼️ Top trending NFT: *{top_nft.get('name', '?')}* — signals NFT meta activity")
                lines.append("")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "*HOW TO TRADE THESE:*",
            "Use `/scan [TICKER]` for full 4-layer signal on any coin above.",
            "Use `/safety [TICKER]` before entering any low-cap play.",
            "",
            "⚠️ HIGH RISK. Max 1–3% portfolio per low-cap play.",
        ])

        return "\n".join(lines)

    async def safety_check(self, ticker: str) -> str:
        """Live safety check — what we can verify via public APIs"""
        ts = utc_now()
        ticker = ticker.upper()

        coin_id = await fetcher.resolve_coin_id(ticker)
        cg = None
        if coin_id:
            cg = await fetcher.coingecko_coin_detail(coin_id)

        lines = [
            f"🛡️ *LIVE SAFETY CHECK — {ticker}*",
            f"🕐 {ts}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if cg and cg.get("market_data"):
            md = cg["market_data"]
            price = md.get("current_price", {}).get("usd", 0)
            vol = md.get("total_volume", {}).get("usd", 0)
            cap = md.get("market_cap", {}).get("usd", 0)
            rank = cg.get("market_cap_rank", "?")

            # Circulating vs total supply
            circ = cg.get("circulating_supply", 0) or 0
            total = cg.get("total_supply", 0) or 1
            float_pct = (circ / total * 100) if total > 0 else 0

            lines.extend([
                f"Live Price         : ${fmt_price(price)}",
                f"Market Cap Rank    : #{rank}",
                f"Market Cap         : ${fmt_large(cap)}",
                f"24H Volume         : ${fmt_large(vol)}",
                f"Circulating Supply : {fmt_large(circ)}",
                f"Float %            : {float_pct:.1f}% of total supply",
                f"",
                f"*VERIFIABLE CHECKS:*",
                f"CoinGecko Listed   : ✅ Yes (verified)" if coin_id else "⚠️ Not found on CoinGecko",
                f"Market Cap > $10M  : {'✅ Yes' if cap > 10_000_000 else '⚠️ Under $10M — very high risk'}",
                f"Daily Vol > $500K  : {'✅ Yes' if vol > 500_000 else '⚠️ Low volume — slippage risk'}",
            ])

            # Community
            community = cg.get("community_data", {}) or {}
            twitter = community.get("twitter_followers", 0) or 0
            lines.append(f"Twitter Followers  : {fmt_large(twitter) if twitter else 'N/A'}")

            # Risk rating
            risk = "🟢 Low"
            if cap < 10_000_000: risk = "🔴 High"
            elif cap < 100_000_000: risk = "🟡 Medium"
            if vol < 100_000: risk = "☠️ Avoid — liquidity too low"

            lines.extend([
                f"",
                f"Overall Risk       : {risk}",
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"⚠️ For contract-level checks (honeypot, mint, ownership),",
                f"verify manually at: rugcheck.xyz & tokensniffer.com",
            ])
        else:
            lines.extend([
                f"⚠️ {ticker} not found on CoinGecko.",
                f"If this is a DEX-only token, provide the contract address",
                f"and check: rugcheck.xyz & tokensniffer.com directly.",
            ])

        return "\n".join(lines)

    def exchange_symbols(self, ticker: str) -> str:
        """Cross-exchange symbol table"""
        t = ticker.upper()
        tl = ticker.lower()
        return (
            f"🏦 *EXCHANGE SYMBOLS — {t}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*BINANCE*\n"
            f"  Spot    : {t}USDT\n"
            f"  Futures : {t}USDT (Futures tab)\n"
            f"  Link    : binance.com/en/trade/{t}_USDT\n\n"
            f"*BYBIT*\n"
            f"  Spot    : {t}USDT\n"
            f"  Perp    : {t}USDT (Derivatives tab)\n"
            f"  Link    : bybit.com/trade/usdt/{t}USDT\n\n"
            f"*OKX*\n"
            f"  Spot    : {t}-USDT\n"
            f"  Perp    : {t}-USDT-SWAP\n"
            f"  Link    : okx.com/trade-spot/{tl}-usdt\n\n"
            f"*KUCOIN*\n"
            f"  Spot    : {t}-USDT\n"
            f"  Futures : {t}USDTM\n"
            f"  Link    : kucoin.com/trade/{t}-USDT\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Always confirm correct tab (Spot vs Futures) before ordering."
        )
