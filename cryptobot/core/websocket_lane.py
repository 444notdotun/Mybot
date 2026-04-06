"""
WEBSOCKET FAST LANE
Real-time price and volume monitoring via Binance WebSocket.
Detects price moves and volume spikes instantly.
Silently triggers deep scan — only sends signal if score meets threshold.
No head-up alerts. One signal only.
"""

import asyncio
import json
import logging
import aiohttp
from datetime import datetime, timezone
from core.alert_manager import get_watchlist

logger = logging.getLogger(__name__)

# Thresholds to trigger a deep scan
PRICE_MOVE_TRIGGER_PCT = 2.5   # 2.5% price move in short window
VOLUME_SPIKE_TRIGGER   = 2.0   # 2x volume above recent average
SCAN_COOLDOWN_SECONDS  = 300   # Don't re-trigger same coin within 5 min


class WebSocketFastLane:

    def __init__(self):
        self._last_prices = {}      # ticker -> last known price
        self._last_triggered = {}   # ticker -> datetime of last deep scan trigger
        self._recent_volumes = {}   # ticker -> list of recent volumes
        self._scan_callback = None  # async function to call when trigger fires

    def set_scan_callback(self, callback):
        """Set the function to call when a trigger fires — this runs the deep scan"""
        self._scan_callback = callback

    def _on_cooldown(self, ticker: str) -> bool:
        if ticker not in self._last_triggered:
            return False
        elapsed = (datetime.now(timezone.utc) - self._last_triggered[ticker]).total_seconds()
        return elapsed < SCAN_COOLDOWN_SECONDS

    def _mark_triggered(self, ticker: str):
        self._last_triggered[ticker] = datetime.now(timezone.utc)

    async def _handle_message(self, ticker: str, data: dict, user_ids: list):
        """Process incoming WebSocket kline message"""
        try:
            kline = data.get("k", {})
            if not kline.get("x"):  # Only process closed candles
                return

            close_price = float(kline.get("c", 0))
            volume = float(kline.get("q", 0))  # quote volume in USDT

            ticker_upper = ticker.upper()

            # Track volume history
            if ticker_upper not in self._recent_volumes:
                self._recent_volumes[ticker_upper] = []
            self._recent_volumes[ticker_upper].append(volume)
            if len(self._recent_volumes[ticker_upper]) > 10:
                self._recent_volumes[ticker_upper].pop(0)

            # Check price move trigger
            price_triggered = False
            if ticker_upper in self._last_prices and self._last_prices[ticker_upper] > 0:
                old_price = self._last_prices[ticker_upper]
                move_pct = abs((close_price - old_price) / old_price) * 100
                if move_pct >= PRICE_MOVE_TRIGGER_PCT:
                    price_triggered = True
                    logger.info(f"WebSocket price trigger: {ticker_upper} moved {move_pct:.1f}%")

            # Check volume spike trigger
            volume_triggered = False
            vols = self._recent_volumes[ticker_upper]
            if len(vols) >= 4:
                avg_vol = sum(vols[:-1]) / (len(vols) - 1)
                if avg_vol > 0 and volume > avg_vol * VOLUME_SPIKE_TRIGGER:
                    volume_triggered = True
                    logger.info(f"WebSocket volume trigger: {ticker_upper} {volume/avg_vol:.1f}x spike")

            self._last_prices[ticker_upper] = close_price

            # Fire deep scan if triggered and not on cooldown
            if (price_triggered or volume_triggered) and not self._on_cooldown(ticker_upper):
                if self._scan_callback and user_ids:
                    self._mark_triggered(ticker_upper)
                    logger.info(f"Triggering deep scan for {ticker_upper}")
                    # Run deep scan for all users watching this coin
                    for user_id in user_ids:
                        watchlist = get_watchlist(user_id)
                        if ticker_upper in watchlist:
                            asyncio.create_task(
                                self._scan_callback(ticker_upper, user_id)
                            )

        except Exception as e:
            logger.error(f"WebSocket message error for {ticker}: {e}")

    async def _stream_coin(self, ticker: str, user_ids_fn):
        """Single coin WebSocket stream — 5min klines"""
        stream_url = f"wss://stream.binance.com:9443/ws/{ticker.lower()}usdt@kline_5m"

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        stream_url,
                        heartbeat=30,
                        timeout=aiohttp.ClientWSTimeout(ws_close=60)
                    ) as ws:
                        logger.info(f"WebSocket connected: {ticker}")
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                await self._handle_message(ticker, data, user_ids_fn())
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except Exception as e:
                logger.warning(f"WebSocket disconnected for {ticker}: {e}")
            # Reconnect after 5 seconds
            await asyncio.sleep(5)

    async def run(self, user_ids_fn, scan_callback):
        """
        Start WebSocket streams for all watchlist coins.
        Dynamically updates as watchlist changes.
        """
        self.set_scan_callback(scan_callback)
        active_streams = {}

        logger.info("WebSocket fast lane starting...")

        while True:
            try:
                # Get current watchlist across all users
                all_tickers = set()
                for uid in user_ids_fn():
                    for ticker in get_watchlist(uid):
                        all_tickers.add(ticker.upper())

                # Start streams for new coins
                for ticker in all_tickers:
                    if ticker not in active_streams:
                        logger.info(f"Starting WebSocket stream for {ticker}")
                        task = asyncio.create_task(
                            self._stream_coin(ticker, user_ids_fn)
                        )
                        active_streams[ticker] = task

                # Cancel streams for removed coins
                for ticker in list(active_streams.keys()):
                    if ticker not in all_tickers:
                        active_streams[ticker].cancel()
                        del active_streams[ticker]
                        logger.info(f"Stopped WebSocket stream for {ticker}")

            except Exception as e:
                logger.error(f"WebSocket manager error: {e}")

            # Check for watchlist changes every 60 seconds
            await asyncio.sleep(60)


# Singleton
websocket_lane = WebSocketFastLane()
