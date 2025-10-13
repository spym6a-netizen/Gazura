# Додай ці імпорти на початку файлу
import asyncio
import json
import random
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict
from math import ceil

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor

# ========== КОНФИГ ==========
BOT_TOKEN = "8160983444:AAF-qKOw_MtVhFPtnejy3UcbPT59riKrsd8"
XP_PER_LEVEL = 100
INACTIVE_DAYS = 7
DB_PATH = "data.db"
QUESTIONS_PATH = "questions.json"
DAILY_QUESTION_LIMIT = 10

# ТВІЙ ID (дізнайся через @userinfobot в Telegram)
ADMIN_ID = 5672490558  # ← ЗАМІНИ НА СВІЙ РЕАЛЬНИЙ ID
# ============================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# ========== БАЗА ДАННИХ ==========
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ОСНОВНА ТАБЛИЦЯ ГРАВЦІВ
cursor.execute("""
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    role TEXT DEFAULT 'Новачок',
    last_active TEXT,
    animals INTEGER DEFAULT 0,
    tap_boost_level INTEGER DEFAULT 1,
    farm_income INTEGER DEFAULT 0,
    total_taps INTEGER DEFAULT 0
)
""")

# ТВАРИНИ ФЕРМИ
cursor.execute("""
CREATE TABLE IF NOT EXISTS farm_animals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    animal_type TEXT NOT NULL,
    income INTEGER NOT NULL,
    count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

# НЕРУХОМІСТЬ
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_real_estate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    income INTEGER NOT NULL,
    price INTEGER NOT NULL,
    last_collect_time TEXT,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

# ДРУЗІ
cursor.execute("""
CREATE TABLE IF NOT EXISTS friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    friend_id INTEGER NOT NULL,
    friend_username TEXT NOT NULL,
    added_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id),
    UNIQUE(user_id, friend_id)
)
""")

# ПЕРЕКАЗИ
cursor.execute("""
CREATE TABLE IF NOT EXISTS money_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    transfer_date TEXT NOT NULL,
    FOREIGN KEY (from_user_id) REFERENCES players (user_id),
    FOREIGN KEY (to_user_id) REFERENCES players (user_id)
)
""")

# ІНШІ ТАБЛИЦІ
cursor.execute("""
CREATE TABLE IF NOT EXISTS item_roulette_prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    probability REAL NOT NULL,
    item_type TEXT NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    item_price INTEGER NOT NULL,
    obtained_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_date TEXT NOT NULL,
    tasks_completed INTEGER DEFAULT 0,
    spin_roulette_count INTEGER DEFAULT 0,
    tap_count INTEGER DEFAULT 0,
    play_minigames_count INTEGER DEFAULT 0,
    correct_answers_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_income (
    user_id INTEGER PRIMARY KEY,
    total_commission INTEGER DEFAULT 0,
    last_collect_date TEXT,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS quiz_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    correct INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

conn.commit()

# ========== ОНОВЛЕННЯ СТРУКТУРИ ТАБЛИЦЬ ==========
try:
    # Перевіряємо чи є колонка income в user_real_estate
    cursor.execute("PRAGMA table_info(user_real_estate)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'income' not in columns:
        print("🔄 Оновлюємо структуру таблиці user_real_estate...")
        cursor.execute("DROP TABLE IF EXISTS user_real_estate")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_real_estate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            income INTEGER NOT NULL,
            price INTEGER NOT NULL,
            last_collect_time TEXT,
            FOREIGN KEY (user_id) REFERENCES players (user_id)
        )
        """)
        print("✅ Таблицю user_real_estate оновлено!")
    
    conn.commit()
except Exception as e:
    print(f"❌ Помилка оновлення таблиць: {e}")

# ========== КОНСТАНТИ ==========
class ItemRoulettePrizes:
    PRIZES = [
        {"name": "💎 Алмаз", "price": 500, "probability": 0.01, "type": "mineral"},
        {"name": "🪨 Камінь", "price": 7, "probability": 0.15, "type": "mineral"},
        {"name": "⛏️ Залізна руда", "price": 45, "probability": 0.12, "type": "mineral"},
        {"name": "🪙 Золота руда", "price": 120, "probability": 0.08, "type": "mineral"},
        {"name": "🔮 Містичний кристал", "price": 300, "probability": 0.03, "type": "magic"},
        {"name": "📜 Старовинний сувій", "price": 80, "probability": 0.10, "type": "magic"},
        {"name": "🧪 Еліксир сили", "price": 200, "probability": 0.05, "type": "potion"},
        {"name": "🌿 Цілюща трава", "price": 25, "probability": 0.14, "type": "potion"},
        {"name": "⚔️ Меч воїна", "price": 350, "probability": 0.02, "type": "weapon"},
        {"name": "🛡️ Щит захисника", "price": 280, "probability": 0.025, "type": "armor"},
        {"name": "🏹 Лук мисливця", "price": 180, "probability": 0.04, "type": "weapon"},
        {"name": "🔱 Тризуб Посейдона", "price": 450, "probability": 0.015, "type": "artifact"},
        {"name": "📿 Амулет удачі", "price": 150, "probability": 0.06, "type": "artifact"},
        {"name": "💍 Кільце могути", "price": 220, "probability": 0.035, "type": "artifact"},
        {"name": "👑 Корона короля", "price": 480, "probability": 0.008, "type": "artifact"},
        {"name": "🧿 Глаз дракона", "price": 320, "probability": 0.02, "type": "magic"},
        {"name": "🌕 Місячний камінь", "price": 90, "probability": 0.09, "type": "mineral"},
        {"name": "☀️ Сонячний самоцвіт", "price": 110, "probability": 0.07, "type": "mineral"},
        {"name": "⚡ Блискавкова руда", "price": 270, "probability": 0.025, "type": "mineral"},
        {"name": "❄️ Крижаний кристал", "price": 130, "probability": 0.055, "type": "mineral"},
        {"name": "🔥 Вогняна руда", "price": 160, "probability": 0.045, "type": "mineral"},
        {"name": "🌪️ Ураганний перл", "price": 290, "probability": 0.018, "type": "mineral"},
        {"name": "🍯 Золотий мед", "price": 65, "probability": 0.11, "type": "potion"},
        {"name": "🧃 Еліксир молодості", "price": 400, "probability": 0.012, "type": "potion"},
        {"name": "🌰 Магічний жолудь", "price": 35, "probability": 0.13, "type": "magic"},
        {"name": "🍀 Чотирилисник", "price": 75, "probability": 0.085, "type": "artifact"},
        {"name": "🎭 Маска таємниці", "price": 190, "probability": 0.038, "type": "artifact"},
        {"name": "📯 Ріг звіра", "price": 95, "probability": 0.065, "type": "artifact"},
        {"name": "🐉 Луска дракона", "price": 380, "probability": 0.014, "type": "artifact"},
        {"name": "🦅 Перо фенікса", "price": 420, "probability": 0.009, "type": "artifact"},
        {"name": "🐺 Зуб вовкулаки", "price": 140, "probability": 0.05, "type": "artifact"},
        {"name": "🕷️ Павутиння арахніда", "price": 55, "probability": 0.095, "type": "magic"},
        {"name": "🍄 Яскрава поганка", "price": 30, "probability": 0.125, "type": "potion"},
        {"name": "🌺 Екзотична квітка", "price": 70, "probability": 0.088, "type": "potion"},
        {"name": "🎪 Цирковий атрибут", "price": 40, "probability": 0.115, "type": "misc"},
        {"name": "🎲 Зачаровані кістки", "price": 85, "probability": 0.072, "type": "misc"},
        {"name": "🪄 Паличка чародія", "price": 250, "probability": 0.028, "type": "weapon"},
        {"name": "📖 Книга заклять", "price": 170, "probability": 0.042, "type": "magic"},
        {"name": "⚗️ Алхімічна колба", "price": 120, "probability": 0.058, "type": "potion"},
        {"name": "🔬 Мікроскоп алхіміка", "price": 210, "probability": 0.032, "type": "misc"}
    ]

class PremiumRoulette:
    MULTIPLIERS = [
        {"multiplier": 2, "probability": 0.20, "price": 100},
        {"multiplier": 3, "probability": 0.15, "price": 200},
        {"multiplier": 4, "probability": 0.12, "price": 300},
        {"multiplier": 5, "probability": 0.10, "price": 400},
        {"multiplier": 6, "probability": 0.08, "price": 500},
        {"multiplier": 7, "probability": 0.07, "price": 600},
        {"multiplier": 8, "probability": 0.06, "price": 700},
        {"multiplier": 9, "probability": 0.05, "price": 800},
        {"multiplier": 10, "probability": 0.04, "price": 900},
        {"type": "ticket", "probability": 0.08, "description": "🎫 Білет в звичайну рулетку"},
        {"type": "nothing", "probability": 0.05, "description": "❌ Нічого не виграно"}
    ]

class TapGame:
    BOOST_LEVELS = {
        1: {"income": 1, "price": 0},
        2: {"income": 2, "price": 100},
        3: {"income": 3, "price": 250},
        4: {"income": 4, "price": 500},
        5: {"income": 5, "price": 1000},
        6: {"income": 6, "price": 2000},
        7: {"income": 7, "price": 4000},
        8: {"income": 8, "price": 8000},
        9: {"income": 9, "price": 16000},
        10: {"income": 10, "price": 32000}
    }

class FarmAnimals:
    ANIMALS = [
        {"name": "🐔 Курка", "price": 100, "income": 5, "emoji": "🐔"},
        {"name": "🐄 Корова", "price": 500, "income": 25, "emoji": "🐄"},
        {"name": "🐖 Свиня", "price": 300, "income": 15, "emoji": "🐖"},
        {"name": "🐑 Вівця", "price": 200, "income": 10, "emoji": "🐑"},
        {"name": "🐎 Кінь", "price": 1000, "income": 50, "emoji": "🐎"},
        {"name": "🐫 Верблюд", "price": 2000, "income": 100, "emoji": "🐫"},
        {"name": "🐘 Слон", "price": 5000, "income": 250, "emoji": "🐘"},
        {"name": "🦒 Жирафа", "price": 3000, "income": 150, "emoji": "🦒"},
        {"name": "🐅 Тигр", "price": 8000, "income": 400, "emoji": "🐅"},
        {"name": "🐉 Дракон", "price": 15000, "income": 750, "emoji": "🐉"}
    ]

class RealEstate:
    PROPERTIES = [
        {"name": "🏠 Будинок", "price": 1000, "income": 50},
        {"name": "🏢 Квартира", "price": 500, "income": 25},
        {"name": "🏬 Офіс", "price": 3000, "income": 150},
        {"name": "🏪 Магазин", "price": 2000, "income": 100},
        {"name": "🏨 Готель", "price": 10000, "income": 500},
        {"name": "🏭 Завод", "price": 25000, "income": 1250},
        {"name": "🏛️ Банк", "price": 50000, "income": 2500},
        {"name": "🗼 Вежа", "price": 100000, "income": 5000}
    ]

class DailyTasks:
    TASKS = [
        {"type": "spin_roulette", "target": 2, "reward": 50, "description": "Прокрути рулетку 2 рази"},
        {"type": "tap_count", "target": 100, "reward": 30, "description": "Зроби 100 тапів"},
        {"type": "play_minigames", "target": 3, "reward": 40, "description": "Зіграй 3 рази у міні-ігри"},
        {"type": "correct_answers", "target": 5, "reward": 60, "description": "Дайте 5 правильних відповідей"},
        {"type": "buy_animals", "target": 2, "reward": 80, "description": "Купи 2 тварини"}
    ]

# ========== БАЗОВІ ФУНКЦІЇ ==========
def ensure_player(user_id: int, username: str):
    cursor.execute("SELECT user_id FROM players WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO players (user_id, username, last_active) VALUES (?, ?, ?)",
            (user_id, username, datetime.now().isoformat())
        )
        # Додаємо стартових тварин
        try:
            cursor.execute(
                "INSERT INTO farm_animals (user_id, animal_type, income, count) VALUES (?, ?, ?, ?)",
                (user_id, "🐔 Курка", 5, 1)
            )
        except:
            pass
        conn.commit()

def get_user_coins(user_id: int) -> int:
    cursor.execute("SELECT coins FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def get_user_level(user_id: int) -> int:
    cursor.execute("SELECT level FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 1

def add_user_coins(user_id: int, coins: int):
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (coins, user_id))
    conn.commit()

def get_user_farm_income(user_id: int) -> int:
    cursor.execute("SELECT SUM(income * count) FROM farm_animals WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result and result[0] else 0

def get_user_real_estate_income(user_id: int) -> int:
    cursor.execute("SELECT SUM(income) FROM user_real_estate WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result and result[0] else 0

def get_user_tap_stats(user_id: int) -> Dict:
    cursor.execute("SELECT tap_boost_level, total_taps FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        level, total_taps = result
        income = TapGame.BOOST_LEVELS.get(level, {"income": 1})["income"]
        return {"level": level, "income": income, "total_taps": total_taps}
    return {"level": 1, "income": 1, "total_taps": 0}

def get_total_passive_income(user_id: int) -> int:
    farm_income = get_user_farm_income(user_id)
    estate_income = get_user_real_estate_income(user_id)
    return farm_income + estate_income

def get_user_friends(user_id: int) -> List[Dict]:
    """Отримати список друзів"""
    cursor.execute("SELECT friend_id, friend_username, added_date FROM friends WHERE user_id = ? ORDER BY added_date DESC", (user_id,))
    friends = []
    for friend_id, username, added_date in cursor.fetchall():
        friends.append({
            "user_id": friend_id,
            "username": username,
            "added_date": added_date
        })
    return friends

def add_friend(user_id: int, friend_id: int, friend_username: str):
    """Додати друга"""
    try:
        cursor.execute(
            "INSERT INTO friends (user_id, friend_id, friend_username, added_date) VALUES (?, ?, ?, ?)",
            (user_id, friend_id, friend_username, datetime.now().isoformat())
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # Вже є в друзях

def transfer_money(from_user_id: int, to_user_id: int, amount: int) -> bool:
    """Переказ грошей"""
    if from_user_id == to_user_id:
        return False
    
    from_coins = get_user_coins(from_user_id)
    if from_coins < amount:
        return False
    
    # Комісія 5%
    commission = ceil(amount * 0.05)
    final_amount = amount - commission
    
    # Виконуємо переказ
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (amount, from_user_id))
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (final_amount, to_user_id))
    
    # Записуємо переказ
    cursor.execute(
        "INSERT INTO money_transfers (from_user_id, to_user_id, amount, transfer_date) VALUES (?, ?, ?, ?)",
        (from_user_id, to_user_id, amount, datetime.now().isoformat())
    )
    
    conn.commit()
    return True

# ========== МЕНЮ ==========
def build_main_menu(user_id: int):
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton("🎮 Ігри", callback_data="menu_games"),
        InlineKeyboardButton("👤 Профіль", callback_data="menu_profile"),
        InlineKeyboardButton("💰 Доходи", callback_data="menu_income"),
        InlineKeyboardButton("🏆 Топ гравців", callback_data="menu_leaderboard"),
        InlineKeyboardButton("📋 Завдання", callback_data="daily_tasks"),
        InlineKeyboardButton("🛍️ Магазин", callback_data="menu_shop")
    ]
    
    # Тільки для адміна
    if user_id == ADMIN_ID:
        buttons.append(InlineKeyboardButton("👑 Адмін", callback_data="admin_panel"))
    
    kb.add(*buttons)
    return kb

def build_games_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎯 Вікторина", callback_data="game_quiz"),
        InlineKeyboardButton("👆 Tap Game", callback_data="game_tap"),
        InlineKeyboardButton("🎰 Рулетки", callback_data="menu_roulettes"),
        InlineKeyboardButton("⚔️ PvP Дуель", callback_data="game_pvp"),
        InlineKeyboardButton("🎲 Кістки", callback_data="game_dice"),
        InlineKeyboardButton("🎯 Вгадай число", callback_data="game_guess"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

def build_roulettes_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🎪 Рулетка предметів", callback_data="menu_item_roulette"),
        InlineKeyboardButton("💰 Звичайна рулетка", callback_data="roulette_normal"),
        InlineKeyboardButton("💎 Преміум рулетка", callback_data="roulette_premium"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
    )
    return kb

def build_income_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🐓 Ферма", callback_data="income_farm"),
        InlineKeyboardButton("🏘️ Нерухомість", callback_data="income_real_estate"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

def build_shop_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🐓 Ферма", callback_data="shop_farm"),
        InlineKeyboardButton("🏘️ Нерухомість", callback_data="shop_real_estate"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

def build_friends_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📋 Список друзів", callback_data="friends_list"),
        InlineKeyboardButton("➕ Додати друга", callback_data="friends_add"),
        InlineKeyboardButton("💰 Надіслати гроші", callback_data="friends_transfer"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_profile")
    )
    return kb

# ========== ОБРОБНИКИ КОМАНД ==========
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name
    
    ensure_player(user_id, username)
    cursor.execute("UPDATE players SET last_active = ? WHERE user_id = ?", 
                   (datetime.now().isoformat(), user_id))
    conn.commit()
    
    text = (
        f"🎮 <b>Вітаю, {username}!</b>\n\n"
        f"🚀 <b>Ласкаво просимо до ігрового бота!</b>\n\n"
        f"💫 <b>Оберіть розділ:</b>"
    )
    
    await message.answer(text, reply_markup=build_main_menu(user_id))

# ========== ОСНОВНІ ОБРОБНИКИ МЕНЮ ==========
@dp.callback_query_handler(lambda c: c.data == 'menu_games')
async def cb_menu_games(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🎮 <b>Меню ігор</b>\n\n"
        "Оберіть гру:\n\n"
        "• 🎯 <b>Вікторина</b> - Відповідайте на питання\n"
        "• 👆 <b>Tap Game</b> - Клацайте та заробляйте\n"
        "• 🎰 <b>Рулетки</b> - Вигравайте призи\n"
        "• ⚔️ <b>PvP Дуель</b> - Змагайтесь з гравцями\n"
        "• 🎲 <b>Кістки</b> - Киньте на удачу\n"
        "• 🎯 <b>Вгадай число</b> - Тестуйте інтуїцію"
    )
    await call.message.edit_text(text, reply_markup=build_games_menu())

@dp.callback_query_handler(lambda c: c.data == 'menu_profile')
async def cb_menu_profile(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    cursor.execute("SELECT username, level, xp, coins, role, total_taps FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result:
        username, level, xp, coins, role, total_taps = result
        farm_income = get_user_farm_income(user_id)
        estate_income = get_user_real_estate_income(user_id)
        total_passive = farm_income + estate_income
        tap_stats = get_user_tap_stats(user_id)
        
        text = (
            f"👤 <b>Профіль гравця</b>\n\n"
            f"🆔 <b>Ім'я:</b> {username}\n"
            f"🎯 <b>Рівень:</b> {level}\n"
            f"💎 <b>Монети:</b> {coins} ✯\n"
            f"🎭 <b>Роль:</b> {role}\n"
            f"👆 <b>Тапів:</b> {total_taps}\n\n"
            f"💰 <b>Пасивний дохід:</b>\n"
            f"• 🐓 Ферма: {farm_income} ✯/год\n"
            f"• 🏘️ Нерухомість: {estate_income} ✯/год\n"
            f"• 💰 Всього: {total_passive} ✯/год\n\n"
            f"👆 <b>Tap Game:</b>\n"
            f"• Рівень: {tap_stats['level']}\n"
            f"• Дохід: {tap_stats['income']} ✯/тап"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("👥 Друзі", callback_data="menu_friends"))
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
        await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'menu_income')
async def cb_menu_income(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    farm_income = get_user_farm_income(user_id)
    estate_income = get_user_real_estate_income(user_id)
    total_passive = farm_income + estate_income
    tap_stats = get_user_tap_stats(user_id)
    
    text = (
        f"💰 <b>Система доходів</b>\n\n"
        f"💎 <b>Ваш баланс:</b> {get_user_coins(user_id)} ✯\n\n"
        f"📊 <b>Поточні доходи:</b>\n"
        f"• 👆 Tap Game: {tap_stats['income']} ✯/тап\n"
        f"• 🐓 Ферма: {farm_income} ✯/год\n"
        f"• 🏘️ Нерухомість: {estate_income} ✯/год\n"
        f"• 💰 Всього пасивно: {total_passive} ✯/год\n\n"
        f"🎯 <b>Оберіть розділ для детальнішої інформації:</b>"
    )
    
    await call.message.edit_text(text, reply_markup=build_income_menu())

@dp.callback_query_handler(lambda c: c.data == 'menu_leaderboard')
async def cb_menu_leaderboard(call: types.CallbackQuery):
    await call.answer()
    cursor.execute("SELECT username, level, coins FROM players ORDER BY coins DESC LIMIT 10")
    top_players = cursor.fetchall()
    
    text = "🏆 <b>Топ 10 гравців</b>\n\n"
    
    if top_players:
        for i, (username, level, coins) in enumerate(top_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            text += f"{medal} {username} - {coins} ✯ (рівень {level})\n"
    else:
        text += "📊 Немає даних про гравців\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="menu_leaderboard"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'menu_shop')
async def cb_menu_shop(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🛍️ <b>Магазин</b>\n\n"
        "Оберіть категорію:\n\n"
        "• 🐓 <b>Ферма</b> - Тварини для пасивного доходу\n"
        "• 🏘️ <b>Нерухомість</b> - Об'єкти нерухомості\n\n"
        "💡 <b>Порада:</b> Інвестуйте в пасивний дохід!"
    )
    await call.message.edit_text(text, reply_markup=build_shop_menu())

@dp.callback_query_handler(lambda c: c.data == 'menu_roulettes')
async def cb_menu_roulettes(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🎰 <b>Рулетки</b>\n\n"
        "Оберіть тип рулетки:\n\n"
        "• 🎪 <b>Рулетка предметів</b> - Вигравайте унікальні предмети\n"
        "• 💰 <b>Звичайна рулетка</b> - Вигравайте монети (50 ✯ за спін)\n"
        "• 💎 <b>Преміум рулетка</b> - Великі виграші з множниками"
    )
    await call.message.edit_text(text, reply_markup=build_roulettes_menu())

@dp.callback_query_handler(lambda c: c.data == 'menu_friends')
async def cb_menu_friends(call: types.CallbackQuery):
    await call.answer()
    text = (
        "👥 <b>Система друзів</b>\n\n"
        "📊 <b>Функції:</b>\n"
        "• Додавайте друзів за ID\n"
        "• Надсилайте монети друзям\n"
        "• Переглядайте список друзів\n\n"
        "💡 <b>Порада:</b> ID друга можна дізнатись з його профілю"
    )
    
    await call.message.edit_text(text, reply_markup=build_friends_menu())

@dp.callback_query_handler(lambda c: c.data.startswith('menu_back|'))
async def cb_menu_back(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.full_name
    
    ensure_player(user_id, username)
    
    text = (
        f"🎮 <b>Головне меню</b>\n\n"
        f"💫 <b>Вітаю, {username}!</b>\n\n"
        f"🚀 <b>Оберіть розділ:</b>"
    )
    
    await call.message.edit_text(text, reply_markup=build_main_menu(user_id))

# ========== СИСТЕМА ДРУЗІВ ==========
@dp.callback_query_handler(lambda c: c.data == 'friends_list')
async def cb_friends_list(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    friends = get_user_friends(user_id)
    
    text = "👥 <b>Ваші друзі</b>\n\n"
    
    if friends:
        for i, friend in enumerate(friends, 1):
            text += f"{i}. {friend['username']}\n"
            text += f"   ID: {friend['user_id']}\n\n"
    else:
        text += "❌ У вас ще немає друзів!\n\n"
        text += "💡 Додайте друга за його ID"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Додати друга", callback_data="friends_add"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_friends"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'friends_add')
async def cb_friends_add(call: types.CallbackQuery):
    await call.answer()
    
    text = (
        "➕ <b>Додати друга</b>\n\n"
        "📝 <b>Формат команди:</b>\n"
        "<code>/addfriend ID_друга</code>\n\n"
        "📝 <b>Приклади:</b>\n"
        "<code>/addfriend 123456789</code>\n\n"
        "💡 <b>Як дізнатись ID друга?</b>\n"
        "1. Попросіть друга написати /start боту\n"
        "2. Він побачить свій ID у відповіді\n"
        "3. Або використайте @userinfobot"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📋 Список друзів", callback_data="friends_list"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_friends"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'friends_transfer')
async def cb_friends_transfer(call: types.CallbackQuery):
    await call.answer()
    
    text = (
        "💰 <b>Надіслати гроші другу</b>\n\n"
        "📝 <b>Формат команди:</b>\n"
        "<code>/transfer ID_друга сума</code>\n\n"
        "📝 <b>Приклади:</b>\n"
        "<code>/transfer 123456789 100</code> - надіслати 100 ✯\n"
        "<code>/transfer 123456789 500</code> - надіслати 500 ✯\n\n"
        "⚠️ <b>Увага:</b>\n"
        "• Комісія 5%\n"
        "• Мінімальна сума: 10 ✯\n"
        "• Не можна надсилати собі"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📋 Список друзів", callback_data="friends_list"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_friends"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.message_handler(commands=['addfriend'])
async def cmd_addfriend(message: types.Message):
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Неправильний формат!\nВикористання: /addfriend ID_друга")
            return
        
        friend_id = int(parts[1])
        
        # Перевіряємо чи не додаємо себе
        if friend_id == user_id:
            await message.answer("❌ Не можна додати себе в друзі!")
            return
        
        # Перевіряємо чи існує гравець
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (friend_id,))
        friend_data = cursor.fetchone()
        
        if not friend_data:
            await message.answer("❌ Гравець не знайдений! Попросіть друга написати /start боту.")
            return
        
        friend_username = friend_data[0]
        
        # Додаємо друга
        if add_friend(user_id, friend_id, friend_username):
            await message.answer(f"✅ <b>Друга додано!</b>\n\n👤 {friend_username} тепер у вашому списку друзів!")
        else:
            await message.answer("❌ Цей гравець вже у вашому списку друзів!")
            
    except ValueError:
        await message.answer("❌ Помилка! ID має бути числом.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['transfer'])
async def cmd_transfer(message: types.Message):
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("❌ Неправильний формат!\nВикористання: /transfer ID_друга сума")
            return
        
        friend_id = int(parts[1])
        amount = int(parts[2])
        
        # Перевірки
        if amount < 10:
            await message.answer("❌ Мінімальна сума переказу: 10 ✯")
            return
        
        if friend_id == user_id:
            await message.answer("❌ Не можна надсилати гроші самому собі!")
            return
        
        user_coins = get_user_coins(user_id)
        if user_coins < amount:
            await message.answer(f"❌ Недостатньо монет! У вас {user_coins} ✯, потрібно {amount} ✯")
            return
        
        # Перевіряємо чи це друг
        cursor.execute("SELECT friend_username FROM friends WHERE user_id = ? AND friend_id = ?", (user_id, friend_id))
        friend_data = cursor.fetchone()
        
        if not friend_data:
            await message.answer("❌ Цей гравець не у вашому списку друзів! Спочатку додайте його.")
            return
        
        friend_username = friend_data[0]
        
        # Виконуємо переказ
        if transfer_money(user_id, friend_id, amount):
            commission = ceil(amount * 0.05)
            final_amount = amount - commission
            
            await message.answer(
                f"✅ <b>Переказ успішний!</b>\n\n"
                f"👤 Отримувач: {friend_username}\n"
                f"💰 Сума: {amount} ✯\n"
                f"💸 Комісія: {commission} ✯ (5%)\n"
                f"🎯 Нараховано: {final_amount} ✯\n"
                f"💎 Ваш новий баланс: {get_user_coins(user_id)} ✯"
            )
        else:
            await message.answer("❌ Помилка переказу!")
            
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

# ========== ОБРОБНИКИ ІГОР ==========

@dp.callback_query_handler(lambda c: c.data == 'game_quiz')
async def cb_game_quiz(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    # Перевірка ліміту питань
    cursor.execute("SELECT COUNT(*) FROM quiz_answers WHERE user_id = ? AND date = ?", 
                   (user_id, datetime.now().date().isoformat()))
    answered_count = cursor.fetchone()[0]
    
    if answered_count >= DAILY_QUESTION_LIMIT:
        await call.message.edit_text(
            f"❌ <b>Ліміт питань на сьогодні вичерпано!</b>\n\n"
            f"Ви вже відповіли на {answered_count}/{DAILY_QUESTION_LIMIT} питань.\n"
            f"🕒 Ліміт оновиться завтра!",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
            )
        )
        return
    
    # Завантаження питань з файлу
    try:
        with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
            questions = json.load(f)
        question = random.choice(questions)
    except:
        await call.message.edit_text(
            "❌ <b>Файл з питаннями не знайдено!</b>\n\n"
            "Створіть файл questions.json з питаннями.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
            )
        )
        return
    
    kb = InlineKeyboardMarkup(row_width=2)
    for i, option in enumerate(question["options"]):
        kb.insert(InlineKeyboardButton(option, callback_data=f"quiz_answer_{i}_{question['correct']}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(
        f"❓ <b>Вікторина</b>\n\n"
        f"{question['question']}\n\n"
        f"📊 Сьогодні відповіли: {answered_count}/{DAILY_QUESTION_LIMIT}",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith('quiz_answer_'))
async def cb_quiz_answer(call: types.CallbackQuery):
    user_id = call.from_user.id
    data_parts = call.data.split('_')
    answer_index = int(data_parts[2])
    correct_index = int(data_parts[3])
    
    if answer_index == correct_index:
        # Правильна відповідь
        reward = 20
        add_user_coins(user_id, reward)
        add_user_xp(user_id, 10)
        
        cursor.execute(
            "INSERT INTO quiz_answers (user_id, date, correct) VALUES (?, ?, ?)",
            (user_id, datetime.now().date().isoformat(), 1)
        )
        conn.commit()
        
        text = (
            f"✅ <b>Правильно!</b>\n\n"
            f"🎉 Ви виграли {reward} ✯\n"
            f"📈 +10 досвіду\n\n"
            f"💎 Баланс: {get_user_coins(user_id)} ✯"
        )
    else:
        # Неправильна відповідь
        cursor.execute(
            "INSERT INTO quiz_answers (user_id, date, correct) VALUES (?, ?, ?)",
            (user_id, datetime.now().date().isoformat(), 0)
        )
        conn.commit()
        
        text = (
            f"❌ <b>Неправильно!</b>\n\n"
            f"💡 Спробуйте ще раз!"
        )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎯 Ще питання", callback_data="game_quiz"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'game_tap')
async def cb_game_tap(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    tap_stats = get_user_tap_stats(user_id)
    next_level = tap_stats['level'] + 1
    next_boost = TapGame.BOOST_LEVELS.get(next_level)
    
    text = (
        f"👆 <b>Tap Game</b>\n\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n"
        f"🎯 Рівень: {tap_stats['level']}\n"
        f"💰 Дохід: {tap_stats['income']} ✯/тап\n"
        f"👆 Всього тапів: {tap_stats['total_taps']}\n\n"
    )
    
    if next_boost:
        text += f"⚡ Наступний рівень ({next_level}): {next_boost['income']} ✯/тап\n"
        text += f"💵 Ціна: {next_boost['price']} ✯\n\n"
    
    text += "🎮 Натискайте кнопку щоб заробляти монети!"
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("👆 Тапнути!", callback_data="tap_click"))
    if next_boost and get_user_coins(user_id) >= next_boost['price']:
        kb.add(InlineKeyboardButton(f"⚡ Прокачати ({next_boost['price']} ✯)", callback_data="tap_upgrade"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'tap_click')
async def cb_tap_click(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    tap_stats = get_user_tap_stats(user_id)
    
    add_user_coins(user_id, tap_stats['income'])
    cursor.execute("UPDATE players SET total_taps = total_taps + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    
    update_daily_task(user_id, "tap_count")
    await cb_game_tap(call)

@dp.callback_query_handler(lambda c: c.data == 'tap_upgrade')
async def cb_tap_upgrade(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    tap_stats = get_user_tap_stats(user_id)
    next_level = tap_stats['level'] + 1
    next_boost = TapGame.BOOST_LEVELS.get(next_level)
    
    if not next_boost:
        await call.answer("🎉 Ви досягли максимального рівня!", show_alert=True)
        return
    
    if get_user_coins(user_id) >= next_boost['price']:
        cursor.execute("UPDATE players SET coins = coins - ?, tap_boost_level = ? WHERE user_id = ?", 
                       (next_boost['price'], next_level, user_id))
        conn.commit()
        await call.answer(f"⚡ Прокачано до {next_level} рівня!", show_alert=True)
        await cb_game_tap(call)
    else:
        await call.answer("❌ Недостатньо монет!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'game_pvp')
async def cb_game_pvp(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    cursor.execute("SELECT user_id, username FROM players WHERE user_id != ? ORDER BY RANDOM() LIMIT 1", (user_id,))
    opponent = cursor.fetchone()
    
    if opponent:
        opponent_id, opponent_name = opponent
        opponent_coins = get_user_coins(opponent_id)
        
        text = (
            f"⚔️ <b>PvP Дуель</b>\n\n"
            f"🎯 <b>Ваш суперник:</b> {opponent_name}\n"
            f"💎 Баланс суперника: {opponent_coins} ✯\n"
            f"💎 Ваш баланс: {get_user_coins(user_id)} ✯\n\n"
            f"🎰 <b>Механіка:</b>\n"
            f"• Кожен ставить 10% від балансу\n"
            f"• Перемагає той, хто викине більше на кістках (1-6)\n"
            f"• Переможець отримує весь банк!\n\n"
            f"⚡ Готові до битви?"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🎲 Прийняти виклик!", callback_data=f"pvp_fight_{opponent_id}"))
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    else:
        text = "❌ Наразі немає доступних суперників!"
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('pvp_fight_'))
async def cb_pvp_fight(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    opponent_id = int(call.data.split('_')[2])
    
    user_coins = get_user_coins(user_id)
    opponent_coins = get_user_coins(opponent_id)
    
    bet_user = max(10, min(1000, user_coins // 10))
    bet_opponent = max(10, min(1000, opponent_coins // 10))
    total_bet = bet_user + bet_opponent
    
    user_roll = random.randint(1, 6)
    opponent_roll = random.randint(1, 6)
    
    cursor.execute("SELECT username FROM players WHERE user_id = ?", (opponent_id,))
    opponent_name = cursor.fetchone()[0]
    
    if user_roll > opponent_roll:
        add_user_coins(user_id, total_bet)
        cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (bet_opponent, opponent_id))
        result_text = f"🎉 <b>Ви перемогли!</b>\n\n"
        reward = total_bet
    elif user_roll < opponent_roll:
        cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (total_bet, opponent_id))
        cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (bet_user, user_id))
        result_text = f"❌ <b>Ви програли!</b>\n\n"
        reward = -bet_user
    else:
        result_text = f"🤝 <b>Нічия!</b>\n\n"
        reward = 0
    
    text = (
        f"{result_text}"
        f"🎲 Ваш кидок: <b>{user_roll}</b>\n"
        f"🎲 Кидок {opponent_name}: <b>{opponent_roll}</b>\n\n"
        f"💰 Ставка: {bet_user} ✯\n"
        f"🏆 Виграш: {reward} ✯\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⚔️ Ще дуель", callback_data="game_pvp"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)
    conn.commit()

@dp.callback_query_handler(lambda c: c.data == 'game_dice')
async def cb_game_dice(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    text = (
        f"🎲 <b>Гра в кістки</b>\n\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🎯 <b>Правила:</b>\n"
        f"• Ставка: 50 ✯\n"
        f"• Кидаєте дві кістки (2-12)\n"
        f"• 7-12: x2 виграш\n"
        f"• 2-6: програш\n\n"
        f"🎰 Готові кинути кістки?"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎲 Кинути кістки (50 ✯)", callback_data="dice_roll"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'dice_roll')
async def cb_dice_roll(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    
    if user_coins < 50:
        await call.answer("❌ Недостатньо монет для ставки!", show_alert=True)
        return
    
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    total = dice1 + dice2
    
    if total >= 7:
        win_amount = 100
        add_user_coins(user_id, win_amount - 50)
        result = f"🎉 <b>Виграш! +50 ✯</b>"
    else:
        cursor.execute("UPDATE players SET coins = coins - 50 WHERE user_id = ?", (user_id,))
        result = f"❌ <b>Програш! -50 ✯</b>"
    
    conn.commit()
    
    text = (
        f"🎲 <b>Результат кидка</b>\n\n"
        f"🎯 Кістки: <b>{dice1}</b> + <b>{dice2}</b> = <b>{total}</b>\n"
        f"💰 {result}\n\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎲 Кинути ще раз", callback_data="dice_roll"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="game_dice"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'game_guess')
async def cb_game_guess(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    secret_number = random.randint(1, 10)
    
    text = (
        f"🎯 <b>Вгадай число</b>\n\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🎯 <b>Правила:</b>\n"
        f"• Загадано число від 1 до 10\n"
        f"• Ставка: 25 ✯\n"
        f"• Вгадали: +75 ✯ (x3)\n"
        f"• Не вгадали: -25 ✯\n\n"
        f"🔢 Оберіть число:"
    )
    
    kb = InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 11):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f"guess_number_{i}_{secret_number}"))
    kb.add(*buttons)
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('guess_number_'))
async def cb_guess_number(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    data_parts = call.data.split('_')
    guessed_number = int(data_parts[2])
    secret_number = int(data_parts[3])
    
    user_coins = get_user_coins(user_id)
    
    if user_coins < 25:
        await call.answer("❌ Недостатньо монет для ставки!", show_alert=True)
        return
    
    if guessed_number == secret_number:
        add_user_coins(user_id, 50)
        result = f"🎉 <b>Вітаю! Ви вгадали!</b>\n+50 ✯"
    else:
        cursor.execute("UPDATE players SET coins = coins - 25 WHERE user_id = ?", (user_id,))
        result = f"❌ <b>Нажаль, не вгадали!</b>\n-25 ✯\nЗагадане число: {secret_number}"
    
    conn.commit()
    
    text = (
        f"🎯 <b>Результат гри</b>\n\n"
        f"🔢 Ваша спроба: <b>{guessed_number}</b>\n"
        f"💰 {result}\n\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎯 Грати ще", callback_data="game_guess"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'daily_tasks')
async def cb_daily_tasks(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    progress = get_daily_tasks_progress(user_id)
    
    text = (
        f"📋 <b>Щоденні завдання</b>\n\n"
        f"✅ Виконано: {progress['tasks_completed']}/{len(DailyTasks.TASKS)}\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🎯 <b>Сьогоднішні завдання:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    buttons_added = False
    
    for i, task in enumerate(progress["active_tasks"]):
        status = "✅" if task["completed"] else "⏳"
        text += f"{i+1}. {task['description']} {status}\n"
        text += f"   Прогрес: {task['current']}/{task['target']} | Нагорода: {task['reward']} ✯\n\n"
        
        if task["completed"]:
            kb.insert(InlineKeyboardButton(f"🎁 Завд.{i+1}", callback_data=f"claim_task_{i}"))
            buttons_added = True
    
    if not buttons_added:
        text += "💡 Виконайте завдання щоб отримати нагороди!"
    
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="daily_tasks"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('claim_task_'))
async def cb_claim_task(call: types.CallbackQuery):
    task_index = int(call.data.replace('claim_task_', ''))
    user_id = call.from_user.id
    
    progress = get_daily_tasks_progress(user_id)
    
    if task_index >= len(progress["active_tasks"]):
        await call.answer("❌ Завдання не знайдено!", show_alert=True)
        return
    
    task = progress["active_tasks"][task_index]
    
    if not task["completed"]:
        await call.answer("❌ Завдання ще не виконано!", show_alert=True)
        return
    
    add_user_coins(user_id, task["reward"])
    cursor.execute("UPDATE daily_tasks SET tasks_completed = tasks_completed + 1 WHERE user_id = ? AND task_date = ?", 
                   (user_id, datetime.now().date().isoformat()))
    conn.commit()
    
    await call.answer(f"🎉 Отримано {task['reward']} ✯!", show_alert=True)
    await cb_daily_tasks(call)

# ========== АДМІН-ФУНКЦІЇ ==========
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def get_all_users() -> List[Dict]:
    """Отримати всіх гравців"""
    cursor.execute("SELECT user_id, username, level, coins, last_active FROM players ORDER BY coins DESC")
    users = []
    for user_id, username, level, coins, last_active in cursor.fetchall():
        users.append({
            "user_id": user_id,
            "username": username,
            "level": level,
            "coins": coins,
            "last_active": last_active
        })
    return users

def update_user_balance(user_id: int, coins: int):
    """Змінити баланс гравця"""
    cursor.execute("UPDATE players SET coins = ? WHERE user_id = ?", (coins, user_id))
    conn.commit()

def update_user_level(user_id: int, level: int):
    """Змінити рівень гравця"""
    cursor.execute("UPDATE players SET level = ? WHERE user_id = ?", (level, user_id))
    conn.commit()

def add_coins_to_all(amount: int):
    """Додати монети всім гравцям"""
    cursor.execute("UPDATE players SET coins = coins + ?", (amount,))
    conn.commit()

def get_bot_stats() -> Dict:
    """Статистика бота"""
    cursor.execute("SELECT COUNT(*) FROM players")
    total_players = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(coins) FROM players")
    total_coins = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM players WHERE last_active > ?", 
                   ((datetime.now() - timedelta(days=1)).isoformat(),))
    active_today = cursor.fetchone()[0]
    
    return {
        "total_players": total_players,
        "total_coins": total_coins,
        "active_today": active_today
    }

# ========== АДМІН-ОБРОБНИКИ ==========
@dp.callback_query_handler(lambda c: c.data == 'admin_panel')
async def cb_admin_panel(call: types.CallbackQuery):
    """Головна адмін-панель"""
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ заборонено!", show_alert=True)
        return
    
    await call.answer()
    stats = get_bot_stats()
    
    text = (
        f"👑 <b>Адмін-панель</b>\n\n"
        f"📊 <b>Статистика бота:</b>\n"
        f"• 👥 Гравців: {stats['total_players']}\n"
        f"• 💰 Монет в обігу: {stats['total_coins']}\n"
        f"• 🎯 Активних сьогодні: {stats['active_today']}\n\n"
        f"⚙️ <b>Оберіть дію:</b>"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📋 Список гравців", callback_data="admin_users_list"),
        InlineKeyboardButton("💰 Змінити баланс", callback_data="admin_edit_balance"),
        InlineKeyboardButton("🎯 Змінити рівень", callback_data="admin_edit_level"),
        InlineKeyboardButton("🎁 Нагородити всіх", callback_data="admin_reward_all"),
        InlineKeyboardButton("📢 Розсилка", callback_data="admin_broadcast"),
        InlineKeyboardButton("📊 Детальна статистика", callback_data="admin_detailed_stats"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'admin_users_list')
async def cb_admin_users_list(call: types.CallbackQuery):
    """Список всіх гравців"""
    if not is_admin(call.from_user.id):
        return
    
    await call.answer()
    users = get_all_users()
    
    text = f"📋 <b>Список гравців</b>\n\n"
    text += f"👥 Всього: {len(users)} гравців\n\n"
    
    for i, user in enumerate(users[:15], 1):
        text += f"{i}. {user['username']}\n"
        text += f"   ID: {user['user_id']} | 💰 {user['coins']} ✯ | 🎯 {user['level']} рів.\n\n"
    
    if len(users) > 15:
        text += f"... і ще {len(users) - 15} гравців"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="admin_users_list"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'admin_edit_balance')
async def cb_admin_edit_balance(call: types.CallbackQuery):
    """Змінити баланс гравця"""
    if not is_admin(call.from_user.id):
        return
    
    await call.answer()
    
    text = (
        "💰 <b>Змінити баланс гравця</b>\n\n"
        "📝 <b>Формат команди:</b>\n"
        "<code>/setcoins ID_гравця кількість</code>\n\n"
        "📝 <b>Приклади:</b>\n"
        "<code>/setcoins 123456789 1000</code> - встановити 1000 монет\n"
        "<code>/setcoins 123456789 +500</code> - додати 500 монет\n"
        "<code>/setcoins 123456789 -200</code> - забрати 200 монет\n\n"
        "💡 <b>Порада:</b> ID гравця можна дізнатись зі списку гравців"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📋 Список гравців", callback_data="admin_users_list"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'admin_edit_level')
async def cb_admin_edit_level(call: types.CallbackQuery):
    """Змінити рівень гравця"""
    if not is_admin(call.from_user.id):
        return
    
    await call.answer()
    
    text = (
        "🎯 <b>Змінити рівень гравця</b>\n\n"
        "📝 <b>Формат команди:</b>\n"
        "<code>/setlevel ID_гравця рівень</code>\n\n"
        "📝 <b>Приклади:</b>\n"
        "<code>/setlevel 123456789 10</code> - встановити 10 рівень\n"
        "<code>/setlevel 123456789 +5</code> - підвищити на 5 рівнів\n"
        "<code>/setlevel 123456789 -2</code> - знизити на 2 рівні\n\n"
        "💡 ID гравця можна дізнатись зі списку гравців"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📋 Список гравців", callback_data="admin_users_list"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'admin_reward_all')
async def cb_admin_reward_all(call: types.CallbackQuery):
    """Нагородити всіх гравців"""
    if not is_admin(call.from_user.id):
        return
    
    await call.answer()
    
    text = (
        "🎁 <b>Нагородити всіх гравців</b>\n\n"
        "📝 <b>Формат команди:</b>\n"
        "<code>/rewardall кількість</code>\n\n"
        "📝 <b>Приклади:</b>\n"
        "<code>/rewardall 100</code> - додати 100 монет кожному\n"
        "<code>/rewardall 1000</code> - додати 1000 монет кожному\n\n"
        "⚠️ <b>Увага:</b> Ця дія нарахує монети ВСІМ гравцям!"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'admin_detailed_stats')
async def cb_admin_detailed_stats(call: types.CallbackQuery):
    """Детальна статистика"""
    if not is_admin(call.from_user.id):
        return
    
    await call.answer()
    users = get_all_users()
    stats = get_bot_stats()
    
    # Топ 10 гравців
    top_players = users[:10]
    
    text = (
        f"📊 <b>Детальна статистика</b>\n\n"
        f"👥 <b>Загальна:</b>\n"
        f"• Всього гравців: {stats['total_players']}\n"
        f"• Монет в обігу: {stats['total_coins']}\n"
        f"• Активних сьогодні: {stats['active_today']}\n\n"
        f"🏆 <b>Топ 10 гравців:</b>\n"
    )
    
    for i, user in enumerate(top_players, 1):
        text += f"{i}. {user['username']} - {user['coins']} ✯ (рівень {user['level']})\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="admin_detailed_stats"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    
    await call.message.edit_text(text, reply_markup=kb)

# ========== АДМІН-КОМАНДИ ==========
@dp.message_handler(commands=['setcoins'])
async def cmd_setcoins(message: types.Message):
    """Команда для зміни балансу"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("❌ Неправильний формат!\nВикористання: /setcoins ID кількість")
            return
        
        user_id = int(parts[1])
        amount_str = parts[2]
        
        # Перевіряємо чи існує гравець
        cursor.execute("SELECT username, coins FROM players WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        
        if not user_data:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username, current_coins = user_data
        
        # Обробляємо amount (+100, -50, або просто число)
        if amount_str.startswith('+'):
            new_coins = current_coins + int(amount_str[1:])
            action = "додано"
        elif amount_str.startswith('-'):
            new_coins = current_coins - int(amount_str[1:])
            action = "знято"
        else:
            new_coins = int(amount_str)
            action = "встановлено"
        
        if new_coins < 0:
            new_coins = 0
        
        # Оновлюємо баланс
        cursor.execute("UPDATE players SET coins = ? WHERE user_id = ?", (new_coins, user_id))
        conn.commit()
        
        await message.answer(
            f"✅ <b>Баланс оновлено!</b>\n\n"
            f"👤 Гравець: {username}\n"
            f"💰 {action}: {abs(int(amount_str))} ✯\n"
            f"💎 Новий баланс: {new_coins} ✯"
        )
        
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['setlevel'])
async def cmd_setlevel(message: types.Message):
    """Команда для зміни рівня"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("❌ Неправильний формат!\nВикористання: /setlevel ID рівень")
            return
        
        user_id = int(parts[1])
        level_str = parts[2]
        
        # Перевіряємо чи існує гравець
        cursor.execute("SELECT username, level FROM players WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        
        if not user_data:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username, current_level = user_data
        
        # Обробляємо level (+5, -2, або просто число)
        if level_str.startswith('+'):
            new_level = current_level + int(level_str[1:])
            action = "підвищено"
        elif level_str.startswith('-'):
            new_level = current_level - int(level_str[1:])
            action = "знижено"
        else:
            new_level = int(level_str)
            action = "встановлено"
        
        if new_level < 1:
            new_level = 1
        
        # Оновлюємо рівень
        cursor.execute("UPDATE players SET level = ? WHERE user_id = ?", (new_level, user_id))
        conn.commit()
        
        await message.answer(
            f"✅ <b>Рівень оновлено!</b>\n\n"
            f"👤 Гравець: {username}\n"
            f"🎯 {action}: {abs(int(level_str))} рівнів\n"
            f"🌟 Новий рівень: {new_level}"
        )
        
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['rewardall'])
async def cmd_rewardall(message: types.Message):
    """Команда для нагородження всіх"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Неправильний формат!\nВикористання: /rewardall кількість")
            return
        
        amount = int(parts[1])
        
        if amount <= 0:
            await message.answer("❌ Кількість має бути додатньою!")
            return
        
        # Нагороджуємо всіх
        cursor.execute("UPDATE players SET coins = coins + ?", (amount,))
        
        # Отримуємо кількість гравців
        cursor.execute("SELECT COUNT(*) FROM players")
        total_players = cursor.fetchone()[0]
        
        conn.commit()
        
        await message.answer(
            f"✅ <b>Всі гравці нагороджені!</b>\n\n"
            f"🎁 Кожен отримав: {amount} ✯\n"
            f"👥 Кількість гравців: {total_players}\n"
            f"💰 Всього видано: {amount * total_players} ✯"
        )
        
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['broadcast'])
async def cmd_broadcast(message: types.Message):
    """Розсилка повідомлень всім гравцям"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ заборонено!")
        return
    
    if len(message.text.split()) < 2:
        await message.answer("❌ Неправильний формат!\nВикористання: /broadcast ваш_текст")
        return
    
    broadcast_text = message.text.split(' ', 1)[1]
    
    try:
        # Отримуємо всіх гравців
        cursor.execute("SELECT user_id FROM players")
        users = cursor.fetchall()
        
        total_users = len(users)
        success_count = 0
        fail_count = 0
        
        # Відправляємо повідомлення про початок розсилки
        progress_msg = await message.answer(
            f"📤 <b>Початок розсилки...</b>\n\n"
            f"👥 Гравців: {total_users}\n"
            f"⏳ Триває відправка..."
        )
        
        for i, (user_id,) in enumerate(users):
            try:
                await bot.send_message(
                    user_id,
                    f"📢 <b>Оголошення від адміністрації</b>\n\n"
                    f"{broadcast_text}\n\n"
                    f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                    parse_mode="HTML"
                )
                success_count += 1
                
                # Оновлюємо прогрес кожні 10 повідомлень
                if i % 10 == 0:
                    await progress_msg.edit_text(
                        f"📤 <b>Розсилка в процесі...</b>\n\n"
                        f"✅ Відправлено: {success_count}/{total_users}\n"
                        f"❌ Помилок: {fail_count}\n"
                        f"⏳ Прогрес: {i}/{total_users}"
                    )
                
                await asyncio.sleep(0.1)  # Затримка щоб не перевищити ліміти Telegram
                
            except Exception as e:
                fail_count += 1
                print(f"Не вдалося відправити повідомлення {user_id}: {e}")
        
        # Фінальне повідомлення
        await progress_msg.edit_text(
            f"✅ <b>Розсилка завершена!</b>\n\n"
            f"📊 <b>Результати:</b>\n"
            f"• 👥 Всього гравців: {total_users}\n"
            f"• ✅ Відправлено: {success_count}\n"
            f"• ❌ Не вдалось: {fail_count}\n"
            f"• 📈 Успішність: {(success_count/total_users)*100:.1f}%\n\n"
            f"💬 <b>Текст повідомлення:</b>\n"
            f"{broadcast_text}"
        )
        
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

# ========== АДМІН-ФУНКЦІЇ ==========
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def get_all_users() -> List[Dict]:
    """Отримати всіх гравців"""
    cursor.execute("SELECT user_id, username, level, coins, last_active FROM players ORDER BY coins DESC")
    users = []
    for user_id, username, level, coins, last_active in cursor.fetchall():
        users.append({
            "user_id": user_id,
            "username": username,
            "level": level,
            "coins": coins,
            "last_active": last_active
        })
    return users

def get_bot_stats() -> Dict:
    """Статистика бота"""
    cursor.execute("SELECT COUNT(*) FROM players")
    total_players = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(coins) FROM players")
    total_coins = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM players WHERE last_active > ?", 
                   ((datetime.now() - timedelta(days=1)).isoformat(),))
    active_today = cursor.fetchone()[0]
    
    return {
        "total_players": total_players,
        "total_coins": total_coins,
        "active_today": active_today
    }

# ========== ІНШІ ФУНКЦІЇ ==========
def add_user_xp(user_id: int, xp: int):
    cursor.execute("UPDATE players SET xp = xp + ? WHERE user_id = ?", (xp, user_id))
    
    # Перевірка підвищення рівня
    current_level = get_user_level(user_id)
    current_xp = get_user_xp(user_id)
    xp_needed = current_level * XP_PER_LEVEL
    
    if current_xp >= xp_needed:
        new_level = current_level + 1
        cursor.execute("UPDATE players SET level = ? WHERE user_id = ?", (new_level, user_id))
        conn.commit()
        return new_level
    return current_level

def get_user_xp(user_id: int) -> int:
    cursor.execute("SELECT xp FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def create_progress_bar(percentage: float, length: int = 20) -> str:
    filled = int(length * percentage / 100)
    empty = length - filled
    return f"[{'█' * filled}{'░' * empty}] {percentage:.1f}%"
# ========== ОБРОБНИКИ ДЛЯ ВСІХ КНОПОК ==========

@dp.callback_query_handler(lambda c: c.data == 'income_farm')
async def cb_income_farm(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    farm_income = get_user_farm_income(user_id)
    
    cursor.execute("SELECT animal_type, income, count FROM farm_animals WHERE user_id = ?", (user_id,))
    user_animals = cursor.fetchall()
    
    text = (
        f"🐓 <b>Ваша ферма</b>\n\n"
        f"💰 Дохід: {farm_income} ✯/год\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
    )
    
    if user_animals:
        text += "🏠 <b>Ваші тварини:</b>\n"
        for animal_type, income, count in user_animals:
            text += f"• {animal_type}: {count} шт. ({income * count} ✯/год)\n"
    else:
        text += "❌ У вас ще немає тварин!\n"
    
    text += "\n🛍️ <b>Доступні тварини:</b>\n"
    for animal in FarmAnimals.ANIMALS[:3]:
        text += f"• {animal['emoji']} {animal['name']}: {animal['price']} ✯ ({animal['income']} ✯/год)\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ Купити тварин", callback_data="shop_farm"))
    kb.add(InlineKeyboardButton("💰 Зібрати дохід", callback_data="farm_collect"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'income_real_estate')
async def cb_income_real_estate(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    estate_income = get_user_real_estate_income(user_id)
    
    cursor.execute("SELECT type, income FROM user_real_estate WHERE user_id = ?", (user_id,))
    user_estates = cursor.fetchall()
    
    text = (
        f"🏘️ <b>Ваша нерухомість</b>\n\n"
        f"💰 Дохід: {estate_income} ✯/год\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
    )
    
    if user_estates:
        text += "🏠 <b>Ваші об'єкти:</b>\n"
        for estate_type, income in user_estates:
            text += f"• {estate_type}: {income} ✯/год\n"
    else:
        text += "❌ У вас ще немає нерухомості!\n"
    
    text += "\n🛍️ <b>Доступна нерухомість:</b>\n"
    for estate in RealEstate.PROPERTIES[:3]:
        text += f"• {estate['name']}: {estate['price']} ✯ ({estate['income']} ✯/год)\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ Купити нерухомість", callback_data="shop_real_estate"))
    kb.add(InlineKeyboardButton("💰 Зібрати дохід", callback_data="estate_collect"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'farm_collect')
async def cb_farm_collect(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    farm_income = get_user_farm_income(user_id)
    
    if farm_income == 0:
        await call.answer("❌ Немає доходу для збору!", show_alert=True)
        return
    
    add_user_coins(user_id, farm_income)
    
    text = (
        f"🐓 <b>Збір доходу з ферми</b>\n\n"
        f"💰 Зібрано: {farm_income} ✯\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🕒 Наступний дохід буде доступний через 1 годину"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="income_farm"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'estate_collect')
async def cb_estate_collect(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    estate_income = get_user_real_estate_income(user_id)
    
    if estate_income == 0:
        await call.answer("❌ Немає доходу для збору!", show_alert=True)
        return
    
    add_user_coins(user_id, estate_income)
    
    text = (
        f"🏘️ <b>Збір доходу з нерухомості</b>\n\n"
        f"💰 Зібрано: {estate_income} ✯\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🕒 Наступний дохід буде доступний через 1 годину"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="income_real_estate"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'shop_farm')
async def cb_shop_farm(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    farm_income = get_user_farm_income(user_id)
    
    text = (
        f"🛍️ <b>Магазин ферми</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n"
        f"💰 Поточний дохід: {farm_income} ✯/год\n\n"
        f"🐓 <b>Доступні тварини:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for animal in FarmAnimals.ANIMALS:
        text += f"• {animal['emoji']} {animal['name']}: {animal['price']} ✯ ({animal['income']} ✯/год)\n"
        if user_coins >= animal['price']:
            kb.insert(InlineKeyboardButton(
                f"{animal['emoji']} {animal['price']}✯", 
                callback_data=f"buy_animal_{animal['name']}"
            ))
    
    text += f"\n💡 <b>Порада:</b> Тварини приносять пасивний дохід кожну годину!"
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="income_farm"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('buy_animal_'))
async def cb_buy_animal(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    animal_name = call.data.replace('buy_animal_', '')
    
    animal = next((a for a in FarmAnimals.ANIMALS if a['name'] == animal_name), None)
    if not animal:
        await call.answer("❌ Тварина не знайдена!", show_alert=True)
        return
    
    user_coins = get_user_coins(user_id)
    
    if user_coins < animal['price']:
        await call.answer("❌ Недостатньо монет!", show_alert=True)
        return
    
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", 
                   (animal['price'], user_id))
    
    cursor.execute("SELECT count FROM farm_animals WHERE user_id = ? AND animal_type = ?", 
                   (user_id, animal['name']))
    result = cursor.fetchone()
    
    if result:
        cursor.execute("UPDATE farm_animals SET count = count + 1 WHERE user_id = ? AND animal_type = ?", 
                       (user_id, animal['name']))
    else:
        cursor.execute(
            "INSERT INTO farm_animals (user_id, animal_type, income, count) VALUES (?, ?, ?, ?)",
            (user_id, animal['name'], animal['income'], 1)
        )
    
    conn.commit()
    update_daily_task(user_id, "buy_animals")
    
    await call.answer(f"✅ Куплено {animal['emoji']} {animal['name']}!", show_alert=True)
    await cb_shop_farm(call)

@dp.callback_query_handler(lambda c: c.data == 'shop_real_estate')
async def cb_shop_real_estate(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    estate_income = get_user_real_estate_income(user_id)
    
    text = (
        f"🛍️ <b>Магазин нерухомості</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n"
        f"💰 Поточний дохід: {estate_income} ✯/год\n\n"
        f"🏘️ <b>Доступна нерухомість:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for estate in RealEstate.PROPERTIES:
        text += f"• {estate['name']}: {estate['price']} ✯ ({estate['income']} ✯/год)\n"
        if user_coins >= estate['price']:
            kb.insert(InlineKeyboardButton(
                f"{estate['name']} {estate['price']}✯", 
                callback_data=f"buy_estate_{estate['name']}"
            ))
    
    text += f"\n💡 <b>Порада:</b> Нерухомість приносить стабільний пасивний дохід!"
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="income_real_estate"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('buy_estate_'))
async def cb_buy_estate(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    estate_name = call.data.replace('buy_estate_', '')
    
    estate = next((e for e in RealEstate.PROPERTIES if e['name'] == estate_name), None)
    if not estate:
        await call.answer("❌ Об'єкт не знайдений!", show_alert=True)
        return
    
    user_coins = get_user_coins(user_id)
    
    if user_coins < estate['price']:
        await call.answer("❌ Недостатньо монет!", show_alert=True)
        return
    
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", 
                   (estate['price'], user_id))
    
    cursor.execute(
        "INSERT INTO user_real_estate (user_id, type, income, price, last_collect_time) VALUES (?, ?, ?, ?, ?)",
        (user_id, estate['name'], estate['income'], estate['price'], datetime.now().isoformat())
    )
    
    conn.commit()
    
    await call.answer(f"✅ Куплено {estate['name']}!", show_alert=True)
    await cb_shop_real_estate(call)

@dp.callback_query_handler(lambda c: c.data == 'menu_item_roulette')
async def cb_menu_item_roulette(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    can_spin = get_user_level(user_id) >= 3 and user_coins >= 200
    
    text = (
        f"🎪 <b>Рулетка предметів</b>\n\n"
        f"💎 Баланс: {user_coins} ✯\n"
        f"🎯 Вартість: 200 ✯\n"
        f"📊 Доступно: {'✅' if can_spin else '❌'}\n\n"
    )
    
    if not can_spin:
        if get_user_level(user_id) < 3:
            text += "❌ Рулетка предметів доступна з 3 рівня!\n\n"
        else:
            text += "❌ Недостатньо монет! Потрібно 200 ✯\n\n"
    
    text += "🏆 <b>Топ призи:</b>\n"
    top_prizes = sorted(ItemRoulettePrizes.PRIZES, key=lambda x: x['price'], reverse=True)[:5]
    for prize in top_prizes:
        text += f"• {prize['name']} - {prize['price']} ✯\n"
    
    kb = InlineKeyboardMarkup(row_width=2)
    if can_spin:
        kb.add(InlineKeyboardButton("🎪 Крутити (200 ✯)", callback_data="item_roulette_spin"))
    kb.add(
        InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_roulettes")
    )
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'item_roulette_spin')
async def cb_item_roulette_spin(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    if get_user_coins(user_id) < 200:
        await call.answer("❌ Недостатньо монет!", show_alert=True)
        return
    
    cursor.execute("UPDATE players SET coins = coins - 200 WHERE user_id = ?", (user_id,))
    
    r = random.random()
    cumulative_probability = 0.0
    
    for prize in ItemRoulettePrizes.PRIZES:
        cumulative_probability += prize["probability"]
        if r <= cumulative_probability:
            cursor.execute(
                "INSERT INTO user_inventory (user_id, item_name, item_price, obtained_date) VALUES (?, ?, ?, ?)",
                (user_id, prize["name"], prize["price"], datetime.now().isoformat())
            )
            conn.commit()
            
            update_daily_task(user_id, "spin_roulette")
            
            text = (
                f"🎪 <b>Результат рулетки</b>\n\n"
                f"🎉 Ви виграли: {prize['name']}!\n"
                f"💎 Ціна: {prize['price']} ✯\n\n"
                f"💼 Предмет додано до інвентаря!\n"
                f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
            )
            
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view"))
            kb.add(InlineKeyboardButton("🎪 Крутити ще", callback_data="item_roulette_spin"))
            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_item_roulette"))
            
            await call.message.edit_text(text, reply_markup=kb)
            return
    
    await call.answer("❌ Помилка рулетки", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'inventory_view')
async def cb_inventory_view(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    cursor.execute(
        "SELECT item_name, item_price, obtained_date FROM user_inventory WHERE user_id = ? ORDER BY obtained_date DESC",
        (user_id,)
    )
    items = cursor.fetchall()
    
    if not items:
        text = "📦 <b>Ваш інвентар</b>\n\n❌ Інвентар порожній!\n🎪 Крутіть рулетку предметів щоб отримати предмети."
    else:
        total_value = sum(item[1] for item in items)
        text = f"📦 <b>Ваш інвентар</b>\n\n📊 Предметів: {len(items)}\n💰 Загальна вартість: {total_value} ✯\n\n"
        
        for i, (name, price, date) in enumerate(items[:10], 1):
            text += f"{i}. {name} - {price} ✯\n"
        
        if len(items) > 10:
            text += f"\n... і ще {len(items) - 10} предметів"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎪 Рулетка предметів", callback_data="menu_item_roulette"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_roulettes"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'roulette_normal')
async def cb_roulette_normal(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    
    text = (
        f"💰 <b>Звичайна рулетка</b>\n\n"
        f"💎 Баланс: {user_coins} ✯\n"
        f"🎯 Вартість: 50 ✯\n\n"
        f"🏆 <b>Можливі виграші:</b>\n"
        f"• 10 ✯ (30% шанс)\n"
        f"• 25 ✯ (25% шанс)\n"
        f"• 50 ✯ (20% шанс)\n"
        f"• 100 ✯ (15% шанс)\n"
        f"• 200 ✯ (10% шанс)\n\n"
        f"🎰 Готові крутити?"
    )
    
    kb = InlineKeyboardMarkup()
    if user_coins >= 50:
        kb.add(InlineKeyboardButton("💰 Крутити (50 ✯)", callback_data="normal_roulette_spin"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_roulettes"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'normal_roulette_spin')
async def cb_normal_roulette_spin(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    if get_user_coins(user_id) < 50:
        await call.answer("❌ Недостатньо монет!", show_alert=True)
        return
    
    cursor.execute("UPDATE players SET coins = coins - 50 WHERE user_id = ?", (user_id,))
    
    r = random.random()
    if r < 0.30:
        win = 10
    elif r < 0.55:
        win = 25
    elif r < 0.75:
        win = 50
    elif r < 0.90:
        win = 100
    else:
        win = 200
    
    add_user_coins(user_id, win)
    update_daily_task(user_id, "spin_roulette")
    
    text = (
        f"💰 <b>Результат рулетки</b>\n\n"
        f"🎉 Ви виграли: {win} ✯!\n\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💰 Крутити ще", callback_data="normal_roulette_spin"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="roulette_normal"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'roulette_premium')
async def cb_roulette_premium(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    
    text = (
        f"💎 <b>Преміум рулетка</b>\n\n"
        f"💎 Баланс: {user_coins} ✯\n"
        f"🎯 Вартість: 500 ✯\n\n"
        f"🏆 <b>Можливі виграші:</b>\n"
    )
    
    for multiplier in PremiumRoulette.MULTIPLIERS:
        if 'multiplier' in multiplier:
            text += f"• x{multiplier['multiplier']} ({multiplier['probability']*100}%)\n"
        else:
            text += f"• {multiplier['description']} ({multiplier['probability']*100}%)\n"
    
    text += f"\n💡 <b>Приклад:</b> При балансі 1000 ✯ можна виграти до 10000 ✯!"
    
    kb = InlineKeyboardMarkup()
    if user_coins >= 500:
        kb.add(InlineKeyboardButton("💎 Крутити (500 ✯)", callback_data="premium_roulette_spin"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_roulettes"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'premium_roulette_spin')
async def cb_premium_roulette_spin(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    
    if user_coins < 500:
        await call.answer("❌ Недостатньо монет!", show_alert=True)
        return
    
    cursor.execute("UPDATE players SET coins = coins - 500 WHERE user_id = ?", (user_id,))
    
    r = random.random()
    cumulative_probability = 0.0
    
    for multiplier in PremiumRoulette.MULTIPLIERS:
        cumulative_probability += multiplier['probability']
        if r <= cumulative_probability:
            if 'multiplier' in multiplier:
                win = user_coins * multiplier['multiplier']
                add_user_coins(user_id, win)
                result_text = f"🎉 <b>ДЖЕКПОТ! x{multiplier['multiplier']}</b>\nВиграш: {win} ✯"
            elif multiplier['type'] == 'ticket':
                result_text = "🎫 <b>Білет в звичайну рулетку</b>\nВи можете безкоштовно покрутити звичайну рулетку!"
            else:
                result_text = "❌ <b>Нічого не виграно</b>\nСпробуйте ще раз!"
            break
    
    conn.commit()
    
    text = (
        f"💎 <b>Результат преміум рулетки</b>\n\n"
        f"{result_text}\n\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💎 Крутити ще", callback_data="premium_roulette_spin"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="roulette_premium"))
    
    await call.message.edit_text(text, reply_markup=kb)

# Додай також ці функції якщо їх немає:
def update_daily_task(user_id: int, task_type: str, increment: int = 1):
    today = datetime.now().date().isoformat()
    
    cursor.execute("SELECT id FROM daily_tasks WHERE user_id = ? AND task_date = ?", (user_id, today))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO daily_tasks (user_id, task_date) VALUES (?, ?)",
            (user_id, today)
        )
    
    if task_type == "spin_roulette":
        cursor.execute("UPDATE daily_tasks SET spin_roulette_count = spin_roulette_count + ? WHERE user_id = ? AND task_date = ?", 
                       (increment, user_id, today))
    elif task_type == "tap_count":
        cursor.execute("UPDATE daily_tasks SET tap_count = tap_count + ? WHERE user_id = ? AND task_date = ?", 
                       (increment, user_id, today))
    elif task_type == "play_minigames":
        cursor.execute("UPDATE daily_tasks SET play_minigames_count = play_minigames_count + ? WHERE user_id = ? AND task_date = ?", 
                       (increment, user_id, today))
    elif task_type == "correct_answers":
        cursor.execute("UPDATE daily_tasks SET correct_answers_count = correct_answers_count + ? WHERE user_id = ? AND task_date = ?", 
                       (increment, user_id, today))
    elif task_type == "buy_animals":
        cursor.execute("UPDATE daily_tasks SET tasks_completed = tasks_completed + ? WHERE user_id = ? AND task_date = ?", 
                       (increment, user_id, today))
    
    conn.commit()



# ========== ЗАПУСК БОТА ==========
if __name__ == "__main__":
    # Ініціалізація рулетки предметів
    cursor.execute("SELECT COUNT(*) FROM item_roulette_prizes")
    if cursor.fetchone()[0] == 0:
        for prize in ItemRoulettePrizes.PRIZES:
            cursor.execute(
                "INSERT INTO item_roulette_prizes (name, price, probability, item_type) VALUES (?, ?, ?, ?)",
                (prize["name"], prize["price"], prize["probability"], prize["type"])
            )
        conn.commit()
    
    # Запуск бота
    log.info("🤖 Бот запускається...")
    try:
        executor.start_polling(dp, skip_updates=True)
    except Exception as e:
        log.error(f"❌ Помилка запуску бота: {e}")
    finally:
        conn.close()
