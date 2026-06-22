#!/usr/bin/env python3
"""FarmTown v18.1 - Rules-compliant: LEVELS-ONLY burn, burn-at-cap, crop rotation."""
import json, urllib.request, urllib.error, uuid, time, os, random, signal, sys, nacl.signing, base58
from concurrent.futures import ThreadPoolExecutor

HOME = os.path.expanduser("~")
WALLET_ID = sys.argv[1] if len(sys.argv) > 1 else "w01"
HEX_FILE = f"/tmp/.farmtown-{WALLET_ID}-token.hex"
KP_FILE = f"{HOME}/.farmtown-keypair-{WALLET_ID}.json"
SUPA_FILE = HOME + "/.farmtown-supakey.hex"
SUPA_TOK = f"/tmp/.farmtown-{WALLET_ID}-supa.txt"
AUTH_TIME = f"/tmp/.farmtown-{WALLET_ID}-auth.txt"
CROP_IDX_FILE = f"/tmp/.farmtown-{WALLET_ID}-cropidx.txt"

def get_crop_idx():
    try:
        with open(CROP_IDX_FILE) as f:
            return int(f.read().strip())
    except:
        return 0

def set_crop_idx(idx):
    with open(CROP_IDX_FILE, "w") as f:
        f.write(str(idx))

# Track total crops planted in current rotation round
PLANTED_ROUND_FILE = f"/tmp/.farmtown-{WALLET_ID}-planted_round.txt"

def get_planted_round():
    try:
        return int(open(PLANTED_ROUND_FILE).read().strip())
    except:
        return 0

def set_planted_round(n):
    with open(PLANTED_ROUND_FILE, "w") as f:
        f.write(str(n))

BASE = "https://play.farmtown.online"

# (seed_id, min_level, cost_gold, grow_minutes, crop_name)
CROPS = [
    ("potato_seed",       1,     5,    0.75, "potato"),
    ("carrot_seed",       1,    20,    2,    "carrot"),
    ("corn_seed",         1,    45,    5,    "corn"),
    ("tomato_seed",       5,    90,    8,    "tomato"),
    ("onion_seed",        5,   140,   12,    "onion"),
    ("wheat_seed",        5,   220,   18,    "wheat"),
    ("pumpkin_seed",     10,   400,   30,    "pumpkin"),
    ("melon_seed",       10,   650,   45,    "melon"),
    ("cucumber_seed",    10,   850,   60,    "cucumber"),
    ("pepper_seed",      15,  1300,   90,    "pepper"),
    ("strawberry_seed",  15,  1900,  120,    "strawberry"),
    ("blueberry_seed",   15,  2600,  180,    "blueberry"),
    ("grape_seed",       20,  4000,  240,    "grape"),
    ("eggplant_seed",    20,  5500,  300,    "eggplant"),
    ("watermelon_seed",  20,  7500,  360,    "watermelon"),
    ("dragonfruit_seed", 25, 12000,  480,    "dragonfruit"),
    ("pineapple_seed",   25, 18000,  600,    "pineapple"),
    ("crystal_berry_seed",25,25000,  720,    "crystal_berry"),
    ("starfruit_seed",   30, 50000, 1080,    "starfruit"),
]
CROP_MAP = {name: (sid, rl, cost, grow) for sid, rl, cost, grow, name in CROPS}

# Dynamic plot cost based on owned count (from game JS)
def plot_cost(owned_count):
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

# Storage tiers (from game JS)
STORAGE_TIERS = [
    {"tier": 0, "itemId": "starter_pouch", "capacity": 30, "costGold": 0},
    {"tier": 1, "itemId": "small_storage_crate", "capacity": 75, "costGold": 25000},
    {"tier": 2, "itemId": "big_storage_crate", "capacity": 125, "costGold": 100000},
    {"tier": 3, "itemId": "farm_storage_chest", "capacity": 200, "costGold": 500000},
]

RUNNING = True
def sig_handler(sig, frame):
    global RUNNING; RUNNING = False; print("\nShutting down...", flush=True)
signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)

# --- Proxy config (SOCKS5 per wallet — each wallet gets unique exit IP) ---
# Tor gives each port a different circuit → different exit node → different IP
# Ports 9050-9060 mapped to w01-w11
# Set NO_PROXY=1 to skip Tor (direct connection, faster)
_wallet_idx = int(WALLET_ID.replace("w","")) - 1 if WALLET_ID.startswith("w") and WALLET_ID[1:].isdigit() else 0
_tor_base = 9050
_tor_port = _tor_base + _wallet_idx
MY_PROXY = f"socks5h://127.0.0.1:{_tor_port}"

if os.environ.get("NO_PROXY","") != "1":
    import socket, socks as socks_mod
    _sock_host = "127.0.0.1"
    _sock_port = _tor_port
    _orig_socket = socket.socket
    def _proxy_socket(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0, fileno=None):
        s = socks_mod.socksocket()
        s.set_proxy(socks_mod.SOCKS5, _sock_host, _sock_port)
        return s
    socket.socket = _proxy_socket
    print(f"[{WALLET_ID}] Proxy: Tor:{_tor_port}", flush=True)
else:
    print(f"[{WALLET_ID}] Direct connection (no proxy)", flush=True)

# --- Core utils ---
def hd(lo=0.05, hi=0.1): time.sleep(random.uniform(lo, hi))

