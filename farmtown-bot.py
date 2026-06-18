#!/usr/bin/env python3
"""
FarmTown Auto-Farmer v1.0
=========================
Automated farming bot for FarmTown (farmtown.online) on Solana.

Features:
- Auto plant/harvest/expand/orders/jobs
- Auto pool burn (gold + FP + levels) when pool is active
- Multi-wallet support via launcher
- Auto-auth with wallet challenge/verify
- Parallel harvesting & planting
- Metrics tracking

Requirements:
    pip install PyNaCl base58

Usage:
    python3 farmtown-bot.py <wallet_id>
    python3 farmtown-bot.py w01

Wallet keypair format (JSON array of bytes):
    [253, 81, 180, ...]  (64 bytes = 32 seed + 32 public)

Author: xbyteid
"""

import json, urllib.request, urllib.error, uuid, time, os, random, signal, sys
from concurrent.futures import ThreadPoolExecutor

try:
    import nacl.signing, base58
except ImportError:
    print("Missing dependencies. Run: pip install PyNaCl base58")
    sys.exit(1)

# ============================================================
# CONFIG - Edit these paths or use environment variables
# ============================================================
HOME = os.path.expanduser("~")
WALLET_ID = sys.argv[1] if len(sys.argv) > 1 else "w01"

HEX_FILE    = f"/tmp/.farmtown-{WALLET_ID}-token.hex"
KP_FILE     = os.environ.get("FARMTOWN_KEYPAIR", f"{HOME}/.farmtown-keypair-{WALLET_ID}.json")
SUPA_FILE   = os.environ.get("FARMTOWN_SUPAKEY", f"{HOME}/.farmtown-supakey.hex")
SUPA_TOK    = f"/tmp/.farmtown-{WALLET_ID}-supa.txt"
AUTH_TIME    = f"/tmp/.farmtown-{WALLET_ID}-auth.txt"
BASE        = "https://play.farmtown.online"

# Pool burn safety floor (don't burn below this level)
POOL_LEVEL_FLOOR = int(os.environ.get("FARMTOWN_LEVEL_FLOOR", "10"))
# Minimum gold to keep after burn
POOL_GOLD_KEEP = int(os.environ.get("FARMTOWN_GOLD_KEEP", "100"))
# Minimum gold reserve for farming (seeds + plot expansion)
FARM_GOLD_RESERVE = int(os.environ.get("FARMTOWN_GOLD_RESERVE", "1000"))

# ============================================================
# Crop data (from game JS)
# ============================================================
CROPS = [
    ("potato_seed",  1,    5,  0.75, "potato"),
    ("carrot_seed",  1,   20,  2,    "carrot"),
    ("corn_seed",    1,   45,  5,    "corn"),
    ("tomato_seed",  5,   90,  8,    "tomato"),
    ("onion_seed",   5,  140, 12,    "onion"),
    ("wheat_seed",   5,  220, 18,    "wheat"),
    ("pumpkin_seed", 10, 400, 30,    "pumpkin"),
    ("melon_seed",   10, 650, 45,    "melon"),
    ("cucumber_seed",10, 850, 60,    "cucumber"),
    ("pepper_seed",  15,1300, 90,    "pepper"),
    ("strawberry_seed",15,1900,120,  "strawberry"),
    ("blueberry_seed",15,2600,180,   "blueberry"),
]
CROP_MAP = {name: (sid, rl, cost, grow) for sid, rl, cost, grow, name in CROPS}

def plot_cost(owned_count):
    """Dynamic plot cost based on owned count (from game JS)."""
    t = max(0, int(owned_count))
    if t < 5: return 100
    if t < 15: return 250
    if t < 30: return 500
    if t < 50: return 1000
    if t < 80: return 2500
    if t < 120: return 5000
    if t < 160: return 10000
    if t < 200: return 25000
    if t < 250: return 50000
    if t < 300: return 100000
    if t < 400: return 250000
    return 500000

