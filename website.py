# website.py
import asyncio
import aiohttp
from aiohttp import web
import sqlite3
import json
import secrets
from datetime import datetime, timedelta
import os

# Используем существующее подключение к базе
DB_PATH = "data.db"

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
        
        # ДОБАВЛЯЕМ новые роуты для поиска и топа
        self.app.router.add_get('/api/top_players', self.handle_top_players)
        self.app.router.add_get('/api/search_players', self.handle_search_players)

    async def handle_index(self, request):
        """Главная страница"""
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

    # ДОБАВЛЯЕМ новые методы для поиска и топа
    async def handle_top_players(self, request):
        """Топ игроков"""
        try:
            top_type = request.query.get('type', 'coins')
            limit = int(request.query.get('limit', 20))
            
            # Получаем топ из базы данных
            players = await self.get_top_players(top_type, limit)
            
            return web.json_response({
                'players': players,
                'type': top_type
            })
            
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_search_players(self, request):
        """Поиск игроков"""
        try:
            username = request.query.get('username')
            user_id = request.query.get('user_id')
            
            if username:
                players = await self.search_players_by_username(username)
            elif user_id:
                players = await self.search_players_by_user_id(user_id)
            else:
                return web.json_response({'error': 'Не указаны параметры поиска'}, status=400)
            
            return web.json_response({
                'players': players,
                'count': len(players)
            })
            
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def get_top_players(self, top_type, limit):
        """Получение топа игроков из базы"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if top_type == 'coins':
            query = "SELECT user_id, username, level, coins, total_taps, role, has_passport FROM players ORDER BY coins DESC LIMIT ?"
        elif top_type == 'level':
            query = "SELECT user_id, username, level, coins, total_taps, role, has_passport FROM players ORDER BY level DESC LIMIT ?"
        elif top_type == 'taps':
            query = "SELECT user_id, username, level, coins, total_taps, role, has_passport FROM players ORDER BY total_taps DESC LIMIT ?"
        else:
            return []
        
        cursor.execute(query, (limit,))
        players = []
        
        for row in cursor.fetchall():
            user_id, username, level, coins, total_taps, role, has_passport = row
            players.append({
                'user_id': user_id,
                'username': username,
                'level': level,
                'coins': coins,
                'total_taps': total_taps,
                'role': role,
                'has_passport': bool(has_passport)
            })
        
        conn.close()
        return players

    async def search_players_by_username(self, username):
        """Поиск игроков по имени"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT user_id, username, level, coins, total_taps, role, has_passport FROM players WHERE username LIKE ? LIMIT 10",
            (f'%{username}%',)
        )
        
        players = []
        for row in cursor.fetchall():
            user_id, username, level, coins, total_taps, role, has_passport = row
            players.append({
                'user_id': user_id,
                'username': username,
                'level': level,
                'coins': coins,
                'total_taps': total_taps,
                'role': role,
                'has_passport': bool(has_passport)
            })
        
        conn.close()
        return players

    async def search_players_by_user_id(self, user_id):
        """Поиск игрока по ID"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT user_id, username, level, coins, total_taps, role, has_passport FROM players WHERE user_id = ?",
            (user_id,)
        )
        
        players = []
        for row in cursor.fetchall():
            user_id, username, level, coins, total_taps, role, has_passport = row
            players.append({
                'user_id': user_id,
                'username': username,
                'level': level,
                'coins': coins,
                'total_taps': total_taps,
                'role': role,
                'has_passport': bool(has_passport)
            })
        
        conn.close()
        return players

    async def start(self):
        """Запуск сервера"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()
        print("🌐 Website server started on http://0.0.0.0:8080")

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
        
        site_url = "http://104.248.184.38:8080"
        
        await message.answer(
            f"🌐 <b>Доступ к веб-сайту</b>\n\n"
            f"🔑 <b>Ваш код доступа:</b> <code>{token}</code>\n\n"
            f"📱 <b>Перейдите на сайт:</b>\n"
            f"{site_url}\n\n"
            f"💡 <b>Инструкция:</b>\n"
            f"1. Откройте сайт в браузере\n"
            f"2. Введите код доступа\n"
            f"3. Наслаждайтесь игрой!\n\n"
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
