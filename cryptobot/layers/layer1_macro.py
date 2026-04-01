"""
LAYER 1 — MACRO MARKET INTELLIGENCE
Live BTC, ETH, dominance, Fear & Greed, global market conditions.
Uses Binance for price/funding/OI and CoinGecko simple/price for market data.
"""

import asyncio
from datetime import datetime, timezone
from core.data_fetcher import fetcher, utc_now
from utils.formatter import fmt_price, fmt_pct, fmt_large


def _fng_label(score: int) -> str:
    if score >= 80: return "🟢 Extreme Greed"
    if score >= 60: return "🟡 Greed"
    if score >= 40: return "⚪ Neutral"
    if score >= 20: return "🟠 Fear"
    return "🔴 Extreme Fear"


def _macro_verdict(fng: int, btc_change: float, dominance: float) -> str:
    if fng < 25 or btc_change < -5:
        return "🔴 RED LIGHT — Macro hostile. Size down or wait."
    if fng > 75 or btc_change > 10:
        return "⚠️ YELLOW LIGHT — Overheated. Tighten stops, reduce size 50%."
    return "✅ GREEN LIGHT — Macro supports plays. Normal sizing."


# CoinGecko simple/price IDs for enrichment (lightweight endpoint, not rate-limited)
CG_SIMPLE_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
    "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink",
    "MATIC": "matic-network", "TAO": "bittensor", "RENDER": "render-token",
    "RNDR": "render-token", "FET": "fetch-ai", "SUI": "sui",
    "WIF": "dogwifcoin", "BONK": "bonk", "PEPE": "pepe",
    "DOGE": "dogecoin", "SHIB": "shiba-inu", "ARB": "arbitrum",
    "OP": "optimism", "INJ": "injective-protocol", "TIA": "celestia",
    "NEAR": "near", "ATOM": "cosmos", "LTC": "litecoin",
    "ZETA": "zetachain", "DEEP": "deep-book",
}


async def _cg_simple(coin_id: str) -> dict:
    """Lightweight CoinGecko call — much less rate-limited than /coins/{id}"""
    import aiohttp, config
    url = f"{config.COINGECKO_BASE}/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": "usd",
        "include_market_cap": "true",
        "include_24hr_vol": "true",
        "include_24hr_change": "true",
        "include_7d_change": "true",
    }
    if config.COINGECKO_API_KEY:
        params["x_cg_demo_api_key"] = config.COINGECKO_API_KEY
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get(coin_id, {})
    except Exception:
        pass
    return {}


