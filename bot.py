import asyncio
import json
import random
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor

# ========== КОНФИГ ==========
BOT_TOKEN = "8259900558:AAHQVUzKQBtKF7N-Xp8smLmAiAf0Hu-hQHw"
XP_PER_LEVEL = 100
INACTIVE_DAYS = 7
DB_PATH = "data.db"
QUESTIONS_PATH = "questions.json"
DAILY_QUESTION_LIMIT = 10
# ============================

logging.basicConfig(level=logging.INFO, format="%(asynctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц для нового обновления
cursor.execute("""
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    last_play TEXT,
    correct_streak INTEGER DEFAULT 0,
    last_task_date TEXT DEFAULT '',
    daily_questions INTEGER DEFAULT 0,
    last_question_date TEXT DEFAULT '',
    prefix TEXT DEFAULT '',
    role TEXT DEFAULT '',
    pvp_rating INTEGER DEFAULT 1000,
    pvp_wins INTEGER DEFAULT 0,
    pvp_losses INTEGER DEFAULT 0,
    language TEXT DEFAULT 'ru'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    friend_id INTEGER,
    friend_username TEXT,
    added_date TEXT,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_real_estate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    estate_type TEXT,
    purchase_price INTEGER,
    purchase_date TEXT,
    income_per_hour INTEGER,
    FOREIGN KEY (user_id) REFERENCES players (user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pvp_duels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player1_id INTEGER,
    player2_id INTEGER,
    winner_id INTEGER,
    bet_amount INTEGER,
    duel_date TEXT,
    FOREIGN KEY (player1_id) REFERENCES players (user_id),
    FOREIGN KEY (player2_id) REFERENCES players (user_id)
)
""")

# Существующие таблицы остаются без изменений
cursor.execute("""
CREATE TABLE IF NOT EXISTS roulette_prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    prize_type TEXT NOT NULL,
    value INTEGER NOT NULL,
    probability REAL NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS roulette_spins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    prize_id INTEGER NOT NULL,
    spin_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players (user_id),
    FOREIGN KEY (prize_id) REFERENCES roulette_prizes (id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_farm (
    user_id INTEGER PRIMARY KEY,
    animals INTEGER DEFAULT 0,
    last_collect_time TEXT,
    total_earned INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_tap_boost (
    user_id INTEGER PRIMARY KEY,
    boost_level INTEGER DEFAULT 1,
    tap_income REAL DEFAULT 1.24,
    total_taps INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0
)
""")
conn.commit()

# ========== КОНСТАНТЫ ОБНОВЛЕНИЯ 2.1.0 ==========
class Prefixes:
    BOSS = {"name": "Босс", "price": 350}
    FAT = {"name": "Толстун", "price": 320}
    PROGRAMMER = {"name": "Программист", "price": 560}
    LEGEND = {"name": "Легенда", "price": 720}
    EMPEROR = {"name": "Император", "price": 1300}
    ASSASSIN = {"name": "Ассасин", "price": 2200}
    OVERSEER = {"name": "Надзиратель", "price": 4500}
    
    ALL_PREFIXES = [BOSS, FAT, PROGRAMMER, LEGEND, EMPEROR, ASSASSIN, OVERSEER]

class Roles:
    FARMER = {"name": "Фермер", "price": 500, "bonus": "farm_income"}
    SMART = {"name": "Умник", "price": 800, "bonus": "question_limit"}
    TAPPER = {"name": "Дрочер", "price": 600, "bonus": "tap_income"}
    
    ALL_ROLES = [FARMER, SMART, TAPPER]

class RealEstate:
    SMALL_HOUSE = {"name": "🏠 Маленький дом", "price": 2000, "income": 125}
    APARTMENT = {"name": "🏡 Квартира", "price": 4500, "income": 300}
    TOWNHOUSE = {"name": "🏘️ Таунхаус", "price": 8000, "income": 600}
    OFFICE = {"name": "🏢 Офисное здание", "price": 12000, "income": 950}
    BUSINESS_CENTER = {"name": "🏛️ Бизнес-центр", "price": 17000, "income": 1400}
    
    ALL_ESTATES = [SMALL_HOUSE, APARTMENT, TOWNHOUSE, OFFICE, BUSINESS_CENTER]

class Languages:
    RU = "ru"
    UA = "ua"
    EN = "en"

# Тексты на разных языках
TEXTS = {
    "ru": {
        "main_menu": "🎮 Главное меню",
        "profile": "👤 Профиль",
        "play": "🎯 Играть",
        "roulette": "🎰 Рулетка", 
        "income": "💰 Доходы",
        "leaderboard": "🏆 Лидеры",
        "tasks": "📅 Задания",
        "shop": "🛍️ Магазин",
        "friends": "👥 Друзья",
        "pvp": "⚔️ PvP Арена",
        "real_estate": "🏘️ Недвижимость"
    },
    "ua": {
        "main_menu": "🎮 Головне меню",
        "profile": "👤 Профіль", 
        "play": "🎯 Грати",
        "roulette": "🎰 Рулетка",
        "income": "💰 Доходи",
        "leaderboard": "🏆 Лідери",
        "tasks": "📅 Завдання",
        "shop": "🛍️ Магазин",
        "friends": "👥 Друзі",
        "pvp": "⚔️ PvP Арена",
        "real_estate": "🏘️ Нерухомість"
    },
    "en": {
        "main_menu": "🎮 Main Menu",
        "profile": "👤 Profile",
        "play": "🎯 Play", 
        "roulette": "🎰 Roulette",
        "income": "💰 Income",
        "leaderboard": "🏆 Leaders",
        "tasks": "📅 Tasks",
        "shop": "🛍️ Shop",
        "friends": "👥 Friends",
        "pvp": "⚔️ PvP Arena",
        "real_estate": "🏘️ Real Estate"
    }
}

# ========== СУЩЕСТВУЮЩИЕ КЛАССЫ И ФУНКЦИИ ==========
# [Здесь весь ваш существующий код классов Roulette, FarmManager, TapGame, Shop...]
# Я сохраняю все ваши оригинальные классы и функции, но добавляю новые

class Roulette:
    def __init__(self):
        self.cost = 4000
        self.prizes = []
        self._load_prizes()
    
    def _load_prizes(self):
        cursor.execute("SELECT id, name, prize_type, value, probability FROM roulette_prizes")
        prizes_data = cursor.fetchall()
        
        if not prizes_data:
            self._create_default_prizes()
            cursor.execute("SELECT id, name, prize_type, value, probability FROM roulette_prizes")
            prizes_data = cursor.fetchall()
        
        for prize_id, name, prize_type, value, probability in prizes_data:
            self.prizes.append({
                'id': prize_id,
                'name': name,
                'type': prize_type,
                'value': value,
                'probability': probability
            })
    
    def _create_default_prizes(self):
        default_prizes = [
            ("🎯 Джекпот!", "jackpot", 10000, 0.02),
            ("💰 Большой выигрыш", "coins", 5000, 0.05),
            ("💵 Средний выигрыш", "coins", 2000, 0.10),
            ("🪙 Малый выигрыш", "coins", 1000, 0.15),
            ("🎫 Бесплатный спин", "free_spin", 1, 0.20),
            ("⭐ Опыт", "experience", 200, 0.25),
            ("🔮 Небольшой приз", "coins", 500, 0.23)
        ]
        
        for name, prize_type, value, probability in default_prizes:
            cursor.execute(
                "INSERT INTO roulette_prizes (name, prize_type, value, probability) VALUES (?, ?, ?, ?)",
                (name, prize_type, value, probability)
            )
        conn.commit()
    
    def spin(self):
        r = random.random()
        cumulative_probability = 0.0
        
        for prize in self.prizes:
            cumulative_probability += prize['probability']
            if r <= cumulative_probability:
                return prize
        
        return self.prizes[-1]

roulette = Roulette()

class FarmManager:
    @staticmethod
    def get_animal_income(animals_count: int, role_bonus: bool = False) -> float:
        base_income = animals_count * 11.25
        if role_bonus:
            base_income *= 1.05  # +5% бонус фермера
        return base_income
    
    @staticmethod
    def calculate_earnings(animals_count: int, hours_passed: float, role_bonus: bool = False) -> int:
        income_per_hour = FarmManager.get_animal_income(animals_count, role_bonus)
        return int(income_per_hour * hours_passed)

class TapGame:
    BOOST_LEVELS = {
        1: {"income": 1.24, "price": 0},
        2: {"income": 1.89, "price": 322},
        3: {"income": 2.00, "price": 422},
        4: {"income": 2.11, "price": 490},
        5: {"income": 2.65, "price": 530},
        6: {"income": 3.00, "price": 600}
    }
    
    @staticmethod
    def get_next_boost_level(current_level: int) -> dict:
        next_level = current_level + 1
        if next_level in TapGame.BOOST_LEVELS:
            return {
                "level": next_level,
                "income": TapGame.BOOST_LEVELS[next_level]["income"],
                "price": TapGame.BOOST_LEVELS[next_level]["price"]
            }
        return None

class Shop:
    ANIMAL_PRICE = 300
    MAX_ANIMALS = 10

# ========== НОВЫЕ ФУНКЦИИ ОБНОВЛЕНИЯ 2.1.0 ==========
def get_user_language(user_id: int) -> str:
    """Получить язык пользователя"""
    cursor.execute("SELECT language FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else "ru"

def get_text(key: str, user_id: int) -> str:
    """Получить текст на языке пользователя"""
    lang = get_user_language(user_id)
    return TEXTS.get(lang, {}).get(key, key)

def ensure_player(user_id: int, username: Optional[str]):
    """Обновленная функция с новыми полями"""
    cursor.execute("SELECT user_id FROM players WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            """INSERT INTO players 
            (user_id, username, last_play, level, xp, coins, correct_streak, 
             last_task_date, daily_questions, last_question_date, prefix, role, language) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username or "", datetime.now().isoformat(), 1, 0, 0, 0, "", 0, "", "", "", "ru")
        )
        conn.commit()
        log.info(f"Created new player: {user_id} ({username})")
    else:
        cursor.execute("UPDATE players SET username = ? WHERE user_id = ?", (username or "", user_id))
        conn.commit()

def get_user_prefix(user_id: int) -> str:
    """Получить префикс пользователя"""
    cursor.execute("SELECT prefix FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else ""

def get_user_role(user_id: int) -> str:
    """Получить роль пользователя"""
    cursor.execute("SELECT role FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else ""

def get_user_real_estate(user_id: int) -> List[Dict]:
    """Получить недвижимость пользователя"""
    cursor.execute(
        "SELECT estate_type, purchase_price, income_per_hour FROM user_real_estate WHERE user_id = ?",
        (user_id,)
    )
    estates = []
    for estate_type, price, income in cursor.fetchall():
        estates.append({
            "type": estate_type,
            "price": price,
            "income": income
        })
    return estates

def get_total_real_estate_income(user_id: int) -> int:
    """Получить общий доход от недвижимости"""
    estates = get_user_real_estate(user_id)
    return sum(estate["income"] for estate in estates)

def buy_prefix(user_id: int, prefix_name: str) -> bool:
    """Купить префикс"""
    prefix_data = next((p for p in Prefixes.ALL_PREFIXES if p["name"] == prefix_name), None)
    if not prefix_data:
        return False
    
    user_coins = get_user_coins(user_id)
    if user_coins < prefix_data["price"]:
        return False
    
    cursor.execute("UPDATE players SET coins = coins - ?, prefix = ? WHERE user_id = ?",
                   (prefix_data["price"], prefix_name, user_id))
    conn.commit()
    return True

def buy_role(user_id: int, role_name: str) -> bool:
    """Купить роль"""
    role_data = next((r for r in Roles.ALL_ROLES if r["name"] == role_name), None)
    if not role_data:
        return False
    
    user_coins = get_user_coins(user_id)
    if user_coins < role_data["price"]:
        return False
    
    cursor.execute("UPDATE players SET coins = coins - ?, role = ? WHERE user_id = ?",
                   (role_data["price"], role_name, user_id))
    conn.commit()
    return True

def buy_real_estate(user_id: int, estate_type: str) -> bool:
    """Купить недвижимость"""
    estate_data = next((e for e in RealEstate.ALL_ESTATES if e["name"] == estate_type), None)
    if not estate_data:
        return False
    
    user_coins = get_user_coins(user_id)
    if user_coins < estate_data["price"]:
        return False
    
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?",
                   (estate_data["price"], user_id))
    
    cursor.execute(
        """INSERT INTO user_real_estate 
        (user_id, estate_type, purchase_price, purchase_date, income_per_hour) 
        VALUES (?, ?, ?, ?, ?)""",
        (user_id, estate_type, estate_data["price"], datetime.now().isoformat(), estate_data["income"])
    )
    conn.commit()
    return True

def get_user_friends(user_id: int) -> List[Dict]:
    """Получить список друзей"""
    cursor.execute(
        """SELECT f.friend_id, f.friend_username, p.level, p.prefix, p.role 
        FROM user_friends f 
        LEFT JOIN players p ON f.friend_id = p.user_id 
        WHERE f.user_id = ?""",
        (user_id,)
    )
    friends = []
    for friend_id, username, level, prefix, role in cursor.fetchall():
        friends.append({
            "id": friend_id,
            "username": username,
            "level": level or 1,
            "prefix": prefix or "",
            "role": role or ""
        })
    return friends

def add_friend(user_id: int, friend_id: int, friend_username: str) -> bool:
    """Добавить друга"""
    # Проверяем, не добавлен ли уже
    cursor.execute("SELECT id FROM user_friends WHERE user_id = ? AND friend_id = ?", (user_id, friend_id))
    if cursor.fetchone():
        return False
    
    cursor.execute(
        "INSERT INTO user_friends (user_id, friend_id, friend_username, added_date) VALUES (?, ?, ?, ?)",
        (user_id, friend_id, friend_username, datetime.now().isoformat())
    )
    conn.commit()
    return True

def get_user_inventory(user_id: int) -> Dict:
    """Получить инвентарь пользователя"""
    prefix = get_user_prefix(user_id)
    role = get_user_role(user_id)
    estates = get_user_real_estate(user_id)
    
    return {
        "prefix": prefix,
        "role": role,
        "real_estate": estates,
        "total_estate_income": get_total_real_estate_income(user_id),
        "estate_count": len(estates)
    }

# ========== ОБНОВЛЕННЫЕ КЛАВИАТУРЫ ==========
def build_main_menu(user_id: int):
    """Обновленное главное меню"""
    lang = get_user_language(user_id)
    kb = InlineKeyboardMarkup(row_width=2)
    
    texts = TEXTS[lang]
    
    kb.add(
        InlineKeyboardButton(texts["play"], callback_data="menu_play"),
        InlineKeyboardButton(texts["profile"], callback_data="menu_profile"),
        InlineKeyboardButton(texts["roulette"], callback_data="menu_roulette"),
        InlineKeyboardButton(texts["income"], callback_data="menu_income"),
        InlineKeyboardButton(texts["leaderboard"], callback_data="menu_leaderboard"),
        InlineKeyboardButton(texts["pvp"], callback_data="menu_pvp"),
        InlineKeyboardButton(texts["friends"], callback_data="menu_friends"),
        InlineKeyboardButton(texts["real_estate"], callback_data="menu_real_estate"),
        InlineKeyboardButton(texts["shop"], callback_data="menu_shop"),
        InlineKeyboardButton(texts["tasks"], callback_data="menu_tasks")
    )
    return kb

def build_shop_menu():
    """Меню магазина"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🏷️ Префиксы", callback_data="shop_prefixes"),
        InlineKeyboardButton("🎭 Роли", callback_data="shop_roles"),
        InlineKeyboardButton("🏘️ Недвижимость", callback_data="shop_real_estate"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

def build_friends_menu(user_id: int):
    """Меню друзей"""
    friends = get_user_friends(user_id)
    kb = InlineKeyboardMarkup(row_width=1)
    
    if friends:
        for friend in friends[:5]:  # Показываем первых 5 друзей
            display_name = f"{friend['prefix']} {friend['username']}" if friend['prefix'] else friend['username']
            kb.add(InlineKeyboardButton(
                f"👤 {display_name} (Ур. {friend['level']})", 
                callback_data=f"friend_view_{friend['id']}"
            ))
    
    kb.add(
        InlineKeyboardButton("🔍 Добавить друга", callback_data="friends_add"),
        InlineKeyboardButton("📊 Список друзей", callback_data="friends_list"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

def build_pvp_menu():
    """Меню PvP"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("⚔️ Быстрая дуэль", callback_data="pvp_quick"),
        InlineKeyboardButton("🏆 Рейтинговый бой", callback_data="pvp_rated"),
        InlineKeyboardButton("👥 Вызов друга", callback_data="pvp_friend"),
        InlineKeyboardButton("📊 Моя статистика", callback_data="pvp_stats"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

# ========== ОБНОВЛЕННЫЕ ФУНКЦИИ ==========
def format_profile_row(user_row, user_id: int):
    """Обновленный формат профиля с префиксом и ролью"""
    if not user_row:
        return "👤 <b>Профиль</b>\n\n❌ Профиль не найден."
    
    if len(user_row) >= 6:
        level, xp, coins, last_play, streak, daily_questions = user_row[:6]
    else:
        level, xp, coins, last_play, streak = user_row
        daily_questions = 0
    
    # Исправляем возможные None значения
    if level is None: level = 1
    if xp is None: xp = 0
    if coins is None: coins = 0
    if streak is None: streak = 0
    if daily_questions is None: daily_questions = 0
    
    # Получаем префикс и роль
    prefix = get_user_prefix(user_id)
    role = get_user_role(user_id)
    total_estate_income = get_total_real_estate_income(user_id)
    
    try:
        lp = datetime.fromisoformat(last_play).strftime("%d.%m.%Y %H:%M") if last_play else "—"
    except Exception:
        lp = last_play or "—"
    
    profile_text = f"👤 <b>Профиль</b>\n\n"
    
    if prefix:
        profile_text += f"🏷️ Префикс: <b>[{prefix}]</b>\n"
    if role:
        profile_text += f"🎭 Роль: <b>{role}</b>\n"
    
    profile_text += (
        f"🏆 Уровень: <b>{level}</b>\n"
        f"✨ Опыт: <b>{xp}/{XP_PER_LEVEL}</b>\n"
        f"💰 Монеты: <b>{coins} ✯</b>\n"
    )
    
    if total_estate_income > 0:
        profile_text += f"🏘️ Доход от недвижимости: <b>{total_estate_income} ✯/час</b>\n"
    
    profile_text += (
        f"📅 Последняя игра: <b>{lp}</b>\n"
        f"🔥 Серия правильных ответов: {streak}\n"
        f"🎯 Вопросов сегодня: {daily_questions}/{DAILY_QUESTION_LIMIT}"
    )
    
    return profile_text

def get_user_coins(user_id: int) -> int:
    """Получить баланс пользователя"""
    cursor.execute("SELECT coins FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

# ========== СУЩЕСТВУЮЩИЕ ФУНКЦИИ ==========
# [Здесь все ваши существующие функции ensure_player, update_last_play, cleanup_inactive_players и т.д.]
# Я сохраняю их, но добавляю вызовы ensure_player где нужно

# ========== НОВЫЕ ХЕНДЛЕРЫ ОБНОВЛЕНИЯ 2.1.0 ==========
@dp.callback_query_handler(lambda c: c.data == "menu_shop")
async def cb_menu_shop(call: types.CallbackQuery):
    """Магазин"""
    await call.answer()
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(call.from_user.id)
    text = f"🛍️ <b>Магазин</b>\n\n💵 Ваш баланс: <b>{user_coins} ✯</b>\n\nВыберите категорию:"
    
    await call.message.edit_text(text, reply_markup=build_shop_menu())

@dp.callback_query_handler(lambda c: c.data == "shop_prefixes")
async def cb_shop_prefixes(call: types.CallbackQuery):
    """Магазин префиксов"""
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    current_prefix = get_user_prefix(user_id)
    
    text = f"🏷️ <b>Магазин префиксов</b>\n\n💵 Баланс: <b>{user_coins} ✯</b>\n"
    text += f"📌 Текущий префикс: <b>{current_prefix if current_prefix else 'Нет'}</b>\n\n"
    
    kb = InlineKeyboardMarkup(row_width=1)
    for prefix in Prefixes.ALL_PREFIXES:
        if user_coins >= prefix["price"]:
            kb.add(InlineKeyboardButton(
                f"[{prefix['name']}] - {prefix['price']} ✯", 
                callback_data=f"buy_prefix_{prefix['name']}"
            ))
        else:
            kb.add(InlineKeyboardButton(
                f"[{prefix['name']}] - {prefix['price']} ✯ ❌", 
                callback_data="not_enough_coins"
            ))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_shop"))
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("buy_prefix_"))
async def cb_buy_prefix(call: types.CallbackQuery):
    """Покупка префикса"""
    await call.answer()
    user_id = call.from_user.id
    prefix_name = call.data.replace("buy_prefix_", "")
    
    if buy_prefix(user_id, prefix_name):
        await call.answer(f"✅ Префикс [{prefix_name}] куплен!", show_alert=True)
        await cb_shop_prefixes(call)  # Обновляем меню
    else:
        await call.answer("❌ Недостаточно монет или ошибка!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "shop_roles")
async def cb_shop_roles(call: types.CallbackQuery):
    """Магазин ролей"""
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    current_role = get_user_role(user_id)
    
    text = f"🎭 <b>Магазин ролей</b>\n\n💵 Баланс: <b>{user_coins} ✯</b>\n"
    text += f"🎯 Текущая роль: <b>{current_role if current_role else 'Нет'}</b>\n\n"
    
    # Описания бонусов
    bonuses = {
        "Фермер": "+5% к доходу фермы",
        "Умник": "Лимит вопросов: 15 → 25/день", 
        "Дрочер": "+2% к доходу за тап"
    }
    
    kb = InlineKeyboardMarkup(row_width=1)
    for role in Roles.ALL_ROLES:
        bonus_text = bonuses.get(role["name"], "")
        if user_coins >= role["price"]:
            kb.add(InlineKeyboardButton(
                f"{role['name']} - {role['price']} ✯\n{bonus_text}", 
                callback_data=f"buy_role_{role['name']}"
            ))
        else:
            kb.add(InlineKeyboardButton(
                f"{role['name']} - {role['price']} ✯ ❌\n{bonus_text}", 
                callback_data="not_enough_coins"
            ))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_shop"))
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("buy_role_"))
async def cb_buy_role(call: types.CallbackQuery):
    """Покупка роли"""
    await call.answer()
    user_id = call.from_user.id
    role_name = call.data.replace("buy_role_", "")
    
    if buy_role(user_id, role_name):
        await call.answer(f"✅ Роль {role_name} куплена!", show_alert=True)
        await cb_shop_roles(call)  # Обновляем меню
    else:
        await call.answer("❌ Недостаточно монет или ошибка!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "shop_real_estate")
async def cb_shop_real_estate(call: types.CallbackQuery):
    """Магазин недвижимости"""
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    user_estates = get_user_real_estate(user_id)
    
    text = f"🏘️ <b>Магазин недвижимости</b>\n\n💵 Баланс: <b>{user_coins} ✯</b>\n"
    text += f"🏠 Ваша недвижимость: <b>{len(user_estates)} объектов</b>\n"
    text += f"💰 Общий доход: <b>{get_total_real_estate_income(user_id)} ✯/час</b>\n\n"
    
    kb = InlineKeyboardMarkup(row_width=1)
    for estate in RealEstate.ALL_ESTATES:
        payback_time = estate["price"] / estate["income"]
        if user_coins >= estate["price"]:
            kb.add(InlineKeyboardButton(
                f"{estate['name']} - {estate['price']} ✯\nДоход: {estate['income']} ✯/час (Окупаемость: {payback_time:.1f}ч)", 
                callback_data=f"buy_estate_{estate['name']}"
            ))
        else:
            kb.add(InlineKeyboardButton(
                f"{estate['name']} - {estate['price']} ✯ ❌\nДоход: {estate['income']} ✯/час", 
                callback_data="not_enough_coins"
            ))
    
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_shop"))
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("buy_estate_"))
async def cb_buy_estate(call: types.CallbackQuery):
    """Покупка недвижимости"""
    await call.answer()
    user_id = call.from_user.id
    estate_name = call.data.replace("buy_estate_", "")
    
    if buy_real_estate(user_id, estate_name):
        await call.answer(f"✅ {estate_name} куплен!", show_alert=True)
        await cb_shop_real_estate(call)  # Обновляем меню
    else:
        await call.answer("❌ Недостаточно монет или ошибка!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "menu_friends")
async def cb_menu_friends(call: types.CallbackQuery):
    """Меню друзей"""
    await call.answer()
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    
    friends = get_user_friends(call.from_user.id)
    text = f"👥 <b>Друзья</b>\n\n📊 Всего друзей: <b>{len(friends)}</b>\n\n"
    
    if friends:
        text += "<b>Недавно добавленные:</b>\n"
        for friend in friends[:3]:
            display_name = f"{friend['prefix']} {friend['username']}" if friend['prefix'] else friend['username']
            text += f"• {display_name} (Ур. {friend['level']})\n"
    
    await call.message.edit_text(text, reply_markup=build_friends_menu(call.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "friends_add")
async def cb_friends_add(call: types.CallbackQuery):
    """Добавление друга"""
    await call.answer()
    text = (
        "🔍 <b>Добавить друга</b>\n\n"
        "Чтобы добавить друга, вам нужно:\n"
        "1. Узнать его ID в боте (/id)\n"
        "2. Отправить ему свой ID\n"
        "3. Использовать команду:\n"
        "<code>/addfriend ID_друга</code>\n\n"
        "Ваш ID: " + str(call.from_user.id)
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_friends"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("friend_view_"))
async def cb_friend_view(call: types.CallbackQuery):
    """Просмотр профиля друга"""
    await call.answer()
    friend_id = int(call.data.replace("friend_view_", ""))
    
    # Получаем данные друга
    cursor.execute(
        "SELECT level, xp, coins, last_play, correct_streak, daily_questions FROM players WHERE user_id = ?", 
        (friend_id,)
    )
    friend_data = cursor.fetchone()
    
    if not friend_data:
        await call.answer("❌ Друг не найден!", show_alert=True)
        return
    
    # Получаем инвентарь друга
    inventory = get_user_inventory(friend_id)
    
    text = f"👤 <b>Профиль друга</b>\n\n"
    
    if inventory["prefix"]:
        text += f"🏷️ Префикс: <b>[{inventory['prefix']}]</b>\n"
    if inventory["role"]:
        text += f"🎭 Роль: <b>{inventory['role']}</b>\n"
    
    level, xp, coins, last_play, streak, daily_questions = friend_data
    text += (
        f"🏆 Уровень: <b>{level}</b>\n"
        f"💰 Монеты: <b>{coins} ✯</b>\n"
        f"🏘️ Недвижимость: <b>{inventory['estate_count']} объектов</b>\n"
        f"💵 Доход от недвижимости: <b>{inventory['total_estate_income']} ✯/час</b>\n"
        f"🔥 Серия ответов: <b>{streak}</b>"
    )
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⚔️ Вызвать на дуэль", callback_data=f"pvp_challenge_{friend_id}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_friends"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "menu_pvp")
async def cb_menu_pvp(call: types.CallbackQuery):
    """Меню PvP"""
    await call.answer()
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    
    # Получаем статистику PvP
    cursor.execute(
        "SELECT pvp_rating, pvp_wins, pvp_losses FROM players WHERE user_id = ?", 
        (call.from_user.id,)
    )
    rating, wins, losses = cursor.fetchone() or (1000, 0, 0)
    
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    
    text = (
        f"⚔️ <b>PvP Арена</b>\n\n"
        f"📊 Ваша статистика:\n"
        f"🏆 Рейтинг: <b>{rating}</b>\n"
        f"✅ Побед: <b>{wins}</b>\n"
        f"❌ Поражений: <b>{losses}</b>\n"
        f"📈 Винрейт: <b>{win_rate:.1f}%</b>"
    )
    
    await call.message.edit_text(text, reply_markup=build_pvp_menu())

@dp.callback_query_handler(lambda c: c.data == "menu_real_estate")
async def cb_menu_real_estate(call: types.CallbackQuery):
    """Меню недвижимости"""
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    estates = get_user_real_estate(user_id)
    total_income = get_total_real_estate_income(user_id)
    
    text = f"🏘️ <b>Моя недвижимость</b>\n\n"
    text += f"💰 Общий доход: <b>{total_income} ✯/час</b>\n"
    text += f"🏠 Всего объектов: <b>{len(estates)}</b>\n\n"
    
    if estates:
        text += "<b>Ваши объекты:</b>\n"
        for estate in estates:
            text += f"• {estate['type']} - {estate['income']} ✯/час\n"
    else:
        text += "❌ У вас пока нет недвижимости.\n🛍️ Посетите магазин чтобы приобрести!"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ Купить недвижимость", callback_data="shop_real_estate"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "not_enough_coins")
async def cb_not_enough_coins(call: types.CallbackQuery):
    """Недостаточно монет"""
    await call.answer("❌ Недостаточно монет!", show_alert=True)

# ========== НОВЫЕ КОМАНДЫ ==========
@dp.message_handler(commands=["id"])
async def cmd_id(message: types.Message):
    """Показать ID пользователя"""
    text = (
        f"🆔 <b>Ваш ID:</b> <code>{message.from_user.id}</code>\n\n"
        "Используйте этот ID для добавления в друзья.\n"
        "Друг может добавить вас командой:\n"
        f"<code>/addfriend {message.from_user.id}</code>"
    )
    await message.answer(text)

@dp.message_handler(commands=["addfriend"])
async def cmd_add_friend(message: types.Message):
    """Добавить друга по ID"""
    try:
        if len(message.text.split()) < 2:
            await message.answer("❌ Использование: /addfriend <ID_друга>")
            return
        
        friend_id = int(message.text.split()[1])
        
        # Нельзя добавить себя
        if friend_id == message.from_user.id:
            await message.answer("❌ Нельзя добавить себя в друзья!")
            return
        
        # Проверяем существует ли игрок
        cursor.execute("SELECT username FROM players WHERE user_id = ?", (friend_id,))
        friend_data = cursor.fetchone()
        
        if not friend_data:
            await message.answer("❌ Игрок с таким ID не найден!")
            return
        
        friend_username = friend_data[0] or f"Игрок {friend_id}"
        
        if add_friend(message.from_user.id, friend_id, friend_username):
            await message.answer(f"✅ Игрок {friend_username} добавлен в друзья!")
        else:
            await message.answer("❌ Этот игрок уже у вас в друзьях!")
            
    except ValueError:
        await message.answer("❌ Неверный формат ID!")
    except Exception as e:
        await message.answer("❌ Произошла ошибка!")

@dp.message_handler(commands=["inventory"])
async def cmd_inventory(message: types.Message):
    """Показать инвентарь"""
    ensure_player(message.from_user.id, message.from_user.username or message.from_user.full_name)
    inventory = get_user_inventory(message.from_user.id)
    
    text = "🎒 <b>Ваш инвентарь</b>\n\n"
    
    if inventory["prefix"]:
        text += f"🏷️ Префикс: <b>[{inventory['prefix']}]</b>\n"
    else:
        text += "🏷️ Префикс: <b>Нет</b>\n"
    
    if inventory["role"]:
        text += f"🎭 Роль: <b>{inventory['role']}</b>\n"
    else:
        text += "🎭 Роль: <b>Нет</b>\n"
    
    text += f"\n🏘️ Недвижимость: <b>{inventory['estate_count']} объектов</b>\n"
    text += f"💰 Общий доход: <b>{inventory['total_estate_income']} ✯/час</b>\n"
    
    if inventory["real_estate"]:
        text += "\n<b>Ваши объекты:</b>\n"
        for estate in inventory["real_estate"]:
            text += f"• {estate['type']}\n"
    
    await message.answer(text)

# ========== СУЩЕСТВУЮЩИЕ ХЕНДЛЕРЫ ==========
# [Здесь все ваши существующие хендлеры, но я обновляю некоторые]

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    cleanup_inactive_players()
    ensure_player(message.from_user.id, message.from_user.username or message.from_user.full_name)
    update_last_play(message.from_user.id)
    
    # Приветственное сообщение с новыми функциями
    text = (
        f"Привет, <b>{message.from_user.first_name}</b>! 🎮\n\n"
        "✨ <b>Обновление 2.1.0</b> ✨\n"
        "• 🏷️ Префиксы и роли\n" 
        "• 👥 Система друзей\n"
        "• ⚔️ PvP дуэли\n"
        "• 🏘️ Недвижимость\n"
        "• 🎒 Инвентарь\n\n"
        "Выбери действие в меню:"
    )
    
    await message.answer(text, reply_markup=build_main_menu(message.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "menu_profile")
async def cb_menu_profile(call: types.CallbackQuery):
    """Обновленный профиль"""
    await call.answer()
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    update_last_play(call.from_user.id)
    
    cursor.execute(
        "SELECT level, xp, coins, last_play, correct_streak, daily_questions FROM players WHERE user_id = ?", 
        (call.from_user.id,)
    )
    user = cursor.fetchone()
    
    await call.message.edit_text(
        format_profile_row(user, call.from_user.id), 
        reply_markup=build_back_button("main")
    )

# ========== МОИ ДОПОЛНЕНИЯ ==========
@dp.message_handler(commands=["language"])
async def cmd_language(message: types.Message):
    """Смена языка"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_ua"), 
        InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")
    )
    
    await message.answer("🌍 Выберите язык / Choose language / Оберіть мову:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("lang_"))
async def cb_language(call: types.CallbackQuery):
    """Обработка смены языка"""
    lang = call.data.replace("lang_", "")
    cursor.execute("UPDATE players SET language = ? WHERE user_id = ?", (lang, call.from_user.id))
    conn.commit()
    
    await call.answer("✅ Язык изменен!" if lang == "ru" else 
                     "✅ Language changed!" if lang == "en" else 
                     "✅ Мову змінено!", show_alert=True)
    
    await call.message.edit_text(
        TEXTS[lang]["main_menu"], 
        reply_markup=build_main_menu(call.from_user.id)
    )

# ========== ФОН ==========
async def periodic_cleanup():
    while True:
        try:
            cleanup_inactive_players()
        except Exception:
            log.exception("periodic_cleanup")
        await asyncio.sleep(60 * 60 * 24)

# ========== СТАРТ ==========
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(periodic_cleanup())
    executor.start_polling(dp, skip_updates=True)
