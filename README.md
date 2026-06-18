# 🌾 FarmTown Auto-Farmer

Automated farming bot for [FarmTown](https://farmtown.online) — a browser-based play-to-earn game on Solana.

## Features

- 🌱 **Auto plant/harvest** — parallel harvesting & planting with **most expensive crop priority** (max EXP + gold)
- 📦 **Auto orders & jobs** — claim rewards automatically
- 🏗️ **Auto expand** — buy plots when affordable, dynamic cost scaling
- 🔥 **Pool burn** — auto-sacrifice gold/FP/levels to Farmer's Pool for $FARM rewards
- 🧹 **Auto clear** — remove dead crops, blockers (trees/rocks/bushes)
- ⭐ **Star collection** — auto-collect falling stars
- 🔑 **Auto-auth** — wallet challenge/verify with auto-refresh, Supabase key auto-extracted from game JS
- 📊 **Metrics** — gold/hr, harvests/hr, levels, cycles, errors
- 👥 **Multi-wallet** — run 1-100+ wallets in parallel via launcher
- 🎯 **Smart seed selection** — prioritizes most expensive affordable crop per level for maximum EXP/harvest
- 🌾 **All 19 crops** — full crop database from game data

## Crop Database

The bot always plants the **most expensive crop** you can afford and have level for:

| # | Crop | Level | Cost | Grow | Reward Gold | Reward XP | Profit |
|---|------|-------|------|------|-------------|-----------|--------|
| 1 | 🥔 Potato | 1 | 5g | 45s | 8g | 1 | +3g |
| 2 | 🥕 Carrot | 1 | 20g | 2m | 40g | 4 | +20g |
| 3 | 🌽 Corn | 1 | 45g | 5m | 95g | 8 | +50g |
| 4 | 🍅 Tomato | 5 | 90g | 8m | 200g | 14 | +110g |
| 5 | 🧅 Onion | 5 | 140g | 12m | 330g | 22 | +190g |
| 6 | 🌾 Wheat | 5 | 220g | 18m | 560g | 32 | +340g |
| 7 | 🎃 Pumpkin | 10 | 400g | 30m | 1,050g | 55 | +650g |
| 8 | 🍈 Melon | 10 | 650g | 45m | 1,800g | 80 | +1,150g |
| 9 | 🥒 Cucumber | 10 | 850g | 1h | 2,400g | 105 | +1,550g |
| 10 | 🌶️ Pepper | 15 | 1,300g | 1.5h | 4,000g | 150 | +2,700g |
| 11 | 🍓 Strawberry | 15 | 1,900g | 2h | 6,200g | 210 | +4,300g |
| 12 | 🫐 Blueberry | 15 | 2,600g | 3h | 8,800g | 280 | +6,200g |
| 13 | 🍇 Grape | 20 | 4,000g | 4h | 9,500g | 220 | +5,500g |
| 14 | 🍆 Eggplant | 20 | 5,500g | 5h | 13,000g | 280 | +7,500g |
| 15 | 🍉 Watermelon | 20 | 7,500g | 6h | 18,000g | 360 | +10,500g |
| 16 | 🥭 Dragonfruit | 25 | 12,000g | 8h | 28,000g | 500 | +16,000g |
| 17 | 🍍 Pineapple | 25 | 18,000g | 10h | 42,000g | 700 | +24,000g |
| 18 | 💎 Crystal Berry | 25 | 25,000g | 12h | 60,000g | 900 | +35,000g |
| 19 | ⭐ Starfruit | 30 | 50,000g | 18h | 100,000g | 1,200 | +50,000g |

**Strategy:** The bot picks the most expensive crop available at your level. Higher cost = more EXP + more gold per harvest.

**Note:** 🌿 Weed exists in-game (costs 50 Stars, premium currency) but is excluded from auto-farming.

## Quick Start

```bash
# 1. Install dependencies
pip install PyNaCl base58

# 2. Create wallet keypair file
#    Your Solana wallet bytes (64 bytes as JSON array)
echo '[253, 81, 180, 148, ...]' > ~/.farmtown-keypair-w01.json

# 3. Run single wallet
python3 farmtown-bot.py w01

# 4. Or use launcher for multi-wallet
chmod +x farmtown-launcher.sh
./farmtown-launcher.sh start
```

## Multi-Wallet Setup

Create keypair files for each wallet:
```bash
~/.farmtown-keypair-w01.json
~/.farmtown-keypair-w02.json
~/.farmtown-keypair-w03.json
# ...etc
```

```bash
./farmtown-launcher.sh start      # Start all
./farmtown-launcher.sh status     # Check status
./farmtown-launcher.sh logs w01   # View logs
./farmtown-launcher.sh stop       # Stop all
```

Or set specific wallets:
```bash
FARMTOWN_WALLETS="w01 w02 w03" ./farmtown-launcher.sh start
```

## Supabase Key (Auto-Extracted)

The bot automatically extracts the Supabase anon key from the game's JS bundle on first run. No manual setup needed.

If auto-extraction fails:
1. Visit https://play.farmtown.online in browser
2. Open DevTools → Sources
3. Search for `supabase` — find the anon key (starts with `eyJ...`)
4. Save it:
```bash
echo -n 'YOUR_KEY_HERE' | xxd -p > ~/.farmtown-supakey.hex
```

## Pool Burn Strategy

When the Farmer's Pool is active, the bot automatically burns:
- **Gold** — all except keep amount (default: 100g)
- **Farm Points** — all available
- **Levels** — all burnable levels (safety floor: Lv10)

### ⚠️ Pool Timing

The pool API may return `status: "active"` BEFORE the countdown reaches zero. Burns made before the pool is truly open will have **0 power** (wasted resources).

The bot includes a safety check: it verifies `totalClaimPower > 0` before burning.

## How It Works

1. **Auth** — Signs a wallet challenge message using ed25519
2. **Snapshot** — Fetches current game state (tiles, inventory, gold, etc.)
3. **Cycle** — Each cycle:
   - Claim completed jobs
   - Complete starter tasks
   - Collect falling stars
   - Clear dead crops & blockers (trees/rocks/bushes)
   - Harvest ready crops (parallel)
   - Expand plots (when affordable)
   - Buy seeds & plant most expensive crop (parallel)
   - Complete orders
   - Pool burn (when active)
4. **Wait** — Sleep until next cycle (based on crop grow times)
5. **Repeat**

## Requirements

- Python 3.8+
- PyNaCl (ed25519 signing)
- base58 (Solana address encoding)
- A FarmTown wallet with some starting gold

## Disclaimer

This bot interacts with a live game server. Use at your own risk. The authors are not responsible for any loss of in-game assets or account bans.

## License

MIT — Use freely, contribute back if you improve it!
