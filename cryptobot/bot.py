"""
DOTMAN CRYPTO INTELLIGENCE BOT — FINAL
6-Layer Live Market Intelligence System
Layer 1: Macro | Layer 2: Alpha | Layer 3: Polymarket
Layer 4: Patterns | Layer 5: Whale | Layer 6: Liquidity
+ AI Chat | Signal Tracking | Backtest Engine | Opportunity Scanner
"""

import asyncio
import logging
import re

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

from core.signal_engine     import SignalEngine
from core.session_manager   import SessionManager
from core.alert_manager     import (
    add_alert, list_alerts_text, clear_alerts,
    add_position, remove_position, get_portfolio_text,
    get_positions, add_to_watchlist, remove_from_watchlist, get_watchlist
)
from core.auto_scanner      import run_auto_scanner, run_alert_checker, get_live_price
from core.signal_history    import (
    get_stats_text, get_open_signals_text, get_open_signals,
    check_open_signals, log_signal
)
from core.ai_chat           import chat_with_memory, ConversationMemory
from core.backtest_engine   import run_backtest, format_backtest_report
from core.opportunity_scanner import run_opportunity_scanner
from layers.layer1_macro    import MacroLayer
from layers.layer2_alpha    import AlphaLayer
from layers.layer3_polymarket import PolymarketLayer
from layers.layer4_patterns import PatternLayer
from layers.layer5_whale    import whale_detector
from layers.layer6_liquidity import liquidity_checker
from utils.formatter        import format_error
import config

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── GLOBAL STATE ──────────────────────────────────────────────────────────────
engine   = SignalEngine()
sessions = SessionManager()
memory   = ConversationMemory(max_history=8)
registered_users = set()
chat_mode_users  = set()


# ── HELPERS ───────────────────────────────────────────────────────────────────

def register_user(uid: int):
    registered_users.add(uid)


async def safe_send(message, text: str):
    """Send with auto-split for Telegram 4096 char limit"""
    chunks = _split(text)
    for chunk in chunks:
        try:
            await message.reply_text(chunk)
        except Exception as e:
            logger.error(f"Send error: {e}")
            try:
                await message.reply_text(chunk[:3800] + "\n...[truncated]")
            except Exception:
                pass


def _split(text: str, limit: int = 4000) -> list:
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        cut = text.rfind('\n', 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:]
    if text:
        chunks.append(text)
    return chunks


# ── /start & /help ────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text(
        "DOTMAN CRYPTO INTELLIGENCE BOT\n"
        "6-Layer Live Market Intelligence\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ANALYSIS\n"
        "/scan [COIN]   — Full 6-layer signal\n"
        "/macro         — Macro gate check\n"
        "/price [COIN]  — Live price block\n"
        "/stage [COIN]  — Pump stage detection\n"
        "/whale [COIN]  — Whale activity\n"
        "/liq [COIN]    — Order book depth\n"
        "/alpha         — Top alpha plays\n"
        "/poly          — Polymarket signals\n"
        "/fng           — Fear and Greed\n\n"
        "SIGNAL TRACKING\n"
        "/signals       — Win rate + history\n"
        "/open          — Open signals\n"
        "/track [COIN]  — Live signal status\n"
        "/backtest      — Backtest analysis\n\n"
        "ALERTS\n"
        "/alert BTC 90000  — Price alert\n"
        "/alerts           — View alerts\n"
        "/clearalerts      — Remove all\n\n"
        "PORTFOLIO\n"
        "/portfolio              — Live PnL\n"
        "/portfolio add SOL 10 85\n"
        "/portfolio remove SOL\n\n"
        "WATCHLIST\n"
        "/watchlist      — View watchlist\n"
        "/watch add TAO\n"
        "/watch remove TAO\n\n"
        "AI CHAT\n"
        "/ask [question] — Ask anything\n"
        "/endchat        — Exit chat mode\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Just type any ticker: BTC SOL ETH TAO"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await start(update, context)


