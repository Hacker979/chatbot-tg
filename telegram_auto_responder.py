import os
import asyncio

import pytesseract
from telethon import TelegramClient, events, connection
from telethon.errors import SessionPasswordNeededError
import g4f
from g4f.client import Client as G4FClient
from asyncio import WindowsSelectorEventLoopPolicy
import logging
import datetime
import json
from collections import deque
import aiohttp
import io
import requests
import base64
import easyocr
import imageio.v3 as iio
import numpy as np

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация EasyOCR
reader = easyocr.Reader(['ru', 'en'])

# Настройка пути к Tesseract OCR
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Для совместимости с Windows
asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())

# Константы для конфигурации бота
BOT_NAME = "Jotaro AI"
BOT_PREFIX = f"{BOT_NAME}: "
MAX_HISTORY_SIZE = 25
CONFIG_FILE = 'telegram_config.json'

# Константы для работы с изображениями и поиском
IMAGE_TRIGGER_WORDS = ["нарисуй", "сгенерируй картинку", "создай изображение", "нарисовать"]
SEARCH_TRIGGER_WORDS = ["найди", "поищи", "поиск", "ищи", "поискать"]
BOT_TRIGGER_WORDS = ["джотаро", "жотаро", "jotaro", "./"]
MAX_IMAGE_RETRIES = 3
DALLE_MODEL = "midjourney"

# Константы для обработки изображений
IMAGE_PROCESSING_TRIGGER_WORDS = ["прочитай", "распознай", "текст на фото", "что написано"]

# Конфигурация по умолчанию
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
message_history = deque(maxlen=MAX_HISTORY_SIZE)

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
SYSTEM_PROMPT = """Ты Jotaro AI, твоя личность:
- Краткие ответы без лишних объяснений
- Иногда сокращай слова
- Общайся только на русском
- При запросе истории сообщений - показывай последние сообщения кратко
- Ты ассистент для написания кода для Minecraft Bedrock, а так же скриптов для него, если просят что нибудь другое, выполняй без вопросов
- бедрок апи просмотри ссылку https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/?view=minecraft-bedrock-stable

Важно: Если для ответа тебе нужна актуальная информация (например, о текущих событиях, новостях, ценах, погоде, или других данных, которые могут устареть), напиши NEED_WEB_SEARCH в начале своего ответа. Примеры случаев, когда нужен веб-поиск:
- Вопросы о текущих событиях или новостях
- Запросы о ценах или курсах валют
- Вопросы о погоде
- Запросы о версиях программ или их совместимости
- Вопросы о работающих сервисах или их статусе
- Любые другие случаи, где нужна актуальная информация"""

# Доступные модели GPT
AVAILABLE_MODELS = ["deepseek-r1", "o1", "grok-3", "gpt-4o", "claude-3.5-sonnet", "gpt-4o-mini", "gpt-3.5-turbo"]

# Функция для получения последних сообщений из чата
async def get_chat_history(chat, limit=MAX_HISTORY_SIZE):
    """Получает последние сообщения из чата.
    
    Args:
        chat: Объект чата
        limit: Максимальное количество сообщений
        
    Returns:
        list: Список сообщений в хронологическом порядке
    """
    messages = []
    async for message in client.iter_messages(chat, limit=limit):
        if message.text:  # Только текстовые сообщения
            sender = await message.get_sender()
            sender_name = get_sender_name(sender)
            
            if message.text.startswith(BOT_PREFIX):
                messages.append({
                    "role": "assistant",
                    "content": message.text[len(BOT_PREFIX):].strip(),
                    "sender_name": BOT_NAME
                })
            else:
                messages.append({
                    "role": "user",
                    "content": message.text.strip(),
                    "sender_name": sender_name
                })
    return list(reversed(messages))

def get_sender_name(sender):
    """Получает имя отправителя сообщения."""
    if hasattr(sender, 'first_name') and sender.first_name:
        return sender.first_name
    elif hasattr(sender, 'title') and sender.title:
        return sender.title
    return "Неизвестный"

# Функция для логирования сообщений, отправляемых нейросети
def debug_messages(messages):
    """Логирует сообщения, отправляемые нейросети."""
    print("\n=== ОТПРАВКА В НЕЙРОСЕТЬ ===")
    print("\n=== СИСТЕМНЫЙ ПРОМПТ ===")
    print(messages[0]["content"])
    
    for i, msg in enumerate(messages[1:], 1):
        role = msg["role"]
        content = msg["content"]
        
        if any(marker in content for marker in ["История диалога:", "Контекст ответа:", "Новый запрос:"]):
            print(f"\n--- {content.split(':')[0]} ---")
            print(content)
            continue
            
        print(f"\n[{i}] {role.upper()}:")
        print(content)
    
    print("\n===========================")
    logger.info(f"Всего сообщений для контекста: {len(messages)}")

