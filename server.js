const express = require('express');
const fs = require('fs');
const path = require('path');
const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const cors = require('cors');
const app = express();

const PORT = 8080;
const JWT_SECRET = 'your-secret-key-change-in-production';
const DATA_DIR = './chat_data';
const ADMIN_USERNAME = 'pym6a';

// Глобальные переменные для реального времени
const activeTypers = new Map(); // channel -> {username, timestamp}
const messageSubscribers = new Map(); // channel -> [res, res, ...]

// Создаем директорию для данных, если её нет
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

app.use(express.json());
app.use(cors());
app.use(express.static('public'));

// Загружаем пользователей
function loadUsers() {
  try {
    const data = fs.readFileSync(path.join(DATA_DIR, 'users.json'), 'utf8');
    return JSON.parse(data);
  } catch (error) {
    return {};
  }
}

// Сохраняем пользователей
function saveUsers(users) {
  fs.writeFileSync(path.join(DATA_DIR, 'users.json'), JSON.stringify(users, null, 2));
}

// Загружаем каналы
function loadChannels() {
  try {
    const data = fs.readFileSync(path.join(DATA_DIR, 'channels.json'), 'utf8');
    return JSON.parse(data);
  } catch (error) {
    return {
      general: { 
        name: 'general', 
        title: 'Общий', 
        isPrivate: false,
        messages: [],
        createdBy: 'system',
        createdAt: new Date().toISOString()
      }
    };
  }
}

// Сохраняем каналы
function saveChannels(channels) {
  fs.writeFileSync(path.join(DATA_DIR, 'channels.json'), JSON.stringify(channels, null, 2));
}

// Функция для уведомления подписчиков о новых сообщениях
function notifySubscribers(channel, data) {
  if (messageSubscribers.has(channel)) {
    const subscribers = messageSubscribers.get(channel);
    messageSubscribers.set(channel, subscribers.filter(res => {
      try {
        res.json(data);
        return false; // Удаляем после отправки
      } catch (e) {
        return false; // Удаляем если ошибка
      }
    }));
    
    if (messageSubscribers.get(channel).length === 0) {
      messageSubscribers.delete(channel);
    }
  }
}

// Функция для получения статуса набора текста
function getTypingStatus(channel) {
  if (!activeTypers.has(channel)) return [];
  
  const now = Date.now();
  const typers = Array.from(activeTypers.get(channel).entries())
    .filter(([username, timestamp]) => now - timestamp < 3000) // 3 секунды активности
    .map(([username]) => username);
  
  // Очищаем старые записи
  if (typers.length === 0) {
    activeTypers.delete(channel);
  }
  
  return typers;
}

// Middleware для проверки JWT токена
function authenticateToken(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1];

  if (!token) {
    return res.status(401).json({ error: 'Токен отсутствует' });
  }

  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) {
      return res.status(403).json({ error: 'Неверный токен' });
    }
    req.user = user;
    next();
  });
}

// Проверка прав на удаление канала
function canDeleteChannel(channel, username) {
  // Админ может удалять любые каналы
  if (username === ADMIN_USERNAME) {
    return true;
  }
  
  // Пользователь может удалять только свои каналы
  return channel.createdBy === username;
}

// Регистрация
app.post('/api/register', async (req, res) => {
  const { username, password } = req.body;
  
  if (!username || !password) {
    return res.status(400).json({ error: 'Имя пользователя и пароль обязательны' });
  }
  
  const users = loadUsers();
  
  if (users[username]) {
    return res.status(400).json({ error: 'Пользователь уже существует' });
  }
  
  const hashedPassword = await bcrypt.hash(password, 10);
  users[username] = {
    username,
    password: hashedPassword,
    avatar: null,
    createdAt: new Date().toISOString()
  };
  
  saveUsers(users);
  
  const token = jwt.sign({ username }, JWT_SECRET);
  res.json({ token, username });
});

