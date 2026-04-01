"""
DOTMAN CRYPTO INTELLIGENCE BOT
Four-Layer Live Market Intelligence System
Telegram Bot — Entry Point
"""

import asyncio
import logging
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

from core.signal_engine import SignalEngine
from core.session_manager import SessionManager
from core.alert_manager import (
    add_alert, list_alerts_text, clear_alerts,
    add_position, remove_position, get_portfolio_text,
    get_positions, add_to_watchlist, remove_from_watchlist,
    get_watchlist
)
from core.auto_scanner import run_auto_scanner, run_alert_checker, get_live_price
from layers.layer1_macro import MacroLayer
from layers.layer2_alpha import AlphaLayer
from layers.layer3_polymarket import PolymarketLayer
from layers.layer4_patterns import PatternLayer
from utils.formatter import format_error
import config

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

engine = SignalEngine()
sessions = SessionManager()

# Track user IDs for auto-scanner
registered_users = set()


# ── HELPERS ───────────────────────────────────────────────────────────────────

async def safe_send(message, text: str):
    try:
        await message.reply_text(text)
    except Exception as e:
        logger.error(f"Send error: {e}")
        try:
            await message.reply_text(text[:4000])
        except Exception:
            pass


def split_message(text: str, limit: int = 4000) -> list:
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        split_at = text.rfind('\n', 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:]
    if text:
        chunks.append(text)
    return chunks


def register_user(user_id: int):
    registered_users.add(user_id)


# ── COMMANDS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    msg = (
        "DOTMAN CRYPTO INTELLIGENCE BOT\n"
        "Four-Layer Live Market Intelligence\n\n"
        "LAYER 1 — Macro Market Intelligence\n"
        "LAYER 2 — Alpha Hunting\n"
        "LAYER 3 — Polymarket Intelligence\n"
        "LAYER 4 — Pattern Recognition\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "COMMANDS:\n\n"
        "/macro — Live macro gate check\n"
        "/scan [COIN] — Full 4-layer signal\n"
        "/alpha — Top alpha plays now\n"
        "/poly — Polymarket signals\n"
        "/fng — Fear and Greed Index\n"
        "/price [COIN] — Quick live price\n"
        "/stage [COIN] — Pump stage only\n\n"
        "ALERTS:\n"
        "/alert BTC 90000 — ping when BTC hits $90K\n"
        "/alerts — view your alerts\n"
        "/clearalerts — remove all alerts\n\n"
        "PORTFOLIO:\n"
        "/portfolio add SOL 10 85.00\n"
        "/portfolio remove SOL\n"
        "/portfolio — view with live PnL\n\n"
        "WATCHLIST:\n"
        "/watchlist — view your watchlist\n"
        "/watch add TAO — add coin\n"
        "/watch remove TAO — remove coin\n\n"
        "Just type any ticker: BTC, SOL, ETH"
    )
    await update.message.reply_text(msg)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await start(update, context)


async def macro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("Pulling live macro data...")
    try:
        layer1 = MacroLayer()
        result = await layer1.full_macro_gate()
        await safe_send(update.message, result)
    except Exception as e:
        await update.message.reply_text(format_error("MACRO", str(e)))


async def fng_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    try:
        layer1 = MacroLayer()
        result = await layer1.fear_and_greed()
        await safe_send(update.message, result)
    except Exception as e:
        await update.message.reply_text(format_error("F&G", str(e)))


async def poly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("Pulling live Polymarket signals...")
    try:
        layer3 = PolymarketLayer()
        result = await layer3.top_signals()
        await safe_send(update.message, result)
    except Exception as e:
        await update.message.reply_text(format_error("POLYMARKET", str(e)))


async def alpha_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("Hunting live alpha plays...")
    try:
        layer2 = AlphaLayer()
        result = await layer2.hunt_alpha()
        await safe_send(update.message, result)
    except Exception as e:
        await update.message.reply_text(format_error("ALPHA HUNT", str(e)))


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /price BTC")
        return
    ticker = context.args[0].upper()
    await update.message.reply_text(f"Fetching live price for {ticker}...")
    try:
        layer1 = MacroLayer()
        result = await layer1.live_price_block(ticker)
        await safe_send(update.message, result)
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
        layer4 = PatternLayer()
        result = await layer4.pump_stage(ticker)
        await safe_send(update.message, result)
    except Exception as e:
        await update.message.reply_text(format_error(ticker, str(e)))


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /scan SOL")
        return
    ticker = context.args[0].upper()
    user_id = update.effective_user.id
    sessions.set_pending_coin(user_id, ticker)
    keyboard = [[
        InlineKeyboardButton("SPOT", callback_data=f"trade_spot_{ticker}"),
        InlineKeyboardButton("PERPETUAL", callback_data=f"trade_perp_{ticker}"),
    ]]
    await update.message.reply_text(
        f"{ticker} — Select trade type:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── ALERT COMMANDS ────────────────────────────────────────────────────────────

async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    user_id = update.effective_user.id

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/alert BTC 90000 — ping when BTC above $90K\n"
            "/alert SOL 80 — ping when SOL below $80\n\n"
            "Bot auto-detects direction based on current price."
        )
        return

    ticker = context.args[0].upper()
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Invalid price. Example: /alert BTC 90000")
        return

    # Fetch current price to determine direction
    live = await get_live_price(ticker)
    if live == 0:
        await update.message.reply_text(f"Could not fetch live price for {ticker}. Try again.")
        return

    direction = "above" if target > live else "below"
    result = add_alert(user_id, ticker, target, direction)
    await update.message.reply_text(
        f"Alert set.\n{ticker} currently at ${live:,.4f}\n"
        f"Will ping you when {ticker} goes {direction.upper()} ${target:,.2f}"
    )


