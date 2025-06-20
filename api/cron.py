import os
import sys
import asyncio
import logging

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import astro # Импортируем ваш основной файл с логикой бота

logger = logging.getLogger(__name__)

# Этот флаг будет показывать, была ли MongoDB уже инициализирована
_mongodb_initialized_cron = False

async def initialize_mongodb_for_cron():
    """Инициализирует MongoDB, если еще не инициализировано."""
    global _mongodb_initialized_cron
    if not _mongodb_initialized_cron:
        logger.info("Инициализация MongoDB для Cron Job...")
        await astro.init_mongodb()
        logger.info("Инициализация MongoDB завершена для Cron Job.")
        _mongodb_initialized_cron = True
    else:
        logger.info("MongoDB уже инициализирована для Cron Job.")

def handler(request, context):
    """
    Обработчик для Cron Job.
    Vercel Cron Job вызывает этот endpoint по HTTP.
    """
    try:
        logger.info("Получен запрос на запуск ежедневной рассылки гороскопов (Cron Job).")
        
        # Запускаем асинхронную задачу
        asyncio.run(run_scheduled_tasks())

        return {
            "statusCode": 200,
            "body": "Daily horoscopes dispatch initiated successfully."
        }
    except Exception as e:
        logger.error(f"Ошибка при запуске Cron Job: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": f"Error initiating daily horoscopes dispatch: {e}"
        }

async def run_scheduled_tasks():
    """
    Асинхронная функция для выполнения запланированных задач.
    """
    await initialize_mongodb_for_cron()
    await astro.scheduled_tasks()
    logger.info("Запланированные задачи (рассылка гороскопов) завершены.")
