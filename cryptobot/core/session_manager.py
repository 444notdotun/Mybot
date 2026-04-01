"""
SESSION MANAGER
Tracks per-user state: pending coin, trade type, active signals.
Simple in-memory store — no database needed for MVP.
"""

from datetime import datetime, timezone
from typing import Optional


class SessionManager:
    def __init__(self):
        self._sessions = {}  # user_id → session dict

    def set_pending_coin(self, user_id: int, ticker: str):
        self._ensure(user_id)
        self._sessions[user_id]["pending_coin"] = ticker
        self._sessions[user_id]["updated_at"] = datetime.now(timezone.utc)

    def get_pending_coin(self, user_id: int) -> Optional[str]:
        return self._sessions.get(user_id, {}).get("pending_coin")

    def clear_pending(self, user_id: int):
        if user_id in self._sessions:
            self._sessions[user_id]["pending_coin"] = None

    def set_active_signal(self, user_id: int, signal: dict):
        self._ensure(user_id)
        self._sessions[user_id]["active_signal"] = signal

    def get_active_signal(self, user_id: int) -> Optional[dict]:
        return self._sessions.get(user_id, {}).get("active_signal")

    def _ensure(self, user_id: int):
        if user_id not in self._sessions:
            self._sessions[user_id] = {
                "pending_coin": None,
                "active_signal": None,
                "trade_type": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