class MacroLayer:

    async def fear_and_greed(self) -> str:
        ts = utc_now()
        data = await fetcher.fear_and_greed()
        if not data or not data.get("data"):
            return f"⚠️ Live fetch failed for Fear and Greed Index.\n{ts}"
        entry = data["data"][0]
        score = int(entry["value"])
        label = entry["value_classification"]
        emoji = _fng_label(score)
        note = ""
        if score < 25:
            note = "Extreme Fear — Buy zone historically. Accumulation signal."
        elif score > 75:
            note = "Extreme Greed — Distribution zone. Take profits now."
        else:
            note = "Neutral — No strong sentiment edge right now."
        return (
            f"FEAR AND GREED INDEX — LIVE\n"
            f"{ts}\n"
            f"Score     : {score}/100\n"
            f"Sentiment : {emoji} {label}\n"
            f"{note}"
        )

    async def live_price_block(self, ticker: str) -> str:
        ts = utc_now()
        ticker = ticker.upper()

        # Run Binance calls + CoinGecko simple in parallel
        coin_id = CG_SIMPLE_IDS.get(ticker)
        spot_task = fetcher.binance_ticker(ticker)
        cg_task = _cg_simple(coin_id) if coin_id else asyncio.sleep(0, result={})
        funding_task = fetcher.binance_funding_rate(ticker)
        oi_task = fetcher.binance_open_interest(ticker)
        klines_task = fetcher.binance_klines(ticker, "1d", 10)

        spot, cg, funding_list, oi, klines = await asyncio.gather(
            spot_task, cg_task, funding_task, oi_task, klines_task
        )

        # CoinGecko enrichment
        market_cap = fmt_large(cg.get("usd_market_cap", 0)) if cg else "N/A"
        change_7d = fmt_pct(cg.get("usd_7d_change", 0)) if cg and cg.get("usd_7d_change") else "N/A"

        if not spot:
            if cg:
                price = cg.get("usd", 0)
                change_24h = cg.get("usd_24h_change", 0) or 0
                vol_24h = cg.get("usd_24h_vol", 0) or 0
                return (
                    f"LIVE PRICE ACTION — {ticker}\n"
                    f"{ts} — refresh before acting\n"
                    f"Price (USD)   : ${fmt_price(price)}\n"
                    f"24H Change    : {fmt_pct(change_24h)}\n"
                    f"24H Volume    : ${fmt_large(vol_24h)}\n"
                    f"7D Change     : {change_7d}\n"
                    f"Market Cap    : ${market_cap}\n"
                    f"Source: CoinGecko (Binance unavailable for {ticker})"
                )
            return f"Cannot fetch live data for {ticker}. Check CoinGecko or DEXScreener directly."

        price = float(spot["lastPrice"])
        change_24h = float(spot["priceChangePercent"])
        high_24h = float(spot["highPrice"])
        low_24h = float(spot["lowPrice"])
        vol_24h = float(spot["quoteVolume"])

        # Funding rate
        funding_str = "N/A"
        funding_bias = ""
        if funding_list and len(funding_list) > 0:
            fr = float(funding_list[0].get("fundingRate", 0)) * 100
            funding_str = f"{fr:+.4f}%"
            funding_bias = "Bullish" if fr < 0 else ("Bearish" if fr > 0.05 else "Neutral")

        # Open interest
        oi_str = "N/A"
        if oi and oi.get("openInterest"):
            oi_val = float(oi["openInterest"]) * price
            oi_str = f"${fmt_large(oi_val)}"

        # Candle direction
        candle_dir = "N/A"
        if klines and len(klines) >= 2:
            last = klines[-1]
            o, c = float(last[1]), float(last[4])
            if c > o * 1.005: candle_dir = "Bullish"
            elif c < o * 0.995: candle_dir = "Bearish"
            else: candle_dir = "Doji"

        return (
            f"LIVE PRICE ACTION — {ticker}\n"
            f"{ts} — refresh before acting\n"
            f"Price (USD)      : ${fmt_price(price)}\n"
            f"24H Change       : {fmt_pct(change_24h)}\n"
            f"24H High         : ${fmt_price(high_24h)}\n"
            f"24H Low          : ${fmt_price(low_24h)}\n"
            f"24H Volume       : ${fmt_large(vol_24h)}\n"
            f"7D Change        : {change_7d}\n"
            f"Market Cap       : ${market_cap}\n"
            f"Current candle   : {candle_dir} (Daily)\n"
            f"Funding rate     : {funding_str} {funding_bias}\n"
            f"Open Interest    : {oi_str}"
        )

    async def full_macro_gate(self) -> str:
        ts = utc_now()

        btc_task = fetcher.binance_ticker("BTC")
        eth_task = fetcher.binance_ticker("ETH")
        fng_task = fetcher.fear_and_greed()
        global_task = fetcher.coingecko_global()
        btc_funding_task = fetcher.binance_funding_rate("BTC")
        btc_oi_task = fetcher.binance_open_interest("BTC")

        btc, eth, fng_data, global_data, btc_funding, btc_oi = await asyncio.gather(
            btc_task, eth_task, fng_task, global_task, btc_funding_task, btc_oi_task
        )

        btc_price = float(btc["lastPrice"]) if btc else 0
        btc_change = float(btc["priceChangePercent"]) if btc else 0
        btc_trend = "Bullish" if btc_change > 1 else ("Bearish" if btc_change < -1 else "Neutral")

        eth_price = float(eth["lastPrice"]) if eth else 0
        eth_btc = (eth_price / btc_price) if btc_price > 0 else 0
        eth_btc_note = "Rising — Altcoin positive" if eth_btc > 0.055 else "Falling — BTC dominant"

        dominance = 0
        total_cap = 0
        if global_data and global_data.get("data"):
            gd = global_data["data"]
            dominance = gd.get("market_cap_percentage", {}).get("btc", 0)
            total_cap = gd.get("total_market_cap", {}).get("usd", 0)
        dom_note = "Rising — Altcoins weak" if dominance > 55 else ("Falling — Altseason forming" if dominance < 45 else "Neutral")

        fng_score = 50
        fng_label = "Neutral"
        if fng_data and fng_data.get("data"):
            fng_score = int(fng_data["data"][0]["value"])
            fng_label = fng_data["data"][0]["value_classification"]
        fng_emoji = _fng_label(fng_score)

        btc_fr = "N/A"
        if btc_funding and len(btc_funding) > 0:
            fr_val = float(btc_funding[0].get("fundingRate", 0)) * 100
            btc_fr = f"{fr_val:+.4f}%"

        btc_oi_str = "N/A"
        if btc_oi and btc_oi.get("openInterest"):
            oi_val = float(btc_oi["openInterest"]) * btc_price
            btc_oi_str = f"${fmt_large(oi_val)}"

        alt_status = "Active" if dominance < 45 else ("Warming up" if dominance < 50 else "Inactive")
        verdict = _macro_verdict(fng_score, btc_change, dominance)

        return (
            f"LIVE MACRO GATE CHECK\n"
            f"{ts}\n"
            f"BTC Price        : ${fmt_price(btc_price)}\n"
            f"BTC 24H Change   : {fmt_pct(btc_change)}\n"
            f"BTC Trend        : {btc_trend}\n"
            f"BTC Dominance    : {dominance:.1f}% — {dom_note}\n"
            f"ETH/BTC Ratio    : {eth_btc:.5f} — {eth_btc_note}\n"
            f"Total Market Cap : ${fmt_large(total_cap)}\n"
            f"Fear and Greed   : {fng_score}/100 — {fng_emoji}\n"
            f"Altseason        : {alt_status}\n"
            f"BTC Funding Rate : {btc_fr}\n"
            f"BTC Open Interest: {btc_oi_str}\n"
            f"VERDICT: {verdict}"
        )
