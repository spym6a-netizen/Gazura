# bot.py — Викторина с лимитом вопросов, друзьями и новой валютой
import asyncio
import json
import random
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor

# ========== КОНФИГ ==========
BOT_TOKEN = "8259900558:AAHQVUzKQBtKF7N-Xp8smLmAiAf0Hu-hQHw"
XP_PER_LEVEL = 100
INACTIVE_DAYS = 7
DB_PATH = "data.db"
QUESTIONS_PATH = "questions.json"
DAILY_QUESTION_LIMIT = 10  # Лимит вопросов в день
# ============================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# ========== БД ==========
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ДОБАВЬ ЭТОТ КОД - ОБНОВЛЕНИЕ СТРУКТУРЫ БАЗЫ
try:
    # Проверяем существование новых колонок и добавляем их если нужно
    cursor.execute("PRAGMA table_info(players)")
    existing_columns = [column[1] for column in cursor.fetchall()]
    
    # Добавляем отсутствующие колонки
    if 'daily_questions' not in existing_columns:
        cursor.execute("ALTER TABLE players ADD COLUMN daily_questions INTEGER DEFAULT 0")
        print("✅ Добавлена колонка daily_questions")
    
    if 'last_question_date' not in existing_columns:
        cursor.execute("ALTER TABLE players ADD COLUMN last_question_date TEXT DEFAULT ''")
        print("✅ Добавлена колонка last_question_date")
    
    if 'last_task_date' not in existing_columns:
        cursor.execute("ALTER TABLE players ADD COLUMN last_task_date TEXT DEFAULT ''")
        print("✅ Добавлена колонка last_task_date")
        
    conn.commit()
except Exception as e:
    print(f"❌ Ошибка при обновлении БД: {e}")

