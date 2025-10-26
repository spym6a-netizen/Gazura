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
from website import setup_website_in_bot, start_website_server

# ========== КОНФИГ ==========
BOT_TOKEN = "8259900558:AAHQVUzKQBtKF7N-Xp8smLmAiAf0Hu-hQHw"
XP_PER_LEVEL = 100
INACTIVE_DAYS = 7
DB_PATH = "data.db"
QUESTIONS_PATH = "questions.json"
DAILY_QUESTION_LIMIT = 10
DAILY_TAP_LIMIT_BASE = 1500  # Ліміт тапів для рівнів >5
DAILY_TAP_LIMIT_ACTIVE = 2500  # Ліміт для ролі Активний

ADMIN_ID = 5672490558

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
    prefix TEXT DEFAULT '',
    last_active TEXT,
    animals INTEGER DEFAULT 0,
    tap_boost_level INTEGER DEFAULT 1,
    farm_income INTEGER DEFAULT 0,
    total_taps INTEGER DEFAULT 0,
    daily_taps INTEGER DEFAULT 0,
    last_tap_reset TEXT
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

# ========== СИСТЕМА КРЕДИТІВ ==========
cursor.execute("""
CREATE TABLE IF NOT EXISTS credit_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    max_amount INTEGER NOT NULL,
    min_level INTEGER NOT NULL,
    term_hours INTEGER NOT NULL,
    interest_rate INTEGER NOT NULL,
    description TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    credit_type INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    taken_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    remaining_amount INTEGER NOT NULL,
    status TEXT DEFAULT 'active',
    next_payment_date TEXT,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS credit_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credit_id INTEGER NOT NULL,
    payment_date TEXT NOT NULL,
    amount INTEGER NOT NULL,
    payment_type TEXT NOT NULL,
    FOREIGN KEY (credit_id) REFERENCES user_credits (id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS credit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    credit_type INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    taken_date TEXT NOT NULL,
    closed_date TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

# Заповнюємо типи кредитів
cursor.execute("SELECT COUNT(*) FROM credit_types")
if cursor.fetchone()[0] == 0:
    credit_types_data = [
        (1, "🟢 Міні-кредит", 5000, 5, 24, 15, "Невеликий кредит для початківців"),
        (2, "🔵 Стандартний", 20000, 10, 48, 25, "Ідеальний для розвитку бізнесу"),
        (3, "🟣 Бізнес-кредит", 50000, 15, 72, 35, "Для серйозних інвестицій"),
        (4, "🟠 Інвест-кредит", 100000, 20, 96, 50, "Максимальні можливості")
    ]
    cursor.executemany(
        "INSERT INTO credit_types (id, name, max_amount, min_level, term_hours, interest_rate, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
        credit_types_data
    )

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
    item_type TEXT NOT NULL,
    obtained_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

#AUCTION
cursor.execute("""
CREATE TABLE IF NOT EXISTS auction_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    item_type TEXT NOT NULL,
    original_price INTEGER NOT NULL,
    auction_price INTEGER NOT NULL,
    listed_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")
# ========== СИСТЕМА ЗАПИТІВ У ДРУЗІ ==========
cursor.execute("""
CREATE TABLE IF NOT EXISTS friend_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL,
    from_username TEXT NOT NULL,
    to_user_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    created_date TEXT NOT NULL,
    FOREIGN KEY (from_user_id) REFERENCES players (user_id),
    FOREIGN KEY (to_user_id) REFERENCES players (user_id)
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

# НОВІ ТАБЛИЦІ ДЛЯ ОНОВЛЕНЬ
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    role_name TEXT NOT NULL,
    purchased_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_prefixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    prefix_id INTEGER NOT NULL,
    prefix_name TEXT NOT NULL,
    purchased_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS auction_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    item_type TEXT NOT NULL,
    original_price INTEGER NOT NULL,
    auction_price INTEGER NOT NULL,
    listed_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pending_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL,
    buyer_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    item_type TEXT NOT NULL,
    price INTEGER NOT NULL,
    created_date TEXT NOT NULL,
    FOREIGN KEY (seller_id) REFERENCES players (user_id),
    FOREIGN KEY (buyer_id) REFERENCES players (user_id)
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
    
    # Перевіряємо нові колонки в players
    cursor.execute("PRAGMA table_info(players)")
    player_columns = [column[1] for column in cursor.fetchall()]
    
    if 'daily_taps' not in player_columns:
        print("🔄 Додаємо нові колонки до таблиці players...")
        cursor.execute("ALTER TABLE players ADD COLUMN daily_taps INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE players ADD COLUMN last_tap_reset TEXT")
        cursor.execute("ALTER TABLE players ADD COLUMN prefix TEXT DEFAULT ''")
        print("✅ Таблицю players оновлено!")
    
    # 🔥 ДОДАЄМО ОНОВЛЕННЯ ДЛЯ USER_INVENTORY 🔥
    cursor.execute("PRAGMA table_info(user_inventory)")
    inventory_columns = [column[1] for column in cursor.fetchall()]
    
    if 'item_type' not in inventory_columns:
        print("🔄 Оновлюємо структуру таблиці user_inventory...")
        
        # Створюємо тимчасову таблицю з новою структурою
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_inventory_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            item_price INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            obtained_date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES players (user_id)
        )
        """)
        
        # Копіюємо дані зі старої таблиці (якщо вони є)
        try:
            cursor.execute("""
            INSERT INTO user_inventory_new (user_id, item_name, item_price, item_type, obtained_date)
            SELECT user_id, item_name, item_price, 'mineral', obtained_date 
            FROM user_inventory
            """)
            print("✅ Дані перенесено до нової таблиці!")
        except sqlite3.OperationalError:
            print("ℹ️ Стара таблиця порожня або не існує")
        
        # Замінюємо таблиці
        cursor.execute("DROP TABLE IF EXISTS user_inventory")
        cursor.execute("ALTER TABLE user_inventory_new RENAME TO user_inventory")
        print("✅ Таблицю user_inventory оновлено!")
    
    conn.commit()
except Exception as e:
    print(f"❌ Помилка оновлення таблиць: {e}")

# ========== КОНСТАНТИ ==========
# ========== СИСТЕМА КРЕДИТІВ ==========
class CreditSystem:
    CREDIT_TYPES = [
        {
            "id": 1, 
            "name": "🟢 Міні-кредит", 
            "max_amount": 5000, 
            "min_level": 5, 
            "term_hours": 24, 
            "interest_rate": 15,
            "description": "Невеликий кредит для початківців"
        },
        {
            "id": 2, 
            "name": "🔵 Стандартний", 
            "max_amount": 20000, 
            "min_level": 10, 
            "term_hours": 48, 
            "interest_rate": 25,
            "description": "Ідеальний для розвитку бізнесу"
        },
        {
            "id": 3, 
            "name": "🟣 Бізнес-кредит", 
            "max_amount": 50000, 
            "min_level": 15, 
            "term_hours": 72, 
            "interest_rate": 35,
            "description": "Для серйозних інвестицій"
        },
        {
            "id": 4, 
            "name": "🟠 Інвест-кредит", 
            "max_amount": 100000, 
            "min_level": 20, 
            "term_hours": 96, 
            "interest_rate": 50,
            "description": "Максимальні можливості"
        }
    ]
# ========== БІЗНЕС СИСТЕМА ==========
class BusinessLicenses:
    LICENSES = [
        {"id": 1, "name": "🟢 BI License", "max_businesses": 4, "price": 16400},
        {"id": 2, "name": "🔵 DS License", "max_businesses": 5, "price": 19400},
        {"id": 3, "name": "🟣 GT License", "max_businesses": 6, "price": 32000}
    ]

class BusinessTypes:
    BUSINESSES = [
        {
            "id": 1, 
            "name": "🚕 Таксопарк", 
            "min_level": 6, 
            "base_price": 50000,
            "type": "service",
            "max_level": 10,
            "upgrade_multiplier": 1.8,
            "base_income": 300,
            "income_multiplier": 1.5
        },
        {
            "id": 2, 
            "name": "🏪 Продуктовий магазин", 
            "min_level": 8, 
            "base_price": 100000,
            "type": "retail",
            "max_level": 10,
            "upgrade_multiplier": 1.8,
            "base_income": 600,
            "income_multiplier": 1.5
        },
        {
            "id": 3, 
            "name": "🔧 Автосервіс", 
            "min_level": 10, 
            "base_price": 200000,
            "type": "service",
            "max_level": 10,
            "upgrade_multiplier": 1.8,
            "base_income": 1200,
            "income_multiplier": 1.5
        },
        {
            "id": 4, 
            "name": "🍕 Ресторан", 
            "min_level": 12, 
            "base_price": 500000,
            "type": "food",
            "max_level": 10,
            "upgrade_multiplier": 1.8,
            "base_income": 3000,
            "income_multiplier": 1.5
        },
        {
            "id": 5, 
            "name": "🏢 Офісний центр", 
            "min_level": 15, 
            "base_price": 1000000,
            "type": "real_estate",
            "max_level": 10,
            "upgrade_multiplier": 1.8,
            "base_income": 6000,
            "income_multiplier": 1.5
        }
    ]
class ItemRoulettePrizes:
    PRIZES = [
        # Існуючі предмети
        {"name": "💎 Алмаз", "price": 500, "probability": 0.01, "type": "mineral", "id": 22},
        {"name": "🔮 Містичний кристал", "price": 300, "probability": 0.03, "type": "magic", "id": 55},
        {"name": "🪨 Камінь", "price": 7, "probability": 0.15, "type": "mineral", "id": 11},
        {"name": "⛏️ Залізна руда", "price": 45, "probability": 0.12, "type": "mineral", "id": 33},
        {"name": "🪙 Золота руда", "price": 120, "probability": 0.08, "type": "mineral", "id": 44},
        {"name": "📜 Старовинний сувій", "price": 80, "probability": 0.10, "type": "magic", "id": 66},
        {"name": "🧪 Еліксир сили", "price": 200, "probability": 0.05, "type": "potion", "id": 77},
        {"name": "🌿 Цілюща трава", "price": 25, "probability": 0.14, "type": "potion", "id": 88},
        {"name": "⚔️ Меч воїна", "price": 350, "probability": 0.02, "type": "weapon", "id": 99},
        {"name": "🚗 Кузов автомобіля", "price": 900, "probability": 0.015, "type": "car_part", "id": 100},
        {"name": "⚙️ Двигун автомобіля", "price": 1200, "probability": 0.012, "type": "car_part", "id": 101},
        {"name": "🛞 Колеса автомобіля", "price": 800, "probability": 0.018, "type": "car_part", "id": 102},
        
        # НОВІ ПРЕДМЕТИ - МІНЕРАЛИ ТА РУДИ
        {"name": "💎 Діамант", "price": 1500, "probability": 0.005, "type": "mineral", "id": 201},
        {"name": "🔴 Рубін", "price": 800, "probability": 0.008, "type": "mineral", "id": 202},
        {"name": "🔵 Сапфір", "price": 750, "probability": 0.008, "type": "mineral", "id": 203},
        {"name": "🟢 Смарагд", "price": 900, "probability": 0.007, "type": "mineral", "id": 204},
        {"name": "🟡 Топаз", "price": 600, "probability": 0.01, "type": "mineral", "id": 205},
        {"name": "🪨 Обсидіан", "price": 400, "probability": 0.02, "type": "mineral", "id": 206},
        {"name": "⛏️ Мідна руда", "price": 60, "probability": 0.1, "type": "mineral", "id": 207},
        {"name": "⚫ Вугілля", "price": 30, "probability": 0.15, "type": "mineral", "id": 208},
        {"name": "🪨 Кремінь", "price": 20, "probability": 0.18, "type": "mineral", "id": 209},
        
        # НОВІ ПРЕДМЕТИ - МАГІЧНІ
        {"name": "🔮 Кристал мудрості", "price": 1200, "probability": 0.006, "type": "magic", "id": 210},
        {"name": "📜 Сувій телепортації", "price": 1500, "probability": 0.004, "type": "magic", "id": 211},
        {"name": "✨ Зоряний пил", "price": 600, "probability": 0.015, "type": "magic", "id": 212},
        {"name": "🔮 Око дракона", "price": 2000, "probability": 0.003, "type": "magic", "id": 213},
        {"name": "💫 Місячний камінь", "price": 950, "probability": 0.007, "type": "magic", "id": 214},
        
        # НОВІ ПРЕДМЕТИ - ЗІЛЛЯ
        {"name": "🧪 Еліксир невидимості", "price": 1800, "probability": 0.005, "type": "potion", "id": 215},
        {"name": "🧴 Зілля здоров'я", "price": 300, "probability": 0.025, "type": "potion", "id": 216},
        {"name": "⚗️ Еліксир швидкості", "price": 1200, "probability": 0.008, "type": "potion", "id": 217},
        {"name": "🧪 Зілля удачі", "price": 2500, "probability": 0.002, "type": "potion", "id": 218},
        {"name": "🌡️ Антидот", "price": 400, "probability": 0.02, "type": "potion", "id": 219},
        
        # НОВІ ПРЕДМЕТИ - ЗБРОЯ
        {"name": "🛡️ Щит героя", "price": 800, "probability": 0.012, "type": "weapon", "id": 220},
        {"name": "🏹 Лук снайпера", "price": 1100, "probability": 0.009, "type": "weapon", "id": 221},
        {"name": "⚔️ Двосічний меч", "price": 1600, "probability": 0.006, "type": "weapon", "id": 222},
        {"name": "🔪 Кинджал тіні", "price": 700, "probability": 0.015, "type": "weapon", "id": 223},
        {"name": "🗡️ Короткий меч", "price": 450, "probability": 0.03, "type": "weapon", "id": 224},
        
        # НОВІ ПРЕДМЕТИ - АВТОЗАПЧАСТИНИ
        {"name": "🚗 Спортивний кузов", "price": 2500, "probability": 0.004, "type": "car_part", "id": 225},
        {"name": "⚙️ Турбодвигун", "price": 3000, "probability": 0.003, "type": "car_part", "id": 226},
        {"name": "🛞 Спортивні диски", "price": 1500, "probability": 0.007, "type": "car_part", "id": 227},
        {"name": "💺 Шкіряний салон", "price": 1800, "probability": 0.006, "type": "car_part", "id": 228},
        {"name": "🔊 Аудіосистема", "price": 1200, "probability": 0.01, "type": "car_part", "id": 229},
        
        # СУПЕР РІДКІСНІ ПРЕДМЕТИ (10 штук)
        {"name": "👑 Корона короля", "price": 10000, "probability": 0.001, "type": "legendary", "id": 300},
        {"name": "🐉 Яйце дракона", "price": 15000, "probability": 0.0008, "type": "legendary", "id": 301},
        {"name": "⚡ Громовий жезл", "price": 12000, "probability": 0.0009, "type": "legendary", "id": 302},
        {"name": "🌌 Космічний артефакт", "price": 20000, "probability": 0.0005, "type": "legendary", "id": 303},
        {"name": "💀 Череп демона", "price": 8000, "probability": 0.0012, "type": "legendary", "id": 304},
        {"name": "🦄 Ріг єдинорога", "price": 13000, "probability": 0.0007, "type": "legendary", "id": 305},
        {"name": "🧿 Амулет безсмертя", "price": 25000, "probability": 0.0004, "type": "legendary", "id": 306},
        {"name": "⚗️ Філософський камінь", "price": 30000, "probability": 0.0003, "type": "legendary", "id": 307},
        {"name": "🔱 Тризуб Посейдона", "price": 18000, "probability": 0.0006, "type": "legendary", "id": 308},
        {"name": "🌟 Зірка бажань", "price": 35000, "probability": 0.0002, "type": "legendary", "id": 309},
    ]

class ItemShop:
    ITEMS = [
        # Базові предмети для покупки
        {"id": 11, "name": "🪨 Камінь", "price": 50, "category": "mineral"},
        {"id": 207, "name": "⛏️ Мідна руда", "price": 120, "category": "mineral"},
        {"id": 208, "name": "⚫ Вугілля", "price": 80, "category": "mineral"},
        {"id": 209, "name": "🪨 Кремінь", "price": 60, "category": "mineral"},
        {"id": 33, "name": "⛏️ Залізна руда", "price": 200, "category": "mineral"},
        
        # Магічні предмети
        {"id": 88, "name": "🌿 Цілюща трава", "price": 100, "category": "potion"},
        {"id": 66, "name": "📜 Старовинний сувій", "price": 250, "category": "magic"},
        {"id": 212, "name": "✨ Зоряний пил", "price": 800, "category": "magic"},
        {"id": 219, "name": "🌡️ Антидот", "price": 500, "category": "potion"},
        
        # Зброя
        {"id": 224, "name": "🗡️ Короткий меч", "price": 600, "category": "weapon"},
        {"id": 223, "name": "🔪 Кинджал тіні", "price": 900, "category": "weapon"},
        {"id": 220, "name": "🛡️ Щит героя", "price": 1000, "category": "weapon"},
        
        # Автозапчастини
        {"id": 100, "name": "🚗 Кузов автомобіля", "price": 1200, "category": "car_part"},
        {"id": 102, "name": "🛞 Колеса автомобіля", "price": 1000, "category": "car_part"},
        {"id": 229, "name": "🔊 Аудіосистема", "price": 1500, "category": "car_part"},
    ]

# Групування предметів по категоріям
ITEMS_BY_CATEGORY = {}
for item in ItemShop.ITEMS:
    category = item["category"]
    if category not in ITEMS_BY_CATEGORY:
        ITEMS_BY_CATEGORY[category] = []
    ITEMS_BY_CATEGORY[category].append(item)

# Словник для швидкого пошуку предметів за ID
ITEM_BY_ID = {item["id"]: item for item in ItemRoulettePrizes.PRIZES}
class CraftingRecipes:
    RECIPES = [
        # Існуючі рецепти
        {
            "id": 1,
            "name": "💎 Кальє з алмазу",
            "result": "💎 Кальє з алмазу",
            "result_price": 1200,
            "result_type": "jewelry",
            "cost": 200,
            "ingredients": [
                {"name": "💎 Алмаз", "quantity": 1},
                {"name": "🔮 Містичний кристал", "quantity": 1}
            ]
        },
        {
            "id": 2,
            "name": "🚗 Випадкова машина",
            "result": "random_car",
            "result_type": "car",
            "cost": 500,
            "ingredients": [
                {"name": "🚗 Кузов автомобіля", "quantity": 1},
                {"name": "⚙️ Двигун автомобіля", "quantity": 1},
                {"name": "🛞 Колеса автомобіля", "quantity": 1}
            ]
        },
        
        # НОВІ РЕЦЕПТИ - ЮВЕЛІРКА
        {
            "id": 3,
            "name": "👑 Проста корона",
            "result": "👑 Проста корона",
            "result_price": 3000,
            "result_type": "jewelry",
            "cost": 500,
            "ingredients": [
                {"name": "🪙 Золота руда", "quantity": 3},
                {"name": "🔴 Рубін", "quantity": 1}
            ]
        },
        {
            "id": 4,
            "name": "💍 Перстень магії",
            "result": "💍 Перстень магії",
            "result_price": 2500,
            "result_type": "jewelry",
            "cost": 400,
            "ingredients": [
                {"name": "🟢 Смарагд", "quantity": 1},
                {"name": "🔮 Містичний кристал", "quantity": 2}
            ]
        },
        
        # НОВІ РЕЦЕПТИ - ЗБРОЯ
        {
            "id": 5,
            "name": "⚔️ Легендарний меч",
            "result": "⚔️ Легендарний меч",
            "result_price": 5000,
            "result_type": "weapon",
            "cost": 800,
            "ingredients": [
                {"name": "⚔️ Меч воїна", "quantity": 1},
                {"name": "💎 Діамант", "quantity": 1},
                {"name": "⛏️ Залізна руда", "quantity": 5}
            ]
        },
        {
            "id": 6,
            "name": "🏹 Ельфійський лук",
            "result": "🏹 Ельфійський лук",
            "result_price": 3500,
            "result_type": "weapon",
            "cost": 600,
            "ingredients": [
                {"name": "🏹 Лук снайпера", "quantity": 1},
                {"name": "💫 Місячний камінь", "quantity": 1},
                {"name": "🌿 Цілюща трава", "quantity": 3}
            ]
        },
        
        # НОВІ РЕЦЕПТИ - МАГІЧНІ ПРЕДМЕТИ
        {
            "id": 7,
            "name": "🔮 Сфера пророцтв",
            "result": "🔮 Сфера пророцтв",
            "result_price": 6000,
            "result_type": "magic",
            "cost": 1000,
            "ingredients": [
                {"name": "🔮 Кристал мудрості", "quantity": 1},
                {"name": "✨ Зоряний пил", "quantity": 3},
                {"name": "📜 Старовинний сувій", "quantity": 2}
            ]
        },
        {
            "id": 8,
            "name": "🧪 Великий еліксир",
            "result": "🧪 Великий еліксир",
            "result_price": 4000,
            "result_type": "potion",
            "cost": 700,
            "ingredients": [
                {"name": "🧪 Еліксир сили", "quantity": 1},
                {"name": "🧴 Зілля здоров'я", "quantity": 2},
                {"name": "🌡️ Антидот", "quantity": 1}
            ]
        },
        
        # НОВІ РЕЦЕПТИ - АВТОМОБІЛІ
        {
            "id": 9,
            "name": "🚓 Поліцейська машина",
            "result": "🚓 Поліцейська машина",
            "result_price": 15000,
            "result_type": "car",
            "cost": 2000,
            "ingredients": [
                {"name": "🚗 Спортивний кузов", "quantity": 1},
                {"name": "⚙️ Турбодвигун", "quantity": 1},
                {"name": "🛞 Спортивні диски", "quantity": 1},
                {"name": "🔊 Аудіосистема", "quantity": 1}
            ]
        },
        {
            "id": 10,
            "name": "🚚 Вантажівка",
            "result": "🚚 Вантажівка",
            "result_price": 12000,
            "result_type": "car",
            "cost": 1500,
            "ingredients": [
                {"name": "🚗 Кузов автомобіля", "quantity": 2},
                {"name": "⚙️ Двигун автомобіля", "quantity": 2},
                {"name": "🛞 Колеса автомобіля", "quantity": 6}
            ]
        },
        
        # ЛЕГЕНДАРНІ РЕЦЕПТИ
        {
            "id": 11,
            "name": "🐉 Драконічний меч",
            "result": "🐉 Драконічний меч",
            "result_price": 25000,
            "result_type": "legendary",
            "cost": 5000,
            "ingredients": [
                {"name": "⚔️ Легендарний меч", "quantity": 1},
                {"name": "🐉 Яйце дракона", "quantity": 1},
                {"name": "🔮 Око дракона", "quantity": 1}
            ]
        },
        {
            "id": 12,
            "name": "🌟 Артефакт богів",
            "result": "🌟 Артефакт богів",
            "result_price": 50000,
            "result_type": "legendary",
            "cost": 10000,
            "ingredients": [
                {"name": "👑 Корона короля", "quantity": 1},
                {"name": "🌌 Космічний артефакт", "quantity": 1},
                {"name": "🧿 Амулет безсмертя", "quantity": 1},
                {"name": "⚗️ Філософський камінь", "quantity": 1}
            ]
        }
    ]
class Cars:
    CARS = [
        # Економ класс
        {"name": "Hyundai Solaris", "class": "economy", "price": 4000, "probability": 0.4},
        {"name": "Kia Rio", "class": "economy", "price": 6000, "probability": 0.3},
        {"name": "Renault Logan", "class": "economy", "price": 7000, "probability": 0.3},
        # Комфорт класс
        {"name": "Toyota Camry", "class": "comfort", "price": 11000, "probability": 0.5},
        {"name": "Passat B7", "class": "comfort", "price": 15000, "probability": 0.5},
        # Бізнес класс
        {"name": "Mercedes-Benz E-Class", "class": "business", "price": 22000, "probability": 0.34},
        {"name": "BMW 5 Series", "class": "business", "price": 22000, "probability": 0.33},
        {"name": "Audi A6", "class": "business", "price": 25000, "probability": 0.33},
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
        {"name": "🐔 Курка", "price": 100, "income": 5, "emoji": "🐔", "max_count": 4},
        {"name": "🐄 Корова", "price": 500, "income": 25, "emoji": "🐄", "max_count": 4},
        {"name": "🐖 Свиня", "price": 300, "income": 15, "emoji": "🐖", "max_count": 4},
        {"name": "🐑 Вівця", "price": 200, "income": 10, "emoji": "🐑", "max_count": 4},
        {"name": "🐎 Кінь", "price": 1000, "income": 50, "emoji": "🐎", "max_count": 4},
        {"name": "🐫 Верблюд", "price": 2000, "income": 100, "emoji": "🐫", "max_count": 4},
        {"name": "🐘 Слон", "price": 5000, "income": 250, "emoji": "🐘", "max_count": 4},
        {"name": "🦒 Жирафа", "price": 3000, "income": 150, "emoji": "🦒", "max_count": 4},
        {"name": "🐅 Тигр", "price": 8000, "income": 400, "emoji": "🐅", "max_count": 4},
        {"name": "🐉 Дракон", "price": 15000, "income": 750, "emoji": "🐉", "max_count": 4}
    ]

class RealEstate:
    PROPERTIES = [
        {"name": "🏠 Будинок", "price": 1000, "income": 50, "max_count": 2},
        {"name": "🏢 Квартира", "price": 500, "income": 25, "max_count": 2},
        {"name": "🏬 Офіс", "price": 3000, "income": 150, "max_count": 2},
        {"name": "🏪 Магазин", "price": 2000, "income": 100, "max_count": 2},
        {"name": "🏨 Готель", "price": 10000, "income": 500, "max_count": 2},
        {"name": "🏭 Завод", "price": 25000, "income": 1250, "max_count": 2},
        {"name": "🏛️ Банк", "price": 50000, "income": 2500, "max_count": 2},
        {"name": "🗼 Вежа", "price": 100000, "income": 5000, "max_count": 2}
    ]

class Roles:
    ROLES = [
        {"id": 1, "name": "Фермер", "price": 550, "description": "Дозволяє купляти 6 одиниць одного товару, +6% до пасивного доходу"},
        {"id": 2, "name": "Колектор", "price": 890, "description": "Дозволяє купувати 4 одиниці нерухомості, +5% до пасивного доходу"},
        {"id": 3, "name": "Студент", "price": 920, "description": "+5% до XP, ліміт питань до 25 в день"},
        {"id": 4, "name": "Активний", "price": 980, "description": "+3% до тапів, ліміт тапів до 2500 в день"},
        {"id": 5, "name": "Щасливчик", "price": 1100, "description": "Бонус 60 монет при виграші в рулетці"},
        {"id": 6, "name": "Воїн", "price": 1300, "description": "Бонус 50 монет при виграші в PvP"},
        {"id": 7, "name": "БАНКІР", "price": 7300, "description": "Отримує комісії, без комісій у продажах, +25 монет/6 годин"}
    ]

class Prefixes:
    PREFIXES = [
        {"id": 371, "name": "Кіт", "price": 800},
        {"id": 482, "name": "Бандит", "price": 910},
        {"id": 228, "name": "Вор", "price": 1230},
        {"id": 567, "name": "Легенда", "price": 1400},
        {"id": 566, "name": "Босс", "price": 1450},
        {"id": 577, "name": "Геймер", "price": 1500},
        {"id": 666, "name": "Опасний", "price": 1670},
        {"id": 888, "name": "Надзиратель⚜️", "price": 2100},
        {"id": 999, "name": "♻️", "price": 3200},
        {"id": 987, "name": "⚠️", "price": 4500},
        {"id": 876, "name": "🔱", "price": 5600}
    ]

class DailyTasks:
    TASKS = [
        {"type": "spin_roulette", "target": 2, "reward": 50, "description": "Прокрути рулетку 2 рази"},
        {"type": "tap_count", "target": 500, "reward": 30, "description": "Зроби 500 тапів"},
        {"type": "tap_count", "target": 1000, "reward": 60, "description": "Зроби 1000 тапів"},
        {"type": "play_minigames", "target": 3, "reward": 40, "description": "Зіграй 3 рази у міні-ігри"},
        {"type": "correct_answers", "target": 5, "reward": 60, "description": "Дайте 5 правильних відповідей"},
        {"type": "buy_animals", "target": 2, "reward": 80, "description": "Купи 2 тварини"}
    ]


# ========== БАЗОВІ ФУНКЦІЇ ==========

# ========== СИСТЕМА КРЕДИТІВ - ФУНКЦІЇ ==========
def get_user_active_credits(user_id: int) -> List[Dict]:
    """Отримати активні кредити гравця"""
    cursor.execute("""
        SELECT uc.id, uc.credit_type, uc.amount, uc.taken_date, uc.due_date, 
               uc.remaining_amount, uc.status, ct.name, ct.interest_rate
        FROM user_credits uc
        JOIN credit_types ct ON uc.credit_type = ct.id
        WHERE uc.user_id = ? AND uc.status = 'active'
        ORDER BY uc.taken_date DESC
    """, (user_id,))
    
    credits = []
    for row in cursor.fetchall():
        credit_id, credit_type, amount, taken_date, due_date, remaining, status, name, interest = row
        credits.append({
            "id": credit_id,
            "type_id": credit_type,
            "amount": amount,
            "taken_date": taken_date,
            "due_date": due_date,
            "remaining": remaining,
            "status": status,
            "name": name,
            "interest_rate": interest
        })
    return credits

def get_user_credit_history(user_id: int) -> List[Dict]:
    """Отримати історію кредитів гравця"""
    cursor.execute("""
        SELECT ch.credit_type, ch.amount, ch.taken_date, ch.closed_date, ch.status, ct.name
        FROM credit_history ch
        JOIN credit_types ct ON ch.credit_type = ct.id
        WHERE ch.user_id = ?
        ORDER BY ch.taken_date DESC
        LIMIT 10
    """, (user_id,))
    
    history = []
    for row in cursor.fetchall():
        credit_type, amount, taken_date, closed_date, status, name = row
        history.append({
            "type_id": credit_type,
            "amount": amount,
            "taken_date": taken_date,
            "closed_date": closed_date,
            "status": status,
            "name": name
        })
    return history

def calculate_credit_interest(amount: int, interest_rate: int, term_hours: int) -> int:
    """Розрахувати загальні відсотки по кредиту"""
    # Відсотки розраховуються за весь термін
    total_interest = (amount * interest_rate) // 100
    return total_interest

def can_take_credit(user_id: int, credit_type_id: int, amount: int) -> Dict:
    """Перевірити чи може гравець взяти кредит"""
    credit_type = next((ct for ct in CreditSystem.CREDIT_TYPES if ct["id"] == credit_type_id), None)
    if not credit_type:
        return {"can": False, "reason": "❌ Тип кредиту не знайдено!"}
    
    user_level = get_user_level(user_id)
    if user_level < credit_type["min_level"]:
        return {"can": False, "reason": f"❌ Потрібен {credit_type['min_level']} рівень! (у вас {user_level})"}
    
    if amount > credit_type["max_amount"]:
        return {"can": False, "reason": f"❌ Максимальна сума: {credit_type['max_amount']:,} ✯"}
    
    if amount < 100:
        return {"can": False, "reason": "❌ Мінімальна сума: 100 ✯"}
    
    # Перевіряємо чи не перевищує кредит 50% від загального доходу
    total_income = get_total_passive_income(user_id)
    max_recommended = total_income * 12  # Максимум - дохід за 12 годин
    if amount > max_recommended and total_income > 0:
        return {"can": False, "reason": f"❌ Занадто великий кредит! Максимум: {max_recommended:,} ✯"}
    
    # Перевіряємо чи немає вже активних кредитів
    active_credits = get_user_active_credits(user_id)
    if active_credits:
        return {"can": False, "reason": "❌ У вас вже є активний кредит!"}
    
    return {"can": True, "reason": "✅ Можна взяти кредит!"}

def take_credit(user_id: int, credit_type_id: int, amount: int) -> bool:
    """Взяти кредит"""
    check = can_take_credit(user_id, credit_type_id, amount)
    if not check["can"]:
        return False
    
    credit_type = next((ct for ct in CreditSystem.CREDIT_TYPES if ct["id"] == credit_type_id), None)
    if not credit_type:
        return False
    
    # Розраховуємо загальну суму до сплати
    total_interest = calculate_credit_interest(amount, credit_type["interest_rate"], credit_type["term_hours"])
    total_amount = amount + total_interest
    
    # Додаємо кредит
    taken_date = datetime.now()
    due_date = taken_date + timedelta(hours=credit_type["term_hours"])
    next_payment = taken_date + timedelta(hours=1)  # Перша виплата через годину
    
    cursor.execute("""
        INSERT INTO user_credits (user_id, credit_type, amount, taken_date, due_date, remaining_amount, next_payment_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, credit_type_id, amount, taken_date.isoformat(), due_date.isoformat(), total_amount, next_payment.isoformat()))
    
    # Додаємо в історію
    cursor.execute("""
        INSERT INTO credit_history (user_id, credit_type, amount, taken_date, status)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, credit_type_id, amount, taken_date.isoformat(), 'active'))
    
    # Видаємо гроші гравцю
    add_user_coins(user_id, amount)
    
    conn.commit()
    return True

def process_credit_payments():
    """Обробити виплати по кредитах (викликати кожну годину)"""
    current_time = datetime.now()
    
    # Знаходимо кредити, по яких треба зробити виплату
    cursor.execute("""
        SELECT uc.id, uc.user_id, uc.remaining_amount, uc.amount, ct.interest_rate, ct.term_hours
        FROM user_credits uc
        JOIN credit_types ct ON uc.credit_type = ct.id
        WHERE uc.status = 'active' AND uc.next_payment_date <= ?
    """, (current_time.isoformat(),))
    
    credits_to_process = cursor.fetchall()
    
    for credit in credits_to_process:
        credit_id, user_id, remaining, original_amount, interest_rate, term_hours = credit
        
        # Розраховуємо щогодинну виплату
        total_interest = calculate_credit_interest(original_amount, interest_rate, term_hours)
        total_amount = original_amount + total_interest
        hourly_payment = total_amount // term_hours
        
        # Перевіряємо чи вистачає грошей у гравця
        user_coins = get_user_coins(user_id)
        user_income = get_total_passive_income(user_id)
        
        if user_coins >= hourly_payment:
            # Списуємо виплату
            cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (hourly_payment, user_id))
            cursor.execute("UPDATE user_credits SET remaining_amount = remaining_amount - ? WHERE id = ?", (hourly_payment, credit_id))
            
            # Записуємо виплату
            cursor.execute("""
                INSERT INTO credit_payments (credit_id, payment_date, amount, payment_type)
                VALUES (?, ?, ?, ?)
            """, (credit_id, current_time.isoformat(), hourly_payment, 'auto'))
            
            # Оновлюємо наступну дату виплати
            next_payment = current_time + timedelta(hours=1)
            cursor.execute("UPDATE user_credits SET next_payment_date = ? WHERE id = ?", (next_payment.isoformat(), credit_id))
            
            print(f"💳 Виплата по кредиту {credit_id}: {hourly_payment} ✯")
            
        else:
            # Не вистачає грошей - мітка про прострочення
            cursor.execute("UPDATE user_credits SET status = 'overdue' WHERE id = ?", (credit_id,))
            print(f"⚠️ Прострочення по кредиту {credit_id}")
        
        # Перевіряємо чи кредит повністю погашено
        cursor.execute("SELECT remaining_amount FROM user_credits WHERE id = ?", (credit_id,))
        new_remaining = cursor.fetchone()[0]
        
        if new_remaining <= 0:
            cursor.execute("UPDATE user_credits SET status = 'paid' WHERE id = ?", (credit_id,))
            cursor.execute("UPDATE credit_history SET closed_date = ?, status = 'paid' WHERE user_id = ? AND credit_type = ? AND status = 'active'", 
                          (current_time.isoformat(), user_id, credit_id))
            print(f"✅ Кредит {credit_id} повністю погашено!")
    
    conn.commit()

