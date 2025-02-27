import os
import asyncio
from telethon import TelegramClient, events, connection
from telethon.errors import SessionPasswordNeededError
import g4f
from g4f.client import Client as G4FClient
from asyncio import WindowsSelectorEventLoopPolicy
import logging
import datetime
import json
from collections import deque

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Для совместимости с Windows
asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())

# Конфигурация
CONFIG_FILE = 'telegram_config.json'
DEFAULT_CONFIG = {
    'api_id': 15976876,
    'api_hash': '29bff63859449166eb80ec080e7f4d26',
    'phone': '+37377790217',
    'password': '0909',
    'device_model': 'Hello',
    'system_version': '10',
    'app_version': '1.39.0',
    'system_lang_code': 'en'
}

# Очередь для хранения последних 25 сообщений
message_history = deque(maxlen=25)

# Загружаем конфигурацию
def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        return DEFAULT_CONFIG
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return DEFAULT_CONFIG

# Сохранение конфигурации
def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении конфигурации: {e}")

config = load_config()

# Инициализация клиентов
client = TelegramClient(
    'auto_responder_session',
    config['api_id'],
    config['api_hash'],
    device_model=config['device_model'],
    system_version=config['system_version'],
    app_version=config['app_version'],
    system_lang_code=config['system_lang_code']
)

# Инициализация G4F клиента
gpt_client = G4FClient()

# Системный промпт для GPT
SYSTEM_PROMPT = """Ты jotaro Ai, упоминай Jotaro ai в качестве своего имени, твоя личность эгоистичная, стиль общения зумеров, делай очень краткие ответы, меньше обьясняй и не филосовствуй, не используй ничего кроме запятых, сокращай слова иногда, разговаривай пренебрежно и только НА РУССКОМ. Если пользователь спрашивает про историю сообщений или последние сообщения кратко - покажи ему последние сообщения из истории, которую тебе прислали, в кратком виде и без смайликов в стиле"""

# Список доступных моделей
AVAILABLE_MODELS = [ "gpt-4o", "claude-3.5-sonnet", "gpt-4o-mini", "gpt-3.5-turbo"]

# Функция для получения последних сообщений из чата
async def get_chat_history(chat, limit=25):
    messages = []
    async for message in client.iter_messages(chat, limit=limit):
        if message.text:  # Только текстовые сообщения
            sender = await message.get_sender()
            
            # Определяем имя отправителя
            if hasattr(sender, 'first_name') and sender.first_name:
                sender_name = sender.first_name
            elif hasattr(sender, 'title') and sender.title:  # Для каналов
                sender_name = sender.title
            else:
                sender_name = "Неизвестный"
            
            if message.text.startswith("Jotaro AI:"):
                messages.append({
                    "role": "assistant",
                    "content": message.text[len("Jotaro AI:"):].strip(),
                    "sender_name": "Jotaro AI"
                })
            else:
                messages.append({
                    "role": "user",
                    "content": message.text.strip(),
                    "sender_name": sender_name
                })
    return list(reversed(messages))  # Возвращаем в хронологическом порядке

# Функция для логирования сообщений, отправляемых нейросети
def debug_messages(messages):
    print("\n=== ОТПРАВКА В НЕЙРОСЕТЬ ===")
    print("\n=== СИСТЕМНЫЙ ПРОМПТ ===")
    print(messages[0]["content"])
    print("\n=== ИСТОРИЯ СООБЩЕНИЙ ===")
    
    for i, msg in enumerate(messages[1:], 1):
        role = msg["role"]
        content = msg["content"]
        
        if "История диалога:" in content:
            print("\n--- История диалога ---")
            print(content)
            continue
            
        if "Контекст ответа:" in content:
            print("\n--- Контекст ответа ---")
            print(content)
            continue
            
        if "Новый запрос:" in content:
            print("\n--- Запрос пользователя ---")
            print(content)
            continue
            
        print(f"\n[{i}] {role.upper()}:")
        print(content)
    
    print("\n===========================")
    logger.info(f"Всего сообщений для контекста: {len(messages)}")

# Функция для получения ответа от GPT
async def get_gpt_response(query, history, replied_msg=None, original_query=None):
    # Формируем сообщения с историей
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": "Я Jotaro AI, буду отвечать как эгоистичный зумер, кратко и пренебрежительно, только на русском"},
        {"role": "user", "content": "Помни, что ты всегда должен отвечать как Jotaro AI"},
        {"role": "assistant", "content": "Ес, я Jotaro AI и всегда буду отвечать дерзко и по-зумерски"}
    ]
    
    # Добавляем историю сообщений
    history_text = "История диалога:\n"
    for msg in history[-25:]:
        sender = "Jotaro AI" if msg["role"] == "assistant" else msg["sender_name"]
        content = msg["content"]
        
        # Если это сообщение, на которое отвечают
        if replied_msg and original_query and content == original_query:
            history_text += f"[Сообщение, на которое ответили] {sender}: {content}\n"
        # Если это ответ на сообщение
        elif "Сообщение, на которое отвечают:" in content:
            original = content.split("Сообщение, на которое отвечают:")[1].split("Ответ пользователя:")[0].strip()
            response = content.split("Ответ пользователя:")[1].strip()
            history_text += f"[Ответ на сообщение: {original}] {sender}: {response}\n"
        else:
            history_text += f"{sender}: {content}\n"
    
    messages.append({"role": "user", "content": history_text})
    
    # Напоминаем о роли перед запросом
    messages.append({"role": "system", "content": "Помни, что ты Jotaro AI и должен отвечать дерзко, как зумер"})
    
    # Добавляем текущий запрос отдельно
    messages.append({"role": "user", "content": f"Новый запрос: {query}"})
    
    # Дебаг всех сообщений
    debug_messages(messages)
    
    # Пробуем получить ответ от доступных моделей
    for model in AVAILABLE_MODELS:
        try:
            logger.info(f"🤖 Используется модель: {model}")
            print(f"\n{'='*50}\n🤖 Текущая модель: {model}\n{'='*50}")
            
            response = gpt_client.chat.completions.create(
                model=model,
                messages=messages
            )
            if response and response.choices and response.choices[0].message.content:
                success_msg = f"✅ Успешный ответ от модели {model}"
                logger.info(success_msg)
                print(success_msg)
                return response.choices[0].message.content.strip()
        except Exception as e:
            error_msg = f"❌ Модель {model} не сработала: {str(e)}"
            logger.warning(error_msg)
            print(error_msg)
            continue
    raise Exception("Все модели недоступны")