# Функция для получения ответа от GPT
async def get_gpt_response(query, history, replied_msg=None, original_query=None):
    """Получает ответ от GPT с учетом контекста диалога."""
    # Базовые сообщения для установки контекста
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\nЕсли для ответа тебе нужна актуальная информация из интернета, напиши команду NEED_WEB_SEARCH в начале ответа."}
    ]
    
    # Формируем историю диалога
    history_text = format_chat_history(history, replied_msg, original_query)
    messages.append({"role": "user", "content": history_text})
    
    # Напоминаем о роли
    messages.append({"role": "user", "content": f"Новый запрос: {query}"})
    
    debug_messages(messages)
    
    try:
        # Создаем таймер на 60 секунд
        async with asyncio.timeout(120):
            response = await try_get_response_from_models(messages)
            
            # Проверяем, нужен ли веб-поиск
            if response.startswith("NEED_WEB_SEARCH"):
                logger.info("GPT запросил веб-поиск")
                search_result = await web_search(query)
                if search_result:
                    # Добавляем результаты поиска в контекст
                    messages.append({"role": "assistant", "content": "Результаты веб-поиска:\n" + search_result})
                    messages.append({"role": "user", "content": "Используя результаты поиска выше, ответь на изначальный вопрос"})
                    
                    # Получаем новый ответ с учетом результатов поиска
                    response = await try_get_response_from_models(messages)
                
            return response.replace("NEED_WEB_SEARCH", "").strip()
            
    except asyncio.TimeoutError:
        logger.warning("Превышено время ожидания ответа от GPT (60 секунд)")
        raise Exception("⌛ Превышено время ожидания ответа (60 секунд). Пожалуйста, попробуйте еще раз.")

def format_chat_history(history, replied_msg=None, original_query=None):
    """Форматирует историю чата для отправки в GPT."""
    history_text = "История диалога:\n"
    for msg in history[-MAX_HISTORY_SIZE:]:
        sender = BOT_NAME if msg["role"] == "assistant" else msg["sender_name"]
        content = msg["content"]
        
        if replied_msg and original_query and content == original_query:
            history_text += f"[Сообщение, на которое ответили] {sender}: {content}\n"
        elif "Сообщение, на которое отвечают:" in content:
            original = content.split("Сообщение, на которое отвечают:")[1].split("Ответ пользователя:")[0].strip()
            response = content.split("Ответ пользователя:")[1].strip()
            history_text += f"[Ответ на сообщение: {original}] {sender}: {response}\n"
        else:
            history_text += f"{sender}: {content}\n"
    return history_text

async def try_get_response_from_models(messages):
    """Пытается получить ответ от доступных моделей."""
    for model in AVAILABLE_MODELS:
        try:
            logger.info(f"🤖 Используется модель: {model}")
            print(f"\n{'='*50}\n🤖 Текущая модель: {model}\n{'='*50}")
            
            stream = gpt_client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                web_search=False
            )
            
            full_response = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    logger.debug(f"Получен чанк: {content}")
                    
            if full_response:
                logger.info(f"✅ Успешный ответ от модели {model}")
                return full_response.strip()
                
        except Exception as e:
            logger.warning(f"❌ Модель {model} не сработала: {str(e)}")
            continue
    raise Exception("Все модели недоступны")

