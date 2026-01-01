import os
import time
import hmac
import random
import string
import hashlib
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient

app = Flask(__name__)
CORS(app)

# ================= CONFIG & DATABASE =================
# Lấy URI từ Environment Variable trên Render (để bảo mật)
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://ngongochungphat_db_user:pPY7Hi7fxsyuHCDB@phatcrystal.tfss1qn.mongodb.net/?appName=PhatCrystal")
client = MongoClient(MONGO_URI)
db = client["pcred_db"]

# Collections thay thế cho các file .json
codes_col = db["codes"]
tien_col = db["tien"]

API_SECRET_SALT = "PCRED_PRIVATE_SALT_2025"
RAW_API_KEYS = ["Sikibidisigama"]
TIME_FMT = "%Y-%m-%d %H:%M:%S"

rate_cache = {}

# ================= UTILS =================
def now():
    return datetime.now()

def generate_code():
    src = string.ascii_uppercase + string.digits
    return "PC-" + "-".join("".join(random.choices(src, k=5)) for _ in range(3))

def hash_api_key(key):
    return hmac.new(API_SECRET_SALT.encode(), key.encode(), hashlib.sha256).hexdigest()

API_KEYS_HASHED = {hash_api_key(k) for k in RAW_API_KEYS}

def clean_expired_codes():
    """Xóa các code hết hạn trong database"""
    t_now = now().strftime(TIME_FMT)
    codes_col.delete_many({"expire_at": {"$lt": t_now}, "state": "unused"})

# ================= SECURITY =================
@app.before_request
def security_check():
    if request.method == "OPTIONS": return
    
    # Rate Limit (15 req / 60s)
    ip = request.remote_addr
    now_t = time.time()
    history = [t for t in rate_cache.get(ip, []) if now_t - t < 60]
    if len(history) >= 15:
        return jsonify({"status": "error", "msg": "Too many requests"}), 429
    history.append(now_t)
    rate_cache[ip] = history

    # API Key Check cho các route quản trị
    protected_paths = ["/create_code", "/generate_code"]
    if request.path in protected_paths:
        raw = request.headers.get("X-API-KEY")
        if not raw or hash_api_key(raw) not in API_KEYS_HASHED:
            return jsonify({"status": "error", "msg": "Invalid API KEY"}), 401

# ================= ROUTES =================
@app.route("/")
def home():
    return "PCRED API MONGODB LIVE - PYTHON 3.12"

@app.route("/check_key", methods=["POST"])
def check_key():
    clean_expired_codes()
    data = request.get_json(silent=True)
    if not data or "code" not in data:
        return jsonify({"status": "invalid"})

    code = data["code"].strip()
    # Tìm code trong MongoDB
    info = codes_col.find_one({"code": code, "state": "unused"})
    
    if not info:
        return jsonify({"status": "invalid"})
            
    return jsonify({"status": "ok", "reward": info["reward"]})
@app.route("/create_code", methods=["POST"])
def create_code():
    raw = request.headers.get("X-API-KEY")
    if not raw or hash_api_key(raw) not in API_KEYS_HASHED:
        return jsonify({"status": "error", "msg": "Invalid API KEY"}), 401
        
    data = request.get_json(silent=True)
    code = data.get("code")
    discord_id = str(data.get("discord_id"))
    reward = int(data.get("reward", 350)) # Reward mặc định

    if not code or not discord_id:
        return jsonify({"status": "error", "msg": "Missing data"})

    # Lưu vào DB
    new_doc = {
        "code": code,
        "discord_id": discord_id,
        "reward": reward,
        "state": "unused",
        "created_at": now().strftime(TIME_FMT),
        "expire_at": (now() + timedelta(hours=24)).strftime(TIME_FMT),
        "used_at": None
    }
    codes_col.insert_one(new_doc)
    return jsonify({"status": "ok"})
@app.route("/generate_code", methods=["POST"])
def generate_code_api():
    data = request.get_json(silent=True)
    discord_id = str(data.get("discord_id", ""))
    reward = int(data.get("reward", 1000))

    if not discord_id:
        return jsonify({"status": "error", "msg": "Missing discord_id"})

    code = generate_code()
    created = now()
    
    new_doc = {
        "code": code,
        "discord_id": discord_id,
        "reward": reward,
        "state": "unused",
        "created_at": created.strftime(TIME_FMT),
        "expire_at": (created + timedelta(hours=24)).strftime(TIME_FMT),
        "used_at": None
    }
    codes_col.insert_one(new_doc)

    return jsonify({"status": "ok", "code": code, "reward": reward})

@app.route("/redeem", methods=["POST"])
def redeem():
    data = request.get_json(silent=True)
    code = data.get("code")
    discord_id = str(data.get("discord_id"))

    # Tìm code và kiểm tra sở hữu
    info = codes_col.find_one({"code": code, "state": "unused", "discord_id": discord_id})

    if not info:
        return jsonify({"status": "error", "msg": "Code không hợp lệ hoặc đã dùng"})

    # Cập nhật tiền (Nếu chưa có thì tạo mới bằng upsert)
    tien_col.update_one(
        {"discord_id": discord_id},
        {"$inc": {"balance": info["reward"]}},
        upsert=True
    )

    # Đánh dấu code đã dùng
    codes_col.update_one(
        {"code": code},
        {"$set": {"state": "used", "used_at": now().strftime(TIME_FMT)}}
    )

    updated_user = tien_col.find_one({"discord_id": discord_id})
    return jsonify({"status": "success", "balance": updated_user["balance"]})

if __name__ == "__main__":
    # Render tự cấp PORT, nếu chạy local dùng 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
