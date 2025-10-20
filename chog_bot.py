# telegram.py
import os
import time
import sqlite3
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Load ENV
BOT_TOKEN = os.getenv("BOT")

# Example wallet address for deposits (replace with your bot's SOL wallet)
DEPOSIT_ADDRESS = "YourSolanaWalletHere"
DUNE_DASHBOARD_URL = "https://dune.com/your-dashboard-link"

# Setup DB (users table)
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    sol_balance REAL DEFAULT 0,
    joined_window TIMESTAMP,
    trading_active INTEGER DEFAULT 0
)
""")
conn.commit()

# ---------------- BOT COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                   (user.id, user.username))
    conn.commit()
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        "This is the Hybrid AI Trading Bot.\n"
        "To begin:\n"
        "1️⃣ Deposit SOL to the address below.\n"
        "2️⃣ Confirm deposit.\n"
        "3️⃣ Join the next 12-hour trading window.\n\n"
        f"💳 Deposit Address:\n`{DEPOSIT_ADDRESS}`",
        parse_mode="Markdown"
    )

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💳 Please deposit SOL to the following address:\n\n`{DEPOSIT_ADDRESS}`\n\n"
        "Once confirmed, your balance will be updated.",
        parse_mode="Markdown"
    )

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📊 View Dashboard", url=DUNE_DASHBOARD_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Here’s the live trading dashboard:", reply_markup=reply_markup)

async def join_window(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    start_time = datetime.utcnow()
    end_time = start_time + timedelta(hours=12)

    cursor.execute("UPDATE users SET trading_active=1, joined_window=? WHERE user_id=?",
                   (start_time, user.id))
    conn.commit()

    await update.message.reply_text(
        f"✅ You’ve joined the trading window!\n"
        f"Start: {start_time} UTC\n"
        f"End: {end_time} UTC\n\n"
        "Profits will be distributed automatically at the end."
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cursor.execute("SELECT sol_balance FROM users WHERE user_id=?", (user.id,))
    row = cursor.fetchone()
    if row:
        await update.message.reply_text(f"💰 Your balance: {row[0]:.4f} SOL")
    else:
        await update.message.reply_text("No account found. Use /start to register.")

# ---------------- MAIN ----------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("deposit", deposit))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("join", join_window))
    app.add_handler(CommandHandler("balance", balance))

    print("🚀 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