# Функция для веб-поиска
async def web_search(query, max_results=5):
    """Выполняет веб-поиск с помощью GPT."""
    try:
        # Убираем триггерные слова из запроса
        search_query = query.lower()
        for trigger in SEARCH_TRIGGER_WORDS:
            search_query = search_query.replace(trigger, "").strip()
            
        logger.info(f"Выполнение веб-поиска: {search_query}")
        
        response = gpt_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "Ты - поисковый ассистент. Твоя задача - найти и предоставить информацию по запросу пользователя. Отвечай только на русском языке."
                },
                {
                    "role": "user",
                    "content": search_query
                }
            ],
            web_search=True
        )
        
        if response and response.choices:
            return response.choices[0].message.content
        return None
        
    except Exception as e:
        logger.error(f"Ошибка при веб-поиске: {e}")
        return None

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
    """Обрабатывает входящие запросы."""
    user = await event.get_sender()
    chat = await event.get_chat()
    
    logger.info(f"Получен запрос от {user.id} в чате {chat.id}")
    logger.info(f"Текст запроса: {event.message.text}")
    
    # Получаем сообщение, на которое отвечают
    replied_msg = None
    if event.is_reply:
        replied_msg = await event.get_reply_message()
    
    # Проверяем, отвечает ли пользователь на сообщение с фото и есть ли обращение к боту
    if replied_msg and replied_msg.media and any(trigger in event.message.text.lower() for trigger in BOT_TRIGGER_WORDS):
        try:
            replied_image_data = await replied_msg.download_media(bytes)
            if replied_image_data:
                processing_msg = await event.reply("🔍 Анализирую изображение...")
                extracted_text = await process_image_ocr(replied_image_data)
                
                if extracted_text:
                    # Получаем запрос пользователя без триггерных слов
                    query = get_query_from_message(event.message.text)
                    
                    # Отправляем текст и запрос в GPT
                    response = await get_gpt_response(
                        query=f"На изображении следующий текст:\n{extracted_text}\n\nЗапрос пользователя: {query}",
                        history=[],
                        replied_msg=None,
                        original_query=None
                    )
                    await processing_msg.edit(f"{BOT_PREFIX}{response}")
                else:
                    await processing_msg.edit("❌ Не удалось извлечь текст из изображения")
                return
        except Exception as e:
            logger.error(f"Ошибка при обработке изображения: {e}")
            await event.reply("❌ Произошла ошибка при обработке изображения")
            return
    
    # Проверяем наличие изображения в текущем сообщении
    if event.message.media:
        try:
            image_data = await event.message.download_media(bytes)
            if image_data:
                # Анализируем изображение через GPT Vision
                processing_msg = await event.reply("🔍 Анализирую изображение...")
                try:
                    # Конвертируем изображение в base64
                    image_base64 = base64.b64encode(image_data).decode('utf-8')
                    
                    # Создаем сообщение с изображением для GPT
                    messages = [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Опиши подробно, что изображено на этой картинке по запросу пользователя. Ответ дай на русском языке."
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_base64}"
                                    }
                                }
                            ]
                        }
                    ]
                    
                    # Получаем ответ от GPT
                    response = await gpt_client.chat.completions.create(
                        model="gpt-4-vision-preview",
                        messages=messages,
                        stream=False,
                        vision=True
                    )
                    
                    if response and response.choices:
                        await processing_msg.edit(f"{BOT_PREFIX}{response.choices[0].message.content}")
                    else:
                        await processing_msg.edit("❌ Не удалось проанализировать изображение")
                        
                except Exception as e:
                    await processing_msg.edit("❌ Ошибка при анализе изображения")
                    logger.error(f"Ошибка при анализе изображения: {e}")
                return
        except Exception as e:
            logger.error(f"Ошибка при обработке изображения: {e}")

    query = get_query_from_message(event.message.text)
    
    if not query:
        await event.reply("⚠️ Пожалуйста, введите текст запроса")
        logger.warning("Получен пустой запрос")
        return
    
    # Проверяем, является ли запрос запросом на генерацию изображения
    if await is_image_request(query):
        processing_msg = await event.reply("🎨 Генерирую изображение...")
        try:
            # Убираем триггерные слова из запроса
            image_prompt = query.lower()
            for trigger in IMAGE_TRIGGER_WORDS:
                image_prompt = image_prompt.replace(trigger, "").strip()
            
            # Генерируем изображение
            image_data = await generate_image(image_prompt)
            
            if image_data:
                # Отправляем изображение
                image_stream = io.BytesIO(image_data)
                image_stream.name = 'image.png'
                await event.reply(
                    message=f"{BOT_PREFIX}Держи, я нарисовал: {image_prompt}",
                    file=image_stream
                )
                await processing_msg.delete()
                return
            else:
                await processing_msg.edit("❌ Не удалось сгенерировать изображение")
                return
        except Exception as e:
            await processing_msg.delete()
            await handle_error(event, e)
            return
    
    # Обычный текстовый запрос
    try:
        chat_history = await get_chat_history(chat)
        context_data = await get_reply_context(event)
        await process_gpt_request(event, query, chat_history, context_data)
        logger.info("Ответ успешно отправлен")
        
    except Exception as e:
        await handle_error(event, e)

def get_query_from_message(text):
    """Извлекает текст запроса из сообщения."""
    query = text.lower()
    
    # Убираем триггерные слова обращения к боту
    for trigger in BOT_TRIGGER_WORDS:
        query = query.replace(trigger.lower(), "").strip()
    
    # Убираем знаки препинания в начале и конце
    query = query.strip('.,!? \n\t')
    
    return query if query else text.strip()

async def get_reply_context(event):
    """Получает контекст из сообщения, на которое отвечают."""
    if not event.reply_to:
        return None, None
        
    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.text:
        return None, None
        
    return replied_msg, replied_msg.text