# ── ANALYSIS COMMANDS ─────────────────────────────────────────────────────────

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /scan SOL")
        return
    ticker = context.args[0].upper()
    sessions.set_pending_coin(update.effective_user.id, ticker)
    keyboard = [[
        InlineKeyboardButton("SPOT", callback_data=f"trade_spot_{ticker}"),
        InlineKeyboardButton("PERPETUAL", callback_data=f"trade_perp_{ticker}"),
    ]]
    await update.message.reply_text(
        f"{ticker} — Select trade type:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def macro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("Pulling live macro data...")
    try:
        await safe_send(update.message, await MacroLayer().full_macro_gate())
    except Exception as e:
        await update.message.reply_text(format_error("MACRO", str(e)))


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /price BTC")
        return
    ticker = context.args[0].upper()
    await update.message.reply_text(f"Fetching live price for {ticker}...")
    try:
        await safe_send(update.message, await MacroLayer().live_price_block(ticker))
    except Exception as e:
        await update.message.reply_text(format_error(ticker, str(e)))


async def stage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /stage SOL")
        return
    ticker = context.args[0].upper()
    await update.message.reply_text(f"Detecting pump stage for {ticker}...")
    try:
        await safe_send(update.message, await PatternLayer().pump_stage(ticker))
    except Exception as e:
        await update.message.reply_text(format_error(ticker, str(e)))


async def whale_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /whale BTC")
        return
    ticker = context.args[0].upper()
    await update.message.reply_text(f"Detecting whale activity for {ticker}...")
    try:
        data = await whale_detector.full_whale_analysis(ticker)
        await safe_send(update.message, whale_detector.format_whale_block(data))
    except Exception as e:
        await update.message.reply_text(format_error(ticker, str(e)))


async def liq_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /liq BTC")
        return
    ticker = context.args[0].upper()
    await update.message.reply_text(f"Checking order book for {ticker}...")
    try:
        data = await liquidity_checker.analyze_liquidity(ticker)
        await safe_send(update.message, liquidity_checker.format_liquidity_block(data))
    except Exception as e:
        await update.message.reply_text(format_error(ticker, str(e)))


async def alpha_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("Hunting live alpha plays...")
    try:
        await safe_send(update.message, await AlphaLayer().hunt_alpha())
    except Exception as e:
        await update.message.reply_text(format_error("ALPHA", str(e)))


async def poly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("Pulling Polymarket signals...")
    try:
        await safe_send(update.message, await PolymarketLayer().top_signals())
    except Exception as e:
        await update.message.reply_text(format_error("POLYMARKET", str(e)))


async def fng_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    try:
        await safe_send(update.message, await MacroLayer().fear_and_greed())
    except Exception as e:
        await update.message.reply_text(format_error("F&G", str(e)))


# ── SIGNAL TRACKING ───────────────────────────────────────────────────────────

async def signals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await safe_send(update.message, get_stats_text(update.effective_user.id))


async def open_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await safe_send(update.message, get_open_signals_text(update.effective_user.id))


async def track_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /track SOL")
        return
    ticker = context.args[0].upper()
    user_id = update.effective_user.id
    sigs = [s for s in get_open_signals(user_id) if s["ticker"] == ticker]
    if not sigs:
        await update.message.reply_text(f"No open signals for {ticker}. Run /scan {ticker} to generate one.")
        return
    await update.message.reply_text(f"Fetching live price for {ticker}...")
    live_price = await get_live_price(ticker)
    lines = [f"LIVE TRACKING — {ticker}", ""]
    for s in sigs:
        entry = s["entry_price"]
        if live_price and entry > 0:
            pnl = ((live_price - entry) / entry * 100) if s["direction"] == "BUY" else ((entry - live_price) / entry * 100)
            pnl_e = "+" if pnl >= 0 else ""
            status = f"{pnl_e}{pnl:.2f}% from entry"
        else:
            status = "Price unavailable"
        tp1_s = "HIT" if live_price and live_price >= s["tp1"] else "pending"
        tp2_s = "HIT" if live_price and live_price >= s["tp2"] else "pending"
        stop_s = "TRIGGERED" if live_price and live_price <= s["stop_loss"] else "safe"
        lines += [
            f"Direction : {s['direction']} [{s['trade_type'].upper()}]",
            f"Entry     : ${s['entry_price']:,.4f}",
            f"Now       : ${live_price:,.4f}" if live_price else "Now       : unavailable",
            f"Status    : {status}",
            f"TP1 ${s['tp1']:,.4f} : {tp1_s}",
            f"TP2 ${s['tp2']:,.4f} : {tp2_s}",
            f"Stop ${s['stop_loss']:,.4f}: {stop_s}",
            f"Pattern   : {s['pattern']}",
            "",
        ]
    await safe_send(update.message, "\n".join(lines))


async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("Running backtest on your signal history...")
    try:
        results = run_backtest(update.effective_user.id)
        await safe_send(update.message, format_backtest_report(results, update.effective_user.id))
    except Exception as e:
        await update.message.reply_text(f"Backtest error: {str(e)[:100]}")


# ── AI CHAT ───────────────────────────────────────────────────────────────────

async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    uid = update.effective_user.id
    chat_mode_users.add(uid)

    if context.args:
        question = " ".join(context.args)
        await update.message.reply_text("Thinking...")
        reply = await chat_with_memory(uid, question, memory)
        await safe_send(update.message, reply)
        return

    await update.message.reply_text(
        "AI CHAT MODE ACTIVE\n\n"
        "Ask me anything:\n"
        "  Should I hold my SOL position?\n"
        "  Is BTC in Stage 1 or Stage 5?\n"
        "  What does a bull flag mean?\n"
        "  Is TAO safe to buy right now?\n"
        "  Explain my open signal\n\n"
        "I have context of your portfolio\n"
        "and open signals.\n\n"
        "Type /endchat to exit."
    )


async def endchat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_mode_users.discard(uid)
    memory.clear(uid)
    await update.message.reply_text("Chat ended. Use /ask to start a new session.")


# ── ALERTS ────────────────────────────────────────────────────────────────────

async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    uid = update.effective_user.id
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/alert BTC 90000\n"
            "/alert SOL 80\n\n"
            "Bot auto-detects direction."
        )
        return
    ticker = context.args[0].upper()
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Invalid price. Example: /alert BTC 90000")
        return
    live = await get_live_price(ticker)
    if not live:
        await update.message.reply_text(f"Could not fetch live price for {ticker}.")
        return
    direction = "above" if target > live else "below"
    add_alert(uid, ticker, target, direction)
    await update.message.reply_text(
        f"Alert set.\n{ticker} now at ${live:,.4f}\n"
        f"Will ping when {ticker} goes {direction.upper()} ${target:,.2f}"
    )


