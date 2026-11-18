import sqlite3
import time
import logging
import io
import threading
import qrcode
import os
import asyncio
import random
import string
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from moviepy import TextClip, ColorClip, CompositeVideoClip, AudioFileClip
from gtts import gTTS
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
import libsql_client  # <--- Turso Client Added

# Logging configuration
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- FIXED: Railway Environment Variables ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "9025362287:AAFZ2bN485I7QG_Upu_hy9CCM8mOWqpk68I")
ADMIN_ID = int(os.getenv("ADMIN_ID", 8122669942))

# --- TURSO DATABASE CREDENTIALS ---
TURSO_URL = os.getenv("TURSO_URL", "libsql://mybotdb-gaganllc.aws-ap-south-1.turso.io")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3OTQ5NDc4MjUsImlkIjoiMDFhMWViMzEtM2QwMS03YThlLWJlMWQtOGE1ZjhiNTYyNjc4Iiwia2lkIjoiNTRfWjhvUlpPbUFmTEZuSzRRS1I2dlhMcE5IbzRXQVRDRFFMSW55QkpQUSIsInJpZCI6ImU4YmUwNjA0LTgxZDYtNDU2MC05ODkwLWM3MjkyMDU2NGQ1YiJ9._CTAZghoZEiOvnP8OMyAZZWJj7_eMyjW4Ew12FdPZLJMB1604LqXL5Ge5hkRKblxmrWpYXFE7rkVrn6fB-SDCw")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# ---------------------------------------------------------
# 🎯 INTEGRATED ENGINE: HOOKS & RETENTION ENGINE (yt-script)
# ---------------------------------------------------------
HOOK_FORMULAS = [
    {"type": "Question Hook", "template": "Did you know that {niche_topic} is completely changing how people succeed?"},
    {"type": "Negative/Warning", "template": "Stop doing this in {niche_topic} if you don't want to waste your time!"},
    {"type": "Curiosity/Secret", "template": "This simple {niche_topic} secret will save you 100s of hours."},
    {"type": "Transformation", "template": "How 1 minute of {niche_topic} daily completely changes your perspective."},
    {"type": "Stat/Fact", "template": "95% of people fail at {niche_topic} because they miss this core principle."}
]

def calculate_hook_score(text):
    score = 5.0
    words = text.split()
    if len(words) < 15:
        score += 2.0  
    if any(kw in text.lower() for kw in ["secret", "stop", "never", "proven", "change", "fast"]):
        score += 1.5  
    if "?" in text or "!" in text:
        score += 1.0  
    return min(score, 9.8)

def generate_viral_script_with_agent(niche):
    hook_data = random.choice(HOOK_FORMULAS)
    hook_text = hook_data["template"].format(niche_topic=niche)
    
    body_scripts = {
        "Motivation & Mindset": "Your mind creates your reality. Every obstacle is an invitation to build resilience. Keep pushing.",
        "Tech & AI Gadgets": "AI automation is replacing repetitive work. Leverage these smart workflows to stay ahead of everyone.",
        "Fitness & Gym": "Consistency beats intensity every time. Show up daily, master your routine, and watch the results follow.",
        "Business & Startup": "Focus on solving real problems. Value creation always leads to sustainable authority and high growth."
    }
    
    main_body = body_scripts.get(niche, f"Mastering {niche} requires focus, discipline, and daily execution. Start small and build momentum.")
    cta = f"Follow for more {niche} secrets!"
    
    full_text = f"{hook_text} {main_body} {cta}"
    h_score = calculate_hook_score(hook_text)
    
    return full_text, h_score, hook_data["type"]

def generate_title_and_tags(niche, script_text):
    clean_niche = niche.replace(" ", "")
    first_words = " ".join(script_text.split()[:4])
    
    title = f"{niche} - {first_words}... #shorts"
    if len(title) > 90:
        title = title[:87] + "..."
        
    tags = [niche.lower(), "shorts", "viral", "automation", "ytagent", clean_niche.lower()]
    return title, tags

NICHE_LIST = [
    "Motivation & Mindset", "Tech & AI Gadgets", "Fitness & Gym", "Business & Startup",
    "Personal Finance", "Life Hacks & DIY", "Psychology Facts", "Historical Events",
    "Sci-Fi & Space", "Health & Nutrition", "Cooking & Recipes", "Travel & Adventure",
    "Fashion & Style", "Book Summaries", "Self Improvement", "Cryptocurrency",
    "Gaming Tips", "Car & Supercars", "Filmmaking & Edit", "Luxury Lifestyle",
    "Stoicism Philosophy", "Mythology Stories", "Productivity Hacks", "Coding Tips",
    "English Learning"
]

def get_db():
  return libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_TOKEN)

async def ensure_tables_exist():
  client = get_db()
  await client.execute('''
        CREATE TABLE IF NOT EXISTS payment_configs (
            plan_key TEXT PRIMARY KEY,
            upi_id TEXT,
            qr_image_file_id TEXT
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS connected_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            platform TEXT DEFAULT 'YouTube',
            channel_info TEXT,
            active_mode TEXT DEFAULT 'none',
            selected_niche TEXT DEFAULT 'none',
            bundle_url TEXT DEFAULT 'none',
            custom_prompt TEXT DEFAULT 'none'
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan_name TEXT DEFAULT 'Free Trial',
            buy_date TEXT,
            expire_date TEXT
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS gift_codes (
            code TEXT PRIMARY KEY,
            plan_name TEXT,
            discount_type TEXT,
            discount_value REAL
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS subscription_prices (
            plan_key TEXT PRIMARY KEY,
            price REAL
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS upload_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            slot_1 TEXT DEFAULT '09:00',
            slot_2 TEXT DEFAULT '12:00',
            slot_3 TEXT DEFAULT '15:00',
            slot_4 TEXT DEFAULT '18:00',
            slot_5 TEXT DEFAULT '21:00',
            slot_6 TEXT DEFAULT '23:00'
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS pending_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_key TEXT,
            amount REAL,
            created_at TEXT
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS received_payments (
            utr TEXT PRIMARY KEY,
            raw_text TEXT,
            is_used INTEGER DEFAULT 0,
            received_at TEXT
        )
    ''')
  await client.execute('''
        CREATE TABLE IF NOT EXISTS feature_controls (
            feature_key TEXT PRIMARY KEY,
            is_enabled INTEGER DEFAULT 1
        )
    ''')
  await client.close()

def is_feature_enabled(key):
    try:
        client = get_db()
        res = client.execute("SELECT is_enabled FROM feature_controls WHERE feature_key = ?", (key,))
        client.close()
        row = res.rows if hasattr(res, 'rows') else res
        return (row[0][0] == 1) if row else True
    except:
        return True

def get_payment_config(plan_key):
    client = get_db()
    res = client.execute("SELECT upi_id, qr_image_file_id FROM payment_configs WHERE plan_key = ?", (plan_key,))
    result = res.rows if hasattr(res, 'rows') else res
    
    if result and result[0][0] and result[0][0] != 'your_merchant_upi@paytm':
        client.close()
        return result[0]
    
    res2 = client.execute("SELECT upi_id, qr_image_file_id FROM payment_configs WHERE upi_id != 'your_merchant_upi@paytm' LIMIT 1")
    fallback = res2.rows if hasattr(res2, 'rows') else res2
    client.close()
    
    if fallback:
        return fallback[0]
        
    return ("your_merchant_upi@paytm", None)
    
