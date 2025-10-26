# website.py
import asyncio
import aiohttp
from aiohttp import web
import sqlite3
import json
import secrets
from datetime import datetime, timedelta
import os
import socket
import requests

# Используем существующее подключение к базе
DB_PATH = "data.db"

def get_server_url():
    """Автоматически определяет URL сервера"""
    try:
        # Пробуем получить внешний IP
        external_ip = requests.get('https://api.ipify.org', timeout=5).text
        return f"http://{external_ip}:8080"
    except:
        try:
            # Если не получилось, получаем локальный IP
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            return f"http://{local_ip}:8080"
        except:
            return "http://localhost:8080"

class WebsiteServer:
    def __init__(self):
        self.app = web.Application()
        self.setup_routes()
        self.auth_tokens = {}  # token -> user_id
        self.setup_database()

    def setup_database(self):
        """Создаем таблицу для веб-сессий если её нет"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_date TEXT NOT NULL,
                last_active TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES players (user_id)
            )
        """)
        conn.commit()
        conn.close()

    def setup_routes(self):
        """Настраиваем маршруты"""
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/api/auth', self.handle_auth)
        self.app.router.add_get('/api/user_data', self.handle_user_data)
        self.app.router.add_post('/api/tap', self.handle_tap)
        self.app.router.add_post('/api/sync', self.handle_sync)
        # Убрал статическую папку, так как она не нужна сейчас

    async def handle_index(self, request):
        """Главная страница"""
        # Читаем index.html и отдаем его
        try:
            with open('index.html', 'r', encoding='utf-8') as f:
                content = f.read()
            return web.Response(text=content, content_type='text/html')
        except FileNotFoundError:
            return web.Response(text='Файл index.html не найден', status=404)

    async def handle_auth(self, request):
        """Генерация кода для аутентификации"""
        user_id = request.query.get('user_id')
        if not user_id:
            return web.json_response({'error': 'No user_id'}, status=400)
        
        try:
            user_id = int(user_id)
        except ValueError:
            return web.json_response({'error': 'Invalid user_id'}, status=400)
        
        # Генерируем токен
        token = secrets.token_hex(16)
        self.auth_tokens[token] = user_id
        
        # Сохраняем в базу
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO web_sessions 
            (token, user_id, created_date, last_active) 
            VALUES (?, ?, ?, ?)
        """, (token, user_id, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        return web.json_response({'token': token})

    def get_user_data(self, user_id):
        """Получаем данные пользователя из базы"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT username, level, coins, role, total_taps, has_passport 
            FROM players WHERE user_id = ?
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result:
            return None
            
        username, level, coins, role, total_taps, has_passport = result
        
        # Получаем доходы
        farm_income = self.get_farm_income(user_id)
        estate_income = self.get_real_estate_income(user_id)
        business_income = self.get_business_income(user_id)
        total_income = farm_income + estate_income + business_income
        
        # Получаем бизнесы
        businesses = self.get_user_businesses(user_id)
        
        conn.close()
        
        return {
            'user_id': user_id,
            'username': username,
            'level': level,
            'coins': coins,
            'role': role,
            'total_taps': total_taps,
            'has_passport': bool(has_passport),
            'incomes': {
                'farm': farm_income,
                'estate': estate_income,
                'business': business_income,
                'total': total_income
            },
            'businesses': businesses
        }

    def get_farm_income(self, user_id):
        """Доход с фермы"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(income * count) FROM farm_animals WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        income = result[0] if result and result[0] else 0
        conn.close()
        return income

    def get_real_estate_income(self, user_id):
        """Доход с недвижимости"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(income) FROM user_real_estate WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        income = result[0] if result and result[0] else 0
        conn.close()
        return income

    def get_business_income(self, user_id):
        """Доход с бизнесов"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(income) FROM user_businesses WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        income = result[0] if result and result[0] else 0
        conn.close()
        return income

    def get_user_businesses(self, user_id):
        """Список бизнесов пользователя"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ub.business_name, ub.level, ub.income, bt.name 
            FROM user_businesses ub 
            JOIN business_types bt ON ub.business_type = bt.id 
            WHERE ub.user_id = ?
        """, (user_id,))
        businesses = []
        for name, level, income, type_name in cursor.fetchall():
            businesses.append({
                'name': name,
                'level': level,
                'income': income,
                'type': type_name
            })
        conn.close()
        return businesses

    async def handle_user_data(self, request):
        """Получение данных пользователя"""
        token = request.query.get('token')
        if not token or token not in self.auth_tokens:
            return web.json_response({'error': 'Invalid token'}, status=401)
        
        user_id = self.auth_tokens[token]
        user_data = self.get_user_data(user_id)
        
        if not user_data:
            return web.json_response({'error': 'User not found'}, status=404)
            
        return web.json_response(user_data)

    async def handle_tap(self, request):
        """Обработка тапов с сайта"""
        try:
            data = await request.json()
        except:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
            
        token = data.get('token')
        
        if not token or token not in self.auth_tokens:
            return web.json_response({'error': 'Invalid token'}, status=401)
        
        user_id = self.auth_tokens[token]
        
        # Обновляем баланс и тапы в базе
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Получаем текущий уровень тап-буста
        cursor.execute("SELECT tap_boost_level FROM players WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        tap_income = 1
        if result and result[0]:
            tap_income = result[0]
        
        # Обновляем баланс и тапы
        cursor.execute("""
            UPDATE players 
            SET coins = coins + ?, total_taps = total_taps + 1, daily_taps = daily_taps + 1 
            WHERE user_id = ?
        """, (tap_income, user_id))
        
        conn.commit()
        
        # Получаем новый баланс
        cursor.execute("SELECT coins FROM players WHERE user_id = ?", (user_id,))
        new_coins = cursor.fetchone()[0]
        
        conn.close()
        
        return web.json_response({
            'success': True, 
            'coins_earned': tap_income,
            'new_balance': new_coins
        })

    async def handle_sync(self, request):
        """Синхронизация данных (polling)"""
        token = request.query.get('token')
        if not token or token not in self.auth_tokens:
            return web.json_response({'error': 'Invalid token'}, status=401)
        
        user_id = self.auth_tokens[token]
        user_data = self.get_user_data(user_id)
        
        return web.json_response(user_data)

async def start(self):
    """Запуск сервера"""
    runner = web.AppRunner(self.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    server_url = get_server_url()
    print("🌐 Website server started!")
    print(f"📱 Сайт доступен по ссылке: {server_url}")
    print("🔑 Получи код доступа в боте командой /website")

# Интеграция с ботом
def setup_website_in_bot(dp):
    """Добавляем команды в бота для работы с сайтом"""
    from aiogram import types
    
    @dp.message_handler(commands=['website', 'site'])
    async def cmd_website(message: types.Message):
        """Генерация кода для доступа к сайту"""
        user_id = message.from_user.id
        
        # Создаем сессию веб-сервера
        from website import website_server
        token = secrets.token_hex(16)
        website_server.auth_tokens[token] = user_id
        
        # Сохраняем в базу
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO web_sessions 
            (token, user_id, created_date, last_active) 
            VALUES (?, ?, ?, ?)
        """, (token, user_id, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        server_url = get_server_url()
        
        await message.answer(
            f"🌐 <b>Доступ к веб-сайту</b>\n\n"
            f"🔑 <b>Ваш код доступа:</b> <code>{token}</code>\n\n"
            f"📱 <b>Перейдите на сайт:</b>\n"
            f"{site_url}\n\n"
            f"💡 <b>Инструкция:</b>\n"
            f"1. Откройте сайт в браузере\n"
            f"2. Введите код доступа\n"
            f"3. Наслаждайтесь игрой!\n\n"
            f"⚡ <b>Особенности:</b>\n"
            f"• Красивый адаптивный дизайн\n"
            f"• Игры недоступные в боте\n"
            f"• Мгновенная синхронизация\n"
            f"• Темная тема с фиолетовыми акцентами",
            parse_mode='HTML'
        )

# Глобальная переменная для сервера
website_server = None

# Запуск сервера
async def start_website_server():
    global website_server
    website_server = WebsiteServer()
    await website_server.start()
    return website_server

if __name__ == "__main__":
    asyncio.run(start_website_server())