// Авторизация
app.post('/api/login', async (req, res) => {
  const { username, password } = req.body;
  
  if (!username || !password) {
    return res.status(400).json({ error: 'Имя пользователя и пароль обязательны' });
  }
  
  const users = loadUsers();
  const user = users[username];
  
  if (!user || !(await bcrypt.compare(password, user.password))) {
    return res.status(401).json({ error: 'Неверные учетные данные' });
  }
  
  const token = jwt.sign({ username }, JWT_SECRET);
  res.json({ token, username, avatar: user.avatar });
});

// Получение каналов (только публичные и приватные пользователя)
app.get('/api/channels', authenticateToken, (req, res) => {
  const channels = loadChannels();
  const filteredChannels = {};
  
  Object.keys(channels).forEach(key => {
    const channel = channels[key];
    // Админ видит все каналы
    if (req.user.username === ADMIN_USERNAME) {
      filteredChannels[key] = channel;
    }
    // Обычные пользователи видят публичные каналы и свои приватные
    else if (!channel.isPrivate || channel.createdBy === req.user.username) {
      filteredChannels[key] = channel;
    }
  });
  
  res.json(filteredChannels);
});

// Получение сообщений канала
app.get('/api/channels/:channel/messages', authenticateToken, (req, res) => {
  const channels = loadChannels();
  const channel = channels[req.params.channel];
  
  if (!channel) {
    return res.status(404).json({ error: 'Канал не найден' });
  }
  
  // Проверяем доступ к приватному каналу
  if (channel.isPrivate && channel.createdBy !== req.user.username && req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Нет доступа к этому каналу' });
  }
  
  res.json(channel.messages);
});

// Long polling для новых сообщений и статуса набора
app.get('/api/channels/:channel/updates', authenticateToken, (req, res) => {
  const channel = req.params.channel;
  const lastUpdate = parseInt(req.query.lastUpdate) || Date.now();
  
  // Проверяем доступ к каналу
  const channels = loadChannels();
  const channelData = channels[channel];
  
  if (!channelData) {
    return res.status(404).json({ error: 'Канал не найден' });
  }
  
  if (channelData.isPrivate && channelData.createdBy !== req.user.username && req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Нет доступа' });
  }
  
  // Добавляем в подписчики
  if (!messageSubscribers.has(channel)) {
    messageSubscribers.set(channel, []);
  }
  messageSubscribers.get(channel).push(res);
  
  // Таймаут 25 секунд
  setTimeout(() => {
    if (messageSubscribers.has(channel)) {
      const subscribers = messageSubscribers.get(channel);
      const index = subscribers.indexOf(res);
      if (index > -1) {
        subscribers.splice(index, 1);
        res.json({ type: 'timeout', timestamp: Date.now() });
      }
    }
  }, 25000);
});

// Отправка сообщения
app.post('/api/channels/:channel/messages', authenticateToken, (req, res) => {
  const { text } = req.body;
  
  if (!text || text.trim() === '') {
    return res.status(400).json({ error: 'Текст сообщения не может быть пустым' });
  }
  
  const channels = loadChannels();
  const channel = channels[req.params.channel];
  
  if (!channel) {
    return res.status(404).json({ error: 'Канал не найден' });
  }
  
  // Проверяем доступ к приватному каналу
  if (channel.isPrivate && channel.createdBy !== req.user.username && req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Нет доступа к этому каналу' });
  }
  
  const users = loadUsers();
  const user = users[req.user.username];
  
  const message = {
    id: Date.now().toString(),
    text: text.trim(),
    username: req.user.username,
    avatar: user.avatar,
    timestamp: new Date().toISOString()
  };
  
  channel.messages.push(message);
  saveChannels(channels);
  
  // Уведомляем всех подписчиков
  notifySubscribers(req.params.channel, {
    type: 'new_message',
    message: message,
    channel: req.params.channel
  });
  
  res.json(message);
});

