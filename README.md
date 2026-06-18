# 🌾 FarmTown Auto-Farmer

Automated farming bot for [FarmTown](https://farmtown.online) — a browser-based play-to-earn game on Solana.

## Features

- 🌱 **Auto plant/harvest** — parallel harvesting & planting
- 📦 **Auto orders & jobs** — claim rewards automatically  
- 🏗️ **Auto expand** — buy plots when you have enough gold
- 🔥 **Pool burn** — auto-sacrifice gold/FP/levels to Farmer's Pool for $FARM rewards
- 🔑 **Auto-auth** — wallet challenge/verify with auto-refresh
- 📊 **Metrics** — gold/hr, harvests/hr, levels, cycles
- 👥 **Multi-wallet** — run multiple wallets in parallel

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

The launcher auto-detects all `~/.farmtown-keypair-*.json` files.

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

The bot automatically extracts the Supabase anon key from the game's JS bundle on first run. If auto-extraction fails:

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

### ⚠️ IMPORTANT: Pool Timing

The pool API may return `status: "active"` BEFORE the countdown reaches zero. Burns made before the pool is truly open will have **0 power** (wasted resources).

The bot includes a safety check: it verifies `totalClaimPower > 0` before burning, which indicates other participants have already burned successfully.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FARMTOWN_KEYPAIR` | `~/.farmtown-keypair-{ID}.json` | Keypair file path |
| `FARMTOWN_SUPAKEY` | `~/.farmtown-supakey.hex` | Supabase key file |
| `FARMTOWN_LEVEL_FLOOR` | `10` | Don't burn below this level |
| `FARMTOWN_GOLD_KEEP` | `100` | Keep this much gold on burn |
| `FARMTOWN_GOLD_RESERVE` | `1000` | Min gold for farming operations |
| `FARMTOWN_WALLETS` | auto-detect | Space-separated wallet IDs |

## How It Works

1. **Auth** — Signs a wallet challenge message using ed25519
2. **Snapshot** — Fetches current game state (tiles, inventory, gold, etc.)
3. **Cycle** — Each cycle does:
   - Claim completed jobs
   - Collect falling stars
   - Clear dead crops & blockers (trees/rocks)
   - Harvest ready crops (parallel)
   - Expand plots (when affordable)
   - Buy seeds & plant (parallel)
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

This bot interacts with a live game. Use at your own risk. The authors are not responsible for any loss of in-game assets or account bans.

## License

MIT — Use freely, contribute back if you improve it!
