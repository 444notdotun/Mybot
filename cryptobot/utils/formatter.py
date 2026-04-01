"""
FORMATTER UTILITIES
Number formatting for clean Telegram output.
"""


def fmt_price(price: float) -> str:
    """Format price based on magnitude"""
    if price == 0:
        return "0"
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.4f}"
    if price >= 0.01:
        return f"{price:.5f}"
    return f"{price:.8f}"


def fmt_pct(pct: float) -> str:
    """Format percentage with color emoji"""
    sign = "+" if pct >= 0 else ""
    emoji = "🟢" if pct >= 0 else "🔴"
    return f"{emoji} {sign}{pct:.2f}%"


def fmt_large(num: float) -> str:
    """Format large numbers with B/M/K suffix"""
    if num == 0:
        return "0"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return f"{num:.0f}"


def format_error(coin: str, error: str) -> str:
    return (
        f"⚠️ *Live fetch failed for {coin}*\n"
        f"Error: {error[:100]}\n"
        f"Please check CoinGecko or DEXScreener directly.\n"
        f"❌ No analysis without live data."
    )
