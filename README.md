# FarmTown Auto-Farmer Bot

A multi-wallet automation bot for [FarmTown](https://play.farmtown.online) — an on-chain farming game on Solana.

## Features

- **Multi-wallet support** — run 30+ wallets in parallel
- **Auto farming** — harvest, plant, hoe grass, clear dead crops
- **Crop rotation** — automatic rotation through all 19 crops for XP optimization
- **Order completion** — auto-complete farm orders and jobs
- **Pool burns** — auto-burn levels when pool is active (levels only, gold preserved)
- **Storage upgrades** — auto-upgrade when gold threshold met
- **Status monitoring** — JSON status files for zero-API-call monitoring
- **Anti-detection** — randomized delays, human-like behavior patterns

## Quick Start

### 1. Install dependencies

```bash
pip3 install pynacl base58
```

### 2. Create wallet keypair files

```bash
# Generate a keypair (example with Python)
python3 -c "import nacl.signing, json; k=nacl.signing.SigningKey.generate(); print(list(k.encode() + k.verify_key.encode()))" > ~/.farmtown-keypair-w01.json
```

Create keypair files for each wallet:
```
~/.farmtown-keypair-w01.json
~/.farmtown-keypair-w02.json
...
~/.farmtown-keypair-w30.json
```

### 3. Configure secrets

Create `/root/.farmtown-env` with your API keys:

```bash
# Captcha providers (for Supabase auth)
SOLVERIFY_KEY="your_solverify_key_here"
CAPTCHA_2CAPTCHA_KEY="your_2captcha_key_here"

# Turnstile sitekey (public, but configurable)
TURNSTILE_SITEKEY="0x4AAAAAADn068lY1uOdr9LV"
```

**Never commit this file!** It's already in `.gitignore`.

### 4. Run the launcher

```bash
chmod +x farmtown-launcher.sh
./farmtown-launcher.sh
```

## Bot Commands

```bash
# Start all bots
./farmtown-launcher.sh

# Check status
ps aux | grep farmtown-bot.py | grep -v grep | wc -l

# View logs
tail -f /tmp/farmtown-logs/w01.log

# Stop all bots
pkill -f "farmtown-bot.py"
```

## Configuration

Edit `farmtown-bot.py` to customize:

- `MIN_GOLD` — minimum gold reserve (default: 5000)
- `CROPS` — crop rotation order
- `EXPAND_ENABLED` — enable/disable plot expansion
- `BURN_LEVEL_THRESHOLD` — level to trigger burns (default: 35)

## Supabase Key (Auto-Extracted)

The bot automatically extracts the Supabase anon key from the game's JS bundle on first run. No manual setup needed.

If you need to manually extract it:
1. Open browser DevTools → Network tab
2. Visit https://play.farmtown.online
3. Search for `supabase` — find the anon key (starts with `eyJ...`)
4. Save to `~/.farmtown-supakey.hex` as hex: `python3 -c "print('your_key'.encode().hex())"`

## Pool Burns

The bot automatically burns levels when:
- Pool status is "active" AND enabled
- `totalClaimPower > 0` (proves pool is truly open)
- Bot has burnable levels (above threshold)

**Important:** Gold is NEVER burned. Only levels and FP.

## Monitoring

The bot writes status to `/tmp/farmtown-status/wXX.json` each cycle:

```json
{
  "level": 35,
  "gold": 1500000,
  "fp": 50000,
  "plots": 200,
  "power": 150,
  "crop_idx": 5,
  "timestamp": 1719000000
}
```

Monitor script reads these files instead of querying the API (zero API calls).

## Anti-Detection

- Randomized delays (0.8-2.5s between actions)
- Human-like username patterns
- Per-wallet IP isolation (optional Tor SOCKS5)
- Staggered bot startup (15s between each)

## License

MIT

## Disclaimer

This bot is for **educational purposes only**. Use at your own risk. The authors are not responsible for any consequences including but not limited to account bans, loss of in-game assets, or violations of FarmTown's Terms of Service.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.