async def alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text(list_alerts_text(update.effective_user.id))


async def clearalerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text(clear_alerts(update.effective_user.id))


# ── PORTFOLIO ─────────────────────────────────────────────────────────────────

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Fetching portfolio with live prices...")
        await safe_send(update.message, await get_portfolio_text(uid, get_live_price))
        return
    sub = context.args[0].lower()
    if sub == "add":
        if len(context.args) < 4:
            await update.message.reply_text("Usage: /portfolio add SOL 10 85.00")
            return
        try:
            amount = float(context.args[2])
            entry  = float(context.args[3])
        except ValueError:
            await update.message.reply_text("Invalid amount or price.")
            return
        await update.message.reply_text(add_position(uid, context.args[1].upper(), amount, entry))
    elif sub == "remove":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /portfolio remove SOL")
            return
        await update.message.reply_text(remove_position(uid, context.args[1].upper()))
    else:
        await update.message.reply_text(
            "/portfolio — view PnL\n"
            "/portfolio add SOL 10 85.00\n"
            "/portfolio remove SOL"
        )


# ── WATCHLIST ─────────────────────────────────────────────────────────────────

async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    wl = get_watchlist(update.effective_user.id)
    await update.message.reply_text(
        f"Watchlist ({len(wl)} coins):\n{', '.join(wl)}\n\n"
        f"/watch add TAO\n/watch remove TAO\n"
        f"Auto-scanned every 10 minutes."
    )


async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage:\n/watch add TAO\n/watch remove TAO")
        return
    sub    = context.args[0].lower()
    ticker = context.args[1].upper()
    if sub == "add":
        result = add_to_watchlist(update.effective_user.id, ticker)
    elif sub == "remove":
        result = remove_from_watchlist(update.effective_user.id, ticker)
    else:
        result = "Usage:\n/watch add TAO\n/watch remove TAO"
    await update.message.reply_text(result)


# ── CALLBACK: SPOT / PERP SELECTION ──────────────────────────────────────────

async def trade_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts      = query.data.split("_")
    trade_type = parts[1]
    ticker     = parts[2]

    await query.edit_message_text(
        f"Running 6-layer analysis on {ticker} [{trade_type.upper()}]...\n"
        "Layers: Macro | Alpha | Polymarket | Patterns | Whale | Liquidity"
    )

    try:
        result = await engine.full_scan(ticker, trade_type)
        for chunk in _split(result):
            await safe_send(query.message, chunk)
    except Exception as e:
        await query.message.reply_text(format_error(ticker, str(e)))


