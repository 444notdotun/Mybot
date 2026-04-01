# ⚡ DOTMAN CRYPTO INTELLIGENCE BOT

Four-Layer Live Market Intelligence System — Telegram Bot

---

## WHAT IT DOES

Every command pulls live data from real APIs. Nothing cached. Nothing guessed.

| Layer | What it does |
|-------|-------------|
| 🔴 Layer 1 | Live BTC, ETH, macro gate, Fear & Greed, dominance |
| 🟠 Layer 2 | Alpha hunting — trending, low-cap plays, safety checks |
| 🟡 Layer 3 | Polymarket live event odds + crypto impact |
| 🟢 Layer 4 | Pattern recognition — RSI, support/resistance, pump stage |

Claude API synthesizes all 4 layers into one direct trade signal.

---

## SETUP — DO THIS ONCE

### Step 1: Get your Telegram Bot Token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Follow prompts — give your bot a name and username
4. BotFather gives you a token like: `7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
5. Copy it

### Step 2: Get your Anthropic API Key

1. Go to https://console.anthropic.com
2. Click API Keys → Create Key
3. Copy the key (starts with `sk-ant-...`)

### Step 3: Install Python dependencies

Make sure you have Python 3.10+ installed.

```bash
cd cryptobot
pip install -r requirements.txt
```

### Step 4: Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in:
```
TELEGRAM_TOKEN=your_token_from_botfather
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### Step 5: Run the bot

```bash
python bot.py
```

You should see:
```
🚀 DOTMAN BOT LIVE — Polling started
```

Now open Telegram, find your bot, and send `/start`

---

## BOT COMMANDS

| Command | What it does |
|---------|-------------|
| `/start` | Launch screen |
| `/macro` | Full live macro gate — BTC, dominance, F&G, ETH/BTC |
| `/scan SOL` | Full 4-layer signal on any coin |
| `/alpha` | Hunt top alpha plays right now |
| `/poly` | Live Polymarket event odds |
| `/fng` | Fear & Greed Index live |
| `/price BTC` | Quick live price block |
| `/stage SOL` | Pump stage detection only |
| `/help` | All commands |

**You can also just type any ticker** — `SOL`, `BTC`, `TAO`, `WIF` — and the bot auto-detects it and asks Spot or Perp.

---

## HOW A SCAN WORKS

1. You type a ticker or use `/scan TICKER`
2. Bot asks: **Spot or Perpetual?** (buttons)
3. You tap your answer
4. Bot pulls live data from all 4 layers simultaneously:
   - Binance API (price, klines, funding rate, OI)
   - CoinGecko (market cap, ATH, rank, 7D change)
   - Fear & Greed Index
   - Polymarket (live event odds)
5. Claude synthesizes everything into one signal with exact entry, 3 TPs, stop loss, leverage, and confluence score
6. Output arrives in ~5–10 seconds

---

## DATA SOURCES

All free, no API key required for basic usage:

- **Binance REST** — `api.binance.com/api/v3/`
- **Binance Futures** — `fapi.binance.com/fapi/v1/`
- **CoinGecko** — `api.coingecko.com/api/v3/`
- **Fear & Greed** — `api.alternative.me/fng/`
- **Polymarket** — `gamma-api.polymarket.com/markets`
- **DEXScreener** — `api.dexscreener.com/`

---

## RUNNING 24/7 (VPS / Server)

For continuous operation, use `screen` or `tmux`:

```bash
# Using screen
screen -S dotman
python bot.py
# Ctrl+A then D to detach
```

Or use `systemd` for auto-restart on crashes — create `/etc/systemd/system/dotman.service`:

```ini
[Unit]
Description=Dotman Crypto Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/cryptobot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10
EnvironmentFile=/path/to/cryptobot/.env

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable dotman
sudo systemctl start dotman
sudo systemctl status dotman
```

---

## PROJECT STRUCTURE

```
cryptobot/
├── bot.py                  ← Entry point, Telegram handlers
├── config.py               ← All config + API URLs
├── requirements.txt
├── .env.example            ← Copy to .env and fill keys
├── .gitignore
│
├── core/
│   ├── data_fetcher.py     ← All live API calls (Binance, CoinGecko, etc.)
│   ├── signal_engine.py    ← Orchestrator — runs 4 layers, calls Claude
│   └── session_manager.py  ← Per-user state tracking
│
├── layers/
│   ├── layer1_macro.py     ← Macro gate, price block, F&G
│   ├── layer2_alpha.py     ← Alpha hunting, safety check, exchange symbols
│   ├── layer3_polymarket.py ← Polymarket signals + phase detection
│   └── layer4_patterns.py  ← RSI, patterns, pump stage, support/resistance
│
└── utils/
    └── formatter.py        ← Number formatting for Telegram
```

---

## NEXT STEPS (PLANNED)

- [ ] Polymarket price alert monitoring (auto-ping on 15%+ odds shift)
- [ ] Price alert system (`/alert BTC 100000`)
- [ ] Portfolio tracker (`/portfolio`)
- [ ] DEX token contract address scanning
- [ ] Webhook mode for production (vs polling)
- [ ] PostgreSQL for signal history and backtesting

---

⚠️ **NOT FINANCIAL ADVICE.** This is a personal trading tool. Never risk more than you can afford to lose completely.