def req(url, data=None, headers=None, timeout=25):
    r = urllib.request.Request(url, data=data, headers=headers or {})
    try: return json.loads(urllib.request.urlopen(r, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read())
        except: return {"ok":False,"http":e.code}
    except Exception as e: return {"ok":False,"err":str(e)[:80]}

# --- Captcha Solver (Solverify primary, 2Captcha fallback) ---
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY", "0x4AAAAAADn068lY1uOdr9LV")
TURNSTILE_URL = "https://play.farmtown.online"

# Provider config: (name, base_url, api_key)
CAPTCHA_PROVIDERS = [
    ("Solverify", "https://solver.solverify.net", os.environ.get("SOLVERIFY_KEY", "")),
    ("2Captcha", "https://api.2captcha.com", os.environ.get("CAPTCHA_2CAPTCHA_KEY", "")),
]

def solve_turnstile():
    """Solve Cloudflare Turnstile. Try Solverify first, fallback to 2Captcha."""
    for provider_name, base_url, api_key in CAPTCHA_PROVIDERS:
        if not api_key:
            continue
        try:
            print(f"[{WALLET_ID}] Solving Turnstile via {provider_name}...", flush=True)
            payload = json.dumps({
                "clientKey": api_key,
                "task": {
                    "type": "TurnstileTaskProxyless",
                    "websiteURL": TURNSTILE_URL,
                    "websiteKey": TURNSTILE_SITEKEY
                }
            }).encode()
            r = req(f"{base_url}/createTask", payload,
                    {"Content-Type": "application/json"}, timeout=30)
            task_id = r.get("taskId")
            if not task_id:
                print(f"[{WALLET_ID}] {provider_name} submit failed: {r}", flush=True)
                continue
            print(f"[{WALLET_ID}] {provider_name} task: {task_id}", flush=True)

            # Poll for result (max 120s)
            for i in range(24):
                time.sleep(5)
                poll = req(f"{base_url}/getTaskResult",
                           json.dumps({"clientKey": api_key, "taskId": task_id}).encode(),
                           {"Content-Type": "application/json"}, timeout=15)
                if poll.get("status") == "ready":
                    token = poll.get("solution", {}).get("token", "")
                    print(f"[{WALLET_ID}] Turnstile solved via {provider_name}! ({(i+1)*5}s)", flush=True)
                    return token
                if poll.get("errorId", 0) > 0:
                    err = poll.get('errorDescription', '?')
                    print(f"[{WALLET_ID}] {provider_name} error: {err}", flush=True)
                    if "ERROR_ZERO_BALANCE" in str(err) or "balance" in str(err).lower():
                        break  # Try next provider
                    return None
        except Exception as e:
            print(f"[{WALLET_ID}] {provider_name} exception: {e}", flush=True)
    return None

# --- Auth ---
def supabase_signup():
    if os.path.exists(SUPA_TOK):
        try:
            with open(SUPA_TOK) as f:
                lines = f.read().strip().split("\n")
                cached = bytes.fromhex(lines[0]).decode()
                saved_at = int(lines[1]) if len(lines)>1 else 0
                refresh_tok = bytes.fromhex(lines[2]).decode() if len(lines)>2 else None
            if time.time() - saved_at < 300: return cached
            # Try refresh token (bypasses captcha)
            if refresh_tok:
                with open(SUPA_FILE) as f: supa = bytes.fromhex(f.read().strip()).decode()
                h = {"Content-Type":"application/json","apikey":supa}
                rd = req("https://irarxwyrpmmxacrbvpnz.supabase.co/auth/v1/token?grant_type=refresh_token",
                    json.dumps({"refresh_token": refresh_tok}).encode(), h, timeout=15)
                if "access_token" in rd:
                    new_tok = rd["access_token"]
                    new_refresh = rd.get("refresh_token", refresh_tok)
                    with open(SUPA_TOK,"w") as f:
                        f.write(new_tok.encode().hex()+"\n"+str(int(time.time()))+"\n"+new_refresh.encode().hex())
                    return new_tok
        except: pass
    with open(SUPA_FILE) as f: supa = bytes.fromhex(f.read().strip()).decode()
    h = {"Content-Type":"application/json","apikey":supa,"Authorization":"Bearer "+supa}
    for attempt in range(6):
        # Try signup without captcha first
        ad = req("https://irarxwyrpmmxacrbvpnz.supabase.co/auth/v1/signup", json.dumps({}).encode(), h, timeout=30)
        print(f"[{WALLET_ID}] Signup attempt {attempt+1}: {ad.get('error_code','ok')}", flush=True)
        # If captcha required, solve it
        if ad.get("error_code") == "captcha_failed" or "captcha" in str(ad).lower():
            token = solve_turnstile()
            if token:
                print(f"[{WALLET_ID}] Submitting captcha token...", flush=True)
                ad = req("https://irarxwyrpmmxacrbvpnz.supabase.co/auth/v1/signup",
                    json.dumps({"gotrue_meta_security":{"captcha_token": token}}).encode(), h, timeout=30)
                print(f"[{WALLET_ID}] Captcha result: {ad.get('error_code','ok')}", flush=True)
        if "access_token" in ad:
            tok = ad["access_token"]
            refresh = ad.get("refresh_token", "")
            with open(SUPA_TOK,"w") as f:
                f.write(tok.encode().hex()+"\n"+str(int(time.time()))+"\n"+refresh.encode().hex())
            return tok
        if ad.get("http") == 429: time.sleep(60 * (attempt + 1))
        else: time.sleep(5)
    return None

def fresh_auth():
    with open(KP_FILE) as f: kb = bytes(json.load(f))
    sk = nacl.signing.SigningKey(kb[:32])
    pk = base58.b58encode(sk.verify_key.encode()).decode()
    at = supabase_signup()
    if not at:
        print(f"[{WALLET_ID}] fresh_auth: supabase_signup failed", flush=True)
        return None
    h2 = {"Content-Type":"application/json","Authorization":"Bearer "+at}
    ch = req(BASE+"/api/auth/wallet/challenge", json.dumps({"walletAddress":pk}).encode(), h2)
    if "message" not in ch or "challengeId" not in ch:
        print(f"[{WALLET_ID}] fresh_auth: challenge failed: {str(ch)[:100]}", flush=True)
        if os.path.exists(SUPA_TOK): os.remove(SUPA_TOK)
        return None
    sig = base58.b58encode(sk.sign(ch["message"].encode()).signature).decode()
    vr = req(BASE+"/api/auth/wallet/verify", json.dumps({"challengeId":ch["challengeId"],
        "nonce":ch["nonce"],"walletAddress":pk,"signature":sig,"message":ch["message"]}).encode(), h2, timeout=30)
    if not vr.get("ok"):
        time.sleep(3)
        vr = req(BASE+"/api/auth/wallet/verify", json.dumps({"challengeId":ch["challengeId"],
            "nonce":ch["nonce"],"walletAddress":pk,"signature":sig,"message":ch["message"]}).encode(), h2, timeout=30)
    tok = at; ws = vr.get("walletSessionToken",""); pid = vr.get("authUserId","")
    if not ws:
        print(f"[{WALLET_ID}] fresh_auth: verify failed: {str(vr)[:100]}", flush=True)
        if os.path.exists(SUPA_TOK): os.remove(SUPA_TOK)
        return None
    with open(HEX_FILE,"w") as f: f.write(tok.encode().hex()+"\n"+ws.encode().hex()+"\n"+pid)
    with open(AUTH_TIME,"w") as f: f.write(str(int(time.time())))
    print(f"[{WALLET_ID}] fresh_auth: OK", flush=True)
    return tok, ws, pid

def get_auth():
    if os.path.exists(AUTH_TIME):
        try:
            age = int(time.time()) - int(open(AUTH_TIME).read().strip())
            if age < 1500:
                if os.path.exists(HEX_FILE):
                    lines = open(HEX_FILE).read().strip().split("\n")
                    return bytes.fromhex(lines[0]).decode(), bytes.fromhex(lines[1]).decode() if len(lines)>1 else "", lines[2] if len(lines)>2 else ""
        except: pass
    r = fresh_auth()
    if r: return r
    if os.path.exists(HEX_FILE):
        try:
            lines = open(HEX_FILE).read().strip().split("\n")
            return bytes.fromhex(lines[0]).decode(), bytes.fromhex(lines[1]).decode() if len(lines)>1 else "", lines[2] if len(lines)>2 else ""
        except: pass
    return None

def is_auth_expired():
    if os.path.exists(AUTH_TIME):
        try: return (time.time() - int(open(AUTH_TIME).read().strip())) > 1500
        except: return True
    return True

# --- API with retry ---
def api_call(path, body, headers, max_retries=3):
    for attempt in range(max_retries):
        result = req(BASE+path, json.dumps(body).encode() if body else None, headers)
        if result.get("ok") or "snapshot" in result or "playerFarmState" in result:
            return result
        if result.get("http") == 429:
            wait = 2 * (2 ** attempt)
            time.sleep(wait); continue
        if result.get("http") in (401, 403):
            if os.path.exists(HEX_FILE): os.remove(HEX_FILE)
            if os.path.exists(SUPA_TOK): os.remove(SUPA_TOK)
            return None
        if attempt < max_retries - 1: time.sleep(1)
    return result

# --- Seed selection: prefer seeds we HAVE, then rotation crop ---
def pick_seed(lv, gold, inv, needed_crops):
    """Pick a seed to plant: prefer seeds we actually have in inventory."""
    idx = get_crop_idx()
    # Pass 1: find seeds we HAVE starting from rotation index
    for i in range(len(CROPS)):
        ci = (idx + i) % len(CROPS)
        sid, rl, cost, grow, name = CROPS[ci]
        if lv < rl: continue
        if inv.get(sid, 0) > 0:
            return sid, grow
    # Pass 2: find ANY seeds we have (any crop)
    for sid, rl, cost, grow, name in CROPS:
        if lv >= rl and inv.get(sid, 0) > 0:
            return sid, grow
    return None

# --- Metrics ---
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
        if self.start_level == 0: self.start_level = lv
        if lv > self.start_level:
            self.levels += (lv - self.start_level)
            self.start_level = lv

    def report(self):
        h = (time.time() - self.start) / 3600
        if h < 0.01: return ""
        return f"METRICS: {self.gold_earned/h:.0f}g/hr | {self.harvests/h:.0f} harvests/hr | {self.orders} orders | {self.expands} expands | {self.levels} levels | {self.cycles} cycles | {self.errors} errors"

# --- Main ---

def main():
    global RUNNING
    print(f"FarmTown v19 — Wallet [{WALLET_ID}] — Continuous Loop", flush=True)
    print("=" * 55, flush=True)

    metrics = Metrics()
    stuck_count = 0
    last_metrics = 0
    last_heavy = 0
    HEAVY_INTERVAL = 300  # 5 min between heavy ops
    my_power = 0

    # Pool auth setup (once)
    POOL_HEX = f"/tmp/.farmtown-{WALLET_ID}-pool.hex"

    while RUNNING:
        time.sleep(random.uniform(2, 4))
        t0 = time.time()

        # --- Auth ---
        auth = get_auth()
        if not auth:
            metrics.errors += 1
            print("AUTH_FAIL - retrying...", flush=True)
            time.sleep(30)
            continue
        tok, ws, pid = auth

        h = {"Content-Type":"application/json","Authorization":"Bearer "+tok,"X-FarmTown-Wallet-Session":ws}
        def api(p, body=None): return api_call(p, body, h)
        def act(a, tool="hoe", **kw): return api("/api/game/action", {"playerId":pid,"action":a,"actionId":str(uuid.uuid4()),
            "clientSentAt":int(time.time()*1000),"selectedTool":tool,"farmSlug":slug,**kw})

        # --- Snapshot ---
        s = api("/api/game/snapshot")
        if not s or not s.get("snapshot"):
            metrics.errors += 1
            if is_auth_expired():
                print("Token expired, re-authing...", flush=True)
                if os.path.exists(HEX_FILE): os.remove(HEX_FILE)
                if os.path.exists(SUPA_TOK): os.remove(SUPA_TOK)
                time.sleep(5); continue
            print("SNAP_FAIL", flush=True)
            if metrics.errors % 3 == 0:
                if os.path.exists(HEX_FILE): os.remove(HEX_FILE)
                if os.path.exists(SUPA_TOK): os.remove(SUPA_TOK)
            time.sleep(10); continue

        sd = s.get("snapshot",{}); farm = sd.get("playerFarmState",{})
        tiles = sd.get("tiles",[]); slug = sd.get("viewContext",{}).get("farmSlug",""); pid = sd.get("localPlayerId",pid)
        lv = farm.get("level",1); gold = farm.get("gold",0); inv = dict(farm.get("inventory",{}))
        fp = farm.get("farmPoints",0)
        msgs = []; hcnt = p = dc = 0

        # ============================================================
        # FAST LOOP: harvest → clear dead → buy seeds → plant
        # ============================================================

        # --- 1. Harvest ALL ready crops (parallel) ---
        ready_tiles = [t for t in tiles if t.get("cropId") and t.get("groundState")=="ready"]
        if ready_tiles:
            with ThreadPoolExecutor(max_workers=6) as pool:
                h_results = list(pool.map(lambda t: (act("harvest", tileX=t["x"], tileY=t["y"]) or {}).get("ok",False), ready_tiles))
            hcnt = sum(h_results)

        # --- 2. Clear dead crops (withered) ---
        dead_tiles = [t for t in tiles if t.get("cropId") and t.get("groundState")=="dead"]
        if dead_tiles:
            with ThreadPoolExecutor(max_workers=6) as pool:
                d_results = list(pool.map(lambda t: (act("clearDead", tileX=t["x"], tileY=t["y"]) or {}).get("ok",False), dead_tiles))
            dc = sum(d_results)

        # --- 3. Refresh state after harvest/clear ---
        if hcnt > 0 or dc > 0:
            s2 = api("/api/game/snapshot")
            if s2 and s2.get("snapshot"):
                sd = s2.get("snapshot",{}); farm = sd.get("playerFarmState",{})
                tiles = sd.get("tiles",[]); gold = farm.get("gold",0); inv = dict(farm.get("inventory",{})); fp = farm.get("farmPoints",0)

        # --- 4. Buy seeds + Plant empty plots ---
        empty = [t for t in tiles if t.get("ownerState")=="owned" and not t.get("cropId")]
        if empty:
            # Buy seeds for rotation crop
            crop_idx = get_crop_idx()
            needed_crops = []
            crop_inv = dict(farm.get("cropInventory",{}))
            for o in farm.get("orders",[]):
                for cname, qty in o.get("requires",{}).items():
                    if crop_inv.get(cname,0) < qty and cname not in needed_crops:
                        needed_crops.append(cname)
            for j in farm.get("farmJobs",[]):
                if j.get("current",0) < j.get("target",1):
                    cid = j.get("cropId","")
                    if cid and cid not in needed_crops:
                        needed_crops.append(cid)

            MIN_GOLD = 500
            for i in range(len(CROPS)):
                ci = (crop_idx + i) % len(CROPS)
                sid, rl, cost, grow, name = CROPS[ci]
                if lv < rl: continue
                have = inv.get(sid, 0)
                need = len(empty) - have
                if need <= 0: break
                while need > 0 and gold >= cost and (gold - cost >= MIN_GOLD or gold <= MIN_GOLD):
                    buy = min(need, max(1, (gold - MIN_GOLD) // cost), 99)
                    if buy <= 0: break
                    if (act("buySeed", seedId=sid, quantity=buy, selectedSeedId=sid) or {}).get("ok"):
                        gold -= cost * buy; inv[sid] = inv.get(sid, 0) + buy
                    else: break
                    need = len(empty) - inv.get(sid, 0)
                if inv.get(sid, 0) > 0:
                    break

            # Plant all empty plots
            empty = [t for t in tiles if t.get("ownerState")=="owned" and not t.get("cropId")]
            plant_queue = []
            for t in empty:
                pick = pick_seed(lv, gold, inv, needed_crops)
                if not pick: break
                seed, grow_min = pick
                if inv.get(seed, 0) <= 0: break
                plant_queue.append((t, seed))
                inv[seed] = inv.get(seed, 0) - 1

            def hoe_and_plant(args):
                tile, seed = args
                gs = tile.get("groundState","")
                if gs in ("grass","cleared","tilled"):
                    act("hoe", tileX=tile["x"], tileY=tile["y"])
                r = act("plant", tileX=tile["x"], tileY=tile["y"], seedId=seed, selectedSeedId=seed)
                return (r or {}).get("ok", False)

            if plant_queue:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results = list(pool.map(hoe_and_plant, plant_queue))
                p = sum(results)

        # ============================================================
        # HEAVY OPS: every 5 min (burn, orders, expand, etc.)
        # ============================================================
        now = time.time()
        if now - last_heavy >= HEAVY_INTERVAL:
            last_heavy = now

            # --- Pool auth + burn ---
            pool_api = api
            if not os.path.exists(POOL_HEX):
                wnum = int(WALLET_ID.replace("w",""))
                time.sleep(wnum * 2)
                fresh = fresh_auth()
                if fresh:
                    ftok, fws, fpid = fresh
                    with open(POOL_HEX,"w") as pf: pf.write(ftok.encode().hex()+"\n"+fws.encode().hex()+"\n"+str(int(time.time())))
                    h_pool = {"Content-Type":"application/json","Authorization":"Bearer "+ftok,"X-FarmTown-Wallet-Session":fws}
                    def pool_api(p, body=None): return api_call(p, body, h_pool)
            else:
                try:
                    plines = open(POOL_HEX).read().strip().split("\n")
                    ptok = bytes.fromhex(plines[0]).decode()
                    pws = bytes.fromhex(plines[1]).decode() if len(plines)>1 else ""
                    h_pool = {"Content-Type":"application/json","Authorization":"Bearer "+ptok,"X-FarmTown-Wallet-Session":pws}
                    def pool_api(p, body=None): return api_call(p, body, h_pool)
                except: pass

            pool_s = pool_api("/api/rewards/farmer-pool/status")
            if pool_s and pool_s.get("ok") and pool_s.get("pool",{}).get("status","missing") != "missing":
                pool_info = pool_s.get("pool",{})
                player_info = pool_s.get("player",{})
                est_payout = player_info.get("estimatedPayoutRaw","0")
                claim_power = player_info.get("contributedClaimPowerToday",0)
                my_power = claim_power
                burnable_levels = player_info.get("burnableLevels",0)
                total_power = pool_info.get("totalClaimPower", 0)
                pool_active = (pool_info.get("status") == "active"
                    and pool_info.get("enabled", False)
                    and total_power > 0)

                burn_levels = min(burnable_levels, max(0, lv - 10)) if burnable_levels > 0 and lv >= 35 and pool_active else 0
                if burn_levels > 0:
                    r = pool_api("/api/rewards/farmer-pool/claim", {"actionId":str(uuid.uuid4()),
                        "goldToBurn":0,"farmPointsToBurn":0,"levelsToBurn":burn_levels})
                    if r and r.get("ok"):
                        msgs.append(f"POOL!-{burn_levels}lv")
                        lv = max(10, lv - burn_levels)
                        with open("/tmp/farmtown-pool.log","a") as pf:
                            pf.write(f"[{time.strftime('%Y-%m-%d %H:%M')}] {WALLET_ID} | "
                                f"Power: {claim_power} | Est: {est_payout} | Pool: {pool_info.get('status','?')}\n")

            # --- Claim completed jobs ---
            for j in farm.get("farmJobs",[]):
                if j.get("current",0) >= j.get("target",1):
                    r = act("claimFarmJob", jobId=j["id"])
                    if r and r.get("ok"):
                        g=r.get('rewards',{}).get('gold',0); msgs.append(f"JOB+{g}g")
                    pfs = r.get("playerFarmState",{}) if r else {}
                    if pfs: gold = pfs.get("gold",gold)

            # --- Starter ---
            r = act("completeStarterTask")
            if r and r.get("ok"): msgs.append("STARTER")

            # --- Stars ---
            for fs in sd.get("fallingStars",[]):
                fid = fs.get("id","")
                if fid: act("collect_star", fallingStarId=fid)

            # --- Clear blockers ---
            owned = [t for t in tiles if t.get("ownerState")=="owned"]
            blocked_tiles = [t for t in tiles if t.get("ownerState")=="locked" and t.get("blocker","none")!="none"]
            if blocked_tiles:
                owned_set = set((t["x"],t["y"]) for t in owned)
                for bt in blocked_tiles:
                    bx, by = bt["x"], bt["y"]
                    is_adjacent = any((bx+dx,by+dy) in owned_set for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)])
                    if is_adjacent:
                        blocker = bt.get("blocker","")
                        tool = "pickaxe" if blocker in ("rock",) else "axe"
                        act("clear", tool=tool, tileX=bx, tileY=by)

            # --- Expand ---
            owned_count = len([t for t in tiles if t.get("ownerState")=="owned"])
            storage_tier_expand = farm.get("storageTier", 0)
            pc = plot_cost(owned_count)
            if storage_tier_expand >= 3 and gold > pc + 500 and owned_count < 250:
                while gold > pc + 500 and owned_count < 250:
                    owned_set = {(t["x"],t["y"]) for t in tiles if t.get("ownerState")=="owned"}
                    expand_tile = None
                    for t in tiles:
                        if t.get("ownerState") != "unowned": continue
                        x, y = t["x"], t["y"]
                        if (x-1,y) in owned_set or (x+1,y) in owned_set or (x,y-1) in owned_set or (x,y+1) in owned_set:
                            expand_tile = t; break
                    if not expand_tile: break
                    r = act("buyPlot", tileX=expand_tile["x"], tileY=expand_tile["y"])
                    if r and r.get("ok"):
                        gold -= pc; tiles = r.get("changedTiles", tiles) or tiles; owned_count += 1; pc = plot_cost(owned_count)
                    else: break

            # --- Storage upgrade ---
            STORAGE_TIERS = [
                ("small_storage_crate", 25000, 75),
                ("big_storage_crate", 100000, 125),
                ("farm_storage_chest", 500000, 200),
            ]
            storage_tier = farm.get("storageTier", 0)
            if storage_tier < len(STORAGE_TIERS):
                item_id, cost, cap = STORAGE_TIERS[storage_tier]
                if gold >= cost + 1000:
                    r = act("buyItem", itemId=item_id)
                    if r and r.get("ok"):
                        msgs.append(f"STORAGE->T{storage_tier+1}({cap})")
                        gold = r.get("playerFarmState", {}).get("gold", gold)

            # --- Complete orders ---
            s_ord = api("/api/game/snapshot")
            if s_ord and s_ord.get("snapshot"):
                farm_o = s_ord.get("snapshot",{}).get("playerFarmState",{})
                crops_o = dict(farm_o.get("cropInventory",{}))
                for o in farm_o.get("orders",[]):
                    reqs = o.get("requires",{})
                    if all(crops_o.get(c,0)>=q for c,q in reqs.items()):
                        if (act("completeOrder", orderId=o["id"]) or {}).get("ok"):
                            g=o.get('rewards',{}).get('gold',0); msgs.append(f"ORD+{g}g")
                        for c,q in reqs.items(): crops_o[c]=crops_o.get(c,0)-q

            # --- Crop rotation advance ---
            owned_count_now = len([t for t in tiles if t.get("ownerState")=="owned"])
            growing_or_ready = len([t for t in tiles if t.get("cropId") and t.get("groundState") in ("growing","seedling","ready")])
            empty_now = [t for t in tiles if t.get("ownerState")=="owned" and not t.get("cropId")]
            planted_count = owned_count_now - len(empty_now)
            if growing_or_ready == 0 and planted_count == 0 and owned_count_now > 0:
                idx = get_crop_idx()
                new_idx = (idx + 1) % len(CROPS)
                set_crop_idx(new_idx)
                set_planted_round(0)
                print(f"[{WALLET_ID}] Rotation: {CROPS[idx][4]} -> {CROPS[new_idx][4]}", flush=True)

        # ============================================================
        # REPORT + STATUS JSON (every cycle)
        # ============================================================
        elapsed = int(time.time()-t0)
        planted_now = sum(1 for t in tiles if t.get("cropId"))
        ready_now = sum(1 for t in tiles if t.get("cropId") and t.get("groundState")=="ready")
        growing_now = sum(1 for t in tiles if t.get("cropId") and t.get("groundState") in ("growing","seedling"))
        owned_count = len([t for t in tiles if t.get("ownerState")=="owned"])
        storage_tier = farm.get("storageTier", 0)
        inv_cap = farm.get("inventoryCapacity", 0)
        pc_now = plot_cost(owned_count)

        status = f"Lv{lv}|G:{gold}|FP:{fp}|P:{planted_now}({ready_now}r/{growing_now}g)|{owned_count}plots"
        print(f"[{time.strftime('%H:%M')}] {status} | H:{hcnt}|P:{p}|DC:{dc} | {elapsed}s {'|'.join(msgs)}", flush=True)

        # Write status JSON
        try:
            os.makedirs("/tmp/farmtown-status", exist_ok=True)
            status_data = {
                "wallet": WALLET_ID, "level": lv, "gold": gold, "fp": fp,
                "storage_tier": storage_tier, "inv_cap": inv_cap,
                "plots": owned_count, "planted": planted_now,
                "ready": ready_now, "growing": growing_now,
                "power": my_power, "plot_cost": pc_now,
                "crop_idx": get_crop_idx(), "ts": int(time.time())
            }
            with open(f"/tmp/farmtown-status/{WALLET_ID}.json", "w") as jf:
                json.dump(status_data, jf)
        except: pass

        # Metrics report every 30 min
        if time.time() - last_metrics > 1800:
            mr = metrics.report()
            if mr: print(mr, flush=True)
            last_metrics = time.time()

    # Final metrics on shutdown
    mr = metrics.report()
    if mr: print(mr, flush=True)
    print("Bot stopped.", flush=True)


if __name__=="__main__":
    main()