# ПОТОМ ИДЕТ СТАРЫЙ КОД СОЗДАНИЯ ТАБЛИЦ
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
    daily_questions INTEGER DEFAULT 0,  -- Количество вопросов сегодня
    last_question_date TEXT DEFAULT ''  -- Дата последнего вопроса
)
""")

# Додай ці таблиці для рулетки
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

# Додай ці таблиці для ферми та tap game
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

# ========== ВОПРОСЫ ==========
QUESTIONS: list = []
questions_file = Path(QUESTIONS_PATH)
if not questions_file.exists():
    log.warning(f"{QUESTIONS_PATH} не найден — создайте файл с вопросами.")
else:
    try:
        with questions_file.open("r", encoding="utf-8") as f:
            QUESTIONS = json.load(f)
            if not isinstance(QUESTIONS, list):
                log.error("questions.json должен содержать список вопросов.")
                QUESTIONS = []
    except Exception:
        log.exception("Не удалось загрузить questions.json")
        QUESTIONS = []

# ========== РУЛЕТКА ==========
class RoulettePrizeType:
    COINS = "coins"
    FREE_SPIN = "free_spin"
    EXPERIENCE = "experience"
    JACKPOT = "jackpot"

class Roulette:
    def __init__(self):
        self.cost = 4000
        self.prizes = []
        self._load_prizes()
    
    def _load_prizes(self):
        """Завантажити призи з бази даних"""
        cursor.execute("SELECT id, name, prize_type, value, probability FROM roulette_prizes")
        prizes_data = cursor.fetchall()
        
        if not prizes_data:
            # Якщо призів немає - створити стандартні
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
        """Створити стандартні призи"""
        default_prizes = [
            ("🎯 Джекпот!", RoulettePrizeType.JACKPOT, 10000, 0.02),      # 2%
            ("💰 Великий выигрыш", RoulettePrizeType.COINS, 5000, 0.05),   # 5%
            ("💵 Средний выигрыш", RoulettePrizeType.COINS, 2000, 0.10),  # 10%
            ("🪙 Малый выигрыш", RoulettePrizeType.COINS, 1000, 0.15),     # 15%
            ("🎫 Бесплатный спин", RoulettePrizeType.FREE_SPIN, 1, 0.20), # 20%
            ("⭐ Опыт", RoulettePrizeType.EXPERIENCE, 200, 0.25),       # 25%
            ("🔮 Небольшой приз", RoulettePrizeType.COINS, 500, 0.23)     # 23%
        ]
        
        for name, prize_type, value, probability in default_prizes:
            cursor.execute(
                "INSERT INTO roulette_prizes (name, prize_type, value, probability) VALUES (?, ?, ?, ?)",
                (name, prize_type, value, probability)
            )
        conn.commit()
    
    def spin(self):
        """Прокрутити рулетку"""
        r = random.random()
        cumulative_probability = 0.0
        
        for prize in self.prizes:
            cumulative_probability += prize['probability']
            if r <= cumulative_probability:
                return prize
        
        return self.prizes[-1]  # На всякий випадок повертаємо останній приз

# Глобальний екземпляр рулетки
roulette = Roulette()

# ========== ФЕРМА І TAP GAME ==========
class FarmManager:
    @staticmethod
    def get_animal_income(animals_count: int) -> float:
        """Дохід за годину від тварин"""
        return animals_count * 11.25
    
    @staticmethod
    def calculate_earnings(animals_count: int, hours_passed: float) -> int:
        """Розрахувати заробіток за пройдений час"""
        income_per_hour = FarmManager.get_animal_income(animals_count)
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
        """Отримати інформацію про наступний рівень буста"""
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

# ========== ФУНКЦИИ ==========
def ensure_player(user_id: int, username: Optional[str]):
    cursor.execute("SELECT user_id FROM players WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO players (user_id, username, last_play, level, xp, coins, correct_streak, last_task_date, daily_questions, last_question_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username or "", datetime.now().isoformat(), 1, 0, 0, 0, "", 0, "")
        )
        conn.commit()
        log.info(f"Created new player: {user_id} ({username})")
    else:
        # Оновити username, якщо він змінився
        cursor.execute("UPDATE players SET username = ? WHERE user_id = ?", (username or "", user_id))
        conn.commit()

def update_last_play(user_id: int):
    cursor.execute("UPDATE players SET last_play = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    conn.commit()

def cleanup_inactive_players():
    now = datetime.now()
    cutoff = now - timedelta(days=INACTIVE_DAYS)
    cursor.execute("SELECT user_id, last_play FROM players")
    to_delete = []
    for uid, last_play in cursor.fetchall():
        if last_play:
            try:
                last_dt = datetime.fromisoformat(last_play)
            except Exception:
                last_dt = now - timedelta(days=INACTIVE_DAYS + 1)
            if last_dt < cutoff:
                to_delete.append(uid)
    for uid in to_delete:
        cursor.execute("DELETE FROM players WHERE user_id = ?", (uid,))
    if to_delete:
        conn.commit()
        log.info(f"Removed {len(to_delete)} inactive players")

def reset_daily_limits():
    """Скидання денного ліміту питань для всіх гравців"""
    today = datetime.now().date()
    cursor.execute("SELECT user_id, last_question_date FROM players WHERE daily_questions > 0")
    for user_id, last_date_str in cursor.fetchall():
        if last_date_str:
            try:
                last_date = datetime.fromisoformat(last_date_str).date()
                if last_date != today:
                    cursor.execute("UPDATE players SET daily_questions = 0 WHERE user_id = ?", (user_id,))
            except:
                cursor.execute("UPDATE players SET daily_questions = 0 WHERE user_id = ?", (user_id,))
    conn.commit()

def can_answer_questions(user_id: int) -> bool:
    """Перевірити, чи може гравець відповідати на питання"""
    today = datetime.now().date()
    cursor.execute("SELECT daily_questions, last_question_date FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        return True
    
    daily_questions, last_date_str = result
    if last_date_str:
        try:
            last_date = datetime.fromisoformat(last_date_str).date()
            if last_date != today:
                # Новий день - скидаємо ліміт
                cursor.execute("UPDATE players SET daily_questions = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                return True
        except:
            pass
    
    return daily_questions < DAILY_QUESTION_LIMIT

def increment_question_count(user_id: int):
    """Збільшити лічильник питань"""
    cursor.execute("UPDATE players SET daily_questions = daily_questions + 1, last_question_date = ? WHERE user_id = ?", 
                   (datetime.now().isoformat(), user_id))
    conn.commit()

def add_xp_and_reward(user_id: int, xp_gain: int, coins_gain: int = 0):
    ensure_player(user_id, "")
    cursor.execute("SELECT level, xp, coins, correct_streak FROM players WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        # Если игрока нет (маловероятно), создаем с начальными значениями
        return 1, xp_gain, coins_gain, 0
    
    level, xp, coins, streak = row
    
    # Исправляем возможные None значения
    if xp is None:
        xp = 0
    if coins is None:
        coins = 0
    if level is None:
        level = 1
    if streak is None:
        streak = 0
    
    xp += xp_gain
    leveled = 0
    while xp >= XP_PER_LEVEL:
        xp -= XP_PER_LEVEL
        level += 1
        leveled += 1
    coins += coins_gain
    
    cursor.execute(
        "UPDATE players SET level = ?, xp = ?, coins = ? WHERE user_id = ?",
        (level, xp, coins, user_id)
    )
    conn.commit()
    return level, xp, coins, leveled

def build_main_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎯 Играть", callback_data="menu_play"),
        InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"),
        InlineKeyboardButton("🎰 Рулетка", callback_data="menu_roulette"),
        InlineKeyboardButton("💰 Доходы", callback_data="menu_income"),
        InlineKeyboardButton("🏆 Таблица лидеров", callback_data="menu_leaderboard"),
        InlineKeyboardButton("📅 Задания дня", callback_data="menu_tasks")
    )
    return kb

def build_back_button(dest="main"):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"menu_back|{dest}"))
    return kb

def format_profile_row(user_row):
    if not user_row:
        return "👤 <b>Профиль</b>\n\n❌ Профиль не найден. Напиши /start"
    
    # Исправляем: теперь 6 элементов вместо 5
    if len(user_row) == 6:
        level, xp, coins, last_play, streak, daily_questions = user_row
    else:
        # Если старый формат (5 элементов)
        level, xp, coins, last_play, streak = user_row
        daily_questions = 0
    
    # Исправляем возможные None значения
    if level is None: level = 1
    if xp is None: xp = 0
    if coins is None: coins = 0
    if streak is None: streak = 0
    if daily_questions is None: daily_questions = 0
    
    try:
        lp = datetime.fromisoformat(last_play).strftime("%d.%m.%Y %H:%M") if last_play else "—"
    except Exception:
        lp = last_play or "—"
    
    # Форматируем валюту с символом ✯
    coins_formatted = f"{coins} ✯"
    
    return (
        f"👤 <b>Профиль</b>\n\n"
        f"🏆 Уровень: <b>{level}</b>\n"
        f"✨ Опыт: <b>{xp}/{XP_PER_LEVEL}</b>\n"
        f"💰 Монеты: <b>{coins_formatted}</b>\n"
        f"📅 Последняя игра: <b>{lp}</b>\n"
        f"🔥 Серия правильных ответов: {streak}\n"
        f"🎯 Вопросов сегодня: {daily_questions}/{DAILY_QUESTION_LIMIT}"
    )

async def send_random_question(chat_id: int, user_id: int, edit_message: Optional[types.Message] = None):
    if not QUESTIONS:
        text = "❗ Вопросы пока недоступны."
        if edit_message:
            await edit_message.edit_text(text)
        else:
            await bot.send_message(chat_id, text)
        return

    # Проверяем лимит вопросов
    if not can_answer_questions(user_id):
        text = (
            f"❌ <b>Лимит вопросов исчерпан!</b>\n\n"
            f"Вы уже ответили на {DAILY_QUESTION_LIMIT} вопросов сегодня.\n"
            f"Приходите завтра для новых вопросов! 🎯"
        )
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🎮 Главное меню", callback_data="menu_back|main"))
        
        if edit_message:
            await edit_message.edit_text(text, reply_markup=kb)
        else:
            await bot.send_message(chat_id, text, reply_markup=kb)
        return

    q_index = random.randrange(len(QUESTIONS))
    q = QUESTIONS[q_index]
    qtext = f"❓ <b>{q['question']}</b>\n\n"
    for i, opt in enumerate(q["options"], start=1):
        qtext += f"{i}. {opt}\n"

    kb = InlineKeyboardMarkup(row_width=2)
    for i, _opt in enumerate(q["options"], start=1):
        kb.add(InlineKeyboardButton(str(i), callback_data=f"ans|{i}|{q_index}"))

    # добавляем кнопку "Не знаю"
    kb.add(InlineKeyboardButton("❓ Не знаю", callback_data=f"ans|0|{q_index}"))
    # добавляем кнопку "Выйти в меню"
    kb.add(InlineKeyboardButton("🎮 Главное меню", callback_data="menu_back|main"))

    if edit_message:
        await edit_message.edit_text(qtext, reply_markup=kb)
    else:
        await bot.send_message(chat_id, qtext, reply_markup=kb)

# ========== ФУНКЦИИ РУЛЕТКИ ==========
def can_spin_roulette(user_id: int) -> bool:
    """Перевірити, чи може користувач крутити рулетку"""
    cursor.execute("SELECT coins FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        return False
    coins = result[0]
    return coins >= 4000

def charge_roulette_cost(user_id: int) -> bool:
    """Списати вартість прокруту"""
    if not can_spin_roulette(user_id):
        return False
    
    cursor.execute("UPDATE players SET coins = coins - 4000 WHERE user_id = ?", (user_id,))
    conn.commit()
    return True

def apply_roulette_prize(user_id: int, prize: dict):
    """Застосувати виграний приз"""
    prize_type = prize['type']
    value = prize['value']
    
    if prize_type == RoulettePrizeType.COINS:
        cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (value, user_id))
    elif prize_type == RoulettePrizeType.EXPERIENCE:
        add_xp_and_reward(user_id, xp_gain=value, coins_gain=0)
    elif prize_type == RoulettePrizeType.JACKPOT:
        cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (value, user_id))
    
    # Записати історію прокрутів
    cursor.execute(
        "INSERT INTO roulette_spins (user_id, prize_id, spin_date) VALUES (?, ?, ?)",
        (user_id, prize['id'], datetime.now().isoformat())
    )
    conn.commit()

def get_roulette_info_text():
    """Текст з інформацією про призи рулетки"""
    text = "🎰 <b>Інформація про рулетку</b>\n\n"
    text += f"💵 Вартість одного прокруту: <b>4000 ✯</b>\n\n"
    text += "<b>Можливі призи:</b>\n"
    
    for prize in roulette.prizes:
        percentage = prize['probability'] * 100
        if prize['type'] == RoulettePrizeType.COINS:
            text += f"• {prize['name']}: <b>{prize['value']} ✯</b> ({percentage:.1f}%)\n"
        elif prize['type'] == RoulettePrizeType.EXPERIENCE:
            text += f"• {prize['name']}: <b>{prize['value']} досвіду</b> ({percentage:.1f}%)\n"
        elif prize['type'] == RoulettePrizeType.FREE_SPIN:
            text += f"• {prize['name']}: <b>{prize['value']} безкоштовний спін</b> ({percentage:.1f}%)\n"
        elif prize['type'] == RoulettePrizeType.JACKPOT:
            text += f"• {prize['name']}: <b>{prize['value']} ✯</b> ({percentage:.1f}%)\n"
    
    return text

# ========== ФУНКЦІЇ ФЕРМИ ТА TAP GAME ==========
def get_user_farm(user_id: int) -> dict:
    """Отримати інформацію про ферму користувача"""
    cursor.execute("SELECT animals, last_collect_time, total_earned FROM user_farm WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        # Створити запис, якщо немає
        cursor.execute(
            "INSERT INTO user_farm (user_id, animals, last_collect_time) VALUES (?, ?, ?)",
            (user_id, 0, datetime.now().isoformat())
        )
        conn.commit()
        return {"animals": 0, "last_collect_time": datetime.now().isoformat(), "total_earned": 0}
    
    animals, last_collect_time, total_earned = result
    return {
        "animals": animals,
        "last_collect_time": last_collect_time,
        "total_earned": total_earned or 0
    }

def get_user_tap_stats(user_id: int) -> dict:
    """Отримати статистику тап-гейму"""
    cursor.execute("SELECT boost_level, tap_income, total_taps, total_earned FROM user_tap_boost WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        # Створити запис, якщо немає
        cursor.execute(
            "INSERT INTO user_tap_boost (user_id, boost_level, tap_income) VALUES (?, ?, ?)",
            (user_id, 1, 1.24)
        )
        conn.commit()
        return {"boost_level": 1, "tap_income": 1.24, "total_taps": 0, "total_earned": 0}
    
    boost_level, tap_income, total_taps, total_earned = result
    return {
        "boost_level": boost_level,
        "tap_income": tap_income,
        "total_taps": total_taps or 0,
        "total_earned": total_earned or 0
    }

def collect_farm_income(user_id: int) -> dict:
    """Зібрати дохід з ферми (ТЕПЕР ТІЛЬКИ ПРИ НАТИСКАННІ КНОПКИ)"""
    farm_data = get_user_farm(user_id)
    animals = farm_data["animals"]
    
    if animals == 0:
        return {"success": False, "message": "У вас немає тварин на фермі!"}
    
    last_collect = datetime.fromisoformat(farm_data["last_collect_time"])
    now = datetime.now()
    hours_passed = (now - last_collect).total_seconds() / 3600
    
    # Мінімальний час між зборами - 1 година
    if hours_passed < 1:
        time_left = 60 - int((hours_passed * 60))  # хвилин залишилось
        return {"success": False, "message": f"Ще рано збирати дохід! Приходьте через {time_left} хв."}
    
    earnings = FarmManager.calculate_earnings(animals, hours_passed)
    
    # Оновити баланс та час збору
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (earnings, user_id))
    cursor.execute(
        "UPDATE user_farm SET last_collect_time = ?, total_earned = total_earned + ? WHERE user_id = ?",
        (now.isoformat(), earnings, user_id)
    )
    conn.commit()
    
    return {"success": True, "earnings": earnings, "hours_passed": hours_passed}

def get_available_farm_income(user_id: int) -> dict:
    """Отримати інформацію про доступний для збору дохід (без збору)"""
    farm_data = get_user_farm(user_id)
    animals = farm_data["animals"]
    
    if animals == 0:
        return {"available": False, "message": "Немає тварин"}
    
    last_collect = datetime.fromisoformat(farm_data["last_collect_time"])
    now = datetime.now()
    hours_passed = (now - last_collect).total_seconds() / 3600
    
    earnings = FarmManager.calculate_earnings(animals, hours_passed)
    
    can_collect = hours_passed >= 1
    time_left = max(0, 60 - int((hours_passed * 60))) if hours_passed < 1 else 0
    
    return {
        "available": can_collect,
        "earnings": earnings,
        "hours_passed": hours_passed,
        "time_left": time_left,
        "animals": animals,
        "income_per_hour": FarmManager.get_animal_income(animals)
    }

def process_tap(user_id: int) -> dict:
    """Обробити тап (клік)"""
    tap_stats = get_user_tap_stats(user_id)
    income = tap_stats["tap_income"]
    
    # Додати монети
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (income, user_id))
    
    # Оновити статистику
    cursor.execute(
        "UPDATE user_tap_boost SET total_taps = total_taps + 1, total_earned = total_earned + ? WHERE user_id = ?",
        (income, user_id)
    )
    conn.commit()
    
    return {"income": income, "new_balance": get_user_coins(user_id)}

def buy_animal(user_id: int) -> dict:
    """Купити тварину"""
    farm_data = get_user_farm(user_id)
    current_animals = farm_data["animals"]
    
    if current_animals >= Shop.MAX_ANIMALS:
        return {"success": False, "message": f"Досягнуто максимум тварин ({Shop.MAX_ANIMALS})!"}
    
    user_coins = get_user_coins(user_id)
    if user_coins < Shop.ANIMAL_PRICE:
        return {"success": False, "message": "Недостатньо монет!"}
    
    # Списати кошти та додати тварину
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (Shop.ANIMAL_PRICE, user_id))
    cursor.execute("UPDATE user_farm SET animals = animals + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    
    return {"success": True, "message": f"Тваринку куплено! Тепер у вас {current_animals + 1} тварин."}

def buy_tap_boost(user_id: int) -> dict:
    """Купити покращення для тап-гейму"""
    tap_stats = get_user_tap_stats(user_id)
    current_level = tap_stats["boost_level"]
    
    next_boost = TapGame.get_next_boost_level(current_level)
    if not next_boost:
        return {"success": False, "message": "У вас максимальний рівень буста!"}
    
    user_coins = get_user_coins(user_id)
    if user_coins < next_boost["price"]:
        return {"success": False, "message": "Недостатньо монет!"}
    
    # Списати кошти та покращити буст
    cursor.execute("UPDATE players SET coins = coins - ? WHERE user_id = ?", (next_boost["price"], user_id))
    cursor.execute(
        "UPDATE user_tap_boost SET boost_level = ?, tap_income = ? WHERE user_id = ?",
        (next_boost["level"], next_boost["income"], user_id)
    )
    conn.commit()
    
    return {
        "success": True, 
        "message": f"Буст покращено до {next_boost['level']} рівня! Дохід за тап: {next_boost['income']} ✯",
        "new_level": next_boost["level"],
        "new_income": next_boost["income"]
    }

def get_user_coins(user_id: int) -> int:
    """Отримати баланс користувача"""
    cursor.execute("SELECT coins FROM players WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def build_income_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🏠 Пассивная ферма", callback_data="income_farm"),
        InlineKeyboardButton("👆 Tap to Money", callback_data="income_tap"),
        InlineKeyboardButton("🛍️ Магазин", callback_data="income_shop"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    return kb

# ========== ХЭНДЛЕРЫ ==========
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    cleanup_inactive_players()
    reset_daily_limits()  # Скидаємо денні ліміти при старті
    ensure_player(message.from_user.id, message.from_user.username or message.from_user.full_name)
    update_last_play(message.from_user.id)
    await message.answer(f"Привет, <b>{message.from_user.first_name}</b>! 🎮\nВыбери действие в меню:", reply_markup=build_main_menu())

@dp.message_handler(commands=["profile"])
async def cmd_profile(message: types.Message):
    ensure_player(message.from_user.id, message.from_user.username or message.from_user.full_name)
    update_last_play(message.from_user.id)
    cursor.execute("SELECT level, xp, coins, last_play, correct_streak, daily_questions FROM players WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    await message.answer(format_profile_row(user), reply_markup=build_back_button("main"))

@dp.message_handler(commands=["leaderboard"])
async def cmd_leaderboard(message: types.Message):
    cleanup_inactive_players()
    update_last_play(message.from_user.id)
    cursor.execute("SELECT username, level, xp FROM players ORDER BY level DESC, xp DESC LIMIT 10")
    rows = cursor.fetchall()
    text = "🏆 <b>Топ игроков</b>\n\n"
    for i, (username, level, xp) in enumerate(rows, start=1):
        display = f"@{username}" if username else f"Игрок {i}"
        text += f"{i}. {display} — {level} lvl ({xp} XP)\n"
    await message.answer(text, reply_markup=build_back_button("main"))

@dp.callback_query_handler(lambda c: c.data == "menu_play")
async def cb_menu_play(call: types.CallbackQuery):
    await call.answer()
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    update_last_play(call.from_user.id)
    await send_random_question(call.message.chat.id, call.from_user.id, edit_message=call.message)

@dp.callback_query_handler(lambda c: c.data.startswith("ans|"))
async def cb_answer(call: types.CallbackQuery):
    await call.answer()
    try:
        _, chosen_s, qindex_s = call.data.split("|")
        chosen = int(chosen_s)
        q_index = int(qindex_s)
    except Exception:
        await call.message.edit_text("Произошла ошибка при обработке ответа.")
        return

    if q_index < 0 or q_index >= len(QUESTIONS):
        await send_random_question(call.message.chat.id, call.from_user.id, edit_message=call.message)
        return

    # Проверяем лимит вопросов
    if not can_answer_questions(call.from_user.id):
        text = (
            f"❌ <b>Лимит вопросов исчерпан!</b>\n\n"
            f"Вы уже ответили на {DAILY_QUESTION_LIMIT} вопросов сегодня.\n"
            f"Приходите завтра для новых вопросов! 🎯"
        )
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🎮 Главное меню", callback_data="menu_back|main"))
        await call.message.edit_text(text, reply_markup=kb)
        return

    q = QUESTIONS[q_index]
    correct = int(q.get("answer", 0))
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    update_last_play(call.from_user.id)

    # Увеличиваем счетчик вопросов
    increment_question_count(call.from_user.id)

    # вариант "Не знаю"
    if chosen == 0:
        cursor.execute("UPDATE players SET correct_streak = 0 WHERE user_id = ?", (call.from_user.id,))
        conn.commit()
        correct_text = q["options"][correct - 1] if correct else "—"
        text = f"😅 <b>Правильный ответ:</b> {correct_text}\nНе переживай — следующий вопрос ждёт тебя."
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🎮 Главное меню", callback_data="menu_back|main"))
        await call.message.edit_text(text, reply_markup=kb)
        await asyncio.sleep(1.5)
        await send_random_question(call.message.chat.id, call.from_user.id, edit_message=call.message)
        return

    # проверка ответа
    if chosen == correct:
        res = add_xp_and_reward(call.from_user.id, xp_gain=15, coins_gain=5)
        cursor.execute("UPDATE players SET correct_streak = correct_streak + 1 WHERE user_id = ?", (call.from_user.id,))
        conn.commit()
        streak = cursor.execute("SELECT correct_streak FROM players WHERE user_id = ?", (call.from_user.id,)).fetchone()[0]
        bonus_text = ""
        if streak % 5 == 0:
            add_xp_and_reward(call.from_user.id, xp_gain=50, coins_gain=25)
            bonus_text = f"\n🔥 Бонус за серию {streak}: +50 XP, +25 ✯"
        level, xp, coins, _ = res
        
        # Форматируем валюту с символом ✯
        coins_formatted = f"{coins} ✯"
        
        text = f"✅ <b>Правильно!</b>\n+15 XP, +5 ✯\n🏆 Уровень: {level} ({xp}/{XP_PER_LEVEL})\n💰 Баланс: {coins_formatted}{bonus_text}"
        await call.message.edit_text(text)
        await asyncio.sleep(1.2)
        await send_random_question(call.message.chat.id, call.from_user.id, edit_message=call.message)
    else:
        cursor.execute("UPDATE players SET correct_streak = 0 WHERE user_id = ?", (call.from_user.id,))
        conn.commit()
        correct_text = q["options"][correct - 1] if correct else "—"
        text = f"❌ <b>Неправильно!</b>\nПравильный ответ: {correct_text}"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🎮 Главное меню", callback_data="menu_back|main"))
        await call.message.edit_text(text, reply_markup=kb)
        await asyncio.sleep(1.5)
        await send_random_question(call.message.chat.id, call.from_user.id, edit_message=call.message)

@dp.callback_query_handler(lambda c: c.data.startswith("menu_back|"))
async def cb_menu_back(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("🎮 Главное меню\nВыбери действие:", reply_markup=build_main_menu())

@dp.callback_query_handler(lambda c: c.data == "menu_profile")
async def cb_menu_profile(call: types.CallbackQuery):
    await call.answer()
    cursor.execute("SELECT level, xp, coins, last_play, correct_streak, daily_questions FROM players WHERE user_id = ?", (call.from_user.id,))
    user = cursor.fetchone()
    await call.message.edit_text(format_profile_row(user), reply_markup=build_back_button("main"))

@dp.callback_query_handler(lambda c: c.data == "menu_leaderboard")
async def cb_menu_leaderboard(call: types.CallbackQuery):
    await call.answer()
    cursor.execute("SELECT username, level, xp FROM players ORDER BY level DESC, xp DESC LIMIT 10")
    rows = cursor.fetchall()
    text = "🏆 <b>Топ игроков</b>\n\n"
    for i, (username, level, xp) in enumerate(rows, start=1):
        display = f"@{username}" if username else f"Игрок {i}"
        text += f"{i}. {display} — {level} lvl ({xp} XP)\n"
    await call.message.edit_text(text, reply_markup=build_back_button("main"))

@dp.callback_query_handler(lambda c: c.data == "menu_tasks")
async def cb_menu_tasks(call: types.CallbackQuery):
    await call.answer()
    today = datetime.now().date()
    cursor.execute("SELECT last_task_date FROM players WHERE user_id = ?", (call.from_user.id,))
    last_date_str = cursor.fetchone()[0] or ""
    last_date = datetime.fromisoformat(last_date_str).date() if last_date_str else None
    new_day = last_date != today
    tasks_text = (
        "📋 <b>Задания дня</b>\n\n"
        "• Ответь на 3 вопроса — +30 XP\n"
        "• Вернись завтра — +20 XP\n"
        "• 5 правильных подряд — бонус +50 XP\n\n"
        "Нажми «Играть», чтобы начать викторину."
    )
    if new_day:
        cursor.execute("UPDATE players SET last_task_date = ? WHERE user_id = ?", (today.isoformat(), call.from_user.id))
        conn.commit()
    await call.message.edit_text(tasks_text, reply_markup=build_back_button("main"))

#INFO
@dp.message_handler(commands=['info'])
async def cmd_info(message: types.Message):
    text = (
        '📍 <b>Информация о боте</b> 📍\n\n'
        '✨ <b>Что сейчас есть в боте:</b>\n\n'
        '• <b>🎯 Викторина</b> — отвечай на вопросы и получай опыт и монеты ✯\n'
        f'• <b>📊 Лимит:</b> {DAILY_QUESTION_LIMIT} вопросов в день\n\n'
        '• <b>🎰 Рулетка</b> — крути за 4000 ✯ и выигрывай призы\n'
        '• <b>💰 Система доходов</b> — пассивный и активный заработок\n'
        '• <b>🏠 Ферма</b> — покупай животных и собирай доход каждый час\n'
        '• <b>👆 Tap Game</b> — нажимай и получай монеты, улучшай бусты\n'
        '• <b>🛍️ Магазин</b> — покупай животных и улучшения\n\n'
        '• <b>👤 Профиль</b> — твоя статистика и прогресс\n'
        '• <b>🏆 Рейтинг</b> — таблица лидеров\n'
        '• <b>📅 Задания</b> — ежедневные цели\n\n'
        '<b>💫 Основная валюта:</b> ✯ (звездочки)\n\n'
        '<code>Версия: 2.0.1</code>\n\n'
        '<b>Связь с разработчиком:</b>\n'
        '<a href="https://t.me/+q7SmgHCfUBpkOWJi">≥ Наша группа ≤</a>\n'
        '<a href="https://t.me/+EfXBYlQYHl43N2E6">≥ Наш канал ≤</a>'
    )
    await message.answer(text)

# ========== ХЕНДЛЕРИ РУЛЕТКИ ==========
@dp.callback_query_handler(lambda c: c.data == "menu_roulette")
async def cb_menu_roulette(call: types.CallbackQuery):
    await call.answer()
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    
    cursor.execute("SELECT coins FROM players WHERE user_id = ?", (call.from_user.id,))
    coins = cursor.fetchone()[0]
    
    # Форматируем валюту с символом ✯
    coins_formatted = f"{coins} ✯"
    
    text = (
        f"🎰 <b>Рулетка удачі</b> 🎰\n\n"
        f"💵 Твої монети: <b>{coins_formatted}</b>\n"
        f"🎯 Вартість прокруту: <b>4000 ✯</b>\n\n"
        f"Крути рулетку та виграй круті призи!\n"
        f"Від скромних монет до великого джекпоту! 🎁"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎰 Крутити рулетку (4000 ✯)", callback_data="roulette_spin"),
        InlineKeyboardButton("📊 Інформація про призи", callback_data="roulette_info"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "roulette_info")
async def cb_roulette_info(call: types.CallbackQuery):
    await call.answer()
    text = get_roulette_info_text()
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎰 До рулетки", callback_data="menu_roulette"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "roulette_spin")
async def cb_roulette_spin(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    ensure_player(user_id, call.from_user.username or call.from_user.full_name)
    
    if not can_spin_roulette(user_id):
        await call.answer("Недостатньо монет для прокруту рулетки!", show_alert=True)
        return
    
    # Списати кошти
    charge_roulette_cost(user_id)
    
    # Прокрутити рулетку
    prize = roulette.spin()
    
    # Застосувати приз
    apply_roulette_prize(user_id, prize)
    
    # Оновити дані гравця
    cursor.execute("SELECT coins FROM players WHERE user_id = ?", (user_id,))
    new_coins = cursor.fetchone()[0]
    
    # Форматируем валюту с символом ✯
    new_coins_formatted = f"{new_coins} ✯"
    
    # Створити красивe повідомлення про виграш
    prize_text = ""
    if prize['type'] == RoulettePrizeType.COINS:
        prize_text = f"🎉 Ти виграв <b>{prize['value']} ✯</b>!"
    elif prize['type'] == RoulettePrizeType.EXPERIENCE:
        prize_text = f"⭐ Ти виграв <b>{prize['value']} досвіду</b>!"
    elif prize['type'] == RoulettePrizeType.FREE_SPIN:
        prize_text = f"🎫 Ти виграв <b>безкоштовний спін</b>!"
    elif prize['type'] == RoulettePrizeType.JACKPOT:
        prize_text = f"🎯 <b>ДЖЕКПОТ!</b> Ти виграв <b>{prize['value']} ✯</b>! 🎯"
    
    text = (
        f"🎰 <b>Результат рулетки</b> 🎰\n\n"
        f"{prize_text}\n\n"
        f"💵 Залишок монет: <b>{new_coins_formatted}</b>\n"
        f"🎁 Приз: {prize['name']}"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎰 Крутити ще раз", callback_data="roulette_spin"),
        InlineKeyboardButton("📊 Інформація", callback_data="roulette_info"),
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_back|main")
    )
    
    await call.message.edit_text(text, reply_markup=kb)

# ========== ХЕНДЛЕРИ ДОХОДІВ ==========
@dp.callback_query_handler(lambda c: c.data == "menu_income")
async def cb_menu_income(call: types.CallbackQuery):
    await call.answer()
    ensure_player(call.from_user.id, call.from_user.username or call.from_user.full_name)
    
    user_coins = get_user_coins(call.from_user.id)
    farm_data = get_user_farm(call.from_user.id)
    tap_stats = get_user_tap_stats(call.from_user.id)
    
    # Форматируем валюту с символом ✯
    coins_formatted = f"{user_coins} ✯"
    
    text = (
        f"💰 <b>Система доходов</b> 💰\n\n"
        f"💵 Ваш баланс: <b>{coins_formatted}</b>\n\n"
        f"🏠 <b>Ферма:</b> {farm_data['animals']} тварин\n"
        f"👆 <b>Tap Game:</b> {tap_stats['boost_level']} ур. ({tap_stats['tap_income']} ✯/тап)\n\n"
        f"Оберіть спосіб заробітку:"
    )
    
    await call.message.edit_text(text, reply_markup=build_income_menu())

@dp.callback_query_handler(lambda c: c.data == "income_farm")
async def cb_income_farm(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    farm_info = get_available_farm_income(user_id)
    
    if farm_info["animals"] == 0:
        text = (
            "🏠 <b>Пассивная ферма</b>\n\n"
            "❌ У вас нет животных на ферме!\n\n"
            "🛍️ Посетите магазин чтобы приобрести животных.\n"
            "💰 Каждое животное приносит 11.25 ✯ в час!"
        )
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🛍️ В магазин", callback_data="income_shop"))
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    else:
        if farm_info["available"]:
            text = (
                f"🏠 <b>Пассивная ферма</b>\n\n"
                f"💰 <b>Доступно для сбора: {farm_info['earnings']} ✯!</b>\n"
                f"⏰ Накоплено за: {farm_info['hours_passed']:.1f} часов\n\n"
                f"🐷 Животных: <b>{farm_info['animals']}</b>\n"
                f"📈 Доход в час: <b>{farm_info['income_per_hour']} ✯</b>\n"
                f"💵 Всего заработано: <b>{get_user_farm(user_id)['total_earned']} ✯</b>"
            )
            
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("💰 Забрать деньги", callback_data="farm_collect"))
            kb.add(InlineKeyboardButton("🛍️ Купить животных", callback_data="shop_animals"))
            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
        else:
            text = (
                f"🏠 <b>Пассивная ферма</b>\n\n"
                f"⏳ Доход еще копится...\n"
                f"🕐 До сбора: <b>{farm_info['time_left']} минут</b>\n"
                f"💰 Накоплено: ~{farm_info['earnings']} ✯\n\n"
                f"🐷 Животных: <b>{farm_info['animals']}</b>\n"
                f"📈 Доход в час: <b>{farm_info['income_per_hour']} ✯</b>\n"
                f"💵 Всего заработано: <b>{get_user_farm(user_id)['total_earned']} ✯</b>"
            )
            
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔄 Обновить", callback_data="income_farm"))
            kb.add(InlineKeyboardButton("🛍️ Купить животных", callback_data="shop_animals"))
            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "farm_collect")
async def cb_farm_collect(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    # Собираем доход
    collect_result = collect_farm_income(user_id)
    
    if collect_result["success"]:
        # Получаем обновленную информацию о ферме
        farm_data = get_user_farm(user_id)
        
        text = (
            f"🏠 <b>Пассивная ферма</b>\n\n"
            f"✅ <b>Успешно собрано: {collect_result['earnings']} ✯!</b> 🎉\n"
            f"⏰ За период: {collect_result['hours_passed']:.1f} часов\n\n"
            f"🐷 Животных: <b>{farm_data['animals']}</b>\n"
            f"📈 Доход в час: <b>{FarmManager.get_animal_income(farm_data['animals'])} ✯</b>\n"
            f"💵 Всего заработано: <b>{farm_data['total_earned']} ✯</b>"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔄 Обновить", callback_data="income_farm"))
        kb.add(InlineKeyboardButton("🛍️ Купить животных", callback_data="shop_animals"))
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
        
        await call.message.edit_text(text, reply_markup=kb)
    else:
        await call.answer(collect_result["message"], show_alert=True)
        # Обновляем ферму чтобы показать актуальное состояние
        await cb_income_farm(call)

@dp.callback_query_handler(lambda c: c.data == "income_tap")
async def cb_income_tap(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    tap_stats = get_user_tap_stats(user_id)
    
    text = (
        f"👆 <b>Tap to Money</b> 👆\n\n"
        f"💵 Нажимай на кнопку и получай монеты!\n"
        f"🎯 Текущий доход за тап: <b>{tap_stats['tap_income']} ✯</b>\n"
        f"📊 Уровень буста: <b>{tap_stats['boost_level']}</b>\n"
        f"👆 Всего тапов: <b>{tap_stats['total_taps']}</b>\n"
        f"💰 Всего заработано: <b>{tap_stats['total_earned']} ✯</b>"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("👆 TAP!", callback_data="tap_click"))
    kb.add(InlineKeyboardButton("🛍️ Улучшить буст", callback_data="shop_boosts"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "tap_click")
async def cb_tap_click(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    tap_result = process_tap(user_id)
    
    # Оновити статистику після тапу
    tap_stats = get_user_tap_stats(user_id)
    
    text = (
        f"👆 <b>+{tap_result['income']} ✯!</b> 🎉\n\n"
        f"💵 Новый баланс: <b>{tap_result['new_balance']} ✯</b>\n"
        f"🎯 Доход за тап: <b>{tap_stats['tap_income']} ✯</b>\n"
        f"📊 Уровень буста: <b>{tap_stats['boost_level']}</b>\n"
        f"👆 Всего тапов: <b>{tap_stats['total_taps']}</b>"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("👆 TAP!", callback_data="tap_click"))
    kb.add(InlineKeyboardButton("🛍️ Улучшить буст", callback_data="shop_boosts"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "income_shop")
async def cb_income_shop(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    user_coins = get_user_coins(user_id)
    farm_data = get_user_farm(user_id)
    tap_stats = get_user_tap_stats(user_id)
    next_boost = TapGame.get_next_boost_level(tap_stats["boost_level"])
    
    # Форматируем валюту с символом ✯
    coins_formatted = f"{user_coins} ✯"
    
    text = (
        f"🛍️ <b>Магазин доходов</b> 🛍️\n\n"
        f"💵 Ваш баланс: <b>{coins_formatted}</b>\n\n"
        f"<b>Доступные товары:</b>\n\n"
        f"🐷 <b>Животное для фермы</b>\n"
        f"💰 Цена: {Shop.ANIMAL_PRICE} ✯\n"
        f"📈 Доход: 11.25 ✯/час\n"
        f"🎯 Куплено: {farm_data['animals']}/{Shop.MAX_ANIMALS}\n\n"
    )
    
    if next_boost:
        text += (
            f"⚡ <b>Буст для Tap Game (Ур. {next_boost['level']})</b>\n"
            f"💰 Цена: {next_boost['price']} ✯\n"
            f"📈 Новый доход: {next_boost['income']} ✯/тап\n"
        )
    else:
        text += f"⚡ <b>Буст для Tap Game</b> - Максимальный уровень достигнут! 🎉\n"
    
    kb = InlineKeyboardMarkup(row_width=1)
    if farm_data["animals"] < Shop.MAX_ANIMALS:
        kb.add(InlineKeyboardButton(f"🐷 Купить животное ({Shop.ANIMAL_PRICE} ✯)", callback_data="shop_buy_animal"))
    if next_boost:
        kb.add(InlineKeyboardButton(f"⚡ Улучшить буст ({next_boost['price']} ✯)", callback_data="shop_buy_boost"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_income"))
    
    await call.message.edit_text(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "shop_buy_animal")
async def cb_shop_buy_animal(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    result = buy_animal(user_id)
    
    if result["success"]:
        await call.answer(result["message"], show_alert=True)
        # Повернутися в магазин
        await cb_income_shop(call)
    else:
        await call.answer(result["message"], show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "shop_buy_boost")
async def cb_shop_buy_boost(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    result = buy_tap_boost(user_id)
    
    if result["success"]:
        await call.answer(result["message"], show_alert=True)
        # Повернутися в магазин
        await cb_income_shop(call)
    else:
        await call.answer(result["message"], show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "shop_animals")
async def cb_shop_animals(call: types.CallbackQuery):
    await call.answer()
    # Просто переходим в магазин
    await cb_income_shop(call)

@dp.callback_query_handler(lambda c: c.data == "shop_boosts")
async def cb_shop_boosts(call: types.CallbackQuery):
    await call.answer()
    # Просто переходим в магазин
    await cb_income_shop(call)

# ========== ФОН ==========
async def periodic_cleanup():
    while True:
        try:
            cleanup_inactive_players()
            reset_daily_limits()  # Скидуємо денні ліміти кожен день
        except Exception:
            log.exception("periodic_cleanup")
        await asyncio.sleep(60 * 60 * 24)  # Раз в день

# ========== СТАРТ ==========
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(periodic_cleanup())
    executor.start_polling(dp, skip_updates=True)