def save_payment_config(plan_key, upi_id, qr_image_file_id=None):
    client = get_db()
    client.execute('''
        INSERT INTO payment_configs (plan_key, upi_id, qr_image_file_id)
        VALUES (?, ?, ?)
        ON CONFLICT(plan_key) DO UPDATE SET upi_id = excluded.upi_id, qr_image_file_id = COALESCE(excluded.qr_image_file_id, qr_image_file_id)
    ''', (plan_key, upi_id, qr_image_file_id))
    client.close()

def get_main_menu(is_admin=False):
    keyboard = []
    row1 = []
    if is_feature_enabled('profile'): row1.append(InlineKeyboardButton("👤 Profile", callback_data="menu_profile"))
    if is_feature_enabled('channels'): row1.append(InlineKeyboardButton("📺 My Channels", callback_data="menu_channels"))
    if row1: keyboard.append(row1)

    row2 = []
    if is_feature_enabled('status'): row2.append(InlineKeyboardButton("📊 Status", callback_data="menu_status"))
    if is_feature_enabled('subscription'): row2.append(InlineKeyboardButton("💎 My Subscription", callback_data="menu_subscription"))
    if row2: keyboard.append(row2)

    row3 = []
    if is_feature_enabled('help'): row3.append(InlineKeyboardButton("❓ Help/Support", callback_data="menu_help"))
    if row3: keyboard.append(row3)

    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="menu_admin")])
        
    return InlineKeyboardMarkup(keyboard)

async def check_user_subscription_active(user_id):
    client = get_db()
    res = client.execute("SELECT expire_date FROM subscriptions WHERE user_id = ?", (user_id,))
    client.close()
    row = res.rows if hasattr(res, 'rows') else res
    
    if not row:
        return False
        
    exp_str = row[0][0]
    try:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
        if datetime.now() <= exp_date:
            return True
    except:
        pass
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID)
    
    client = get_db()
    res = client.execute("SELECT user_id FROM subscriptions WHERE user_id = ?", (user.id,))
    rows = res.rows if hasattr(res, 'rows') else res
    if not rows:
        buy_d = datetime.now().strftime("%Y-%m-%d")
        exp_d = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        client.execute("INSERT INTO subscriptions (user_id, plan_name, buy_date, expire_date) VALUES (?, ?, ?, ?)", 
                       (user.id, "Free Trial", buy_d, exp_d))
    client.close()
    
    welcome_text = (
        f"👋 Welcome to **Blinkeyes Automation Bot**, {user.first_name}!\n\n"
        "Aap apne YouTube channels ko connect karke automated videos schedule aur publish kar sakte hain."
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=get_main_menu(is_admin), parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=get_main_menu(is_admin), parse_mode="Markdown")

