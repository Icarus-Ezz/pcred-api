from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import json, os, time, threading
import hashlib, hmac, random, string

app = Flask(__name__)
CORS(app)

# ================= CONFIG =================
DATA_DIR = "data"
CODES_FILE = os.path.join(DATA_DIR, "codes.json")
TIEN_FILE = os.path.join(DATA_DIR, "tien.json")

API_SECRET_SALT = "PCRED_PRIVATE_SALT_2025"
RAW_API_KEYS = ["Sikibidisigama"]

RATE_LIMIT = 15
RATE_TIME = 60
TIME_FMT = "%Y-%m-%d %H:%M:%S"

rate_cache = {}
file_lock = threading.Lock()

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

# ================= UTIL =================
def now():
    return datetime.now()

def generate_code():
    src = string.ascii_uppercase + string.digits
    return "PC-" + "-".join("".join(random.choices(src, k=5)) for _ in range(3))

def hash_api_key(key):
    return hmac.new(API_SECRET_SALT.encode(), key.encode(), hashlib.sha256).hexdigest()

API_KEYS_HASHED = {hash_api_key(k) for k in RAW_API_KEYS}

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def clean_expired_codes(codes):
    t = now()
    for code in list(codes.keys()):
        try:
            expire_t = datetime.strptime(codes[code]["expire_at"], TIME_FMT)
            if t >= expire_t:
                del codes[code]
        except:
            del codes[code]

# ================= SECURITY =================
@app.before_request
def security_check():
    if request.method == "OPTIONS": return
    
    # Rate Limit
    ip = request.remote_addr
    now_t = time.time()
    history = [t for t in rate_cache.get(ip, []) if now_t - t < RATE_TIME]
    if len(history) >= RATE_LIMIT:
        return jsonify({"status": "error", "msg": "Too many requests"}), 429
    history.append(now_t)
    rate_cache[ip] = history

    # API Key Check (Chỉ cho các route đặc biệt)
    protected_paths = ["/create_code", "/generate_code", "/redeem"]
    if request.path in protected_paths:
        raw = request.headers.get("X-API-KEY")
        if not raw or hash_api_key(raw) not in API_KEYS_HASHED:
            return jsonify({"status": "error", "msg": "Invalid API KEY"}), 401

# ================= ROUTES =================
@app.route("/")
def home():
    return "PCRED API IS LIVE"

@app.route("/check_key", methods=["POST"])
def check_key():
    data = request.get_json(silent=True)
    if not data or "code" not in data:
        return jsonify({"status": "invalid"})

    code = data["code"].strip()
    with file_lock:
        codes = load_json(CODES_FILE)
        clean_expired_codes(codes)
        info = codes.get(code)
        
        if not info or info["state"] != "unused":
            return jsonify({"status": "invalid"})
            
    return jsonify({"status": "ok", "reward": info["reward"]})

@app.route("/generate_code", methods=["POST"])
def generate_code_api():
    data = request.get_json(silent=True)
    discord_id = str(data.get("discord_id", ""))
    reward = int(data.get("reward", 1000))

    if not discord_id:
        return jsonify({"status": "error", "msg": "Missing discord_id"})

    with file_lock:
        codes = load_json(CODES_FILE)
        clean_expired_codes(codes)
        code = generate_code()
        created = now()
        codes[code] = {
            "discord_id": discord_id,
            "reward": reward,
            "state": "unused",
            "created_at": created.strftime(TIME_FMT),
            "expire_at": (created + timedelta(hours=24)).strftime(TIME_FMT),
            "used_at": None
        }
        save_json(CODES_FILE, codes)

    return jsonify({"status": "ok", "code": code, "reward": reward})

@app.route("/redeem", methods=["POST"])
def redeem():
    data = request.get_json(silent=True)
    code = data.get("code")
    discord_id = str(data.get("discord_id"))

    with file_lock:
        codes = load_json(CODES_FILE)
        tien = load_json(TIEN_FILE)
        info = codes.get(code)

        if not info or info["state"] != "unused" or info["discord_id"] != discord_id:
            return jsonify({"status": "error", "msg": "Code không hợp lệ hoặc đã dùng"})

        tien[discord_id] = tien.get(discord_id, 0) + info["reward"]
        info["state"] = "used"
        info["used_at"] = now().strftime(TIME_FMT)

        save_json(CODES_FILE, codes)
        save_json(TIEN_FILE, tien)

    return jsonify({"status": "success", "balance": tien[discord_id]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