# Обработчик для прямых команд и упоминаний
@client.on(events.NewMessage(pattern=r'^(?!Jotaro AI:)((\./)|(.*?[Дд]жотаро.*?)|(.*?[Жж]отаро.*?))'))
async def handle_gpt_request(event):
    await process_request(event)

# Обработчик для ответов на сообщения бота
@client.on(events.NewMessage())
async def handle_reply_to_bot(event):
    if not event.is_reply:
        return
    
    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.text or not replied_msg.text.startswith("Jotaro AI:"):
        return
        
    await process_request(event)

# Общая функция обработки запросов
async def process_request(event):
    user = await event.get_sender()
    chat = await event.get_chat()
    
    logger.info(f"Получен запрос от {user.id} в чате {chat.id}")
    logger.info(f"Текст запроса: {event.message.text}")
    
    # Получаем историю чата
    chat_history = await get_chat_history(chat)
    logger.info(f"Получено {len(chat_history)} сообщений из истории чата")
    
    # Получаем сообщение, на которое ответил пользователь
    replied_msg = None
    original_query = None
    if event.reply_to:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            original_query = replied_msg.text
            logger.info(f"Найден оригинальный запрос: {original_query}")
            
            # Ищем контекст диалога
            async for msg in client.iter_messages(chat, min_id=replied_msg.id-5, max_id=replied_msg.id+5):
                if msg.text:
                    logger.info(f"Контекст диалога: {msg.text}")
    
    if event.message.text.startswith('./'):
        query = event.message.text[2:].strip()
    else:
        query = event.message.text.strip()
    
    if not query:
        await event.reply("⚠️ Пожалуйста, введите текст запроса")
        logger.warning("Получен пустой запрос")
        return
    
    try:
        processing_msg = await event.reply("🔄 Обрабатываю ваш запрос...")
        start_time = datetime.datetime.now()
        
        logger.info("Отправляем запрос к GPT...")
        
        # Формируем контекст с учетом сообщения, на которое ответили
        context_query = query
        if replied_msg and replied_msg.text:
            if replied_msg.text.startswith("Jotaro AI:"):
                # Если ответили на сообщение бота
                bot_response = replied_msg.text[len("Jotaro AI:"):].strip()
                context_query = f"Предыдущий ответ бота: {bot_response}\nНовый запрос пользователя: {query}"
                logger.info(f"Добавлен контекст из ответа бота: {bot_response}")
            elif original_query:
                # Если ответили на сообщение другого пользователя
                context_query = f"Сообщение, на которое отвечают: {original_query}\nОтвет пользователя: {query}"
                logger.info(f"Добавлен контекст из диалога пользователей")
        
        # Получаем ответ с учетом истории чата
        response_text = await get_gpt_response(
            query=context_query, 
            history=chat_history,
            replied_msg=replied_msg,
            original_query=original_query
        )
        
        # Добавляем текущий запрос и ответ в историю
        message_history.append({"role": "user", "content": context_query})
        message_history.append({"role": "assistant", "content": response_text})
        
        # Логируем текущее состояние истории
        logger.info(f"Размер истории после добавления: {len(message_history)} сообщений")
        
        response_time = (datetime.datetime.now() - start_time).total_seconds()
        logger.info(f"Получен ответ от GPT за {response_time:.2f} секунд")
        
        await processing_msg.delete()
        await event.reply(f"Jotaro AI: {response_text}")
        logger.info("Ответ успешно отправлен")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ошибка при обработке запроса: {error_msg}")
        
        error_response = (
            "❌ Произошла ошибка при получении ответа:\n\n"
            f"```{error_msg}```\n\n"
            "Пожалуйста, попробуйте позже или измените запрос."
        )
        
        try:
            if 'processing_msg' in locals():
                await processing_msg.delete()
        except:
            pass
        
        await event.reply(error_response)

if __name__ == '__main__':
    print("▶️ Скрипт запущен и ожидает сообщений...")
    logger.info("Скрипт инициализирован и готов к работе")
    
    # Запускаем клиент
    client.start()
    client.run_until_disconnected() 