# ── MESSAGE HANDLER ───────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    uid  = update.effective_user.id
    text = update.message.text.strip()

    # Chat mode — everything goes to AI
    if uid in chat_mode_users:
        await update.message.reply_text("Thinking...")
        await safe_send(update.message, await chat_with_memory(uid, text, memory))
        return

    # Auto-detect ticker (2-10 letters only)
    if re.match(r'^[A-Za-z]{2,10}$', text):
        ticker = text.upper()
        sessions.set_pending_coin(uid, ticker)
        keyboard = [[
            InlineKeyboardButton("SPOT",       callback_data=f"trade_spot_{ticker}"),
            InlineKeyboardButton("PERPETUAL",  callback_data=f"trade_perp_{ticker}"),
        ]]
        await update.message.reply_text(
            f"{ticker} — Select trade type:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Default — AI interpreter
    await safe_send(update.message, await chat_with_memory(uid, text, memory))


# ── BACKGROUND: SIGNAL OUTCOME CHECKER ───────────────────────────────────────

async def run_signal_checker(app):
    logger.info("Signal outcome checker started — every 5 minutes")
    while True:
        await asyncio.sleep(300)
        try:
            triggered = await check_open_signals(get_live_price)
            for sig in triggered:
                uid     = sig["user_id"]
                outcome = sig["outcome"]
                ticker  = sig["ticker"]
                live    = sig.get("live_price", 0)
                pnl     = sig.get("pnl_pct", 0) or 0

                if outcome in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]:
                    level = outcome.replace("_HIT", "")
                    msg = (
                        f"TARGET HIT — {ticker}\n"
                        f"{level} reached at ${live:,.4f}\n"
                        f"PnL: {pnl:+.1f}%\n\n"
                        f"Action: Move stop to breakeven now.\n"
                        f"Run /track {ticker} to see full status."
                    )
                elif outcome == "STOPPED":
                    msg = (
                        f"STOP LOSS HIT — {ticker}\n"
                        f"Stopped out at ${live:,.4f}\n"
                        f"PnL: {pnl:+.1f}%\n\n"
                        f"Loss contained. Capital protected.\n"
                        f"Run /backtest to update win rate."
                    )
                else:
                    continue

                try:
                    await app.bot.send_message(chat_id=uid, text=msg)
                except Exception as e:
                    logger.error(f"Signal notify error: {e}")
        except Exception as e:
            logger.error(f"Signal checker error: {e}")


# ── STARTUP ───────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start",       "Launch the bot"),
        BotCommand("scan",        "Full 6-layer signal"),
        BotCommand("macro",       "Live macro gate"),
        BotCommand("price",       "Quick live price"),
        BotCommand("stage",       "Pump stage detection"),
        BotCommand("whale",       "Whale activity"),
        BotCommand("liq",         "Order book depth"),
        BotCommand("alpha",       "Top alpha plays"),
        BotCommand("poly",        "Polymarket signals"),
        BotCommand("fng",         "Fear and Greed Index"),
        BotCommand("ask",         "AI chat — ask anything"),
        BotCommand("endchat",     "Exit AI chat mode"),
        BotCommand("signals",     "Signal history + win rate"),
        BotCommand("open",        "Open signals tracking"),
        BotCommand("track",       "Live signal status"),
        BotCommand("backtest",    "Backtest analysis"),
        BotCommand("alert",       "Set price alert"),
        BotCommand("alerts",      "View your alerts"),
        BotCommand("portfolio",   "Portfolio with live PnL"),
        BotCommand("watchlist",   "View watchlist"),
        BotCommand("help",        "All commands"),
    ])

    # Start all background tasks
    asyncio.create_task(run_alert_checker(application, list(registered_users)))
    asyncio.create_task(run_auto_scanner(application, list(registered_users)))
    asyncio.create_task(run_signal_checker(application))
    asyncio.create_task(run_opportunity_scanner(application, lambda: list(registered_users)))
    logger.info("All 4 background tasks started")


async def post_shutdown(application: Application):
    from core.data_fetcher import fetcher
    await fetcher.close()


def main():
    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Analysis
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_cmd))
    app.add_handler(CommandHandler("scan",        scan_cmd))
    app.add_handler(CommandHandler("macro",       macro_cmd))
    app.add_handler(CommandHandler("price",       price_cmd))
    app.add_handler(CommandHandler("stage",       stage_cmd))
    app.add_handler(CommandHandler("whale",       whale_cmd))
    app.add_handler(CommandHandler("liq",         liq_cmd))
    app.add_handler(CommandHandler("alpha",       alpha_cmd))
    app.add_handler(CommandHandler("poly",        poly_cmd))
    app.add_handler(CommandHandler("fng",         fng_cmd))
    # AI Chat
    app.add_handler(CommandHandler("ask",         ask_cmd))
    app.add_handler(CommandHandler("endchat",     endchat_cmd))
    # Signal tracking
    app.add_handler(CommandHandler("signals",     signals_cmd))
    app.add_handler(CommandHandler("open",        open_cmd))
    app.add_handler(CommandHandler("track",       track_cmd))
    app.add_handler(CommandHandler("backtest",    backtest_cmd))
    # Alerts
    app.add_handler(CommandHandler("alert",       alert_cmd))
    app.add_handler(CommandHandler("alerts",      alerts_cmd))
    app.add_handler(CommandHandler("clearalerts", clearalerts_cmd))
    # Portfolio
    app.add_handler(CommandHandler("portfolio",   portfolio_cmd))
    # Watchlist
    app.add_handler(CommandHandler("watchlist",   watchlist_cmd))
    app.add_handler(CommandHandler("watch",       watch_cmd))
    # Callbacks + messages
    app.add_handler(CallbackQueryHandler(trade_type_callback, pattern=r"^trade_(spot|perp)_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("DOTMAN BOT — FINAL — ALL 6 LAYERS LIVE")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