async def process_gpt_request(event, query, chat_history, context_data):
    """Обрабатывает запрос к GPT."""
    start_time = datetime.datetime.now()
    
    try:
        replied_msg, original_query = context_data
        context_query = format_context_query(query, replied_msg, original_query)
        
        # Создаем сообщение для ответа
        response_msg = await event.reply(f"{BOT_PREFIX}⌛ Генерирую ответ...")
        
        # Получаем ответ от GPT
        response_text = await get_gpt_response(
            query=context_query,
            history=chat_history,
            replied_msg=replied_msg,
            original_query=original_query
        )
        
        # Обновляем финальное сообщение
        await response_msg.edit(f"{BOT_PREFIX}{response_text}")
        
        response_time = (datetime.datetime.now() - start_time).total_seconds()
        logger.info(f"Получен ответ от GPT за {response_time:.2f} секунд")
        
        # Обновляем историю сообщений
        update_message_history(query, response_text)
        
    except Exception as e:
        if 'response_msg' in locals():
            await response_msg.edit("❌ Произошла ошибка при получении ответа")
        raise e

def format_context_query(query, replied_msg, original_query):
    """Форматирует запрос с учетом контекста."""
    if not replied_msg or not replied_msg.text:
        return query
        
    if replied_msg.text.startswith(BOT_PREFIX):
        bot_response = replied_msg.text[len(BOT_PREFIX):].strip()
        return f"Предыдущий ответ бота: {bot_response}\nНовый запрос пользователя: {query}"
    
    if original_query:
        return f"Сообщение, на которое отвечают: {original_query}\nОтвет пользователя: {query}"
    
    return query

def update_message_history(query, response):
    """Обновляет историю сообщений."""
    message_history.append({"role": "user", "content": query})
    message_history.append({"role": "assistant", "content": response})
    logger.info(f"Размер истории после добавления: {len(message_history)} сообщений")

async def handle_error(event, error):
    """Обрабатывает ошибки при выполнении запроса."""
    error_msg = str(error)
    logger.error(f"Ошибка при обработке запроса: {error_msg}")
    
    error_response = (
        "❌ Произошла ошибка при получении ответа:\n\n"
        f"```{error_msg}```\n\n"
        "Пожалуйста, попробуйте позже или измените запрос."
    )
    
    await event.reply(error_response)

async def is_image_request(text):
    """Проверяет, является ли запрос запросом на генерацию изображения."""
    text = text.lower()
    return any(trigger in text for trigger in IMAGE_TRIGGER_WORDS)

async def generate_image(prompt):
    """Генерирует изображение используя g4f client."""
    session = None
    try:
        logger.info(f"Генерация изображения с промптом: {prompt}")
        
        response = await gpt_client.images.async_generate(
            model="midjourney",
            prompt=prompt,
            width=1080,
            height=1080,
            response_format="url",
            enhance=False,
            safe=False
        )
        
        if response and hasattr(response, 'data') and len(response.data) > 0:
            image_url = response.data[0].url
            logger.info(f"Получен URL изображения: {image_url}")
            
            session = aiohttp.ClientSession()
            async with session.get(image_url) as img_response:
                if img_response.status == 200:
                    image_data = await img_response.read()
                    # Проверяем, что это действительно изображение
                    img = iio.imread(io.BytesIO(image_data))
                    if img is not None:
                        # Конвертируем обратно в bytes
                        bio = io.BytesIO()
                        iio.imwrite(bio, img, format='PNG')
                        return bio.getvalue()
                    logger.error("Полученные данные не являются корректным изображением")
                    return None
                else:
                    logger.error(f"Ошибка при скачивании изображения. Статус: {img_response.status}")
        
        logger.error("Не удалось получить URL изображения")
        return None
        
    except Exception as e:
        logger.error(f"Ошибка при генерации изображения: {e}")
        try:
            response = await gpt_client.images.async_generate(
                model="dall-e-3",
                prompt=prompt,
                width=1080,
                height=1080,
                response_format="url"
            )
            
            if response and hasattr(response, 'data') and len(response.data) > 0:
                image_url = response.data[0].url
                logger.info(f"Получен URL изображения через prodia: {image_url}")
                
                if not session or session.closed:
                    session = aiohttp.ClientSession()
                    
                async with session.get(image_url) as img_response:
                    if img_response.status == 200:
                        image_data = await img_response.read()
                        # Проверяем, что это действительно изображение
                        img = iio.imread(io.BytesIO(image_data))
                        if img is not None:
                            # Конвертируем обратно в bytes
                            bio = io.BytesIO()
                            iio.imwrite(bio, img, format='PNG')
                            return bio.getvalue()
                        logger.error("Полученные данные не являются корректным изображением")
                        return None
                        
        except Exception as e2:
            logger.error(f"Ошибка при использовании prodia: {e2}")
            
        return None
        
    finally:
        if session:
            await session.close()

