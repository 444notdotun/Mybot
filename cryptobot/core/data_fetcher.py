"""
LIVE DATA FETCHER
All API calls in one place. Every function pulls LIVE data only.
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
    """Single async session for all HTTP calls"""

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

    # ── BINANCE SPOT ─────────────────────────────────────────────────────────

    async def binance_ticker(self, symbol: str) -> Optional[dict]:
        """24hr ticker stats"""
        return await self.get(
            f"{config.BINANCE_BASE}/ticker/24hr",
            {"symbol": f"{symbol}USDT"}
        )

    async def binance_klines(self, symbol: str, interval: str = "1d", limit: int = 100) -> Optional[list]:
        """Candlestick data"""
        return await self.get(
            f"{config.BINANCE_BASE}/klines",
            {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
        )

    async def binance_price(self, symbol: str) -> Optional[dict]:
        """Simple current price"""
        return await self.get(
            f"{config.BINANCE_BASE}/ticker/price",
            {"symbol": f"{symbol}USDT"}
        )

    # ── BINANCE FUTURES ───────────────────────────────────────────────────────

    async def binance_funding_rate(self, symbol: str) -> Optional[list]:
        """Latest funding rate"""
        return await self.get(
            f"{config.BINANCE_FUTURES}/fundingRate",
            {"symbol": f"{symbol}USDT", "limit": 1}
        )

    async def binance_open_interest(self, symbol: str) -> Optional[dict]:
        """Live open interest"""
        return await self.get(
            f"{config.BINANCE_FUTURES}/openInterest",
            {"symbol": f"{symbol}USDT"}
        )

    async def binance_futures_ticker(self, symbol: str) -> Optional[dict]:
        """Futures 24hr ticker"""
        return await self.get(
            f"{config.BINANCE_FUTURES}/ticker/24hr",
            {"symbol": f"{symbol}USDT"}
        )

    # ── COINGECKO ─────────────────────────────────────────────────────────────

    async def coingecko_price(self, coin_id: str) -> Optional[dict]:
        """Price, market cap, 24h change"""
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

    async def coingecko_coin_detail(self, coin_id: str) -> Optional[dict]:
        """Full coin detail including ATH, rank, etc."""
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
        }
        if config.COINGECKO_API_KEY:
            params["x_cg_demo_api_key"] = config.COINGECKO_API_KEY
        return await self.get(f"{config.COINGECKO_BASE}/coins/{coin_id}", params)

    async def coingecko_trending(self) -> Optional[dict]:
        """Top trending coins right now"""
        return await self.get(f"{config.COINGECKO_BASE}/search/trending")

    async def coingecko_global(self) -> Optional[dict]:
        """Global market data: dominance, total cap, etc."""
        return await self.get(f"{config.COINGECKO_BASE}/global")

    async def coingecko_search(self, query: str) -> Optional[dict]:
        """Search for a coin by ticker to get its ID"""
        return await self.get(f"{config.COINGECKO_BASE}/search", {"query": query})

    # ── FEAR & GREED ──────────────────────────────────────────────────────────

    async def fear_and_greed(self) -> Optional[dict]:
        """Live Fear & Greed Index"""
        return await self.get(config.FNG_URL, {"limit": 1})

    # ── POLYMARKET ────────────────────────────────────────────────────────────

    async def polymarket_markets(self, limit: int = 20) -> Optional[list]:
        """Top active Polymarket markets"""
        return await self.get(
            f"{config.POLYMARKET_BASE}/markets",
            {"limit": limit, "active": "true", "closed": "false", "_sort": "volume24hr:desc"}
        )

    async def polymarket_market(self, market_id: str) -> Optional[dict]:
        """Single market detail"""
        return await self.get(f"{config.POLYMARKET_BASE}/markets/{market_id}")

    # ── DEXSCREENER ───────────────────────────────────────────────────────────

    async def dexscreener_token(self, contract: str) -> Optional[dict]:
        """Token data from DEX"""
        return await self.get(f"{config.DEXSCREENER_BASE}/tokens/{contract}")

    async def dexscreener_trending(self) -> Optional[dict]:
        """Trending tokens on DEX"""
        return await self.get(f"{config.DEXSCREENER_BASE}/pairs/solana/trending")

    # ── COIN ID RESOLUTION ────────────────────────────────────────────────────

    # Common ticker → CoinGecko ID map for speed
    TICKER_TO_ID = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
        "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink",
        "MATIC": "matic-network", "UNI": "uniswap", "AAVE": "aave",
        "TAO": "bittensor", "RENDER": "render-token", "RNDR": "render-token",
        "FET": "fetch-ai", "SUI": "sui", "DEEP": "deep-book",
        "ZETA": "zetachain", "WIF": "dogwifcoin", "BONK": "bonk",
        "PEPE": "pepe", "DOGE": "dogecoin", "SHIB": "shiba-inu",
        "ARB": "arbitrum", "OP": "optimism", "INJ": "injective-protocol",
        "TIA": "celestia", "PYTH": "pyth-network", "JTO": "jito-governance-token",
        "WLD": "worldcoin-wld", "APT": "aptos", "SEI": "sei-network",
        "NEAR": "near", "ATOM": "cosmos", "FTM": "fantom",
        "LTC": "litecoin", "BCH": "bitcoin-cash", "ETC": "ethereum-classic",
    }

    async def resolve_coin_id(self, ticker: str) -> Optional[str]:
        """Get CoinGecko ID from ticker, with live search fallback"""
        ticker = ticker.upper()
        if ticker in self.TICKER_TO_ID:
            return self.TICKER_TO_ID[ticker]
        # Live search fallback
        result = await self.coingecko_search(ticker)
        if result and result.get("coins"):
            for coin in result["coins"][:3]:
                if coin.get("symbol", "").upper() == ticker:
                    return coin["id"]
        return None


# Singleton instance
fetcher = DataFetcher()
