# ⚡ DOTMAN CRYPTO INTELLIGENCE BOT

> Four-Layer Live Market Intelligence System — Telegram Bot

A production-grade crypto trading signal bot powered by Claude AI. Pulls live data from Binance, CoinGecko, Polymarket, and Fear & Greed Index simultaneously, then synthesizes everything into one direct trade signal.

---

## HOW IT WORKS

Every scan runs four layers in parallel:

| Layer | What it does |
|-------|-------------|
| 🔴 Layer 1 — Macro | Live BTC, ETH, dominance, Fear & Greed, funding rate, OI |
| 🟠 Layer 2 — Alpha | Trending coins, safety checks, cross-exchange symbols |
| 🟡 Layer 3 — Polymarket | Live prediction market odds + crypto event impact |
| 🟢 Layer 4 — Patterns | RSI, support/resistance, pump stage, pattern detection |

Claude API synthesizes all four layers into one direct signal: entry zone, three take-profit levels, stop loss, leverage guidance, and confluence score.

---

## FEATURES

- **Live signals** — `/scan SOL` → full 4-layer buy/sell signal in under 5 seconds
- **Spot + Perpetual** — separate signal structure for each trade type
- **Pump stage detection** — identifies Stage 1–5 from live kline data
- **Price alerts** — `/alert BTC 90000` pings you the moment price hits
- **Portfolio tracker** — tracks your positions with live PnL in dollars and %
- **Auto-scanner** — scans your watchlist every 2 hours, pushes signals automatically
- **Macro gate** — Red/Yellow/Green verdict before every signal
- **Polymarket integration** — event odds mapped to crypto impact

---

## COMMANDS

### Analysis
| Command | Description |
|---------|-------------|
| `/scan [COIN]` | Full 4-layer signal — asks Spot or Perpetual |
| `/macro` | Live macro gate check |
| `/stage [COIN]` | Pump stage detection only |
| `/price [COIN]` | Quick live price block |
| `/alpha` | Top trending alpha plays |
| `/poly` | Live Polymarket signals |
| `/fng` | Fear & Greed Index |

### Alerts
| Command | Description |
|---------|-------------|
| `/alert BTC 90000` | Ping when BTC hits $90K |
| `/alerts` | View all active alerts |
| `/clearalerts` | Remove all alerts |

### Portfolio
| Command | Description |
|---------|-------------|
| `/portfolio` | View positions with live PnL |
| `/portfolio add SOL 10 85.00` | Add position (ticker, amount, entry) |
| `/portfolio remove SOL` | Remove position |

### Watchlist
| Command | Description |
|---------|-------------|
| `/watchlist` | View watchlist |
| `/watch add TAO` | Add coin to watchlist |
| `/watch remove TAO` | Remove coin |

---

## SETUP

### Requirements
- Python 3.10+
- Telegram Bot Token from @BotFather
- Anthropic API Key from console.anthropic.com

### Install

```bash
git clone https://github.com/YOURUSERNAME/dotman-bot.git
cd dotman-bot
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Open `.env` and fill in:

```
TELEGRAM_TOKEN=your_telegram_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### Run

```bash
python3 bot.py
```

---

## PROJECT STRUCTURE

```
cryptobot/
├── bot.py                    ← Entry point, all Telegram handlers
├── config.py                 ← Config + API base URLs
├── requirements.txt
├── .env.example              ← Copy to .env, never commit .env
│
├── core/
│   ├── data_fetcher.py       ← All live API calls
│   ├── signal_engine.py      ← Orchestrator — runs 4 layers, calls Claude
│   ├── alert_manager.py      ← Price alerts + portfolio + watchlist
│   ├── auto_scanner.py       ← 2H background scanner + alert checker
│   └── session_manager.py    ← Per-user state
│
├── layers/
│   ├── layer1_macro.py       ← Macro gate, live price block, F&G
│   ├── layer2_alpha.py       ← Alpha hunting, safety check, exchange symbols
│   ├── layer3_polymarket.py  ← Polymarket signals + phase detection
│   └── layer4_patterns.py    ← RSI, patterns, pump stage, support/resistance
│
├── utils/
│   └── formatter.py          ← Number formatting
│
└── data/                     ← Auto-created — alerts, portfolio, watchlist
```

---

## DATA SOURCES

| Source | Data |
|--------|------|
| Binance REST | Price, klines, 24H stats |
| Binance Futures | Funding rate, open interest |
| CoinGecko | Market cap, 7D change, trending |
| Fear & Greed | Sentiment index |
| Polymarket | Live prediction market odds |
| DEXScreener | DEX token data |

---

## PUMP STAGES

| Stage | Meaning | Action |
|-------|---------|--------|
| 1 — Silent Accumulation | Smart money buying quietly | Best entry window |
| 2 — Breakout Loading | Compression before move | Prepare entry |
| 3 — Breakout Confirmed | Volume explosion + pattern break | Enter fast |
| 4 — Parabolic | Overextended, no clean entry | Take profits only |
| 5 — Distribution | Smart money selling into you | Exit now |

---

## ENVIRONMENT VARIABLES

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | From @BotFather |
| `ANTHROPIC_API_KEY` | Yes | From console.anthropic.com |
| `COINGECKO_API_KEY` | No | Free tier works without this |

---

## DISCLAIMER

Personal trading tool only. Not financial advice. Never invest more than you can afford to lose.