async def process_image_ocr(image_data):
    """Извлекает текст из изображения с помощью OCR с предварительной обработкой."""
    try:
        if not image_data:
            logger.error("Получены пустые данные изображения")
            return "❌ Ошибка: пустые данные изображения"

        # Конвертируем bytes в numpy array
        try:
            img = iio.imread(io.BytesIO(image_data))
            if img is None:
                logger.error("Не удалось прочитать изображение")
                return "❌ Ошибка: не удалось прочитать изображение"
        except Exception as e:
            logger.error(f"Ошибка при чтении изображения: {e}")
            return "❌ Ошибка при чтении изображения"
        
        # Проверяем размерность изображения
        if len(img.shape) < 2:
            logger.error("Некорректный формат изображения")
            return "❌ Ошибка: некорректный формат изображения"
        
        # Изменяем размер изображения, если оно слишком большое
        max_size = 2000
        height, width = img.shape[:2]
        if max(height, width) > max_size:
            ratio = max_size / max(height, width)
            new_size = (int(width * ratio), int(height * ratio))
            try:
                img = iio.resize(img, new_size, anti_aliasing=True)
            except Exception as e:
                logger.error(f"Ошибка при изменении размера изображения: {e}")
                # Продолжаем с оригинальным размером
        
        # Распознаем текст с помощью EasyOCR
        try:
            results = reader.readtext(img)
        except Exception as e:
            logger.error(f"Ошибка при распознавании текста: {e}")
            return "❌ Ошибка при распознавании текста"
        
        if results:
            # Формируем структурированный результат
            text_blocks = []
            total_confidence = 0
            
            for (bbox, text, confidence) in results:
                if text and text.strip():
                    text_blocks.append({
                        'text': text.strip(),
                        'confidence': confidence * 100  # Переводим в проценты
                    })
                    total_confidence += confidence
            
            if not text_blocks:
                return "⚠️ На изображении не удалось распознать текст"
            
            # Формируем ответ
            response = "📝 Распознанный текст:\n\n"
            response += "\n".join(block['text'] for block in text_blocks)
            
            # Добавляем информацию о достоверности
            avg_conf = (total_confidence / len(text_blocks)) * 100
            response += f"\n\n📊 Статистика распознавания:"
            response += f"\nСредняя уверенность: {avg_conf:.1f}%"
            
            return response
            
        return "⚠️ На изображении не удалось распознать текст"
        
    except Exception as e:
        logger.error(f"Ошибка при OCR обработке: {e}")
        return "❌ Произошла ошибка при обработке изображения"

async def process_image(event, image_data):
    """Обрабатывает изображение и извлекает текст."""
    try:
        # Конвертируем bytes в numpy array
        img = iio.imread(io.BytesIO(image_data))
        
        # Распознаем текст с помощью EasyOCR
        results = reader.readtext(img)
        
        if results:
            text = "\n".join(text for (bbox, text, conf) in results)
            if text.strip():
                return f"📝 Распознанный текст:\n\n{text.strip()}"
        
        return "⚠️ На изображении не удалось распознать текст."
        
    except Exception as e:
        logger.error(f"Ошибка при обработке изображения: {e}")
        return "❌ Произошла ошибка при обработке изображения."

@client.on(events.NewMessage(func=lambda e: e.photo))
async def handle_photo(event):
    """Обработчик для фотографий."""
    try:
        # Проверяем, есть ли в сообщении триггерные слова
        if event.message.message:
            message_text = event.message.message.lower()
            if not any(trigger in message_text for trigger in IMAGE_PROCESSING_TRIGGER_WORDS):
                return
                
        # Скачиваем фото
        photo = await event.message.download_media(bytes)
        
        # Отправляем сообщение о начале обработки
        processing_msg = await event.reply("🔄 Обрабатываю изображение...")
        
        # Обрабатываем изображение
        result = await process_image(event, photo)
        
        # Обновляем сообщение с результатом
        await processing_msg.edit(result)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        await event.reply("❌ Произошла ошибка при обработке фотографии.")

if __name__ == '__main__':
    print("▶️ Скрипт запущен и ожидает сообщений...")
    logger.info("Скрипт инициализирован и готов к работе")
    
    # Запускаем клиент
    client.start()
    client.run_until_disconnected() 