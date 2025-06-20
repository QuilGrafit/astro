import os
import sys
import asyncio
import logging

# Добавляем корневую директорию проекта в sys.path,
# чтобы astro.py был доступен для импорта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import astro # Импортируем ваш основной файл с логикой бота

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Этот флаг будет показывать, была ли MongoDB уже инициализирована
# в рамках текущего экземпляра серверной функции.
# Важно для избежания повторной инициализации при каждом запросе,
# но при этом гарантировать, что она инициализирована.
_mongodb_initialized = False

async def initialize_and_run_bot():
    """
    Инициализирует MongoDB и устанавливает вебхук, если еще не инициализировано.
    Это асинхронная функция, которая должна быть вызвана в обработчике.
    """
    global _mongodb_initialized
    if not _mongodb_initialized:
        logger.info("Выполняю инициализацию бота и MongoDB...")
        await astro.init_mongodb()
        logger.info("Инициализация MongoDB завершена.")
        if astro.WEBHOOK_URL:
            await astro.bot.set_webhook(astro.WEBHOOK_URL, drop_pending_updates=True)
            logger.info(f"Вебхук установлен на: {astro.WEBHOOK_URL}")
        else:
            logger.error("WEBHOOK_HOST не установлен. Вебхук не будет настроен.")
        _mongodb_initialized = True
    else:
        logger.info("MongoDB и вебхук уже инициализированы.")


class TelegramWebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Проверяем, является ли запрос от Telegram
        if self.path != astro.WEBHOOK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        
        try:
            update = json.loads(body)
            logger.info(f"Получен webhook update: {update}")
            
            # Запускаем асинхронную функцию в текущем EventLoop
            asyncio.run(self.process_update(update))

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            logger.error("Получен невалидный JSON в webhook.")
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode())
            logger.error(f"Ошибка при обработке webhook: {e}", exc_info=True)

    async def process_update(self, update_data: dict):
        # Vercel пересоздает окружение при каждом запросе,
        # поэтому нам нужно инициализировать MongoDB и вебхук здесь.
        # Однако, чтобы не делать это при каждом микросекундном запросе (если их много),
        # мы используем глобальный флаг _mongodb_initialized.
        # В реальной серверless среде, инициализация происходит каждый "холодный старт".
        await initialize_and_run_bot()

        # Создаем объект aiogram.types.Update из полученных данных
        telegram_update = astro.types.Update.model_validate(update_data) # Использовать model_validate

        # Передаем update в диспетчер aiogram
        # handle_updates принимает список апдейтов, поэтому оборачиваем
        await astro.dp.feed_update(astro.bot, telegram_update)


# Для Vercel, точка входа - это HTTP-сервер,
# который будет вызван при запросе к /api/index.py
def handler(event, context):
    """
    Основной обработчик для Vercel.
    Vercel передает события в формат WSGI/ASGI, но мы здесь эмулируем
    простой HTTP-сервер для aiogram'а webhook.
    Для реальных сложных WSGI/ASGI приложений, лучше использовать uvicorn/gunicorn.
    Однако для aiogram webhook достаточно такого подхода,
    так как aiogram сам обрабатывает Update.
    """
    
    # event['body'] содержит тело запроса (payload от Telegram)
    # event['headers'] содержит заголовки
    # event['path'] содержит путь запроса

    try:
        # aiogram ожидает raw body, не json.
        # Vercel JSON-декодирует тело автоматически, если Content-Type: application/json.
        # Нам нужно обратно превратить его в байты.
        if isinstance(event.get('body'), dict):
            raw_body = json.dumps(event['body']).encode('utf-8')
            headers = event.get('headers', {})
            headers['content-length'] = str(len(raw_body)) # Обновим Content-Length
            event['body'] = raw_body
            event['headers'] = headers
        elif isinstance(event.get('body'), str): # Если body - строка (base64-encoded)
            raw_body = base64.b64decode(event['body'])
            headers = event.get('headers', {})
            headers['content-length'] = str(len(raw_body))
            event['body'] = raw_body
            event['headers'] = headers


        # Эмулируем Flask/aiohttp request для aiogram webhook
        # aiogram.webhook.utils.TelegramWebhookRequestHandler
        # ожидает Request объект.

        # Простой способ: передать raw update в диспетчер напрямую.
        # Однако, aiogram.webhook.aiohttp_web.SimpleRequestHandler ожидает aiohttp.web.Request.
        # На Vercel мы можем обойти это, напрямую вызывая dp.feed_update.

        if event['path'] != astro.WEBHOOK_PATH:
            return {
                "statusCode": 404,
                "body": "Not Found"
            }

        update_data = json.loads(event['body'])
        
        # Запускаем асинхронную часть
        asyncio.run(TelegramWebhookHandler._process_vercel_update(update_data))

        return {
            "statusCode": 200,
            "body": "OK"
        }
    except Exception as e:
        logger.error(f"Ошибка в Vercel handler: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": f"Internal Server Error: {e}"
        }

# Для Vercel нужно немного другой механизм обработки, не BaseHTTPRequestHandler
# Создадим асинхронный метод для обработки
async def _process_vercel_update(update_data: dict):
    # Эта функция будет вызываться из handler(event, context)
    # после получения данных от Vercel.
    
    await initialize_and_run_bot()

    # Создаем объект aiogram.types.Update из полученных данных
    telegram_update = astro.types.Update.model_validate(update_data)

    # Передаем update в диспетчер aiogram
    await astro.dp.feed_update(astro.bot, telegram_update)

# Заменяем метод в классе
TelegramWebhookHandler._process_vercel_update = _process_vercel_update