def can_repay_credit_early(user_id: int, credit_id: int) -> Dict:
    """Перевірити чи можна погасити кредит достроково"""
    cursor.execute("""
        SELECT uc.remaining_amount, uc.amount, ct.interest_rate
        FROM user_credits uc
        JOIN credit_types ct ON uc.credit_type = ct.id
        WHERE uc.id = ? AND uc.user_id = ? AND uc.status = 'active'
    """, (credit_id, user_id))
    
    result = cursor.fetchone()
    if not result:
        return {"can": False, "reason": "❌ Кредит не знайдено!"}
    
    remaining, original_amount, interest_rate = result
    
    # При достроковому погашенні - знижка 20% на відсотки
    discount = (original_amount * interest_rate * 20) // 10000
    final_amount = remaining - discount
    
    user_coins = get_user_coins(user_id)
    if user_coins < final_amount:
        return {"can": False, "reason": f"❌ Недостатньо монет! Потрібно {final_amount:,} ✯"}
    
    return {"can": True, "reason": "✅ Можна погасити достроково!", "amount": final_amount, "discount": discount}

def repay_credit_early(user_id: int, credit_id: int) -> bool:
    """Погасити кредит достроково"""
    check = can_repay_credit_early(user_id, credit_id)
    if not check["can"]:
        return False
    
    final_amount = check["amount"]
    
    # Списуємо гроші
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (final_amount, user_id))
    
    # Закриваємо кредит
    current_time = datetime.now()
    cursor.execute("UPDATE user_credits SET status = 'paid_early', remaining_amount = 0 WHERE id = ?", (credit_id,))
    cursor.execute("UPDATE credit_history SET closed_date = ?, status = 'paid_early' WHERE user_id = ? AND status = 'active'", 
                  (current_time.isoformat(), user_id))
    
    # Записуємо виплату
    cursor.execute("""
        INSERT INTO credit_payments (credit_id, payment_date, amount, payment_type)
        VALUES (?, ?, ?, ?)
    """, (credit_id, current_time.isoformat(), final_amount, 'early'))
    
    conn.commit()
    return True# ========== СИСТЕМА КРЕДИТІВ - МЕНЮ ==========
def build_bank_menu(user_id: int):
    """Побудувати меню банку"""
    kb = InlineKeyboardMarkup(row_width=2)
    
    kb.add(
        InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"),
        InlineKeyboardButton("📊 Мої кредити", callback_data="bank_my_credits")
    )
    kb.add(
        InlineKeyboardButton("💳 Виплатити", callback_data="bank_repay"),
        InlineKeyboardButton("📋 Історія", callback_data="bank_history")
    )
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    return kb

def build_credits_menu(user_id: int):
    """Побудувати меню вибору кредиту"""
    user_level = get_user_level(user_id)
    active_credits = get_user_active_credits(user_id)
    has_active_credit = len(active_credits) > 0
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for credit_type in CreditSystem.CREDIT_TYPES:
        if user_level >= credit_type["min_level"] and not has_active_credit:
            button_text = f"{credit_type['name']} - до {credit_type['max_amount']:,} ✯"
            callback_data = f"credit_choose_{credit_type['id']}"
        elif has_active_credit:
            button_text = f"🔴 {credit_type['name']} - є активний кредит"
            callback_data = "credit_has_active"
        else:
            button_text = f"🔴 {credit_type['name']} - р. {credit_type['min_level']}+"
            callback_data = "credit_level_low"
        
        kb.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    if has_active_credit:
        kb.add(InlineKeyboardButton("📊 Мої кредити", callback_data="bank_my_credits"))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    return kb

