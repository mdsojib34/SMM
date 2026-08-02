# -*- coding: utf-8 -*-
"""
=====================================================================
 PROFESSIONAL TELEGRAM SMM PANEL BOT  (v3 - FULLY DYNAMIC EDITION)
=====================================================================
 Single file. SQLite. Pyrogram (latest / kurigram compatible).

 EVERYTHING is editable from the Admin Panel:
   texts, buttons, menus, categories, services, payment methods,
   provider APIs, coupons, referral rules, settings, maintenance.

 INSTALL
   pip install pyrogram tgcrypto requests
 RUN
   python smm_bot_v3.py

 CONFIG -> see "STEP 1 CONFIGURATION" block below (lines ~60-75).
 Everything else is managed inside the bot: /admin
=====================================================================
"""

import os
import re
import io
import json
import time
import random
import string
import sqlite3
import asyncio
import logging
import hashlib
import threading
import traceback
from datetime import datetime, timedelta, timezone

import requests
from pyrogram import Client, filters, enums
from pyrogram.errors import RPCError, FloodWait
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# =====================================================================
# STEP 1 CONFIGURATION  (the ONLY place you must edit)
# =====================================================================
API_ID = int(os.getenv("36497386", "0"))                 # <-- my.telegram.org  API_ID
API_HASH = os.getenv("bf09e9a32f89d28087b44bcdb043239c", "")                   # <-- my.telegram.org  API_HASH
BOT_TOKEN = os.getenv("8995940738:AAEnVYIcC72TCi8aH620d9MH2DQIDAGKCMw", "")                 # <-- @BotFather token
OWNER_IDS = [int(x) for x in os.getenv("ADMINS", "0").replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()]
DB_FILE = os.getenv("DB_FILE", "smm_panel.db")         # SQLite database file
LOG_FILE = os.getenv("LOG_FILE", "smm_bot.log")
SESSION_NAME = os.getenv("SESSION_NAME", "smm_panel_bot")
# =====================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
log = logging.getLogger("smm")


def now_ts() -> int:
    return int(time.time())


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def rid(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


# =====================================================================
# DATABASE LAYER (thread safe, parameterised -> SQL-injection proof)
# =====================================================================
_lock = threading.RLock()
_conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("PRAGMA foreign_keys=ON")


def q(sql: str, args=()) -> list:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql: str, args=()):
    r = q(sql, args)
    return r[0] if r else None


def run(sql: str, args=()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def runmany(sql: str, seq) -> None:
    with _lock:
        _conn.executemany(sql, seq)
        _conn.commit()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, lang TEXT DEFAULT 'en',
    balance REAL DEFAULT 0, spent REAL DEFAULT 0, ref_by INTEGER, ref_earned REAL DEFAULT 0,
    banned INTEGER DEFAULT 0, joined INTEGER, last_seen INTEGER, notify INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS admins(
    user_id INTEGER PRIMARY KEY, role TEXT DEFAULT 'admin', perms TEXT DEFAULT 'all', added INTEGER);

CREATE TABLE IF NOT EXISTS providers(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, url TEXT, api_key TEXT,
    active INTEGER DEFAULT 1, priority INTEGER DEFAULT 100, is_default INTEGER DEFAULT 0,
    balance REAL DEFAULT 0, currency TEXT DEFAULT '', last_sync INTEGER DEFAULT 0, added INTEGER);

CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, icon TEXT DEFAULT '',
    sort INTEGER DEFAULT 100, hidden INTEGER DEFAULT 0, keywords TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS services(
    id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id INTEGER, service_id TEXT,
    name TEXT, category_id INTEGER, raw_category TEXT, rate REAL DEFAULT 0, price REAL DEFAULT 0,
    min_qty INTEGER DEFAULT 1, max_qty INTEGER DEFAULT 100000, type TEXT DEFAULT '',
    refill INTEGER DEFAULT 0, cancel INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0,
    custom_price REAL DEFAULT 0, updated INTEGER,
    UNIQUE(provider_id, service_id));

CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, service_row INTEGER, provider_id INTEGER,
    provider_order TEXT, service_name TEXT, link TEXT, quantity INTEGER, charge REAL,
    status TEXT DEFAULT 'pending', start_count INTEGER DEFAULT 0, remains INTEGER DEFAULT 0,
    refunded REAL DEFAULT 0, created INTEGER, updated INTEGER, note TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS payment_methods(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, icon TEXT DEFAULT '',
    address TEXT DEFAULT '', instructions TEXT DEFAULT '', min_amount REAL DEFAULT 1,
    max_amount REAL DEFAULT 1000000, rate REAL DEFAULT 1, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 100);

CREATE TABLE IF NOT EXISTS deposits(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, method_id INTEGER, method_name TEXT,
    amount REAL, credited REAL DEFAULT 0, txid TEXT, status TEXT DEFAULT 'pending',
    coupon TEXT DEFAULT '', created INTEGER, handled INTEGER DEFAULT 0, admin_id INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS transactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, amount REAL,
    balance_after REAL, detail TEXT, created INTEGER);

CREATE TABLE IF NOT EXISTS coupons(
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, percent REAL DEFAULT 0,
    max_uses INTEGER DEFAULT 1, used INTEGER DEFAULT 0, min_deposit REAL DEFAULT 0,
    expires INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created INTEGER);

CREATE TABLE IF NOT EXISTS coupon_uses(
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, user_id INTEGER, amount REAL, created INTEGER);

CREATE TABLE IF NOT EXISTS tickets(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, subject TEXT,
    status TEXT DEFAULT 'open', created INTEGER, updated INTEGER);

CREATE TABLE IF NOT EXISTS ticket_messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, sender TEXT, body TEXT, created INTEGER);

CREATE TABLE IF NOT EXISTS texts(
    key TEXT, lang TEXT, value TEXT, PRIMARY KEY(key, lang));

CREATE TABLE IF NOT EXISTS buttons(
    key TEXT PRIMARY KEY, label TEXT, emoji TEXT DEFAULT '', sort INTEGER DEFAULT 100,
    row INTEGER DEFAULT 0, visible INTEGER DEFAULT 1, enabled INTEGER DEFAULT 1, target TEXT);

CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS force_channels(
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, title TEXT DEFAULT '',
    invite_link TEXT DEFAULT '', active INTEGER DEFAULT 1, sort INTEGER DEFAULT 100, added INTEGER);

