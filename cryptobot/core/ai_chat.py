"""
AI CHAT MODE
Natural language interface for trade questions.
User can ask anything about a trade, coin, or market condition.
Has full context: live price, portfolio, open signals, macro gate.
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from core.signal_history import get_open_signals, get_stats_text
from core.alert_manager import get_positions, get_watchlist
from utils.formatter import fmt_price, fmt_pct, fmt_large
import config


CHAT_SYSTEM_PROMPT = """You are DOTMAN, an elite crypto trading intelligence assistant built into a Telegram bot.

You have access to the user's live portfolio, open signals, watchlist, and real-time market context.

Your job is to answer trade questions with precision. You are direct, honest, and never say "it might go up" without a specific reason backed by data.

RULES:
- Always use the live context provided. Never guess prices.
- Be concise — Telegram messages should be under 300 words
- If asked about a specific coin with no live data provided, say so clearly
- Give actionable answers: entry, stop, or "no trade" — never vague
- Format for Telegram: no markdown headers, use plain text and emojis
- If the question is unclear, ask ONE clarifying question

PERSONALITY:
- Direct and confident
- Never sugarcoat bad setups
- Protect capital first, grow it second
- You've seen every market cycle and you're not impressed by hype"""


async def chat_with_context(
    user_id: int,
    user_message: str,
    live_context: dict = None
) -> str:
    """
    Process a natural language trading question with full context.
    live_context can include: price, macro, portfolio, open_signals
    """

    # Build context string
    context_parts = []

    if live_context:
        if live_context.get("price"):
            context_parts.append(f"LIVE PRICE DATA:\n{live_context['price']}")
        if live_context.get("macro"):
            context_parts.append(f"CURRENT MACRO:\n{live_context['macro']}")

    # Add portfolio context
    positions = get_positions(user_id)
    if positions:
        pos_lines = ["USER PORTFOLIO:"]
        for p in positions:
            pos_lines.append(f"  {p['ticker']}: {p['amount']} @ ${p['entry_price']:,.4f}")
        context_parts.append("\n".join(pos_lines))

    # Add open signals
    open_sigs = get_open_signals(user_id)
    if open_sigs:
        sig_lines = ["OPEN SIGNALS:"]
        for s in open_sigs:
            sig_lines.append(
                f"  {s['ticker']} {s['direction']}: entry ${s['entry_price']:,.4f} "
                f"TP1 ${s['tp1']:,.4f} Stop ${s['stop_loss']:,.4f}"
            )
        context_parts.append("\n".join(sig_lines))

    # Add watchlist
    watchlist = get_watchlist(user_id)
    if watchlist:
        context_parts.append(f"WATCHLIST: {', '.join(watchlist)}")

    context_str = "\n\n".join(context_parts) if context_parts else "No additional context available."

    full_prompt = (
        f"USER CONTEXT:\n{context_str}\n\n"
        f"USER QUESTION: {user_message}\n\n"
        f"Answer directly and concisely. Use the context above."
    )

    return await _call_claude_chat(full_prompt)


async def _call_claude_chat(prompt: str) -> str:
    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": 600,
        "system": CHAT_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}]
    }

    timeout = aiohttp.ClientTimeout(total=20)
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
                return "Could not process question right now. Try again."
    except asyncio.TimeoutError:
        return "Request timed out. Try a shorter question."
    except Exception as e:
        return f"Error: {str(e)[:100]}"


# ── CONVERSATION MEMORY (per session) ────────────────────────────────────────

class ConversationMemory:
    """Keeps last N messages per user for context continuity"""

    def __init__(self, max_history: int = 6):
        self._history = {}
        self.max_history = max_history

    def add(self, user_id: int, role: str, content: str):
        if user_id not in self._history:
            self._history[user_id] = []
        self._history[user_id].append({"role": role, "content": content})
        # Keep only last N messages
        if len(self._history[user_id]) > self.max_history:
            self._history[user_id] = self._history[user_id][-self.max_history:]

    def get(self, user_id: int) -> list:
        return self._history.get(user_id, [])

    def clear(self, user_id: int):
        self._history[user_id] = []

    def is_in_chat_mode(self, user_id: int) -> bool:
        return user_id in self._history and len(self._history[user_id]) > 0


async def chat_with_memory(
    user_id: int,
    user_message: str,
    memory: ConversationMemory,
    live_context: dict = None
) -> str:
    """Multi-turn conversation with memory"""

    # Build context
    context_parts = []
    if live_context:
        if live_context.get("price"):
            context_parts.append(f"LIVE DATA:\n{live_context['price']}")
        if live_context.get("macro"):
            context_parts.append(f"MACRO:\n{live_context['macro'][:400]}")

    positions = get_positions(user_id)
    if positions:
        pos_lines = ["PORTFOLIO: " + ", ".join(
            f"{p['ticker']} {p['amount']}@${p['entry_price']:,.2f}" for p in positions
        )]
        context_parts.append("\n".join(pos_lines))

    open_sigs = get_open_signals(user_id)
    if open_sigs:
        sig_summary = "OPEN SIGNALS: " + ", ".join(
            f"{s['ticker']} {s['direction']} entry ${s['entry_price']:,.2f}" for s in open_sigs
        )
        context_parts.append(sig_summary)

    system_with_context = CHAT_SYSTEM_PROMPT
    if context_parts:
        system_with_context += f"\n\nCURRENT USER CONTEXT:\n" + "\n".join(context_parts)

    # Build messages with history
    messages = memory.get(user_id).copy()
    messages.append({"role": "user", "content": user_message})

    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": 600,
        "system": system_with_context,
        "messages": messages
    }

    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    reply = data["content"][0]["text"]
                    # Save to memory
                    memory.add(user_id, "user", user_message)
                    memory.add(user_id, "assistant", reply)
                    return reply
                return "Could not process right now."
    except asyncio.TimeoutError:
        return "Timed out. Try again."
    except Exception as e:
        return f"Error: {str(e)[:100]}"