def build_my_credits_menu(user_id: int):
    """Побудувати меню моїх кредитів"""
    active_credits = get_user_active_credits(user_id)
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if not active_credits:
        kb.add(InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"))
    else:
        for credit in active_credits:
            # Розраховуємо час до кінця
            due_date = datetime.fromisoformat(credit['due_date'])
            time_left = due_date - datetime.now()
            hours_left = max(0, int(time_left.total_seconds() // 3600))
            
            button_text = f"{credit['name']} - {credit['remaining']:,} ✯ ({hours_left}г)"
            kb.add(InlineKeyboardButton(button_text, callback_data=f"credit_view_{credit['id']}"))
    
    kb.add(InlineKeyboardButton("📋 Історія", callback_data="bank_history"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    return kb

def build_repay_menu(user_id: int):
    """Побудувати меню виплат"""
    active_credits = get_user_active_credits(user_id)
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if not active_credits:
        kb.add(InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"))
    else:
        for credit in active_credits:
            check = can_repay_credit_early(user_id, credit['id'])
            if check["can"]:
                button_text = f"🟢 {credit['name']} - {check['amount']:,} ✯"
                callback_data = f"credit_repay_{credit['id']}"
            else:
                button_text = f"🔴 {credit['name']} - {check['reason']}"
                callback_data = "credit_cannot_repay"
            
            kb.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    return 
# ========== БІЗНЕС СИСТЕМА - ФУНКЦІЇ ==========
def get_user_business_license(user_id: int) -> Dict:
    """Отримати інформацію про ліцензію гравця"""
    cursor.execute("""
        SELECT ul.license_id, ul.max_businesses, bl.name, bl.price
        FROM user_business_licenses ul
        JOIN business_licenses bl ON ul.license_id = bl.id
        WHERE ul.user_id = ?
    """, (user_id,))
    
    result = cursor.fetchone()
    if result:
        license_id, max_businesses, name, price = result
        return {
            "license_id": license_id,
            "max_businesses": max_businesses,
            "name": name,
            "price": price
        }
    else:
        # Створюємо запис за замовчуванням
        cursor.execute(
            "INSERT INTO user_business_licenses (user_id, license_id, max_businesses, purchased_date) VALUES (?, 1, 2, ?)",
            (user_id, datetime.now().isoformat())
        )
        conn.commit()
        return {
            "license_id": 1,
            "max_businesses": 2,
            "name": "🟢 BI License",
            "price": 16400
        }

def get_user_businesses(user_id: int) -> List[Dict]:
    """Отримати бізнеси гравця"""
    cursor.execute("""
        SELECT ub.id, ub.business_type, ub.business_name, ub.level, ub.income, 
               ub.purchased_date, bt.name, bt.base_price, bt.max_level
        FROM user_businesses ub
        JOIN business_types bt ON ub.business_type = bt.id
        WHERE ub.user_id = ?
        ORDER BY ub.purchased_date DESC
    """, (user_id,))
    
    businesses = []
    for row in cursor.fetchall():
        business_id, business_type, business_name, level, income, purchased_date, type_name, base_price, max_level = row
        businesses.append({
            "id": business_id,
            "type_id": business_type,
            "name": business_name,
            "level": level,
            "income": income,
            "purchased_date": purchased_date,
            "type_name": type_name,
            "base_price": base_price,
            "max_level": max_level
        })
    return businesses

def get_business_type_count(user_id: int, business_type: int) -> int:
    """Отримати кількість бізнесів певного типу у гравця"""
    cursor.execute("""
        SELECT COUNT(*) FROM user_businesses 
        WHERE user_id = ? AND business_type = ?
    """, (user_id, business_type))
    return cursor.fetchone()[0]

def can_buy_business(user_id: int, business_type_id: int) -> Dict:
    """Перевірити чи може гравець купити бізнес"""
    business = next((b for b in BusinessTypes.BUSINESSES if b["id"] == business_type_id), None)
    if not business:
        return {"can": False, "reason": "❌ Бізнес не знайдено!"}
    
    user_level = get_user_level(user_id)
    if user_level < business["min_level"]:
        return {"can": False, "reason": f"❌ Потрібен {business['min_level']} рівень! (у вас {user_level})"}
    
    # Перевіряємо ліміт бізнесів одного типу (макс. 2)
    same_type_count = get_business_type_count(user_id, business_type_id)
    if same_type_count >= 2:
        return {"can": False, "reason": f"❌ Максимум 2 бізнеси одного типу! (у вас {same_type_count})"}
    
    # Перевіряємо загальний ліміт бізнесів
    license_info = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    if len(user_businesses) >= license_info["max_businesses"]:
        return {"can": False, "reason": f"❌ Досягнуто ліміт бізнесів! ({license_info['max_businesses']})"}
    
    user_coins = get_user_coins(user_id)
    if user_coins < business["base_price"]:
        return {"can": False, "reason": f"❌ Недостатньо монет! Потрібно {business['base_price']} ✯"}
    
    return {"can": True, "reason": "✅ Можна купити бізнес!"}

def buy_business(user_id: int, business_type_id: int) -> bool:
    """Купити бізнес"""
    check = can_buy_business(user_id, business_type_id)
    if not check["can"]:
        return False
    
    business = next((b for b in BusinessTypes.BUSINESSES if b["id"] == business_type_id), None)
    if not business:
        return False
    
    # Списуємо монети
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", 
                   (business["base_price"], user_id))
    
    # Додаємо бізнес
    cursor.execute("""
        INSERT INTO user_businesses (user_id, business_type, business_name, level, income, purchased_date)
        VALUES (?, ?, ?, 1, ?, ?)
    """, (user_id, business_type_id, business["name"], business["base_income"], datetime.now().isoformat()))
    
    conn.commit()
    return True

def calculate_business_income(business_type_id: int, level: int) -> int:
    """Розрахувати дохід бізнесу за рівень"""
    business = next((b for b in BusinessTypes.BUSINESSES if b["id"] == business_type_id), None)
    if not business:
        return 0
    
    base_income = business["base_income"]
    multiplier = business["income_multiplier"]
    return int(base_income * (multiplier ** (level - 1)))

def calculate_upgrade_price(business_type_id: int, current_level: int) -> int:
    """Розрахувати ціну покращення бізнесу"""
    business = next((b for b in BusinessTypes.BUSINESSES if b["id"] == business_type_id), None)
    if not business:
        return 0
    
    base_price = business["base_price"]
    multiplier = business["upgrade_multiplier"]
    return int(base_price * (multiplier ** (current_level - 1)))

def can_upgrade_business(user_id: int, business_id: int) -> Dict:
    """Перевірити чи можна покращити бізнес"""
    cursor.execute("""
        SELECT ub.level, ub.business_type, ub.income, bt.max_level, bt.name
        FROM user_businesses ub
        JOIN business_types bt ON ub.business_type = bt.id
        WHERE ub.id = ? AND ub.user_id = ?
    """, (business_id, user_id))
    
    result = cursor.fetchone()
    if not result:
        return {"can": False, "reason": "❌ Бізнес не знайдено!"}
    
    level, business_type, income, max_level, business_name = result
    
    if level >= max_level:
        return {"can": False, "reason": f"❌ Бізнес вже максимального рівня! ({max_level})"}
    
    upgrade_price = calculate_upgrade_price(business_type, level)
    user_coins = get_user_coins(user_id)
    
    if user_coins < upgrade_price:
        return {"can": False, "reason": f"❌ Недостатньо монет! Потрібно {upgrade_price} ✯"}
    
    return {"can": True, "reason": "✅ Можна покращити бізнес!", "price": upgrade_price}

def upgrade_business(user_id: int, business_id: int) -> bool:
    """Покращити бізнес"""
    check = can_upgrade_business(user_id, business_id)
    if not check["can"]:
        return False
    
    cursor.execute("""
        SELECT business_type, level FROM user_businesses 
        WHERE id = ? AND user_id = ?
    """, (business_id, user_id))
    
    result = cursor.fetchone()
    if not result:
        return False
    
    business_type, current_level = result
    upgrade_price = calculate_upgrade_price(business_type, current_level)
    new_level = current_level + 1
    new_income = calculate_business_income(business_type, new_level)
    
    # Списуємо монети та оновлюємо бізнес
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", 
                   (upgrade_price, user_id))
    cursor.execute("UPDATE user_businesses SET level = ?, income = ? WHERE id = ?", 
                   (new_level, new_income, business_id))
    
    conn.commit()
    return True

def get_total_business_income(user_id: int) -> int:
    """Отримати загальний дохід від усіх бізнесів"""
    businesses = get_user_businesses(user_id)
    total_income = sum(business["income"] for business in businesses)
    return total_income

def update_business_income_for_user(user_id: int):
    """Оновити дохід від бізнесів для гравця (кожні 6 годин)"""
    businesses = get_user_businesses(user_id)
    if not businesses:
        return
    
    total_income = get_total_business_income(user_id)
    
    # Додаємо дохід до балансу
    if total_income > 0:
        add_user_coins(user_id, total_income)
        print(f"💼 Нараховано {total_income} ✯ від бізнесів гравцю {user_id}")


# ========== СИСТЕМА КРЕДИТІВ - ОБРОБНИКИ ==========
@dp.callback_query_handler(lambda c: c.data == 'bank_loans')
async def cb_bank_loans(call: types.CallbackQuery):
    """Головне меню банку"""
    await call.answer()
    user_id = call.from_user.id
    
    active_credits = get_user_active_credits(user_id)
    total_debt = sum(credit['remaining'] for credit in active_credits)
    
    text = (
        f"🏦 <b>Банк - Кредитна система</b>\n\n"
        f"💼 Активних кредитів: {len(active_credits)}\n"
        f"💸 Загальний борг: {total_debt:,} ✯\n"
        f"💎 Ваш баланс: {get_user_coins(user_id):,} ✯\n"
        f"📈 Ваш дохід: {get_total_passive_income(user_id)} ✯/6 год\n\n"
        f"🚀 <b>Оберіть дію:</b>"
    )
    
    await call.message.edit_text(text, reply_markup=build_bank_menu(user_id))

@dp.callback_query_handler(lambda c: c.data == 'bank_credits')
async def cb_bank_credits(call: types.CallbackQuery):
    """Меню вибору кредиту"""
    await call.answer()
    user_id = call.from_user.id
    
    active_credits = get_user_active_credits(user_id)
    has_active_credit = len(active_credits) > 0
    
    if has_active_credit:
        text = (
            f"💰 <b>Взяття кредиту</b>\n\n"
            f"❌ У вас вже є активний кредит!\n\n"
            f"💡 Спочатку погасіть поточний кредит, щоб взяти новий."
        )
    else:
        text = (
            f"💰 <b>Взяття кредиту</b>\n\n"
            f"💎 Ваш баланс: {get_user_coins(user_id):,} ✯\n"
            f"🎯 Ваш рівень: {get_user_level(user_id)}\n"
            f"📈 Ваш дохід: {get_total_passive_income(user_id)} ✯/6 год\n\n"
            f"🏦 <b>Доступні кредити:</b>\n\n"
            f"🟢 - можна взяти\n"
            f"🔴 - потрібен вищий рівень\n\n"
            f"💡 Кредит автоматично погашається з вашого доходу!"
        )
    
    await call.message.edit_text(text, reply_markup=build_credits_menu(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith('credit_choose_'))
async def cb_credit_choose(call: types.CallbackQuery):
    """Вибір типу кредиту"""
    await call.answer()
    user_id = call.from_user.id
    credit_type_id = int(call.data.split('_')[2])
    
    credit_type = next((ct for ct in CreditSystem.CREDIT_TYPES if ct["id"] == credit_type_id), None)
    if not credit_type:
        await call.answer("❌ Тип кредиту не знайдено!", show_alert=True)
        return
    
    text = (
        f"🏦 <b>{credit_type['name']}</b>\n\n"
        f"📝 {credit_type['description']}\n\n"
        f"💰 Максимальна сума: {credit_type['max_amount']:,} ✯\n"
        f"📈 Відсоткова ставка: {credit_type['interest_rate']}%\n"
        f"⏰ Термін: {credit_type['term_hours']} годин\n"
        f"💎 Ваш баланс: {get_user_coins(user_id):,} ✯\n\n"
        f"💡 <b>Введіть суму кредиту:</b>\n"
        f"<code>/takecredit {credit_type_id} СУМА</code>\n\n"
        f"📝 <b>Приклад:</b>\n"
        f"<code>/takecredit {credit_type_id} 1000</code>\n"
        f"<code>/takecredit {credit_type_id} 5000</code>"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💰 Взяти максимальний", callback_data=f"credit_max_{credit_type_id}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_credits"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('credit_max_'))
async def cb_credit_max(call: types.CallbackQuery):
    """Взяття максимального кредиту"""
    await call.answer()
    user_id = call.from_user.id
    credit_type_id = int(call.data.split('_')[2])
    
    credit_type = next((ct for ct in CreditSystem.CREDIT_TYPES if ct["id"] == credit_type_id), None)
    if not credit_type:
        await call.answer("❌ Тип кредиту не знайдено!", show_alert=True)
        return
    
    max_amount = credit_type["max_amount"]
    
    if take_credit(user_id, credit_type_id, max_amount):
        total_interest = calculate_credit_interest(max_amount, credit_type["interest_rate"], credit_type["term_hours"])
        total_amount = max_amount + total_interest
        
        text = (
            f"🎉 <b>Кредит успішно видано!</b>\n\n"
            f"🏦 Тип: {credit_type['name']}\n"
            f"💰 Сума: {max_amount:,} ✯\n"
            f"📈 Відсотки: {total_interest:,} ✯\n"
            f"💸 Загалом до сплати: {total_amount:,} ✯\n"
            f"⏰ Термін: {credit_type['term_hours']} годин\n\n"
            f"💎 Новий баланс: {get_user_coins(user_id):,} ✯\n\n"
            f"💡 <b>Кредит автоматично погашатиметься з вашого доходу!</b>"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📊 Мої кредити", callback_data="bank_my_credits"))
        kb.add(InlineKeyboardButton("⬅️ Головне", callback_data="bank_loans"))
        
        await call.message.edit_text(text, reply_markup=kb)
    else:
        await call.answer("❌ Не вдалося взяти кредит!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'bank_my_credits')
async def cb_bank_my_credits(call: types.CallbackQuery):
    """Мої кредити"""
    await call.answer()
    user_id = call.from_user.id
    
    active_credits = get_user_active_credits(user_id)
    
    if not active_credits:
        text = (
            f"📊 <b>Мої кредити</b>\n\n"
            f"✅ У вас немає активних кредитів!\n\n"
            f"💡 Почніть з взяття першого кредиту для розвитку."
        )
    else:
        total_debt = sum(credit['remaining'] for credit in active_credits)
        text = (
            f"📊 <b>Мої кредити</b>\n\n"
            f"💼 Активних кредитів: {len(active_credits)}\n"
            f"💸 Загальний борг: {total_debt:,} ✯\n\n"
            f"🎯 Оберіть кредит для деталей:"
        )
    
    await call.message.edit_text(text, reply_markup=build_my_credits_menu(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith('credit_view_'))
async def cb_credit_view(call: types.CallbackQuery):
    """Перегляд деталей кредиту"""
    await call.answer()
    user_id = call.from_user.id
    credit_id = int(call.data.split('_')[2])
    
    cursor.execute("""
        SELECT uc.amount, uc.taken_date, uc.due_date, uc.remaining_amount, uc.status,
               ct.name, ct.interest_rate, ct.term_hours
        FROM user_credits uc
        JOIN credit_types ct ON uc.credit_type = ct.id
        WHERE uc.id = ? AND uc.user_id = ?
    """, (credit_id, user_id))
    
    result = cursor.fetchone()
    if not result:
        await call.answer("❌ Кредит не знайдено!", show_alert=True)
        return
    
    amount, taken_date, due_date, remaining, status, name, interest, term = result
    
    # Розраховуємо час до кінця
    due_datetime = datetime.fromisoformat(due_date)
    time_left = due_datetime - datetime.now()
    hours_left = max(0, int(time_left.total_seconds() // 3600))
    
    # Розраховуємо щогодинну виплату
    total_interest = calculate_credit_interest(amount, interest, term)
    total_amount = amount + total_interest
    hourly_payment = total_amount // term
    
    text = (
        f"📊 <b>Деталі кредиту</b>\n\n"
        f"🏦 Тип: {name}\n"
        f"💰 Початкова сума: {amount:,} ✯\n"
        f"📈 Відсоткова ставка: {interest}%\n"
        f"💸 Залишок боргу: {remaining:,} ✯\n"
        f"⏰ Залишилось: {hours_left} годин\n"
        f"💳 Щогодинна виплата: {hourly_payment} ✯\n"
        f"📅 Взяття: {taken_date[:16]}\n"
        f"📅 Кінець: {due_date[:16]}\n\n"
    )
    
    # Перевіряємо можливість дострокового погашення
    check = can_repay_credit_early(user_id, credit_id)
    if check["can"]:
        text += f"🟢 Дострокове погашення: {check['amount']:,} ✯ (знижка {check['discount']:,} ✯)"
    else:
        text += f"🔴 {check['reason']}"
    
    kb = InlineKeyboardMarkup()
    
    if check["can"]:
        kb.add(InlineKeyboardButton(f"💳 Виплатити ({check['amount']:,} ✯)", callback_data=f"credit_repay_{credit_id}"))
    
    kb.add(InlineKeyboardButton("📊 Мої кредити", callback_data="bank_my_credits"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'bank_repay')
async def cb_bank_repay(call: types.CallbackQuery):
    """Меню виплат кредитів"""
    await call.answer()
    user_id = call.from_user.id
    
    active_credits = get_user_active_credits(user_id)
    
    if not active_credits:
        text = (
            f"💳 <b>Виплата кредитів</b>\n\n"
            f"✅ У вас немає активних кредитів!\n\n"
            f"💡 Кредити автоматично погашаються з вашого доходу."
        )
    else:
        text = (
            f"💳 <b>Виплата кредитів</b>\n\n"
            f"💎 Ваш баланс: {get_user_coins(user_id):,} ✯\n"
            f"💼 Активних кредитів: {len(active_credits)}\n\n"
            f"🟢 - можна виплатити достроково\n"
            f"🔴 - недостатньо коштів\n\n"
            f"💡 Дострокове погашення дає знижку 20% на відсотки!"
        )
    
    await call.message.edit_text(text, reply_markup=build_repay_menu(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith('credit_repay_'))
async def cb_credit_repay(call: types.CallbackQuery):
    """Виплата кредиту достроково"""
    await call.answer()
    user_id = call.from_user.id
    credit_id = int(call.data.split('_')[2])
    
    if repay_credit_early(user_id, credit_id):
        text = (
            f"🎉 <b>Кредит успішно погашено!</b>\n\n"
            f"✅ Ви достроково погасили кредит\n"
            f"💰 Знижка на відсотки: активована\n"
            f"💎 Новий баланс: {get_user_coins(user_id):,} ✯\n\n"
            f"🚀 Тепер ви можете взяти новий кредит!"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"))
        kb.add(InlineKeyboardButton("📋 Історія", callback_data="bank_history"))
        kb.add(InlineKeyboardButton("⬅️ Головне", callback_data="bank_loans"))
        
        await call.message.edit_text(text, reply_markup=kb)
    else:
        await call.answer("❌ Не вдалося погасити кредит!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'bank_history')
async def cb_bank_history(call: types.CallbackQuery):
    """Історія кредитів"""
    await call.answer()
    user_id = call.from_user.id
    
    history = get_user_credit_history(user_id)
    active_credits = get_user_active_credits(user_id)
    
    text = (
        f"📋 <b>Історія кредитів</b>\n\n"
        f"💼 Активних: {len(active_credits)} кредитів\n"
        f"📊 Всього в історії: {len(history)} записів\n\n"
    )
    
    if not history:
        text += "📝 У вас ще не було кредитів.\n💡 Почніть з першого кредиту для розвитку!"
    else:
        text += "📅 <b>Останні кредити:</b>\n\n"
        for i, credit in enumerate(history[:5], 1):  # Показуємо останні 5
            status_emoji = "✅" if credit['status'] in ['paid', 'paid_early'] else "⏳" if credit['status'] == 'active' else "⚠️"
            date = credit['taken_date'][:10]
            text += f"{i}. {status_emoji} {credit['name']} - {credit['amount']:,} ✯ ({date})\n"
    
    kb = InlineKeyboardMarkup()
    if not active_credits:
        kb.add(InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"))
    kb.add(InlineKeyboardButton("📊 Мої кредити", callback_data="bank_my_credits"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data in ['credit_has_active', 'credit_level_low', 'credit_cannot_repay'])
async def cb_credit_errors(call: types.CallbackQuery):
    """Обробники помилок кредитної системи"""
    if call.data == 'credit_has_active':
        await call.answer("❌ У вас вже є активний кредит!", show_alert=True)
    elif call.data == 'credit_level_low':
        await call.answer("🔴 Потрібен вищий рівень!", show_alert=True)
    elif call.data == 'credit_cannot_repay':
        await call.answer("❌ Недостатньо коштів для виплати!", show_alert=True)

# ========== СИСТЕМА ЗАПИТІВ У ДРУЗІ - ФУНКЦІЇ ==========
def send_friend_request(from_user_id: int, from_username: str, to_user_id: int) -> bool:
    """Надіслати запит у друзі"""
    # Перевіряємо чи не відправляємо самому собі
    if from_user_id == to_user_id:
        return False
    
    # Перевіряємо чи вже є запит
    cursor.execute("""
        SELECT id FROM friend_requests 
        WHERE from_user_id = ? AND to_user_id = ? AND status = 'pending'
    """, (from_user_id, to_user_id))
    
    if cursor.fetchone():
        return False  # Вже є активний запит
    
    # Перевіряємо чи вже є в друзях
    cursor.execute("SELECT id FROM friends WHERE user_id = ? AND friend_id = ?", (from_user_id, to_user_id))
    if cursor.fetchone():
        return False  # Вже в друзях
    
    # Створюємо запит
    cursor.execute("""
        INSERT INTO friend_requests (from_user_id, from_username, to_user_id, created_date)
        VALUES (?, ?, ?, ?)
    """, (from_user_id, from_username, to_user_id, datetime.now().isoformat()))
    
    conn.commit()
    return True

def get_pending_friend_requests(user_id: int) -> List[Dict]:
    """Отримати запити у друзі для гравця"""
    cursor.execute("""
        SELECT fr.id, fr.from_user_id, fr.from_username, fr.created_date
        FROM friend_requests fr
        WHERE fr.to_user_id = ? AND fr.status = 'pending'
        ORDER BY fr.created_date DESC
    """, (user_id,))
    
    requests = []
    for row in cursor.fetchall():
        req_id, from_user_id, from_username, created_date = row
        requests.append({
            "id": req_id,
            "from_user_id": from_user_id,
            "from_username": from_username,
            "created_date": created_date
        })
    return requests

def get_friend_request_by_id(request_id: int, to_user_id: int) -> Optional[Dict]:
    """Отримати запит у друзі з перевіркою отримувача"""
    cursor.execute("""
        SELECT id, from_user_id, from_username, to_user_id, status, created_date
        FROM friend_requests 
        WHERE id = ? AND to_user_id = ? AND status = 'pending'
    """, (request_id, to_user_id))
    
    result = cursor.fetchone()
    if not result:
        return None
    
    return {
        "id": result[0],
        "from_user_id": result[1],
        "from_username": result[2],
        "to_user_id": result[3],
        "status": result[4],
        "created_date": result[5]
    }

def accept_friend_request(request_id: int, to_user_id: int) -> bool:
    """Прийняти запит у друзі з перевіркою прав"""
    try:
        # Отримуємо запит з перевіркою отримувача
        cursor.execute("""
            SELECT id, from_user_id, from_username, to_user_id, status, created_date
            FROM friend_requests 
            WHERE id = ? AND to_user_id = ? AND status = 'pending'
        """, (request_id, to_user_id))
        
        result = cursor.fetchone()
        if not result:
            print(f"❌ Запит {request_id} не знайдено або вже оброблено для користувача {to_user_id}")
            return False
        
        request_id, from_user_id, from_username, to_user_id, status, created_date = result
        
        # Отримуємо username того хто прийняв запит
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (to_user_id,))
        to_username_result = cursor.fetchone()
        to_username = to_username_result[0] if to_username_result else f"User{to_user_id}"
        
        # Додаємо в друзі обом гравцям
        try:
            # Додаємо друга для того хто прийняв запит
            cursor.execute(
                "INSERT OR IGNORE INTO friends (user_id, friend_id, friend_username, added_date) VALUES (?, ?, ?, ?)",
                (to_user_id, from_user_id, from_username, datetime.now().isoformat())
            )
            
            # Додаємо друга для того хто надіслав запит
            cursor.execute(
                "INSERT OR IGNORE INTO friends (user_id, friend_id, friend_username, added_date) VALUES (?, ?, ?, ?)",
                (from_user_id, to_user_id, to_username, datetime.now().isoformat())
            )
        except sqlite3.IntegrityError as e:
            print(f"ℹ️ Гравці {from_user_id} і {to_user_id} вже друзі: {e}")
        
        # Оновлюємо статус запиту
        cursor.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = ?", (request_id,))
        
        conn.commit()
        print(f"✅ Запит {request_id} прийнято - гравці {from_user_id} і {to_user_id} тепер друзі")
        return True
        
    except Exception as e:
        print(f"❌ Помилка прийняття запиту {request_id}: {e}")
        conn.rollback()
        return False

def reject_friend_request(request_id: int, to_user_id: int) -> bool:
    """Відхилити запит у друзі з перевіркою прав"""
    try:
        # Перевіряємо чи запит належить користувачу
        request = get_friend_request_by_id(request_id, to_user_id)
        if not request:
            print(f"❌ Запит {request_id} не знайдено для користувача {to_user_id}")
            return False
        
        cursor.execute("UPDATE friend_requests SET status = 'rejected' WHERE id = ?", (request_id,))
        conn.commit()
        print(f"✅ Запит {request_id} відхилено користувачем {to_user_id}")
        return cursor.rowcount > 0
    except Exception as e:
        print(f"❌ Помилка відхилення запиту {request_id}: {e}")
        return False

# ========== СИСТЕМА ЗАПИТІВ У ДРУЗІ - ОБРОБНИКИ ==========
@dp.callback_query_handler(lambda c: c.data == 'friends_requests')
async def cb_friends_requests(call: types.CallbackQuery):
    """Меню запитів у друзі"""
    await call.answer()
    user_id = call.from_user.id
    
    pending_requests = get_pending_friend_requests(user_id)
    
    if not pending_requests:
        text = (
            f"📨 <b>Запити у друзі</b>\n\n"
            f"✅ У вас немає нових запитів!\n\n"
            f"💡 Тут з'являться запити від інших гравців."
        )
        kb = InlineKeyboardMarkup()
    else:
        text = (
            f"📨 <b>Запити у друзі</b>\n\n"
            f"👥 У вас {len(pending_requests)} нових запитів:\n\n"
            f"🎯 <b>Оберіть запит для перегляду:</b>"
        )
        
        kb = InlineKeyboardMarkup(row_width=1)
        for request in pending_requests:
            kb.add(
                InlineKeyboardButton(
                    f"👤 {request['from_username']} (ID: {request['from_user_id']})", 
                    callback_data=f"friend_request_view_{request['id']}"
                )
            )
    
    kb.add(InlineKeyboardButton("📋 Список друзів", callback_data="friends_list"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_friends"))
    
    await call.message.edit_text(text, reply_markup=kb)

#990
@dp.message_handler(commands=['debug_requests'])
async def cmd_debug_requests(message: types.Message):
    """Дебаг-команда для перевірки запитів"""
    user_id = message.from_user.id
    
    cursor.execute("SELECT * FROM friend_requests WHERE to_user_id = ?", (user_id,))
    requests = cursor.fetchall()
    
    text = f"🔧 <b>Дебаг запитів для {user_id}</b>\n\n"
    
    if not requests:
        text += "❌ Немає запитів\n"
    else:
        for req in requests:
            text += f"ID: {req[0]}, Від: {req[1]}, До: {req[3]}, Статус: {req[4]}\n"
    
    await message.answer(text)

@dp.callback_query_handler(lambda c: c.data.startswith('friend_request_view_'))
async def cb_friend_request_view(call: types.CallbackQuery):
    """Перегляд конкретного запиту у друзі"""
    await call.answer()
    user_id = call.from_user.id
    request_id = int(call.data.split('_')[3])
    
    cursor.execute("""
        SELECT fr.from_user_id, fr.from_username, fr.created_date, p.level, p.coins
        FROM friend_requests fr
        JOIN players p ON fr.from_user_id = p.user_id
        WHERE fr.id = ? AND fr.to_user_id = ?
    """, (request_id, user_id))
    
    result = cursor.fetchone()
    if not result:
        await call.answer("❌ Запит не знайдено!", show_alert=True)
        return
    
    from_user_id, from_username, created_date, level, coins = result
    
    time_ago = datetime.now() - datetime.fromisoformat(created_date)
    hours_ago = int(time_ago.total_seconds() // 3600)
    
    text = (
        f"📨 <b>Запит у друзі</b>\n\n"
        f"👤 Гравець: {from_username}\n"
        f"🆔 ID: {from_user_id}\n"
        f"🎯 Рівень: {level}\n"
        f"💰 Баланс: {coins:,} ✯\n"
        f"⏰ Надіслано: {hours_ago} год. тому\n\n"
        f"🤝 Прийняти цей запит у друзі?"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Прийняти", callback_data=f"friend_accept_{request_id}"),
        InlineKeyboardButton("❌ Відхилити", callback_data=f"friend_reject_{request_id}")
    )
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="friends_requests"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('friend_accept_'))
async def cb_friend_accept(call: types.CallbackQuery):
    """Прийняти запит у друзі"""
    user_id = call.from_user.id
    request_id = int(call.data.split('_')[2])
    
    print(f"🔍 Спроба прийняти запит {request_id} від користувача {user_id}")
    
    # Отримуємо інформацію про запит
    cursor.execute("SELECT from_user_id, from_username FROM friend_requests WHERE id = ? AND to_user_id = ? AND status = 'pending'", 
                  (request_id, user_id))
    result = cursor.fetchone()
    
    if not result:
        await call.answer("❌ Запит не знайдено, вже оброблено або не для вас!", show_alert=True)
        print(f"❌ Запит {request_id} не знайдено для користувача {user_id}")
        return
    
    from_user_id, from_username = result
    
    if accept_friend_request(request_id, user_id):
        # Оновлюємо повідомлення для того хто прийняв
        try:
            await call.message.edit_text(
                f"✅ <b>ЗАПИТ ПРИЙНЯТО</b>\n\n"
                f"🤝 Ви тепер друзі з {from_username}!\n\n"
                f"🎉 Можете надсилати один одному гроші та спілкуватися!",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("💰 Надіслати гроші", callback_data=f"friends_transfer_{from_user_id}"),
                    InlineKeyboardButton("📋 Мої друзі", callback_data="friends_list")
                )
            )
        except Exception as e:
            print(f"❌ Помилка оновлення повідомлення: {e}")
        
        # Сповіщаємо того хто надіслав запит
        try:
            await bot.send_message(
                from_user_id,
                f"✅ <b>ВАШ ЗАПИТ ПРИЙНЯТО!</b>\n\n"
                f"👤 {call.from_user.username or call.from_user.full_name} прийняв ваш запит у друзі.\n\n"
                f"🎉 Тепер ви друзі!\n"
                f"💬 Можете надсилати один одному гроші!",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("💰 Надіслати гроші", callback_data=f"friends_transfer_{user_id}"),
                    InlineKeyboardButton("📋 Мої друзі", callback_data="friends_list")
                )
            )
        except Exception as e:
            print(f"❌ Не вдалось сповістити {from_user_id}: {e}")
        
        await call.answer("✅ Запит прийнято! Ви тепер друзі!", show_alert=False)
    else:
        await call.answer("❌ Не вдалося прийняти запит!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data.startswith('friend_reject_'))
async def cb_friend_reject(call: types.CallbackQuery):
    """Відхилити запит у друзі"""
    user_id = call.from_user.id
    request_id = int(call.data.split('_')[2])
    
    print(f"🔍 Спроба відхилити запит {request_id} від користувача {user_id}")
    
    # Отримуємо інформацію про запит
    cursor.execute("SELECT from_user_id, from_username FROM friend_requests WHERE id = ? AND to_user_id = ? AND status = 'pending'", 
                  (request_id, user_id))
    result = cursor.fetchone()
    
    if not result:
        await call.answer("❌ Запит не знайдено або вже оброблено!", show_alert=True)
        return
    
    from_user_id, from_username = result
    
    if reject_friend_request(request_id, user_id):
        # Оновлюємо повідомлення для того хто відхилив
        try:
            await call.message.edit_text(
                f"❌ <b>ЗАПИТ ВІДХИЛЕНО</b>\n\n"
                f"👤 Ви відхилили запит від {from_username}.",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("📨 Інші запити", callback_data="friends_requests"),
                    InlineKeyboardButton("📋 Мої друзі", callback_data="friends_list")
                )
            )
        except Exception as e:
            print(f"❌ Помилка оновлення повідомлення: {e}")
        
        # Сповіщаємо того хто надіслав запит (необов'язково)
        try:
            await bot.send_message(
                from_user_id,
                f"❌ <b>ВАШ ЗАПИТ ВІДХИЛЕНО</b>\n\n"
                f"👤 {call.from_user.username or call.from_user.full_name} відхилив ваш запит у друзі."
            )
        except:
            pass  # Не вдалось відправити сповіщення
        
        await call.answer("❌ Запит відхилено!", show_alert=False)
    else:
        await call.answer("❌ Не вдалося відхилити запит!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data.startswith('friends_transfer_'))
async def cb_friends_transfer_quick(call: types.CallbackQuery):
    """Швидкий переказ грошей другу"""
    await call.answer()
    user_id = call.from_user.id
    friend_id = int(call.data.split('_')[2])
    
    cursor.execute("SELECT username FROM players WHERE user_id = ?", (friend_id,))
    friend_data = cursor.fetchone()
    
    if not friend_data:
        await call.answer("❌ Гравець не знайдений!", show_alert=True)
        return
    
    friend_username = friend_data[0]
    
    await call.message.answer(
        f"💰 <b>Швидкий переказ другу</b>\n\n"
        f"👤 Друг: {friend_username}\n"
        f"🆔 ID: {friend_id}\n"
        f"💎 Ваш баланс: {get_user_coins(user_id):,} ✯\n\n"
        f"💡 <b>Введіть суму для переказу:</b>\n"
        f"<code>/transfer {friend_id} СУМА</code>\n\n"
        f"📝 <b>Приклад:</b>\n"
        f"<code>/transfer {friend_id} 100</code>\n"
        f"<code>/transfer {friend_id} 500</code>"
    )

def remove_friend(user_id: int, friend_id: int) -> bool:
    """Видалити друга зі списку"""
    try:
        # Видаляємо з обох сторін
        cursor.execute("DELETE FROM friends WHERE user_id = ? AND friend_id = ?", (user_id, friend_id))
        cursor.execute("DELETE FROM friends WHERE user_id = ? AND friend_id = ?", (friend_id, user_id))
        
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"❌ Помилка видалення друга: {e}")
        return False

def get_friend_info(user_id: int, friend_id: int) -> Dict:
    """Отримати інформацію про друга"""
    cursor.execute("""
        SELECT f.friend_username, f.added_date, p.level, p.coins, p.role
        FROM friends f
        JOIN players p ON f.friend_id = p.user_id
        WHERE f.user_id = ? AND f.friend_id = ?
    """, (user_id, friend_id))
    
    result = cursor.fetchone()
    if not result:
        return None
    
    username, added_date, level, coins, role = result
    return {
        "username": username,
        "added_date": added_date,
        "level": level,
        "coins": coins,
        "role": role
    }
#------====== PASS =======-------
def can_get_passport(user_id: int) -> Dict:
    level = get_user_level(user_id)
    coins = get_user_coins(user_id)
    
    if level < 2:
        return {"can": False, "reason": "❌ Потрібен 2 рівень!"}
    if coins < 1000:
        return {"can": False, "reason": f"❌ Недостатньо монет! Потрібно 1000 ✯ (у вас {coins} ✯)"}
    return {"can": True, "reason": "✅ Можна отримати паспорт!"}

def buy_passport(user_id: int) -> bool:
    check = can_get_passport(user_id)
    if not check["can"]:
        return False
    
    cursor.execute("UPDATE players SET coins = coins - 1000, has_passport = TRUE WHERE user_id = ?", (user_id,))
    conn.commit()
    return True

def create_progress_bar(percentage: float, length: int = 10) -> str:
    """Створити прогрес-бар"""
    filled = int(length * percentage / 100)
    empty = length - filled
    return f"█" * filled + "░" * empty
#===================== craft
def get_user_craftable_items(user_id: int) -> List[Dict]:
    """Отримати доступні для крафту предмети"""
    user_items = get_user_inventory(user_id)
    craftable = []
    
    for recipe in CraftingRecipes.RECIPES:
        can_craft = True
        missing_ingredients = []
        
        for ingredient in recipe["ingredients"]:
            # Рахуємо кількість потрібних предметів
            required_count = ingredient["quantity"]
            user_count = sum(1 for item in user_items if item["name"] == ingredient["name"])
            
            if user_count < required_count:
                can_craft = False
                missing_ingredients.append(f"{ingredient['name']} ({user_count}/{required_count})")
        
        craftable.append({
            "recipe": recipe,
            "can_craft": can_craft,
            "missing_ingredients": missing_ingredients
        })
    
    return craftable

def craft_item(user_id: int, recipe_id: int) -> Dict:
    """Виконати крафт предмета"""
    recipe = next((r for r in CraftingRecipes.RECIPES if r["id"] == recipe_id), None)
    if not recipe:
        return {"success": False, "message": "❌ Рецепт не знайдено!"}
    
    # Перевіряємо наявність предметів
    user_items = get_user_inventory(user_id)
    user_coins = get_user_coins(user_id)
    
    if user_coins < recipe["cost"]:
        return {"success": False, "message": "❌ Недостатньо монет для крафту!"}
    
    for ingredient in recipe["ingredients"]:
        required_count = ingredient["quantity"]
        user_count = sum(1 for item in user_items if item["name"] == ingredient["name"])
        
        if user_count < required_count:
            return {"success": False, "message": f"❌ Недостатньо {ingredient['name']}!"}
    
    # Видаляємо використані предмети
    for ingredient in recipe["ingredients"]:
        for _ in range(ingredient["quantity"]):
            remove_from_inventory(user_id, ingredient["name"])
    
    # Списуємо вартість крафту
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (recipe["cost"], user_id))
    
    # Додаємо результат
    if recipe["result"] == "random_car":
        # Генеруємо випадкову машину
        car = get_random_car()
        add_to_inventory(user_id, car["name"], car["price"], "car")
        result_message = f"🎉 Ви сконструювали: {car['name']} ({car['class']} класс)!"
    else:
        add_to_inventory(user_id, recipe["result"], recipe["result_price"], recipe["result_type"])
        result_message = f"🎉 Ви сконструювали: {recipe['result']}!"
    
    conn.commit()
    return {"success": True, "message": result_message}

def get_random_car() -> Dict:
    """Отримати випадкову машину згідно з ймовірностями"""
    r = random.random()
    cumulative_prob = 0.0
    
    for car in Cars.CARS:
        cumulative_prob += car["probability"]
        if r <= cumulative_prob:
            return car
    
    return Cars.CARS[0]  # fallback

# Додаємо на початок цих функцій:
def check_passport_required(user_id: int) -> bool:
    """Перевірити чи потрібен паспорт"""
    cursor.execute("SELECT has_passport FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else False

# В кожну функцію додаємо перевірку на початку:
@dp.callback_query_handler(lambda c: c.data in ['shop_farm', 'shop_real_estate', 'shop_roles', 'shop_prefixes', 'menu_income', 'menu_friends', 'inventory_view'])
async def check_passport_access(call: types.CallbackQuery):
    """Перевірка доступу до функцій, що вимагають паспорт"""
    user_id = call.from_user.id
    
    if not check_passport_required(user_id):
        await call.answer("❌ Ця функція доступна тільки з паспортом! Отримайте паспорт в профілі.", show_alert=True)
        return
    
    # Якщо паспорт є - передаємо до оригінального обробника
    if call.data == 'shop_farm':
        await cb_shop_farm(call)
    elif call.data == 'shop_real_estate':
        await cb_shop_real_estate(call)
    elif call.data == 'shop_roles':
        await cb_shop_roles(call)
    elif call.data == 'shop_prefixes':
        await cb_shop_prefixes(call)
    elif call.data == 'menu_income':
        await cb_menu_income(call)
    elif call.data == 'menu_friends':
        await cb_menu_friends(call)  # Це вже має бути виправлено вище
    elif call.data == 'inventory_view':
        await cb_inventory_view(call)

def ensure_player(user_id: int, username: str):
    cursor.execute("SELECT user_id FROM players WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO players (user_id, username, last_active, last_tap_reset) VALUES (?, ?, ?, ?)",
            (user_id, username, datetime.now().isoformat(), datetime.now().date().isoformat())
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

def get_user_role(user_id: int) -> str:
    cursor.execute("SELECT role FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else "Новачок"

def get_user_prefix(user_id: int) -> str:
    cursor.execute("SELECT prefix FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else ""

def add_user_coins(user_id: int, coins: int):
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (coins, user_id))
    conn.commit()

def get_user_farm_income(user_id: int) -> int:
    cursor.execute("SELECT SUM(income * count) FROM farm_animals WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    base_income = result[0] if result and result[0] else 0
    
    # Бонуси від ролей
    role = get_user_role(user_id)
    if role == "Фермер":
        base_income = int(base_income * 1.06)
    elif role == "Колектор":
        base_income = int(base_income * 1.05)
    
    return base_income

def get_user_real_estate_income(user_id: int) -> int:
    cursor.execute("SELECT SUM(income) FROM user_real_estate WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    base_income = result[0] if result and result[0] else 0
    
    # Бонуси від ролей
    role = get_user_role(user_id)
    if role == "Фермер":
        base_income = int(base_income * 1.06)
    elif role == "Колектор":
        base_income = int(base_income * 1.05)
    
    return base_income

def get_user_tap_stats(user_id: int) -> Dict:
    cursor.execute("SELECT tap_boost_level, total_taps, daily_taps, last_tap_reset FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    # Скидання лічильника тапів на новий день
    today = datetime.now().date().isoformat()
    if result and result[3] != today:
        cursor.execute("UPDATE players SET daily_taps = 0, last_tap_reset = ? WHERE user_id = ?", (today, user_id))
        conn.commit()
        daily_taps = 0
    else:
        daily_taps = result[2] if result else 0
    
    if result:
        level, total_taps, _, _ = result
        income = TapGame.BOOST_LEVELS.get(level, {"income": 1})["income"]
        
        # Бонус від ролі Активний
        role = get_user_role(user_id)
        if role == "Активний":
            income = int(income * 1.03)
        
        return {
            "level": level, 
            "income": income, 
            "total_taps": total_taps,
            "daily_taps": daily_taps
        }
    return {"level": 1, "income": 1, "total_taps": 0, "daily_taps": 0}

def get_daily_tap_limit(user_id: int) -> int:
    level = get_user_level(user_id)
    role = get_user_role(user_id)
    
    if level <= 5:
        return float('inf')  # Без ліміту для рівнів <= 5
    
    if role == "Активний":
        return DAILY_TAP_LIMIT_ACTIVE
    else:
        return DAILY_TAP_LIMIT_BASE

def can_user_tap(user_id: int) -> bool:
    tap_stats = get_user_tap_stats(user_id)
    daily_limit = get_daily_tap_limit(user_id)
    return tap_stats["daily_taps"] < daily_limit

def get_total_passive_income(user_id: int) -> int:
    farm_income = get_user_farm_income(user_id)
    estate_income = get_user_real_estate_income(user_id)
    business_income = get_total_business_income(user_id)
    
    # Додатковий дохід для Банкіра
    role = get_user_role(user_id)
    if role == "БАНКІР":
        estate_income += 25
    
    return farm_income + estate_income + business_income

# Продовження в наступній частині...
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
    
    # Комісія 5% (крім Банкіра)
    commission = 0 if get_user_role(from_user_id) == "БАНКІР" else ceil(amount * 0.05)
    final_amount = amount - commission
    
    # Виконуємо переказ
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (amount, from_user_id))
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (final_amount, to_user_id))
    
    # Записуємо переказ
    cursor.execute(
        "INSERT INTO money_transfers (from_user_id, to_user_id, amount, transfer_date) VALUES (?, ?, ?, ?)",
        (from_user_id, to_user_id, amount, datetime.now().isoformat())
    )
    
    # Додаємо комісію до банкіра
    if commission > 0:
        cursor.execute("SELECT user_id FROM players WHERE role = 'БАНКІР'")
        banker = cursor.fetchone()
        if banker:
            banker_id = banker[0]
            cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (commission, banker_id))
            cursor.execute(
                "INSERT INTO bank_income (user_id, total_commission) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET total_commission = total_commission + ?",
                (banker_id, commission, commission)
            )
    
    conn.commit()
    return True
#=========== МАГАЗИН УРОВНІВ ===============
def buy_level(user_id: int) -> Dict:
    """Купити наступний рівень"""
    current_level = get_user_level(user_id)
    next_level = current_level + 1
    
    # Розраховуємо ціну: 1500 * 2^(current_level-1)
    price = 1500 * (2 ** (current_level - 1))
    
    user_coins = get_user_coins(user_id)
    
    if user_coins < price:
        return {"success": False, "message": f"❌ Недостатньо монет! Потрібно {price} ✯"}
    
    # Списуємо монети та підвищуємо рівень
    cursor.execute("UPDATE players SET coins = coins - ?, level = ? WHERE user_id = ?", 
                   (price, next_level, user_id))
    conn.commit()
    
    return {
        "success": True, 
        "message": f"🎉 Рівень підвищено до {next_level}!",
        "price": price,
        "new_level": next_level
    }

def add_user_xp(user_id: int, xp: int):
    # Бонус для Студента
    role = get_user_role(user_id)
    if role == "Студент":
        xp = int(xp * 1.05)
    
    cursor.execute("UPDATE players SET xp = xp + ? WHERE user_id = ?", (xp, user_id))
    
    # Перевірка підвищення рівня (тільки через XP)
    current_level = get_user_level(user_id)
    current_xp = get_user_xp(user_id)
    xp_needed = current_level * XP_PER_LEVEL
    
    if current_xp >= xp_needed:
        new_level = current_level + 1
        cursor.execute("UPDATE players SET level = ? WHERE user_id = ?", (new_level, user_id))
        conn.commit()
        return new_level
    return current_level

#=========== PROFILE NO PASS ==========
async def show_profile_without_passport(call: types.CallbackQuery, user_id: int):
    """Показати профіль без паспорта"""
    cursor.execute("SELECT username, level, coins FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result:
        username, level, coins = result
        check = can_get_passport(user_id)
        
        text = (
            f"👤 <b>Профіль гравця</b>\n\n"
            f"🆔 ID: {user_id}\n"
            f"👤 Ім'я: {username}\n"
            f"💎 Баланс: {coins} ✯\n"
            f"🎯 Рівень: {level}\n\n"
            f"❌ <b>У вас немає паспорта!</b>\n\n"
        )
        
        if check["can"]:
            text += f"✅ {check['reason']}\nНатисніть кнопку нижче щоб отримати паспорт за 1000 ✯"
        else:
            text += f"📋 <b>Умови отримання паспорта:</b>\n"
            text += f"• 🎯 2 рівень (у вас {level})\n"
            f"• 💰 1000 монет (у вас {coins})\n\n"
            f"💡 {check['reason']}"
        
        kb = InlineKeyboardMarkup()
        
        if check["can"]:
            kb.add(InlineKeyboardButton("🛂 Отримати паспорт (1000 ✯)", callback_data="buy_passport"))
        
        # ТІЛЬКИ ці кнопки доступні без паспорта
        kb.add(InlineKeyboardButton("🎮 Ігри", callback_data="menu_games"))
        kb.add(InlineKeyboardButton("🛍️ Магазин", callback_data="shop_levels"))  # Тільки рівні!
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
        
        await call.message.edit_text(text, reply_markup=kb)

def can_get_passport(user_id: int) -> Dict:
    """Перевірити чи може гравець отримати паспорт"""
    level = get_user_level(user_id)
    coins = get_user_coins(user_id)
    
    if level < 2:
        return {"can": False, "reason": "❌ Потрібен 2 рівень!"}
    if coins < 1000:
        return {"can": False, "reason": f"❌ Недостатньо монет! Потрібно 1000 ✯"}
    return {"can": True, "reason": "✅ Можна отримати паспорт!"}

def buy_passport(user_id: int) -> bool:
    """Купити паспорт"""
    check = can_get_passport(user_id)
    if not check["can"]:
        return False
    
    cursor.execute("UPDATE players SET coins = coins - 1000, has_passport = TRUE WHERE user_id = ?", (user_id,))
    conn.commit()
    return True

async def show_beautiful_passport(call: types.CallbackQuery, user_id: int):
    """Показати стильний системний паспорт"""
    # Отримуємо дані гравця
    cursor.execute("SELECT username, level, coins, role, total_taps, last_active FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        await call.answer("❌ Гравець не знайдений!")
        return
    
    username, level, coins, role, total_taps, last_active = result
    
    # Розраховуємо дохід
    farm_income = get_user_farm_income(user_id)
    estate_income = get_user_real_estate_income(user_id)
    total_income = farm_income + estate_income
    
    # Прогрес рівня
    xp_needed = level * XP_PER_LEVEL
    current_xp = get_user_xp(user_id)
    progress_percent = min(int((current_xp / xp_needed) * 100), 100) if xp_needed > 0 else 0
    progress_bar = create_modern_progress_bar(progress_percent)
    
    # Дата реєстрації
    reg_date = last_active[:10] if last_active else "НЕВІДОМО"
    
    # Унікальний номер паспорта
    passport_number = f"P-{user_id % 10000:04d}"
    
    # Форматуємо числа
    formatted_coins = f"{coins:,}"
    formatted_income = f"{total_income:,}"
    
    # Створюємо стильний текст паспорта
    text = (
        f"⟡━━━━━━━━━━━━━━━⟡\n"
        f"      🛂  <b>ПАСПОРТ</b>\n"
        f"⟡━━━━━━━━━━━━━━━⟡\n\n"
        f"<b>👤 USER:</b> {username}\n"
        f"<b>🆔 ID :</b> #{user_id}\n"
        f"<b>⭐ LVL:</b> {level} ⟣ {progress_bar} {progress_percent}%\n"
        f"<b>💰 CREDITS:</b> {formatted_coins} ✯\n"
        f"<b>🏠 BASE INCOME:</b> {formatted_income} ✯ / 6H\n"
        f"<b>🎭 ROLE:</b> {get_english_role(role)}\n"
        f"<b>📅 DATE ISSUED:</b> {reg_date}\n\n"
        f"⟡━━━━━━━━━━━━━━━⟡\n"
        f"   <b>AUTHORIZED ACCESS:</b> #{passport_number}\n"
        f"⟡━━━━━━━━━━━━━━━⟡\n\n"
        f"<i>⟡ SYSTEM IDENTITY CONFIRMED ⟡</i>"
    )
    
    await call.message.edit_text(text, reply_markup=build_passport_menu(user_id))

def create_modern_progress_bar(percentage: float) -> str:
    """Створити сучасний прогрес-бар"""
    filled = int(10 * percentage / 100)
    empty = 10 - filled
    return f"█" * filled + "░" * empty

def get_english_role(role: str) -> str:
    """Перевести роль на англійську"""
    role_map = {
        "Новачок": "NEWBIE",
        "Фермер": "FARMER", 
        "Колектор": "COLLECTOR",
        "Студент": "STUDENT",
        "Активний": "ACTIVE",
        "Щасливчик": "LUCKY",
        "Воїн": "WARRIOR",
        "БАНКІР": "BANKER"
    }
    return role_map.get(role, role.upper())

def get_user_emoji(role: str) -> str:
    """Отримати емодзі для ролі"""
    emoji_map = {
        "Новачок": "👶",
        "Фермер": "👨‍🌾", 
        "Колектор": "🏢",
        "Студент": "🎓",
        "Активний": "⚡",
        "Щасливчик": "🍀",
        "Воїн": "⚔️",
        "БАНКІР": "💰"
    }
    return emoji_map.get(role, "👤")

async def show_passport(call: types.CallbackQuery, user_id: int):
    """Показати паспорт гравця (головна функція)"""
    await show_beautiful_passport(call, user_id)

def build_passport_menu(user_id: int):
    """Побудувати меню для паспорта"""
    kb = InlineKeyboardMarkup(row_width=2)
    
    kb.add(
        InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view"),
        InlineKeyboardButton("👥 Друзі", callback_data="menu_friends"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

@dp.callback_query_handler(lambda c: c.data == 'buy_passport')
async def cb_buy_passport(call: types.CallbackQuery):
    """Обробник купівлі паспорта"""
    user_id = call.from_user.id
    
    if buy_passport(user_id):
        await call.answer("✅ Паспорт успішно отримано!", show_alert=True)
        await cb_menu_profile(call)
    else:
        await call.answer("❌ Не вдалося отримати паспорт!", show_alert=True)

def can_get_passport(user_id: int) -> Dict:
    """Перевірити чи може гравець отримати паспорт"""
    level = get_user_level(user_id)
    coins = get_user_coins(user_id)
    
    if level < 2:
        return {"can": False, "reason": "❌ Потрібен 2 рівень!"}
    if coins < 1000:
        return {"can": False, "reason": f"❌ Недостатньо монет! Потрібно 1000 ✯"}
    return {"can": True, "reason": "✅ Можна отримати паспорт!"}

def buy_passport(user_id: int) -> bool:
    """Купити паспорт"""
    check = can_get_passport(user_id)
    if not check["can"]:
        return False
    
    cursor.execute("UPDATE players SET coins = coins - 1000, has_passport = TRUE WHERE user_id = ?", (user_id,))
    conn.commit()
    return True

@dp.callback_query_handler(lambda c: c.data == 'buy_passport')
async def cb_buy_passport(call: types.CallbackQuery):
    """Обробник купівлі паспорта"""
    user_id = call.from_user.id
    
    if buy_passport(user_id):
        await call.answer("✅ Паспорт успішно отримано!", show_alert=True)
        await cb_menu_profile(call)  # Повертаємось до профілю (тепер з паспортом)
    else:
        await call.answer("❌ Не вдалося отримати паспорт!", show_alert=True)


# ========== ІНВЕНТАР ТА ПРЕДМЕТИ ==========
def get_user_inventory(user_id: int) -> List[Dict]:
    """Отримати інвентар гравця (ТІЛЬКИ предмети, без ролей)"""
    try:
        # ТІЛЬКИ предмети, без ролей
        cursor.execute("""
            SELECT item_name, item_price, item_type, obtained_date 
            FROM user_inventory 
            WHERE user_id = ? 
            ORDER BY obtained_date DESC
        """, (user_id,))
        
        items = []
        for name, price, item_type, date in cursor.fetchall():
            items.append({
                "name": name,
                "price": price,
                "type": item_type,
                "date": date,
                "category": "item"
            })
        
        return items
        
    except Exception as e:
        print(f"Помилка отримання інвентаря: {e}")
        return []
        
    except Exception as e:
        print(f"Помилка отримання інвентаря: {e}")
        return []

def remove_from_inventory(user_id: int, item_name: str) -> bool:
    """Видалити предмет з інвентаря"""
    # SQLite не підтримує LIMIT в DELETE, тому робимо так:
    cursor.execute("""
        DELETE FROM user_inventory 
        WHERE id IN (
            SELECT id FROM user_inventory 
            WHERE user_id = ? AND item_name = ? 
            LIMIT 1
        )
    """, (user_id, item_name))
    conn.commit()
    return cursor.rowcount > 0

def get_user_roles(user_id: int) -> List[Dict]:
    """Отримати ролі гравця"""
    cursor.execute("SELECT role_id, role_name, purchased_date FROM user_roles WHERE user_id = ?", (user_id,))
    roles = []
    for role_id, role_name, date in cursor.fetchall():
        roles.append({
            "id": role_id,
            "name": role_name,
            "purchased_date": date
        })
    return roles

def get_user_prefixes(user_id: int) -> List[Dict]:
    """Отримати префікси гравця"""
    cursor.execute("SELECT prefix_id, prefix_name, purchased_date FROM user_prefixes WHERE user_id = ?", (user_id,))
    prefixes = []
    for prefix_id, prefix_name, date in cursor.fetchall():
        prefixes.append({
            "id": prefix_id,
            "name": prefix_name,
            "purchased_date": date
        })
    return prefixes

def buy_role(user_id: int, role_id: int) -> bool:
    """Купити роль"""
    # Перевіряємо чи вже є роль
    if get_user_roles(user_id):
        return False  # Можна мати тільки одну роль
    
    role = next((r for r in Roles.ROLES if r["id"] == role_id), None)
    if not role:
        return False
    
    user_coins = get_user_coins(user_id)
    if user_coins < role["price"]:
        return False
    
    # Купівля ролі
    cursor.execute("UPDATE players SET coins = coins - ?, role = ? WHERE user_id = ?", 
                   (role["price"], role["name"], user_id))
    cursor.execute(
        "INSERT INTO user_roles (user_id, role_id, role_name, purchased_date) VALUES (?, ?, ?, ?)",
        (user_id, role_id, role["name"], datetime.now().isoformat())
    )
    conn.commit()
    return True

def buy_prefix(user_id: int, prefix_id: int) -> bool:
    """Купити префікс"""
    prefix = next((p for p in Prefixes.PREFIXES if p["id"] == prefix_id), None)
    if not prefix:
        return False
    
    user_coins = get_user_coins(user_id)
    if user_coins < prefix["price"]:
        return False
    
    # Купівля префікса
    cursor.execute("UPDATE players SET coins = coins - ?, prefix = ? WHERE user_id = ?", 
                   (prefix["price"], prefix["name"], user_id))
    cursor.execute(
        "INSERT INTO user_prefixes (user_id, prefix_id, prefix_name, purchased_date) VALUES (?, ?, ?, ?)",
        (user_id, prefix_id, prefix["name"], datetime.now().isoformat())
    )
    conn.commit()
    return True

# ========== АУКЦІОН ТА ПРОДАЖІ ==========
def add_to_auction(user_id: int, item_name: str, item_type: str, original_price: int) -> bool:
    """Додати предмет на аукціон"""
    auction_price = int(original_price * 0.9)  # Знижка 10%
    
    cursor.execute(
        "INSERT INTO auction_items (user_id, item_name, item_type, original_price, auction_price, listed_date) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, item_name, item_type, original_price, auction_price, datetime.now().isoformat())
    )
    conn.commit()
    return True

def remove_from_auction(item_id: int) -> bool:
    """Видалити предмет з аукціону"""
    cursor.execute("DELETE FROM auction_items WHERE id = ?", (item_id,))
    conn.commit()
    return cursor.rowcount > 0

def buy_from_auction(user_id: int, item_id: int) -> bool:
    """Купити предмет з аукціону"""
    cursor.execute("SELECT * FROM auction_items WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    if not item:
        return False
    
    _, seller_id, item_name, item_type, original_price, auction_price, _ = item
    buyer_coins = get_user_coins(user_id)
    
    if buyer_coins < auction_price:
        return False
    
    # Комісія 4%
    commission = int(auction_price * 0.04)
    seller_gets = auction_price - commission
    
    # Виконуємо угоду
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (auction_price, user_id))
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (seller_gets, seller_id))
    
    # Додаємо комісію до банкіра
    cursor.execute("SELECT user_id FROM players WHERE role = 'БАНКІР'")
    banker = cursor.fetchone()
    if banker:
        banker_id = banker[0]
        cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (commission, banker_id))
        cursor.execute(
            "INSERT INTO bank_income (user_id, total_commission) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET total_commission = total_commission + ?",
            (banker_id, commission, commission)
        )
    
    # Додаємо предмет покупцю
    add_to_inventory(user_id, item_name, original_price, item_type)
    
    # Видаляємо з аукціону
    remove_from_auction(item_id)
    
    conn.commit()
    return True

def add_to_inventory(user_id: int, item_name: str, item_price: int, item_type: str) -> bool:
    """Додати предмет в інвентар"""
    try:
        # Перевіряємо кількість предметів в інвентарі
        cursor.execute("SELECT COUNT(*) FROM user_inventory WHERE user_id = ?", (user_id,))
        item_count = cursor.fetchone()[0]
        
        if item_count >= 10:
            return False  # Інвентар переповнений
        
        # Додаємо предмет
        cursor.execute(
            "INSERT INTO user_inventory (user_id, item_name, item_price, item_type, obtained_date) VALUES (?, ?, ?, ?, ?)",
            (user_id, item_name, item_price, item_type, datetime.now().isoformat())
        )
        return True
    except Exception as e:
        print(f"❌ Помилка додавання в інвентар: {e}")
        return False

def create_pending_sale(seller_id: int, buyer_id: int, item_name: str, item_type: str, price: int) -> bool:
    """Створити запропоновану продаж"""
    cursor.execute(
        "INSERT INTO pending_sales (seller_id, buyer_id, item_name, item_type, price, created_date) VALUES (?, ?, ?, ?, ?, ?)",
        (seller_id, buyer_id, item_name, item_type, price, datetime.now().isoformat())
    )
    conn.commit()
    return True

def accept_pending_sale(sale_id: int) -> bool:
    """Прийняти запропоновану продаж"""
    cursor.execute("SELECT * FROM pending_sales WHERE id = ?", (sale_id,))
    sale = cursor.fetchone()
    if not sale:
        return False
    
    _, seller_id, buyer_id, item_name, item_type, price, _ = sale
    
    buyer_coins = get_user_coins(buyer_id)
    if buyer_coins < price:
        return False
    
    # Комісія 4% (крім Банкіра)
    commission = 0 if get_user_role(seller_id) == "БАНКІР" else int(price * 0.04)
    seller_gets = price - commission
    
    # Виконуємо угоду
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (price, buyer_id))
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (seller_gets, seller_id))
    
    # Додаємо комісію до банкіра
    if commission > 0:
        cursor.execute("SELECT user_id FROM players WHERE role = 'БАНКІР'")
        banker = cursor.fetchone()
        if banker:
            banker_id = banker[0]
            cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (commission, banker_id))
            cursor.execute(
                "INSERT INTO bank_income (user_id, total_commission) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET total_commission = total_commission + ?",
                (banker_id, commission, commission)
            )
    
    # Додаємо предмет покупцю
    add_to_inventory(buyer_id, item_name, price, item_type)
    
    # Видаляємо запропоновану продаж
    cursor.execute("DELETE FROM pending_sales WHERE id = ?", (sale_id,))
    
    conn.commit()
    return True

def reject_pending_sale(sale_id: int) -> bool:
    """Відхилити запропоновану продаж"""
    cursor.execute("DELETE FROM pending_sales WHERE id = ?", (sale_id,))
    conn.commit()
    return cursor.rowcount > 0

# ========== ЩОДЕННІ ЗАВДАННЯ ==========
def get_daily_tasks_progress(user_id: int) -> Dict:
    """Отримати прогрес щоденних завдань"""
    today = datetime.now().date().isoformat()
    
    cursor.execute("SELECT * FROM daily_tasks WHERE user_id = ? AND task_date = ?", (user_id, today))
    task_data = cursor.fetchone()
    
    if not task_data:
        # Створюємо новий запис
        cursor.execute(
            "INSERT INTO daily_tasks (user_id, task_date) VALUES (?, ?)",
            (user_id, today)
        )
        conn.commit()
        task_data = (0, user_id, today, 0, 0, 0, 0, 0)
    
    _, _, _, tasks_completed, spin_count, tap_count, minigames_count, correct_answers = task_data
    
    # Вибираємо 2 випадкових завдання на день
    random.seed(f"{today}_{user_id}")
    daily_tasks = random.sample(DailyTasks.TASKS, 2)
    
    active_tasks = []
    for task in daily_tasks:
        if task["type"] == "spin_roulette":
            current = spin_count
        elif task["type"] == "tap_count":
            current = tap_count
        elif task["type"] == "play_minigames":
            current = minigames_count
        elif task["type"] == "correct_answers":
            current = correct_answers
        elif task["type"] == "buy_animals":
            current = tasks_completed
        else:
            current = 0
        
        completed = current >= task["target"]
        active_tasks.append({
            **task,
            "current": current,
            "completed": completed
        })
    
    return {
        "tasks_completed": tasks_completed,
        "active_tasks": active_tasks
    }

def update_daily_task(user_id: int, task_type: str, increment: int = 1):
    """Оновити прогрес щоденного завдання"""
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

# ========== МЕНЮ ==========
def build_main_menu(user_id: int):
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton("🎮 Ігри", callback_data="menu_games"),
        InlineKeyboardButton("👤 Профіль", callback_data="menu_profile"),
        InlineKeyboardButton("💰 Доходи", callback_data="menu_income"),
        InlineKeyboardButton("🏢 Бізнес", callback_data="menu_business"),
        InlineKeyboardButton("🏆 Топ гравців", callback_data="menu_leaderboard"),
        InlineKeyboardButton("📋 Завдання", callback_data="daily_tasks"),
        InlineKeyboardButton("🛍️ Магазин", callback_data="menu_shop"),
        InlineKeyboardButton("🏦 Банк", callback_data="bank_loans")
    ]
    
    if user_id in [5672490558, 6446725004]:
        buttons.append(InlineKeyboardButton("👑 Адмін", callback_data="simple_admin_panel"))
    
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

# ========== БІЗНЕС СИСТЕМА - МЕНЮ ==========
def build_business_menu(user_id: int):
    """Побудувати меню бізнес-системи"""
    kb = InlineKeyboardMarkup(row_width=2)
    
    kb.add(
        InlineKeyboardButton("🏢 Мої бізнеси", callback_data="business_list"),
        InlineKeyboardButton("🛍️ Купити бізнес", callback_data="business_buy")
    )
    kb.add(
        InlineKeyboardButton("📊 Ліцензії", callback_data="business_licenses"),
        InlineKeyboardButton("💰 Дохід", callback_data="business_income")
    )
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    return kb

def build_business_list_menu(user_id: int, page: int = 1):
    """Побудувати меню списку бізнесів"""
    businesses = get_user_businesses(user_id)
    items_per_page = 5
    total_pages = (len(businesses) + items_per_page - 1) // items_per_page
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_businesses = businesses[start_idx:end_idx]
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for business in page_businesses:
        kb.add(InlineKeyboardButton(
            f"🏢 {business['name']} (р.{business['level']}) - {business['income']}✯/6г",
            callback_data=f"business_view_{business['id']}"
        ))
    
    # Кнопки пагінації
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("◀️", callback_data=f"business_list_{page-1}"))
    
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("▶️", callback_data=f"business_list_{page+1}"))
    
    if pagination_buttons:
        kb.row(*pagination_buttons)
    
    kb.add(InlineKeyboardButton("🛍️ Купити бізнес", callback_data="business_buy"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_business"))
    
    return kb

# ========== СИСТЕМА КРЕДИТІВ - МЕНЮ ==========
def build_bank_menu(user_id: int):
    """Побудувати меню банку"""
    kb = InlineKeyboardMarkup(row_width=2)
    
    kb.add(
        InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"),
        InlineKeyboardButton("📊 Мої кредити", callback_data="bank_my_credits")
    )
    kb.add(
        InlineKeyboardButton("💳 Виплатити", callback_data="bank_repay"),
        InlineKeyboardButton("📋 Історія", callback_data="bank_history")
    )
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    return kb

def build_credits_menu(user_id: int):
    """Побудувати меню вибору кредиту"""
    user_level = get_user_level(user_id)
    active_credits = get_user_active_credits(user_id)
    has_active_credit = len(active_credits) > 0
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for credit_type in CreditSystem.CREDIT_TYPES:
        if user_level >= credit_type["min_level"] and not has_active_credit:
            button_text = f"{credit_type['name']} - до {credit_type['max_amount']:,} ✯"
            callback_data = f"credit_choose_{credit_type['id']}"
        elif has_active_credit:
            button_text = f"🔴 {credit_type['name']} - є активний кредит"
            callback_data = "credit_has_active"
        else:
            button_text = f"🔴 {credit_type['name']} - р. {credit_type['min_level']}+"
            callback_data = "credit_level_low"
        
        kb.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    if has_active_credit:
        kb.add(InlineKeyboardButton("📊 Мої кредити", callback_data="bank_my_credits"))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    return kb

def build_my_credits_menu(user_id: int):
    """Побудувати меню моїх кредитів"""
    active_credits = get_user_active_credits(user_id)
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if not active_credits:
        kb.add(InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"))
    else:
        for credit in active_credits:
            # Розраховуємо час до кінця
            due_date = datetime.fromisoformat(credit['due_date'])
            time_left = due_date - datetime.now()
            hours_left = max(0, int(time_left.total_seconds() // 3600))
            
            button_text = f"{credit['name']} - {credit['remaining']:,} ✯ ({hours_left}г)"
            kb.add(InlineKeyboardButton(button_text, callback_data=f"credit_view_{credit['id']}"))
    
    kb.add(InlineKeyboardButton("📋 Історія", callback_data="bank_history"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    return kb

def build_repay_menu(user_id: int):
    """Побудувати меню виплат"""
    active_credits = get_user_active_credits(user_id)
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if not active_credits:
        kb.add(InlineKeyboardButton("💰 Взяти кредит", callback_data="bank_credits"))
    else:
        for credit in active_credits:
            check = can_repay_credit_early(user_id, credit['id'])
            if check["can"]:
                button_text = f"🟢 {credit['name']} - {check['amount']:,} ✯"
                callback_data = f"credit_repay_{credit['id']}"
            else:
                button_text = f"🔴 {credit['name']} - {check['reason']}"
                callback_data = "credit_cannot_repay"
            
            kb.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="bank_loans"))
    
    return kb

def build_business_buy_menu(user_id: int):
    """Побудувати меню купівлі бізнесів"""
    license_info = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    user_level = get_user_level(user_id)
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for business in BusinessTypes.BUSINESSES:
        can_buy = can_buy_business(user_id, business["id"])
        has_business = any(b["type_id"] == business["id"] for b in user_businesses)
        
        if has_business:
            count = get_business_type_count(user_id, business["id"])
            button_text = f"✅ {business['name']} ({count}/2)"
            callback_data = "business_already_owned"
        elif user_level >= business["min_level"] and len(user_businesses) < license_info["max_businesses"]:
            button_text = f"🟢 {business['name']} - {business['base_price']:,} ✯"
            callback_data = f"business_buy_{business['id']}"
        else:
            button_text = f"🔴 {business['name']} - р.{business['min_level']}+"
            callback_data = "business_cannot_buy"
        
        kb.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    kb.add(InlineKeyboardButton("📊 Ліцензії", callback_data="business_licenses"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_business"))
    
    return kb

def build_business_licenses_menu(user_id: int):
    """Побудувати меню ліцензій"""
    user_license = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for license_data in BusinessLicenses.LICENSES:
        if license_data["id"] == user_license["license_id"]:
            # Поточна ліцензія
            button_text = f"⭐ {license_data['name']} ({license_data['max_businesses']} біз.) - АКТИВНА"
            callback_data = "license_current"
        elif license_data["max_businesses"] > user_license["max_businesses"]:
            # Краща ліцензія - можна купити
            button_text = f"🟢 {license_data['name']} - {license_data['price']:,} ✯"
            callback_data = f"license_buy_{license_data['id']}"
        else:
            # Гірша ліцензія - вже пройдено
            button_text = f"✅ {license_data['name']} ({license_data['max_businesses']} біз.)"
            callback_data = "license_owned"
        
        kb.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    # Інформація про поточний стан
    kb.add(InlineKeyboardButton(
        f"📊 Поточний ліміт: {len(user_businesses)}/{user_license['max_businesses']}", 
        callback_data="none"
    ))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_business"))
    
    return kb

def build_roulettes_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🎪 Рулетка предметів", callback_data="menu_item_roulette"),
        InlineKeyboardButton("💰 Звичайна рулетка", callback_data="roulette_normal"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
    )
    return kb

def build_income_menu(user_id: int):
    kb = InlineKeyboardMarkup(row_width=1)
    buttons = [
        InlineKeyboardButton("🐓 Ферма", callback_data="income_farm"),
        InlineKeyboardButton("🏘️ Нерухомість", callback_data="income_real_estate"),
    ]
    
    # Кнопка банку для Банкіра
    if get_user_role(user_id) == "БАНКІР":
        buttons.append(InlineKeyboardButton("🏦 Банк", callback_data="bank_income"))
    
    buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    kb.add(*buttons)
    return kb

def build_shop_menu(user_id: int):
    """Побудувати меню магазину з урахуванням паспорта"""
    cursor.execute("SELECT has_passport FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    has_passport = result[0] if result else False
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if has_passport:
        # Повний доступ з паспортом
        kb.add(
            InlineKeyboardButton("🐓 Ферма", callback_data="shop_farm"),
            InlineKeyboardButton("🏘️ Нерухомість", callback_data="shop_real_estate"),
            InlineKeyboardButton("🎭 Ролі", callback_data="shop_roles"),
            InlineKeyboardButton("🏷️ Префікси", callback_data="shop_prefixes"),
            InlineKeyboardButton("🎯 Рівні", callback_data="shop_levels"),
            InlineKeyboardButton("🛍️ Предмети", callback_data="shop_items"),  # НОВА КНОПКА
            InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
        )
    else:
        # Обмежений доступ без паспорта - тільки рівні
        kb.add(InlineKeyboardButton("🎯 Рівні", callback_data="shop_levels"))
        kb.add(InlineKeyboardButton("🛂 Отримати паспорт", callback_data="menu_profile"))
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    return kb

def build_friends_menu(user_id: int):
    """Побудувати меню друзів"""
    pending_requests = get_pending_friend_requests(user_id)
    has_requests = len(pending_requests) > 0
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if has_requests:
        kb.add(InlineKeyboardButton(f"📨 Запити ({len(pending_requests)})", callback_data="friends_requests"))
    
    kb.add(
        InlineKeyboardButton("📋 Список друзів", callback_data="friends_list"),
        InlineKeyboardButton("➕ Додати друга", callback_data="friends_add"),
        InlineKeyboardButton("💰 Надіслати гроші", callback_data="friends_transfer"),
        InlineKeyboardButton("🗑️ Видалити друга", callback_data="friends_remove")  # НОВА КНОПКА
    )
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_profile"))
    
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
    
    # Головне меню НЕ видаляємо - воно залишається назавжди
    await message.answer(text, reply_markup=build_main_menu(user_id))

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
    
    # Головне меню НЕ видаляємо
    await call.message.edit_text(text, reply_markup=build_main_menu(user_id))

@dp.callback_query_handler(lambda c: c.data == 'menu_profile')
async def cb_menu_profile(call: types.CallbackQuery):
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    cursor.execute("SELECT has_passport FROM players WHERE user_id = ?", (user_id,))
    has_passport = cursor.fetchone()[0]
    
    if not has_passport:
        # Профіль БЕЗ паспорта
        await show_profile_without_passport(call, user_id)
    else:
        # Профіль З паспортом
        await show_passport(call, user_id)


#=============== VIEM PROFILE
@dp.callback_query_handler(lambda c: c.data.startswith('view_passport_'))
async def cb_view_passport(call: types.CallbackQuery):
    # Показуємо паспорт іншого гравця
    pass

@dp.message_handler(commands=['sell'])
async def cmd_sell(message: types.Message):
    """Команда продажу предмета іншому гравцю"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 4:
            await message.answer(
                "❌ <b>Неправильний формат!</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/sell ID_покупця ID_предмета ціна</code>\n\n"
                "📝 <b>Приклад:</b>\n"
                "<code>/sell 123456789 22 500</code>\n\n"
                "💡 <b>ID предмета</b> можна дізнатись в інвентарі"
            )
            return
        
        buyer_id = int(parts[1])
        item_id = int(parts[2])
        price = int(parts[3])
        
        # Перевірки
        if buyer_id == user_id:
            await message.answer("❌ Не можна продати предмет самому собі!")
            return
        
        if price < 10:
            await message.answer("❌ Мінімальна ціна: 10 ✯")
            return
        
        # Знаходимо предмет в інвентарі
        cursor.execute("SELECT item_name, item_type FROM user_inventory WHERE user_id = ?", (user_id,))
        items = cursor.fetchall()
        
        # Шукаємо предмет за ID
        item_found = None
        for item_name, item_type in items:
            for prize in ItemRoulettePrizes.PRIZES:
                if prize["id"] == item_id and prize["name"] == item_name:
                    item_found = (item_name, item_type, prize["price"])
                    break
            if item_found:
                break
        
        if not item_found:
            await message.answer("❌ Предмет не знайдено в вашому інвентарі!")
            return
        
        item_name, item_type, original_price = item_found
        
        # Перевіряємо чи існує покупець
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (buyer_id,))
        buyer_data = cursor.fetchone()
        
        if not buyer_data:
            await message.answer("❌ Гравець-покупець не знайдений!")
            return
        
        buyer_username = buyer_data[0]
        
        # Створюємо запропоновану продаж
        if create_pending_sale(user_id, buyer_id, item_name, item_type, price):
            # Відправляємо повідомлення покупцю (НЕ видаляємо - висить до рішення)
            try:
                await bot.send_message(
                    buyer_id,
                    f"🛍️ <b>Пропозиція покупки</b>\n\n"
                    f"👤 <b>Продавець:</b> {message.from_user.username or message.from_user.full_name}\n"
                    f"🎁 <b>Предмет:</b> {item_name}\n"
                    f"💰 <b>Ціна:</b> {price} ✯\n\n"
                    f"💎 <b>Ваш баланс:</b> {get_user_coins(buyer_id)} ✯\n\n"
                    f"<i>Ця пропозиція активна до вашого рішення</i>",
                    reply_markup=InlineKeyboardMarkup().add(
                        InlineKeyboardButton("✅ Прийняти", callback_data=f"accept_sale_{user_id}_{item_id}"),
                        InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_sale_{user_id}_{item_id}")
                    )
                )
                await message.answer(f"✅ Пропозицію відправлено гравцю {buyer_username}!")
            except Exception as e:
                await message.answer("❌ Не вдалося відправити пропозицію гравцю. Можливо, бот заблокований.")
        else:
            await message.answer("❌ Помилка при створенні пропозиції продажу!")
            
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")


# ========== БІЗНЕС СИСТЕМА - ОБРОБНИКИ ==========
@dp.callback_query_handler(lambda c: c.data == 'menu_business')
async def cb_menu_business(call: types.CallbackQuery):
    """Головне меню бізнес-системи"""
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    license_info = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    total_income = get_total_business_income(user_id)
    
    text = (
        f"🏢 <b>Бізнес-Система</b>\n\n"
        f"💼 Ваші бізнеси: {len(user_businesses)}/{license_info['max_businesses']}\n"
        f"📄 Ліцензія: {license_info['name']}\n"
        f"💰 Дохід: {total_income} ✯/6 год\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🚀 <b>Оберіть дію:</b>"
    )
    
    await call.message.edit_text(text, reply_markup=build_business_menu(user_id))

@dp.callback_query_handler(lambda c: c.data == 'business_list')
async def cb_business_list(call: types.CallbackQuery):
    """Список бізнесів гравця"""
    await call.answer()
    user_id = call.from_user.id
    
    businesses = get_user_businesses(user_id)
    total_income = get_total_business_income(user_id)
    
    if not businesses:
        text = (
            f"🏢 <b>Ваші бізнеси</b>\n\n"
            f"❌ У вас ще немає бізнесів!\n\n"
            f"💡 Почніть з купівлі першого бізнесу в магазині."
        )
    else:
        text = (
            f"🏢 <b>Ваші бізнеси</b>\n\n"
            f"📊 Всього бізнесів: {len(businesses)}\n"
            f"💰 Загальний дохід: {total_income} ✯/6 год\n\n"
            f"🎯 Оберіть бізнес для деталей:"
        )
    
    await call.message.edit_text(text, reply_markup=build_business_list_menu(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith('business_list_'))
async def cb_business_list_page(call: types.CallbackQuery):
    """Пагінація списку бізнесів"""
    await call.answer()
    user_id = call.from_user.id
    page = int(call.data.split('_')[2])
    
    businesses = get_user_businesses(user_id)
    total_income = get_total_business_income(user_id)
    
    text = (
        f"🏢 <b>Ваші бізнеси</b>\n\n"
        f"📊 Всього бізнесів: {len(businesses)}\n"
        f"💰 Загальний дохід: {total_income} ✯/6 год\n\n"
        f"🎯 Оберіть бізнес для деталей:"
    )
    
    await call.message.edit_text(text, reply_markup=build_business_list_menu(user_id, page))

@dp.callback_query_handler(lambda c: c.data.startswith('business_view_'))
async def cb_business_view(call: types.CallbackQuery):
    """Перегляд деталей бізнесу"""
    await call.answer()
    user_id = call.from_user.id
    business_id = int(call.data.split('_')[2])
    
    cursor.execute("""
        SELECT ub.business_name, ub.level, ub.income, ub.purchased_date, bt.name, bt.max_level
        FROM user_businesses ub
        JOIN business_types bt ON ub.business_type = bt.id
        WHERE ub.id = ? AND ub.user_id = ?
    """, (business_id, user_id))
    
    result = cursor.fetchone()
    if not result:
        await call.answer("❌ Бізнес не знайдено!", show_alert=True)
        return
    
    business_name, level, income, purchased_date, type_name, max_level = result
    
    # Розраховуємо наступне покращення
    upgrade_check = can_upgrade_business(user_id, business_id)
    upgrade_info = ""
    if upgrade_check["can"]:
        upgrade_info = f"🟢 Покращити до {level + 1} рівня: {upgrade_check['price']:,} ✯"
    elif level < max_level:
        upgrade_info = f"🔴 Покращення: {upgrade_check['reason']}"
    else:
        upgrade_info = "⭐ Максимальний рівень досягнуто!"
    
    text = (
        f"🏢 <b>Деталі бізнесу</b>\n\n"
        f"📝 Назва: {business_name}\n"
        f"🎯 Тип: {type_name}\n"
        f"⭐ Рівень: {level}/{max_level}\n"
        f"💰 Дохід: {income} ✯/6 год\n"
        f"📅 Куплено: {purchased_date[:10]}\n\n"
        f"{upgrade_info}"
    )
    
    kb = InlineKeyboardMarkup()
    
    if upgrade_check["can"]:
        kb.add(InlineKeyboardButton(f"⚡ Покращити ({upgrade_check['price']:,} ✯)", callback_data=f"business_upgrade_{business_id}"))
    
    kb.add(InlineKeyboardButton("📋 Список бізнесів", callback_data="business_list"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_business"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('business_upgrade_'))
async def cb_business_upgrade(call: types.CallbackQuery):
    """Покращити бізнес"""
    await call.answer()
    user_id = call.from_user.id
    business_id = int(call.data.split('_')[2])
    
    if upgrade_business(user_id, business_id):
        await call.answer("✅ Бізнес успішно покращено!", show_alert=True)
        await cb_business_view(call)  # Повертаємось до перегляду
    else:
        await call.answer("❌ Не вдалося покращити бізнес!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'business_buy')
async def cb_business_buy(call: types.CallbackQuery):
    """Меню купівлі бізнесів"""
    await call.answer()
    user_id = call.from_user.id
    
    license_info = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    user_level = get_user_level(user_id)
    
    text = (
        f"🛍️ <b>Купівля бізнесу</b>\n\n"
        f"💼 Ваші бізнеси: {len(user_businesses)}/{license_info['max_businesses']}\n"
        f"💎 Баланс: {get_user_coins(user_id):,} ✯\n"
        f"🎯 Ваш рівень: {user_level}\n\n"
        f"🏢 <b>Доступні бізнеси:</b>\n\n"
        f"🟢 - можна купити\n"
        f"🔴 - потрібен вищий рівень\n"
        f"✅ - вже є у власності\n\n"
        f"💡 Максимум 2 бізнеси одного типу!"
    )
    
    await call.message.edit_text(text, reply_markup=build_business_buy_menu(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith('business_buy_'))
async def cb_business_buy_confirm(call: types.CallbackQuery):
    """Підтвердження купівлі бізнесу"""
    await call.answer()
    user_id = call.from_user.id
    business_type_id = int(call.data.split('_')[2])
    
    business = next((b for b in BusinessTypes.BUSINESSES if b["id"] == business_type_id), None)
    if not business:
        await call.answer("❌ Бізнес не знайдено!", show_alert=True)
        return
    
    check = can_buy_business(user_id, business_type_id)
    if not check["can"]:
        await call.answer(check["reason"], show_alert=True)
        return
    
    text = (
        f"🏢 <b>Підтвердження покупки</b>\n\n"
        f"📝 Бізнес: {business['name']}\n"
        f"💰 Ціна: {business['base_price']:,} ✯\n"
        f"💎 Ваш баланс: {get_user_coins(user_id):,} ✯\n"
        f"💰 Дохід: {business['base_income']} ✯/6 год\n"
        f"⭐ Макс. рівень: {business['max_level']}\n\n"
        f"💡 Бізнес можна буде покращувати для збільшення доходу!"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Купити", callback_data=f"business_confirm_{business_type_id}"))
    kb.add(InlineKeyboardButton("❌ Скасувати", callback_data="business_buy"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('business_confirm_'))
async def cb_business_confirm(call: types.CallbackQuery):
    """Підтверджена купівля бізнесу"""
    await call.answer()
    user_id = call.from_user.id
    business_type_id = int(call.data.split('_')[2])
    
    if buy_business(user_id, business_type_id):
        business = next((b for b in BusinessTypes.BUSINESSES if b["id"] == business_type_id), None)
        
        text = (
            f"🎉 <b>Бізнес успішно куплено!</b>\n\n"
            f"🏢 Назва: {business['name']}\n"
            f"💰 Витрачено: {business['base_price']:,} ✯\n"
            f"💎 Новий баланс: {get_user_coins(user_id):,} ✯\n"
            f"📈 Дохід: {business['base_income']} ✯/6 год\n\n"
            f"⚡ Тепер ви можете покращувати бізнес для збільшення доходу!"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🏢 Мої бізнеси", callback_data="business_list"))
        kb.add(InlineKeyboardButton("🛍️ Ще бізнес", callback_data="business_buy"))
        kb.add(InlineKeyboardButton("⬅️ Головне", callback_data="menu_business"))
        
        await call.message.edit_text(text, reply_markup=kb)
    else:
        await call.answer("❌ Не вдалося купити бізнес!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'business_already_owned')
async def cb_business_already_owned(call: types.CallbackQuery):
    """Повідомлення про вже наявний бізнес"""
    await call.answer("❌ У вас вже є цей тип бізнесу! (макс. 2 одного типу)", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'business_cannot_buy')
async def cb_business_cannot_buy(call: types.CallbackQuery):
    """Повідомлення про неможливість купівлі"""
    await call.answer("🔴 Цей бізнес ще не доступний! Потрібен вищий рівень.", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'business_licenses')
async def cb_business_licenses(call: types.CallbackQuery):
    """Меню ліцензій"""
    await call.answer()
    user_id = call.from_user.id
    
    user_license = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    
    text = (
        f"📊 <b>Система ліцензій</b>\n\n"
        f"💼 Поточний ліміт: {len(user_businesses)}/{user_license['max_businesses']} бізнесів\n"
        f"📄 Ваша ліцензія: {user_license['name']}\n"
        f"💎 Баланс: {get_user_coins(user_id):,} ✯\n\n"
        f"🏢 <b>Доступні ліцензії:</b>\n\n"
        f"⭐ - ваша поточна ліцензія\n"
        f"🟢 - можна купити\n"
        f"✅ - вже є краща ліцензія\n\n"
        f"💡 Можна купувати будь-яку ліцензію!"
    )
    
    await call.message.edit_text(text, reply_markup=build_business_licenses_menu(user_id))

@dp.callback_query_handler(lambda c: c.data == 'refresh_licenses')
async def cb_refresh_licenses(call: types.CallbackQuery):
    """Оновити меню ліцензій"""
    await call.answer("🔄 Меню оновлено!")
    
    user_id = call.from_user.id
    user_license = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    
    # Створюємо НОВИЙ текст
    text = (
        f"📊 <b>Система ліцензій</b>\n\n"
        f"💼 Поточний ліміт: {len(user_businesses)}/{user_license['max_businesses']} бізнесів\n"
        f"📄 Ваша ліцензія: {user_license['name']}\n"
        f"💎 Баланс: {get_user_coins(user_id):,} ✯\n\n"
        f"🏢 <b>Доступні ліцензії:</b>\n\n"
        f"✅ - вже куплено\n"
        f"🟢 - можна купити\n"
        f"🔴 - потрібна попередня ліцензія\n\n"
        f"💡 Ліцензії купуються по черзі!"
    )
    
    # Створюємо НОВУ клавіатуру
    kb = InlineKeyboardMarkup(row_width=1)
    
    for license_data in BusinessLicenses.LICENSES:
        if license_data["id"] < user_license["license_id"]:
            button_text = f"✅ {license_data['name']} ({license_data['max_businesses']} біз.)"
            callback_data = "license_already_owned"
        elif license_data["id"] == user_license["license_id"]:
            button_text = f"🟢 {license_data['name']} - {license_data['price']:,} ✯"
            callback_data = f"license_buy_{license_data['id']}"
        else:
            prev_license = next((l for l in BusinessLicenses.LICENSES if l["id"] == license_data["id"] - 1), None)
            if prev_license:
                button_text = f"🔴 {license_data['name']} - купіть {prev_license['name']}"
            else:
                button_text = f"🔴 {license_data['name']} - потрібна попередня"
            callback_data = "license_cannot_buy"
        
        kb.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    kb.add(InlineKeyboardButton(
        f"📊 Поточний ліміт: {len(user_businesses)}/{user_license['max_businesses']}", 
        callback_data="none"
    ))
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="refresh_licenses"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_business"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('license_buy_'))
async def cb_license_buy(call: types.CallbackQuery):
    """Купівля ліцензії"""
    await call.answer()
    user_id = call.from_user.id
    license_id = int(call.data.split('_')[2])
    
    license_data = next((l for l in BusinessLicenses.LICENSES if l["id"] == license_id), None)
    
    if not license_data:
        await call.answer("❌ Ліцензія не знайдена!", show_alert=True)
        return
    
    user_license = get_user_business_license(user_id)
    
    # Перевіряємо чи це не поточна ліцензія
    if license_id == user_license["license_id"]:
        await call.answer("✅ Ця ліцензія вже активна!", show_alert=True)
        return
    
    # Перевіряємо чи це не гірша ліцензія
    if license_data["max_businesses"] <= user_license["max_businesses"]:
        await call.answer("❌ У вас вже є краща ліцензія!", show_alert=True)
        return
    
    user_coins = get_user_coins(user_id)
    if user_coins < license_data["price"]:
        await call.answer(f"❌ Недостатньо монет! Потрібно {license_data['price']:,} ✯", show_alert=True)
        return
    
    # Купуємо ліцензію
    cursor.execute("""
        UPDATE user_business_licenses 
        SET license_id = ?, max_businesses = ?, purchased_date = ?
        WHERE user_id = ?
    """, (license_id, license_data["max_businesses"], datetime.now().isoformat(), user_id))
    
    # Списуємо монети
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", 
                   (license_data["price"], user_id))
    
    conn.commit()
    
    text = (
        f"🎉 <b>Ліцензію успішно куплено!</b>\n\n"
        f"📄 Ліцензія: {license_data['name']}\n"
        f"💼 Новий ліміт: {license_data['max_businesses']} бізнесів\n"
        f"💰 Витрачено: {license_data['price']:,} ✯\n"
        f"💎 Новий баланс: {get_user_coins(user_id):,} ✯\n\n"
        f"🚀 Тепер ви можете мати більше бізнесів!"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ Купити бізнес", callback_data="business_buy"))
    kb.add(InlineKeyboardButton("📊 Перейти до ліцензій", callback_data="business_licenses"))
    kb.add(InlineKeyboardButton("⬅️ Головне", callback_data="menu_business"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'license_current')
async def cb_license_current(call: types.CallbackQuery):
    """Поточна ліцензія"""
    await call.answer("⭐ Ця ліцензія вже активна!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'license_owned')
async def cb_license_owned(call: types.CallbackQuery):
    """Вже є краща ліцензія"""
    await call.answer("✅ У вас вже є краща ліцензія!", show_alert=True)



@dp.callback_query_handler(lambda c: c.data == 'license_already_owned')
async def cb_license_already_owned(call: types.CallbackQuery):
    """Повідомлення про вже наявну ліцензію"""
    await call.answer("✅ Ця ліцензія вже куплена!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'license_cannot_buy')
async def cb_license_cannot_buy(call: types.CallbackQuery):
    """Повідомлення про неможливість купівлі ліцензії"""
    await call.answer("🔴 Спочатку купіть попередню ліцензію!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'business_income')
async def cb_business_income(call: types.CallbackQuery):
    """Інформація про дохід від бізнесів"""
    await call.answer()
    user_id = call.from_user.id
    
    businesses = get_user_businesses(user_id)
    total_income = get_total_business_income(user_id)
    
    text = (
        f"💰 <b>Дохід від бізнесів</b>\n\n"
        f"📊 Всього бізнесів: {len(businesses)}\n"
        f"💸 Загальний дохід: {total_income} ✯/6 год\n\n"
    )
    
    if businesses:
        text += "🏢 <b>Ваші бізнеси:</b>\n"
        for business in businesses:
            text += f"• {business['name']} (р.{business['level']}): {business['income']} ✯/6 год\n"
        
        text += f"\n💡 Дохід нараховується автоматично кожні 6 годин!"
    else:
        text += "❌ У вас ще немає бізнесів!\n\n💡 Почніть з купівлі першого бізнесу."
    
    kb = InlineKeyboardMarkup()
    if businesses:
        kb.add(InlineKeyboardButton("📋 Список бізнесів", callback_data="business_list"))
    kb.add(InlineKeyboardButton("🛍️ Купити бізнес", callback_data="business_buy"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_business"))
    
    await call.message.edit_text(text, reply_markup=kb)

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
    
    cursor.execute("SELECT has_passport FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    has_passport = result[0] if result else False
    
    if not has_passport:
        # Профіль БЕЗ паспорта
        await show_profile_without_passport(call, user_id)
    else:
        # Профіль З паспортом (поки старий профіль)
        await show_old_profile(call, user_id)

async def show_old_profile(call: types.CallbackQuery, user_id: int):
    """Старий профіль (тимчасово)"""
    cursor.execute("SELECT username, level, xp, coins, role, total_taps FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result:
        username, level, xp, coins, role, total_taps = result
        prefix = get_user_prefix(user_id)
        farm_income = get_user_farm_income(user_id)
        estate_income = get_user_real_estate_income(user_id)
        total_passive = farm_income + estate_income
        
        text = (
            f"👤 <b>Профіль гравця</b>\n\n"
            f"🆔 <b>ID:</b> {user_id}\n"
            f"👤 <b>Ім'я:</b> {prefix} {username}\n"
            f"🎯 <b>Рівень:</b> {level}\n"
            f"💎 <b>Монети:</b> {coins} ✯\n"
            f"🎭 <b>Роль:</b> {role}\n"
            f"👆 <b>Тапів:</b> {total_taps}\n\n"
            f"💰 <b>Пасивний дохід:</b>\n"
            f"• 🐓 Ферма: {farm_income} ✯/6 год\n"
            f"• 🏘️ Нерухомість: {estate_income} ✯/6 год\n"
            f"• 💰 Всього: {total_passive} ✯/6 год"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view"))
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
    
    text = (
        f"💰 <b>Система доходів</b>\n\n"
        f"💎 <b>Ваш баланс:</b> {get_user_coins(user_id)} ✯\n\n"
        f"📊 <b>Поточні доходи:</b>\n"
        f"• 🐓 Ферма: {farm_income} ✯/6 год\n"
        f"• 🏘️ Нерухомість: {estate_income} ✯/6 год\n"
        f"• 💰 Всього пасивно: {total_passive} ✯/6 год\n\n"
        f"🎯 <b>Оберіть розділ для детальнішої інформації:</b>"
    )
    
    await call.message.edit_text(text, reply_markup=build_income_menu(user_id))

@dp.callback_query_handler(lambda c: c.data == 'menu_leaderboard')
async def cb_menu_leaderboard(call: types.CallbackQuery):
    await call.answer()
    cursor.execute("SELECT user_id, username, level, coins, role, prefix FROM players ORDER BY coins DESC LIMIT 10")
    top_players = cursor.fetchall()
    
    text = "🏆 <b>Топ 10 гравців</b>\n\n"
    
    if top_players:
        for i, (user_id, username, level, coins, role, prefix) in enumerate(top_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            display_name = f"{prefix} {username}" if prefix else username
            text += f"{medal} {display_name} - {coins} ✯\n"
            text += f"   🎯 Рівень: {level} | 🎭 Роль: {role}\n\n"
    else:
        text += "📊 Немає даних про гравців\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="menu_leaderboard"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'menu_shop')
async def cb_menu_shop(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    cursor.execute("SELECT has_passport FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    has_passport = result[0] if result else False
    
    if has_passport:
        text = (
            "🛍️ <b>Магазин</b>\n\n"
            "Оберіть категорію:\n\n"
            "• 🐓 <b>Ферма</b> - Тварини для пасивного доходу\n"
            "• 🏘️ <b>Нерухомість</b> - Об'єкти нерухомості\n"
            "• 🎭 <b>Ролі</b> - Спеціальні можливості\n"
            "• 🏷️ <b>Префікси</b> - Стильні позначки\n"
            "• 🎯 <b>Рівні</b> - Швидке підвищення рівня\n\n"
            "💡 <b>Порада:</b> Інвестуйте в пасивний дохід!"
        )
    else:
        text = (
            "🛍️ <b>Магазин</b>\n\n"
            "❌ <b>У вас немає паспорта!</b>\n\n"
            "📋 <b>Доступно без паспорта:</b>\n"
            "• 🎯 Купівля рівнів\n\n"
            "📋 <b>Потрібен паспорт:</b>\n"
            "• 🐓 Ферма\n• 🏘️ Нерухомість\n• 🎭 Ролі\n• 🏷️ Префікси\n\n"
            "💡 Отримайте паспорт в профілі!"
        )
    
    await call.message.edit_text(text, reply_markup=build_shop_menu(user_id))

@dp.callback_query_handler(lambda c: c.data == 'menu_roulettes')
async def cb_menu_roulettes(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🎰 <b>Рулетки</b>\n\n"
        "Оберіть тип рулетки:\n\n"
        "• 🎪 <b>Рулетка предметів</b> - Вигравайте унікальні предмети\n"
        "• 💰 <b>Звичайна рулетка</b> - Вигравайте монети (50 ✯ за спін)\n"
    )
    await call.message.edit_text(text, reply_markup=build_roulettes_menu())

@dp.callback_query_handler(lambda c: c.data == 'menu_friends')
async def cb_menu_friends(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    text = (
        "👥 <b>Система друзів</b>\n\n"
        "📊 <b>Функції:</b>\n"
        "• Додавайте друзів за ID\n"
        "• Надсилайте монети друзям\n"
        "• Переглядайте список друзів\n"
        "• Приймайте запити у друзі\n\n"
        "💡 <b>Новинка:</b> Система запитів у друзі як у соцмережах!"
    )
    
    await call.message.edit_text(text, reply_markup=build_friends_menu(user_id))  # ДОДАВ user_id

def build_remove_friends_menu(user_id: int, page: int = 1):
    """Побудувати меню видалення друзів"""
    friends = get_user_friends(user_id)
    items_per_page = 5
    total_pages = (len(friends) + items_per_page - 1) // items_per_page
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_friends = friends[start_idx:end_idx]
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for friend in page_friends:
        kb.add(InlineKeyboardButton(
            f"👤 {friend['username']}",
            callback_data=f"friend_remove_{friend['user_id']}"
        ))
    
    # Кнопки пагінації
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("◀️", callback_data=f"friends_remove_{page-1}"))
    
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("▶️", callback_data=f"friends_remove_{page+1}"))
    
    if pagination_buttons:
        kb.row(*pagination_buttons)
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_friends"))
    
    return kb
@dp.callback_query_handler(lambda c: c.data == 'friends_remove')
async def cb_friends_remove(call: types.CallbackQuery):
    """Меню видалення друзів"""
    await call.answer()
    user_id = call.from_user.id
    
    friends = get_user_friends(user_id)
    
    if not friends:
        text = (
            f"🗑️ <b>Видалення друзів</b>\n\n"
            f"✅ У вас немає друзів для видалення!\n\n"
            f"💡 Спочатку додайте друзів."
        )
    else:
        text = (
            f"🗑️ <b>Видалення друзів</b>\n\n"
            f"👥 У вас {len(friends)} друзів\n\n"
            f"⚠️ <b>Оберіть друга для видалення:</b>\n\n"
            f"🔴 Ця дія незворотня! Друга буде видалено з обох списків."
        )
    
    await call.message.edit_text(text, reply_markup=build_remove_friends_menu(user_id))

@dp.callback_query_handler(lambda c: c.data.startswith('friends_remove_'))
async def cb_friends_remove_page(call: types.CallbackQuery):
    """Пагінація меню видалення друзів"""
    await call.answer()
    user_id = call.from_user.id
    page = int(call.data.split('_')[2])
    
    friends = get_user_friends(user_id)
    
    text = (
        f"🗑️ <b>Видалення друзів</b>\n\n"
        f"👥 У вас {len(friends)} друзів\n\n"
        f"⚠️ <b>Оберіть друга для видалення:</b>\n\n"
        f"🔴 Ця дія незворотня! Друга буде видалено з обох списків."
    )
    
    await call.message.edit_text(text, reply_markup=build_remove_friends_menu(user_id, page))

@dp.callback_query_handler(lambda c: c.data.startswith('friend_remove_'))
async def cb_friend_remove_confirm(call: types.CallbackQuery):
    """Підтвердження видалення друга"""
    await call.answer()
    user_id = call.from_user.id
    friend_id = int(call.data.split('_')[2])
    
    friend_info = get_friend_info(user_id, friend_id)
    
    if not friend_info:
        await call.answer("❌ Друг не знайдений!", show_alert=True)
        return
    
    text = (
        f"🗑️ <b>ПІДТВЕРДЖЕННЯ ВИДАЛЕННЯ</b>\n\n"
        f"👤 Друг: {friend_info['username']}\n"
        f"🆔 ID: {friend_id}\n"
        f"🎯 Рівень: {friend_info['level']}\n"
        f"💰 Баланс: {friend_info['coins']:,} ✯\n"
        f"🎭 Роль: {friend_info['role']}\n"
        f"📅 Додано: {friend_info['added_date'][:10]}\n\n"
        f"⚠️ <b>Ви впевнені, що хочете видалити цього друга?</b>\n\n"
        f"🔴 Ця дія незворотня! Ви не зможете надсилати гроші цьому гравцю."
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("✅ Так, видалити", callback_data=f"friend_confirm_remove_{friend_id}"),
        InlineKeyboardButton("❌ Скасувати", callback_data="friends_remove")
    )
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('friend_confirm_remove_'))
async def cb_friend_confirm_remove(call: types.CallbackQuery):
    """Підтверджене видалення друга"""
    await call.answer()
    user_id = call.from_user.id
    friend_id = int(call.data.split('_')[3])
    
    friend_info = get_friend_info(user_id, friend_id)
    
    if not friend_info:
        await call.answer("❌ Друг не знайдений!", show_alert=True)
        return
    
    if remove_friend(user_id, friend_id):
        text = (
            f"✅ <b>ДРУГА ВИДАЛЕНО</b>\n\n"
            f"👤 {friend_info['username']} був видалений з вашого списку друзів.\n\n"
            f"💔 Ви більше не будете друзями в системі."
        )
        
        # Сповіщаємо друга про видалення (необов'язково)
        try:
            await bot.send_message(
                friend_id,
                f"💔 <b>ВИ ВИДАЛЕНІ З ДРУЗІВ</b>\n\n"
                f"👤 {call.from_user.username or call.from_user.full_name} видалив вас зі списку друзів."
            )
        except:
            pass  # Не вдалось відправити сповіщення
        
    else:
        text = "❌ Не вдалося видалити друга!"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📋 Список друзів", callback_data="friends_list"))
    kb.add(InlineKeyboardButton("⬅️ Меню друзів", callback_data="menu_friends"))
    
    await call.message.edit_text(text, reply_markup=kb)

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
#====================== INFO ==========================
@dp.message_handler(commands=['info'])
async def cmd_info(message: types.Message):
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    cursor.execute("SELECT has_passport FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    has_passport = result[0] if result else False
    
    text = (
        f"⟡━━━━━━━━━━━━━━━⟡\n"
        f"      📚  <b>ІНФОРМАЦІЯ ПРО БОТА</b>\n"
        f"⟡━━━━━━━━━━━━━━━⟡\n\n"
    )
    
    if not has_passport:
        text += (
            f"🎯 <b>ЕТАП 1: ПОЧАТОК ГРИ</b>\n"
            f"1. Грайте в 🎮 <b>Ігри</b> для заробітку\n"
            f"2. Отримайте 🎯 <b>2 рівень</b> та 1000 ✯\n"
            f"3. Купіть 🛂 <b>Паспорт</b> в профілі\n\n"
            f"📋 <b>ДОСТУПНО БЕЗ ПАСПОРТА:</b>\n"
            f"• 🎮 Всі ігри (заробляйте монети)\n"
            f"• 🛍️ Магазин рівнів (підвищуйте рівень)\n"
            f"• 👤 Профіль (отримайте паспорт)\n\n"
        )
    else:
        text += (
            f"✅ <b>У ВАС Є ПАСПОРТ!</b>\n\n"
            f"🎯 <b>ПОВНИЙ ДОСТУП:</b>\n"
        )
    
    text += (
        f"📋 <b>ОСНОВНІ РОЗДІЛИ:</b>\n"
        f"• 🎮 <b>Ігри</b> - заробляйте монети\n"
        f"• 🛍️ <b>Магазин</b> - купуйте покращення\n"
        f"• 👤 <b>Профіль</b> - ваш паспорт та статистика\n"
        f"• 💰 <b>Доходи</b> - пасивний заробіток\n"
        f"• 📦 <b>Інвентар</b> - ваші предмети\n"
        f"• 👥 <b>Друзі</b> - спілкування та перекази\n"
        f"• 🏆 <b>Топ гравців</b> - рейтинг\n\n"
    )
    
    text += (
        f"🎮 <b>ІГРИ ДЛЯ ЗАРОБІТКУ:</b>\n"
        f"• 🎯 <b>Вікторина</b> - відповідайте на питання\n"
        f"• 👆 <b>Tap Game</b> - клікайте та заробляйте\n"
        f"• 🎰 <b>Рулетки</b> - вигравайте призи\n"
        f"• ⚔️ <b>PvP Дуель</b> - змагайтесь з гравцями\n"
        f"• 🎲 <b>Кістки</b> - випробуйте удачу\n"
        f"• 🎯 <b>Вгадай число</b> - тестуйте інтуїцію\n\n"
    )
    
    text += (
        f"💰 <b>ПАСИВНИЙ ДОХІД:</b>\n"
        f"• 🐓 <b>Ферма</b> - тварини приносять дохід\n"
        f"• 🏘️ <b>Нерухомість</b> - об'єкти нерухомості\n"
        f"• 💰 Дохід нараховується кожні 6 годин\n\n"
    )
    
    text += (
        f"🛍️ <b>МАГАЗИН:</b>\n"
        f"• 🐓 <b>Ферма</b> - тварини\n"
        f"• 🏘️ <b>Нерухомість</b> - об'єкти\n"
        f"• 🎭 <b>Ролі</b> - спеціальні можливості\n"
        f"• 🏷️ <b>Префікси</b> - стильні позначки\n"
        f"• 🎯 <b>Рівні</b> - швидке підвищення\n\n"
    )
    
    text += (
        f"⚡ <b>КОРИСНІ КОМАНДИ:</b>\n"
        f"• /start - головне меню\n"
        f"• /info - ця довідка\n"
        f"• /profile - ваш профіль\n"
        f"• /shop - магазин\n"
        f"• /games - ігри\n"
        f"• /inventory - інвентар\n"
        f"• /friends - друзі\n\n"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    await message.answer(text, reply_markup=kb)
# ========== ІНВЕНТАР ТА АУКЦІОН ==========

@dp.callback_query_handler(lambda c: c.data.startswith('sell_item_menu|'))
async def cb_sell_item_menu(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    page = int(call.data.split('|')[1])
    
    items_per_page = 10
    user_items = get_user_inventory(user_id)
    
    if not user_items:
        await call.message.edit_text(
            "❌ <b>У вас немає предметів для продажу!</b>\n\n"
            "🎪 Отримайте предмети з рулетки предметів.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view")
            )
        )
        return
    
    # Розділяємо предмети на сторінки
    total_pages = (len(user_items) + items_per_page - 1) // items_per_page
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_items = user_items[start_idx:end_idx]
    
    text = f"💰 <b>Продаж предметів</b>\n\n"
    text += f"📦 Предметів: {len(user_items)}/10\n\n"
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for i, item in enumerate(page_items, start_idx + 1):
        # Отримуємо ID предмета
        item_id = "??"
        
        if item["category"] == "role":
            # Для ролей
            item_id = f"role_{item.get('role_id', '?')}"
            item_name_display = item["name"]
        else:
            # Для звичайних предметів
            for prize in ItemRoulettePrizes.PRIZES:
                if prize["name"] == item["name"]:
                    item_id = prize["id"]
                    break
            item_name_display = item["name"]
        
        text += f"{i}. {item_name_display} (ID: {item_id})\n"
        text += f"   💰 Ціна: {item['price']} ✯\n\n"
        
        # Кнопки для продажу
        kb.row(
            InlineKeyboardButton(
                f"🎁 {item_name_display[:10]}...", 
                callback_data=f"select_sell_item|{item_id}"
            ),
            InlineKeyboardButton(
                f"💰 {item['price']}✯", 
                callback_data=f"quick_sell|{item_id}"
            )
        )
    
    # Кнопки пагінації тільки якщо більше 1 сторінки
    if total_pages > 1:
        pagination_buttons = []
        if page > 1:
            pagination_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"sell_item_menu|{page-1}"))
        
        if page < total_pages:
            pagination_buttons.append(InlineKeyboardButton("Вперед ▶️", callback_data=f"sell_item_menu|{page+1}"))
        
        if pagination_buttons:
            kb.row(*pagination_buttons)
    
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)
    
    # Розділяємо предмети на сторінки
    total_pages = (len(user_items) + items_per_page - 1) // items_per_page
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_items = user_items[start_idx:end_idx]
    
    text = f"💰 <b>Продаж предметів</b>\n\n"
    text += f"📦 Предметів: {len(user_items)}/10\n\n"
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for i, item in enumerate(page_items, start_idx + 1):
        # Знаходимо ID предмета
        item_id = "??"
        for prize in ItemRoulettePrizes.PRIZES:
            if prize["name"] == item["name"]:
                item_id = prize["id"]
                break
        
        text += f"{i}. {item['name']} (ID: {item_id})\n"
        text += f"   💰 Ціна: {item['price']} ✯\n\n"
        
        # Кнопки для продажу
        kb.row(
            InlineKeyboardButton(
                f"🎁 {item['name'][:10]}...", 
                callback_data=f"select_sell_item|{item_id}"
            ),
            InlineKeyboardButton(
                f"💰 {item['price']}✯", 
                callback_data=f"quick_sell|{item_id}"
            )
        )
    
    # Кнопки пагінації тільки якщо більше 1 сторінки
    if total_pages > 1:
        pagination_buttons = []
        if page > 1:
            pagination_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"sell_item_menu|{page-1}"))
        
        if page < total_pages:
            pagination_buttons.append(InlineKeyboardButton("Вперед ▶️", callback_data=f"sell_item_menu|{page+1}"))
        
        if pagination_buttons:
            kb.row(*pagination_buttons)
    
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('select_sell_item|'))
async def cb_select_sell_item(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    item_id_str = call.data.split('|')[1]  # Змінюємо назву змінної
    
    # Перевіряємо чи це роль
    if item_id_str.startswith('role_'):
        # Це роль
        role_id = int(item_id_str.replace('role_', ''))
        cursor.execute("SELECT role_name FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
        role_data = cursor.fetchone()
        
        if not role_data:
            await call.answer("❌ Роль не знайдена!", show_alert=True)
            return
            
        role_name = role_data[0]
        role_price = next((r["price"] for r in Roles.ROLES if r["id"] == role_id), 500)
        sell_price = int(role_price * 0.7)
        
        text = (
            f"💰 <b>Продаж ролі</b>\n\n"
            f"🎭 Роль: {role_name}\n"
            f"🆔 ID: {item_id_str}\n"
            f"💎 Оригінальна ціна: {role_price} ✯\n"
            f"💰 Ціна продажу: {sell_price} ✯ (70%)\n\n"
            f"⚠️ <b>Увага:</b> При продажі ролі вона буде видалена з вашого профілю!"
        )
        
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("💰 Швидка продажа", callback_data=f"quick_sell|{item_id_str}")
        )
        
    else:
        # Це звичайний предмет - спробуємо перетворити в число
        try:
            item_id = int(item_id_str)
        except ValueError:
            await call.answer("❌ Неправильний ID предмета!", show_alert=True)
            return
            
        item_name = None
        item_price = 0
        for prize in ItemRoulettePrizes.PRIZES:
            if prize["id"] == item_id:
                item_name = prize["name"]
                item_price = prize["price"]
                break
        
        if not item_name:
            await call.answer("❌ Предмет не знайдено!", show_alert=True)
            return
        
        text = (
            f"💰 <b>Продаж предмета</b>\n\n"
            f"🎁 Предмет: {item_name}\n"
            f"🆔 ID: {item_id}\n"
            f"💎 Оригінальна ціна: {item_price} ✯\n\n"
            f"📝 <b>Варіанти продажу:</b>\n"
            f"• 🏪 На аукціон (90% ціни)\n"
            f"• 💰 Швидка продажа (70% ціни)\n\n"
        )
        
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🏪 На аукціон", callback_data=f"sell_auction|{item_id}"),
            InlineKeyboardButton("💰 Швидка продажа", callback_data=f"quick_sell|{item_id}")
        )
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="sell_item_menu|1"))
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('quick_sell|role_'))
async def cb_quick_sell_role(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    role_id = int(call.data.replace('quick_sell|role_', ''))
    
    # Знаходимо роль
    cursor.execute("SELECT role_name FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
    role_data = cursor.fetchone()
    
    if not role_data:
        await call.answer("❌ Роль не знайдена!", show_alert=True)
        return
        
    role_name = role_data[0]
    role_price = next((r["price"] for r in Roles.ROLES if r["id"] == role_id), 500)
    sell_price = int(role_price * 0.7)  # 70% від ціни
    
    # Видаляємо роль
    cursor.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
    
    # Змінюємо роль гравця на "Новачок"
    cursor.execute("UPDATE players SET role = 'Новачок' WHERE user_id = ?", (user_id,))
    
    # Додаємо монети
    add_user_coins(user_id, sell_price)
    conn.commit()
    
    await call.answer(f"✅ Роль {role_name} продана за {sell_price} ✯!", show_alert=True)
    await cb_inventory_view(call)

@dp.message_handler(commands=['sellrole'])
async def cmd_sellrole(message: types.Message):
    """Продати роль командою"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "❌ <b>Неправильний формат!</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/sellrole ID_ролі</code>\n\n"
                "📝 <b>Приклад:</b>\n"
                "<code>/sellrole 1</code> - продати роль Фермер\n"
                "<code>/sellrole 7</code> - продати роль БАНКІР\n\n"
                "💡 <b>ID ролей:</b>\n"
                "1-Фермер, 2-Колектор, 3-Студент\n"
                "4-Активний, 5-Щасливчик, 6-Воїн, 7-БАНКІР"
            )
            return
        
        role_id = int(parts[1])
        
        if role_id < 1 or role_id > 7:
            await message.answer("❌ ID ролі має бути від 1 до 7!")
            return
        
        # Перевіряємо чи є роль
        cursor.execute("SELECT role_name FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
        role_data = cursor.fetchone()
        
        if not role_data:
            await message.answer("❌ У вас немає цієї ролі!")
            return
            
        role_name = role_data[0]
        role_price = next((r["price"] for r in Roles.ROLES if r["id"] == role_id), 500)
        sell_price = int(role_price * 0.7)
        
        # Продаємо роль
        cursor.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
        cursor.execute("UPDATE players SET role = 'Новачок' WHERE user_id = ?", (user_id,))
        add_user_coins(user_id, sell_price)
        conn.commit()
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))  # ДОДАЄМО КНОПКУ НАЗАД
        
        await message.answer(
            f"✅ <b>Роль продана!</b>\n\n"
            f"🎭 Роль: {role_name}\n"
            f"🆔 ID: {role_id}\n"
            f"💰 Отримано: {sell_price} ✯\n"
            f"💎 Новий баланс: {get_user_coins(user_id)} ✯\n\n"
            f"⚡ Ваша роль змінена на 'Новачок'",
            reply_markup=kb  # ДОДАЄМО КЛАВІАТУРУ
        )
        
    except ValueError:
        await message.answer("❌ ID ролі має бути числом!")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.callback_query_handler(lambda c: c.data.startswith('select_sell_item|'))
async def cb_select_sell_item(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    item_id = int(call.data.split('|')[1])
    
    # Знаходимо предмет
    item_name = None
    item_price = 0
    for prize in ItemRoulettePrizes.PRIZES:
        if prize["id"] == item_id:
            item_name = prize["name"]
            item_price = prize["price"]
            break
    
    if not item_name:
        await call.answer("❌ Предмет не знайдено!", show_alert=True)
        return
    
    text = (
        f"💰 <b>Продаж предмета</b>\n\n"
        f"🎁 Предмет: {item_name}\n"
        f"💎 Оригінальна ціна: {item_price} ✯\n\n"
        f"📝 <b>Варіанти продажу:</b>\n"
        f"• 🏪 На аукціон (90% ціни)\n"
        f"• 👤 Іншому гравцю\n\n"
        f"💡 <b>Порада:</b> На аукціоні предмет буде доступний 24 години"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🏪 На аукціон", callback_data=f"sell_auction|{item_id}"),
        InlineKeyboardButton("👤 Іншому гравцю", callback_data=f"sell_player|{item_id}"),
        InlineKeyboardButton("💰 Швидка продажа", callback_data=f"quick_sell|{item_id}"),
        InlineKeyboardButton("⬅️ Назад", callback_data="sell_item_menu|1")
    )
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('sell_auction|'))
async def cb_sell_auction(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    item_id = int(call.data.split('|')[1])
    
    # Знаходимо предмет
    item_data = None
    for prize in ItemRoulettePrizes.PRIZES:
        if prize["id"] == item_id:
            item_data = prize
            break
    
    if not item_data:
        await call.answer("❌ Предмет не знайдено!", show_alert=True)
        return
    
    # Перевіряємо чи є предмет в інвентарі
    user_items = get_user_inventory(user_id)
    if not any(item["name"] == item_data["name"] for item in user_items):
        await call.answer("❌ У вас немає цього предмета!", show_alert=True)
        return
    
    # Додаємо на аукціон
    if add_to_auction(user_id, item_data["name"], item_data["type"], item_data["price"]):
        # Видаляємо з інвентаря
        remove_from_inventory(user_id, item_data["name"])
        
        auction_price = int(item_data["price"] * 0.9)
        
        await call.message.edit_text(
            f"✅ <b>Предмет виставлено на аукціон!</b>\n\n"
            f"🎁 Предмет: {item_data['name']}\n"
            f"💰 Оригінальна ціна: {item_data['price']} ✯\n"
            f"🏪 Ціна на аукціоні: {auction_price} ✯\n"
            f"💸 Ви отримаєте: {int(auction_price * 0.96)} ✯\n\n"
            f"⏰ Предмет буде видалено через 24 години",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⚖️ Перейти до аукціону", callback_data="auction_view|1"),
                InlineKeyboardButton("⬅️ Назад", callback_data="sell_item_menu|1")
            )
        )
    else:
        await call.answer("❌ Помилка при додаванні на аукціон!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data.startswith('quick_sell|'))
async def cb_quick_sell(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    item_id_str = call.data.replace('quick_sell|', '')
    
    # Перевіряємо чи це роль
    if item_id_str.startswith('role_'):
        # Швидка продаж ролі
        role_id = int(item_id_str.replace('role_', ''))
        cursor.execute("SELECT role_name FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
        role_data = cursor.fetchone()
        
        if not role_data:
            await call.answer("❌ Роль не знайдена!", show_alert=True)
            return
            
        role_name = role_data[0]
        role_price = next((r["price"] for r in Roles.ROLES if r["id"] == role_id), 500)
        sell_price = int(role_price * 0.7)
        
        # Видаляємо роль
        cursor.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
        
        # Змінюємо роль гравця на "Новачок"
        cursor.execute("UPDATE players SET role = 'Новачок' WHERE user_id = ?", (user_id,))
        
        # Додаємо монети
        add_user_coins(user_id, sell_price)
        conn.commit()
        
        await call.answer(f"✅ Роль {role_name} продана за {sell_price} ✯!", show_alert=True)
        await cb_inventory_view(call)
        
    else:
        # Звичайний предмет
        try:
            item_id = int(item_id_str)
        except ValueError:
            await call.answer("❌ Неправильний ID предмета!", show_alert=True)
            return
            
        # Старий код для предметів
        item_data = None
        for prize in ItemRoulettePrizes.PRIZES:
            if prize["id"] == item_id:
                item_data = prize
                break
        
        if not item_data:
            await call.answer("❌ Предмет не знайдено!", show_alert=True)
            return
        
        # Швидка продажа - 70% від ціни
        quick_sell_price = int(item_data["price"] * 0.7)
        
        # Видаляємо з інвентаря
        remove_from_inventory(user_id, item_data["name"])
        
        # Додаємо монети
        add_user_coins(user_id, quick_sell_price)
        
        await call.message.edit_text(
            f"💰 <b>Предмет швидко продано!</b>\n\n"
            f"🎁 Предмет: {item_data['name']}\n"
            f"💎 Оригінальна ціна: {item_data['price']} ✯\n"
            f"🏪 Ви отримали: {quick_sell_price} ✯ (70%)\n"
            f"💸 Ваш баланс: {get_user_coins(user_id)} ✯",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔄 Продати ще", callback_data="sell_item_menu|1"),
                InlineKeyboardButton("⬅️ В інвентар", callback_data="inventory_view")
            )
        )

@dp.callback_query_handler(lambda c: c.data == 'inventory_view')
async def cb_inventory_view(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    items = get_user_inventory(user_id)  # Тільки предмети
    user_role = get_user_role(user_id)   # Отримуємо роль гравця
    
    total_items = len(items)
    
    text = f"📦 <b>Ваш інвентар</b>\n\n"
    
    # ДОДАЄМО ІНФОРМАЦІЮ ПРО РОЛЬ (не займає місце)
    if user_role != "Новачок":
        # Знаходимо ID ролі
        role_id = next((r["id"] for r in Roles.ROLES if r["name"] == user_role), "?")
        text += f"🎭 <b>Ваша роль:</b> {user_role} (ID: {role_id})\n"
        text += f"💡 Продати: <code>/sellrole {role_id}</code>\n\n"
    
    text += f"📊 Предметів: {total_items}/10\n\n"
    
    if total_items == 0:
        text += "❌ У вас немає предметів!\n🎪 Крутіть рулетку предметів щоб отримати предмети."
    else:
        text += "🎁 <b>Предмети:</b>\n"
        for i, item in enumerate(items[:10], 1):
            # Для предметів з рулетки
            item_id = "??"
            for prize in ItemRoulettePrizes.PRIZES:
                if prize["name"] == item["name"]:
                    item_id = prize["id"]
                    break
            
            text += f"{i}. {item['name']} (ID: {item_id}) - {item['price']} ✯\n"
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎪 Рулетка предметів", callback_data="menu_item_roulette"),
        InlineKeyboardButton("⚖️ Аукціон", callback_data="auction_view|1"),
        InlineKeyboardButton("🛠️ Крафт предметів", callback_data="crafting_menu")
    )
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_profile"))
    
    await call.message.edit_text(text, reply_markup=kb)
@dp.message_handler(commands=['roles'])
async def cmd_roles(message: types.Message):
    """Показати всі доступні ролі та їх ID"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    user_role = get_user_role(user_id)
    
    text = (
        f"🎭 <b>Система ролей</b>\n\n"
        f"⭐ <b>Ваша поточна роль:</b> {user_role}\n\n"
        f"📋 <b>Доступні ролі:</b>\n"
    )
    
    for role in Roles.ROLES:
        has_role = " ✅ ВАША" if role["name"] == user_role else ""
        text += f"• <b>{role['name']}</b> (ID: {role['id']}){has_role}\n"
        text += f"  💰 {role['price']} ✯ | {role['description']}\n\n"
    
    text += (
        f"💡 <b>Команди для роботи з ролями:</b>\n"
        f"• <code>/sellrole ID</code> - продати роль\n"
        f"• Перейти в магазин ролей для покупки\n\n"
        f"⚡ <b>Увага:</b> Можна мати тільки одну роль!"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ Магазин ролей", callback_data="shop_roles"))
    kb.add(InlineKeyboardButton("⬅️ Головне меню", callback_data="menu_back|main"))
    
    await message.answer(text, reply_markup=kb)
#======================= CRAFT MENU
@dp.callback_query_handler(lambda c: c.data == 'crafting_menu')
async def cb_crafting_menu(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    # Перевіряємо рівень
    user_level = get_user_level(user_id)
    if user_level < 5:
        await call.answer("❌ Крафт доступний з 5 рівня!", show_alert=True)
        return
    
    user_coins = get_user_coins(user_id)
    craftable_items = get_user_craftable_items(user_id)
    
    text = (
        f"🛠️ <b>Мастерня крафту</b>\n\n"
        f"💎 Баланс: {user_coins} ✯\n"
        f"🎯 Ваш рівень: {user_level}\n\n"
        f"📋 <b>Доступні рецепти:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for craftable in craftable_items:
        recipe = craftable["recipe"]
        emoji = "✅" if craftable["can_craft"] else "❌"
        
        text += f"\n{emoji} <b>{recipe['name']}</b>\n"
        text += f"💰 Вартість крафту: {recipe['cost']} ✯\n"
        
        # Інгредієнти
        text += "📦 Потрібно: "
        ingredients_text = []
        for ingredient in recipe["ingredients"]:
            ingredients_text.append(f"{ingredient['name']} x{ingredient['quantity']}")
        text += ", ".join(ingredients_text) + "\n"
        
        # Результат
        if recipe["result"] == "random_car":
            text += f"🎁 Результат: Випадкова машина\n"
        else:
            text += f"🎁 Результат: {recipe['result']} ({recipe['result_price']} ✯)\n"
        
        # Статус
        if not craftable["can_craft"]:
            text += f"❌ Не вистачає: {', '.join(craftable['missing_ingredients'])}\n"
        
        text += "\n"
        
        # Кнопка
        if craftable["can_craft"]:
            kb.insert(InlineKeyboardButton(
                f"🛠️ {recipe['name']} - {recipe['cost']}✯", 
                callback_data=f"craft_item_{recipe['id']}"
            ))
        else:
            kb.insert(InlineKeyboardButton(
                f"❌ {recipe['name']}", 
                callback_data="cannot_craft"
            ))
    
    if not any(craftable["can_craft"] for craftable in craftable_items):
        text += "\n💡 Зберіть потрібні предмети з рулетки для крафту!"
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('craft_item_'))
async def cb_craft_item(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    recipe_id = int(call.data.replace('craft_item_', ''))
    
    result = craft_item(user_id, recipe_id)
    
    if result["success"]:
        await call.answer("✅ Крафт успішний!", show_alert=True)
    else:
        await call.answer(result["message"], show_alert=True)
    
    await cb_crafting_menu(call)

@dp.callback_query_handler(lambda c: c.data == 'cannot_craft')
async def cb_cannot_craft(call: types.CallbackQuery):
    await call.answer("❌ Недостатньо матеріалів для крафту!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'auction_view')
async def cb_auction_view(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    cursor.execute("SELECT * FROM auction_items")
    auction_items = cursor.fetchall()
    
    text = "⚖️ <b>Аукціон</b>\n\n"
    
    if not auction_items:
        text += "❌ На аукціоні поки немає предметів!\n\n"
        text += "💡 Ви можете виставити свої предмети на продаж з інвентаря."
    else:
        text += "🏷️ <b>Доступні предмети:</b>\n\n"
        for item in auction_items:
            item_id, seller_id, item_name, item_type, original_price, auction_price, listed_date = item
            
            # Знаходимо продавця
            cursor.execute("SELECT username FROM players WHERE user_id = ?", (seller_id,))
            seller_name = cursor.fetchone()[0]
            
            # Комісія 4%
            commission = int(auction_price * 0.04)
            seller_gets = auction_price - commission
            
            text += f"🎁 {item_name}\n"
            text += f"💰 Ціна: {auction_price} ✯ (знижка 10%)\n"
            text += f"💸 Продавець отримає: {seller_gets} ✯\n"
            text += f"👤 Продавець: {seller_name}\n\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📦 Мій інвентар", callback_data="inventory_view"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)

# ========== ОБРОБНИКИ ПРОДАЖІВ ==========
@dp.callback_query_handler(lambda c: c.data.startswith('auction_view|'))
async def cb_auction_view(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    page = int(call.data.split('|')[1])
    
    # Очищаємо старі предмети
    cleanup_old_auction_items()
    
    cursor.execute("""
        SELECT ai.*, p.username 
        FROM auction_items ai 
        JOIN players p ON ai.user_id = p.user_id 
        ORDER BY ai.listed_date DESC
    """)
    all_auction_items = cursor.fetchall()
    
    items_per_page = 20
    total_pages = (len(all_auction_items) + items_per_page - 1) // items_per_page
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_items = all_auction_items[start_idx:end_idx]
    
    text = f"⚖️ <b>Аукціон</b>\n\n"
    text += f"📄 Сторінка {page}/{total_pages}\n"
    text += f"🎁 Всього предметів: {len(all_auction_items)}\n\n"
    
    if not page_items:
        text += "❌ На цій сторінці немає предметів!\n\n"
    else:
        for i, item in enumerate(page_items, start_idx + 1):
            item_id, seller_id, item_name, item_type, original_price, auction_price, listed_date, seller_name = item
            
            # Комісія 4%
            commission = int(auction_price * 0.04)
            seller_gets = auction_price - commission
            
            # Час розміщення
            list_time = datetime.fromisoformat(listed_date)
            time_ago = datetime.now() - list_time
            hours_ago = int(time_ago.total_seconds() // 3600)
            
            text += f"{i}. 🎁 {item_name}\n"
            text += f"   💰 Ціна: {auction_price} ✯\n"
            text += f"   👤 Продавець: {seller_name}\n"
            text += f"   ⏰ {hours_ago} год. тому\n"
            text += f"   🎯 Кнопка: /buy {item_id}\n\n"
    
    kb = InlineKeyboardMarkup(row_width=5)
    
    # Кнопки пагінації
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("◀️", callback_data=f"auction_view|{page-1}"))
    
    # Додаємо кнопки сторінок (максимум 5)
    start_page = max(1, page - 2)
    end_page = min(total_pages, start_page + 4)
    
    for p in range(start_page, end_page + 1):
        if p == page:
            pagination_buttons.append(InlineKeyboardButton(f"•{p}•", callback_data=f"auction_view|{p}"))
        else:
            pagination_buttons.append(InlineKeyboardButton(str(p), callback_data=f"auction_view|{p}"))
    
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("▶️", callback_data=f"auction_view|{page+1}"))
    
    if pagination_buttons:
        kb.row(*pagination_buttons)
    
    kb.row(
        InlineKeyboardButton("📦 Мій інвентар", callback_data="inventory_view"),
        InlineKeyboardButton("💰 Продати предмет", callback_data="sell_item_menu|1")
    )
    kb.row(InlineKeyboardButton("🔄 Оновити", callback_data=f"auction_view|{page}"))
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith('accept_sale_'))
async def cb_accept_sale(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    data_parts = call.data.split('_')
    seller_id = int(data_parts[2])
    item_id = int(data_parts[3])
    
    # Знаходимо запропоновану продаж
    cursor.execute("SELECT id FROM pending_sales WHERE seller_id = ? AND buyer_id = ?", (seller_id, user_id))
    sale = cursor.fetchone()
    
    if not sale:
        await call.answer("❌ Пропозиція не знайдена!", show_alert=True)
        return
    
    sale_id = sale[0]
    
    if accept_pending_sale(sale_id):
        await call.answer("✅ Покупку успішно завершено!", show_alert=True)
        
        # Повідомляємо продавця
        try:
            await bot.send_message(
                seller_id,
                f"✅ <b>Ваш предмет продано!</b>\n\n"
                f"👤 <b>Покупець:</b> {call.from_user.username or call.from_user.full_name}\n"
                f"💰 <b>Отримано:</b> {get_user_coins(seller_id)} ✯\n\n"
                f"💎 Ваш новий баланс: {get_user_coins(seller_id)} ✯"
            )
        except:
            pass
        
        # Видаляємо повідомлення пропозиції після прийняття
        await call.message.edit_text(
            "✅ <b>Покупку успішно завершено!</b>\n\n"
            "🎁 Предмет додано до вашого інвентаря.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view")
            )
        )
    else:
        await call.answer("❌ Недостатньо монет для покупки!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data.startswith('reject_sale_'))
async def cb_reject_sale(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    data_parts = call.data.split('_')
    seller_id = int(data_parts[2])
    item_id = int(data_parts[3])
    
    # Знаходимо запропоновану продаж
    cursor.execute("SELECT id FROM pending_sales WHERE seller_id = ? AND buyer_id = ?", (seller_id, user_id))
    sale = cursor.fetchone()
    
    if sale:
        reject_pending_sale(sale[0])
        
        # Повідомляємо продавця
        try:
            await bot.send_message(
                seller_id,
                f"❌ <b>Пропозицію відхилено</b>\n\n"
                f"👤 <b>Покупець:</b> {call.from_user.username or call.from_user.full_name}\n"
                f"💬 Відмовився від покупки вашого предмету."
            )
        except:
            pass
    
    await call.answer("❌ Пропозицію відхилено", show_alert=True)
    
    # Видаляємо повідомлення пропозиції після відхилення
    await call.message.edit_text(
        "❌ <b>Пропозицію відхилено</b>",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view")
        )
    )



@dp.callback_query_handler(lambda c: c.data.startswith('reject_sale_'))
async def cb_reject_sale(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    data_parts = call.data.split('_')
    seller_id = int(data_parts[2])
    item_id = int(data_parts[3])
    
    # Знаходимо запропоновану продаж
    cursor.execute("SELECT id FROM pending_sales WHERE seller_id = ? AND buyer_id = ?", (seller_id, user_id))
    sale = cursor.fetchone()
    
    if sale:
        reject_pending_sale(sale[0])
        
        # Повідомляємо продавця
        try:
            await bot.send_message(
                seller_id,
                f"❌ <b>Пропозицію відхилено</b>\n\n"
                f"👤 <b>Покупець:</b> {call.from_user.username or call.from_user.full_name}\n"
                f"💬 Відмовився від покупки вашого предмету."
            )
        except:
            pass
    
    await call.answer("❌ Пропозицію відхилено", show_alert=True)
    await call.message.edit_text(
        "❌ <b>Пропозицію відхилено</b>",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view")
        )
    )

# Івенти- Адмін івенти - ADMIN EVENT
def apply_event_bonus(base_reward, reward_type='coins'):
    """Застосувати бонуси івентів до винагороди"""
    event = get_active_event()
    
    if not event:
        return base_reward
    
    if event['type'] == '2xcoins' and reward_type == 'coins':
        return base_reward * 2
    elif event['type'] == '2xxp' and reward_type == 'xp':
        return base_reward * 2
    elif event['type'] == 'free_spins' and reward_type == 'spins':
        return 0  # Безкоштовні спіни
    
    return base_reward
# ========== ОБРОБНИКИ ІГОР ==========

@dp.callback_query_handler(lambda c: c.data == 'game_quiz')
async def cb_game_quiz(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    # Перевірка ліміту питань (бонус для Студента)
    role = get_user_role(user_id)
    daily_limit = DAILY_QUESTION_LIMIT
    if role == "Студент":
        daily_limit = 25
    
    cursor.execute("SELECT COUNT(*) FROM quiz_answers WHERE user_id = ? AND date = ?", 
                   (user_id, datetime.now().date().isoformat()))
    answered_count = cursor.fetchone()[0]
    
    if answered_count >= daily_limit:
        await call.message.edit_text(
            f"❌ <b>Ліміт питань на сьогодні вичерпано!</b>\n\n"
            f"Ви вже відповіли на {answered_count}/{daily_limit} питань.\n"
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
        
        if not questions:
            await call.message.edit_text(
                "❌ <b>Файл з питаннями порожній!</b>\n\n"
                "Додайте питання до файлу questions.json",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
                )
            )
            return
        
        # Фільтруємо тільки валідні питання (тепер з полем "answer")
        valid_questions = []
        for q in questions:
            if ('question' in q and 'options' in q and 'answer' in q and 
                isinstance(q['options'], list) and len(q['options']) > 0 and
                0 <= q['answer'] < len(q['options'])):
                valid_questions.append(q)
        
        if not valid_questions:
            await call.message.edit_text(
                "❌ <b>Немає валідних питань!</b>\n\n"
                "Перевірте формат питань у файлі questions.json\n"
                "Потрібні поля: question, options, answer",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
                )
            )
            return
            
        question = random.choice(valid_questions)
        
    except FileNotFoundError:
        await call.message.edit_text(
            "❌ <b>Файл з питаннями не знайдено!</b>\n\n"
            "Створіть файл questions.json з питаннями.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
            )
        )
        return
    except json.JSONDecodeError:
        await call.message.edit_text(
            "❌ <b>Помилка в форматі файлу питань!</b>\n\n"
            "Перевірте правильність JSON формату.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
            )
        )
        return
    except Exception as e:
        await call.message.edit_text(
            f"❌ <b>Помилка завантаження питань:</b>\n{e}",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="menu_games")
            )
        )
        return
    
    # Створюємо клавіатуру з варіантами відповідей (тепер з 'answer')
    kb = InlineKeyboardMarkup(row_width=2)
    for i, option in enumerate(question["options"]):
        kb.insert(InlineKeyboardButton(option, callback_data=f"quiz_answer_{i}_{question['answer']}"))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(
        f"❓ <b>Вікторина</b>\n\n"
        f"{question['question']}\n\n"
        f"📊 Сьогодні відповіли: {answered_count}/{daily_limit}",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith('quiz_answer_'))
async def cb_quiz_answer(call: types.CallbackQuery):
    user_id = call.from_user.id
    data_parts = call.data.split('_')
    
    if len(data_parts) != 4:
        await call.answer("❌ Помилка в форматі відповіді!", show_alert=True)
        return
    
    try:
        answer_index = int(data_parts[2])
        correct_index = int(data_parts[3])  # Тепер це 'answer'
    except ValueError:
        await call.answer("❌ Помилка в форматі відповіді!", show_alert=True)
        return
    
    # Бонус XP для Студента
    role = get_user_role(user_id)
    xp_bonus = 10
    if role == "Студент":
        xp_bonus = int(xp_bonus * 1.05)
    
    if answer_index == correct_index:
        # Правильна відповідь
        reward = 20
        add_user_coins(user_id, reward)
        add_user_xp(user_id, xp_bonus)
        
        cursor.execute(
            "INSERT INTO quiz_answers (user_id, date, correct) VALUES (?, ?, ?)",
            (user_id, datetime.now().date().isoformat(), 1)
        )
        conn.commit()
        
        update_daily_task(user_id, "correct_answers")
        update_daily_task(user_id, "play_minigames")
        
        text = (
            f"✅ <b>Правильно!</b>\n\n"
            f"🎉 Ви виграли {reward} ✯\n"
            f"📈 +{xp_bonus} досвіду\n\n"
            f"💎 Баланс: {get_user_coins(user_id)} ✯"
        )
    else:
        # Неправильна відповідь
        cursor.execute(
            "INSERT INTO quiz_answers (user_id, date, correct) VALUES (?, ?, ?)",
            (user_id, datetime.now().date().isoformat(), 0)
        )
        conn.commit()
        
        update_daily_task(user_id, "play_minigames")
        
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
    daily_limit = get_daily_tap_limit(user_id)
    next_level = tap_stats['level'] + 1
    next_boost = TapGame.BOOST_LEVELS.get(next_level)
    
    # Прогрес-бар для ліміту тапів
    tap_progress = min(tap_stats['daily_taps'] / daily_limit * 100, 100) if daily_limit != float('inf') else 0
    progress_bar = create_progress_bar(tap_progress)
    
    text = (
        f"👆 <b>Tap Game</b>\n\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n"
        f"🎯 Рівень: {tap_stats['level']}\n"
        f"💰 Дохід: {tap_stats['income']} ✯/тап\n"
        f"👆 Всього тапів: {tap_stats['total_taps']}\n"
        f"📊 Сьогодні: {tap_stats['daily_taps']}"
    )
    
    if daily_limit != float('inf'):
        text += f"/{daily_limit}\n{progress_bar}\n"
    else:
        text += "\n"
    
    if next_boost:
        text += f"\n⚡ Наступний рівень ({next_level}): {next_boost['income']} ✯/тап\n"
        text += f"💵 Ціна: {next_boost['price']} ✯\n\n"
    
    text += "🎮 Натискайте кнопку щоб заробляти монети!"
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    # Перевіряємо чи не перевищено ліміт
    if can_user_tap(user_id):
        kb.add(InlineKeyboardButton("👆 Тапнути!", callback_data="tap_click"))
    else:
        kb.add(InlineKeyboardButton("❌ Ліміт тапів вичерпано", callback_data="tap_limit"))
    
    if next_boost and get_user_coins(user_id) >= next_boost['price']:
        kb.add(InlineKeyboardButton(f"⚡ Прокачати ({next_boost['price']} ✯)", callback_data="tap_upgrade"))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_games"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'tap_click')
async def cb_tap_click(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    # Перевірка ліміту
    if not can_user_tap(user_id):
        await call.answer("❌ Ліміт тапів на сьогодні вичерпано!", show_alert=True)
        await cb_game_tap(call)
        return
    
    tap_stats = get_user_tap_stats(user_id)
    
    add_user_coins(user_id, tap_stats['income'])
    cursor.execute("UPDATE players SET total_taps = total_taps + 1, daily_taps = daily_taps + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    
    update_daily_task(user_id, "tap_count")
    await cb_game_tap(call)

@dp.callback_query_handler(lambda c: c.data == 'tap_limit')
async def cb_tap_limit(call: types.CallbackQuery):
    await call.answer("❌ Ліміт тапів на сьогодні вичерпано!", show_alert=True)

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
    
    bonus = 0
    if user_roll > opponent_roll:
        # Бонус для Воїна
        if get_user_role(user_id) == "Воїн":
            bonus = 50
            total_bet += bonus
        
        add_user_coins(user_id, total_bet)
        cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (bet_opponent, opponent_id))
        result_text = f"🎉 <b>Ви перемогли!</b>\n\n"
        reward = total_bet
        if bonus > 0:
            result_text += f"⚔️ Бонус Воїна: +{bonus} ✯\n"
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
    update_daily_task(user_id, "play_minigames")

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
    update_daily_task(user_id, "play_minigames")
    
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
    
    secret_number = random.randint(1, 3)  # Зміна з 1-10 на 1-3
    
    text = (
        f"🎯 <b>Вгадай число</b>\n\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🎯 <b>Правила:</b>\n"
        f"• Загадано число від 1 до 3\n"  # Оновлено діапазон
        f"• Ставка: 25 ✯\n"
        f"• Вгадали: +75 ✯ (x3)\n"
        f"• Не вгадали: -25 ✯\n\n"
        f"🔢 Оберіть число:"
    )
    
    kb = InlineKeyboardMarkup(row_width=3)
    buttons = []
    for i in range(1, 4):  # Зміна з 10 на 3
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
    update_daily_task(user_id, "play_minigames")
    
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

# ========== РУЛЕТКИ ==========
@dp.callback_query_handler(lambda c: c.data == 'menu_item_roulette')
async def cb_menu_item_roulette(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_level = get_user_level(user_id)
    user_coins = get_user_coins(user_id)
    
    # Перевірка рівня для рулетки предметів (тепер від 5 рівня)
    if user_level < 5:
        await call.message.edit_text(
            f"❌ <b>Рулетка предметів доступна з 5 рівня!</b>\n\n"
            f"🎯 Ваш рівень: {user_level}/5\n"
            f"💡 Піднімайте рівень, щоб отримати доступ до рулетки предметів!",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ Назад", callback_data="menu_roulettes")
            )
        )
        return
    
    can_spin = user_coins >= 200
    
    text = (
        f"🎪 <b>Рулетка предметів</b>\n\n"
        f"💎 Баланс: {user_coins} ✯\n"
        f"🎯 Вартість: 200 ✯\n"
        f"📊 Доступно: {'✅' if can_spin else '❌'}\n\n"
    )
    
    if not can_spin:
        text += "❌ Недостатньо монет! Потрібно 200 ✯\n\n"
    
    text += "🏆 <b>Топ призи:</b>\n"
    top_prizes = sorted(ItemRoulettePrizes.PRIZES, key=lambda x: x['price'], reverse=True)[:5]
    for prize in top_prizes:
        text += f"• {prize['name']} (ID: {prize['id']}) - {prize['price']} ✯\n"
    
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
    """Крутіння рулетки предметів"""
    await call.answer()
    user_id = call.from_user.id
    
    # Перевірка рівня (5+ для рулетки предметів)
    user_level = get_user_level(user_id)
    if user_level < 5:
        await call.answer("❌ Рулетка предметів доступна з 5 рівня!", show_alert=True)
        return
    
    if get_user_coins(user_id) < 200:
        await call.answer("❌ Недостатньо монет! Потрібно 200 ✯", show_alert=True)
        return
    
    # Списуємо монети
    cursor.execute("UPDATE players SET coins = coins - 200 WHERE user_id = ?", (user_id,))
    
    # Випадковий вибір призу
    r = random.random()
    cumulative_probability = 0.0
    
    for prize in ItemRoulettePrizes.PRIZES:
        cumulative_probability += prize["probability"]
        if r <= cumulative_probability:
            # Бонус для Щасливчика
            bonus = 0
            if get_user_role(user_id) == "Щасливчик":
                bonus = 60
                add_user_coins(user_id, bonus)
            
            # Додаємо предмет в інвентар
            if add_to_inventory(user_id, prize["name"], prize["price"], prize["type"]):
                conn.commit()
                
                update_daily_task(user_id, "spin_roulette")
                
                bonus_text = f"\n🎰 Бонус Щасливчика: +{bonus} ✯" if bonus > 0 else ""
                
                text = (
                    f"🎪 <b>Результат рулетки</b>\n\n"
                    f"🎉 Ви виграли: {prize['name']}!\n"
                    f"💎 Ціна: {prize['price']} ✯\n"
                    f"🆔 ID: {prize['id']}{bonus_text}\n\n"
                    f"💼 Предмет додано до інвентаря!\n"
                    f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
                )
            else:
                text = (
                    f"❌ <b>Інвентар переповнений!</b>\n\n"
                    f"🎉 Ви виграли: {prize['name']}!\n"
                    f"💎 Але інвентар переповнений (макс. 10 предметів)\n\n"
                    f"💡 Продайте або видаліть предмети з інвентаря"
                )
            
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("📦 Інвентар", callback_data="inventory_view"))
            kb.add(InlineKeyboardButton("🎪 Крутити ще", callback_data="item_roulette_spin"))
            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_item_roulette"))
            
            await call.message.edit_text(text, reply_markup=kb)
            return
    
    # Якщо жоден предмет не вибрано (малоймовірно, але на всяк випадок)
    await call.answer("❌ Помилка рулетки", show_alert=True)

# Продовження в наступній частині...
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
    
    # Бонус для Щасливчика
    bonus = 0
    if get_user_role(user_id) == "Щасливчик":
        bonus = 60
    
    total_win = win + bonus
    add_user_coins(user_id, total_win)
    update_daily_task(user_id, "spin_roulette")
    
    bonus_text = f"\n🎰 Бонус Щасливчика: +{bonus} ✯" if bonus > 0 else ""
    
    text = (
        f"💰 <b>Результат рулетки</b>\n\n"
        f"🎉 Ви виграли: {win} ✯!{bonus_text}\n"
        f"💰 Загальний виграш: {total_win} ✯\n\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💰 Крутити ще", callback_data="normal_roulette_spin"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="roulette_normal"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'income_farm')
async def cb_income_farm(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    # Оновлюємо дохід перед показом
    update_income_for_user(user_id)
    
    farm_income = get_user_farm_income(user_id)
    estate_income = get_user_real_estate_income(user_id)
    total_income_per_hour = farm_income + estate_income
    
    # Отримуємо інформацію про останнє нарахування
    last_income_time = get_last_income_time(user_id)
    next_income_time = "Не встановлено"
    
    if last_income_time:
        next_income_time = (last_income_time + timedelta(hours=1)).strftime("%H:%M")
    
    cursor.execute("SELECT animal_type, income, count FROM farm_animals WHERE user_id = ?", (user_id,))
    user_animals = cursor.fetchall()
    
    text = (
        f"🐓 <b>Ваша ферма</b>\n\n"
        f"💰 Дохід: {farm_income} ✯/6 год\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n"
        f"🕒 Наступне нарахування: ~{next_income_time}\n"
        f"🎯 Всього пасивно: {total_income_per_hour} ✯/6 год\n\n"
    )
    
    if user_animals:
        text += "🏠 <b>Ваші тварини:</b>\n"
        for animal_type, income, count in user_animals:
            text += f"• {animal_type}: {count} шт. ({income * count} ✯/6 год)\n"
    else:
        text += "❌ У вас ще немає тварин!\n"
    
    text += "\n🛍️ <b>Доступні тварини:</b>\n"
    for animal in FarmAnimals.ANIMALS[:3]:
        text += f"• {animal['emoji']} {animal['name']}: {animal['price']} ✯ ({animal['income']} ✯/год)\n"
    
    text += f"\n💡 <b>Дохід нараховується автоматично кожні 6 годин!</b>"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ Купити тварин", callback_data="shop_farm"))
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="income_farm"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'income_real_estate')
async def cb_income_real_estate(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    # Оновлюємо дохід перед показом
    update_income_for_user(user_id)
    
    farm_income = get_user_farm_income(user_id)
    estate_income = get_user_real_estate_income(user_id)
    total_income_per_hour = farm_income + estate_income
    
    # Отримуємо інформацію про останнє нарахування
    last_income_time = get_last_income_time(user_id)
    next_income_time = "Не встановлено"
    
    if last_income_time:
        next_income_time = (last_income_time + timedelta(hours=1)).strftime("%H:%M")
    
    cursor.execute("SELECT type, income FROM user_real_estate WHERE user_id = ?", (user_id,))
    user_estates = cursor.fetchall()
    
    text = (
        f"🏘️ <b>Ваша нерухомість</b>\n\n"
        f"💰 Дохід: {estate_income} ✯/6 год\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n"
        f"🕒 Наступне нарахування: ~{next_income_time}\n"
        f"🎯 Всього пасивно: {total_income_per_hour} ✯/6 год\n\n"
    )
    
    if user_estates:
        text += "🏠 <b>Ваші об'єкти:</b>\n"
        for estate_type, income in user_estates:
            text += f"• {estate_type}: {income} ✯/6 год\n"
    else:
        text += "❌ У вас ще немає нерухомості!\n"
    
    text += "\n🛍️ <b>Доступна нерухомість:</b>\n"
    for estate in RealEstate.PROPERTIES[:3]:
        text += f"• {estate['name']}: {estate['price']} ✯ ({estate['income']} ✯/6 год)\n"
    
    text += f"\n💡 <b>Дохід нараховується автоматично кожні 6 годин!</b>"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ Купити нерухомість", callback_data="shop_real_estate"))
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="income_real_estate"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'bank_collect')
async def cb_bank_collect(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    cursor.execute("SELECT total_commission FROM bank_income WHERE user_id = ?", (user_id,))
    bank_data = cursor.fetchone()
    
    if not bank_data or bank_data[0] == 0:
        await call.answer("❌ Немає доходу для збору!", show_alert=True)
        return
    
    total_commission = bank_data[0]
    add_user_coins(user_id, total_commission)
    
    # Оновлюємо банківський запис
    current_date = datetime.now().date().isoformat()
    cursor.execute(
        "UPDATE bank_income SET total_commission = 0, last_collect_date = ? WHERE user_id = ?",
        (current_date, user_id)
    )
    conn.commit()
    
    text = (
        f"🏦 <b>Збір банківського доходу</b>\n\n"
        f"💰 Зібрано: {total_commission} ✯\n"
        f"💎 Новий баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🎉 Комісії з продажів та переводів успішно зібрані!"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="bank_income"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

# Продовження в наступній частині...
# ========== МАГАЗИН ==========
# ========== МАГАЗИН ПРЕДМЕТІВ ==========

@dp.callback_query_handler(lambda c: c.data == 'shop_items')
async def cb_shop_items(call: types.CallbackQuery):
    """Магазин предметів"""
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    
    text = (
        f"🛍️ <b>Магазин предметів</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n\n"
        f"📦 <b>Категорії предметів:</b>\n"
        f"• ⛏️ Мінерали та руди\n"
        f"• 🔮 Магічні предмети\n"
        f"• ⚔️ Зброя та обладунки\n"
        f"• 🚗 Автозапчастини\n"
        f"• 🧪 Зілля та еліксири\n\n"
        f"💡 Купляйте предмети для крафтингу та колекціонування!"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⛏️ Мінерали", callback_data="shop_category_mineral"),
        InlineKeyboardButton("🔮 Магія", callback_data="shop_category_magic"),
        InlineKeyboardButton("⚔️ Зброя", callback_data="shop_category_weapon"),
        InlineKeyboardButton("🚗 Автозапчастини", callback_data="shop_category_car_part"),
        InlineKeyboardButton("🧪 Зілля", callback_data="shop_category_potion")
    )
    kb.add(InlineKeyboardButton("🛠️ Крафтинг", callback_data="crafting_menu"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_shop"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('shop_category_'))
async def cb_shop_category(call: types.CallbackQuery):
    """Показ предметів по категорії"""
    await call.answer()
    user_id = call.from_user.id
    category = call.data.replace('shop_category_', '')
    
    user_coins = get_user_coins(user_id)
    category_names = {
        'mineral': '⛏️ Мінерали та руди',
        'magic': '🔮 Магічні предмети', 
        'weapon': '⚔️ Зброя та обладунки',
        'car_part': '🚗 Автозапчастини',
        'potion': '🧪 Зілля та еліксири'
    }
    
    category_items = ITEMS_BY_CATEGORY.get(category, [])
    
    text = (
        f"🛍️ <b>{category_names.get(category, 'Предмети')}</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    if not category_items:
        text += "❌ Наразі немає предметів у цій категорії!"
    else:
        for item in category_items:
            can_buy = user_coins >= item['price']
            emoji = "✅" if can_buy else "❌"
            
            text += f"{emoji} {item['name']} - {item['price']} ✯ (ID: {item['id']})\n"
            
            if can_buy:
                kb.insert(InlineKeyboardButton(
                    f"{item['name']} - {item['price']}✯",
                    callback_data=f"buy_item_{item['id']}"
                ))
            else:
                kb.insert(InlineKeyboardButton(
                    f"❌ {item['price']}✯",
                    callback_data="cannot_buy_item"
                ))
    
    kb.add(InlineKeyboardButton("📦 Всі категорії", callback_data="shop_items"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_shop"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('buy_item_'))
async def cb_buy_item(call: types.CallbackQuery):
    """Купівля предмета з магазину"""
    await call.answer()
    user_id = call.from_user.id
    item_id = int(call.data.replace('buy_item_', ''))
    
    # Знаходимо предмет в магазині
    shop_item = next((item for item in ItemShop.ITEMS if item['id'] == item_id), None)
    if not shop_item:
        await call.answer("❌ Предмет не знайдено в магазині!", show_alert=True)
        return
    
    user_coins = get_user_coins(user_id)
    if user_coins < shop_item['price']:
        await call.answer("❌ Недостатньо монет для покупки!", show_alert=True)
        return
    
    # Знаходимо повну інформацію про предмет
    item_info = ITEM_BY_ID.get(item_id)
    if not item_info:
        await call.answer("❌ Інформація про предмет не знайдена!", show_alert=True)
        return
    
    # Перевіряємо місце в інвентарі
    user_items = get_user_inventory(user_id)
    if len(user_items) >= 10:
        await call.answer("❌ Інвентар переповнений! (макс. 10 предметів)", show_alert=True)
        return
    
    # Купівля предмета
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", 
                   (shop_item['price'], user_id))
    
    # Додаємо предмет в інвентар
    if add_to_inventory(user_id, item_info['name'], item_info['price'], item_info['type']):
        conn.commit()
        await call.answer(f"✅ Куплено {item_info['name']} за {shop_item['price']} ✯!", show_alert=True)
        
        # Повертаємось до магазину
        await cb_shop_items(call)
    else:
        await call.answer("❌ Помилка при додаванні предмета в інвентар!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'cannot_buy_item')
async def cb_cannot_buy_item(call: types.CallbackQuery):
    """Недостатньо монет для покупки"""
    await call.answer("❌ Недостатньо монет для покупки!", show_alert=True)

# ========== ПОКРАЩЕНИЙ КРАФТИНГ ==========

@dp.callback_query_handler(lambda c: c.data == 'crafting_menu')
async def cb_crafting_menu(call: types.CallbackQuery):
    """Покращене меню крафтингу"""
    await call.answer()
    user_id = call.from_user.id
    
    # Перевіряємо рівень
    user_level = get_user_level(user_id)
    if user_level < 5:
        await call.answer("❌ Крафт доступний з 5 рівня!", show_alert=True)
        return
    
    user_coins = get_user_coins(user_id)
    craftable_items = get_user_craftable_items(user_id)
    
    text = (
        f"🛠️ <b>Мастерня крафту</b>\n\n"
        f"💎 Баланс: {user_coins} ✯\n"
        f"🎯 Ваш рівень: {user_level}\n"
        f"📦 Доступно рецептів: {len([c for c in craftable_items if c['can_craft']])}/{len(craftable_items)}\n\n"
        f"📋 <b>Категорії рецептів:</b>\n"
    )
    
    # Групуємо рецепти по категоріям
    categories = {
        "jewelry": "💎 Ювелірні вироби",
        "weapon": "⚔️ Зброя", 
        "magic": "🔮 Магічні предмети",
        "potion": "🧪 Зілля",
        "car": "🚗 Транспорт",
        "legendary": "🌟 Легендарні предмети"
    }
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for category_id, category_name in categories.items():
        category_recipes = [c for c in craftable_items if c['recipe'].get('result_type') == category_id]
        available_count = len([c for c in category_recipes if c['can_craft']])
        
        emoji = "✅" if available_count > 0 else "⏳"
        kb.insert(InlineKeyboardButton(
            f"{emoji} {category_name}",
            callback_data=f"crafting_category_{category_id}"
        ))
    
    kb.add(InlineKeyboardButton("📦 Мій інвентар", callback_data="inventory_view"))
    kb.add(InlineKeyboardButton("🛍️ Магазин предметів", callback_data="shop_items"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('crafting_category_'))
async def cb_crafting_category(call: types.CallbackQuery):
    """Крафтинг по категорії"""
    await call.answer()
    user_id = call.from_user.id
    category = call.data.replace('crafting_category_', '')
    
    user_coins = get_user_coins(user_id)
    craftable_items = get_user_craftable_items(user_id)
    
    category_names = {
        "jewelry": "💎 Ювелірні вироби",
        "weapon": "⚔️ Зброя",
        "magic": "🔮 Магічні предмети", 
        "potion": "🧪 Зілля",
        "car": "🚗 Транспорт",
        "legendary": "🌟 Легендарні предмети"
    }
    
    category_recipes = [c for c in craftable_items if c['recipe'].get('result_type') == category]
    
    text = (
        f"🛠️ <b>Крафтинг - {category_names.get(category, 'Предмети')}</b>\n\n"
        f"💎 Баланс: {user_coins} ✯\n\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    if not category_recipes:
        text += "❌ Немає рецептів у цій категорії!"
    else:
        for craftable in category_recipes:
            recipe = craftable["recipe"]
            emoji = "✅" if craftable["can_craft"] else "❌"
            
            text += f"\n{emoji} <b>{recipe['name']}</b>\n"
            text += f"💰 Вартість крафту: {recipe['cost']} ✯\n"
            
            # Інгредієнти
            text += "📦 Потрібно: "
            ingredients_text = []
            for ingredient in recipe["ingredients"]:
                ingredients_text.append(f"{ingredient['name']} x{ingredient['quantity']}")
            text += ", ".join(ingredients_text) + "\n"
            
            # Результат
            if recipe["result"] == "random_car":
                text += f"🎁 Результат: Випадкова машина\n"
            else:
                text += f"🎁 Результат: {recipe['result']} ({recipe['result_price']} ✯)\n"
            
            # Статус
            if not craftable["can_craft"]:
                text += f"❌ Не вистачає: {', '.join(craftable['missing_ingredients'])}\n"
            
            text += "\n"
            
            # Кнопка
            if craftable["can_craft"] and user_coins >= recipe["cost"]:
                kb.insert(InlineKeyboardButton(
                    f"🛠️ {recipe['name']} - {recipe['cost']}✯", 
                    callback_data=f"craft_item_{recipe['id']}"
                ))
            else:
                kb.insert(InlineKeyboardButton(
                    f"❌ {recipe['name']}", 
                    callback_data="cannot_craft"
                ))
    
    if not any(craftable["can_craft"] for craftable in category_recipes):
        text += "\n💡 Зберіть потрібні предмети з магазину або рулетки!"
    
    kb.add(InlineKeyboardButton("📂 Всі категорії", callback_data="crafting_menu"))
    kb.add(InlineKeyboardButton("🛍️ Магазин предметів", callback_data="shop_items"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)
    
@dp.callback_query_handler(lambda c: c.data == 'shop_levels')
async def cb_shop_levels(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    current_level = get_user_level(user_id)
    next_level = current_level + 1
    user_coins = get_user_coins(user_id)
    
    # Розраховуємо ціну
    price = 1500 * (2 ** (current_level - 1))
    can_buy = user_coins >= price
    
    text = (
        f"🎯 <b>Магазин рівнів</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n"
        f"🎯 Поточний рівень: {current_level}\n"
        f"⬆️ Наступний рівень: {next_level}\n"
        f"💰 Ціна: {price} ✯\n\n"
    )
    
    if can_buy:
        text += f"✅ Ви можете купити підвищення до {next_level} рівня!"
    else:
        text += f"❌ Недостатньо монет для покупки!\nПотрібно ще {price - user_coins} ✯"
    
    text += f"\n\n💡 <b>Ціни на наступні рівні:</b>\n"
    
    # Показуємо ціни на наступні 3 рівні
    for i in range(1, 4):
        level = current_level + i
        future_price = 1500 * (2 ** (level - 2))  # -2 бо показуємо ціну для переходу з level-1 на level
        text += f"• Рівень {level}: {future_price} ✯\n"
    
    kb = InlineKeyboardMarkup()
    
    if can_buy:
        kb.add(InlineKeyboardButton(f"🎯 Купити рівень {next_level} - {price}✯", callback_data="buy_level"))
    
    kb.add(InlineKeyboardButton("🛍️ До магазину", callback_data="menu_shop"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'buy_level')
async def cb_buy_level(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    result = buy_level(user_id)
    
    if result["success"]:
        await call.answer(f"✅ {result['message']}", show_alert=True)
    else:
        await call.answer(result["message"], show_alert=True)
    
    await cb_shop_levels(call)
@dp.callback_query_handler(lambda c: c.data == 'shop_farm')
async def cb_shop_farm(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    farm_income = get_user_farm_income(user_id)
    user_role = get_user_role(user_id)
    
    # Максимальна кількість тварин (бонус для Фермера)
    max_animals = 4
    if user_role == "Фермер":
        max_animals = 6
    
    text = (
        f"🛍️ <b>Магазин ферми</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n"
        f"💰 Поточний дохід: {farm_income} ✯/6 год\n"
        f"🐓 Макс. кількість: {max_animals} од.\n\n"
        f"🐓 <b>Доступні тварини:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for animal in FarmAnimals.ANIMALS:
        # Перевіряємо чи гравець вже має цю тварину та її кількість
        cursor.execute("SELECT count FROM farm_animals WHERE user_id = ? AND animal_type = ?", (user_id, animal['name']))
        result = cursor.fetchone()
        current_count = result[0] if result else 0
        
        can_buy = user_coins >= animal['price'] and current_count < max_animals
        emoji = "✅" if can_buy else "❌"
        
        text += f"{emoji} {animal['emoji']} {animal['name']}: {animal['price']} ✯ ({animal['income']} ✯/6 год)"
        if current_count > 0:
            text += f" [Маєте: {current_count}/{max_animals}]\n"
        else:
            text += "\n"
        
        if can_buy:
            kb.insert(InlineKeyboardButton(
                f"{animal['emoji']} {animal['price']}✯", 
                callback_data=f"buy_animal_{animal['name']}"
            ))
        else:
            kb.insert(InlineKeyboardButton(
                f"❌ {animal['price']}✯", 
                callback_data=f"cannot_buy_animal"
            ))
    
    text += f"\n💡 <b>Порада:</b> Тварини приносять пасивний дохід кожні 6 годин!"
    if user_role == "Фермер":
        text += f"\n🎭 <b>Бонус Фермера:</b> Можна купувати до {max_animals} тварин одного типу!"
    
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
    user_role = get_user_role(user_id)
    
    # Максимальна кількість тварин
    max_animals = 4
    if user_role == "Фермер":
        max_animals = 6
    
    # Перевіряємо поточну кількість
    cursor.execute("SELECT count FROM farm_animals WHERE user_id = ? AND animal_type = ?", (user_id, animal['name']))
    result = cursor.fetchone()
    current_count = result[0] if result else 0
    
    if current_count >= max_animals:
        await call.answer(f"❌ Досягнуто максимум ({max_animals}) для цієї тварини!", show_alert=True)
        return
    
    if user_coins < animal['price']:
        await call.answer("❌ Недостатньо монет!", show_alert=True)
        return
    
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", 
                   (animal['price'], user_id))
    
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
    
    await call.answer(f"✅ Куплено {animal['emoji']} {animal['name']}! Тепер у вас {current_count + 1}/{max_animals}", show_alert=True)
    await cb_shop_farm(call)

@dp.callback_query_handler(lambda c: c.data == 'cannot_buy_animal')
async def cb_cannot_buy_animal(call: types.CallbackQuery):
    await call.answer("❌ Недостатньо монет або досягнуто ліміт!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'shop_real_estate')
async def cb_shop_real_estate(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    estate_income = get_user_real_estate_income(user_id)
    user_role = get_user_role(user_id)
    
    # Максимальна кількість нерухомості (бонус для Колектора)
    max_estates = 2
    if user_role == "Колектор":
        max_estates = 4
    
    text = (
        f"🛍️ <b>Магазин нерухомості</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n"
        f"💰 Поточний дохід: {estate_income} ✯/6 год\n"
        f"🏘️ Макс. кількість: {max_estates} од.\n\n"
        f"🏘️ <b>Доступна нерухомість:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for estate in RealEstate.PROPERTIES:
        # Перевіряємо чи гравець вже має цю нерухомість
        cursor.execute("SELECT COUNT(*) FROM user_real_estate WHERE user_id = ? AND type = ?", (user_id, estate['name']))
        current_count = cursor.fetchone()[0]
        
        can_buy = user_coins >= estate['price'] and current_count < max_estates
        emoji = "✅" if can_buy else "❌"
        
        text += f"{emoji} {estate['name']}: {estate['price']} ✯ ({estate['income']} ✯/6 год)"
        if current_count > 0:
            text += f" [Маєте: {current_count}/{max_estates}]\n"
        else:
            text += "\n"
        
        if can_buy:
            kb.insert(InlineKeyboardButton(
                f"{estate['name']} {estate['price']}✯", 
                callback_data=f"buy_estate_{estate['name']}"
            ))
        else:
            kb.insert(InlineKeyboardButton(
                f"❌ {estate['price']}✯", 
                callback_data=f"cannot_buy_estate"
            ))
    
    text += f"\n💡 <b>Порада:</b> Нерухомість приносить стабільний пасивний дохід!"
    if user_role == "Колектор":
        text += f"\n🎭 <b>Бонус Колектора:</b> Можна купувати до {max_estates} об'єктів одного типу!"
    
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
    user_role = get_user_role(user_id)
    
    # Максимальна кількість нерухомості
    max_estates = 2
    if user_role == "Колектор":
        max_estates = 4
    
    # Перевіряємо поточну кількість
    cursor.execute("SELECT COUNT(*) FROM user_real_estate WHERE user_id = ? AND type = ?", (user_id, estate['name']))
    current_count = cursor.fetchone()[0]
    
    if current_count >= max_estates:
        await call.answer(f"❌ Досягнуто максимум ({max_estates}) для цього об'єкта!", show_alert=True)
        return
    
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
    
    await call.answer(f"✅ Куплено {estate['name']}! Тепер у вас {current_count + 1}/{max_estates}", show_alert=True)
    await cb_shop_real_estate(call)

@dp.callback_query_handler(lambda c: c.data == 'cannot_buy_estate')
async def cb_cannot_buy_estate(call: types.CallbackQuery):
    await call.answer("❌ Недостатньо монет або досягнуто ліміт!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'shop_roles')
async def cb_shop_roles(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    current_role = get_user_role(user_id)
    
    text = (
        f"🎭 <b>Магазин ролей</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n"
        f"🎯 Поточна роль: {current_role}\n\n"
        f"🎭 <b>Доступні ролі:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for role in Roles.ROLES:
        can_buy = user_coins >= role['price'] and current_role != role['name']
        has_role = current_role == role['name']
        emoji = "✅" if can_buy else "❌" if not has_role else "⭐"
        
        if has_role:
            text += f"{emoji} <b>{role['name']}</b> - У ВАС\n"
            text += f"   💰 {role['price']} ✯ | {role['description']}\n\n"
        else:
            text += f"{emoji} <b>{role['name']}</b>\n"
            text += f"   💰 {role['price']} ✯ | {role['description']}\n\n"
        
        if can_buy:
            kb.insert(InlineKeyboardButton(
                f"🎭 {role['name']} - {role['price']}✯", 
                callback_data=f"buy_role_{role['id']}"
            ))
        elif not has_role:
            kb.insert(InlineKeyboardButton(
                f"❌ {role['name']} - {role['price']}✯", 
                callback_data=f"cannot_buy_role"
            ))
        else:
            kb.insert(InlineKeyboardButton(
                f"⭐ {role['name']} - ВАША РОЛЬ", 
                callback_data=f"already_has_role"
            ))
    
    text += "💡 <b>Увага:</b> Можна мати тільки одну роль! При покупці нової стара продається."
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_shop"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('buy_role_'))
async def cb_buy_role(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    role_id = int(call.data.replace('buy_role_', ''))
    
    if buy_role(user_id, role_id):
        await call.answer("✅ Роль успішно куплена!", show_alert=True)
        await cb_shop_roles(call)
    else:
        await call.answer("❌ Помилка покупки ролі!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'cannot_buy_role')
async def cb_cannot_buy_role(call: types.CallbackQuery):
    await call.answer("❌ Недостатньо монет для покупки!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'already_has_role')
async def cb_already_has_role(call: types.CallbackQuery):
    await call.answer("⭐ Ця роль вже активна!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'shop_prefixes')
async def cb_shop_prefixes(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(user_id)
    current_prefix = get_user_prefix(user_id)
    
    text = (
        f"🏷️ <b>Магазин префіксів</b>\n\n"
        f"💎 Ваш баланс: {user_coins} ✯\n"
        f"🏷️ Поточний префікс: {current_prefix if current_prefix else 'Відсутній'}\n\n"
        f"🏷️ <b>Доступні префікси:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for prefix in Prefixes.PREFIXES:
        can_buy = user_coins >= prefix['price'] and current_prefix != prefix['name']
        has_prefix = current_prefix == prefix['name']
        emoji = "✅" if can_buy else "❌" if not has_prefix else "⭐"
        
        if has_prefix:
            text += f"{emoji} <b>{prefix['name']}</b> - У ВАС\n"
            text += f"   💰 {prefix['price']} ✯ | ID: {prefix['id']}\n\n"
        else:
            text += f"{emoji} <b>{prefix['name']}</b>\n"
            text += f"   💰 {prefix['price']} ✯ | ID: {prefix['id']}\n\n"
        
        if can_buy:
            kb.insert(InlineKeyboardButton(
                f"{prefix['name']} - {prefix['price']}✯", 
                callback_data=f"buy_prefix_{prefix['id']}"
            ))
        elif not has_prefix:
            kb.insert(InlineKeyboardButton(
                f"❌ {prefix['price']}✯", 
                callback_data=f"cannot_buy_prefix"
            ))
        else:
            kb.insert(InlineKeyboardButton(
                f"⭐ {prefix['name']}", 
                callback_data=f"already_has_prefix"
            ))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_shop"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('buy_prefix_'))
async def cb_buy_prefix(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    prefix_id = int(call.data.replace('buy_prefix_', ''))
    
    if buy_prefix(user_id, prefix_id):
        await call.answer("✅ Префікс успішно куплений!", show_alert=True)
        await cb_shop_prefixes(call)
    else:
        await call.answer("❌ Помилка покупки префікса!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'cannot_buy_prefix')
async def cb_cannot_buy_prefix(call: types.CallbackQuery):
    await call.answer("❌ Недостатньо монет для покупки!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == 'already_has_prefix')
async def cb_already_has_prefix(call: types.CallbackQuery):
    await call.answer("⭐ Цей префікс вже активний!", show_alert=True)

# ========== ЩОДЕННІ ЗАВДАННЯ ==========
@dp.callback_query_handler(lambda c: c.data == 'daily_tasks')
async def cb_daily_tasks(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    progress = get_daily_tasks_progress(user_id)
    
    text = (
        f"📋 <b>Щоденні завдання</b>\n\n"
        f"✅ Виконано: {progress['tasks_completed']}/2\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🎯 <b>Сьогоднішні завдання:</b>\n"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    buttons_added = False
    
    for i, task in enumerate(progress["active_tasks"]):
        # Прогрес-бар для завдання
        percentage = min((task['current'] / task['target']) * 100, 100)
        progress_bar = create_progress_bar(percentage)
        
        status = "✅" if task["completed"] else "⏳"
        text += f"{i+1}. {task['description']} {status}\n"
        text += f"   {progress_bar}\n"
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


# ========== ДОДАТКОВІ ФУНКЦІЇ ==========
def add_user_xp(user_id: int, xp: int):
    # Бонус для Студента
    role = get_user_role(user_id)
    if role == "Студент":
        xp = int(xp * 1.05)
    
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

def create_progress_bar(percentage: float, length: int = 10) -> str:
    filled = int(length * percentage / 100)
    empty = length - filled
    return f"[{'█' * filled}{'░' * empty}] {percentage:.1f}%"

# ========== АДМІН-ADMIN
#додати адміністратора
# ========== КОНФИГ ==========
BOT_TOKEN = "8160983444:AAF-qKOw_MtVhFPtnejy3UcbPT59riKrsd8"
OWNER_ID = 5672490558  # ТВІЙ ID
ADMIN_IDS = [OWNER_ID]  # Початковий список - тільки ти

# ========== ПЕРЕВІРКА АДМІНА ==========
def is_admin(user_id: int) -> bool:
    """Перевіряє чи є користувач адміном (з автоматичним створенням таблиці)"""
    try:
        # Власник завжди адмін
        if user_id == OWNER_ID:
            return True
            
        # Спочатку перевіряємо чи таблиця існує
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='bot_admins'
        """)
        table_exists = cursor.fetchone()
        
        if not table_exists:
            # Якщо таблиці немає - створюємо її
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    added_date TEXT NOT NULL,
                    status TEXT DEFAULT 'active'
                )
            """)
            conn.commit()
            print("✅ Таблицю bot_admins створено")
            return False  # Поки ніхто не адмін крім власника
        
        # Перевіряємо в базі даних
        cursor.execute("""
            SELECT 1 FROM bot_admins 
            WHERE user_id = ? AND (status = 'active' OR status IS NULL)
        """, (user_id,))
        
        is_adm = cursor.fetchone() is not None
        
        # Додатковий дебаг
        if is_adm:
            print(f"✅ Користувач {user_id} знайдений в адмінах")
        else:
            print(f"❌ Користувач {user_id} не знайдений в адмінах")
            
        return is_adm
        
    except Exception as e:
        print(f"❌ Помилка перевірки адміна {user_id}: {e}")
        return False


# ========== КОМАНДИ ДЛЯ ВЛАСНИКА ==========

# ========== НОВА ПРОСТА АДМІН-СИСТЕМА ==========

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

@dp.callback_query_handler(lambda c: c.data == 'simple_admin_panel')
async def cb_simple_admin_panel(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Доступ заборонено!", show_alert=True)
        return
    
    text = (
        "👑 <b>АДМІН-ПАНЕЛЬ v2.0</b>\n\n"
        "⚡ <b>Використовуй команди:</b>\n\n"
        "💰 <b>Гроші:</b>\n"
        "<code>/setcoins ID сумма</code>\n"
        "<code>/rewardtop5 сумма</code>\n"
        "<code>/rewardactive сумма</code>\n\n"
        
        "📊 <b>Статистика:</b>\n"  
        "<code>/adminstats</code>\n"
        "<code>/users</code>\n\n"
        
        "🎯 <b>Івенти:</b>\n"
        "<code>/event start 2xcoins 24</code>\n"
        "<code>/event status</code>\n\n"
        
        "⚡ <b>Експорт:</b>\n"
        "<code>/export users</code>\n"
        "<code>/export items</code>\n\n"
        
        "🛡️ <b>Модерація:</b>\n"
        "<code>/warn ID причина</code>\n"
        "<code>/mute ID хвилини</code>\n"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="simple_admin_panel"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    await call.message.edit_text(text, reply_markup=kb)

# ========== БАЗОВІ АДМІН-КОМАНДИ ==========

@dp.message_handler(commands=['setcoin'])
async def cmd_setcoin(message: types.Message):
    """Встановити/додати/відняти монети гравцю"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer(
                "💰 <b>КОМАНДА SETCOIN</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/setcoin ID сумма</code> - встановити баланс\n"
                "<code>/setcoin ID +сума</code> - додати монети\n"
                "<code>/setcoin ID -сума</code> - відняти монети\n\n"
                "🎯 <b>Приклади:</b>\n"
                "<code>/setcoin 123456789 1000</code> - встановити 1000 ✯\n"
                "<code>/setcoin 123456789 +500</code> - додати 500 ✯\n"
                "<code>/setcoin 123456789 -200</code> - відняти 200 ✯\n\n"
                "⚠️ <b>Увага:</b> Без знаку + чи - встановлює точний баланс!"
            )
            return
        
        user_id = int(parts[1])
        amount_str = parts[2]
        
        # ВИПРАВЛЕНА ЛОГІКА: правильно визначаємо операцію
        operation = "set"  # за замовчуванням - встановити
        
        if amount_str.startswith('+'):
            operation = "add"
            amount = int(amount_str[1:])
        elif amount_str.startswith('-'):
            operation = "subtract" 
            amount = int(amount_str[1:])
        else:
            # Якщо немає + чи - на початку, то це встановлення значення
            operation = "set"
            amount = int(amount_str)
        
        # Перевіряємо чи гравець існує
        cursor.execute("SELECT username, coins FROM players WHERE user_id = ?", (user_id,))
        player_data = cursor.fetchone()
        
        if not player_data:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username, current_coins = player_data
        admin_name = message.from_user.username or message.from_user.full_name
        
        # Виконуємо операцію
        if operation == "add":
            new_coins = current_coins + amount
            cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
            action_text = f"💰 Додано: +{amount} ✯"
            
        elif operation == "subtract":
            new_coins = max(0, current_coins - amount)  # Щоб не було від'ємних
            cursor.execute("UPDATE players SET coins = ? WHERE user_id = ?", (new_coins, user_id))
            action_text = f"💰 Віднято: -{amount} ✯"
            
        else:  # set - ВСТАНОВИТИ значення
            new_coins = max(0, amount)  # Щоб не було від'ємних
            cursor.execute("UPDATE players SET coins = ? WHERE user_id = ?", (new_coins, user_id))
            action_text = f"💰 Встановлено: {amount} ✯"
        
        conn.commit()
        
        # Формуємо результат
        result_text = (
            f"✅ <b>БАЛАНС ОНОВЛЕНО</b>\n\n"
            f"⟡━━━━━━━━━━━━━━━━━━━━━⟡\n"
            f"👤 <b>Гравець:</b> {username}\n"
            f"🆔 <b>ID:</b> {user_id}\n"
            f"📊 <b>Операція:</b> {action_text}\n\n"
            f"💎 <b>Старий баланс:</b> {current_coins} ✯\n"
            f"💰 <b>Новий баланс:</b> {new_coins} ✯\n\n"
            f"👮 <b>Адміністратор:</b> {admin_name}\n"
            f"⏰ <b>Час:</b> {datetime.now().strftime('%H:%M:%S')}\n"
            f"⟡━━━━━━━━━━━━━━━━━━━━━⟡"
        )
        
        await message.answer(result_text)
        
        # Додамо дебаг інформацію для перевірки
        debug_info = (
            f"🔧 <b>ДЕБАГ ІНФО:</b>\n"
            f"Введено: {amount_str}\n"
            f"Операція: {operation}\n"
            f"Сума: {amount}\n"
            f"Старий баланс: {current_coins}\n"
            f"Новий баланс: {new_coins}"
        )
        print(debug_info)  # Для перевірки в консолі
        
        # Сповіщаємо гравця про зміни
        try:
            operation_emoji = "📈" if operation == "add" else "📉" if operation == "subtract" else "⚡"
            await bot.send_message(
                user_id,
                f"{operation_emoji} <b>ВАШ БАЛАНС ОНОВЛЕНО</b>\n\n"
                f"💎 <b>Старий баланс:</b> {current_coins} ✯\n"
                f"💰 <b>Новий баланс:</b> {new_coins} ✯\n"
                f"📊 <b>Операція:</b> {action_text}\n\n"
                f"👮 <i>Адміністратор: {admin_name}</i>\n"
                f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        except:
            pass  # Якщо не вдалось сповістити гравця
            
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['setlevel'])
async def cmd_setlevel(message: types.Message):
    """Встановити/додати/відняти рівень гравцю"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer(
                "🎯 <b>КОМАНДА SETLEVEL</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/setlevel ID рівень</code> - встановити рівень\n"
                "<code>/setlevel ID +рівень</code> - додати рівні\n"
                "<code>/setlevel ID -рівень</code> - відняти рівні\n\n"
                "🎯 <b>Приклади:</b>\n"
                "<code>/setlevel 123456789 10</code> - встановити 10 рівень\n"
                "<code>/setlevel 123456789 +5</code> - додати 5 рівнів\n"
                "<code>/setlevel 123456789 -2</code> - відняти 2 рівні\n\n"
                "⚠️ <b>Увага:</b> Мінімальний рівень - 1!"
            )
            return
        
        user_id = int(parts[1])
        level_str = parts[2]
        
        # Визначаємо тип операції
        operation = "set"
        if level_str.startswith('+'):
            operation = "add"
            levels = int(level_str[1:])
        elif level_str.startswith('-'):
            operation = "subtract"
            levels = int(level_str[1:])
        else:
            operation = "set"
            levels = int(level_str)
        
        # Перевіряємо чи гравець існує
        cursor.execute("SELECT username, level FROM players WHERE user_id = ?", (user_id,))
        player_data = cursor.fetchone()
        
        if not player_data:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username, current_level = player_data
        admin_name = message.from_user.username or message.from_user.full_name
        
        # Виконуємо операцію
        if operation == "add":
            new_level = current_level + levels
            cursor.execute("UPDATE players SET level = level + ? WHERE user_id = ?", (levels, user_id))
            action_text = f"🎯 Додано: +{levels} рівнів"
            
        elif operation == "subtract":
            new_level = max(1, current_level - levels)  # Мінімум 1 рівень
            cursor.execute("UPDATE players SET level = ? WHERE user_id = ?", (new_level, user_id))
            action_text = f"🎯 Віднято: -{levels} рівнів"
            
        else:  # set
            new_level = max(1, levels)  # Мінімум 1 рівень
            cursor.execute("UPDATE players SET level = ? WHERE user_id = ?", (new_level, user_id))
            action_text = f"🎯 Встановлено: {levels} рівень"
        
        # Скидаємо XP для нового рівня
        cursor.execute("UPDATE players SET xp = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        
        # Формуємо результат
        result_text = (
            f"✅ <b>РІВЕНЬ ОНОВЛЕНО</b>\n\n"
            f"⟡━━━━━━━━━━━━━━━━━━━━━⟡\n"
            f"👤 <b>Гравець:</b> {username}\n"
            f"🆔 <b>ID:</b> {user_id}\n"
            f"📊 <b>Операція:</b> {action_text}\n\n"
            f"🎯 <b>Старий рівень:</b> {current_level}\n"
            f"⭐ <b>Новий рівень:</b> {new_level}\n"
            f"📈 <b>XP скинуто:</b> 0/{new_level * XP_PER_LEVEL}\n\n"
            f"👮 <b>Адміністратор:</b> Luna\n"
            f"⏰ <b>Час:</b> {datetime.now().strftime('%H:%M:%S')}\n"
            f"⟡━━━━━━━━━━━━━━━━━━━━━⟡"
        )
        
        await message.answer(result_text)
        
        # Сповіщаємо гравця про зміни
        try:
            await bot.send_message(
                user_id,
                f"⭐ <b>ВАШ РІВЕНЬ ОНОВЛЕНО</b>\n\n"
                f"🎯 <b>Старий рівень:</b> {current_level}\n"
                f"⭐ <b>Новий рівень:</b> {new_level}\n"
                f"📊 <b>Операція:</b> {action_text}\n"
                f"📈 <b>Прогрес:</b> 0/{new_level * XP_PER_LEVEL} XP\n\n"
                f"👮 <i>Адміністратор: Luna</i>\n"
                f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['adminstats'])
async def cmd_adminstats(message: types.Message):
    """Проста статистика"""
    if not is_admin(message.from_user.id):
        return
    
    cursor.execute("SELECT COUNT(*) FROM players WHERE last_active > datetime('now', '-1 day')")
    active_today = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM players")
    total_players = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(coins) FROM players")
    total_coins = cursor.fetchone()[0] or 0
    
    text = (
        "📊 <b>СТАТИСТИКА БОТА</b>\n\n"
        f"👥 Гравців: {total_players}\n"
        f"🎯 Активних за 24г: {active_today}\n" 
        f"💰 Монет в обігу: {total_coins:,} ✯\n"
        f"🕒 Час: {datetime.now().strftime('%H:%M')}"
    )
    
    await message.answer(text)

@dp.message_handler(commands=['users'])
async def cmd_users(message: types.Message):
    """Простий список гравців"""
    if not is_admin(message.from_user.id):
        return
    
    cursor.execute("SELECT user_id, username, coins, level FROM players ORDER BY coins DESC LIMIT 10")
    top_players = cursor.fetchall()
    
    text = "🏆 <b>ТОП-10 ГРАВЦІВ</b>\n\n"
    for i, (user_id, username, coins, level) in enumerate(top_players, 1):
        text += f"{i}. {username}\n"
        text += f"   ID: {user_id} | 💰 {coins:,} ✯ | 🎯 {level} рів.\n\n"
    
    await message.answer(text)

#=========== ADMIN COMANDS - АДМІН КОМАНДИ ==========
@dp.message_handler(commands=['msgall'])
async def cmd_msgall(message: types.Message):
    """Надіслати красиве сповіщення всім гравцям"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "🔔 <b>ФОРМАТ РОЗСИЛКИ</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/msgall ваше повідомлення</code>\n\n"
                "🎯 <b>Приклади:</b>\n"
                "<code>/msgall Важлива інформація для всіх гравців! 🚀</code>\n"
                "<code>/msgall Завтра оновлення гри з 14:00! 🎮</code>\n"
                "<code>/msgall Новий івент стартує через 2 дні! 🎉</code>\n\n"
                "⚠️ <b>Увага:</b> Повідомлення буде відправлено ВСІМ гравцям!"
            )
            return
        
        admin_message = parts[1]
        admin_name = message.from_user.username or message.from_user.full_name
        
        # Отримуємо всіх гравців
        cursor.execute("SELECT user_id, username FROM players")
        all_players = cursor.fetchall()
        
        if not all_players:
            await message.answer("❌ Немає гравців для розсилки!")
            return
        
        success_count = 0
        failed_count = 0
        
        # Красиве оформлення повідомлення
        announcement_text = (
            f"⟡━━━━━━━━━━━━━━━━⟡\n"
            f"   📢  <b>СПОВІЩЕННЯ АДМІНІСТРАЦІЇ</b>\n"
            f"⟡━━━━━━━━━━━━━━━━⟡\n\n"
            f"💫 <b>ПОВІДОМЛЕННЯ:</b>\n"
            f"✨ {admin_message}\n\n"
            f"👮 <b>АДМІНІСТРАТОР:</b> Luna\n"
            f"📅 <b>ДАТА:</b> {datetime.now().strftime('%d.%m.%Y')}\n"
            f"⏰ <b>ЧАС:</b> {datetime.now().strftime('%H:%M')}\n\n"
            f"⟡━━━━━━━━━━━━━━━━⟡\n"
            f"     🎮 <i>Дякуємо за гру!</i> 🎮\n"
            f"⟡━━━━━━━━━━━━━━━━⟡"
        )
        
        # Відправляємо повідомлення кожному гравцю
        for user_id, username in all_players:
            try:
                await bot.send_message(
                    user_id,
                    announcement_text,
                    parse_mode="HTML"
                )
                success_count += 1
                
                # Невелика затримка щоб не перевантажити Telegram
                await asyncio.sleep(0.1)
                
            except Exception as e:
                print(f"❌ Не вдалось відправити {user_id}: {e}")
                failed_count += 1
        
        # Результати для адміна
        results_text = (
            f"📨 <b>РОЗСИЛКА ЗАВЕРШЕНА</b>\n\n"
            f"⟡━━━━━━━━━━━━━━━━━━━━━⟡\n"
            f"📊 <b>СТАТИСТИКА:</b>\n"
            f"✅ Успішно: {success_count} гравців\n"
            f"❌ Не вдалось: {failed_count} гравців\n"
            f"👥 Всього: {len(all_players)} гравців\n\n"
            f"💬 <b>ПОВІДОМЛЕННЯ:</b>\n"
            f"📝 {admin_message}\n\n"
            f"⏰ <i>Час відправки: {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        
        await message.answer(results_text)
        
        # Додатково логуємо
        log.info(f"📢 Адмін {admin_name} зробив розсилку: {admin_message}")
        
    except Exception as e:
        await message.answer(f"❌ Помилка розсилки: {e}")

@dp.message_handler(commands=['msgi'])
async def cmd_msgi(message: types.Message):
    """Надіслати повідомлення гравцю від адміністрації"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        parts = message.text.split(maxsplit=2)  # Розділяємо на 3 частини
        if len(parts) < 3:
            await message.answer(
                "❌ <b>Неправильний формат!</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/msgi ID_гравця ваше повідомлення</code>\n\n"
                "📝 <b>Приклади:</b>\n"
                "<code>/msgi 123456789 Вітаємо з перемогою! 🎉</code>\n"
                "<code>/msgi 123456789 Нагадуємо про правила спільноти</code>\n\n"
                "💡 <b>ID гравця</b> можна дізнатись через /users"
            )
            return
        
        user_id = int(parts[1])
        admin_message = parts[2]
        admin_name = message.from_user.username or message.from_user.full_name
        
        # Перевіряємо чи гравець існує
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (user_id,))
        player_data = cursor.fetchone()
        
        if not player_data:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        player_name = player_data[0]
        
        # Відправляємо повідомлення гравцю
        try:
            await bot.send_message(
                user_id,
                f"📢 <b>ПОВІДОМЛЕННЯ ВІД АДМІНІСТРАЦІЇ</b>\n\n"
                f"💬 {admin_message}\n\n"
                f"👮 <i>Адміністратор: Luna</i>\n"
                f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"🎉 Гарного дня!"
            )
            
            await message.answer(
                f"✅ <b>Повідомлення відправлено!</b>\n\n"
                f"👤 Гравець: {player_name}\n"
                f"🆔 ID: {user_id}\n"
                f"💬 Повідомлення: {admin_message}\n\n"
                f"📨 Гравець отримав ваше повідомлення"
            )
            
        except Exception as e:
            await message.answer(f"❌ Не вдалося відправити повідомлення гравцю. Можливо, бот заблокований.")
            
    except ValueError:
        await message.answer("❌ Помилка! ID має бути числом.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['export'])
async def cmd_export(message: types.Message):
    """Експорт даних в CSV"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "📁 <b>ЕКСПОРТ ДАНИХ</b>\n\n"
                "⚡ <b>Команди:</b>\n"
                "<code>/export users</code> - список гравців\n"
                "<code>/export items</code> - предмети в інвентарях\n"
                "<code>/export transactions</code> - перекази\n"
                "<code>/export businesses</code> - бізнеси\n"
            )
            return
        
        export_type = parts[1].lower()
        
        if export_type == 'users':
            await export_users(message)
        elif export_type == 'items':
            await export_items(message)
        elif export_type == 'transactions':
            await export_transactions(message)
        elif export_type == 'businesses':
            await export_businesses(message)
        else:
            await message.answer("❌ Невідомий тип експорту")
            
    except Exception as e:
        await message.answer(f"❌ Помилка експорту: {e}")

async def export_users(message: types.Message):
    """Експорт гравців"""
    cursor.execute("""
        SELECT user_id, username, level, xp, coins, role, prefix, 
               total_taps, last_active 
        FROM players 
        ORDER BY coins DESC
    """)
    users = cursor.fetchall()
    
    # Створюємо CSV
    csv_content = "ID;Username;Level;XP;Coins;Role;Prefix;Taps;Last Active\n"
    
    for user in users:
        user_id, username, level, xp, coins, role, prefix, taps, last_active = user
        csv_content += f"{user_id};{username};{level};{xp};{coins};{role};{prefix};{taps};{last_active}\n"
    
    # Зберігаємо в файл
    filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(csv_content)
    
    # Відправляємо файл
    with open(filename, 'rb') as f:
        await message.answer_document(
            f,
            caption=f"📊 Експорт гравців ({len(users)} записів)"
        )
    
    # Видаляємо тимчасовий файл
    os.remove(filename)

async def export_items(message: types.Message):
    """Експорт предметів"""
    cursor.execute("""
        SELECT ui.user_id, p.username, ui.item_name, ui.item_price, ui.item_type, ui.obtained_date
        FROM user_inventory ui
        JOIN players p ON ui.user_id = p.user_id
        ORDER BY ui.obtained_date DESC
    """)
    items = cursor.fetchall()
    
    csv_content = "User ID;Username;Item Name;Price;Type;Obtained Date\n"
    
    for item in items:
        user_id, username, item_name, price, item_type, date = item
        csv_content += f"{user_id};{username};{item_name};{price};{item_type};{date}\n"
    
    filename = f"items_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(csv_content)
    
    with open(filename, 'rb') as f:
        await message.answer_document(
            f,
            caption=f"🎁 Експорт предметів ({len(items)} записів)"
        )
    
    os.remove(filename)

async def export_transactions(message: types.Message):
    """Експорт переказів"""
    cursor.execute("""
        SELECT mt.from_user_id, p1.username, mt.to_user_id, p2.username, 
               mt.amount, mt.transfer_date
        FROM money_transfers mt
        JOIN players p1 ON mt.from_user_id = p1.user_id
        JOIN players p2 ON mt.to_user_id = p2.user_id
        ORDER BY mt.transfer_date DESC
    """)
    transactions = cursor.fetchall()
    
    csv_content = "From User;From Username;To User;To Username;Amount;Date\n"
    
    for trans in transactions:
        from_id, from_name, to_id, to_name, amount, date = trans
        csv_content += f"{from_id};{from_name};{to_id};{to_name};{amount};{date}\n"
    
    filename = f"transactions_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(csv_content)
    
    with open(filename, 'rb') as f:
        await message.answer_document(
            f,
            caption=f"💸 Експорт переказів ({len(transactions)} записів)"
        )
    
    os.remove(filename)

async def export_businesses(message: types.Message):
    """Експорт бізнесів"""
    cursor.execute("""
        SELECT ub.user_id, p.username, ub.business_name, ub.business_type, 
               ub.level, ub.purchased_date
        FROM user_businesses ub
        JOIN players p ON ub.user_id = p.user_id
        ORDER BY ub.purchased_date DESC
    """)
    businesses = cursor.fetchall()
    
    csv_content = "User ID;Username;Business Name;Type;Level;Purchased Date\n"
    
    for biz in businesses:
        user_id, username, biz_name, biz_type, level, date = biz
        csv_content += f"{user_id};{username};{biz_name};{biz_type};{level};{date}\n"
    
    filename = f"businesses_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(csv_content)
    
    with open(filename, 'rb') as f:
        await message.answer_document(
            f,
            caption=f"🏢 Експорт бізнесів ({len(businesses)} записів)"
        )
    
    os.remove(filename)

# ========== СИСТЕМА МОДЕРАЦІЇ ==========

@dp.message_handler(commands=['warn'])
async def cmd_warn(message: types.Message):
    """Видати попередження гравцю"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("❌ Формат: /warn ID причина\nНаприклад: /warn 123456789 спам")
            return
        
        user_id = int(parts[1])
        reason = parts[2]
        
        # Перевіряємо чи гравець існує
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (user_id,))
        player = cursor.fetchone()
        
        if not player:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username = player[0]
        
        # Логуємо попередження (тимчасово в окрему таблицю)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                reason TEXT NOT NULL,
                admin_id INTEGER NOT NULL,
                admin_username TEXT NOT NULL,
                warning_date TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            INSERT INTO warnings (user_id, username, reason, admin_id, admin_username, warning_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, reason, message.from_user.id, 
              message.from_user.username or message.from_user.full_name,
              datetime.now().isoformat()))
        
        # Рахуємо кількість попереджень
        cursor.execute("SELECT COUNT(*) FROM warnings WHERE user_id = ?", (user_id,))
        warn_count = cursor.fetchone()[0]
        
        conn.commit()
        
        # Відправляємо сповіщення гравцю
        try:
            await bot.send_message(
                user_id,
                f"⚠️ <b>ВИ ОТРИМАЛИ ПОПЕРЕДЖЕННЯ</b>\n\n"
                f"📝 Причина: {reason}\n"
                f"🔢 Попереджень: {warn_count}/3\n"
                f"❗ При отриманні 3 попереджень - бан!"
            )
        except:
            pass  # Не вдалось відправити повідомлення
        
        await message.answer(
            f"⚠️ <b>ПОПЕРЕДЖЕННЯ ВИДАНО</b>\n\n"
            f"👤 Гравець: {username}\n"
            f"🆔 ID: {user_id}\n"
            f"📝 Причина: {reason}\n"
            f"🔢 Попереджень: {warn_count}/3\n\n"
            f"{'🚨 УВАГА: Наступне попередження - бан!' if warn_count >= 2 else ''}"
        )
        
    except ValueError:
        await message.answer("❌ Помилка! ID має бути числом")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['mute'])
async def cmd_mute(message: types.Message):
    """Заблокувати гравця на час"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            await message.answer("❌ Формат: /mute ID хвилини\nНаприклад: /mute 123456789 60")
            return
        
        user_id = int(parts[1])
        minutes = int(parts[2])
        
        if minutes <= 0 or minutes > 10080:  # Максимум 7 днів
            await message.answer("❌ Хвилини мають бути від 1 до 10080 (7 днів)")
            return
        
        # Перевіряємо чи гравець існує
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (user_id,))
        player = cursor.fetchone()
        
        if not player:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username = player[0]
        
        # Тимчасово зберігаємо в окремій таблиці
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                end_time TEXT NOT NULL,
                admin_id INTEGER NOT NULL,
                admin_username TEXT NOT NULL,
                mute_date TEXT NOT NULL
            )
        """)
        
        end_time = datetime.now() + timedelta(minutes=minutes)
        
        cursor.execute("""
            INSERT INTO mutes (user_id, username, end_time, admin_id, admin_username, mute_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, end_time.isoformat(), message.from_user.id,
              message.from_user.username or message.from_user.full_name,
              datetime.now().isoformat()))
        
        conn.commit()
        
        # Сповіщаємо гравця
        try:
            await bot.send_message(
                user_id,
                f"🔇 <b>ВИ ЗАМУЧЕНІ</b>\n\n"
                f"⏰ Тривалість: {minutes} хвилин\n"
                f"🕒 Розблокування: {end_time.strftime('%H:%M')}\n"
                f"👮 Адміністратор: {message.from_user.username or message.from_user.full_name}\n\n"
                f"📵 До завершення муту доступ до ігор обмежено"
            )
        except:
            pass
        
        await message.answer(
            f"🔇 <b>ГРАВЕЦЬ ЗАМУЧЕНИЙ</b>\n\n"
            f"👤 {username}\n"
            f"🆔 {user_id}\n"
            f"⏰ На {minutes} хвилин\n"
            f"🕒 До {end_time.strftime('%H:%M')}"
        )
        
    except ValueError:
        await message.answer("❌ Помилка! ID та хвилини мають бути числами")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['warnings'])
async def cmd_warnings(message: types.Message):
    """Перегляд попереджень гравця"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Формат: /warnings ID\nНаприклад: /warnings 123456789")
            return
        
        user_id = int(parts[1])
        
        # Отримуємо попередження
        cursor.execute("""
            SELECT reason, admin_username, warning_date 
            FROM warnings 
            WHERE user_id = ? 
            ORDER BY warning_date DESC
        """, (user_id,))
        
        warnings = cursor.fetchall()
        
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (user_id,))
        player = cursor.fetchone()
        
        if not player:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username = player[0]
        
        if not warnings:
            await message.answer(f"✅ {username} не має попереджень")
            return
        
        text = f"⚠️ <b>ПОПЕРЕДЖЕННЯ {username}</b>\n\n"
        
        for i, (reason, admin, date) in enumerate(warnings, 1):
            warn_date = datetime.fromisoformat(date).strftime('%d.%m.%Y %H:%M')
            text += f"{i}. {reason}\n"
            text += f"   👮 {admin} | {warn_date}\n\n"
        
        text += f"📊 Всього попереджень: {len(warnings)}/3"
        
        await message.answer(text)
        
    except ValueError:
        await message.answer("❌ Помилка! ID має бути числом")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")
@dp.message_handler(commands=['setcoins'])
async def cmd_setcoins(message: types.Message):
    """Додати/відняти монети гравцю"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("❌ Формат: /setcoins ID сумма\nНаприклад: /setcoins 123456789 1000")
            return
        
        user_id = int(parts[1])
        amount = int(parts[2])
        
        # Перевіряємо чи гравець існує
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (user_id,))
        player = cursor.fetchone()
        
        if not player:
            await message.answer("❌ Гравець не знайдений!")
            return
        
        username = player[0]
        
        # Оновлюємо баланс
        cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        
        # Отримуємо новий баланс
        cursor.execute("SELECT coins FROM players WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        
        action = "додано" if amount > 0 else "знято"
        await message.answer(
            f"✅ <b>Баланс оновлено!</b>\n\n"
            f"👤 Гравець: {username}\n"
            f"🆔 ID: {user_id}\n"
            f"💰 {action}: {abs(amount)} ✯\n"
            f"💎 Новий баланс: {new_balance} ✯"
        )
        
    except ValueError:
        await message.answer("❌ Помилка! ID та сумма мають бути числами")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['rewardactive'])
async def cmd_rewardactive(message: types.Message):
    """Нагородити всіх активних гравців"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Формат: /rewardactive сумма\nНаприклад: /rewardactive 500")
            return
        
        amount = int(parts[1])
        
        if amount <= 0:
            await message.answer("❌ Сума має бути більше 0!")
            return
        
        # Рахуємо активних гравців (останні 24 години)
        cursor.execute("SELECT COUNT(*) FROM players WHERE last_active > datetime('now', '-1 day')")
        active_players = cursor.fetchone()[0]
        
        if active_players == 0:
            await message.answer("❌ Немає активних гравців за останні 24 години!")
            return
        
        # Нагороджуємо активних
        cursor.execute("UPDATE players SET coins = coins + ? WHERE last_active > datetime('now', '-1 day')", (amount,))
        conn.commit()
        
        total_reward = active_players * amount
        
        await message.answer(
            f"🎉 <b>Активних гравців нагороджено!</b>\n\n"
            f"👥 Гравців: {active_players}\n"
            f"💰 Нагорода: {amount} ✯ кожному\n"
            f"💸 Всього видано: {total_reward} ✯\n\n"
            f"⚡ Гравці отримають сповіщення!"
        )
        
        # TODO: Тут потім додамо сповіщення гравцям
        
    except ValueError:
        await message.answer("❌ Помилка! Сума має бути числом")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['rewardtop5'])
async def cmd_rewardtop5(message: types.Message):
    """Нагородити топ-5 гравців за балансом"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Формат: /rewardtop5 сумма\nНаприклад: /rewardtop5 1000")
            return
        
        amount = int(parts[1])
        
        if amount <= 0:
            await message.answer("❌ Сума має бути більше 0!")
            return
        
        # Отримуємо топ-5 гравців
        cursor.execute("SELECT user_id, username, coins FROM players ORDER BY coins DESC LIMIT 5")
        top_players = cursor.fetchall()
        
        if not top_players:
            await message.answer("❌ Немає гравців для нагородження!")
            return
        
        # Нагороджуємо топ-5
        rewarded_players = []
        for user_id, username, current_coins in top_players:
            cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
            rewarded_players.append(f"• {username} - {current_coins + amount} ✯")
        
        conn.commit()
        
        players_list = "\n".join(rewarded_players)
        
        await message.answer(
            f"🏆 <b>Топ-5 гравців нагороджено!</b>\n\n"
            f"💰 Нагорода: {amount} ✯ кожному\n\n"
            f"🎯 Нагороджені гравці:\n{players_list}"
        )
        
    except ValueError:
        await message.answer("❌ Помилка! Сума має бути числом")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

# СИСТЕМА ІВЕНТІВ

# Глобальна змінна для поточного івенту
current_event = None

@dp.message_handler(commands=['event'])
async def cmd_event(message: types.Message):
    """Керування івентами"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        
        if len(parts) < 2:
            await message.answer(
                "🎯 <b>СИСТЕМА ІВЕНТІВ</b>\n\n"
                "⚡ <b>Команди:</b>\n"
                "<code>/event start 2xcoins 24</code> - запустити івент\n"
                "<code>/event start 2xxp 48</code> - x2 досвіду на 48 год.\n" 
                "<code>/event status</code> - статус івенту\n"
                "<code>/event stop</code> - зупинити івент\n\n"
                "🎁 <b>Доступні івенти:</b>\n"
                "• <code>2xcoins</code> - подвійні монети\n"
                "• <code>2xxp</code> - подвійний досвід\n"
                "• <code>free_spins</code> - безкоштовні спіни\n"
            )
            return
        
        subcommand = parts[1].lower()
        
        if subcommand == 'start' and len(parts) >= 4:
            event_type = parts[2].lower()
            hours = int(parts[3])
            
            global current_event
            current_event = {
                'type': event_type,
                'start_time': datetime.now(),
                'end_time': datetime.now() + timedelta(hours=hours),
                'hours': hours
            }
            
            event_names = {
                '2xcoins': '💰 Подвійні монети',
                '2xxp': '🎯 Подвійний досвід', 
                'free_spins': '🎰 Безкоштовні спіни'
            }
            
            event_name = event_names.get(event_type, event_type)
            
            await message.answer(
                f"🎉 <b>ІВЕНТ ЗАПУЩЕНО!</b>\n\n"
                f"🎯 Тип: {event_name}\n"
                f"⏰ Тривалість: {hours} годин\n"
                f"🕒 Завершиться: {current_event['end_time'].strftime('%d.%m.%Y о %H:%M')}\n\n"
                f"📢 Оголошення відправлено всім гравцям!"
            )
            
            # TODO: Тут потім додамо розсилку гравцям
            
        elif subcommand == 'status':
            if current_event:
                time_left = current_event['end_time'] - datetime.now()
                hours_left = max(0, int(time_left.total_seconds() // 3600))
                minutes_left = max(0, int((time_left.total_seconds() % 3600) // 60))
                
                event_names = {
                    '2xcoins': '💰 Подвійні монети',
                    '2xxp': '🎯 Подвійний досвід',
                    'free_spins': '🎰 Безкоштовні спіни'
                }
                
                event_name = event_names.get(current_event['type'], current_event['type'])
                
                await message.answer(
                    f"📊 <b>СТАТУС ІВЕНТУ</b>\n\n"
                    f"🎯 Тип: {event_name}\n"
                    f"⏰ Залишилось: {hours_left}г {minutes_left}хв\n"
                    f"🕒 Завершиться: {current_event['end_time'].strftime('%d.%m.%Y о %H:%M')}\n"
                    f"🚀 Запущено: {current_event['start_time'].strftime('%d.%m.%Y %H:%M')}"
                )
            else:
                await message.answer("❌ Наразі активних івентів немає")
                
        elif subcommand == 'stop':
            if current_event:
                current_event = None
                await message.answer("✅ Івент зупинено!")
            else:
                await message.answer("❌ Наразі активних івентів немає")
                
        else:
            await message.answer("❌ Невідома команда. Використовуй /event для допомоги")
            
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

# Функція для перевірки активного івенту (для використання в інших частинах коду)
def get_active_event():
    """Отримати поточний активний івент"""
    global current_event
    if current_event and datetime.now() < current_event['end_time']:
        return current_event
    return None

def is_event_active(event_type):
    """Перевірити чи активний конкретний івент"""
    event = get_active_event()
    return event and event['type'] == event_type



# ADMIN STAST - АДМІН СТАТИСТИКА
@dp.message_handler(commands=['adminstats'])
async def cmd_adminstats(message: types.Message):
    """Швидка статистика бота"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        # Активні за 24 години
        cursor.execute("SELECT COUNT(*) FROM players WHERE last_active > datetime('now', '-1 day')")
        active_today = cursor.fetchone()[0]
        
        # Всього гравців
        cursor.execute("SELECT COUNT(*) FROM players")
        total_players = cursor.fetchone()[0]
        
        # Загальний баланс
        cursor.execute("SELECT SUM(coins) FROM players")
        total_coins = cursor.fetchone()[0] or 0
        
        # Топ-1 гравець
        cursor.execute("SELECT username, coins FROM players ORDER BY coins DESC LIMIT 1")
        top_player = cursor.fetchone()
        top_player_info = f"{top_player[0]} - {top_player[1]:,} ✯" if top_player else "Немає"
        
        # Предметів в інвентарях
        cursor.execute("SELECT COUNT(*) FROM user_inventory")
        total_items = cursor.fetchone()[0]
        
        text = (
            "📊 <b>СТАТИСТИКА БОТА</b>\n\n"
            f"👥 Всього гравців: {total_players}\n"
            f"🎯 Активних за 24г: {active_today}\n"
            f"💰 Монет в обігу: {total_coins:,} ✯\n"
            f"🏆 Топ-1 гравець: {top_player_info}\n"
            f"🎁 Предметів в інвентарях: {total_items}\n\n"
            f"🕒 Оновлено: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await message.answer(text)
        
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['users'])
async def cmd_users(message: types.Message):
    """Список гравців"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        cursor.execute("SELECT user_id, username, coins, level, last_active FROM players ORDER BY coins DESC LIMIT 15")
        players = cursor.fetchall()
        
        text = "👥 <b>ТОП-15 ГРАВЦІВ</b>\n\n"
        
        for i, (user_id, username, coins, level, last_active) in enumerate(players, 1):
            # Визначаємо активність
            last_active_time = datetime.fromisoformat(last_active)
            time_diff = datetime.now() - last_active_time
            hours_ago = int(time_diff.total_seconds() // 3600)
            
            status = "🟢" if hours_ago < 1 else "🟡" if hours_ago < 24 else "🔴"
            
            text += f"{status} {i}. {username}\n"
            text += f"   🆔 {user_id} | 💰 {coins:,} ✯ | 🎯 {level} рів.\n"
            text += f"   ⏰ {hours_ago} год. тому\n\n"
        
        await message.answer(text)
        
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")
# ========== СИСТЕМА ДРУЗІВ (оновлена) ==========
@dp.callback_query_handler(lambda c: c.data == 'friends_list')
async def cb_friends_list(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    friends = get_user_friends(user_id)
    
    text = "👥 <b>Ваші друзі</b>\n\n"
    
    if friends:
        for i, friend in enumerate(friends, 1):
            friend_prefix = get_user_prefix(friend['user_id'])
            display_name = f"{friend_prefix} {friend['username']}" if friend_prefix else friend['username']
            text += f"{i}. {display_name}\n"
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
        "• Комісія 5% (крім Банкіра)\n"
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
            await message.answer(
                "🤝 <b>ДОДАВАННЯ ДРУГА</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/addfriend ID_гравця</code>\n\n"
                "📝 <b>Приклади:</b>\n"
                "<code>/addfriend 123456789</code>\n\n"
                "💡 <b>Що станеться:</b>\n"
                "• Гравець отримає пряме повідомлення\n" 
                "• З кнопками 'Прийняти' та 'Відхилити'\n"
                "• Після підтвердження ви станете друзями"
            )
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
        from_username = message.from_user.username or message.from_user.full_name
        
        # Перевіряємо чи вже друзі
        cursor.execute("SELECT id FROM friends WHERE user_id = ? AND friend_id = ?", (user_id, friend_id))
        if cursor.fetchone():
            await message.answer("❌ Цей гравець вже у вашому списку друзів!")
            return
        
        # Перевіряємо чи вже надсилали запит
        cursor.execute("SELECT id FROM friend_requests WHERE from_user_id = ? AND to_user_id = ? AND status = 'pending'", 
                      (user_id, friend_id))
        if cursor.fetchone():
            await message.answer("❌ Ви вже надсилали запит цьому гравцю! Очікуйте підтвердження.")
            return
        
        # Створюємо запит
        cursor.execute("""
            INSERT INTO friend_requests (from_user_id, from_username, to_user_id, created_date)
            VALUES (?, ?, ?, ?)
        """, (user_id, from_username, friend_id, datetime.now().isoformat()))
        
        conn.commit()
        
        # Сповіщуємо того хто надіслав запит
        await message.answer(
            f"📨 <b>Запит у друзі надіслано!</b>\n\n"
            f"👤 Гравець: {friend_username}\n"
            f"🆔 ID: {friend_id}\n\n"
            f"💡 Очікуйте підтвердження! Гравець отримав сповіщення."
        )
        
        # Надсилаємо ПРЯМЕ СПОВІЩЕННЯ гравцю з кнопками
        try:
            request_id = cursor.lastrowid  # Отримуємо ID щойно створеного запиту
            
            await bot.send_message(
                friend_id,
                f"📨 <b>НОВИЙ ЗАПИТ У ДРУЗІ</b>\n\n"
                f"👤 <b>{from_username}</b> хоче додати вас у друзі!\n\n"
                f"🆔 ID: {user_id}\n"
                f"⏰ Час: {datetime.now().strftime('%H:%M')}\n\n"
                f"🤝 Ви хочете прийняти цей запит?",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("✅ Прийняти", callback_data=f"friend_accept_{request_id}"),
                    InlineKeyboardButton("❌ Відхилити", callback_data=f"friend_reject_{request_id}")
                )
            )
        except Exception as e:
            await message.answer(f"❌ Не вдалося відправити запит. Можливо, гравець заблокував бота.")
            # Видаляємо запит якщо не вдалось відправити
            cursor.execute("DELETE FROM friend_requests WHERE id = ?", (request_id,))
            conn.commit()
            
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
            commission = 0 if get_user_role(user_id) == "БАНКІР" else ceil(amount * 0.05)
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

@dp.message_handler(commands=['business'])
async def cmd_business(message: types.Message):
    """Команда для відкриття бізнес-меню"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    license_info = get_user_business_license(user_id)
    user_businesses = get_user_businesses(user_id)
    total_income = get_total_business_income(user_id)
    
    text = (
        f"🏢 <b>Бізнес-Система</b>\n\n"
        f"💼 Ваші бізнеси: {len(user_businesses)}/{license_info['max_businesses']}\n"
        f"📄 Ліцензія: {license_info['name']}\n"
        f"💰 Дохід: {total_income} ✯/6 год\n"
        f"💎 Баланс: {get_user_coins(user_id)} ✯\n\n"
        f"🚀 <b>Оберіть дію:</b>"
    )
    
    await message.answer(text, reply_markup=build_business_menu(user_id))

@dp.message_handler(commands=['takecredit'])
async def cmd_takecredit(message: types.Message):
    """Команда для взяття кредиту"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer(
                "💰 <b>ВЗЯТТЯ КРЕДИТУ</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/takecredit ID_кредиту СУМА</code>\n\n"
                "📝 <b>Приклади:</b>\n"
                "<code>/takecredit 1 1000</code> - міні-кредит 1000 ✯\n"
                "<code>/takecredit 2 5000</code> - стандартний 5000 ✯\n\n"
                "🏦 <b>Доступні кредити:</b>\n"
                "1. 🟢 Міні-кредит (5+ рівень) - до 5,000 ✯\n"
                "2. 🔵 Стандартний (10+) - до 20,000 ✯\n"
                "3. 🟣 Бізнес-кредит (15+) - до 50,000 ✯\n"
                "4. 🟠 Інвест-кредит (20+) - до 100,000 ✯"
            )
            return
        
        credit_type_id = int(parts[1])
        amount = int(parts[2])
        
        if take_credit(user_id, credit_type_id, amount):
            credit_type = next((ct for ct in CreditSystem.CREDIT_TYPES if ct["id"] == credit_type_id), None)
            total_interest = calculate_credit_interest(amount, credit_type["interest_rate"], credit_type["term_hours"])
            
            await message.answer(
                f"🎉 <b>Кредит успішно видано!</b>\n\n"
                f"🏦 Тип: {credit_type['name']}\n"
                f"💰 Сума: {amount:,} ✯\n"
                f"📈 Відсотки: {total_interest:,} ✯\n"
                f"💸 Загалом до сплати: {amount + total_interest:,} ✯\n"
                f"⏰ Термін: {credit_type['term_hours']} годин\n\n"
                f"💎 Новий баланс: {get_user_coins(user_id):,} ✯\n\n"
                f"💡 Кредит автоматично погашатиметься з вашого доходу!"
            )
        else:
            await message.answer("❌ Не вдалося взяти кредит! Перевірте умови.")
            
    except ValueError:
        await message.answer("❌ Помилка! Перевірте правильність введених даних.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['bank'])
async def cmd_bank(message: types.Message):
    """Команда для відкриття банку"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    active_credits = get_user_active_credits(user_id)
    total_debt = sum(credit['remaining'] for credit in active_credits)
    
    text = (
        f"🏦 <b>Банк - Кредитна система</b>\n\n"
        f"💼 Активних кредитів: {len(active_credits)}\n"
        f"💸 Загальний борг: {total_debt:,} ✯\n"
        f"💎 Ваш баланс: {get_user_coins(user_id):,} ✯\n"
        f"📈 Ваш дохід: {get_total_passive_income(user_id)} ✯/6 год\n\n"
        f"🚀 <b>Оберіть дію:</b>"
    )
    
    await message.answer(text, reply_markup=build_bank_menu(user_id))

@dp.message_handler(commands=['friends'])
async def cmd_friends(message: types.Message):
    """Команда для перегляду друзів та запитів"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    friends = get_user_friends(user_id)
    pending_requests = get_pending_friend_requests(user_id)
    
    text = (
        f"🤝 <b>Система друзів</b>\n\n"
        f"👥 Друзів: {len(friends)}\n"
        f"📨 Запитів: {len(pending_requests)}\n\n"
    )
    
    if pending_requests:
        text += f"💡 У вас є {len(pending_requests)} нових запитів у друзі!\n"
        text += f"🎯 Використайте меню нижче щоб переглянути їх."
    
    await message.answer(text, reply_markup=build_friends_menu(user_id))

@dp.message_handler(commands=['removefriend'])
async def cmd_removefriend(message: types.Message):
    """Команда для видалення друга"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "🗑️ <b>ВИДАЛЕННЯ ДРУГА</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/removefriend ID_друга</code>\n\n"
                "📝 <b>Приклади:</b>\n"
                "<code>/removefriend 123456789</code>\n\n"
                "💡 <b>Альтернатива:</b> Використовуйте меню друзів для зручного вибору."
            )
            return
        
        friend_id = int(parts[1])
        
        # Перевіряємо чи це друг
        friend_info = get_friend_info(user_id, friend_id)
        if not friend_info:
            await message.answer("❌ Цей гравець не у вашому списку друзів!")
            return
        
        # Видаляємо друга
        if remove_friend(user_id, friend_id):
            await message.answer(
                f"✅ <b>Друга видалено!</b>\n\n"
                f"👤 {friend_info['username']} був видалений з вашого списку друзів.\n\n"
                f"💔 Ви більше не будете друзями в системі."
            )
            
            # Сповіщаємо друга
            try:
                await bot.send_message(
                    friend_id,
                    f"💔 <b>ВИ ВИДАЛЕНІ З ДРУЗІВ</b>\n\n"
                    f"👤 {message.from_user.username or message.from_user.full_name} видалив вас зі списку друзів."
                )
            except:
                pass
        else:
            await message.answer("❌ Не вдалося видалити друга!")
            
    except ValueError:
        await message.answer("❌ Помилка! ID має бути числом.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

# ========== АУКЦІОН ДЛЯ ВСІХ ==========

def cleanup_old_auction_items():
    """Очистити старі предмети з аукціону (старіші 24 годин)"""
    yesterday = (datetime.now() - timedelta(hours=24)).isoformat()
    cursor.execute("DELETE FROM auction_items WHERE listed_date < ?", (yesterday,))
    conn.commit()

def add_to_auction(user_id: int, item_name: str, item_type: str, original_price: int) -> bool:
    """Додати предмет на аукціон"""
    auction_price = int(original_price * 0.9)  # Знижка 10%
    
    # Спочатку очистимо старі предмети
    cleanup_old_auction_items()
    
    cursor.execute(
        "INSERT INTO auction_items (user_id, item_name, item_type, original_price, auction_price, listed_date) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, item_name, item_type, original_price, auction_price, datetime.now().isoformat())
    )
    conn.commit()
    return True

@dp.callback_query_handler(lambda c: c.data == 'auction_view')
async def cb_auction_view(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    # Очищаємо старі предмети
    cleanup_old_auction_items()
    
    cursor.execute("""
        SELECT ai.*, p.username 
        FROM auction_items ai 
        JOIN players p ON ai.user_id = p.user_id 
        ORDER BY ai.listed_date DESC
    """)
    auction_items = cursor.fetchall()
    
    text = "⚖️ <b>Аукціон</b>\n\n"
    
    if not auction_items:
        text += "❌ На аукціоні поки немає предметів!\n\n"
        text += "💡 Ви можете виставити свої предмети з інвентаря командою <code>/sellitem ID_предмета</code>"
    else:
        text += f"🏷️ <b>Доступні предмети ({len(auction_items)}):</b>\n\n"
        
        for i, item in enumerate(auction_items, 1):
            item_id, seller_id, item_name, item_type, original_price, auction_price, listed_date, seller_name = item
            
            # Комісія 4%
            commission = int(auction_price * 0.04)
            seller_gets = auction_price - commission
            
            # Час розміщення
            list_time = datetime.fromisoformat(listed_date)
            time_ago = datetime.now() - list_time
            hours_ago = int(time_ago.total_seconds() // 3600)
            
            text += f"{i}. 🎁 {item_name}\n"
            text += f"   💰 Ціна: {auction_price} ✯ (знижка 10%)\n"
            text += f"   💸 Продавець отримає: {seller_gets} ✯\n"
            text += f"   👤 Продавець: {seller_name}\n"
            text += f"   ⏰ Розміщено: {hours_ago} год. тому\n"
            text += f"   🎯 Команда: <code>/buy {item_id}</code>\n\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📦 Мій інвентар", callback_data="inventory_view"))
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="auction_view"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.message_handler(commands=['auction'])
async def cmd_auction(message: types.Message):
    """Команда для перегляду аукціону"""
    user_id = message.from_user.id
    
    # Очищаємо старі предмети
    cleanup_old_auction_items()
    
    cursor.execute("""
        SELECT ai.*, p.username 
        FROM auction_items ai 
        JOIN players p ON ai.user_id = p.user_id 
        ORDER BY ai.listed_date DESC
    """)
    auction_items = cursor.fetchall()
    
    text = "⚖️ <b>Аукціон</b>\n\n"
    
    if not auction_items:
        text += "❌ На аукціоні поки немає предметів!\n\n"
        text += "💡 Ви можете виставити свої предмети з інвентаря командою <code>/sellitem ID_предмета</code>"
    else:
        text += f"🏷️ <b>Доступні предмети ({len(auction_items)}):</b>\n\n"
        
        for i, item in enumerate(auction_items, 1):
            item_id, seller_id, item_name, item_type, original_price, auction_price, listed_date, seller_name = item
            
            # Комісія 4%
            commission = int(auction_price * 0.04)
            seller_gets = auction_price - commission
            
            # Час розміщення
            list_time = datetime.fromisoformat(listed_date)
            time_ago = datetime.now() - list_time
            hours_ago = int(time_ago.total_seconds() // 3600)
            
            text += f"{i}. 🎁 {item_name}\n"
            text += f"   💰 Ціна: {auction_price} ✯ (знижка 10%)\n"
            text += f"   💸 Продавець отримає: {seller_gets} ✯\n"
            text += f"   👤 Продавець: {seller_name}\n"
            text += f"   ⏰ Розміщено: {hours_ago} год. тому\n"
            text += f"   🎯 Команда: <code>/buy {item_id}</code>\n\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📦 Мій інвентар", callback_data="inventory_view"))
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="auction_view"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await message.answer(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'auction_view')
async def cb_auction_view(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    # Очищаємо старі предмети
    cleanup_old_auction_items()
    
    cursor.execute("""
        SELECT ai.*, p.username 
        FROM auction_items ai 
        JOIN players p ON ai.user_id = p.user_id 
        ORDER BY ai.listed_date DESC
    """)
    auction_items = cursor.fetchall()
    
    text = "⚖️ <b>Аукціон</b>\n\n"
    
    if not auction_items:
        text += "❌ На аукціоні поки немає предметів!\n\n"
        text += "💡 Ви можете виставити свої предмети з інвентаря командою <code>/sellitem ID_предмета</code>"
    else:
        text += f"🏷️ <b>Доступні предмети ({len(auction_items)}):</b>\n\n"
        
        for i, item in enumerate(auction_items, 1):
            item_id, seller_id, item_name, item_type, original_price, auction_price, listed_date, seller_name = item
            
            # Комісія 4%
            commission = int(auction_price * 0.04)
            seller_gets = auction_price - commission
            
            # Час розміщення
            list_time = datetime.fromisoformat(listed_date)
            time_ago = datetime.now() - list_time
            hours_ago = int(time_ago.total_seconds() // 3600)
            
            text += f"{i}. 🎁 {item_name}\n"
            text += f"   💰 Ціна: {auction_price} ✯ (знижка 10%)\n"
            text += f"   💸 Продавець отримає: {seller_gets} ✯\n"
            text += f"   👤 Продавець: {seller_name}\n"
            text += f"   ⏰ Розміщено: {hours_ago} год. тому\n"
            text += f"   🎯 Команда: <code>/buy {item_id}</code>\n\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📦 Мій інвентар", callback_data="inventory_view"))
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="auction_view"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="inventory_view"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.message_handler(commands=['buy'])
async def cmd_buy(message: types.Message):
    """Команда для купівлі предмета з аукціону"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "❌ <b>Неправильний формат!</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/buy ID_предмета</code>\n\n"
                "📝 <b>Приклад:</b>\n"
                "<code>/buy 1</code> - купити предмет з ID 1\n\n"
                "💡 <b>ID предмета</b> можна побачити в аукціоні"
            )
            return
        
        item_id = int(parts[1])
        
        # Знаходимо предмет на аукціоні
        cursor.execute("SELECT * FROM auction_items WHERE id = ?", (item_id,))
        item = cursor.fetchone()
        
        if not item:
            await message.answer("❌ Предмет не знайдено на аукціоні!")
            return
        
        auction_id, seller_id, item_name, item_type, original_price, auction_price, listed_date = item
        
        # Перевіряємо чи не купуємо у себе
        if seller_id == user_id:
            await message.answer("❌ Не можна купити свій же предмет!")
            return
        
        buyer_coins = get_user_coins(user_id)
        
        if buyer_coins < auction_price:
            await message.answer(f"❌ Недостатньо монет! Потрібно {auction_price} ✯, у вас {buyer_coins} ✯")
            return
        
        # Комісія 4%
        commission = int(auction_price * 0.04)
        seller_gets = auction_price - commission
        
        # Виконуємо угоду
        cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (auction_price, user_id))
        cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (seller_gets, seller_id))
        
        # Додаємо комісію до банкіра
        cursor.execute("SELECT user_id FROM players WHERE role = 'БАНКІР'")
        banker = cursor.fetchone()
        if banker:
            banker_id = banker[0]
            cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (commission, banker_id))
            cursor.execute(
                "INSERT INTO bank_income (user_id, total_commission) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET total_commission = total_commission + ?",
                (banker_id, commission, commission)
            )
        
        # Додаємо предмет покупцю
        add_to_inventory(user_id, item_name, original_price, item_type)
        
        # Видаляємо з аукціону
        cursor.execute("DELETE FROM auction_items WHERE id = ?", (auction_id,))
        
        # Знаходимо імена для повідомлення
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (seller_id,))
        seller_name = cursor.fetchone()[0]
        
        conn.commit()
        
        # Повідомляємо покупця
        await message.answer(
            f"✅ <b>Покупка успішна!</b>\n\n"
            f"🎁 Предмет: {item_name}\n"
            f"💰 Ціна: {auction_price} ✯\n"
            f"👤 Продавець: {seller_name}\n"
            f"💎 Ваш новий баланс: {get_user_coins(user_id)} ✯\n\n"
            f"🎉 Предмет додано до вашого інвентаря!"
        )
        
        # Повідомляємо продавця
        try:
            await bot.send_message(
                seller_id,
                f"💰 <b>Ваш предмет продано!</b>\n\n"
                f"🎁 Предмет: {item_name}\n"
                f"💵 Оригінальна ціна: {original_price} ✯\n"
                f"🛒 Продано за: {auction_price} ✯\n"
                f"💸 Ви отримали: {seller_gets} ✯\n"
                f"👤 Покупець: {message.from_user.username or message.from_user.full_name}\n"
                f"💎 Ваш новий баланс: {get_user_coins(seller_id)} ✯"
            )
        except:
            pass  # Якщо не вдалось відправити повідомлення продавцю
            
    except ValueError:
        await message.answer("❌ Помилка! ID має бути числом.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@dp.message_handler(commands=['sellitem'])
async def cmd_sellitem(message: types.Message):
    """Команда для продажу предмета на аукціон"""
    user_id = message.from_user.id
    ensure_player(user_id, message.from_user.username or message.from_user.full_name)
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "❌ <b>Неправильний формат!</b>\n\n"
                "📝 <b>Використання:</b>\n"
                "<code>/sellitem ID_предмета</code>\n\n"
                "📝 <b>Приклад:</b>\n"
                "<code>/sellitem 22</code> - продати алмаз\n\n"
                "💡 <b>ID предмета</b> можна побачити в інвентарі"
            )
            return
        
        item_id = int(parts[1])
        
        # Знаходимо предмет в інвентарі
        items = get_user_inventory(user_id)
        item_to_sell = None
        
        for item in items:
            for prize in ItemRoulettePrizes.PRIZES:
                if prize["id"] == item_id and prize["name"] == item["name"]:
                    item_to_sell = (item["name"], prize["price"], prize["type"])
                    break
            if item_to_sell:
                break
        
        if not item_to_sell:
            await message.answer("❌ Предмет не знайдено в вашому інвентарі!")
            return
        
        item_name, original_price, item_type = item_to_sell
        auction_price = int(original_price * 0.9)  # 90% від оригінальної ціни
        
        # Додаємо на аукціон
        if add_to_auction(user_id, item_name, item_type, original_price):
            # Видаляємо з інвентаря
            remove_from_inventory(user_id, item_name)
            
            await message.answer(
                f"✅ <b>Предмет виставлено на аукціон!</b>\n\n"
                f"🎁 Предмет: {item_name}\n"
                f"💰 Оригінальна ціна: {original_price} ✯\n"
                f"🛒 Ціна на аукціоні: {auction_price} ✯\n"
                f"💸 Ви отримаєте: {int(auction_price * 0.96)} ✯\n\n"
                f"📊 <b>Розрахунок:</b>\n"
                f"• Знижка 10%: -{int(original_price * 0.1)} ✯\n"
                f"• Комісія 4%: -{int(auction_price * 0.04)} ✯\n\n"
                f"⚖️ Переглянути аукціон: /auction\n"
                f"💡 Предмет буде видалено через 24 години"
            )
        else:
            await message.answer("❌ Помилка при додаванні на аукціон!")
            
    except ValueError:
        await message.answer("❌ Помилка! ID має бути числом.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")





# ========== БІЗНЕС СИСТЕМА ==========
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_business_licenses (
    user_id INTEGER PRIMARY KEY,
    license_id INTEGER DEFAULT 1,
    max_businesses INTEGER DEFAULT 2,
    purchased_date TEXT,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    business_type INTEGER NOT NULL,
    business_name TEXT NOT NULL,
    level INTEGER DEFAULT 1,
    income INTEGER NOT NULL,
    purchased_date TEXT NOT NULL,
    last_income_time TEXT,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS business_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    min_level INTEGER NOT NULL,
    base_price INTEGER NOT NULL,
    business_type TEXT NOT NULL,
    max_level INTEGER DEFAULT 10,
    upgrade_multiplier REAL DEFAULT 1.8,
    base_income INTEGER NOT NULL,
    income_multiplier REAL DEFAULT 1.5
)
""")

# Заповнюємо типи бізнесів
cursor.execute("SELECT COUNT(*) FROM business_types")
if cursor.fetchone()[0] == 0:
    business_types_data = [
        (1, "🚕 Таксопарк", 6, 50000, "service", 10, 1.8, 300, 1.5),
        (2, "🏪 Продуктовий магазин", 8, 100000, "retail", 10, 1.8, 600, 1.5),
        (3, "🔧 Автосервіс", 10, 200000, "service", 10, 1.8, 1200, 1.5),
        (4, "🍕 Ресторан", 12, 500000, "food", 10, 1.8, 3000, 1.5),
        (5, "🏢 Офісний центр", 15, 1000000, "real_estate", 10, 1.8, 6000, 1.5)
    ]
    cursor.executemany(
        "INSERT INTO business_types (id, name, min_level, base_price, business_type, max_level, upgrade_multiplier, base_income, income_multiplier) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        business_types_data
    )

# Ліцензії
# Ліцензії (спрощена версія)
cursor.execute("""
CREATE TABLE IF NOT EXISTS business_licenses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    max_businesses INTEGER NOT NULL,
    price INTEGER NOT NULL
)
""")

cursor.execute("SELECT COUNT(*) FROM business_licenses")
if cursor.fetchone()[0] == 0:
    licenses_data = [
        (1, "🟢 BI License", 4, 16400),
        (2, "🔵 DS License", 5, 19400),
        (3, "🟣 GT License", 6, 32000)
    ]
    cursor.executemany(
        "INSERT INTO business_licenses (id, name, max_businesses, price) VALUES (?, ?, ?, ?)",
        licenses_data
    )

# ========== СИСТЕМА АВТОМАТИЧНОГО ВИДАЛЕННЯ ==========

async def delete_message_with_delay(chat_id: int, message_id: int, delay: int = 20):
    """Видалити повідомлення через затримку"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        # Ігноруємо помилки (повідомлення вже видалено тощо)
        pass

async def send_message_with_auto_delete(chat_id: int, text: str, reply_markup=None, delay: int = 20):
    """Надіслати повідомлення з автоматичним видаленням"""
    message = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    asyncio.create_task(delete_message_with_delay(chat_id, message.message_id, delay))
    return message

async def edit_message_with_auto_delete(call: types.CallbackQuery, text: str, reply_markup=None, delay: int = 20):
    """Редагувати повідомлення з автоматичним видаленням"""
    await call.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    asyncio.create_task(delete_message_with_delay(call.message.chat.id, call.message.message_id, delay))

async def auto_delete_old_messages():
    """Автоматично видаляти старі повідомлення бота"""
    while True:
        try:
            # Тут можна додати логіку для пошуку та видалення старих повідомлень
            # Наприклад, за допомогою бази даних відстежувати ID повідомлень
            await asyncio.sleep(300)  # Перевіряємо кожні 5 хвилин
        except Exception as e:
            print(f"❌ Помилка в auto_delete_old_messages: {e}")
            await asyncio.sleep(60)
#000000000
async def cleanup_old_pending_sales():
    """Очистити старі запропоновані продажі (старіші 7 днів)"""
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    cursor.execute("DELETE FROM pending_sales WHERE created_date < ?", (week_ago,))
    conn.commit()

# Додай цей виклик до планувальника доходів або запуску бота
async def background_tasks():
    """Фонові задачі"""
    while True:
        try:
            await cleanup_old_pending_sales()
            await asyncio.sleep(3600)  # Перевіряємо кожну годину
        except Exception as e:
            print(f"❌ Помилка в background_tasks: {e}")
            await asyncio.sleep(300)

# ========== АВТОМАТИЧНА СИСТЕМА ДОХОДІВ ==========

def get_last_income_time(user_id: int) -> Optional[datetime]:
    """Отримати час останнього нарахування доходу"""
    cursor.execute("SELECT last_income_time FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        return datetime.fromisoformat(result[0])
    return None

def calculate_passive_income(user_id: int) -> int:
    """Розрахувати пасивний дохід за 6 годин"""
    farm_income = get_user_farm_income(user_id)
    estate_income = get_user_real_estate_income(user_id)
    
    role = get_user_role(user_id)
    if role == "БАНКІР":
        estate_income += 25
    
    # Залишаємо ту саму суму, що була за годину
    total_income = farm_income + estate_income
    return total_income

def update_income_for_user(user_id: int):
    """Оновити дохід для конкретного гравця (тепер кожні 6 годин)"""
    last_income_time = get_last_income_time(user_id)
    if not last_income_time:
        cursor.execute("UPDATE players SET last_income_time = ? WHERE user_id = ?", 
                       (datetime.now().isoformat(), user_id))
        conn.commit()
        return
    
    current_time = datetime.now()
    time_diff = current_time - last_income_time
    hours_passed = time_diff.total_seconds() / 3600
    
    # Змінюємо з 1 години на 6 годин
    if hours_passed >= 6:
        income_per_6_hours = calculate_passive_income(user_id)
        full_periods = int(hours_passed // 6)
        total_income = income_per_6_hours * full_periods
        
        if total_income > 0:
            add_user_coins(user_id, total_income)
            new_income_time = last_income_time + timedelta(hours=6 * full_periods)
            cursor.execute("UPDATE players SET last_income_time = ? WHERE user_id = ?", 
                           (new_income_time.isoformat(), user_id))

            # Додаємо дохід від бізнесів (кожні 6 годин)
            business_income = get_total_business_income(user_id)
            if business_income > 0:
                add_user_coins(user_id, business_income)
                print(f"💼 Нараховано {business_income} ✯ від бізнесів гравцю {user_id}")
            
            conn.commit()
            print(f"💵 Нараховано {total_income} ✯ гравцю {user_id} за {full_periods * 6} год.")
async def update_all_incomes():
    """Оновити доходи для всіх гравців"""
    try:
        cursor.execute("SELECT user_id FROM players")
        all_players = cursor.fetchall()
        
        updated_count = 0
        for (user_id,) in all_players:
            update_income_for_user(user_id)
            updated_count += 1
            
        print(f"✅ Перевірено доходи для {updated_count} гравців")
        
    except Exception as e:
        print(f"❌ Помилка оновлення доходів: {e}")

async def income_scheduler():
    """Планувальник для автоматичного нарахування доходів та кредитних виплат"""
    while True:
        try:
            await update_all_incomes()
            await asyncio.sleep(6 * 3600)  # Дохід кожні 6 годин
        except Exception as e:
            print(f"❌ Помилка в планувальнику доходів: {e}")
            await asyncio.sleep(300)

async def credit_payment_scheduler():
    """Планувальник для кредитних виплат (кожну годину)"""
    while True:
        try:
            process_credit_payments()
            await asyncio.sleep(3600)  # Кредитні виплати кожну годину
        except Exception as e:
            print(f"❌ Помилка в планувальнику кредитів: {e}")
            await asyncio.sleep(300)

# ========== ОНОВЛЕННЯ СТРУКТУРИ БАЗИ ========== БД
#====---- pass ----======
# Перевіряємо чи є колонка has_passport
# ВМЕСТО ЭТОГО добавь проверку:
cursor.execute("PRAGMA table_info(players)")
columns = [column[1] for column in cursor.fetchall()]

if 'has_passport' not in columns:
    cursor.execute("ALTER TABLE players ADD COLUMN has_passport BOOLEAN DEFAULT FALSE")
    print(" ✅ Колонку has_passport додано!")
else:
    print(" ✅ Колонка has_passport вже існує!")

# Додамо в секцію оновлення БД
if 'has_passport' not in player_columns:
    cursor.execute("ALTER TABLE players ADD COLUMN has_passport BOOLEAN DEFAULT FALSE")
# Додаємо в секцію оновлення БД
try:
    # Перевіряємо чи є колонка item_type в user_inventory
    cursor.execute("PRAGMA table_info(user_inventory)")
    inventory_columns = [column[1] for column in cursor.fetchall()]
    
    if 'item_type' not in inventory_columns:
        print("🔄 Оновлюємо структуру таблиці user_inventory для підтримки машин...")
        # Тут вже є логіка оновлення, просто переконуємося що все працює
except Exception as e:
    print(f"❌ Помилка оновлення таблиць: {e}")


try:
    # Перевіряємо чи є колонка last_income_time
    cursor.execute("PRAGMA table_info(players)")
    player_columns = [column[1] for column in cursor.fetchall()]

    if 'last_income_time' not in player_columns:
        print("🔄 Додаємо колонку last_income_time до таблиці players...")
        cursor.execute("ALTER TABLE players ADD COLUMN last_income_time TEXT")
        conn.commit()
        print("✅ Колонку last_income_time додано!")
        
except Exception as e:
    print(f"❌ Помилка оновлення таблиць: {e}")
        
except Exception as e:
    print(f"❌ Помилка оновлення таблиць: {e}")


#DELAUCH-ADMIN
# ========== АДМІН-КОМАНДА ДЛЯ ОЧИЩЕННЯ АУКЦІОНУ ==========

@dp.message_handler(commands=['clearauction'])
async def cmd_clearauction(message: types.Message):
    """Очистити весь аукціон (тільки для адмінів)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ заборонено!")
        return
    
    try:
        # Отримуємо кількість предметів перед видаленням
        cursor.execute("SELECT COUNT(*) FROM auction_items")
        items_count = cursor.fetchone()[0]
        
        if items_count == 0:
            await message.answer("ℹ️ На аукціоні вже немає предметів!")
            return
        
        # Отримуємо інформацію про предмети для повідомлення
        cursor.execute("""
            SELECT ai.item_name, p.username 
            FROM auction_items ai 
            JOIN players p ON ai.user_id = p.user_id
        """)
        items_info = cursor.fetchall()
        
        # Видаляємо всі предмети
        cursor.execute("DELETE FROM auction_items")
        conn.commit()
        
        # Формуємо список видалених предметів
        items_list = ""
        for i, (item_name, seller_name) in enumerate(items_info[:10], 1):  # Обмежуємо до 10 предметів
            items_list += f"{i}. {item_name} (від {seller_name})\n"
        
        if len(items_info) > 10:
            items_list += f"... і ще {len(items_info) - 10} предметів\n"
        
        await message.answer(
            f"🧹 <b>Аукціон очищено!</b>\n\n"
            f"📊 <b>Видалено предметів:</b> {items_count}\n\n"
            f"📦 <b>Видалені предмети:</b>\n{items_list}\n"
            f"⚡ Всі предмети успішно видалені з аукціону!"
        )
        
        # Логуємо дію
        log.info(f"👑 Адмін {message.from_user.id} очистив аукціон ({items_count} предметів)")
        
    except Exception as e:
        await message.answer(f"❌ Помилка при очищенні аукціону: {e}")
        log.error(f"Помилка очищення аукціону: {e}")
#^^0000^^

import os

QUESTIONS_PATH = "questions.json"

# Додай цю перевірку на початку
print(f"📁 Поточний каталог: {os.getcwd()}")
print(f"📁 Файл питань: {QUESTIONS_PATH}")
print(f"📁 Файл існує: {os.path.exists(QUESTIONS_PATH)}")

if os.path.exists(QUESTIONS_PATH):
    print(f"📁 Права доступу: {oct(os.stat(QUESTIONS_PATH).st_mode)[-3:]}")
    
#=============================================== USER LIST ADMIN
@dp.message_handler(commands=['us'])
async def cmd_us(message: types.Message):
    """Показати всіх гравців"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ заборонено!")
        return
    
    cursor.execute("SELECT user_id, username, level, coins FROM players ORDER BY coins DESC")
    users = cursor.fetchall()
    
    text = f"👥 <b>Всі гравці ({len(users)}):</b>\n\n"
    
    for user_id, username, level, coins in users:
        username = username or f"User{user_id}"
        text += f"👤 {username}\n🆔 {user_id} | 🎯 {level} | 💰 {coins} ✯\n\n"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Оновити", callback_data="refresh_us"))
    
    await message.answer(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'refresh_us')
async def cb_refresh_us(call: types.CallbackQuery):
    """Оновити список гравців"""
    if not is_admin(call.from_user.id):
        return
    
    await cmd_us(call.message)
    await call.answer("✅ Список оновлено!")

        # ========== ЗАПУСК БОТА ==========
async def on_startup(dp):
    # Запуск веб-сервера
    website_server = await start_website_server()
    dp.website_server = website_server
    setup_website_in_bot(dp)
    
async def main():
    """Головна асинхронна функція"""
    # Ініціалізація рулетки предметів
    cursor.execute("SELECT COUNT(*) FROM item_roulette_prizes")
    if cursor.fetchone()[0] == 0:
        for prize in ItemRoulettePrizes.PRIZES:
            cursor.execute(
                "INSERT INTO item_roulette_prizes (name, price, probability, item_type) VALUES (?, ?, ?, ?)",
                (prize["name"], prize["price"], prize["probability"], prize["type"])
            )
        conn.commit()    
    # ... решта коду запуску
    # Запуск бота
    log.info("🤖 Бот запускається...")
    log.info(f"👑 Адмін ID: {ADMIN_ID}")
    log.info("💰 Автоматична система доходів активована!")
    
    try:
        # Запускаємо фонові задачі
        asyncio.create_task(income_scheduler())
        asyncio.create_task(background_tasks())
        
        # Запускаємо бота
        await dp.start_polling()
        
    except Exception as e:
        log.error(f"❌ Помилка запуску бота: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