# ============================================================
# Graceful shutdown
# ============================================================
RUNNING = True
def sig_handler(sig, frame):
    global RUNNING; RUNNING = False
    print("\nShutting down...", flush=True)
signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)

# ============================================================
# Core utils
# ============================================================
def hd(lo=0.05, hi=0.1):
    time.sleep(random.uniform(lo, hi))

def req(url, data=None, headers=None, timeout=12):
    r = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        return json.loads(urllib.request.urlopen(r, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read())
        except: return {"ok": False, "http": e.code}
    except Exception as e:
        return {"ok": False, "err": str(e)[:80]}

# ============================================================
# Supabase key extraction
# ============================================================
def get_supabase_key():
    """
    Read Supabase anon key from file. If not found, attempt to
    extract from game's JS bundle (auto-discovery).
    """
    if os.path.exists(SUPA_FILE):
        try:
            with open(SUPA_FILE) as f:
                return bytes.fromhex(f.read().strip()).decode()
        except:
            pass

    print("[SETUP] Supabase key not found, extracting from game...", flush=True)
    try:
        # Fetch main page to find JS bundle
        page = req(BASE, timeout=15)
        # Try to get from the game's index HTML
        html = urllib.request.urlopen(urllib.request.Request(BASE,
            headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read().decode()

        # Look for supabase URL pattern in HTML/JS
        import re
        # Pattern: supabase URL + anon key
        match = re.search(r'https://([a-z0-9]+)\.supabase\.co', html)
        if match:
            project_id = match.group(1)
            # Try common supabase anon key pattern - fetch from auth endpoint
            supa_url = f"https://{project_id}.supabase.co"
            # The anon key is typically embedded in the JS bundle
            # Try fetching the JS bundles
            js_matches = re.findall(r'src="(/[^"]*\.js[^"]*)"', html)
            for js_path in js_matches:
                try:
                    js_url = BASE + js_path if js_path.startswith("/") else js_path
                    js_content = urllib.request.urlopen(urllib.request.Request(js_url,
                        headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read().decode()
                    # Look for the anon key pattern (eyJ... base64 JWT)
                    key_match = re.search(r'["\']?(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)["\']', js_content)
                    if key_match:
                        key = key_match.group(1).strip('"\'')
                        # Save it
                        with open(SUPA_FILE, "w") as f:
                            f.write(key.encode().hex())
                        print(f"[SETUP] Supabase key extracted and saved to {SUPA_FILE}", flush=True)
                        return key
                except:
                    continue
    except Exception as e:
        print(f"[SETUP] Auto-extract failed: {e}", flush=True)

    print(f"[SETUP] Could not auto-extract. Please set manually:", flush=True)
    print(f"  1. Visit {BASE} in browser", flush=True)
    print(f"  2. Open DevTools → Sources, search for 'supabase'", flush=True)
    print(f"  3. Find the anon key (starts with 'eyJ...')", flush=True)
    print(f"  4. Save it: echo -n 'YOUR_KEY' | xxd -p > {SUPA_FILE}", flush=True)
    return None

# ============================================================
# Auth
# ============================================================
def supabase_signup():
    if os.path.exists(SUPA_TOK):
        try:
            with open(SUPA_TOK) as f:
                lines = f.read().strip().split("\n")
                cached = bytes.fromhex(lines[0]).decode()
                saved_at = int(lines[1]) if len(lines) > 1 else 0
            if time.time() - saved_at < 3000:
                return cached
        except:
            pass

    supa = get_supabase_key()
    if not supa:
        return None

    h = {"Content-Type": "application/json", "apikey": supa, "Authorization": "Bearer " + supa}
    for attempt in range(6):
        ad = req(f"https://{get_supabase_project_id()}.supabase.co/auth/v1/signup",
                 json.dumps({}).encode(), h, timeout=30)
        if "access_token" in ad:
            tok = ad["access_token"]
            with open(SUPA_TOK, "w") as f:
                f.write(tok.encode().hex() + "\n" + str(int(time.time())))
            return tok
        if ad.get("http") == 429:
            time.sleep(60 * (attempt + 1))
        else:
            return None
    return None

def get_supabase_project_id():
    """Extract project ID from supabase key or file."""
    # Try from key
    supa = None
    if os.path.exists(SUPA_FILE):
        try:
            with open(SUPA_FILE) as f:
                supa = bytes.fromhex(f.read().strip()).decode()
        except:
            pass
    if supa:
        try:
            import base64
            payload = supa.split(".")[1] + "=="
            data = json.loads(base64.b64decode(payload))
            ref = data.get("ref", "")
            if ref:
                return ref
        except:
            pass
    # Fallback: extract from page
    try:
        html = urllib.request.urlopen(urllib.request.Request(BASE,
            headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read().decode()
        import re
        match = re.search(r'https://([a-z0-9]+)\.supabase\.co', html)
        if match:
            return match.group(1)
    except:
        pass
    # Fallback: try common FarmTown supabase project
    # This is a public identifier, not a secret
    try:
        html = urllib.request.urlopen(urllib.request.Request(BASE,
            headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read().decode()
        import re
        match = re.search(r'https://([a-z0-9]+)\.supabase\.co', html)
        if match:
            return match.group(1)
    except:
        pass
    print("[AUTH] Could not determine Supabase project ID.", flush=True)
    print(f"  Please create {SUPA_FILE} manually (see README)", flush=True)
    return None

def fresh_auth():
    if not os.path.exists(KP_FILE):
        print(f"[AUTH] Keypair not found: {KP_FILE}", flush=True)
        print(f"  Create it: echo '[253, 81, ...]' > {KP_FILE}", flush=True)
        return None

    with open(KP_FILE) as f:
        kb = bytes(json.load(f))
    sk = nacl.signing.SigningKey(kb[:32])
    pk = base58.b58encode(sk.verify_key.encode()).decode()
    at = supabase_signup()
    if not at:
        return None

    h2 = {"Content-Type": "application/json", "Authorization": "Bearer " + at}
    ch = req(BASE + "/api/auth/wallet/challenge",
             json.dumps({"walletAddress": pk}).encode(), h2)
    if "message" not in ch:
        return None

    sig = base58.b58encode(sk.sign(ch["message"].encode()).signature).decode()
    vr = req(BASE + "/api/auth/wallet/verify",
             json.dumps({"challengeId": ch["challengeId"], "nonce": ch["nonce"],
                         "walletAddress": pk, "signature": sig,
                         "message": ch["message"]}).encode(), h2, timeout=30)
    if not vr.get("ok"):
        time.sleep(3)
        vr = req(BASE + "/api/auth/wallet/verify",
                 json.dumps({"challengeId": ch["challengeId"], "nonce": ch["nonce"],
                             "walletAddress": pk, "signature": sig,
                             "message": ch["message"]}).encode(), h2, timeout=30)

    tok = at
    ws = vr.get("walletSessionToken", "")
    pid = vr.get("authUserId", "")
    with open(HEX_FILE, "w") as f:
        f.write(tok.encode().hex() + "\n" + ws.encode().hex() + "\n" + pid)
    with open(AUTH_TIME, "w") as f:
        f.write(str(int(time.time())))
    return tok, ws, pid

def get_auth():
    if os.path.exists(AUTH_TIME):
        try:
            age = int(time.time()) - int(open(AUTH_TIME).read().strip())
            if age < 1500:
                if os.path.exists(HEX_FILE):
                    lines = open(HEX_FILE).read().strip().split("\n")
                    return (bytes.fromhex(lines[0]).decode(),
                            bytes.fromhex(lines[1]).decode() if len(lines) > 1 else "",
                            lines[2] if len(lines) > 2 else "")
        except:
            pass
    r = fresh_auth()
    if r:
        return r
    if os.path.exists(HEX_FILE):
        try:
            lines = open(HEX_FILE).read().strip().split("\n")
            return (bytes.fromhex(lines[0]).decode(),
                    bytes.fromhex(lines[1]).decode() if len(lines) > 1 else "",
                    lines[2] if len(lines) > 2 else "")
        except:
            pass
    return None

def is_auth_expired():
    if os.path.exists(AUTH_TIME):
        try:
            return (time.time() - int(open(AUTH_TIME).read().strip())) > 1500
        except:
            return True
    return True

# ============================================================
# API with retry
# ============================================================
def api_call(path, body, headers, max_retries=3):
    for attempt in range(max_retries):
        result = req(BASE + path, json.dumps(body).encode() if body else None, headers)
        if result.get("ok") or "snapshot" in result or "playerFarmState" in result:
            return result
        if result.get("http") == 429:
            wait = 2 * (2 ** attempt)
            time.sleep(wait); continue
        if result.get("http") in (401, 403):
            if os.path.exists(HEX_FILE):
                os.remove(HEX_FILE)
            return None
        if attempt < max_retries - 1:
            time.sleep(1)
    return result

# ============================================================
# Seed selection
# ============================================================
def pick_seed(lv, gold, inv, needed_crops):
    # 1. Use inventory seeds for needed crops first
    for name in needed_crops:
        info = CROP_MAP.get(name)
        if info and inv.get(info[0], 0) > 0 and lv >= info[1]:
            return info[0], info[3]
    # 2. Use any inventory seeds
    for sid, rl, cost, grow, name in CROPS:
        if inv.get(sid, 0) > 0 and lv >= rl:
            return sid, grow
    # 3. Buy cheapest available for needed crops
    for name in needed_crops:
        info = CROP_MAP.get(name)
        if info and lv >= info[1] and gold >= info[2]:
            return info[0], info[3]
    # 4. Buy cheapest available
    for sid, rl, cost, grow, name in CROPS:
        if lv >= rl and gold >= cost:
            return sid, grow
    return None

# ============================================================
# Metrics
# ============================================================
class Metrics:
    def __init__(self):
        self.start = time.time()
        self.gold_earned = 0
        self.orders = 0
        self.harvests = 0
        self.levels = 0
        self.start_level = 0
        self.cycles = 0
        self.errors = 0
        self.expands = 0

    def update(self, gold_gain, od, hcnt, lv, el):
        self.gold_earned += gold_gain
        self.orders += od
        self.harvests += hcnt
        self.expands += el
        self.cycles += 1
        if self.start_level == 0:
            self.start_level = lv
        if lv > self.start_level:
            self.levels += (lv - self.start_level)
            self.start_level = lv

    def report(self):
        h = (time.time() - self.start) / 3600
        if h < 0.01:
            return ""
        return (f"METRICS: {self.gold_earned/h:.0f}g/hr | "
                f"{self.harvests/h:.0f} harvests/hr | "
                f"{self.orders} orders | {self.expands} expands | "
                f"{self.levels} levels | {self.cycles} cycles | "
                f"{self.errors} errors")

# ============================================================
# Pool burn helper
# ============================================================
def check_pool_open(api_func):
    """
    Check if the farmer pool is actually open (not just 'active' in API).
    Returns (is_open, pool_info, player_info) or (False, None, None).
    
    IMPORTANT: The pool API may return status='active' BEFORE the countdown
    reaches zero. Burns made before the pool is truly open will have 0 power.
    Always verify the pool countdown has ended before burning.
    """
    pool_s = api_func("/api/rewards/farmer-pool/status")
    if not pool_s or not pool_s.get("ok"):
        return False, None, None

    pool_info = pool_s.get("pool", {})
    player_info = pool_s.get("player", {})

    if pool_info.get("status", "missing") == "missing":
        return False, None, None

    # Check if pool has participants (indicates it's truly open)
    # A pool that just opened but hasn't started accepting burns
    # will have 0 totalClaimPower
    total_power = pool_info.get("totalClaimPower", 0)
    if total_power == 0 and pool_info.get("status") == "active":
        # Pool says active but no one has claimed yet - might be pre-open
        # Wait a bit and check again
        time.sleep(5)
        pool_s2 = api_func("/api/rewards/farmer-pool/status")
        if pool_s2 and pool_s2.get("ok"):
            pool_info2 = pool_s2.get("pool", {})
            if pool_info2.get("totalClaimPower", 0) > 0:
                return True, pool_info2, pool_s2.get("player", player_info)
        # Still 0 power - pool might not be truly open
        return False, pool_info, player_info

    return True, pool_info, player_info

# ============================================================
# Main loop
# ============================================================
def main():
    global RUNNING
    print(f"FarmTown Auto-Farmer v1.0 - Wallet [{WALLET_ID}]", flush=True)
    print("=" * 55, flush=True)

    # Validate keypair exists
    if not os.path.exists(KP_FILE):
        print(f"ERROR: Keypair not found: {KP_FILE}", flush=True)
        print(f"Create it with your Solana wallet bytes:", flush=True)
        print(f"  echo '[253, 81, 180, ...]' > {KP_FILE}", flush=True)
        sys.exit(1)

    metrics = Metrics()
    stuck_count = 0
    last_metrics = 0

    while RUNNING:
        time.sleep(random.uniform(0.5, 1.5))
        t0 = time.time()

        # --- Auth with auto-refresh ---
        auth = get_auth()
        if not auth:
            metrics.errors += 1
            print("AUTH_FAIL - retrying...", flush=True)
            time.sleep(30)
            continue
        tok, ws, pid = auth

        h = {"Content-Type": "application/json",
             "Authorization": "Bearer " + tok,
             "X-FarmTown-Wallet-Session": ws}

        def api(p, body=None):
            return api_call(p, body, h)

        def act(a, tool="hoe", **kw):
            return api("/api/game/action", {
                "playerId": pid, "action": a,
                "actionId": str(uuid.uuid4()),
                "clientSentAt": int(time.time() * 1000),
                "selectedTool": tool, "farmSlug": slug, **kw
            })

        # --- Snapshot with retry ---
        s = api("/api/game/snapshot")
        if not s or not s.get("snapshot"):
            metrics.errors += 1
            if is_auth_expired():
                print("Token expired, re-authing...", flush=True)
                if os.path.exists(HEX_FILE):
                    os.remove(HEX_FILE)
                time.sleep(5); continue
            print("SNAP_FAIL", flush=True)
            time.sleep(10); continue

        sd = s.get("snapshot", {})
        farm = sd.get("playerFarmState", {})
        tiles = sd.get("tiles", [])
        slug = sd.get("viewContext", {}).get("farmSlug", "")
        pid = sd.get("localPlayerId", pid)

        lv = farm.get("level", 1)
        gold = farm.get("gold", 0)
        inv = dict(farm.get("inventory", {}))
        fp = farm.get("farmPoints", 0)
        hcnt = p = od = sb = el = jc = dc = cl_cnt = 0
        msgs = []

        # --- 1. Claim completed jobs ---
        for j in farm.get("farmJobs", []):
            if j.get("current", 0) >= j.get("target", 1):
                r = act("claimFarmJob", jobId=j["id"])
                if r and r.get("ok"):
                    jc += 1
                    g = r.get("rewards", {}).get("gold", 0)
                    msgs.append(f"JOB+{g}g")
                pfs = r.get("playerFarmState", {}) if r else {}
                if pfs:
                    gold = pfs.get("gold", gold)

        # --- 2. Starter ---
        r = act("completeStarterTask")
        if r and r.get("ok"):
            msgs.append("STARTER")

        # --- 3. Stars ---
        for fs in sd.get("fallingStars", []):
            fid = fs.get("id", "")
            if fid:
                act("collect_star", fallingStarId=fid)

        # --- 4. Clear blockers ---
        owned = [t for t in tiles if t.get("ownerState") == "owned"]
        blocked_tiles = [t for t in tiles
                        if t.get("ownerState") == "locked"
                        and t.get("blocker", "none") != "none"]
        if blocked_tiles:
            owned_set = set((t["x"], t["y"]) for t in owned)
            for bt in blocked_tiles:
                bx, by = bt["x"], bt["y"]
                is_adjacent = any(
                    (bx + dx, by + dy) in owned_set
                    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]
                )
                if is_adjacent:
                    blocker = bt.get("blocker", "")
                    tool = "pickaxe" if blocker in ("rock",) else "axe"
                    r = act("clear", tool=tool, tileX=bx, tileY=by)
                    if r and r.get("ok"):
                        cl_cnt += 1
                        msgs.append(f"CLEAR({blocker})")

        # --- 5. Clear dead (parallel) ---
        dead_tiles = [t for t in tiles
                     if t.get("cropId") and t.get("groundState") == "dead"]
        if dead_tiles:
            with ThreadPoolExecutor(max_workers=6) as pool:
                d_results = list(pool.map(
                    lambda t: act("clearDead", tileX=t["x"], tileY=t["y"]).get("ok", False),
                    dead_tiles))
            dc = sum(d_results)

        # --- 6. Harvest (parallel) ---
        harvest_tiles = [t for t in tiles
                        if t.get("cropId") and t.get("groundState") == "ready"]
        if harvest_tiles:
            with ThreadPoolExecutor(max_workers=6) as pool:
                h_results = list(pool.map(
                    lambda t: act("harvest", tileX=t["x"], tileY=t["y"]).get("ok", False),
                    harvest_tiles))
            hcnt = sum(h_results)

        # Refresh after harvest
        if hcnt > 0 or dc > 0 or cl_cnt > 0:
            s2 = api("/api/game/snapshot")
            if s2 and s2.get("snapshot"):
                sd2 = s2.get("snapshot", {})
                farm = sd2.get("playerFarmState", {})
                gold = farm.get("gold", 0)
                inv = dict(farm.get("inventory", {}))
                tiles = sd2.get("tiles", [])
                fp = farm.get("farmPoints", 0)

        # --- 7. Collect needed crops ---
        needed_crops = []
        crop_inv = dict(farm.get("cropInventory", {}))

        for o in farm.get("orders", []):
            for cname, qty in o.get("requires", {}).items():
                have = crop_inv.get(cname, 0)
                if have < qty and cname not in needed_crops:
                    needed_crops.append(cname)

        for j in farm.get("farmJobs", []):
            if j.get("current", 0) < j.get("target", 1):
                cid = j.get("cropId", "")
                if cid and cid not in needed_crops:
                    needed_crops.append(cid)

        # --- 8. Expand plots ---
        owned_count = len([t for t in tiles if t.get("ownerState") == "owned"])
        pc = plot_cost(owned_count)
        seed_reserve = owned_count * 5
        reserve = FARM_GOLD_RESERVE + seed_reserve
        available_for_expand = gold - reserve
        max_expand = max(0, available_for_expand // pc) if pc > 0 else 0

        if max_expand > 0:
            done = set()
            for t in tiles:
                if t.get("ownerState") != "owned":
                    continue
                if el >= max_expand:
                    break
                if gold - pc < FARM_GOLD_RESERVE:
                    break
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx, ny = t["x"] + dx, t["y"] + dy
                    if (nx, ny) in done:
                        continue
                    tile = next((tt for tt in tiles if tt["x"] == nx and tt["y"] == ny), None)
                    if not tile:
                        continue
                    if tile.get("ownerState") == "locked":
                        if tile.get("blocker", "none") != "none":
                            blocker = tile.get("blocker", "")
                            tool = "pickaxe" if blocker in ("rock",) else "axe"
                            cr = act("clear", tool=tool, tileX=nx, tileY=ny)
                            if cr and cr.get("ok"):
                                cl_cnt += 1
                                msgs.append(f"CLEAR({blocker})")
                            hd(0.1, 0.2)
                        if gold - pc >= FARM_GOLD_RESERVE:
                            if act("buyPlot", tileX=nx, tileY=ny).get("ok"):
                                el += 1; gold -= pc; done.add((nx, ny))
                                msgs.append("EXPAND+1")
                        if el >= max_expand:
                            break
                if el >= max_expand:
                    break

        # Refresh tiles after expand
        if el > 0:
            s3 = api("/api/game/snapshot")
            if s3 and s3.get("snapshot"):
                sd3 = s3.get("snapshot", {})
                tiles = sd3.get("tiles", [])
                farm = sd3.get("playerFarmState", {})
                gold = farm.get("gold", 0)
                inv = dict(farm.get("inventory", {}))

        # --- 9. Buy seeds ---
        empty = [t for t in tiles if t.get("ownerState") == "owned" and not t.get("cropId")]
        ts = sum(v for k, v in inv.items() if k.endswith("_seed") and v > 0)
        need = max(len(empty), 9) - ts

        if need > 0:
            # First buy for needed crops
            for cname in needed_crops:
                if need <= 0:
                    break
                info = CROP_MAP.get(cname)
                if not info:
                    continue
                sid, rl, cost, grow = info
                if lv >= rl and gold >= cost and (gold - cost >= FARM_GOLD_RESERVE or gold <= FARM_GOLD_RESERVE):
                    buy = min(need, max(1, gold - 100) // cost, 20)
                    if buy > 0:
                        if act("buySeed", seedId=sid, quantity=buy, selectedSeedId=sid).get("ok"):
                            sb += buy; gold -= cost * buy
                            inv[sid] = inv.get(sid, 0) + buy
                        need = max(len(empty), 9) - sum(v for k, v in inv.items() if k.endswith("_seed") and v > 0)
            # Then cheapest available
            for sid, rl, cost, grow, name in CROPS:
                if need <= 0:
                    break
                if lv >= rl and gold >= cost and (gold - cost >= FARM_GOLD_RESERVE or gold <= FARM_GOLD_RESERVE):
                    buy = min(need, max(1, gold - 100) // cost, 20)
                    if buy > 0:
                        if act("buySeed", seedId=sid, quantity=buy, selectedSeedId=sid).get("ok"):
                            sb += buy; gold -= cost * buy
                            inv[sid] = inv.get(sid, 0) + buy
                        need = max(len(empty), 9) - sum(v for k, v in inv.items() if k.endswith("_seed") and v > 0)

        # --- 10. Parallel hoe+plant ---
        empty = [t for t in tiles if t.get("ownerState") == "owned" and not t.get("cropId")]
        plant_queue = []
        for t in empty:
            pick = pick_seed(lv, gold, inv, needed_crops)
            if not pick:
                break
            seed, grow_min = pick
            if inv.get(seed, 0) <= 0:
                break
            plant_queue.append((t, seed))
            inv[seed] = inv.get(seed, 0) - 1

        def hoe_and_plant(args):
            tile, seed = args
            gs = tile.get("groundState", "")
            if gs in ("grass", "cleared", "tilled"):
                act("hoe", tileX=tile["x"], tileY=tile["y"])
            r = act("plant", tileX=tile["x"], tileY=tile["y"],
                    seedId=seed, selectedSeedId=seed)
            return r.get("ok", False)

        if plant_queue:
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(hoe_and_plant, plant_queue))
            p = sum(results)

        # --- 11. Complete orders ---
        sd3 = api("/api/game/snapshot")
        if sd3 and sd3.get("snapshot"):
            farm3 = sd3.get("snapshot", {}).get("playerFarmState", {})
            crops = dict(farm3.get("cropInventory", {}))
            for o in farm3.get("orders", []):
                reqs = o.get("requires", {})
                if all(crops.get(c, 0) >= q for c, q in reqs.items()):
                    if act("completeOrder", orderId=o["id"]).get("ok"):
                        od += 1
                        g = o.get("rewards", {}).get("gold", 0)
                        msgs.append(f"ORD+{g}g")
                    for c, q in reqs.items():
                        crops[c] = crops.get(c, 0) - q

        # --- 12. Pool burn (with safety checks) ---
        pool_open, pool_info, player_info = check_pool_open(api)
        if pool_open and pool_info and player_info:
            burnable_levels = player_info.get("burnableLevels", 0)

            burn_fp = fp if fp > 0 else 0
            burn_gold = max(0, gold - POOL_GOLD_KEEP) if gold > POOL_GOLD_KEEP else 0
            burn_levels = burnable_levels if burnable_levels > 0 else 0

            if burn_fp > 0 or burn_gold > 0 or burn_levels > 0:
                r = api("/api/rewards/farmer-pool/claim", {
                    "actionId": str(uuid.uuid4()),
                    "goldToBurn": burn_gold,
                    "farmPointsToBurn": burn_fp,
                    "levelsToBurn": burn_levels
                })
                if r and r.get("ok"):
                    msgs.append(f"POOL!-{burn_gold}g-{burn_fp}fp-{burn_levels}lv")
                    gold = POOL_GOLD_KEEP
                    fp = 0
                    lv = max(POOL_LEVEL_FLOOR, lv - burn_levels)

                    # Log pool claim
                    est_payout = player_info.get("estimatedPayoutRaw", "0")
                    claim_power = r.get("claim", {}).get("claimPower", 0)
                    with open("/tmp/farmtown-pool.log", "a") as pf:
                        pf.write(f"[{time.strftime('%Y-%m-%d %H:%M')}] {WALLET_ID} | "
                                f"Power: +{claim_power} | "
                                f"Burned: {burn_gold}g + {burn_fp}fp + {burn_levels}lv | "
                                f"Pool: {pool_info.get('status', '?')}\n")

        # --- METRICS ---
        gold_gain = sum(int(m.split('+')[1].rstrip('g'))
                       for m in msgs if m.startswith(('ORD+', 'JOB+')))
        metrics.update(gold_gain, od, hcnt, lv, el)

        # --- REPORT ---
        elapsed = int(time.time() - t0)
        planted_now = sum(1 for t in tiles if t.get("cropId"))
        ready_now = sum(1 for t in tiles
                       if t.get("cropId") and t.get("groundState") == "ready")
        growing_now = sum(1 for t in tiles
                         if t.get("cropId") and t.get("groundState") in ("growing", "seedling"))
        need_str = ",".join(needed_crops[:3]) if needed_crops else "none"
        pc_now = plot_cost(owned_count)

        status = f"Lv{lv}|G:{gold}|FP:{fp}|P:{planted_now}({ready_now}r/{growing_now}g)|{owned_count}plots"
        actions = f"H:{hcnt}|P:{p}|B:{sb}|O:{od}|E:{el}|J:{jc}|DC:{dc}|CL:{cl_cnt}"
        print(f"[{time.strftime('%H:%M')}] {status} | {actions} | "
              f"{elapsed}s need=[{need_str}] plotCost:{pc_now}g {'|'.join(msgs)}",
              flush=True)

        # Stuck detection
        if planted_now == 0 and sb == 0 and hcnt == 0:
            stuck_count += 1
            if stuck_count >= 5:
                print(f"⚠️ STUCK {stuck_count} cycles (G:{gold} seeds:{ts})", flush=True)
        else:
            stuck_count = 0

        # Wait for next cycle
        min_wait = 10
        if planted_now == 0 and sb == 0:
            min_wait = 15
            if gold < 5:
                min_wait = 30
        # Check growing crops for optimal wait
        for t in tiles:
            if t.get("cropId") and t.get("groundState") in ("growing", "seedling"):
                for sid, rl, cost, grow, name in CROPS:
                    if name == t.get("cropId"):
                        min_wait = min(min_wait, max(grow * 30, 10))
                        break

        wait = max(min_wait, 10) + random.uniform(1, 3)
        if RUNNING:
            time.sleep(wait)

    # Final metrics
    mr = metrics.report()
    if mr:
        print(mr, flush=True)
    print("Bot stopped.", flush=True)

if __name__ == "__main__":
    main()