// Управление статусом набора текста
app.post('/api/channels/:channel/typing', authenticateToken, (req, res) => {
  const { isTyping } = req.body;
  const channel = req.params.channel;
  
  if (!activeTypers.has(channel)) {
    activeTypers.set(channel, new Map());
  }
  
  const channelTypers = activeTypers.get(channel);
  
  if (isTyping) {
    channelTypers.set(req.user.username, Date.now());
    
    // Уведомляем подписчиков о начале набора
    notifySubscribers(channel, {
      type: 'typing_update',
      users: getTypingStatus(channel),
      channel: channel
    });
    
    // Автоматически очищаем через 3 секунды
    setTimeout(() => {
      if (channelTypers.has(req.user.username)) {
        const timestamp = channelTypers.get(req.user.username);
        if (Date.now() - timestamp >= 3000) {
          channelTypers.delete(req.user.username);
          notifySubscribers(channel, {
            type: 'typing_update',
            users: getTypingStatus(channel),
            channel: channel
          });
        }
      }
    }, 3000);
  } else {
    channelTypers.delete(req.user.username);
    notifySubscribers(channel, {
      type: 'typing_update',
      users: getTypingStatus(channel),
      channel: channel
    });
  }
  
  res.json({ success: true });
});

// Создание канала
app.post('/api/channels', authenticateToken, (req, res) => {
  const { name, title, isPrivate = false } = req.body;
  
  if (!name || !title) {
    return res.status(400).json({ error: 'Имя и заголовок канала обязательны' });
  }
  
  // Валидация имени канала
  if (!/^[a-z0-9\-_]+$/.test(name)) {
    return res.status(400).json({ error: 'Имя канала может содержать только латинские буквы, цифры, дефисы и подчеркивания' });
  }
  
  const channels = loadChannels();
  
  if (channels[name]) {
    return res.status(400).json({ error: 'Канал уже существует' });
  }
  
  channels[name] = {
    name,
    title,
    isPrivate: Boolean(isPrivate),
    messages: [],
    createdBy: req.user.username,
    createdAt: new Date().toISOString()
  };
  
  saveChannels(channels);
  res.json(channels[name]);
});

// Удаление канала
app.delete('/api/channels/:channel', authenticateToken, (req, res) => {
  const channels = loadChannels();
  const channel = channels[req.params.channel];
  
  if (!channel) {
    return res.status(404).json({ error: 'Канал не найден' });
  }
  
  // Нельзя удалить основной канал general
  if (req.params.channel === 'general') {
    return res.status(400).json({ error: 'Нельзя удалить основной канал' });
  }
  
  // Проверяем права на удаление
  if (!canDeleteChannel(channel, req.user.username)) {
    return res.status(403).json({ error: 'Недостаточно прав для удаления этого канала' });
  }
  
  // Удаляем канал
  delete channels[req.params.channel];
  saveChannels(channels);
  
  res.json({ success: true, message: 'Канал успешно удален' });
});

// Получение профиля пользователя
app.get('/api/profile', authenticateToken, (req, res) => {
  const users = loadUsers();
  const user = users[req.user.username];
  
  res.json({
    username: req.user.username,
    avatar: user.avatar,
    createdAt: user.createdAt
  });
});

// Обновление аватара
app.post('/api/profile/avatar', authenticateToken, async (req, res) => {
  const { avatar } = req.body;
  
  if (!avatar) {
    return res.status(400).json({ error: 'Аватар обязателен' });
  }
  
  const users = loadUsers();
  const user = users[req.user.username];
  
  if (!user) {
    return res.status(404).json({ error: 'Пользователь не найден' });
  }
  
  user.avatar = avatar;
  saveUsers(users);
  
  res.json({ avatar });
});

