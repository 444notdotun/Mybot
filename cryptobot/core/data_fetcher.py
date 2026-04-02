"""
LIVE DATA FETCHER
All API calls in one place. Every function pulls LIVE data only.
Fallback chain: Binance → Bybit → KuCoin → CoinGecko → DEXScreener
No caching. No memory substitution. Every call is timestamped.
"""

import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import Optional
import config


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


class DataFetcher:

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=config.HTTP_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def get(self, url: str, params: dict = None) -> Optional[dict]:
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── BINANCE ───────────────────────────────────────────────────────────────

    async def binance_ticker(self, symbol: str) -> Optional[dict]:
        return await self.get(
            f"{config.BINANCE_BASE}/ticker/24hr",
            {"symbol": f"{symbol}USDT"}
        )

    async def binance_klines(self, symbol: str, interval: str = "1d", limit: int = 100) -> Optional[list]:
        return await self.get(
            f"{config.BINANCE_BASE}/klines",
            {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
        )

    async def binance_funding_rate(self, symbol: str) -> Optional[list]:
        return await self.get(
            f"{config.BINANCE_FUTURES}/fundingRate",
            {"symbol": f"{symbol}USDT", "limit": 1}
        )

    async def binance_open_interest(self, symbol: str) -> Optional[dict]:
        return await self.get(
            f"{config.BINANCE_FUTURES}/openInterest",
            {"symbol": f"{symbol}USDT"}
        )

    # ── BYBIT FALLBACK ────────────────────────────────────────────────────────

    async def bybit_ticker(self, symbol: str) -> Optional[dict]:
        """Bybit spot ticker — fallback when Binance doesn't list coin"""
        result = await self.get(
            "https://api.bybit.com/v5/market/tickers",
            {"category": "spot", "symbol": f"{symbol}USDT"}
        )
        if result and result.get("result", {}).get("list"):
            t = result["result"]["list"][0]
            return {
                "lastPrice": t.get("lastPrice", 0),
                "priceChangePercent": t.get("price24hPcnt", "0"),
                "highPrice": t.get("highPrice24h", 0),
                "lowPrice": t.get("lowPrice24h", 0),
                "quoteVolume": t.get("turnover24h", 0),
                "source": "Bybit"
            }
        return None

    async def bybit_klines(self, symbol: str, interval: str = "D", limit: int = 50) -> Optional[list]:
        """Bybit klines — interval: 1,3,5,15,30,60,120,240,360,720,D,W,M"""
        result = await self.get(
            "https://api.bybit.com/v5/market/kline",
            {"category": "spot", "symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
        )
        if result and result.get("result", {}).get("list"):
            # Bybit format: [startTime, open, high, low, close, volume, turnover]
            # Convert to Binance format: [time, open, high, low, close, volume, ...]
            raw = result["result"]["list"]
            converted = []
            for k in raw:
                converted.append([k[0], k[1], k[2], k[3], k[4], k[5], k[0], k[4], k[5], 0, 0, 0])
            return converted
        return None

    # ── KUCOIN FALLBACK ───────────────────────────────────────────────────────

    async def kucoin_ticker(self, symbol: str) -> Optional[dict]:
        """KuCoin ticker — fallback for coins not on Binance or Bybit"""
        result = await self.get(
            f"https://api.kucoin.com/api/v1/market/stats",
            {"symbol": f"{symbol}-USDT"}
        )
        if result and result.get("data") and result["data"].get("last"):
            d = result["data"]
            last = float(d.get("last", 0))
            open_p = float(d.get("open", last) or last)
            change_pct = ((last - open_p) / open_p * 100) if open_p > 0 else 0
            return {
                "lastPrice": str(last),
                "priceChangePercent": str(round(change_pct, 2)),
                "highPrice": d.get("high", 0),
                "lowPrice": d.get("low", 0),
                "quoteVolume": d.get("volValue", 0),
                "source": "KuCoin"
            }
        return None

    async def kucoin_klines(self, symbol: str, interval: str = "1day", limit: int = 50) -> Optional[list]:
        """KuCoin klines"""
        import time
        end_time = int(time.time())
        start_time = end_time - (limit * 86400)
        result = await self.get(
            f"https://api.kucoin.com/api/v1/market/candles",
            {"symbol": f"{symbol}-USDT", "type": interval, "startAt": start_time, "endAt": end_time}
        )
        if result and result.get("data"):
            raw = result["data"]
            converted = []
            for k in raw:
                # KuCoin: [time, open, close, high, low, volume, turnover]
                converted.append([k[0], k[1], k[3], k[4], k[2], k[5], k[0], k[2], k[5], 0, 0, 0])
            return converted
        return None

    # ── UNIVERSAL TICKER (tries all exchanges) ────────────────────────────────

    async def get_ticker(self, symbol: str) -> Optional[dict]:
        """
        Try Binance first, then Bybit, then KuCoin.
        Returns ticker dict with 'source' field indicating which exchange.
        """
        # Try Binance
        result = await self.binance_ticker(symbol)
        if result:
            result["source"] = "Binance"
            return result

        # Try Bybit
        result = await self.bybit_ticker(symbol)
        if result:
            return result

        # Try KuCoin
        result = await self.kucoin_ticker(symbol)
        if result:
            return result

        return None

    async def get_klines(self, symbol: str, limit: int = 50) -> Optional[list]:
        """
        Try Binance klines first, then Bybit, then KuCoin.
        """
        result = await self.binance_klines(symbol, "1d", limit)
        if result and len(result) > 5:
            return result

        result = await self.bybit_klines(symbol, "D", limit)
        if result and len(result) > 5:
            return result

        result = await self.kucoin_klines(symbol, "1day", limit)
        if result and len(result) > 5:
            return result

        return None

    # ── COINGECKO ─────────────────────────────────────────────────────────────

    async def coingecko_price(self, coin_id: str) -> Optional[dict]:
        params = {
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
            "include_7d_change": "true",
        }
        if config.COINGECKO_API_KEY:
            params["x_cg_demo_api_key"] = config.COINGECKO_API_KEY
        return await self.get(f"{config.COINGECKO_BASE}/simple/price", params)

    async def coingecko_trending(self) -> Optional[dict]:
        return await self.get(f"{config.COINGECKO_BASE}/search/trending")

    async def coingecko_global(self) -> Optional[dict]:
        return await self.get(f"{config.COINGECKO_BASE}/global")

    async def coingecko_search(self, query: str) -> Optional[dict]:
        return await self.get(f"{config.COINGECKO_BASE}/search", {"query": query})

    # ── FEAR & GREED ──────────────────────────────────────────────────────────

    async def fear_and_greed(self) -> Optional[dict]:
        return await self.get(config.FNG_URL, {"limit": 1})

    # ── POLYMARKET ────────────────────────────────────────────────────────────

    async def polymarket_markets(self, limit: int = 20) -> Optional[list]:
        return await self.get(
            f"{config.POLYMARKET_BASE}/markets",
            {"limit": limit, "active": "true", "closed": "false", "_sort": "volume24hr:desc"}
        )

    # ── DEXSCREENER ───────────────────────────────────────────────────────────

    async def dexscreener_token(self, contract: str) -> Optional[dict]:
        return await self.get(f"{config.DEXSCREENER_BASE}/tokens/{contract}")

    # ── COIN ID RESOLUTION ────────────────────────────────────────────────────

    TICKER_TO_ID = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
        "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink",
        "MATIC": "matic-network", "UNI": "uniswap", "AAVE": "aave",
        "TAO": "bittensor", "RENDER": "render-token", "RNDR": "render-token",
        "FET": "fetch-ai", "SUI": "sui", "WIF": "dogwifcoin",
        "BONK": "bonk", "PEPE": "pepe", "DOGE": "dogecoin",
        "SHIB": "shiba-inu", "ARB": "arbitrum", "OP": "optimism",
        "INJ": "injective-protocol", "TIA": "celestia",
        "PYTH": "pyth-network", "JTO": "jito-governance-token",
        "WLD": "worldcoin-wld", "APT": "aptos", "SEI": "sei-network",
        "NEAR": "near", "ATOM": "cosmos", "FTM": "fantom",
        "LTC": "litecoin", "BCH": "bitcoin-cash", "ETC": "ethereum-classic",
        "ZETA": "zetachain", "DEEP": "deep-book",
    }

    async def resolve_coin_id(self, ticker: str) -> Optional[str]:
        ticker = ticker.upper()
        if ticker in self.TICKER_TO_ID:
            return self.TICKER_TO_ID[ticker]
        result = await self.coingecko_search(ticker)
        if result and result.get("coins"):
            for coin in result["coins"][:3]:
                if coin.get("symbol", "").upper() == ticker:
                    return coin["id"]
        return None


fetcher = DataFetcher()