async def alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    result = list_alerts_text(update.effective_user.id)
    await update.message.reply_text(result)


async def clearalerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    result = clear_alerts(update.effective_user.id)
    await update.message.reply_text(result)


# ── PORTFOLIO COMMANDS ────────────────────────────────────────────────────────

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    user_id = update.effective_user.id

    if not context.args:
        # Show portfolio
        await update.message.reply_text("Fetching portfolio with live prices...")
        result = await get_portfolio_text(user_id, get_live_price)
        await safe_send(update.message, result)
        return

    sub = context.args[0].lower()

    if sub == "add":
        if len(context.args) < 4:
            await update.message.reply_text(
                "Usage: /portfolio add SOL 10 85.00\n"
                "(ticker, amount, entry price)"
            )
            return
        ticker = context.args[1].upper()
        try:
            amount = float(context.args[2])
            entry = float(context.args[3])
        except ValueError:
            await update.message.reply_text("Invalid amount or price.")
            return
        result = add_position(user_id, ticker, amount, entry)
        await update.message.reply_text(result)

    elif sub == "remove":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /portfolio remove SOL")
            return
        result = remove_position(user_id, context.args[1].upper())
        await update.message.reply_text(result)

    else:
        await update.message.reply_text(
            "Portfolio commands:\n"
            "/portfolio — view with live PnL\n"
            "/portfolio add SOL 10 85.00\n"
            "/portfolio remove SOL"
        )


# ── WATCHLIST COMMANDS ────────────────────────────────────────────────────────

async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    user_id = update.effective_user.id
    wl = get_watchlist(user_id)
    await update.message.reply_text(
        f"Your watchlist ({len(wl)} coins):\n"
        f"{', '.join(wl)}\n\n"
        f"Add: /watch add TAO\n"
        f"Remove: /watch remove TAO\n"
        f"Auto-scanned every 2 hours."
    )


async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    user_id = update.effective_user.id
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage:\n/watch add TAO\n/watch remove TAO")
        return
    sub = context.args[0].lower()
    ticker = context.args[1].upper()
    if sub == "add":
        result = add_to_watchlist(user_id, ticker)
    elif sub == "remove":
        result = remove_from_watchlist(user_id, ticker)
    else:
        result = "Usage:\n/watch add TAO\n/watch remove TAO"
    await update.message.reply_text(result)


# ── CALLBACK HANDLER ──────────────────────────────────────────────────────────

async def trade_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    trade_type = parts[1]
    ticker = parts[2]

    await query.edit_message_text(
        f"Running 4-layer analysis on {ticker} [{trade_type.upper()}]...\n"
        "Pulling live data from Binance, CoinGecko, Polymarket, F&G..."
    )

    try:
        result = await engine.full_scan(ticker, trade_type)
        chunks = split_message(result)
        for chunk in chunks:
            await safe_send(query.message, chunk)
    except Exception as e:
        await query.message.reply_text(format_error(ticker, str(e)))


# ── MESSAGE HANDLER ───────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    import re
    text = update.message.text.strip().upper()
    if re.match(r'^[A-Z]{2,10}$', text):
        ticker = text
        sessions.set_pending_coin(update.effective_user.id, ticker)
        keyboard = [[
            InlineKeyboardButton("SPOT", callback_data=f"trade_spot_{ticker}"),
            InlineKeyboardButton("PERPETUAL", callback_data=f"trade_perp_{ticker}"),
        ]]
        await update.message.reply_text(
            f"{ticker} — Select trade type:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        result = await engine.claude_interpret(update.message.text)
        await safe_send(update.message, result)


# ── STARTUP ───────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Launch the bot"),
        BotCommand("macro", "Live macro gate check"),
        BotCommand("scan", "Full 4-layer scan on a coin"),
        BotCommand("alpha", "Hunt top alpha plays now"),
        BotCommand("poly", "Live Polymarket signals"),
        BotCommand("fng", "Fear and Greed Index"),
        BotCommand("price", "Quick live price"),
        BotCommand("stage", "Pump stage detection"),
        BotCommand("alert", "Set price alert"),
        BotCommand("alerts", "View your alerts"),
        BotCommand("portfolio", "Portfolio with live PnL"),
        BotCommand("watchlist", "View watchlist"),
        BotCommand("help", "All commands"),
    ])

    # Start background tasks
    asyncio.create_task(run_alert_checker(application, list(registered_users)))
    asyncio.create_task(run_auto_scanner(application, list(registered_users)))
    logger.info("Background tasks started")


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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("macro", macro_cmd))
    app.add_handler(CommandHandler("fng", fng_cmd))
    app.add_handler(CommandHandler("poly", poly_cmd))
    app.add_handler(CommandHandler("alpha", alpha_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("stage", stage_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("alerts", alerts_cmd))
    app.add_handler(CommandHandler("clearalerts", clearalerts_cmd))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))
    app.add_handler(CommandHandler("watch", watch_cmd))
    app.add_handler(CallbackQueryHandler(trade_type_callback, pattern=r"^trade_(spot|perp)_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("DOTMAN BOT LIVE — Polling started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