// Удаление сообщения
app.delete('/api/channels/:channel/messages/:messageId', authenticateToken, (req, res) => {
  const channels = loadChannels();
  const channel = channels[req.params.channel];
  
  if (!channel) {
    return res.status(404).json({ error: 'Канал не найден' });
  }
  
  // Проверяем доступ к приватному каналу
  if (channel.isPrivate && channel.createdBy !== req.user.username && req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Нет доступа к этому каналу' });
  }
  
  const messageIndex = channel.messages.findIndex(m => m.id === req.params.messageId);

  if (messageIndex === -1) {
    return res.status(404).json({ error: 'Сообщение не найдено' });
  }
  
  const message = channel.messages[messageIndex];
  
  if (message.username !== req.user.username && req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Вы можете удалять только свои сообщения' });
  }
  
  channel.messages.splice(messageIndex, 1);
  saveChannels(channels);
  
  // Уведомляем подписчиков об удалении
  notifySubscribers(req.params.channel, {
    type: 'message_deleted',
    messageId: req.params.messageId,
    channel: req.params.channel
  });
  
  res.json({ success: true });
});

// Поиск сообщений
app.get('/api/search/messages', authenticateToken, (req, res) => {
  const { query, channel } = req.query;
  
  if (!query || query.length < 2) {
    return res.status(400).json({ error: 'Поисковый запрос должен содержать минимум 2 символа' });
  }
  
  const channels = loadChannels();
  const results = [];
  
  Object.entries(channels).forEach(([channelName, channelData]) => {
    // Проверяем доступ к каналу
    if (channelData.isPrivate && channelData.createdBy !== req.user.username && req.user.username !== ADMIN_USERNAME) {
      return;
    }
    
    // Если указан конкретный канал, ищем только в нем
    if (channel && channel !== channelName) {
      return;
    }
    
    channelData.messages.forEach(message => {
      if (message.text.toLowerCase().includes(query.toLowerCase())) {
        results.push({
          ...message,
          channel: channelName,
          channelTitle: channelData.title
        });
      }
    });
  });
  
  // Сортируем по времени (новые сверху)
  results.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  
  res.json(results);
});

// Получение статистики (только для админа)
app.get('/api/admin/stats', authenticateToken, (req, res) => {
  if (req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Недостаточно прав' });
  }
  
  const users = loadUsers();
  const channels = loadChannels();
  
  let totalMessages = 0;
  Object.values(channels).forEach(channel => {
    totalMessages += channel.messages.length;
  });
  
  const stats = {
    totalUsers: Object.keys(users).length,
    totalChannels: Object.keys(channels).length,
    totalMessages: totalMessages,
    activeChannels: Object.values(channels).filter(ch => ch.messages.length > 0).length
  };
  
  res.json(stats);
});

// Редактирование сообщения
app.put('/api/channels/:channel/messages/:messageId', authenticateToken, (req, res) => {
  const { text } = req.body;
  
  if (!text || text.trim() === '') {
    return res.status(400).json({ error: 'Текст сообщения не может быть пустым' });
  }
  
  const channels = loadChannels();
  const channel = channels[req.params.channel];
  
  if (!channel) {
    return res.status(404).json({ error: 'Канал не найден' });
  }
  
  // Проверяем доступ к приватному каналу
  if (channel.isPrivate && channel.createdBy !== req.user.username && req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Нет доступа к этому каналу' });
  }
  
  const messageIndex = channel.messages.findIndex(m => m.id === req.params.messageId);

  if (messageIndex === -1) {
    return res.status(404).json({ error: 'Сообщение не найдено' });
  }
  
  const message = channel.messages[messageIndex];
  
  if (message.username !== req.user.username && req.user.username !== ADMIN_USERNAME) {
    return res.status(403).json({ error: 'Вы можете редактировать только свои сообщения' });
  }
  
  // Обновляем сообщение
  channel.messages[messageIndex] = {
    ...message,
    text: text.trim(),
    edited: true,
    editedAt: new Date().toISOString()
  };
  
  saveChannels(channels);
  
  // Уведомляем подписчиков об редактировании
  notifySubscribers(req.params.channel, {
    type: 'message_updated',
    message: channel.messages[messageIndex],
    channel: req.params.channel
  });
  
  res.json(channel.messages[messageIndex]);
});

app.listen(PORT, () => {
  console.log(`Сервер чата запущен на порту ${PORT}`);
});