CREATE TABLE IF NOT EXISTS logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT, actor INTEGER, action TEXT, detail TEXT, created INTEGER);
"""


def init_db() -> None:
    with _lock:
        _conn.executescript(SCHEMA)
        _conn.commit()
    for oid in OWNER_IDS:
        if oid:
            run("INSERT OR IGNORE INTO admins(user_id, role, perms, added) VALUES(?,?,?,?)",
                (oid, "owner", "all", now_ts()))
    seed_settings()
    seed_texts()
    seed_buttons()
    seed_categories()
    seed_payment_methods()
    log.info("Database ready -> %s", DB_FILE)


def audit(level: str, actor: int, action: str, detail: str = "") -> None:
    run("INSERT INTO logs(level, actor, action, detail, created) VALUES(?,?,?,?,?)",
        (level, actor or 0, action, str(detail)[:2000], now_ts()))
    if level in ("ERROR", "WARN"):
        log.warning("%s | %s | %s", action, actor, detail)


# =====================================================================
# SETTINGS (all dynamic, editable in Admin -> Settings)
# =====================================================================
DEFAULT_SETTINGS = {
    "bot_name": "SMM Panel Bot",
    "bot_username": "",
    "currency": "BDT",
    "currency_symbol": "৳",
    "usd_rate": "120",              # 1 USD (provider rate) -> local currency
    "profit_percent": "20",         # markup added on provider rate
    "min_order_amount": "1",
    "support_username": "",
    "force_join": "1",
    "maintenance": "0",
    "languages": "en,bn",
    "default_lang": "en",
    "ref_bonus": "5",               # fixed bonus on referral join
    "ref_commission": "5",          # % of referred user's deposit
    "ref_min_withdraw": "50",
    "ref_enabled": "1",
    "deposit_enabled": "1",
    "order_enabled": "1",
    "auto_refund": "1",
    "auto_refill": "0",
    "status_interval": "180",       # seconds between order status polls
    "sync_interval": "21600",       # seconds between service re-sync
    "flood_limit": "6",             # messages per 5 seconds
    "page_size": "8",
    "admin_log_chat": "0",
}


def seed_settings() -> None:
    for k, v in DEFAULT_SETTINGS.items():
        run("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))


def S(key: str, default: str = "") -> str:
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def SF(key: str, default: float = 0.0) -> float:
    try:
        return float(S(key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def SI(key: str, default: int = 0) -> int:
    return int(SF(key, default))


def SB(key: str, default: bool = False) -> bool:
    return S(key, "1" if default else "0") in ("1", "true", "True", "yes", "on")


def set_setting(key: str, value) -> None:
    run("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)))


def cur(amount) -> str:
    try:
        return f"{S('currency_symbol','')}{float(amount):,.2f}"
    except (TypeError, ValueError):
        return f"{S('currency_symbol','')}0.00"


# =====================================================================
# DYNAMIC TEXTS  (every message lives in DB -> Admin -> Customization)
# =====================================================================
DEFAULT_TEXTS = {
    "en": {
        "welcome": "👋 <b>Welcome {name}!</b>\n\nYou are using <b>{bot}</b> — the fastest SMM panel on Telegram.\n\n💰 Balance: <b>{balance}</b>\n🆔 ID: <code>{id}</code>",
        "start": "🏠 <b>Main Menu</b>\n\n💰 Balance: <b>{balance}</b>\n📦 Orders: <b>{orders}</b>\n\nChoose an option below.",
        "footer": "\n\n<i>Powered by {bot}</i>",
        "account": "👤 <b>My Account</b>\n\n🆔 ID: <code>{id}</code>\n👤 Name: {name}\n🔗 Username: @{username}\n🌐 Language: {lang}\n💰 Balance: <b>{balance}</b>\n💸 Total spent: <b>{spent}</b>\n📦 Orders: <b>{orders}</b>\n👥 Referrals: <b>{refs}</b>\n📅 Joined: {joined}",
        "balance": "💰 <b>Wallet</b>\n\nAvailable balance: <b>{balance}</b>\nTotal spent: <b>{spent}</b>\nReferral earnings: <b>{ref_earned}</b>",
        "choose_category": "🛒 <b>New Order</b>\n\nSelect a category:",
        "choose_service": "📋 <b>{category}</b>\n\nSelect a service:",
        "service_info": "🧾 <b>{name}</b>\n\n💵 Price: <b>{price}</b> / 1000\n📉 Min: <b>{min}</b>\n📈 Max: <b>{max}</b>\n{extra}\n\nSend the <b>link</b> for this order:",
        "ask_quantity": "🔢 Now send the <b>quantity</b>\n\nAllowed: <b>{min}</b> – <b>{max}</b>",
        "order_summary": "🧾 <b>Order Summary</b>\n\n📋 Service: {name}\n🔗 Link: {link}\n🔢 Quantity: <b>{qty}</b>\n💵 Charge: <b>{charge}</b>\n💰 Balance: <b>{balance}</b>\n\nConfirm your order?",
        "order_success": "✅ <b>Order Placed!</b>\n\n🆔 Order: <code>#{id}</code>\n📋 {name}\n🔢 {qty}\n💵 {charge}\n\nUse 📦 My Orders to track it.",
        "order_failed": "❌ <b>Order Failed</b>\n\n{reason}\n\nYour balance was not charged (or was refunded).",
        "insufficient": "⚠️ <b>Insufficient balance</b>\n\nRequired: <b>{need}</b>\nAvailable: <b>{have}</b>\n\nPlease add funds first.",
        "deposit": "💳 <b>Add Funds</b>\n\nSelect a payment method:",
        "deposit_method": "💳 <b>{name}</b>\n\n📮 Account / Address:\n<code>{address}</code>\n\n📖 Instructions:\n{instructions}\n\nMin: <b>{min}</b> | Max: <b>{max}</b>\n\nSend the <b>amount</b> you paid:",
        "deposit_txid": "🧾 Now send the <b>Transaction ID / sender number / proof</b>:",
        "deposit_submitted": "⏳ <b>Deposit submitted</b>\n\n🆔 Request: <code>#{id}</code>\n💵 Amount: <b>{amount}</b>\n\nAdmins will review it shortly.",
        "deposit_approved": "✅ <b>Deposit approved</b>\n\n🆔 <code>#{id}</code>\n💵 Credited: <b>{amount}</b>\n💰 New balance: <b>{balance}</b>",
        "deposit_rejected": "❌ <b>Deposit rejected</b>\n\n🆔 <code>#{id}</code>\n📝 Reason: {reason}",
        "history": "📜 <b>Transaction History</b>\n\n{list}",
        "orders": "📦 <b>My Orders</b>\n\n{list}",
        "order_detail": "📦 <b>Order #{id}</b>\n\n📋 {name}\n🔗 {link}\n🔢 Quantity: {qty}\n📊 Status: <b>{status}</b>\n🚀 Start count: {start}\n⏳ Remains: {remains}\n💵 Charge: {charge}\n💸 Refunded: {refunded}\n📅 {created}",
        "referral": "🎁 <b>Referral Program</b>\n\n🔗 Your link:\n{link}\n\n👥 Referrals: <b>{count}</b>\n💰 Earned: <b>{earned}</b>\n\n🎯 Join bonus: <b>{bonus}</b>\n📈 Deposit commission: <b>{commission}%</b>\n🏧 Min withdraw: <b>{min_withdraw}</b>",
        "referral_joined": "🎉 New referral! <b>{name}</b> joined using your link.\n💰 Bonus: <b>{bonus}</b>",
        "referral_commission": "💰 Referral commission: <b>{amount}</b> from {name}'s deposit.",
        "coupon": "🎟 <b>Coupon</b>\n\nSend your coupon code to apply it to your next deposit.",
        "coupon_ok": "✅ Coupon <code>{code}</code> applied — <b>{percent}%</b> extra on your next deposit.",
        "coupon_bad": "❌ Invalid, expired or already used coupon.",
        "ticket": "📞 <b>Support</b>\n\nSend your message and our team will reply here.",
        "ticket_created": "✅ Ticket <code>#{id}</code> created. We will reply soon.",
        "ticket_reply": "📩 <b>Support reply — Ticket #{id}</b>\n\n{body}",
        "ticket_closed": "🔒 Ticket <code>#{id}</code> closed.",
        "language": "🌐 <b>Language</b>\n\nSelect your language:",
        "language_set": "✅ Language updated.",
        "about": "ℹ️ <b>About</b>\n\n{bot} delivers premium social media marketing services with instant automated delivery.",
        "rules": "📋 <b>Rules</b>\n\n1. One order per link at a time.\n2. Keep your account public while an order runs.\n3. No refunds after completion.",
        "terms": "📜 <b>Terms of Service</b>\n\nBy using this bot you accept that all services are delivered as-is by third-party providers.",
        "privacy": "🔐 <b>Privacy Policy</b>\n\nWe store only your Telegram ID, username and order data required to operate the service.",
        "maintenance": "🛠 <b>Maintenance</b>\n\nThe bot is temporarily unavailable. Please try again later.",
        "force_join": "🔒 <b>Join required</b>\n\nTo use this bot you must join the channel(s) below:\n{channels}\n\nAfter joining, press <b>✅ Verify Join</b>.",
        "force_join_ok": "✅ Verified! Welcome.",
        "force_join_fail": "❌ You have not joined all required channels yet.",
        "banned": "🚫 Your account has been suspended. Contact support.",
        "flood": "🐢 Slow down please.",
        "error": "⚠️ Something went wrong. Please try again.",
        "cancelled": "❌ Cancelled.",
        "invalid_input": "⚠️ Invalid input. Please try again.",
        "no_services": "📭 No services available in this category yet.",
        "notify_status": "🔔 <b>Order #{id}</b> status: <b>{status}</b>",
        "notify_refund": "💸 <b>Refund</b>\n\nOrder <code>#{id}</code> — <b>{amount}</b> returned to your wallet.",
        "broadcast_header": "📢 <b>Announcement</b>\n\n",
    },
    "bn": {
        "welcome": "👋 <b>স্বাগতম {name}!</b>\n\nআপনি ব্যবহার করছেন <b>{bot}</b>।\n\n💰 ব্যালেন্স: <b>{balance}</b>\n🆔 আইডি: <code>{id}</code>",
        "start": "🏠 <b>মেইন মেনু</b>\n\n💰 ব্যালেন্স: <b>{balance}</b>\n📦 অর্ডার: <b>{orders}</b>\n\nনিচ থেকে অপশন বাছুন।",
        "choose_category": "🛒 <b>নতুন অর্ডার</b>\n\nক্যাটাগরি বাছুন:",
        "choose_service": "📋 <b>{category}</b>\n\nসার্ভিস বাছুন:",
        "insufficient": "⚠️ <b>ব্যালেন্স অপর্যাপ্ত</b>\n\nপ্রয়োজন: <b>{need}</b>\nআছে: <b>{have}</b>",
        "maintenance": "🛠 বট আপাতত বন্ধ আছে, পরে চেষ্টা করুন।",
        "banned": "🚫 আপনার অ্যাকাউন্ট বন্ধ করা হয়েছে।",
        "cancelled": "❌ বাতিল করা হয়েছে।",
        "force_join": "🔒 <b>জয়েন করা আবশ্যক</b>\n\nবট ব্যবহার করতে নিচের চ্যানেলগুলোতে জয়েন করুন:\n{channels}\n\nজয়েন করে <b>✅ Verify Join</b> চাপুন।",
        "force_join_ok": "✅ ভেরিফাই সম্পন্ন!",
        "force_join_fail": "❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি।",
    },
}


def seed_texts() -> None:
    for lang, pack in DEFAULT_TEXTS.items():
        for k, v in pack.items():
            run("INSERT OR IGNORE INTO texts(key, lang, value) VALUES(?,?,?)", (k, lang, v))


def T(key: str, lang: str = None, **kw) -> str:
    lang = lang or S("default_lang", "en")
    r = one("SELECT value FROM texts WHERE key=? AND lang=?", (key, lang))
    if not r:
        r = one("SELECT value FROM texts WHERE key=? AND lang='en'", (key,))
    if not r:
        r = one("SELECT value FROM texts WHERE key=? LIMIT 1", (key,))
    txt = r["value"] if r else key
    kw.setdefault("bot", S("bot_name", "SMM Panel"))
    try:
        return txt.format(**kw)
    except (KeyError, IndexError, ValueError):
        return txt


# =====================================================================
# DYNAMIC BUTTONS / MENU CUSTOMIZER
# =====================================================================
DEFAULT_BUTTONS = [
    # key,           label,               emoji, sort, row, target
    ("new_order",    "New Order",         "🛒", 10, 0, "cat:list:0"),
    ("orders",       "My Orders",         "📦", 20, 0, "orders:0"),
    ("wallet",       "Wallet",            "💰", 30, 1, "wallet"),
    ("deposit",      "Add Funds",         "💳", 40, 1, "dep:list"),
    ("history",      "History",           "📜", 50, 2, "history:0"),
    ("account",      "My Account",        "👤", 60, 2, "account"),
    ("referral",     "Referral",          "🎁", 70, 3, "ref"),
    ("coupon",       "Coupon",            "🎟", 80, 3, "coupon"),
    ("support",      "Support",           "📞", 90, 4, "ticket"),
    ("language",     "Language",          "🌐", 100, 4, "lang"),
    ("about",        "About",             "ℹ️", 110, 5, "info:about"),
    ("rules",        "Rules",             "📋", 120, 5, "info:rules"),
]


def seed_buttons() -> None:
    for key, label, emoji, sort, row, target in DEFAULT_BUTTONS:
        run("""INSERT OR IGNORE INTO buttons(key,label,emoji,sort,row,visible,enabled,target)
               VALUES(?,?,?,?,?,1,1,?)""", (key, label, emoji, sort, row, target))


def btn_label(key: str, fallback: str = "") -> str:
    b = one("SELECT label, emoji FROM buttons WHERE key=?", (key,))
    if not b:
        return fallback or key
    return (f"{b['emoji']} {b['label']}").strip()


def main_menu(uid: int) -> InlineKeyboardMarkup:
    rows = {}
    for b in q("SELECT * FROM buttons WHERE visible=1 ORDER BY row ASC, sort ASC"):
        target = b["target"] if b["enabled"] else "disabled"
        rows.setdefault(b["row"], []).append(
            InlineKeyboardButton((f"{b['emoji']} {b['label']}").strip(), callback_data=target))
    kb = [rows[k] for k in sorted(rows)]
    if is_admin(uid):
        kb.append([InlineKeyboardButton("👑 Admin Panel", callback_data="adm:home")])
    return InlineKeyboardMarkup(kb or [[InlineKeyboardButton("🏠 Home", callback_data="home")]])


def back_kb(target: str = "home", label: str = "🔙 Back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])


def pager(prefix: str, page: int, total: int, per: int, extra_back: str = "home") -> list:
    row, pages = [], max(1, (total + per - 1) // per)
    if page > 0:
        row.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}{page-1}"))
    row.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page + 1 < pages:
        row.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}{page+1}"))
    out = [row] if pages > 1 else []
    out.append([InlineKeyboardButton("🔙 Back", callback_data=extra_back)])
    return out


# =====================================================================
# DEFAULT CATEGORIES  (auto-mapped from provider categories, editable)
# =====================================================================
DEFAULT_CATEGORIES = [
    ("Instagram", "📸", 10, "instagram,insta,ig,reel"),
    ("YouTube", "▶️", 20, "youtube,yt,shorts"),
    ("TikTok", "🎵", 30, "tiktok,tt,douyin"),
    ("Facebook", "📘", 40, "facebook,fb,messenger"),
    ("Telegram", "✈️", 50, "telegram,tg"),
    ("Twitter (X)", "❌", 60, "twitter,x.com,tweet"),
    ("Spotify", "🎧", 70, "spotify"),
    ("Website Traffic", "🌐", 80, "traffic,website,seo,visitor"),
    ("Others", "📦", 999, ""),
]


def seed_categories() -> None:
    for name, icon, sort, kws in DEFAULT_CATEGORIES:
        run("INSERT OR IGNORE INTO categories(name, icon, sort, hidden, keywords) VALUES(?,?,?,0,?)",
            (name, icon, sort, kws))


def match_category(raw: str) -> int:
    raw_l = (raw or "").lower()
    best = None
    for c in q("SELECT * FROM categories ORDER BY sort ASC"):
        for kw in [k.strip().lower() for k in (c["keywords"] or "").split(",") if k.strip()]:
            if kw in raw_l:
                return c["id"]
        if c["name"].lower() == "others":
            best = c["id"]
    return best or run("INSERT OR IGNORE INTO categories(name, icon, sort) VALUES('Others','📦',999)")


def seed_payment_methods() -> None:
    if one("SELECT id FROM payment_methods LIMIT 1"):
        return
    defaults = [
        ("bKash", "📱", "01XXXXXXXXX", "Send money to the number above, then submit the TrxID.", 50, 50000, 1, 10),
        ("Nagad", "📲", "01XXXXXXXXX", "Send money to the number above, then submit the TrxID.", 50, 50000, 1, 20),
        ("Rocket", "🚀", "01XXXXXXXXX", "Send money to the number above, then submit the TrxID.", 50, 50000, 1, 30),
        ("Binance Pay", "🟡", "Binance ID: 000000", "Pay via Binance Pay and submit the transfer ID.", 1, 100000, 1, 40),
        ("USDT (TRC20)", "💵", "TXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "Send USDT (TRC20) and submit the TX hash.", 1, 100000, 120, 50),
        ("Manual Deposit", "🧾", "Contact admin", "Contact support to arrange a manual deposit.", 1, 100000, 1, 60),
    ]
    for n, i, a, ins, mn, mx, rate, sort in defaults:
        run("""INSERT INTO payment_methods(name,icon,address,instructions,min_amount,max_amount,rate,active,sort)
               VALUES(?,?,?,?,?,?,?,1,?)""", (n, i, a, ins, mn, mx, rate, sort))


# =====================================================================
# USERS / SECURITY (auth, roles, flood, validation)
# =====================================================================
def is_admin(uid: int) -> bool:
    return bool(uid) and (uid in OWNER_IDS or one("SELECT user_id FROM admins WHERE user_id=?", (uid,)) is not None)


def is_owner(uid: int) -> bool:
    if uid in OWNER_IDS:
        return True
    a = one("SELECT role FROM admins WHERE user_id=?", (uid,))
    return bool(a and a["role"] == "owner")


def get_user(uid: int) -> dict:
    u = one("SELECT * FROM users WHERE user_id=?", (uid,))
    return u or {}


def ensure_user(m) -> dict:
    uid = m.from_user.id
    u = get_user(uid)
    if not u:
        run("""INSERT INTO users(user_id, username, first_name, lang, joined, last_seen)
               VALUES(?,?,?,?,?,?)""",
            (uid, m.from_user.username or "", m.from_user.first_name or "", S("default_lang", "en"),
             now_ts(), now_ts()))
        audit("INFO", uid, "user_register", m.from_user.username or "")
        u = get_user(uid)
    else:
        run("UPDATE users SET username=?, first_name=?, last_seen=? WHERE user_id=?",
            (m.from_user.username or "", m.from_user.first_name or "", now_ts(), uid))
    return u


def ulang(uid: int) -> str:
    u = get_user(uid)
    return (u.get("lang") or S("default_lang", "en")) if u else S("default_lang", "en")


def add_balance(uid: int, amount: float, kind: str, detail: str = "") -> float:
    run("UPDATE users SET balance = ROUND(balance + ?, 4) WHERE user_id=?", (float(amount), uid))
    bal = float(get_user(uid).get("balance", 0))
    run("INSERT INTO transactions(user_id, kind, amount, balance_after, detail, created) VALUES(?,?,?,?,?,?)",
        (uid, kind, float(amount), bal, detail, now_ts()))
    return bal


_flood = {}


def flood_ok(uid: int) -> bool:
    limit = max(1, SI("flood_limit", 6))
    bucket = _flood.setdefault(uid, [])
    t = time.time()
    bucket[:] = [x for x in bucket if t - x < 5]
    bucket.append(t)
    return len(bucket) <= limit


URL_RE = re.compile(r"^https?://[\w\-\.]+\.[a-z]{2,}(/\S*)?$", re.I)


def valid_link(text: str) -> bool:
    return bool(text) and len(text) <= 512 and bool(URL_RE.match(text.strip()))


def valid_amount(text: str, lo: float = 0.0001, hi: float = 10 ** 9):
    try:
        v = float(str(text).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def clean(text: str, limit: int = 400) -> str:
    text = (text or "").replace("<", "&lt;").replace(">", "&gt;")
    return text[:limit]


# =====================================================================
# MULTI PROVIDER API CLIENT  (standard SMM /api/v2 protocol)
# =====================================================================
class ProviderAPI:
    def __init__(self, row: dict):
        self.id = row["id"]
        self.name = row["name"]
        self.url = row["url"].strip()
        self.key = row["api_key"].strip()

    def _post(self, payload: dict, timeout: int = 40):
        payload = dict(payload)
        payload["key"] = self.key
        r = requests.post(self.url, data=payload, timeout=timeout,
                          headers={"User-Agent": "SMMPanelBot/3.0"})
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON from provider: {r.text[:200]}")

    def services(self):
        return self._post({"action": "services"}, timeout=90)

    def balance(self):
        return self._post({"action": "balance"})

    def add(self, service_id, link, quantity, extra: dict = None):
        p = {"action": "add", "service": service_id, "link": link, "quantity": quantity}
        if extra:
            p.update(extra)
        return self._post(p)

    def status(self, provider_order):
        return self._post({"action": "status", "order": provider_order})

    def multi_status(self, ids):
        return self._post({"action": "status", "orders": ",".join(str(i) for i in ids)})

    def refill(self, provider_order):
        return self._post({"action": "refill", "order": provider_order})


def provider_client(pid: int):
    p = one("SELECT * FROM providers WHERE id=?", (pid,))
    return ProviderAPI(p) if p else None


def active_providers() -> list:
    return q("SELECT * FROM providers WHERE active=1 ORDER BY is_default DESC, priority ASC, id ASC")


def default_provider():
    p = one("SELECT * FROM providers WHERE active=1 AND is_default=1")
    if p:
        return p
    return one("SELECT * FROM providers WHERE active=1 ORDER BY priority ASC, id ASC")


# ---------------------------------------------------------------------
# PRICING  (provider rate -> local currency + profit markup, or override)
# ---------------------------------------------------------------------
def sell_price(service: dict) -> float:
    if float(service.get("custom_price") or 0) > 0:
        return round(float(service["custom_price"]), 4)
    rate = float(service.get("rate") or 0) * SF("usd_rate", 1)
    return round(rate * (1 + SF("profit_percent", 0) / 100.0), 4)


def order_charge(service: dict, qty: int) -> float:
    return round(sell_price(service) * (int(qty) / 1000.0), 4)


# ---------------------------------------------------------------------
# SERVICE SYNC  (all services imported dynamically, never hardcoded)
# ---------------------------------------------------------------------
def sync_provider(pid: int) -> tuple:
    api = provider_client(pid)
    if not api:
        return 0, "Provider not found"
    try:
        data = api.services()
    except Exception as e:  # noqa: BLE001
        audit("ERROR", 0, "sync_failed", f"{pid}: {e}")
        return 0, str(e)[:200]
    if not isinstance(data, list):
        return 0, f"Unexpected response: {str(data)[:150]}"
    rows, count = [], 0
    for s in data:
        try:
            sid = str(s.get("service"))
            name = str(s.get("name", ""))[:250]
            raw_cat = str(s.get("category", "Others"))[:150]
            cat_id = match_category(raw_cat + " " + name)
            rate = float(s.get("rate", 0) or 0)
            mn = int(float(s.get("min", 1) or 1))
            mx = int(float(s.get("max", 100000) or 100000))
            rows.append((pid, sid, name, cat_id, raw_cat, rate, mn, mx,
                         str(s.get("type", "")), 1 if s.get("refill") else 0,
                         1 if s.get("cancel") else 0, now_ts()))
            count += 1
        except (TypeError, ValueError):
            continue
    runmany("""INSERT INTO services(provider_id, service_id, name, category_id, raw_category, rate,
                    min_qty, max_qty, type, refill, cancel, updated)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider_id, service_id) DO UPDATE SET
                    name=excluded.name, category_id=excluded.category_id,
                    raw_category=excluded.raw_category, rate=excluded.rate,
                    min_qty=excluded.min_qty, max_qty=excluded.max_qty, type=excluded.type,
                    refill=excluded.refill, cancel=excluded.cancel, updated=excluded.updated""", rows)
    run("UPDATE providers SET last_sync=? WHERE id=?", (now_ts(), pid))
    try:
        b = api.balance()
        if isinstance(b, dict):
            run("UPDATE providers SET balance=?, currency=? WHERE id=?",
                (float(b.get("balance", 0) or 0), str(b.get("currency", ""))[:10], pid))
    except Exception:  # noqa: BLE001
        pass
    audit("INFO", 0, "sync_ok", f"provider {pid}: {count} services")
    return count, ""


def sync_all_providers() -> str:
    out = []
    for p in active_providers():
        n, err = sync_provider(p["id"])
        out.append(f"• {p['name']}: {n} services" + (f" ⚠️ {err}" if err else ""))
    return "\n".join(out) or "No active providers."


# =====================================================================
# ORDER ENGINE
# =====================================================================
STATUS_DONE = ("completed",)
STATUS_FAIL = ("canceled", "cancelled", "refunded", "error", "fail", "failed", "partial")


def place_order(uid: int, srow: int, link: str, qty: int) -> tuple:
    """Returns (order_id, error). Balance-safe: charge first, refund on failure."""
    svc = one("SELECT * FROM services WHERE id=?", (srow,))
    if not svc:
        return None, "Service unavailable."
    if svc["hidden"]:
        return None, "Service disabled."
    if not SB("order_enabled", True):
        return None, "Ordering is temporarily disabled."
    qty = int(qty)
    if qty < svc["min_qty"] or qty > svc["max_qty"]:
        return None, f"Quantity must be between {svc['min_qty']} and {svc['max_qty']}."
    charge = order_charge(svc, qty)
    if charge < SF("min_order_amount", 0):
        return None, f"Minimum order amount is {cur(SF('min_order_amount', 0))}."
    with _lock:
        u = get_user(uid)
        if not u:
            return None, "User not found."
        if float(u["balance"]) < charge:
            return None, "insufficient"
        run("UPDATE users SET balance = ROUND(balance - ?, 4), spent = ROUND(spent + ?, 4) WHERE user_id=?",
            (charge, charge, uid))
        bal = float(get_user(uid)["balance"])
        run("INSERT INTO transactions(user_id,kind,amount,balance_after,detail,created) VALUES(?,?,?,?,?,?)",
            (uid, "order", -charge, bal, svc["name"][:120], now_ts()))
        oid = run("""INSERT INTO orders(user_id, service_row, provider_id, provider_order, service_name,
                        link, quantity, charge, status, created, updated)
                     VALUES(?,?,?,?,?,?,?,?,'pending',?,?)""",
                  (uid, srow, svc["provider_id"], "", svc["name"], link, qty, charge, now_ts(), now_ts()))
    api = provider_client(svc["provider_id"])
    if not api:
        refund_order(oid, charge, "provider missing")
        return None, "Provider not configured."
    try:
        res = api.add(svc["service_id"], link, qty)
    except Exception as e:  # noqa: BLE001
        refund_order(oid, charge, f"api error: {e}")
        audit("ERROR", uid, "order_api_error", str(e))
        return None, "Provider API error. Amount refunded."
    if isinstance(res, dict) and res.get("order"):
        run("UPDATE orders SET provider_order=?, status='processing', updated=? WHERE id=?",
            (str(res["order"]), now_ts(), oid))
        audit("INFO", uid, "order_placed", f"#{oid} -> {res['order']}")
        return oid, ""
    reason = (res or {}).get("error") if isinstance(res, dict) else str(res)
    refund_order(oid, charge, f"rejected: {reason}")
    return None, f"Provider rejected the order: {clean(str(reason), 150)}"


def refund_order(oid: int, amount: float, reason: str) -> None:
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    if not o or float(o["refunded"]) > 0:
        return
    amount = round(min(float(amount), float(o["charge"])), 4)
    with _lock:
        run("UPDATE users SET balance = ROUND(balance + ?, 4), spent = MAX(ROUND(spent - ?, 4), 0) WHERE user_id=?",
            (amount, amount, o["user_id"]))
        bal = float(get_user(o["user_id"]).get("balance", 0))
        run("INSERT INTO transactions(user_id,kind,amount,balance_after,detail,created) VALUES(?,?,?,?,?,?)",
            (o["user_id"], "refund", amount, bal, f"order #{oid}: {reason}"[:180], now_ts()))
        run("UPDATE orders SET refunded=?, status='refunded', note=?, updated=? WHERE id=?",
            (amount, str(reason)[:200], now_ts(), oid))
    audit("WARN", o["user_id"], "order_refund", f"#{oid} {amount} {reason}")


def apply_status(o: dict, info: dict) -> tuple:
    """Update one order from provider status payload. Returns (new_status, refunded)."""
    status = str(info.get("status", "")).strip().lower() or o["status"]
    start = int(float(info.get("start_count", 0) or 0))
    remains = int(float(info.get("remains", 0) or 0))
    refunded = 0.0
    if status in STATUS_FAIL and SB("auto_refund", True) and float(o["refunded"]) <= 0:
        charge = float(o["charge"])
        if status == "partial" and int(o["quantity"]) > 0:
            refunded = round(charge * (remains / float(o["quantity"])), 4)
        else:
            refunded = charge
        if refunded > 0:
            refund_order(o["id"], refunded, f"auto refund ({status})")
            status = "refunded" if refunded >= charge else "partial"
    run("UPDATE orders SET status=?, start_count=?, remains=?, updated=? WHERE id=?",
        (status, start, remains, now_ts(), o["id"]))
    return status, refunded


def request_refill(oid: int) -> str:
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    if not o or not o["provider_order"]:
        return "Order not eligible."
    api = provider_client(o["provider_id"])
    if not api:
        return "Provider not configured."
    try:
        res = api.refill(o["provider_order"])
    except Exception as e:  # noqa: BLE001
        return f"Refill failed: {e}"[:180]
    if isinstance(res, dict) and (res.get("refill") or res.get("status")):
        run("UPDATE orders SET note='refill requested', updated=? WHERE id=?", (now_ts(), oid))
        return "✅ Refill requested."
    return f"❌ {clean(str((res or {}).get('error', res)), 150)}"


# =====================================================================
# BOT CLIENT
# =====================================================================
app = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=enums.ParseMode.HTML,
    workers=8,
)

STATE: dict = {}          # user_id -> {"a": action, ...}  (conversation FSM)


def set_state(uid: int, action: str, **data) -> None:
    STATE[uid] = dict(a=action, **data)


def pop_state(uid: int) -> dict:
    return STATE.pop(uid, {})


async def notify(uid: int, text: str, kb=None) -> bool:
    u = get_user(uid)
    if u and not u.get("notify", 1):
        return False
    try:
        await app.send_message(uid, text, reply_markup=kb, disable_web_page_preview=True)
        return True
    except RPCError:
        return False


async def admin_log(text: str) -> None:
    chat = SI("admin_log_chat", 0)
    targets = [chat] if chat else [a["user_id"] for a in q("SELECT user_id FROM admins")]
    for t in targets:
        try:
            await app.send_message(t, text, disable_web_page_preview=True)
        except RPCError:
            continue


async def render(ev, text: str, kb=None) -> None:
    """Edit for callbacks, send for messages."""
    try:
        if isinstance(ev, CallbackQuery):
            await ev.edit_message_text(text, reply_markup=kb, disable_web_page_preview=True)
        else:
            await ev.reply_text(text, reply_markup=kb, disable_web_page_preview=True)
    except RPCError as e:
        if "MESSAGE_NOT_MODIFIED" in str(e):
            return
        try:
            chat = ev.message.chat.id if isinstance(ev, CallbackQuery) else ev.chat.id
            await app.send_message(chat, text, reply_markup=kb, disable_web_page_preview=True)
        except RPCError:
            pass


async def guard(ev) -> bool:
    """Maintenance / ban / flood / force-join gate. True = allowed."""
    uid = ev.from_user.id
    lang = ulang(uid)
    if not flood_ok(uid):
        try:
            await (ev.answer(T("flood", lang), show_alert=True) if isinstance(ev, CallbackQuery)
                   else ev.reply_text(T("flood", lang)))
        except RPCError:
            pass
        return False
    u = get_user(uid)
    if u and u.get("banned"):
        await render(ev, T("banned", lang))
        return False
    if SB("maintenance", False) and not is_admin(uid):
        await render(ev, T("maintenance", lang))
        return False
    missing = await fj_missing(uid)
    if missing:
        await render(ev, T("force_join", lang, channels=fj_list_text(missing)), fj_keyboard(missing))
        return False
    return True


# =====================================================================
# FORCE JOIN CHANNEL MANAGER (fully dynamic, stored in SQLite)
# =====================================================================
def fj_channels(active_only: bool = True) -> list:
    sql = "SELECT * FROM force_channels"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY sort ASC, id ASC"
    return q(sql)


def fj_ref(ch: dict) -> str:
    """Chat reference usable with get_chat_member (@username or -100... id)."""
    cid = str(ch.get("chat_id") or "").strip()
    if cid.lstrip("-").isdigit():
        return cid
    return "@" + cid.lstrip("@")


def fj_link(ch: dict) -> str:
    link = (ch.get("invite_link") or "").strip()
    if link:
        return link
    cid = str(ch.get("chat_id") or "").strip()
    if cid and not cid.lstrip("-").isdigit():
        return f"https://t.me/{cid.lstrip('@')}"
    return ""


def fj_title(ch: dict) -> str:
    return clean(ch.get("title") or str(ch.get("chat_id") or ""), 60)


async def fj_missing(uid: int) -> list:
    """Channels the user has NOT joined yet."""
    if not SB("force_join", False) or is_admin(uid):
        return []
    missing = []
    for ch in fj_channels():
        ref = fj_ref(ch)
        if not ref or ref == "@":
            continue
        try:
            member = await app.get_chat_member(ref, uid)
            status = getattr(member, "status", None)
            if status in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED):
                missing.append(ch)
        except RPCError as e:
            txt = str(e).upper()
            if "USER_NOT_PARTICIPANT" in txt:
                missing.append(ch)
            elif any(k in txt for k in ("CHANNEL_INVALID", "CHAT_ADMIN_REQUIRED", "PEER_ID_INVALID",
                                        "USERNAME_NOT_OCCUPIED", "CHANNEL_PRIVATE")):
                audit("WARN", 0, "force_join_unreachable", f"{ref}: {e}")
            else:
                missing.append(ch)
        except Exception as e:  # noqa: BLE001
            audit("ERROR", 0, "force_join_check", f"{ref}: {e}")
    return missing


def fj_keyboard(missing: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in missing:
        link = fj_link(ch)
        if link:
            rows.append([InlineKeyboardButton(f"📢 Join {fj_title(ch)}", url=link)])
    rows.append([InlineKeyboardButton("✅ Verify Join", callback_data="fjverify")])
    return InlineKeyboardMarkup(rows)


def fj_list_text(missing: list) -> str:
    lines = []
    for ch in missing:
        link = fj_link(ch)
        lines.append(f"• <a href=\"{link}\">{fj_title(ch)}</a>" if link else f"• {fj_title(ch)}")
    return "\n".join(lines) or "—"


def home_text(uid: int) -> str:
    u = get_user(uid) or {}
    orders = one("SELECT COUNT(*) c FROM orders WHERE user_id=?", (uid,))["c"]
    return T("start", ulang(uid), balance=cur(u.get("balance", 0)), orders=orders,
             name=clean(u.get("first_name", "")), id=uid) + T("footer", ulang(uid))


# =====================================================================
# COMMANDS
# =====================================================================
@app.on_message(filters.command("start") & filters.private)
async def cmd_start(_, m: Message):
    u = ensure_user(m)
    uid = m.from_user.id
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) > 1 and not u.get("ref_by"):
        arg = parts[1].strip()
        ref = arg[3:] if arg.startswith("ref") else arg
        if ref.isdigit() and int(ref) != uid and get_user(int(ref)):
            rby = int(ref)
            run("UPDATE users SET ref_by=? WHERE user_id=?", (rby, uid))
            if SB("ref_enabled", True):
                bonus = SF("ref_bonus", 0)
                if bonus > 0:
                    add_balance(rby, bonus, "referral", f"referral {uid}")
                    run("UPDATE users SET ref_earned=ROUND(ref_earned+?,4) WHERE user_id=?", (bonus, rby))
                    await notify(rby, T("referral_joined", ulang(rby),
                                        name=clean(m.from_user.first_name or str(uid)), bonus=cur(bonus)))
            audit("INFO", uid, "referral_join", f"by {rby}")
    if not await guard(m):
        return
    await m.reply_text(
        T("welcome", ulang(uid), name=clean(m.from_user.first_name or ""),
          balance=cur(get_user(uid).get("balance", 0)), id=uid),
        reply_markup=main_menu(uid))


@app.on_message(filters.command("menu") & filters.private)
async def cmd_menu(_, m: Message):
    ensure_user(m)
    if not await guard(m):
        return
    await m.reply_text(home_text(m.from_user.id), reply_markup=main_menu(m.from_user.id))


@app.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(_, m: Message):
    pop_state(m.from_user.id)
    await m.reply_text(T("cancelled", ulang(m.from_user.id)), reply_markup=main_menu(m.from_user.id))


@app.on_message(filters.command("balance") & filters.private)
async def cmd_balance(_, m: Message):
    ensure_user(m)
    if not await guard(m):
        return
    u = get_user(m.from_user.id)
    await m.reply_text(T("balance", ulang(m.from_user.id), balance=cur(u["balance"]),
                         spent=cur(u["spent"]), ref_earned=cur(u["ref_earned"])),
                       reply_markup=main_menu(m.from_user.id))


@app.on_message(filters.command("admin") & filters.private)
async def cmd_admin(_, m: Message):
    ensure_user(m)
    if not is_admin(m.from_user.id):
        return await m.reply_text("🚫 Not authorised.")
    await m.reply_text(admin_home_text(), reply_markup=admin_home_kb(m.from_user.id))


@app.on_message(filters.command("id") & filters.private)
async def cmd_id(_, m: Message):
    await m.reply_text(f"🆔 <code>{m.from_user.id}</code>")


# =====================================================================
# USER CALLBACKS
# =====================================================================
@app.on_callback_query()
async def on_cb(_, cq: CallbackQuery):
    uid = cq.from_user.id
    ensure_user(cq)
    data = cq.data or ""
    try:
        if data == "noop":
            return await cq.answer()
        if data == "disabled":
            return await cq.answer("🚫 This feature is disabled.", show_alert=True)
        if data.startswith("adm:"):
            if not is_admin(uid):
                return await cq.answer("🚫 Not authorised.", show_alert=True)
            return await admin_router(cq, data[4:])
        if data == "fjverify":
            missing = await fj_missing(uid)
            if missing:
                await cq.answer(T("force_join_fail", ulang(uid)), show_alert=True)
                return await render(cq, T("force_join", ulang(uid), channels=fj_list_text(missing)),
                                    fj_keyboard(missing))
            await cq.answer(T("force_join_ok", ulang(uid)), show_alert=True)
            return await render(cq, home_text(uid), main_menu(uid))
        if not await guard(cq):
            return
        await user_router(cq, data)
    except Exception as e:  # noqa: BLE001
        audit("ERROR", uid, "callback_error", f"{data}: {e}\n{traceback.format_exc()[:800]}")
        try:
            await cq.answer(T("error", ulang(uid)), show_alert=True)
        except RPCError:
            pass


async def user_router(cq: CallbackQuery, data: str):
    uid = cq.from_user.id
    lang = ulang(uid)
    per = max(3, SI("page_size", 8))
    u = get_user(uid)

    if data == "home":
        pop_state(uid)
        return await render(cq, home_text(uid), main_menu(uid))

    # ---------------- categories / services ----------------
    if data.startswith("cat:list:"):
        page = int(data.split(":")[2])
        cats = q("""SELECT c.*, (SELECT COUNT(*) FROM services s WHERE s.category_id=c.id AND s.hidden=0) n
                    FROM categories c WHERE c.hidden=0 ORDER BY c.sort ASC, c.name ASC""")
        cats = [c for c in cats if c["n"] > 0]
        if not cats:
            return await render(cq, T("no_services", lang), back_kb())
        chunk = cats[page * per:(page + 1) * per]
        kb = [[InlineKeyboardButton(f"{c['icon']} {c['name']} ({c['n']})",
                                    callback_data=f"cat:open:{c['id']}:0")] for c in chunk]
        kb += pager("cat:list:", page, len(cats), per)
        return await render(cq, T("choose_category", lang), InlineKeyboardMarkup(kb))

    if data.startswith("cat:open:"):
        _, _, cid, page = data.split(":")
        cid, page = int(cid), int(page)
        cat = one("SELECT * FROM categories WHERE id=?", (cid,))
        svcs = q("""SELECT * FROM services WHERE category_id=? AND hidden=0
                    ORDER BY rate ASC, name ASC""", (cid,))
        if not svcs:
            return await render(cq, T("no_services", lang), back_kb("cat:list:0"))
        chunk = svcs[page * per:(page + 1) * per]
        kb = [[InlineKeyboardButton(f"{cur(sell_price(s))} • {s['name'][:45]}",
                                    callback_data=f"svc:{s['id']}")] for s in chunk]
        kb += pager(f"cat:open:{cid}:", page, len(svcs), per, "cat:list:0")
        title = f"{cat['icon']} {cat['name']}" if cat else "Services"
        return await render(cq, T("choose_service", lang, category=title), InlineKeyboardMarkup(kb))

    if data.startswith("svc:"):
        srow = int(data.split(":")[1])
        s = one("SELECT * FROM services WHERE id=? AND hidden=0", (srow,))
        if not s:
            return await cq.answer("Service unavailable.", show_alert=True)
        set_state(uid, "order_link", srow=srow)
        extra = ("♻️ Refill: yes" if s["refill"] else "♻️ Refill: no") + (f"\n🏷 Type: {s['type']}" if s["type"] else "")
        return await render(cq, T("service_info", lang, name=clean(s["name"], 200),
                                 price=cur(sell_price(s)), min=s["min_qty"], max=s["max_qty"], extra=extra),
                            back_kb(f"cat:open:{s['category_id']}:0", "❌ Cancel"))

    if data == "order:confirm":
        st = STATE.get(uid, {})
        if st.get("a") != "order_confirm":
            return await cq.answer("Session expired.", show_alert=True)
        pop_state(uid)
        oid, err = place_order(uid, st["srow"], st["link"], st["qty"])
        if err == "insufficient":
            s = one("SELECT * FROM services WHERE id=?", (st["srow"],))
            return await render(cq, T("insufficient", lang, need=cur(order_charge(s, st["qty"])),
                                     have=cur(get_user(uid)["balance"])), back_kb("dep:list", "💳 Add Funds"))
        if err:
            return await render(cq, T("order_failed", lang, reason=clean(err, 200)), back_kb())
        o = one("SELECT * FROM orders WHERE id=?", (oid,))
        await admin_log(f"🆕 Order <code>#{oid}</code>\n👤 <code>{uid}</code>\n📋 {clean(o['service_name'],80)}\n"
                        f"🔢 {o['quantity']}\n💵 {cur(o['charge'])}")
        return await render(cq, T("order_success", lang, id=oid, name=clean(o["service_name"], 120),
                                 qty=o["quantity"], charge=cur(o["charge"])),
                            back_kb("orders:0", "📦 My Orders"))

    # ---------------- orders ----------------
    if data.startswith("orders:"):
        page = int(data.split(":")[1])
        rows = q("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (uid,))
        if not rows:
            return await render(cq, T("orders", lang, list="📭 No orders yet."), back_kb())
        chunk = rows[page * per:(page + 1) * per]
        listing = "\n".join(f"<code>#{o['id']}</code> • {clean(o['service_name'],40)} • {o['quantity']} • "
                            f"<b>{o['status']}</b> • {cur(o['charge'])}" for o in chunk)
        kb = [[InlineKeyboardButton(f"#{o['id']} · {o['status']}", callback_data=f"order:{o['id']}")]
              for o in chunk]
        kb += pager("orders:", page, len(rows), per)
        return await render(cq, T("orders", lang, list=listing), InlineKeyboardMarkup(kb))

    if data.startswith("order:") and data.split(":")[1].isdigit():
        oid = int(data.split(":")[1])
        o = one("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, uid))
        if not o:
            return await cq.answer("Not found.", show_alert=True)
        kb = [[InlineKeyboardButton("🔄 Refresh status", callback_data=f"order:refresh:{oid}")]]
        s = one("SELECT refill FROM services WHERE id=?", (o["service_row"],))
        if s and s["refill"] and o["status"] in ("completed", "partial"):
            kb.append([InlineKeyboardButton("♻️ Request refill", callback_data=f"order:refill:{oid}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="orders:0")])
        return await render(cq, T("order_detail", lang, id=o["id"], name=clean(o["service_name"], 120),
                                 link=clean(o["link"], 120), qty=o["quantity"], status=o["status"],
                                 start=o["start_count"], remains=o["remains"], charge=cur(o["charge"]),
                                 refunded=cur(o["refunded"]),
                                 created=datetime.utcfromtimestamp(o["created"]).strftime("%Y-%m-%d %H:%M")),
                            InlineKeyboardMarkup(kb))

    if data.startswith("order:refresh:"):
        oid = int(data.split(":")[2])
        o = one("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, uid))
        if not o:
            return await cq.answer("Not found.", show_alert=True)
        await cq.answer("Checking…")
        await asyncio.get_event_loop().run_in_executor(None, poll_single, oid)
        return await user_router(cq, f"order:{oid}")

    if data.startswith("order:refill:"):
        oid = int(data.split(":")[2])
        if not one("SELECT id FROM orders WHERE id=? AND user_id=?", (oid, uid)):
            return await cq.answer("Not found.", show_alert=True)
        msg = await asyncio.get_event_loop().run_in_executor(None, request_refill, oid)
        return await cq.answer(msg, show_alert=True)

    # ---------------- wallet / history ----------------
    if data == "wallet":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_label("deposit", "💳 Add Funds"), callback_data="dep:list")],
            [InlineKeyboardButton(btn_label("history", "📜 History"), callback_data="history:0")],
            [InlineKeyboardButton("🔙 Back", callback_data="home")]])
        return await render(cq, T("balance", lang, balance=cur(u["balance"]), spent=cur(u["spent"]),
                                 ref_earned=cur(u["ref_earned"])), kb)

    if data.startswith("history:"):
        page = int(data.split(":")[1])
        rows = q("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC", (uid,))
        if not rows:
            return await render(cq, T("history", lang, list="📭 Nothing yet."), back_kb())
        chunk = rows[page * per:(page + 1) * per]
        listing = "\n".join(
            f"{'➕' if t['amount'] >= 0 else '➖'} <b>{cur(abs(t['amount']))}</b> • {t['kind']} • "
            f"{datetime.utcfromtimestamp(t['created']).strftime('%m-%d %H:%M')}\n<i>{clean(t['detail'],60)}</i>"
            for t in chunk)
        return await render(cq, T("history", lang, list=listing),
                            InlineKeyboardMarkup(pager("history:", page, len(rows), per)))

    # ---------------- deposits ----------------
    if data == "dep:list":
        if not SB("deposit_enabled", True):
            return await cq.answer("🚫 Deposits are disabled.", show_alert=True)
        ms = q("SELECT * FROM payment_methods WHERE active=1 ORDER BY sort ASC, id ASC")
        if not ms:
            return await render(cq, "📭 No payment methods available.", back_kb())
        kb = [[InlineKeyboardButton(f"{m['icon']} {m['name']}", callback_data=f"dep:m:{m['id']}")] for m in ms]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="home")])
        return await render(cq, T("deposit", lang), InlineKeyboardMarkup(kb))

    if data.startswith("dep:m:"):
        mid = int(data.split(":")[2])
        m = one("SELECT * FROM payment_methods WHERE id=? AND active=1", (mid,))
        if not m:
            return await cq.answer("Unavailable.", show_alert=True)
        set_state(uid, "dep_amount", mid=mid)
        return await render(cq, T("deposit_method", lang, name=f"{m['icon']} {m['name']}",
                                 address=clean(m["address"], 200), instructions=clean(m["instructions"], 600),
                                 min=cur(m["min_amount"]), max=cur(m["max_amount"])),
                            back_kb("dep:list", "❌ Cancel"))

    # ---------------- account / referral / coupon ----------------
    if data == "account":
        orders = one("SELECT COUNT(*) c FROM orders WHERE user_id=?", (uid,))["c"]
        refs = one("SELECT COUNT(*) c FROM users WHERE ref_by=?", (uid,))["c"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(("🔔 Notifications: ON" if u.get("notify", 1) else "🔕 Notifications: OFF"),
                                  callback_data="acc:notify")],
            [InlineKeyboardButton(btn_label("language", "🌐 Language"), callback_data="lang")],
            [InlineKeyboardButton("🔙 Back", callback_data="home")]])
        return await render(cq, T("account", lang, id=uid, name=clean(u.get("first_name", "")),
                                 username=clean(u.get("username") or "none"), lang=lang,
                                 balance=cur(u["balance"]), spent=cur(u["spent"]), orders=orders, refs=refs,
                                 joined=datetime.utcfromtimestamp(u["joined"] or now_ts()).strftime("%Y-%m-%d")), kb)

    if data == "acc:notify":
        run("UPDATE users SET notify=1-notify WHERE user_id=?", (uid,))
        return await user_router(cq, "account")

    if data == "ref":
        if not SB("ref_enabled", True):
            return await cq.answer("🚫 Referral program is disabled.", show_alert=True)
        me = S("bot_username", "").lstrip("@") or (await app.get_me()).username
        set_setting("bot_username", me)
        refs = one("SELECT COUNT(*) c FROM users WHERE ref_by=?", (uid,))["c"]
        kb = [[InlineKeyboardButton("🏧 Withdraw earnings", callback_data="ref:withdraw")],
              [InlineKeyboardButton("🔙 Back", callback_data="home")]]
        return await render(cq, T("referral", lang, link=f"https://t.me/{me}?start=ref{uid}", count=refs,
                                 earned=cur(u["ref_earned"]), bonus=cur(SF("ref_bonus", 0)),
                                 commission=SF("ref_commission", 0),
                                 min_withdraw=cur(SF("ref_min_withdraw", 0))), InlineKeyboardMarkup(kb))

    if data == "ref:withdraw":
        earned = float(u["ref_earned"])
        mn = SF("ref_min_withdraw", 0)
        if earned < mn:
            return await cq.answer(f"Minimum withdraw is {cur(mn)} (you have {cur(earned)}).", show_alert=True)
        run("UPDATE users SET ref_earned=0 WHERE user_id=?", (uid,))
        bal = add_balance(uid, earned, "ref_withdraw", "referral earnings to wallet")
        return await render(cq, f"✅ <b>{cur(earned)}</b> moved to your wallet.\n💰 Balance: <b>{cur(bal)}</b>",
                            back_kb())

    if data == "coupon":
        set_state(uid, "coupon_code")
        return await render(cq, T("coupon", lang), back_kb("home", "❌ Cancel"))

    # ---------------- support ----------------
    if data == "ticket":
        set_state(uid, "ticket_body")
        rows = q("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,))
        extra = ""
        if rows:
            extra = "\n\n🗂 <b>Your tickets</b>\n" + "\n".join(
                f"<code>#{t['id']}</code> • {clean(t['subject'],40)} • <b>{t['status']}</b>" for t in rows)
        sup = S("support_username", "").lstrip("@")
        kb = [[InlineKeyboardButton("👨‍💻 Contact admin", url=f"https://t.me/{sup}")]] if sup else []
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="home")])
        return await render(cq, T("ticket", lang) + extra, InlineKeyboardMarkup(kb))

    # ---------------- language / info ----------------
    if data == "lang":
        langs = [x.strip() for x in S("languages", "en").split(",") if x.strip()]
        kb = [[InlineKeyboardButton(f"{'✅ ' if x == lang else ''}{x.upper()}", callback_data=f"lang:set:{x}")]
              for x in langs]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="home")])
        return await render(cq, T("language", lang), InlineKeyboardMarkup(kb))

    if data.startswith("lang:set:"):
        newlang = data.split(":")[2][:5]
        run("UPDATE users SET lang=? WHERE user_id=?", (newlang, uid))
        await cq.answer(T("language_set", newlang))
        return await render(cq, home_text(uid), main_menu(uid))

    if data.startswith("info:"):
        key = data.split(":")[1]
        return await render(cq, T(key, lang), back_kb())

    return await cq.answer()


# =====================================================================
# TEXT INPUT ROUTER (conversation FSM for users + admins)
# =====================================================================
@app.on_message(filters.private & ~filters.command(["start", "menu", "admin", "cancel", "balance", "id"]))
async def on_text(_, m: Message):
    uid = m.from_user.id
    ensure_user(m)
    st = STATE.get(uid)
    if not st:
        if not await guard(m):
            return
        return await m.reply_text(home_text(uid), reply_markup=main_menu(uid))
    if st.get("a", "").startswith("adm_"):
        return await admin_input(m, st)
    if not await guard(m):
        return
    lang = ulang(uid)
    a = st["a"]
    body = (m.text or m.caption or "").strip()

    if a == "order_link":
        if not valid_link(body):
            return await m.reply_text(T("invalid_input", lang))
        s = one("SELECT * FROM services WHERE id=?", (st["srow"],))
        if not s:
            pop_state(uid)
            return await m.reply_text(T("error", lang))
        set_state(uid, "order_qty", srow=st["srow"], link=body)
        return await m.reply_text(T("ask_quantity", lang, min=s["min_qty"], max=s["max_qty"]))

    if a == "order_qty":
        s = one("SELECT * FROM services WHERE id=?", (st["srow"],))
        v = valid_amount(body, 1, 10 ** 9)
        if not s or v is None or int(v) < s["min_qty"] or int(v) > s["max_qty"]:
            return await m.reply_text(T("invalid_input", lang))
        qty = int(v)
        charge = order_charge(s, qty)
        set_state(uid, "order_confirm", srow=st["srow"], link=st["link"], qty=qty)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data="order:confirm"),
             InlineKeyboardButton("❌ Cancel", callback_data="home")]])
        return await m.reply_text(T("order_summary", lang, name=clean(s["name"], 120), link=clean(st["link"], 120),
                                    qty=qty, charge=cur(charge), balance=cur(get_user(uid)["balance"])), reply_markup=kb)

    if a == "dep_amount":
        pm = one("SELECT * FROM payment_methods WHERE id=?", (st["mid"],))
        v = valid_amount(body, 0.01)
        if not pm or v is None or v < pm["min_amount"] or v > pm["max_amount"]:
            return await m.reply_text(T("invalid_input", lang))
        set_state(uid, "dep_txid", mid=st["mid"], amount=v)
        return await m.reply_text(T("deposit_txid", lang))

    if a == "dep_txid":
        pm = one("SELECT * FROM payment_methods WHERE id=?", (st["mid"],))
        pop_state(uid)
        if not pm or len(body) < 3:
            return await m.reply_text(T("invalid_input", lang))
        coupon = st.get("coupon", "") or (get_user(uid).get("coupon") or "")
        did = run("""INSERT INTO deposits(user_id, method_id, method_name, amount, txid, status, coupon, created)
                     VALUES(?,?,?,?,?,'pending',?,?)""",
                  (uid, pm["id"], pm["name"], st["amount"], clean(body, 120), coupon, now_ts()))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"adm:dep:ok:{did}"),
                                    InlineKeyboardButton("❌ Reject", callback_data=f"adm:dep:no:{did}")]])
        for adm in q("SELECT user_id FROM admins"):
            try:
                await app.send_message(adm["user_id"],
                                       f"💳 <b>Deposit #{did}</b>\n👤 <code>{uid}</code>\n"
                                       f"🏦 {pm['name']}\n💵 {cur(st['amount'])}\n🧾 <code>{clean(body,120)}</code>",
                                       reply_markup=kb)
            except RPCError:
                continue
        return await m.reply_text(T("deposit_submitted", lang, id=did, amount=cur(st["amount"])),
                                  reply_markup=main_menu(uid))

    if a == "coupon_code":
        pop_state(uid)
        code = body.upper()[:32]
        c = one("SELECT * FROM coupons WHERE code=? AND active=1", (code,))
        if (not c or (c["expires"] and c["expires"] < now_ts()) or c["used"] >= c["max_uses"]
                or one("SELECT id FROM coupon_uses WHERE code=? AND user_id=?", (code, uid))):
            return await m.reply_text(T("coupon_bad", lang), reply_markup=main_menu(uid))
        set_setting(f"user_coupon_{uid}", code)
        return await m.reply_text(T("coupon_ok", lang, code=code, percent=c["percent"]),
                                  reply_markup=main_menu(uid))

    if a == "ticket_body":
        pop_state(uid)
        if len(body) < 3:
            return await m.reply_text(T("invalid_input", lang))
        tid = run("INSERT INTO tickets(user_id, subject, status, created, updated) VALUES(?,?,'open',?,?)",
                  (uid, clean(body, 60), now_ts(), now_ts()))
        run("INSERT INTO ticket_messages(ticket_id, sender, body, created) VALUES(?,?,?,?)",
            (tid, "user", clean(body, 3000), now_ts()))
        await admin_log(f"📞 <b>Ticket #{tid}</b>\n👤 <code>{uid}</code>\n\n{clean(body,600)}\n\n"
                        f"Reply: <code>/reply {tid} your message</code>")
        return await m.reply_text(T("ticket_created", lang, id=tid), reply_markup=main_menu(uid))

    pop_state(uid)
    return await m.reply_text(home_text(uid), reply_markup=main_menu(uid))


@app.on_message(filters.command("reply") & filters.private)
async def cmd_reply(_, m: Message):
    if not is_admin(m.from_user.id):
        return
    parts = (m.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return await m.reply_text("Usage: <code>/reply TICKET_ID message</code>")
    tid, body = int(parts[1]), parts[2]
    t = one("SELECT * FROM tickets WHERE id=?", (tid,))
    if not t:
        return await m.reply_text("Ticket not found.")
    run("INSERT INTO ticket_messages(ticket_id, sender, body, created) VALUES(?,?,?,?)",
        (tid, "admin", clean(body, 3000), now_ts()))
    run("UPDATE tickets SET status='answered', updated=? WHERE id=?", (now_ts(), tid))
    await notify(t["user_id"], T("ticket_reply", ulang(t["user_id"]), id=tid, body=clean(body, 3000)))
    await m.reply_text("✅ Sent.")


# =====================================================================
# ADMIN PANEL (fully dynamic management)
# =====================================================================
def admin_home_text() -> str:
    u = one("SELECT COUNT(*) c FROM users")["c"]
    today = now_ts() - 86400
    nu = one("SELECT COUNT(*) c FROM users WHERE joined>?", (today,))["c"]
    o = one("SELECT COUNT(*) c FROM orders")["c"]
    no = one("SELECT COUNT(*) c FROM orders WHERE created>?", (today,))["c"]
    rev = one("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE kind='deposit'")["s"]
    spent = one("SELECT COALESCE(SUM(charge-refunded),0) s FROM orders")["s"]
    pend = one("SELECT COUNT(*) c FROM deposits WHERE status='pending'")["c"]
    svc = one("SELECT COUNT(*) c FROM services")["c"]
    return (f"👑 <b>Admin Dashboard</b>\n\n"
            f"👥 Users: <b>{u}</b> (+{nu} today)\n"
            f"📦 Orders: <b>{o}</b> (+{no} today)\n"
            f"💰 Deposits: <b>{cur(rev)}</b>\n"
            f"💸 Sales: <b>{cur(spent)}</b>\n"
            f"⏳ Pending deposits: <b>{pend}</b>\n"
            f"🧾 Services: <b>{svc}</b>\n"
            f"🛠 Maintenance: <b>{'ON' if SB('maintenance') else 'OFF'}</b>")


def admin_home_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="adm:users:0"),
         InlineKeyboardButton("📦 Orders", callback_data="adm:orders:0")],
        [InlineKeyboardButton("💳 Deposits", callback_data="adm:deps:0"),
         InlineKeyboardButton("🏦 Payment Methods", callback_data="adm:pm:list")],
        [InlineKeyboardButton("🔑 Provider APIs", callback_data="adm:api:list"),
         InlineKeyboardButton("🧾 Services", callback_data="adm:svc:home")],
        [InlineKeyboardButton("🗂 Categories", callback_data="adm:cat:list"),
         InlineKeyboardButton("🎟 Coupons", callback_data="adm:cpn:list")],
        [InlineKeyboardButton("📞 Tickets", callback_data="adm:tk:0"),
         InlineKeyboardButton("📢 Broadcast", callback_data="adm:bc:start")],
        [InlineKeyboardButton("✏️ Texts", callback_data="adm:txt:0"),
         InlineKeyboardButton("🎛 Menu Buttons", callback_data="adm:btn:list")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="adm:set:0"),
         InlineKeyboardButton("📈 Statistics", callback_data="adm:stats")],
        [InlineKeyboardButton("🔒 Force Join", callback_data="adm:fj:list"),
         InlineKeyboardButton("🗒 Logs", callback_data="adm:logs")],
        [InlineKeyboardButton("🛠 Toggle Maintenance", callback_data="adm:maint")],
        [InlineKeyboardButton("🏠 User Menu", callback_data="home")],
    ])


def akb(rows, back="adm:home"):
    rows = list(rows)
    rows.append([InlineKeyboardButton("🔙 Back", callback_data=back)])
    return InlineKeyboardMarkup(rows)


async def admin_router(cq: CallbackQuery, d: str):
    uid = cq.from_user.id
    per = max(3, SI("page_size", 8))

    if d == "home":
        pop_state(uid)
        return await render(cq, admin_home_text(), admin_home_kb(uid))

    if d == "maint":
        set_setting("maintenance", "0" if SB("maintenance") else "1")
        audit("WARN", uid, "maintenance", S("maintenance"))
        return await render(cq, admin_home_text(), admin_home_kb(uid))

    if d == "stats":
        t = now_ts() - 86400
        rows = {
            "Total users": one("SELECT COUNT(*) c FROM users")["c"],
            "Today users": one("SELECT COUNT(*) c FROM users WHERE joined>?", (t,))["c"],
            "Active (24h)": one("SELECT COUNT(*) c FROM users WHERE last_seen>?", (t,))["c"],
            "Banned": one("SELECT COUNT(*) c FROM users WHERE banned=1")["c"],
            "Total orders": one("SELECT COUNT(*) c FROM orders")["c"],
            "Today orders": one("SELECT COUNT(*) c FROM orders WHERE created>?", (t,))["c"],
            "Completed": one("SELECT COUNT(*) c FROM orders WHERE status='completed'")["c"],
            "Cancelled/Refunded": one("SELECT COUNT(*) c FROM orders WHERE status IN ('canceled','cancelled','refunded')")["c"],
            "Pending deposits": one("SELECT COUNT(*) c FROM deposits WHERE status='pending'")["c"],
        }
        dep = one("SELECT COALESCE(SUM(credited),0) s FROM deposits WHERE status='approved'")["s"]
        sales = one("SELECT COALESCE(SUM(charge-refunded),0) s FROM orders")["s"]
        cost = one("""SELECT COALESCE(SUM(o.charge),0) s FROM orders o""")["s"] / max(1.0, 1 + SF("profit_percent", 0) / 100)
        body = "\n".join(f"• {k}: <b>{v}</b>" for k, v in rows.items())
        body += (f"\n• Total deposits: <b>{cur(dep)}</b>\n• Revenue: <b>{cur(sales)}</b>"
                 f"\n• Est. profit: <b>{cur(sales - cost)}</b>")
        return await render(cq, "📈 <b>Statistics</b>\n\n" + body, akb([]))

    if d == "logs":
        rows = q("SELECT * FROM logs ORDER BY id DESC LIMIT 20")
        body = "\n".join(f"<code>{datetime.utcfromtimestamp(l['created']).strftime('%m-%d %H:%M')}</code> "
                         f"[{l['level']}] {clean(l['action'],30)} — {clean(l['detail'],60)}" for l in rows)
        return await render(cq, "🗒 <b>Recent logs</b>\n\n" + (body or "empty"), akb([]))

    # ---------------- force join channels ----------------
    if d == "fj:list":
        rows = fj_channels(active_only=False)
        kb = [[InlineKeyboardButton(f"{'✅' if c['active'] else '⛔️'} {c['sort']} · {fj_title(c)}",
                                    callback_data=f"adm:fj:ch:{c['id']}")] for c in rows]
        kb.append([InlineKeyboardButton("➕ Add channel", callback_data="adm:fj:add")])
        kb.append([InlineKeyboardButton(f"🔒 Force Join: {'ON' if SB('force_join') else 'OFF'}",
                                        callback_data="adm:fj:toggle")])
        return await render(cq, ("🔒 <b>Force Join Manager</b>\n\n"
                                 f"Channels: <b>{len(rows)}</b> (active {len([c for c in rows if c['active']])})\n"
                                 "Add public channels by @username or private channels by numeric ID + invite link.\n"
                                 "⚠️ The bot must be an admin in every channel."), akb(kb))

    if d == "fj:toggle":
        set_setting("force_join", "0" if SB("force_join") else "1")
        audit("WARN", uid, "force_join_toggle", S("force_join"))
        return await admin_router(cq, "fj:list")

    if d == "fj:add":
        set_state(uid, "adm_fj_add")
        return await render(cq, ("➕ <b>Add force-join channel</b>\n\n"
                                 "Send: <code>@username | Title | invite link (optional)</code>\n"
                                 "Private channel: <code>-1001234567890 | VIP | https://t.me/+abc123</code>"),
                            akb([], "adm:fj:list"))

    if d.startswith("fj:ch:"):
        cid = int(d.split(":")[2])
        c = one("SELECT * FROM force_channels WHERE id=?", (cid,))
        if not c:
            return await cq.answer("Not found.", show_alert=True)
        kb = [
            [InlineKeyboardButton("✏️ Edit username/ID", callback_data=f"adm:fj:edit:{cid}"),
             InlineKeyboardButton("🏷 Edit title", callback_data=f"adm:fj:title:{cid}")],
            [InlineKeyboardButton("🔗 Edit invite link", callback_data=f"adm:fj:link:{cid}"),
             InlineKeyboardButton("↕️ Change order", callback_data=f"adm:fj:sort:{cid}")],
            [InlineKeyboardButton("⛔️ Disable" if c["active"] else "✅ Enable",
                                  callback_data=f"adm:fj:tog:{cid}"),
             InlineKeyboardButton("🗑 Remove", callback_data=f"adm:fj:del:{cid}")],
        ]
        return await render(cq, (f"🔒 <b>Channel #{cid}</b>\n\n"
                                 f"🆔 <code>{clean(c['chat_id'], 60)}</code>\n"
                                 f"🏷 {fj_title(c)}\n"
                                 f"🔗 {clean(c['invite_link'] or fj_link(c) or 'none', 80)}\n"
                                 f"↕️ Order: <b>{c['sort']}</b>\n"
                                 f"📶 Status: <b>{'active' if c['active'] else 'disabled'}</b>"),
                            akb(kb, "adm:fj:list"))

    if d.startswith("fj:tog:"):
        cid = int(d.split(":")[2])
        run("UPDATE force_channels SET active=1-active WHERE id=?", (cid,))
        audit("INFO", uid, "force_channel_toggle", cid)
        return await admin_router(cq, f"fj:ch:{cid}")

    if d.startswith("fj:del:"):
        cid = int(d.split(":")[2])
        run("DELETE FROM force_channels WHERE id=?", (cid,))
        audit("WARN", uid, "force_channel_delete", cid)
        return await admin_router(cq, "fj:list")

    if d.startswith("fj:edit:") or d.startswith("fj:title:") or d.startswith("fj:link:") or d.startswith("fj:sort:"):
        kind, cid = d.split(":")[1], int(d.split(":")[2])
        prompts = {
            "edit": "✏️ Send new <b>@username</b> or numeric channel ID:",
            "title": "🏷 Send new <b>title</b>:",
            "link": "🔗 Send new <b>invite link</b> (send <code>-</code> to clear):",
            "sort": "↕️ Send new <b>order number</b> (lower shows first):",
        }
        set_state(uid, f"adm_fj_{kind}", cid=cid)
        return await render(cq, prompts[kind], akb([], f"adm:fj:ch:{cid}"))

    # ---------------- users ----------------
    if d.startswith("users:"):
        page = int(d.split(":")[1])
        rows = q("SELECT * FROM users ORDER BY joined DESC")
        chunk = rows[page * per:(page + 1) * per]
        kb = [[InlineKeyboardButton(f"{'🚫' if x['banned'] else '👤'} {x['user_id']} • {cur(x['balance'])}",
                                    callback_data=f"adm:user:{x['user_id']}")] for x in chunk]
        kb.append([InlineKeyboardButton("🔎 Search user", callback_data="adm:user:search")])
        kb += pager("adm:users:", page, len(rows), per, "adm:home")
        return await render(cq, f"👥 <b>Users</b> — total {len(rows)}", InlineKeyboardMarkup(kb))

    if d == "user:search":
        set_state(uid, "adm_user_search")
        return await render(cq, "🔎 Send user ID or @username:", akb([], "adm:users:0"))

    if d.startswith("user:") and d.split(":")[1].lstrip("-").isdigit():
        tid = int(d.split(":")[1])
        x = get_user(tid)
        if not x:
            return await cq.answer("Not found.", show_alert=True)
        orders = one("SELECT COUNT(*) c FROM orders WHERE user_id=?", (tid,))["c"]
        kb = [
            [InlineKeyboardButton("➕ Add balance", callback_data=f"adm:ubal:add:{tid}"),
             InlineKeyboardButton("➖ Remove balance", callback_data=f"adm:ubal:sub:{tid}")],
            [InlineKeyboardButton("♻️ Reset balance", callback_data=f"adm:ubal:reset:{tid}"),
             InlineKeyboardButton("♻️ Reset referral", callback_data=f"adm:uref:{tid}")],
            [InlineKeyboardButton("✅ Unban" if x["banned"] else "🚫 Ban", callback_data=f"adm:uban:{tid}"),
             InlineKeyboardButton("🗑 Delete", callback_data=f"adm:udel:{tid}")],
            [InlineKeyboardButton("✉️ Message user", callback_data=f"adm:umsg:{tid}")],
        ]
        return await render(cq, f"👤 <b>User {tid}</b>\n\n@{clean(x['username'] or 'none')}\n"
                                f"💰 {cur(x['balance'])}\n💸 spent {cur(x['spent'])}\n📦 orders {orders}\n"
                                f"🎁 ref earned {cur(x['ref_earned'])}\n🚫 banned: {bool(x['banned'])}",
                            akb(kb, "adm:users:0"))

    if d.startswith("ubal:"):
        _, mode, tid = d.split(":")
        tid = int(tid)
        if mode == "reset":
            run("UPDATE users SET balance=0 WHERE user_id=?", (tid,))
            audit("WARN", uid, "balance_reset", tid)
            return await admin_router(cq, f"user:{tid}")
        set_state(uid, "adm_balance", tid=tid, mode=mode)
        return await render(cq, f"💵 Send amount to {'add to' if mode == 'add' else 'remove from'} user {tid}:",
                            akb([], f"adm:user:{tid}"))

    if d.startswith("uref:"):
        tid = int(d.split(":")[1])
        run("UPDATE users SET ref_earned=0 WHERE user_id=?", (tid,))
        run("UPDATE users SET ref_by=NULL WHERE ref_by=?", (tid,))
        return await admin_router(cq, f"user:{tid}")

    if d.startswith("uban:"):
        tid = int(d.split(":")[1])
        run("UPDATE users SET banned=1-banned WHERE user_id=?", (tid,))
        audit("WARN", uid, "user_ban_toggle", tid)
        return await admin_router(cq, f"user:{tid}")

    if d.startswith("udel:"):
        tid = int(d.split(":")[1])
        run("DELETE FROM users WHERE user_id=?", (tid,))
        audit("WARN", uid, "user_delete", tid)
        return await admin_router(cq, "users:0")

    if d.startswith("umsg:"):
        tid = int(d.split(":")[1])
        set_state(uid, "adm_umsg", tid=tid)
        return await render(cq, f"✉️ Send the message for user {tid}:", akb([], f"adm:user:{tid}"))

    # ---------------- orders ----------------
    if d.startswith("orders:"):
        page = int(d.split(":")[1])
        rows = q("SELECT * FROM orders ORDER BY id DESC")
        chunk = rows[page * per:(page + 1) * per]
        body = "\n".join(f"<code>#{o['id']}</code> 👤{o['user_id']} • {clean(o['service_name'],28)} • "
                         f"{o['quantity']} • <b>{o['status']}</b> • {cur(o['charge'])}" for o in chunk) or "empty"
        kb = [[InlineKeyboardButton("🔄 Poll all statuses", callback_data="adm:poll")]]
        kb += pager("adm:orders:", page, len(rows), per, "adm:home")
        return await render(cq, f"📦 <b>Orders</b> — {len(rows)}\n\n{body}", InlineKeyboardMarkup(kb))

    if d == "poll":
        await cq.answer("Polling…")
        n = await asyncio.get_event_loop().run_in_executor(None, poll_orders)
        return await cq.answer(f"✅ {n} orders updated.", show_alert=True)

    # ---------------- deposits ----------------
    if d.startswith("deps:"):
        page = int(d.split(":")[1])
        rows = q("SELECT * FROM deposits ORDER BY (status='pending') DESC, id DESC")
        chunk = rows[page * per:(page + 1) * per]
        kb = [[InlineKeyboardButton(f"#{x['id']} {x['status']} • {cur(x['amount'])} • {x['user_id']}",
                                    callback_data=f"adm:dep:v:{x['id']}")] for x in chunk]
        kb += pager("adm:deps:", page, len(rows), per, "adm:home")
        return await render(cq, f"💳 <b>Deposits</b> — {len(rows)}", InlineKeyboardMarkup(kb))

    if d.startswith("dep:v:"):
        did = int(d.split(":")[2])
        x = one("SELECT * FROM deposits WHERE id=?", (did,))
        if not x:
            return await cq.answer("Not found.", show_alert=True)
        kb = []
        if x["status"] == "pending":
            kb.append([InlineKeyboardButton("✅ Approve", callback_data=f"adm:dep:ok:{did}"),
                       InlineKeyboardButton("❌ Reject", callback_data=f"adm:dep:no:{did}")])
        return await render(cq, f"💳 <b>Deposit #{did}</b>\n👤 <code>{x['user_id']}</code>\n🏦 {x['method_name']}\n"
                                f"💵 {cur(x['amount'])}\n🧾 <code>{clean(x['txid'],120)}</code>\n"
                                f"📊 {x['status']}", akb(kb, "adm:deps:0"))

    if d.startswith("dep:ok:"):
        did = int(d.split(":")[2])
        x = one("SELECT * FROM deposits WHERE id=? AND status='pending'", (did,))
        if not x:
            return await cq.answer("Already handled.", show_alert=True)
        amount = float(x["amount"])
        code = S(f"user_coupon_{x['user_id']}", "")
        bonus = 0.0
        if code:
            c = one("SELECT * FROM coupons WHERE code=? AND active=1", (code,))
            if c and amount >= c["min_deposit"] and c["used"] < c["max_uses"] and (not c["expires"] or c["expires"] > now_ts()):
                bonus = round(amount * float(c["percent"]) / 100.0, 4)
                run("UPDATE coupons SET used=used+1 WHERE id=?", (c["id"],))
                run("INSERT INTO coupon_uses(code,user_id,amount,created) VALUES(?,?,?,?)",
                    (code, x["user_id"], bonus, now_ts()))
            set_setting(f"user_coupon_{x['user_id']}", "")
        total = amount + bonus
        bal = add_balance(x["user_id"], total, "deposit", f"deposit #{did} {x['method_name']}")
        run("UPDATE deposits SET status='approved', credited=?, handled=?, admin_id=? WHERE id=?",
            (total, now_ts(), uid, did))
        u = get_user(x["user_id"])
        if u and u.get("ref_by") and SB("ref_enabled", True):
            comm = round(amount * SF("ref_commission", 0) / 100.0, 4)
            if comm > 0:
                run("UPDATE users SET ref_earned=ROUND(ref_earned+?,4) WHERE user_id=?", (comm, u["ref_by"]))
                await notify(u["ref_by"], T("referral_commission", ulang(u["ref_by"]), amount=cur(comm),
                                            name=clean(u.get("first_name", ""))))
        await notify(x["user_id"], T("deposit_approved", ulang(x["user_id"]), id=did, amount=cur(total),
                                     balance=cur(bal)))
        audit("INFO", uid, "deposit_approved", f"#{did} {total}")
        return await cq.answer("✅ Approved.", show_alert=True)

    if d.startswith("dep:no:"):
        did = int(d.split(":")[2])
        set_state(uid, "adm_dep_reject", did=did)
        return await render(cq, "📝 Send the rejection reason:", akb([], "adm:deps:0"))

    # ---------------- providers ----------------
    if d == "api:list":
        rows = q("SELECT * FROM providers ORDER BY priority ASC, id ASC")
        kb = [[InlineKeyboardButton(f"{'✅' if p['active'] else '⛔️'}{'⭐️' if p['is_default'] else ''} {p['name']}"
                                    f" • {p['balance']}{p['currency']}", callback_data=f"adm:api:v:{p['id']}")]
              for p in rows]
        kb.append([InlineKeyboardButton("➕ Add provider", callback_data="adm:api:add")])
        kb.append([InlineKeyboardButton("🔄 Sync all services", callback_data="adm:api:syncall")])
        return await render(cq, f"🔑 <b>Provider APIs</b> — {len(rows)}", akb(kb))

    if d == "api:add":
        set_state(uid, "adm_api_add")
        return await render(cq, "➕ Send: <code>Name | https://panel.com/api/v2 | APIKEY</code>",
                            akb([], "adm:api:list"))

    if d == "api:syncall":
        await cq.answer("Syncing…")
        res = await asyncio.get_event_loop().run_in_executor(None, sync_all_providers)
        return await render(cq, "🔄 <b>Sync result</b>\n\n" + res, akb([], "adm:api:list"))

    if d.startswith("api:v:"):
        pid = int(d.split(":")[2])
        p = one("SELECT * FROM providers WHERE id=?", (pid,))
        if not p:
            return await cq.answer("Not found.", show_alert=True)
        n = one("SELECT COUNT(*) c FROM services WHERE provider_id=?", (pid,))["c"]
        kb = [
            [InlineKeyboardButton("🔄 Sync services", callback_data=f"adm:api:sync:{pid}"),
             InlineKeyboardButton("🧪 Test API", callback_data=f"adm:api:test:{pid}")],
            [InlineKeyboardButton("⛔️ Disable" if p["active"] else "✅ Enable", callback_data=f"adm:api:tg:{pid}"),
             InlineKeyboardButton("⭐️ Set default", callback_data=f"adm:api:def:{pid}")],
            [InlineKeyboardButton("✏️ Edit", callback_data=f"adm:api:edit:{pid}"),
             InlineKeyboardButton("🔢 Priority", callback_data=f"adm:api:prio:{pid}")],
            [InlineKeyboardButton("🗑 Delete", callback_data=f"adm:api:del:{pid}")],
        ]
        return await render(cq, f"🔑 <b>{clean(p['name'])}</b>\n\n🌐 <code>{clean(p['url'],120)}</code>\n"
                                f"🔐 <code>{clean(p['api_key'][:6])}***</code>\n💰 {p['balance']} {p['currency']}\n"
                                f"🧾 Services: {n}\n📌 Priority: {p['priority']}\n"
                                f"📊 Active: {bool(p['active'])} | Default: {bool(p['is_default'])}",
                            akb(kb, "adm:api:list"))

    if d.startswith("api:sync:"):
        pid = int(d.split(":")[2])
        await cq.answer("Syncing…")
        n, err = await asyncio.get_event_loop().run_in_executor(None, sync_provider, pid)
        return await cq.answer(f"✅ {n} services." if not err else f"❌ {err}", show_alert=True)

    if d.startswith("api:test:"):
        pid = int(d.split(":")[2])
        api = provider_client(pid)
        try:
            res = await asyncio.get_event_loop().run_in_executor(None, api.balance)
            return await cq.answer(f"✅ OK: {res}", show_alert=True)
        except Exception as e:  # noqa: BLE001
            return await cq.answer(f"❌ {e}"[:180], show_alert=True)

    if d.startswith("api:tg:"):
        pid = int(d.split(":")[2])
        run("UPDATE providers SET active=1-active WHERE id=?", (pid,))
        return await admin_router(cq, f"api:v:{pid}")

    if d.startswith("api:def:"):
        pid = int(d.split(":")[2])
        run("UPDATE providers SET is_default=0")
        run("UPDATE providers SET is_default=1, active=1 WHERE id=?", (pid,))
        return await admin_router(cq, f"api:v:{pid}")

    if d.startswith("api:del:"):
        pid = int(d.split(":")[2])
        run("DELETE FROM services WHERE provider_id=?", (pid,))
        run("DELETE FROM providers WHERE id=?", (pid,))
        audit("WARN", uid, "provider_delete", pid)
        return await admin_router(cq, "api:list")

    if d.startswith("api:edit:"):
        pid = int(d.split(":")[2])
        set_state(uid, "adm_api_edit", pid=pid)
        return await render(cq, "✏️ Send: <code>Name | URL | APIKEY</code>", akb([], f"adm:api:v:{pid}"))

    if d.startswith("api:prio:"):
        pid = int(d.split(":")[2])
        set_state(uid, "adm_api_prio", pid=pid)
        return await render(cq, "🔢 Send priority number (lower = higher priority):", akb([], f"adm:api:v:{pid}"))

    # ---------------- services / categories ----------------
    if d == "svc:home":
        total = one("SELECT COUNT(*) c FROM services")["c"]
        hidden = one("SELECT COUNT(*) c FROM services WHERE hidden=1")["c"]
        kb = [[InlineKeyboardButton("🔎 Search service", callback_data="adm:svc:search")],
              [InlineKeyboardButton("💹 Set profit %", callback_data="adm:set:edit:profit_percent")],
              [InlineKeyboardButton("💱 Set USD rate", callback_data="adm:set:edit:usd_rate")],
              [InlineKeyboardButton("🔄 Sync all", callback_data="adm:api:syncall")]]
        return await render(cq, f"🧾 <b>Services</b>\n\nTotal: <b>{total}</b>\nHidden: <b>{hidden}</b>\n"
                                f"Profit: <b>{SF('profit_percent')}%</b>\nUSD rate: <b>{SF('usd_rate')}</b>", akb(kb))

    if d == "svc:search":
        set_state(uid, "adm_svc_search")
        return await render(cq, "🔎 Send part of a service name:", akb([], "adm:svc:home"))

    if d.startswith("svc:v:"):
        sid = int(d.split(":")[2])
        s = one("SELECT * FROM services WHERE id=?", (sid,))
        if not s:
            return await cq.answer("Not found.", show_alert=True)
        kb = [[InlineKeyboardButton("👁 Show" if s["hidden"] else "🙈 Hide", callback_data=f"adm:svc:tg:{sid}")],
              [InlineKeyboardButton("💵 Custom price", callback_data=f"adm:svc:price:{sid}")]]
        return await render(cq, f"🧾 <b>{clean(s['name'],150)}</b>\n\n🆔 {s['service_id']}\n📂 {clean(s['raw_category'],60)}\n"
                                f"💵 Sell: {cur(sell_price(s))}/1000\n🏷 Cost: {s['rate']}\n"
                                f"📉 {s['min_qty']} – 📈 {s['max_qty']}\n🙈 Hidden: {bool(s['hidden'])}",
                            akb(kb, "adm:svc:home"))

    if d.startswith("svc:tg:"):
        sid = int(d.split(":")[2])
        run("UPDATE services SET hidden=1-hidden WHERE id=?", (sid,))
        return await admin_router(cq, f"svc:v:{sid}")

    if d.startswith("svc:price:"):
        sid = int(d.split(":")[2])
        set_state(uid, "adm_svc_price", sid=sid)
        return await render(cq, "💵 Send custom price per 1000 (0 = auto):", akb([], f"adm:svc:v:{sid}"))

    if d == "cat:list":
        rows = q("SELECT * FROM categories ORDER BY sort ASC")
        kb = [[InlineKeyboardButton(f"{'🙈' if c['hidden'] else '👁'} {c['icon']} {c['name']}",
                                    callback_data=f"adm:cat:v:{c['id']}")] for c in rows]
        kb.append([InlineKeyboardButton("➕ Add category", callback_data="adm:cat:add")])
        return await render(cq, "🗂 <b>Categories</b>", akb(kb))

    if d == "cat:add":
        set_state(uid, "adm_cat_add")
        return await render(cq, "➕ Send: <code>Name | icon | sort | keyword1,keyword2</code>",
                            akb([], "adm:cat:list"))

    if d.startswith("cat:v:"):
        cid = int(d.split(":")[2])
        c = one("SELECT * FROM categories WHERE id=?", (cid,))
        n = one("SELECT COUNT(*) c FROM services WHERE category_id=?", (cid,))["c"]
        kb = [[InlineKeyboardButton("👁 Show" if c["hidden"] else "🙈 Hide", callback_data=f"adm:cat:tg:{cid}"),
               InlineKeyboardButton("✏️ Edit", callback_data=f"adm:cat:edit:{cid}")],
              [InlineKeyboardButton("🗑 Delete", callback_data=f"adm:cat:del:{cid}")]]
        return await render(cq, f"🗂 <b>{c['icon']} {c['name']}</b>\n\nServices: {n}\nSort: {c['sort']}\n"
                                f"Keywords: <code>{clean(c['keywords'],200)}</code>", akb(kb, "adm:cat:list"))

    if d.startswith("cat:tg:"):
        cid = int(d.split(":")[2])
        run("UPDATE categories SET hidden=1-hidden WHERE id=?", (cid,))
        return await admin_router(cq, f"cat:v:{cid}")

    if d.startswith("cat:edit:"):
        cid = int(d.split(":")[2])
        set_state(uid, "adm_cat_edit", cid=cid)
        return await render(cq, "✏️ Send: <code>Name | icon | sort | keywords</code>", akb([], f"adm:cat:v:{cid}"))

    if d.startswith("cat:del:"):
        cid = int(d.split(":")[2])
        run("DELETE FROM categories WHERE id=?", (cid,))
        return await admin_router(cq, "cat:list")

    # ---------------- payment methods ----------------
    if d == "pm:list":
        rows = q("SELECT * FROM payment_methods ORDER BY sort ASC")
        kb = [[InlineKeyboardButton(f"{'✅' if p['active'] else '⛔️'} {p['icon']} {p['name']}",
                                    callback_data=f"adm:pm:v:{p['id']}")] for p in rows]
        kb.append([InlineKeyboardButton("➕ Add method", callback_data="adm:pm:add")])
        kb.append([InlineKeyboardButton(("⛔️ Disable deposits" if SB("deposit_enabled", True)
                                         else "✅ Enable deposits"), callback_data="adm:pm:gate")])
        return await render(cq, "🏦 <b>Payment Methods</b>", akb(kb))

    if d == "pm:gate":
        set_setting("deposit_enabled", "0" if SB("deposit_enabled", True) else "1")
        return await admin_router(cq, "pm:list")

    if d == "pm:add":
        set_state(uid, "adm_pm_add")
        return await render(cq, "➕ Send: <code>Name | icon | address | instructions | min | max</code>",
                            akb([], "adm:pm:list"))

    if d.startswith("pm:v:"):
        pid = int(d.split(":")[2])
        p = one("SELECT * FROM payment_methods WHERE id=?", (pid,))
        kb = [[InlineKeyboardButton("⛔️ Disable" if p["active"] else "✅ Enable", callback_data=f"adm:pm:tg:{pid}"),
               InlineKeyboardButton("✏️ Edit", callback_data=f"adm:pm:edit:{pid}")],
              [InlineKeyboardButton("🗑 Delete", callback_data=f"adm:pm:del:{pid}")]]
        return await render(cq, f"🏦 <b>{p['icon']} {p['name']}</b>\n\n📮 <code>{clean(p['address'],200)}</code>\n"
                                f"📖 {clean(p['instructions'],400)}\n💵 {cur(p['min_amount'])} – {cur(p['max_amount'])}\n"
                                f"📊 Active: {bool(p['active'])}", akb(kb, "adm:pm:list"))

    if d.startswith("pm:tg:"):
        pid = int(d.split(":")[2])
        run("UPDATE payment_methods SET active=1-active WHERE id=?", (pid,))
        return await admin_router(cq, f"pm:v:{pid}")

    if d.startswith("pm:edit:"):
        pid = int(d.split(":")[2])
        set_state(uid, "adm_pm_edit", pid=pid)
        return await render(cq, "✏️ Send: <code>Name | icon | address | instructions | min | max</code>",
                            akb([], f"adm:pm:v:{pid}"))

    if d.startswith("pm:del:"):
        pid = int(d.split(":")[2])
        run("DELETE FROM payment_methods WHERE id=?", (pid,))
        return await admin_router(cq, "pm:list")

    # ---------------- coupons ----------------
    if d == "cpn:list":
        rows = q("SELECT * FROM coupons ORDER BY id DESC")
        kb = [[InlineKeyboardButton(f"{'✅' if c['active'] else '⛔️'} {c['code']} • {c['percent']}% • "
                                    f"{c['used']}/{c['max_uses']}", callback_data=f"adm:cpn:v:{c['id']}")]
              for c in rows]
        kb.append([InlineKeyboardButton("➕ Add coupon", callback_data="adm:cpn:add")])
        return await render(cq, "🎟 <b>Coupons</b>", akb(kb))

    if d == "cpn:add":
        set_state(uid, "adm_cpn_add")
        return await render(cq, "➕ Send: <code>CODE | percent | max_uses | min_deposit | days_valid</code>",
                            akb([], "adm:cpn:list"))

    if d.startswith("cpn:v:"):
        cid = int(d.split(":")[2])
        c = one("SELECT * FROM coupons WHERE id=?", (cid,))
        exp = datetime.utcfromtimestamp(c["expires"]).strftime("%Y-%m-%d") if c["expires"] else "never"
        kb = [[InlineKeyboardButton("⛔️ Disable" if c["active"] else "✅ Enable", callback_data=f"adm:cpn:tg:{cid}"),
               InlineKeyboardButton("🗑 Delete", callback_data=f"adm:cpn:del:{cid}")]]
        return await render(cq, f"🎟 <b>{c['code']}</b>\n\n💯 {c['percent']}%\n👥 {c['used']}/{c['max_uses']}\n"
                                f"💵 min deposit {cur(c['min_deposit'])}\n📅 expires {exp}", akb(kb, "adm:cpn:list"))

    if d.startswith("cpn:tg:"):
        cid = int(d.split(":")[2])
        run("UPDATE coupons SET active=1-active WHERE id=?", (cid,))
        return await admin_router(cq, f"cpn:v:{cid}")

    if d.startswith("cpn:del:"):
        cid = int(d.split(":")[2])
        run("DELETE FROM coupons WHERE id=?", (cid,))
        return await admin_router(cq, "cpn:list")

    # ---------------- tickets ----------------
    if d.startswith("tk:"):
        page = int(d.split(":")[1])
        rows = q("SELECT * FROM tickets ORDER BY (status='open') DESC, id DESC")
        chunk = rows[page * per:(page + 1) * per]
        kb = [[InlineKeyboardButton(f"#{t['id']} {t['status']} • {clean(t['subject'],28)}",
                                    callback_data=f"adm:tkv:{t['id']}")] for t in chunk]
        kb += pager("adm:tk:", page, len(rows), per, "adm:home")
        return await render(cq, f"📞 <b>Tickets</b> — {len(rows)}", InlineKeyboardMarkup(kb))

    if d.startswith("tkv:"):
        tid = int(d.split(":")[1])
        t = one("SELECT * FROM tickets WHERE id=?", (tid,))
        msgs = q("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id ASC LIMIT 20", (tid,))
        body = "\n\n".join(f"<b>{msg['sender']}</b>: {clean(msg['body'],400)}" for msg in msgs)
        kb = [[InlineKeyboardButton("✍️ Reply", callback_data=f"adm:tkr:{tid}"),
               InlineKeyboardButton("🔒 Close" if t["status"] != "closed" else "🔓 Reopen",
                                    callback_data=f"adm:tkc:{tid}")]]
        return await render(cq, f"📞 <b>Ticket #{tid}</b> • 👤 <code>{t['user_id']}</code> • {t['status']}\n\n{body}",
                            akb(kb, "adm:tk:0"))

    if d.startswith("tkr:"):
        tid = int(d.split(":")[1])
        set_state(uid, "adm_ticket_reply", tid=tid)
        return await render(cq, "✍️ Send your reply:", akb([], f"adm:tkv:{tid}"))

    if d.startswith("tkc:"):
        tid = int(d.split(":")[1])
        t = one("SELECT * FROM tickets WHERE id=?", (tid,))
        new = "open" if t["status"] == "closed" else "closed"
        run("UPDATE tickets SET status=?, updated=? WHERE id=?", (new, now_ts(), tid))
        if new == "closed":
            await notify(t["user_id"], T("ticket_closed", ulang(t["user_id"]), id=tid))
        return await admin_router(cq, f"tkv:{tid}")

    # ---------------- broadcast ----------------
    if d == "bc:start":
        set_state(uid, "adm_broadcast")
        return await render(cq, "📢 Send the broadcast content now.\n\n"
                                "Text, photo, video, animation, audio, voice, document, poll "
                                "or forward any message — it will be copied to all users.", akb([]))

    # ---------------- texts ----------------
    if d.startswith("txt:") and d.split(":")[1].isdigit():
        page = int(d.split(":")[1])
        rows = q("SELECT key, lang FROM texts ORDER BY key ASC, lang ASC")
        chunk = rows[page * per:(page + 1) * per]
        kb = [[InlineKeyboardButton(f"✏️ {r['key']} [{r['lang']}]",
                                    callback_data=f"adm:txt:e:{r['lang']}:{r['key']}")] for r in chunk]
        kb += pager("adm:txt:", page, len(rows), per, "adm:home")
        return await render(cq, "✏️ <b>Text Customization</b>\n\nEvery bot message is editable here.\n"
                                "Placeholders like <code>{balance}</code> must be kept.",
                            InlineKeyboardMarkup(kb))

    if d.startswith("txt:e:"):
        _, _, lng, key = d.split(":", 3)
        set_state(uid, "adm_text_edit", key=key, lng=lng)
        current = T(key, lng)
        return await render(cq, f"✏️ <b>{key}</b> [{lng}]\n\nCurrent:\n<code>{clean(current, 1500)}</code>\n\n"
                                f"Send the new text:", akb([], "adm:txt:0"))

    # ---------------- buttons / menu customizer ----------------
    if d == "btn:list":
        rows = q("SELECT * FROM buttons ORDER BY row ASC, sort ASC")
        kb = [[InlineKeyboardButton(f"{'👁' if b['visible'] else '🙈'}{'' if b['enabled'] else '⛔️'} "
                                    f"{b['emoji']} {b['label']}", callback_data=f"adm:btn:v:{b['key']}")]
              for b in rows]
        kb.append([InlineKeyboardButton("➕ Add button", callback_data="adm:btn:add")])
        return await render(cq, "🎛 <b>Menu Customizer</b>\n\nRename, re-emoji, reposition, hide or disable "
                                "any main-menu button.", akb(kb))

    if d == "btn:add":
        set_state(uid, "adm_btn_add")
        return await render(cq, "➕ Send: <code>key | label | emoji | row | sort | callback_or_url_target</code>\n\n"
                                "Example: <code>promo | Promotions | 🔥 | 6 | 10 | info:about</code>",
                            akb([], "adm:btn:list"))

    if d.startswith("btn:v:"):
        key = d.split(":", 2)[2]
        b = one("SELECT * FROM buttons WHERE key=?", (key,))
        if not b:
            return await cq.answer("Not found.", show_alert=True)
        kb = [[InlineKeyboardButton("🙈 Hide" if b["visible"] else "👁 Show", callback_data=f"adm:btn:tg:{key}"),
               InlineKeyboardButton("⛔️ Disable" if b["enabled"] else "✅ Enable", callback_data=f"adm:btn:en:{key}")],
              [InlineKeyboardButton("✏️ Edit label/emoji/position", callback_data=f"adm:btn:e:{key}")],
              [InlineKeyboardButton("🗑 Delete", callback_data=f"adm:btn:del:{key}")]]
        return await render(cq, f"🎛 <b>{b['emoji']} {b['label']}</b>\n\nkey: <code>{b['key']}</code>\n"
                                f"row: {b['row']} | sort: {b['sort']}\ntarget: <code>{b['target']}</code>\n"
                                f"visible: {bool(b['visible'])} | enabled: {bool(b['enabled'])}",
                            akb(kb, "adm:btn:list"))

    if d.startswith("btn:tg:"):
        key = d.split(":", 2)[2]
        run("UPDATE buttons SET visible=1-visible WHERE key=?", (key,))
        return await admin_router(cq, f"btn:v:{key}")

    if d.startswith("btn:en:"):
        key = d.split(":", 2)[2]
        run("UPDATE buttons SET enabled=1-enabled WHERE key=?", (key,))
        return await admin_router(cq, f"btn:v:{key}")

    if d.startswith("btn:del:"):
        key = d.split(":", 2)[2]
        run("DELETE FROM buttons WHERE key=?", (key,))
        return await admin_router(cq, "btn:list")

    if d.startswith("btn:e:"):
        key = d.split(":", 2)[2]
        set_state(uid, "adm_btn_edit", key=key)
        return await render(cq, "✏️ Send: <code>label | emoji | row | sort | target</code>",
                            akb([], f"adm:btn:v:{key}"))

    # ---------------- settings ----------------
    if d.startswith("set:") and d.split(":")[1].isdigit():
        page = int(d.split(":")[1])
        rows = q("SELECT * FROM settings WHERE key NOT LIKE 'user_coupon_%' ORDER BY key ASC")
        chunk = rows[page * per:(page + 1) * per]
        kb = [[InlineKeyboardButton(f"⚙️ {r['key']} = {str(r['value'])[:18]}",
                                    callback_data=f"adm:set:edit:{r['key']}")] for r in chunk]
        kb += pager("adm:set:", page, len(rows), per, "adm:home")
        return await render(cq, "⚙️ <b>Settings</b>\n\nEverything is editable without touching the code.",
                            InlineKeyboardMarkup(kb))

    if d.startswith("set:edit:"):
        key = d.split(":", 2)[2]
        set_state(uid, "adm_set_edit", key=key)
        return await render(cq, f"⚙️ <b>{key}</b>\n\nCurrent: <code>{clean(S(key), 300)}</code>\n\nSend the new value:",
                            akb([], "adm:set:0"))

    return await cq.answer()


async def admin_input(m: Message, st: dict):
    """Handles all admin FSM text input."""
    uid = m.from_user.id
    a = st["a"]
    body = (m.text or m.caption or "").strip()

    if a == "adm_broadcast":
        pop_state(uid)
        users = q("SELECT user_id FROM users WHERE banned=0")
        status = await m.reply_text(f"📢 Broadcasting to {len(users)} users…")
        ok = fail = 0
        for i, x in enumerate(users, 1):
            try:
                await m.copy(x["user_id"])
                ok += 1
            except FloodWait as e:
                await asyncio.sleep(int(e.value) + 1)
                try:
                    await m.copy(x["user_id"])
                    ok += 1
                except RPCError:
                    fail += 1
            except RPCError:
                fail += 1
            if i % 25 == 0:
                try:
                    await status.edit_text(f"📢 Progress: {i}/{len(users)}\n✅ {ok} | ❌ {fail}")
                except RPCError:
                    pass
                await asyncio.sleep(0.5)
        audit("INFO", uid, "broadcast", f"{ok} ok / {fail} fail")
        return await status.edit_text(f"📢 <b>Broadcast complete</b>\n✅ Delivered: {ok}\n❌ Failed: {fail}")

    pop_state(uid)

    if a == "adm_fj_add":
        parts = [x.strip() for x in body.split("|")]
        ident = parts[0].lstrip("@") if parts else ""
        if not ident:
            return await m.reply_text("⚠️ Format: <code>@username | Title | invite link</code>")
        title = parts[1] if len(parts) > 1 and parts[1] else ident
        link = parts[2] if len(parts) > 2 else ""
        if ident.lstrip("-").isdigit() and not link:
            return await m.reply_text("⚠️ Private channels need an invite link.\n"
                                      "<code>-1001234567890 | VIP | https://t.me/+abc</code>")
        nxt = (one("SELECT COALESCE(MAX(sort),0)+10 s FROM force_channels") or {}).get("s") or 10
        run("""INSERT INTO force_channels(chat_id, title, invite_link, active, sort, added)
               VALUES(?,?,?,1,?,?)""", (ident[:80], title[:60], link[:200], nxt, now_ts()))
        audit("INFO", uid, "force_channel_add", ident)
        return await m.reply_text(f"✅ Channel added: <b>{clean(title, 60)}</b>\n"
                                  "⚠️ Make sure the bot is an admin in that channel.")

    if a in ("adm_fj_edit", "adm_fj_title", "adm_fj_link", "adm_fj_sort"):
        cid = st["cid"]
        if a == "adm_fj_edit":
            run("UPDATE force_channels SET chat_id=? WHERE id=?", (body.strip().lstrip("@")[:80], cid))
        elif a == "adm_fj_title":
            run("UPDATE force_channels SET title=? WHERE id=?", (body.strip()[:60], cid))
        elif a == "adm_fj_link":
            val = "" if body.strip() == "-" else body.strip()[:200]
            run("UPDATE force_channels SET invite_link=? WHERE id=?", (val, cid))
        else:
            if not body.strip().lstrip("-").isdigit():
                return await m.reply_text("⚠️ Send a number.")
            run("UPDATE force_channels SET sort=? WHERE id=?", (int(body.strip()), cid))
        audit("INFO", uid, "force_channel_edit", f"{cid} {a}")
        return await m.reply_text("✅ Updated.", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Open channel", callback_data=f"adm:fj:ch:{cid}")]]))

    if a == "adm_user_search":
        target = body.lstrip("@")
        x = (get_user(int(target)) if target.isdigit()
             else one("SELECT * FROM users WHERE username=? COLLATE NOCASE", (target,)))
        if not x:
            return await m.reply_text("❌ User not found.")
        return await m.reply_text(f"👤 Found <code>{x['user_id']}</code>",
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("Open", callback_data=f"adm:user:{x['user_id']}")]]))

    if a == "adm_balance":
        v = valid_amount(body, 0.0001)
        if v is None:
            return await m.reply_text("⚠️ Invalid amount.")
        amount = v if st["mode"] == "add" else -v
        bal = add_balance(st["tid"], amount, "admin", f"by admin {uid}")
        audit("WARN", uid, "balance_change", f"{st['tid']} {amount}")
        await notify(st["tid"], f"{'➕' if amount > 0 else '➖'} <b>{cur(abs(amount))}</b> "
                                f"{'added to' if amount > 0 else 'removed from'} your wallet.\n"
                                f"💰 Balance: <b>{cur(bal)}</b>")
        return await m.reply_text(f"✅ Done. New balance: {cur(bal)}")

    if a == "adm_umsg":
        await notify(st["tid"], f"📩 <b>Message from admin</b>\n\n{clean(body, 3000)}")
        return await m.reply_text("✅ Sent.")

    if a == "adm_dep_reject":
        did = st["did"]
        x = one("SELECT * FROM deposits WHERE id=? AND status='pending'", (did,))
        if not x:
            return await m.reply_text("Already handled.")
        run("UPDATE deposits SET status='rejected', handled=?, admin_id=? WHERE id=?", (now_ts(), uid, did))
        await notify(x["user_id"], T("deposit_rejected", ulang(x["user_id"]), id=did, reason=clean(body, 200)))
        audit("WARN", uid, "deposit_rejected", f"#{did}")
        return await m.reply_text("✅ Rejected.")

    if a in ("adm_api_add", "adm_api_edit"):
        parts = [p.strip() for p in body.split("|")]
        if len(parts) != 3 or not parts[1].startswith("http"):
            return await m.reply_text("⚠️ Format: <code>Name | URL | APIKEY</code>")
        if a == "adm_api_add":
            pid = run("""INSERT INTO providers(name, url, api_key, active, priority, is_default, added)
                         VALUES(?,?,?,1,100,?,?)""",
                      (parts[0][:60], parts[1], parts[2],
                       0 if one("SELECT id FROM providers WHERE is_default=1") else 1, now_ts()))
        else:
            pid = st["pid"]
            run("UPDATE providers SET name=?, url=?, api_key=? WHERE id=?", (parts[0][:60], parts[1], parts[2], pid))
        await m.reply_text("🔄 Saved. Syncing services…")
        n, err = await asyncio.get_event_loop().run_in_executor(None, sync_provider, pid)
        return await m.reply_text(f"✅ Provider saved. Services imported: <b>{n}</b>" if not err else f"⚠️ {err}",
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("Open provider", callback_data=f"adm:api:v:{pid}")]]))

    if a == "adm_api_prio":
        v = valid_amount(body, 0, 100000)
        if v is None:
            return await m.reply_text("⚠️ Invalid number.")
        run("UPDATE providers SET priority=? WHERE id=?", (int(v), st["pid"]))
        return await m.reply_text("✅ Priority updated.")

    if a == "adm_svc_search":
        rows = q("SELECT * FROM services WHERE name LIKE ? ORDER BY name LIMIT 15", (f"%{body[:40]}%",))
        if not rows:
            return await m.reply_text("❌ No services found.")
        kb = [[InlineKeyboardButton(f"{cur(sell_price(s))} • {s['name'][:40]}",
                                    callback_data=f"adm:svc:v:{s['id']}")] for s in rows]
        return await m.reply_text(f"🔎 {len(rows)} results", reply_markup=InlineKeyboardMarkup(kb))

    if a == "adm_svc_price":
        v = valid_amount(body, 0)
        if v is None:
            return await m.reply_text("⚠️ Invalid price.")
        run("UPDATE services SET custom_price=? WHERE id=?", (v, st["sid"]))
        return await m.reply_text("✅ Price updated.")

    if a in ("adm_cat_add", "adm_cat_edit"):
        p = [x.strip() for x in body.split("|")]
        while len(p) < 4:
            p.append("")
        sort = int(valid_amount(p[2], 0, 100000) or 100)
        if a == "adm_cat_add":
            run("INSERT OR IGNORE INTO categories(name, icon, sort, keywords) VALUES(?,?,?,?)",
                (p[0][:40], p[1][:6], sort, p[3][:300]))
        else:
            run("UPDATE categories SET name=?, icon=?, sort=?, keywords=? WHERE id=?",
                (p[0][:40], p[1][:6], sort, p[3][:300], st["cid"]))
        return await m.reply_text("✅ Category saved.")

    if a in ("adm_pm_add", "adm_pm_edit"):
        p = [x.strip() for x in body.split("|")]
        if len(p) < 6:
            return await m.reply_text("⚠️ Format: <code>Name | icon | address | instructions | min | max</code>")
        mn = valid_amount(p[4], 0) or 1
        mx = valid_amount(p[5], 0) or 100000
        if a == "adm_pm_add":
            run("""INSERT INTO payment_methods(name,icon,address,instructions,min_amount,max_amount,active,sort)
                   VALUES(?,?,?,?,?,?,1,100)""", (p[0][:40], p[1][:6], p[2][:200], p[3][:800], mn, mx))
        else:
            run("""UPDATE payment_methods SET name=?, icon=?, address=?, instructions=?, min_amount=?, max_amount=?
                   WHERE id=?""", (p[0][:40], p[1][:6], p[2][:200], p[3][:800], mn, mx, st["pid"]))
        return await m.reply_text("✅ Payment method saved.")

    if a == "adm_cpn_add":
        p = [x.strip() for x in body.split("|")]
        if len(p) < 5:
            return await m.reply_text("⚠️ Format: <code>CODE | percent | max_uses | min_deposit | days_valid</code>")
        days = int(valid_amount(p[4], 0, 3650) or 0)
        run("""INSERT OR REPLACE INTO coupons(code, percent, max_uses, used, min_deposit, expires, active, created)
               VALUES(?,?,?,0,?,?,1,?)""",
            (p[0].upper()[:32], valid_amount(p[1], 0, 100) or 0, int(valid_amount(p[2], 1, 10 ** 6) or 1),
             valid_amount(p[3], 0) or 0, now_ts() + days * 86400 if days else 0, now_ts()))
        return await m.reply_text("✅ Coupon created.")

    if a == "adm_ticket_reply":
        tid = st["tid"]
        t = one("SELECT * FROM tickets WHERE id=?", (tid,))
        run("INSERT INTO ticket_messages(ticket_id, sender, body, created) VALUES(?,?,?,?)",
            (tid, "admin", clean(body, 3000), now_ts()))
        run("UPDATE tickets SET status='answered', updated=? WHERE id=?", (now_ts(), tid))
        await notify(t["user_id"], T("ticket_reply", ulang(t["user_id"]), id=tid, body=clean(body, 3000)))
        return await m.reply_text("✅ Reply sent.")

    if a == "adm_text_edit":
        run("""INSERT INTO texts(key, lang, value) VALUES(?,?,?)
               ON CONFLICT(key, lang) DO UPDATE SET value=excluded.value""", (st["key"], st["lng"], body[:4000]))
        audit("INFO", uid, "text_edit", f"{st['key']}[{st['lng']}]")
        return await m.reply_text("✅ Text updated.")

    if a in ("adm_btn_add", "adm_btn_edit"):
        p = [x.strip() for x in body.split("|")]
        if a == "adm_btn_add":
            if len(p) < 6:
                return await m.reply_text("⚠️ Format: <code>key | label | emoji | row | sort | target</code>")
            run("""INSERT OR REPLACE INTO buttons(key,label,emoji,row,sort,visible,enabled,target)
                   VALUES(?,?,?,?,?,1,1,?)""",
                (re.sub(r"\W+", "_", p[0])[:30], p[1][:40], p[2][:6],
                 int(valid_amount(p[3], 0, 50) or 0), int(valid_amount(p[4], 0, 10000) or 100), p[5][:60]))
        else:
            if len(p) < 5:
                return await m.reply_text("⚠️ Format: <code>label | emoji | row | sort | target</code>")
            run("UPDATE buttons SET label=?, emoji=?, row=?, sort=?, target=? WHERE key=?",
                (p[0][:40], p[1][:6], int(valid_amount(p[2], 0, 50) or 0),
                 int(valid_amount(p[3], 0, 10000) or 100), p[4][:60], st["key"]))
        return await m.reply_text("✅ Button saved.")

    if a == "adm_set_edit":
        set_setting(st["key"], body[:1000])
        audit("INFO", uid, "setting_edit", st["key"])
        return await m.reply_text(f"✅ <code>{st['key']}</code> updated.")

    return await m.reply_text("✅ Done.", reply_markup=main_menu(uid))


# =====================================================================
# BACKGROUND WORKERS (status polling, auto refund, service sync)
# =====================================================================
PENDING = ("pending", "processing", "in progress", "inprogress", "active", "queue", "partial")


def poll_single(oid: int) -> None:
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    if not o or not o["provider_order"]:
        return
    api = provider_client(o["provider_id"])
    if not api:
        return
    try:
        info = api.status(o["provider_order"])
    except Exception as e:  # noqa: BLE001
        audit("WARN", 0, "status_error", f"#{oid}: {e}")
        return
    if isinstance(info, dict) and not info.get("error"):
        apply_status(o, info)


def poll_orders() -> int:
    updated = 0
    rows = q("""SELECT * FROM orders WHERE provider_order != '' AND LOWER(status) IN
                ('pending','processing','in progress','inprogress','active','queue','partial')
                ORDER BY id ASC LIMIT 300""")
    for o in rows:
        api = provider_client(o["provider_id"])
        if not api:
            continue
        try:
            info = api.status(o["provider_order"])
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(info, dict) or info.get("error"):
            continue
        old = o["status"]
        new, refunded = apply_status(o, info)
        if new != old:
            updated += 1
            PENDING_NOTIFY.append((o["user_id"], o["id"], new, refunded))
    return updated


PENDING_NOTIFY: list = []


async def worker_status():
    while True:
        try:
            await asyncio.get_event_loop().run_in_executor(None, poll_orders)
            while PENDING_NOTIFY:
                uid, oid, status, refunded = PENDING_NOTIFY.pop(0)
                await notify(uid, T("notify_status", ulang(uid), id=oid, status=status))
                if refunded:
                    await notify(uid, T("notify_refund", ulang(uid), id=oid, amount=cur(refunded)))
        except Exception as e:  # noqa: BLE001
            audit("ERROR", 0, "worker_status", str(e))
        await asyncio.sleep(max(30, SI("status_interval", 180)))


async def worker_sync():
    await asyncio.sleep(20)
    while True:
        try:
            if active_providers():
                await asyncio.get_event_loop().run_in_executor(None, sync_all_providers)
        except Exception as e:  # noqa: BLE001
            audit("ERROR", 0, "worker_sync", str(e))
        await asyncio.sleep(max(600, SI("sync_interval", 21600)))


async def on_startup():
    me = await app.get_me()
    set_setting("bot_username", me.username or "")
    asyncio.create_task(worker_status())
    asyncio.create_task(worker_sync())
    log.info("Bot online as @%s", me.username)
    for oid in OWNER_IDS:
        try:
            await app.send_message(oid, f"✅ <b>{S('bot_name')}</b> is online.\nUse /admin to manage everything.")
        except RPCError:
            continue


def main() -> None:
    init_db()
    if not (API_ID and API_HASH and BOT_TOKEN):
        raise SystemExit("❌ Set API_ID, API_HASH and BOT_TOKEN at the top of this file (or as env vars).")
    if not OWNER_IDS:
        raise SystemExit("❌ Set ADMINS (your Telegram user ID) at the top of this file.")
    app.start()
    app.loop.run_until_complete(on_startup())
    from pyrogram import idle
    idle()
    app.stop()


if __name__ == "__main__":
    main()