async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    client = get_db()
    res = client.execute("SELECT plan_name, buy_date, expire_date FROM subscriptions WHERE user_id = ?", (user.id,))
    client.close()
    sub_rows = res.rows if hasattr(res, 'rows') else res
    sub = sub_rows[0] if sub_rows else None
    
    plan_name = sub[0] if sub else "Free Trial"
    buy_date = sub[1] if sub else "N/A"
    expire_date = sub[2] if sub else "N/A"
    
    text = (
        f"👤 **User Profile:**\n\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"👤 **Name:** {user.full_name}\n"
        f"💎 **Active Plan:** {plan_name}\n"
        f"📅 **Buy Date:** {buy_date}\n"
        f"⏳ **Expire Date:** {expire_date}\n"
    )
    keyboard = [
        [InlineKeyboardButton("💳 Buy / Upgrade Subscription", callback_data="sub_plans")],
        [InlineKeyboardButton("« Back to Home", callback_data="back_home")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def subscription_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    client = get_db()
    res = client.execute("SELECT plan_name, buy_date, expire_date FROM subscriptions WHERE user_id = ?", (user.id,))
    client.close()
    sub_rows = res.rows if hasattr(res, 'rows') else res
    sub = sub_rows[0] if sub_rows else None
    
    plan_name = sub[0] if sub else "Free Trial"
    buy_date = sub[1] if sub else "N/A"
    expire_date = sub[2] if sub else "N/A"
    
    text = (
        f"💎 **Your Subscription Status:**\n\n"
        f"📦 **Current Plan:** `{plan_name}`\n"
        f"📅 **Activation Date:** {buy_date}\n"
        f"⏳ **Expiry Date:** {expire_date}\n\n"
        "Aap yahan se apna plan upgrade ya renew kar sakte hain:"
    )
    keyboard = [
        [InlineKeyboardButton("💳 Upgrade / Buy Plan", callback_data="sub_plans")],
        [InlineKeyboardButton("« Back to Home", callback_data="back_home")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def sub_plans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    client = get_db()
    res = client.execute("SELECT plan_key, price FROM subscription_prices")
    client.close()
    price_rows = res.rows if hasattr(res, 'rows') else res
    prices = {row[0]: row[1] for row in price_rows}
    
    p_s99 = prices.get("silver_99", 99)
    p_s499 = prices.get("silver_499", 499)
    p_g249 = prices.get("gold_249", 249)
    p_g1299 = prices.get("gold_1299", 1299)
    p_p399 = prices.get("platinum_399", 399)
    p_p2199 = prices.get("platinum_2199", 2199)
    
    text = (
        "💳 **Choose Your Subscription Plan & Duration:**\n\n"
        "🔹 **Silver Plan** (1 Channel - 3 Reels/day)\n"
        "🔸 **Gold Plan** (4 Channels - 6 Reels/day)\n"
        "💎 **Platinum Plan** (8 Channels - 10 Reels/day)\n\n"
        "Kripya niche diye gaye plan me se apna duration select karein:"
    )
    keyboard = [
        [InlineKeyboardButton(f"🥈 Silver ₹{p_s99} (1M)", callback_data="pay_silver_99"),
         InlineKeyboardButton(f"🥈 Silver ₹{p_s499} (6M)", callback_data="pay_silver_499")],
        [InlineKeyboardButton(f"🥇 Gold ₹{p_g249} (1M)", callback_data="pay_gold_249"),
         InlineKeyboardButton(f"🥇 Gold ₹{p_g1299} (6M)", callback_data="pay_gold_1299")],
        [InlineKeyboardButton(f"💎 Platinum ₹{p_p399} (1M)", callback_data="pay_platinum_399"),
         InlineKeyboardButton(f"💎 Platinum ₹{p_p2199} (6M)", callback_data="pay_platinum_2199")],
        [InlineKeyboardButton("« Back to Profile", callback_data="menu_profile")]
    ]
    
    try:
        await query.message.delete()
    except Exception:
        pass
        
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
   
async def select_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    plan_type = parts[1] 
    duration = parts[2] 
    
    plan_key = f"{plan_type}_{duration}"
    context.user_data['active_plan_key'] = plan_key
    context.user_data['pending_plan_key'] = plan_key 
    
    client = get_db()
    res = client.execute("SELECT price FROM subscription_prices WHERE plan_key = ?", (plan_key,))
    client.close()
    price_rows = res.rows if hasattr(res, 'rows') else res
    row = price_rows[0] if price_rows else None
    
    base_price = row[0] if row else (99 if duration == "99" else 499)
    
    applied_coupon = context.user_data.get('applied_coupon')
    discount_text = ""
    final_price = base_price
    
    if applied_coupon:
        g_code, g_plan, d_type, d_val = applied_coupon
        if g_plan.lower() in plan_type.lower() or g_plan.lower() == "all":
            if d_type == "PERCENT":
                final_price = base_price - (base_price * (d_val / 100))
                discount_text = f"\n🏷️ Coupon Applied: `{g_code}` ({d_val}% OFF)"
            else:
                final_price = max(0, base_price - d_val)
                discount_text = f"\n🏷️ Coupon Applied: `{g_code}` (₹{d_val} OFF)"
                
    context.user_data['final_price'] = final_price
    
    upi_id, qr_file_id = get_payment_config(plan_key)
    if not upi_id or upi_id == 'your_merchant_upi@paytm':
        client = get_db()
        res_fb = client.execute("SELECT upi_id, qr_image_file_id FROM payment_configs WHERE upi_id != 'your_merchant_upi@paytm' LIMIT 1")
        client.close()
        fb_rows = res_fb.rows if hasattr(res_fb, 'rows') else res_fb
        fallback_cfg = fb_rows[0] if fb_rows else None
        if fallback_cfg:
            upi_id = fallback_cfg[0]
            if not qr_file_id:
                qr_file_id = fallback_cfg[1]

    upi_pay_link = f"upi://pay?pa={upi_id}&pn=BlinkeyesAutomation&am={final_price}&cu=INR"

    text = (
        f"💳 **Pay via QR / UPI ({plan_type.upper()} - ₹{final_price})**{discount_text}\n\n"
        f"1. Is QR Code ko apne kisi bhi UPI App se scan karein.\n"
        f"2. Ya phir UPI ID par direct payment karein: `{upi_id}`\n"
        f"3. Payment ke baad **UPI Transaction ID (UTR)** yahan chat mein bhej dein."
    )
    
    keyboard = [
        [InlineKeyboardButton("🎟️ Apply Coupon / Gift Code", callback_data=f"prompt_coupon_{plan_key}")],
        [InlineKeyboardButton("✅ I Have Paid (Submit UTR)", callback_data=f"submit_utr_{plan_key}")],
        [InlineKeyboardButton("« Back to Plans", callback_data="sub_plans")]
    ]
    
    try:
        await query.message.delete()
    except Exception:
        pass

    if qr_file_id:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=qr_file_id,
                caption=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return
        except Exception:
            pass

    try:
        img = qrcode.make(upi_pay_link)
        bio = io.BytesIO()
        img.save(bio, format='PNG')
        bio.seek(0)
        
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=bio,
            caption=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"QR generation error: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text + f"\n\n📌 **UPI ID:** `{upi_id}`",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def prompt_coupon_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['waiting_for_coupon'] = True
    context.user_data['coupon_plan_context'] = query.data.replace("prompt_coupon_", "")
    await query.message.reply_text("🎟️ Kripya apna **Coupon / Gift Code** yahan chat mein type karke bhejein:", parse_mode="Markdown")

async def submit_utr_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    plan_key = f"{parts[2]}_{parts[3]}"
    context.user_data['pending_plan_key'] = plan_key
    context.user_data['waiting_for_channel'] = False 
    context.user_data['waiting_for_auth_code'] = False
    
    await query.message.reply_text(
        "📝 Kripya apni **UPI Transaction ID (UTR)** yahan chat mein type karke bhej dein (jaise: `213456789012`):",
        parse_mode="Markdown"
    )

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SCOPES 
    user = update.effective_user
    text_content = update.message.text.strip() if update.message.text else ""
    
    if context.user_data.get('admin_replying_to_user') and user.id == ADMIN_ID:
        target_user_id = context.user_data.get('admin_replying_to_user')
        reply_content = update.message.text.strip()
        
        try:
            await context.bot.send_message(
                chat_id=int(target_user_id),
                text=f"💬 **Admin Response:**\n\n{reply_content}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ Reply user tak safaltapurvak bhej diya gaya hai!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error sending reply: {e}")
            
        context.user_data.pop('admin_replying_to_user', None)
        return

    if context.user_data.get('waiting_for_support_msg'):
        support_text = update.message.text.strip()
        context.user_data['waiting_for_support_msg'] = False
        
        admin_ticket_msg = (
            f"📨 **New Support Ticket / Message!**\n\n"
            f"👤 User: {user.first_name} (@{user.username})\n"
            f"🆔 User ID: `{user.id}`\n\n"
            f"💬 **Message:**\n{support_text}"
        )
        
        keyboard = [[InlineKeyboardButton("💬 Reply to User", callback_data=f"reply_user_{user.id}")]]
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_ticket_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
        await update.message.reply_text(
            "✅ **Aapka message Admin ke paas bhej diya gaya hai!**\nJald hi admin aapse sampark karenge.",
            parse_mode="Markdown"
        )
        return

    if context.user_data.get('waiting_for_coupon'):
        client = get_db()
        res = client.execute("SELECT plan_name, discount_type, discount_value FROM gift_codes WHERE code = ?", (text_content,))
        client.close()
        g_rows = res.rows if hasattr(res, 'rows') else res
        g_data = g_rows[0] if g_rows else None
        
        if g_data:
            g_plan, d_type, d_val = g_data
            context.user_data['applied_coupon'] = (text_content, g_plan, d_type, d_val)
            await update.message.reply_text(f"🎉 **Coupon Applied Successfully!** Discount added. Dobara plan select karke QR generate karein taaki discounted amount dikhe.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Invalid ya expired coupon code!")
        context.user_data['waiting_for_coupon'] = False
        return

    if context.user_data.get('waiting_for_gift_details') and user.id == ADMIN_ID:
        parts = text_content.split(" ")
        if len(parts) >= 2:
            plan_name = parts[0]
            disc_str = parts[1]
            
            if "%" in disc_str:
                d_type = "PERCENT"
                d_val = float(disc_str.replace("%", ""))
            else:
                d_type = "AMOUNT"
                d_val = float(disc_str.replace("₹", ""))
                
            rand_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
            
            client = get_db()
            client.execute("INSERT OR REPLACE INTO gift_codes (code, plan_name, discount_type, discount_value) VALUES (?, ?, ?, ?)", 
                           (rand_code, plan_name, d_type, d_val))
            client.close()
            
            await update.message.reply_text(
                f"🎁 **Coupon / Gift Code Generated!**\n\n"
                f"📦 Plan: `{plan_name}`\n"
                f"🏷️ Value: `{disc_str}`\n"
                f"🔑 Code: `{rand_code}`",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ Sahi format likhein, jaise: `Silver 20%` ya `Gold 100`")
        context.user_data['waiting_for_gift_details'] = False
        return

    if context.user_data.get('editing_sub_price') and user.id == ADMIN_ID:
        plan_key = context.user_data.get('target_sub_plan')
        try:
            new_price = float(text_content)
            client = get_db()
            client.execute("INSERT OR REPLACE INTO subscription_prices (plan_key, price) VALUES (?, ?)", (plan_key, new_price))
            client.close()
            
            await update.message.reply_text(f"✅ Price for `{plan_key}` updated to `₹{new_price}` successfully!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ Kripya sirf valid digits enter karein (e.g. `199`).")
        context.user_data.pop('editing_sub_price', None)
        context.user_data.pop('target_sub_plan', None)
        return

    if context.user_data.get('editing_slot'):
        slot_num = context.user_data.get('editing_slot')
        ch_id = context.user_data.get('editing_ch_id')
        
        if len(text_content) == 5 and ":" in text_content:
            col_name = f"slot_{slot_num}"
            client = get_db()
            client.execute(f"UPDATE upload_schedules SET {col_name} = ? WHERE user_id = ?", (text_content, user.id))
            client.close()
            
            await update.message.reply_text(f"✅ **Slot {slot_num} updated to {text_content}!**", parse_mode="Markdown")
            context.user_data.pop('editing_slot', None)
            context.user_data.pop('editing_ch_id', None)
            return
        else:
            await update.message.reply_text("⚠️ Invalid time format! Kripya `HH:MM` format mein bhej dein (e.g. `18:00`).")
            return

    if context.user_data.get('waiting_for_auth_code'):
        flow = context.user_data.get('oauth_flow')
        if not flow:
            await update.message.reply_text("❌ Session expired. Kripya dobara 'Connect YouTube' par click karein.")
            context.user_data['waiting_for_auth_code'] = False
            return
            
        try:
            code = text_content
            if "code=" in text_content:
                from urllib.parse import urlparse, parse_qs
                parsed_url = urlparse(text_content)
                query_params = parse_qs(parsed_url.query)
                if 'code' in query_params:
                    code = query_params['code'][0]

            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            token_file_path = f"token_{user.id}.json"
            with open(token_file_path, 'w') as token:
                token.write(credentials.to_json())
                
            channel_title = f"YouTube Channel ({user.first_name})"
            try:
                SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
                creds = Credentials.from_authorized_user_file(token_file_path, SCOPES)
                youtube = build('youtube', 'v3', credentials=creds)
                channels_response = youtube.channels().list(mine=True, part='snippet').execute()
                if channels_response.get('items'):
                    channel_title = channels_response['items'][0]['snippet']['title']
            except Exception as fetch_err:
                logging.error(f"Error fetching channel name: {fetch_err}")

            client = get_db()
            res_ex = client.execute(
                "SELECT id FROM connected_channels WHERE user_id = ? AND platform = ? AND channel_info = ?",
                (user.id, "YouTube", channel_title)
            )
            ex_rows = res_ex.rows if hasattr(res_ex, 'rows') else res_ex
            
            if not ex_rows:
                client.execute(
                    "INSERT INTO connected_channels (user_id, platform, channel_info, active_mode) VALUES (?, ?, ?, ?)", 
                    (user.id, "YouTube", channel_title, "none")
                )
            client.close()

            await update.message.reply_text(
                f"🎉 **Success!** Aapka YouTube channel **{channel_title}** safaltapurvak connect ho gaya hai!\n"
                "Ab aap 'My Channels ➔ YouTube Management' mein ise dekh sakte hain.",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Authentication Failed: {e}\nKripya sahi link ya code dobara copy karke bhejein.")
            
        context.user_data['waiting_for_auth_code'] = False
        context.user_data.pop('oauth_flow', None)
        return

    if 'pending_plan_key' in context.user_data:
        plan_key = context.user_data.get('pending_plan_key', 'silver_99')
        utr_input = re.sub(r'\D', '', text_content)
        
        if len(utr_input) != 12:
            await update.message.reply_text("⚠️ Kripya apni sahi **12-digit UPI Transaction ID (UTR)** enter karein:")
            return

        client = get_db()
        res_pay = client.execute("SELECT is_used FROM received_payments WHERE utr = ?", (utr_input,))
        pay_rows = res_pay.rows if hasattr(res_pay, 'rows') else res_pay
        payment_record = pay_rows[0] if pay_rows else None
        
        if payment_record and payment_record[0] == 0:
            client.execute("UPDATE received_payments SET is_used = 1 WHERE utr = ?", (utr_input,))
            
            duration_days = 180 if any(x in plan_key for x in ["499", "1299", "2199"]) else 30
            plan_name = plan_key.replace("_", " ").title()
            buy_d = datetime.now().strftime("%Y-%m-%d")
            exp_d = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d")
            
            client.execute(
                "INSERT OR REPLACE INTO subscriptions (user_id, plan_name, buy_date, expire_date) VALUES (?, ?, ?, ?)", 
                (user.id, plan_name, buy_d, exp_d)
            )
            client.close()
            
            context.user_data.pop('pending_plan_key', None)
            await update.message.reply_text(
                f"✅ **Payment Successful & Verified!**\n\n"
                f"🎉 Aapka **{plan_name}** subscription automatically activate kar diya gaya hai!\n"
                f"🧾 UTR: `{utr_input}`\n"
                f"📅 Valid Upto: `{exp_d}`",
                parse_mode="Markdown"
            )
            return

        client.close()
        admin_msg = (
            f"🔔 **Manual UTR Check Needed!**\n\n"
            f"👤 User: {user.first_name} (`{user.id}`)\n"
            f"📦 Plan: `{plan_key}`\n"
            f"💳 UTR: `{utr_input}`"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Approve & Activate", callback_data=f"approve_{user.id}_{plan_key}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")]
        ]
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        await update.message.reply_text("⏳ Aapki UTR verify ki ja rahi hai. Payment confirm hote hi subscription activate ho jayegi!")
        context.user_data.pop('pending_plan_key', None)
        return

async def channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    client = get_db()
    res = client.execute("SELECT id, channel_info, platform FROM connected_channels WHERE user_id = ?", (user.id,))
    client.close()
    ch_rows = res.rows if hasattr(res, 'rows') else res
    
    text = "📺 **Connected Channels & Pages:**\n\nAap apne YouTube channels aur Instagram pages yahan manage kar sakte hain:\n\n"
    keyboard = [
        [InlineKeyboardButton("📺 YouTube Management", callback_data="yt_manage")],
        [InlineKeyboardButton("📸 Instagram Management", callback_data="ig_manage")],
        [InlineKeyboardButton("🔗 Connect YouTube (OAuth)", callback_data="auth_youtube")],
        [InlineKeyboardButton("➕ Add New Channel / Page", callback_data="add_account")]
    ]
    
    if ch_rows:
        text += "**Aapke Connected Channels:**\n"
        for ch in ch_rows:
            c_id, c_info, c_plat = ch[0], ch[1], ch[2]
            text += f"• {c_plat}: `{c_info}`\n"
            keyboard.append([InlineKeyboardButton(f"🗑️ Remove {c_info}", callback_data=f"remove_chan_{c_id}")])
            
    keyboard.append([InlineKeyboardButton("« Back to Home", callback_data="back_home")])
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def remove_user_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    ch_id = int(query.data.split("_")[2])
    client = get_db()
    client.execute("DELETE FROM connected_channels WHERE id = ?", (ch_id,))
    client.close()
    
    await query.answer("Channel removed successfully!", show_alert=True)
    await channels_callback(update, context)

async def prompt_add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['waiting_for_channel'] = True
    context.user_data.pop('pending_plan_key', None)
    context.user_data.pop('waiting_for_auth_code', None)
    
    keyboard = [[InlineKeyboardButton("« Back to Channels", callback_data="menu_channels")]]
    await query.message.edit_text(
        "➕ **Add New Channel / Page:**\n\n"
        "Kripya apne **YouTube Channel ka link** ya **Instagram Page link** yahan chat mein type karke bhej dein:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def start_youtube_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        SCOPES = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly"
        ]
        
        from google_auth_oauthlib.flow import Flow
        
        flow = Flow.from_client_secrets_file(
            'client_secret.json',
            scopes=SCOPES,
            redirect_uri='http://localhost/'
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        context.user_data['oauth_flow'] = flow
        context.user_data['waiting_for_auth_code'] = True
        context.user_data.pop('pending_plan_key', None)
        context.user_data.pop('waiting_for_channel_name', None)
        
        keyboard = [
            [InlineKeyboardButton("🔗 1. Login & Get Code", url=authorization_url)],
            [InlineKeyboardButton("« Back to Channels", callback_data="menu_channels")]
        ]
        
        text = (
            "📺 **YouTube Account Authentication:**\n\n"
            "1. Upar diye gaye button par click karke apne YouTube/Google account se login karein.\n"
            "2. Access allow karne ke baad blank/error page ka URL link copy karein.\n"
            "3. Us link ko yahan chat mein bhej dein!"
        )
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    except Exception as e:
        await query.message.edit_text(f"❌ Error generating auth link: {e}")

async def channel_management_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    
    platform_db = "Instagram" if "ig" in query.data else "YouTube"
    
    client = get_db()
    res = client.execute("SELECT id, channel_info, active_mode, selected_niche FROM connected_channels WHERE user_id = ? AND platform = ?", (user.id, platform_db))
    client.close()
    channels = res.rows if hasattr(res, 'rows') else res
    
    text = f"📺 **{platform_db} Management:**\n\nSelect a channel/page below to manage its modes & settings:\n\n"
    keyboard = []
    
    if channels:
        for ch in channels:
            ch_id, ch_info, mode_val, niche_val = ch[0], ch[1], ch[2], ch[3]
            mode_text = mode_val.upper() if mode_val else "NONE"
            niche_text = niche_val if niche_val else "None"
            
            if mode_val == 'ai' and niche_val and niche_val != 'none':
                text += f"• 🆔 **{ch_info}**\n  ┗ Mode: `{mode_text}` | Niche: `{niche_text}`\n\n"
            else:
                text += f"• 🆔 **{ch_info}**\n  ┗ Mode: `{mode_text}`\n\n"
                
            keyboard.append([InlineKeyboardButton(f"⚙️ {ch_info}", callback_data=f"select_ch_{ch_id}_{platform_db}")])
    else:
        text += f"Abhi koi {platform_db} account connected nahi hai.\n\n"
        
    if platform_db == "YouTube":
        keyboard.append([InlineKeyboardButton("🔗 Connect YouTube (OAuth)", callback_data="auth_youtube")])
        
    keyboard.append([InlineKeyboardButton("« Back to Channels", callback_data="menu_channels")])
    keyboard.append([InlineKeyboardButton("« Back to Home", callback_data="back_home")])
    
    try:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception:
        pass

async def show_specific_channel_modes(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int):
    query = update.callback_query
    user = update.effective_user
    
    client = get_db()
    res = client.execute("SELECT id, channel_info, active_mode, selected_niche, platform FROM connected_channels WHERE id = ? AND user_id = ?", (channel_id, user.id))
    client.close()
    ch_rows = res.rows if hasattr(res, 'rows') else res
    ch = ch_rows[0] if ch_rows else None
    
    if not ch:
        await query.answer("Channel not found!", show_alert=True)
        return

    ch_id, ch_info, active_mode, selected_niche, platform = ch
    mode_text = active_mode.upper() if active_mode else "NONE"
    
    if active_mode == 'ai' and selected_niche and selected_niche != 'none':
        niche_display = f"  ┗ Mode: `{mode_text}` | Niche: `{selected_niche}`"
    else:
        niche_display = f"  ┗ Mode: `{mode_text}`"

    text = (
        f"📺 **{platform} Management & Modes:**\n\n"
        f"• 🆔 **{ch_info}**\n"
        f"{niche_display}"
    )
  
    btn1 = "🟢 1. Auto Post (Send Link)" if active_mode == 'link' else "⚪ 1. Auto Post (Send Link)"
    btn2 = "🟢 2. AI Automation (11 Agents/25 Niches)" if active_mode == 'ai' else "⚪ 2. AI Automation (11 Agents/25 Niches)"
    btn3 = "🟢 3. Connect Video Bundle" if active_mode == 'bundle' else "⚪ 3. Connect Video Bundle"

    back_callback = "yt_manage" if platform == "YouTube" else "ig_manage"

    keyboard = []
    
    if is_feature_enabled('mode_autopost'):
        keyboard.append([InlineKeyboardButton(btn1, callback_data=f"setmode_link_{ch_id}")])
    if is_feature_enabled('mode_aiauto'):
        keyboard.append([InlineKeyboardButton(btn2, callback_data=f"show_niches_{ch_id}")])
    if is_feature_enabled('mode_bundle'):
        keyboard.append([InlineKeyboardButton(btn3, callback_data=f"setmode_bundle_{ch_id}")])
    if is_feature_enabled('mode_schedule'):
        keyboard.append([InlineKeyboardButton("⏰ Schedule Slots (Max 6)", callback_data=f"ch_schedule_{ch_id}")])
        
    keyboard.append([InlineKeyboardButton("« Back to Channels", callback_data=back_callback)])
    keyboard.append([InlineKeyboardButton("« Back to Home", callback_data="back_home")])
    
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_channel_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    ch_id = int(data[2])
    context.user_data['active_channel_id'] = ch_id
    await show_specific_channel_modes(update, context, ch_id)

async def show_niche_dropdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    ch_id = int(data[2])
    context.user_data['active_channel_id'] = ch_id
    
    keyboard = []
    for i in range(0, len(NICHE_LIST), 2):
        row = [InlineKeyboardButton(NICHE_LIST[i], callback_data=f"pickniche_{i}_{ch_id}")]
        if i + 1 < len(NICHE_LIST):
            row.append(InlineKeyboardButton(NICHE_LIST[i+1], callback_data=f"pickniche_{i+1}_{ch_id}"))
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("« Back to Management", callback_data=f"select_ch_{ch_id}_YouTube")])
    
    await query.message.edit_text("🎯 **Select Your AI Video Niche (25 Preset Options):**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_mode_niche_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action = data[0]
    
    client = get_db()
    
    if action == "setmode":
        mode = data[1]
        ch_id = int(data[2])
        client.execute("UPDATE connected_channels SET active_mode = ? WHERE id = ?", (mode, ch_id))
        client.close()
        await query.answer(f"Mode changed to: {mode.upper()}")
        await show_specific_channel_modes(update, context, ch_id)
        
    elif action == "pickniche":
        niche_idx = int(data[1])
        ch_id = int(data[2])
        selected_niche = NICHE_LIST[niche_idx]
        client.execute("UPDATE connected_channels SET active_mode = 'ai', selected_niche = ? WHERE id = ?", (selected_niche, ch_id))
        client.close()
        await query.answer(f"AI Niche set to: {selected_niche}")
        await show_specific_channel_modes(update, context, ch_id)

async def channel_schedule_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    ch_id = int(data[2])
    context.user_data['active_channel_id'] = ch_id
    
    client = get_db()
    res = client.execute("SELECT slot_1, slot_2, slot_3, slot_4, slot_5, slot_6 FROM upload_schedules WHERE user_id = ?", (update.effective_user.id,))
    sched_rows = res.rows if hasattr(res, 'rows') else res
    row = sched_rows[0] if sched_rows else None
    
    if not row:
        client.execute("INSERT INTO upload_schedules (user_id) VALUES (?)", (update.effective_user.id,))
        slots = ['09:00', '12:00', '15:00', '18:00', '21:00', '23:00']
    else:
        slots = list(row)
    client.close()
    
    active_count = sum(1 for s in slots if s and s.strip() != "" and s != "None")
    
    text = (
        "⏰ **Channel Upload Schedule Manager (Max 6 Slots):**\n\n"
        f"📊 **Active Slots:** `{active_count}/6`\n\n"
        f"1️⃣ Slot 1: `{slots[0] or 'Not Set'}`\n"
        f"2️⃣ Slot 2: `{slots[1] or 'Not Set'}`\n"
        f"3️⃣ Slot 3: `{slots[2] or 'Not Set'}`\n"
        f"4️⃣ Slot 4: `{slots[3] or 'Not Set'}`\n"
        f"5️⃣ Slot 5: `{slots[4] or 'Not Set'}`\n"
        f"6️⃣ Slot 6: `{slots[5] or 'Not Set'}`\n\n"
        "Niche kisi slot par click karke use Edit ya Delete karein:"
    )
    
    keyboard = []
    for idx, s_time in enumerate(slots, start=1):
        time_display = s_time if (s_time and s_time != "None") else "Disabled"
        keyboard.append([
            InlineKeyboardButton(f"⚙️ Slot {idx} ({time_display})", callback_data=f"manage_slot_{idx}_{ch_id}"),
            InlineKeyboardButton("❌ Delete", callback_data=f"del_slot_{idx}_{ch_id}")
        ])
        
    keyboard.append([InlineKeyboardButton("« Back to Channel Modes", callback_data=f"select_ch_{ch_id}_YouTube")])
    
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def manage_slot_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    slot_num = int(data[2])
    ch_id = int(data[3])
    
    context.user_data['editing_slot'] = slot_num
    context.user_data['editing_ch_id'] = ch_id
    
    await query.message.reply_text(
        f"✏️ **Edit Slot {slot_num}:**\n\n"
        "Kripya naya time **24-hour format** (HH:MM) mein chat mein bhej dein.\n"
        "*(Example: `14:30` ya `09:15`)*",
        parse_mode="Markdown"
    )

async def delete_slot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    slot_num = int(data[2])
    ch_id = int(data[3])
    
    col_name = f"slot_{slot_num}"
    client = get_db()
    client.execute(f"UPDATE upload_schedules SET {col_name} = 'None' WHERE user_id = ?", (update.effective_user.id,))
    client.close()
    
    await query.answer(f"Slot {slot_num} deleted!", show_alert=True)
    await channel_schedule_menu(update, context)

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    client = get_db()
    
    res_c = client.execute("SELECT COUNT(*) FROM connected_channels WHERE user_id = ?", (user_id,))
    c_rows = res_c.rows if hasattr(res, 'rows') else res_c
    active_channels_count = c_rows[0][0] if c_rows else 0
    
    res_s = client.execute("SELECT slot_1, slot_2, slot_3, slot_4, slot_5, slot_6 FROM upload_schedules WHERE user_id = ?", (user_id,))
    s_rows = res_s.rows if hasattr(res, 'rows') else res_s
    row = s_rows[0] if s_rows else None
    
    client.close()
    
    pending_slots = 0
    if row:
        pending_slots = sum(1 for s in row if s and s.strip() != "" and s != "None")
        
    text = (
        "📊 **System Status Logs:**\n\n"
        f"• **Active Channels:** `{active_channels_count}`\n"
        f"• **Scheduled Pending Slots:** `{pending_slots}`\n"
        f"• **AI Agents Engine:** `Active (Background)`\n\n"
        "✅ System running smoothly in background!"
    )
    
    keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="back_home")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def help_support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = "❓ **Help & Support Center:**\n\nKripya niche diye gaye option ko chunen:"
    keyboard = [
        [InlineKeyboardButton("📖 Guide & Tutorial", callback_data="view_guide")],
        [InlineKeyboardButton("💬 Contact Support", callback_data="send_support")],
        [InlineKeyboardButton("« Back to Home", callback_data="back_home")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def guide_tutorial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "📖 **Guide & Tutorial:**\n\n1. Pehle 'Connect YouTube' se apna channel auth karein.\n2. Uske baad mode select karein ( jaise Auto Post ya AI Automation ).\n3. Schedule slots mein time set karein, bot automated videos upload karta rahega."
    keyboard = [[InlineKeyboardButton("« Back to Help", callback_data="menu_help")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def contact_support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['waiting_for_support_msg'] = True
    
    text = (
        "💬 **Contact Support:**\n\n"
        "Kripya apni samasya (problem) ya query yahan chat mein type karke bhej dein. "
        "Aapka message seedha Admin ke paas bhej diya jayega!"
    )
    keyboard = [[InlineKeyboardButton("« Back to Help", callback_data="menu_help")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_reply_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        return
        
    user_id_to_reply = query.data.replace("reply_user_", "")
    context.user_data['admin_replying_to_user'] = user_id_to_reply
    
    await query.message.reply_text(
        f"✍️ Kripya User (`{user_id_to_reply}`) ke liye apna reply message yahan type karke bhejein:",
        parse_mode="Markdown"
    )

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.answer("⚠️ Aapke paas admin access nahi hai!", show_alert=True)
        return

    text = (
        "⚙️ **Admin Control Panel:**\n\n"
        "Yahan se aap saare users, subscriptions aur user menu buttons ko **On / Off** control kar sakte hain:"
    )
    
    client = get_db()
    res = client.execute("SELECT feature_key, is_enabled FROM feature_controls")
    client.close()
    feat_rows = res.rows if hasattr(res, 'rows') else res
    controls = {row[0]: row[1] for row in feat_rows}

    def status_icon(key):
        return "🟢 ON" if controls.get(key, 1) == 1 else "🔴 OFF"

    keyboard = [
        [InlineKeyboardButton("👥 View All Users", callback_data="admin_users")],
        [InlineKeyboardButton("🎁 Generate Gift Code", callback_data="admin_gen_gift")],
        [InlineKeyboardButton("💳 Manage Subscriptions", callback_data="admin_subs")],
        [InlineKeyboardButton("⚙️ Set Payment QR", callback_data="admin_set_qr")],
        [InlineKeyboardButton("📨 Support Tickets", callback_data="admin_tickets")],
        [InlineKeyboardButton(f"Profile: {status_icon('profile')}", callback_data="toggle_feat_profile"),
         InlineKeyboardButton(f"Channels: {status_icon('channels')}", callback_data="toggle_feat_channels")],
        [InlineKeyboardButton(f"Status: {status_icon('status')}", callback_data="toggle_feat_status"),
         InlineKeyboardButton(f"Subscription: {status_icon('subscription')}", callback_data="toggle_feat_subscription")],
        [InlineKeyboardButton(f"Help: {status_icon('help')}", callback_data="toggle_feat_help")],
        [InlineKeyboardButton("--- Channel Mode Controls ---", callback_data="ignore")],
        [InlineKeyboardButton(f"1. Auto Post: {status_icon('mode_autopost')}", callback_data="toggle_feat_mode_autopost")],
        [InlineKeyboardButton(f"2. AI Automation: {status_icon('mode_aiauto')}", callback_data="toggle_feat_mode_aiauto")],
        [InlineKeyboardButton(f"3. Video Bundle: {status_icon('mode_bundle')}", callback_data="toggle_feat_mode_bundle")],
        [InlineKeyboardButton(f"4. Schedule Slots: {status_icon('mode_schedule')}", callback_data="toggle_feat_mode_schedule")],
        [InlineKeyboardButton("« Back to Home", callback_data="back_home")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def toggle_feature_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        return

    feat_key = query.data.replace("toggle_feat_", "")
    if feat_key == "ignore":
        return
    
    client = get_db()
    res = client.execute("SELECT is_enabled FROM feature_controls WHERE feature_key = ?", (feat_key,))
    f_rows = res.rows if hasattr(res, 'rows') else res
    row = f_rows[0] if f_rows else None
    
    current_status = row[0] if row else 1
    new_status = 0 if current_status == 1 else 1
    
    client.execute("INSERT OR REPLACE INTO feature_controls (feature_key, is_enabled) VALUES (?, ?)", (feat_key, new_status))
    client.close()
    
    await admin_panel_callback(update, context)

async def admin_sub_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "admin_users":
        client = get_db()
        res = client.execute("SELECT user_id, plan_name, buy_date, expire_date FROM subscriptions")
        client.close()
        users = res.rows if hasattr(res, 'rows') else res
        
        text = "👥 **All Registered Users & Activity:**\n\n"
        if users:
            for u in users:
                u_id, u_plan, u_buy, u_exp = u[0], u[1], u[2], u[3]
                text += f"🆔 ID: `{u_id}`\n💎 Plan: {u_plan}\n🛒 Bought: {u_buy}\n⏳ Expires: {u_exp}\n\n"
        else:
            text += "Koi user registered nahi hai."
            
        keyboard = [[InlineKeyboardButton("« Back to Admin Panel", callback_data="menu_admin")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
        
    elif data == "admin_gen_gift":
        context.user_data['waiting_for_gift_details'] = True
        text = (
            "🎁 **Generate Gift / Coupon Code:**\n\n"
            "Kripya chat mein **Plan Name** aur **Discount** type karke bhejein.\n"
            "*(Example: `Silver 20%` ya `Gold 100`)*"
        )
        keyboard = [[InlineKeyboardButton("« Back to Admin Panel", callback_data="menu_admin")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
        
    elif data == "admin_subs":
        text = "💳 **Manage Subscriptions (Edit Prices):**\n\nSelect a plan to update its price:"
        keyboard = [
            [InlineKeyboardButton("🥈 Silver (1 Month)", callback_data="edit_price_silver_99"),
             InlineKeyboardButton("🥈 Silver (6 Months)", callback_data="edit_price_silver_499")],
            [InlineKeyboardButton("🥇 Gold (1 Month)", callback_data="edit_price_gold_249"),
             InlineKeyboardButton("🥇 Gold (6 Months)", callback_data="edit_price_gold_1299")],
            [InlineKeyboardButton("💎 Platinum (1 Month)", callback_data="edit_price_platinum_399"),
             InlineKeyboardButton("💎 Platinum (6 Months)", callback_data="edit_price_platinum_2199")],
            [InlineKeyboardButton("« Back to Admin Panel", callback_data="menu_admin")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
        
    elif data == "admin_set_qr":
        text = (
            "⚙️ **Set Payment QR & UPI:**\n\n"
            "Kisi bhi plan ke liye QR set karne ke liye yeh command use karein:\n"
            "`/setqr [plan_key] [upi_id]`\n\n"
            "Example: `/setqr silver_99 myupi@paytm`"
        )
    elif data == "admin_tickets":
        text = "📨 **Support Tickets:**\n\nKoi ticket pending nahi hai."
    else:
        text = "⚙️ Feature under development."

    keyboard = [[InlineKeyboardButton("« Back to Admin Panel", callback_data="menu_admin")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def edit_sub_price_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_key = query.data.replace("edit_price_", "")
    
    context.user_data['editing_sub_price'] = True
    context.user_data['target_sub_plan'] = plan_key
    
    await query.message.reply_text(
        f"✏️ **Edit Price for `{plan_key}`:**\n\nKripya naya price amount chat mein bhej dein (e.g. `199`):",
        parse_mode="Markdown"
    )

async def set_qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
        
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ Sahi format use karein:\n`/setqr silver_99 your_upi@okicici`", parse_mode="Markdown")
        return
        
    plan_key = args[0]
    upi_id = args[1]
    
    qr_file_id = None
    if update.message.photo:
        qr_file_id = update.message.photo[-1].file_id
    elif update.message.reply_to_message and update.message.reply_to_message.photo:
        qr_file_id = update.message.reply_to_message.photo[-1].file_id
        
    save_payment_config(plan_key, upi_id, qr_file_id)
    
    await update.message.reply_text(
        f"✅ Success! <b>{plan_key}</b> ke liye UPI (<code>{upi_id}</code>) aur QR code save ho gaya hai!",
        parse_mode="HTML"
    )

async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.answer("⚠️ Aapke paas iska access nahi hai!", show_alert=True)
        return
        
    data = query.data 
    parts = data.split("_")
    action = parts[0]
    user_id = parts[1]
    
    if action == "approve":
        plan_name = parts[2].upper() if len(parts) > 2 else "Premium Plan"
        buy_d = datetime.now().strftime("%Y-%m-%d")
        exp_d = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        
        client = get_db()
        client.execute("INSERT OR REPLACE INTO subscriptions (user_id, plan_name, buy_date, expire_date) VALUES (?, ?, ?, ?)", 
                       (int(user_id), plan_name, buy_d, exp_d))
        client.close()
        
        new_caption = (query.message.caption or "") + "\n\n✅ **Payment Received & Verified! Status: Subscription Activated**"
        try:
            if query.message.photo:
                await query.message.edit_caption(caption=new_caption, parse_mode="Markdown")
            else:
                await query.message.edit_text(new_caption, parse_mode="Markdown")
        except Exception:
            pass
            
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"🎉 **Badhai ho!** Aapka payment receive aur verify ho gaya hai. Aapka **{plan_name}** subscription activate kar diya gaya hai!",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error notifying user: {e}")
            
    elif action == "reject":
        try:
            if query.message.photo:
                await query.message.edit_caption(caption=(query.message.caption or "") + "\n\n❌ **Status: Rejected**", parse_mode="Markdown")
            else:
                await query.message.edit_text(query.message.text + "\n\n❌ **Status: Rejected**", parse_mode="Markdown")
        except:
            pass
            
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ **Payment Rejected:** Aapki UTR / Payment verify nahi ho payi. Kripya sahi UTR ke sath dobara try karein.",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error notifying user: {e}")

async def generate_and_upload_ai_video(bot, user_id, channel_name, niche):
    try:
        if not await check_user_subscription_active(user_id):
            return

        os.makedirs("downloads", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_filename = f"downloads/kling_ai_reel_{user_id}_{timestamp}.mp4"
        audio_filename = f"downloads/kling_audio_{user_id}_{timestamp}.mp3"
        
        full_script, hook_score, hook_type = generate_viral_script_with_agent(niche)
        video_title, video_tags = generate_title_and_tags(niche, full_script)
        
        tts = gTTS(text=full_script, lang='en', slow=False)
        tts.save(audio_filename)
        
        audio_clip = AudioFileClip(audio_filename)
        raw_duration = audio_clip.duration
        video_duration = max(16.0, min(20.0, raw_duration + 3.0))
        
        bg_clip = ColorClip(size=(720, 1280), color=(5, 8, 15), duration=video_duration)
        header_card = ColorClip(size=(640, 140), color=(18, 24, 38), duration=video_duration).with_position(('center', 100))
        
        title_txt = TextClip(text=f"✨ KLING AI CINEMATIC", font_size=32, color="gold", size=(600, 50))
        title_txt = title_txt.with_duration(video_duration).with_position(('center', 115))
        
        niche_txt = TextClip(text=f"Niche: {niche} | AI Model: v2.5", font_size=24, color="deepskyblue", size=(600, 50))
        niche_txt = niche_txt.with_duration(video_duration).with_position(('center', 170))
        
        content_card = ColorClip(size=(640, 600), color=(12, 16, 26), duration=video_duration).with_position(('center', 280))
        script_txt = TextClip(text=f'"{full_script}"', font_size=36, color="white", size=(600, 550))
        script_txt = script_txt.with_duration(video_duration).with_position(('center', 310))
        
        footer_card = ColorClip(size=(640, 100), color=(18, 24, 38), duration=video_duration).with_position(('center', 920))
        footer_txt = TextClip(text=f"🔥 VIRAL HOOK: {hook_type.upper()}", font_size=24, color="springgreen", size=(600, 70))
        footer_txt = footer_txt.with_duration(video_duration).with_position(('center', 935))
        
        video = CompositeVideoClip([
            bg_clip, 
            header_card, title_txt, niche_txt, 
            content_card, script_txt, 
            footer_card, footer_txt
        ])
        video = video.with_audio(audio_clip)
        video.write_videofile(video_filename, fps=30, codec='libx264', audio_codec='aac', logger=None)
        
        audio_clip.close()
        video.close()
        
        token_file = f"token_{user_id}.json"
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            youtube = build('youtube', 'v3', credentials=creds)
            
            body = {
                'snippet': {
                    'title': video_title,
                    'description': f"{full_script}\n\nGenerated via Kling AI Cinematic Engine.\nHook Type: {hook_type}\nHook Score: {hook_score}/10\n\n#shorts #{niche.replace(' ', '')} #klingai #aiart #automation",
                    'tags': video_tags,
                    'categoryId': '22'
                },
                'status': {
                    'privacyStatus': 'public'
                }
            }
            
            media = MediaFileUpload(video_filename, chunksize=-1, resumable=True)
            request = youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                
            await bot.send_message(
                chat_id=user_id,
                text=f"✅ **Kling AI Style Cinematic Video Uploaded!**\n\n📺 Channel: **{channel_name}**\n🎯 Niche: `{niche}`\n🔥 Hook Score: `{hook_score}/10`\n🔗 Video ID: `{response.get('id')}`",
                parse_mode="Markdown"
            )
            
        if os.path.exists(video_filename): os.remove(video_filename)
        if os.path.exists(audio_filename): os.remove(audio_filename)
        
    except Exception as e:
        logging.error(f"Error in Kling AI video generation: {e}")

async def check_and_run_schedules(bot):
    current_time = datetime.now().strftime("%H:%M")
    
    client = get_db()
    res_sch = client.execute("SELECT user_id, slot_1, slot_2, slot_3, slot_4, slot_5, slot_6 FROM upload_schedules")
    schedules = res_sch.rows if hasattr(res, 'rows') else res_sch
    
    for sched in schedules:
        user_id = sched[0]
        active_slots = [sched[1], sched[2], sched[3], sched[4], sched[5], sched[6]]
        
        if current_time in active_slots:
            res_ch = client.execute("SELECT id, platform, channel_info, active_mode, selected_niche FROM connected_channels WHERE user_id = ? AND active_mode != 'none'", (user_id,))
            channels = res_ch.rows if hasattr(res_ch, 'rows') else res_ch
            
            for ch in channels:
                ch_id, platform, ch_name, mode, niche = ch
                if mode == 'ai':
                    await generate_and_upload_ai_video(bot, user_id, ch_name, niche)
                    
    client.close()

async def background_scheduler_loop(bot):
    while True:
        try:
            await check_and_run_schedules(bot)
        except Exception as e:
            logging.error(f"Scheduler Loop Error: {e}")
        await asyncio.sleep(60)

web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Blinkeyes Bot is Alive & Running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

@web_app.route('/webhook/payment', methods=['POST'])
def payment_webhook():
    data = request.json or {}
    if data.get('secret') != "blinkeyes_secure_pay_2026":
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    notif_text = str(data.get('text', ''))
    utr_match = re.search(r'\b\d{12}\b', notif_text)
    
    if utr_match:
        utr_number = utr_match.group(0)
        client = get_db()
        client.execute("INSERT OR IGNORE INTO received_payments (utr, raw_text, is_used, received_at) VALUES (?, ?, 0, ?)",
                       (utr_number, notif_text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        client.close()
        return jsonify({"status": "success", "utr_saved": utr_number}), 200
        
    return jsonify({"status": "ignored", "message": "No 12-digit UTR found"}), 200

def main():
  app = ApplicationBuilder().token(BOT_TOKEN).build()

  app.add_handler(CommandHandler("start", start))
  app.add_handler(CommandHandler("setqr", set_qr_command))

  app.add_handler(CallbackQueryHandler(start, pattern="^back_home$"))
  app.add_handler(CallbackQueryHandler(profile_callback, pattern="^menu_profile$"))
  app.add_handler(CallbackQueryHandler(sub_plans_callback, pattern="^sub_plans$"))
  app.add_handler(
      CallbackQueryHandler(
          subscription_status_menu, pattern="^menu_subscription$"
      )
  )
  app.add_handler(CallbackQueryHandler(status_callback, pattern="^menu_status$"))
  app.add_handler(
      CallbackQueryHandler(help_support_callback, pattern="^menu_help$")
  )
  app.add_handler(
      CallbackQueryHandler(guide_tutorial_callback, pattern="^view_guide$")
  )
  app.add_handler(
      CallbackQueryHandler(contact_support_callback, pattern="^send_support$")
  )
  app.add_handler(
      CallbackQueryHandler(prompt_coupon_handler, pattern="^prompt_coupon_")
  )
  app.add_handler(
      CallbackQueryHandler(channels_callback, pattern="^menu_channels$")
  )

  app.add_handler(
      CallbackQueryHandler(
          select_plan_callback,
          pattern=(
              "^pay_(silver|gold|platinum)_(99|499|249|1299|399|2199)$"
          ),
      )
  )
  app.add_handler(
      CallbackQueryHandler(submit_utr_prompt, pattern="^submit_utr_")
  )

  app.add_handler(
      CallbackQueryHandler(admin_panel_callback, pattern="^menu_admin$")
  )
  app.add_handler(
      CallbackQueryHandler(
          admin_sub_actions,
          pattern="^admin_(users|gen_gift|subs|set_qr|tickets)$",
      )
  )
  app.add_handler(
      CallbackQueryHandler(edit_sub_price_prompt, pattern="^edit_price_")
  )
  app.add_handler(
      CallbackQueryHandler(
          handle_approval_callback, pattern="^(approve|reject)_"
      )
  )
  app.add_handler(
      CallbackQueryHandler(toggle_feature_handler, pattern="^toggle_feat_")
  )
  app.add_handler(
      CallbackQueryHandler(admin_reply_prompt, pattern="^reply_user_")
  )

  app.add_handler(
      CallbackQueryHandler(
          channel_management_callback, pattern="^(yt_manage|ig_manage)$"
      )
  )
  app.add_handler(
      CallbackQueryHandler(handle_channel_selection, pattern="^select_ch_")
  )
  app.add_handler(
      CallbackQueryHandler(show_niche_dropdown, pattern="^show_niches_")
  )
  app.add_handler(
      CallbackQueryHandler(
          handle_mode_niche_pick, pattern="^(setmode|pickniche)_"
      )
  )
  app.add_handler(
      CallbackQueryHandler(channel_schedule_menu, pattern="^ch_schedule_")
  )
  app.add_handler(
      CallbackQueryHandler(manage_slot_options, pattern="^manage_slot_")
  )
  app.add_handler(
      CallbackQueryHandler(delete_slot_handler, pattern="^del_slot_")
  )
  app.add_handler(
      CallbackQueryHandler(remove_user_channel, pattern="^remove_chan_")
  )
  app.add_handler(
      CallbackQueryHandler(prompt_add_account, pattern="^add_account$")
  )
  app.add_handler(
      CallbackQueryHandler(start_youtube_auth, pattern="^auth_youtube$")
  )

  app.add_handler(
      MessageHandler(
          (filters.TEXT | filters.VIDEO | filters.Document.ALL)
          & (~filters.COMMAND),
          handle_text_messages,
      )
  )

  async def post_init(application):
    await ensure_tables_exist()
    asyncio.create_task(background_scheduler_loop(application.bot))

  app.post_init = post_init

  print("🤖 Bot is running smoothly with Turso Cloud DB & Full Feature Controls...")
  app.run_polling()


if __name__ == "__main__":
  threading.Thread(target=run_web, daemon=True).start()

  while True:
    try:
      print("🤖 Bot restarting polling...")
      main()
    except Exception as e:
      print(f"Connection Error: {e}. Reconnecting in 5 seconds...")
      time.sleep(5)
