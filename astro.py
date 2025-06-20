import os
import logging
import hashlib
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, ReplyKeyboardRemove
import asyncio
import re
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# --- Загрузка переменных окружения для локальной разработки ---
# На Render эти переменные будут установлены автоматически.
load_dotenv()

# --- Настройки (читаются из переменных окружения) ---
TOKEN = os.getenv("BOT_TOKEN")
TON_WALLET = os.getenv("TON_WALLET_ADDRESS")
ADSGRAM_API_KEY = os.getenv("ADSGRAM_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "AstroBotDB")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "users")

# Настройки вебхука для Render/Vercel
# WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") # Это может быть адрес вашего Render сервиса
# WEBHOOK_PATH = f"/webhook/{TOKEN}" # Пример, можно использовать просто /webhook
# WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else None

# На Render WEBHOOK_URL обычно формируется из URL сервиса, который можно получить из переменных окружения Render
# Или, как мы делали, просто используем WEBHOOK_HOST и формируем URL
# Для Render, если вы используете их домен:
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME") # Render предоставляет этот URL
if not WEBHOOK_HOST:
    # Если на Render нет RENDER_EXTERNAL_HOSTNAME, возможно, используется другая переменная
    # Или это локальный запуск. Тогда WEBHOOK_URL будет None, и бот перейдет в long-polling.
    WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") # Fallback для случаев, если вы задаете его вручную
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST and TOKEN else None


# --- Логирование ---
# Настройка логирования для вывода в консоль (Render будет перехватывать это)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Проверка наличия обязательных переменных окружения ---
if not TOKEN:
    logger.error("Environment variable BOT_TOKEN is not set.")
    raise ValueError("Environment variable BOT_TOKEN is not set.")
if not TON_WALLET:
    logger.error("Environment variable TON_WALLET_ADDRESS is not set.")
    # raise ValueError("Environment variable TON_WALLET_ADDRESS is not set.") # Закомментировано, если это не критично для запуска
if not MONGO_URI:
    logger.error("Environment variable MONGO_URI is not set.")
    raise ValueError("Environment variable MONGO_URI is not set.")

# --- Инициализация бота и диспетчера ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage()) # Используем MemoryStorage

# --- Соединение с MongoDB ---
mongo_client: AsyncIOMotorClient = None
db = None
users_collection = None

async def init_mongodb():
    global mongo_client, db, users_collection
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[MONGO_DB_NAME]
        users_collection = db[MONGO_COLLECTION_NAME]
        await users_collection.create_index("user_id", unique=True)
        logger.info("Успешно подключено к MongoDB.")
    except Exception as e:
        logger.error(f"Ошибка при подключении к MongoDB: {e}", exc_info=True)
        # В случае ошибки, возможно, стоит поднять исключение или предпринять другие действия
        raise ConnectionError(f"Не удалось подключиться к MongoDB: {e}")

# --- Состояния FSM ---
class UserState(StatesGroup):
    choosing_sign = State()
    choosing_date = State()
    choosing_type = State()
    waiting_for_payment = State()
    waiting_for_adsgram_payment = State()
    waiting_for_ton_payment = State()
    waiting_for_birth_date = State()

# --- Вспомогательные функции для работы с БД ---
async def get_user_data(user_id: int):
    return await users_collection.find_one({"user_id": user_id})

async def update_user_data(user_id: int, data: dict):
    await users_collection.update_one({"user_id": user_id}, {"$set": data}, upsert=True)

# --- Клавиатуры ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="♈ Овен")
    builder.button(text="♉ Телец")
    builder.button(text="♊ Близнецы")
    builder.button(text="♋ Рак")
    builder.button(text="♌ Лев")
    builder.button(text="♍ Дева")
    builder.button(text="♎ Весы")
    builder.button(text="♏ Скорпион")
    builder.button(text="♐ Стрелец")
    builder.button(text="♑ Козерог")
    builder.button(text="♒ Водолей")
    builder.button(text="♓ Рыбы")
    builder.button(text="⭐️ Выбрать свой знак") # Добавленная кнопка
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_date_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="date_today")
    builder.button(text="Завтра", callback_data="date_tomorrow")
    builder.button(text="Неделя", callback_data="date_week")
    return builder.as_markup()

def get_horoscope_type_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Общий", callback_data="type_general")
    builder.button(text="Любовный", callback_data="type_love")
    builder.button(text="Бизнес", callback_data="type_business")
    builder.button(text="Здоровье", callback_data="type_health")
    return builder.as_markup()

def get_payment_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    # Кнопка оплаты AdsGram
    # Параметры: amount, currency, order_id, description, redirect_url (опционально)
    # Используйте уникальный order_id для каждой транзакции
    order_id_adsgram = f"adsgram_{user_id}_{int(datetime.now().timestamp())}"
    builder.button(text="Через AdsGram (1 просмотр)", url=f"https://adsgram.ai/pay?api_key={ADSGRAM_API_KEY}&amount=1&order_id={order_id_adsgram}")
    
    # Кнопка оплаты TON (примерная логика, требует реальной интеграции)
    amount_ton = 0.05 # Примерная сумма в TON
    ton_invoice_url = f"https://ton.org/invoice/{TON_WALLET}?amount={int(amount_ton * 1e9)}" # Конвертация в нано-TON
    builder.button(text=f"Через TON ({amount_ton} TON)", url=ton_invoice_url)

    builder.button(text="Проверить оплату", callback_data="check_payment")
    return builder.as_markup()

def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Главное меню", callback_data="start_over")
    return builder.as_markup()

# --- Генерация гороскопа (заглушка) ---
async def generate_horoscope(sign: str, date_type: str, horoscope_type: str):
    # Здесь может быть логика обращения к API или генерации гороскопа
    # Для примера:
    base_horoscope = f"Ваш гороскоп для знака {sign} на {date_type} ({horoscope_type} аспект):\n\n"
    horoscopes = {
        "today": {
            "general": "Сегодня вас ждет день, полный неожиданных открытий и приятных встреч.",
            "love": "В личных отношениях возможны новые романтические переживания.",
            "business": "На работе будьте внимательны к деталям, чтобы избежать недоразумений.",
            "health": "Уделите внимание своему самочувствию, возможно, потребуется отдых."
        },
        "tomorrow": {
            "general": "Завтрашний день принесет спокойствие и возможность завершить начатые дела.",
            "love": "День благоприятен для укрепления связей и взаимопонимания.",
            "business": "Ожидайте новых предложений, которые могут быть очень выгодными.",
            "health": "Энергии будет достаточно для всех ваших планов."
        },
        "week": {
            "general": "На этой неделе сосредоточьтесь на своих долгосрочных целях. Возможно, придется потрудиться больше обычного, но результат того стоит.",
            "love": "Ваши отношения укрепятся, если вы проявите больше внимания и заботы к близким.",
            "business": "Будьте открыты к сотрудничеству, новые партнерства принесут успех.",
            "health": "Ваша выносливость на высоте, но не забывайте о сбалансированном питании."
        }
    }
    return base_horoscope + horoscopes.get(date_type, {}).get(horoscope_type, "Гороскоп пока недоступен.")

# --- Проверка оплаты (заглушка) ---
async def check_payment_status(user_id: int):
    # Здесь должна быть реальная логика проверки оплаты:
    # - Для AdsGram: обращение к API AdsGram с order_id
    # - Для TON: проверка транзакций на блокчейне TON (сложнее)
    # Для примера, всегда возвращаем True для демонстрации
    logger.info(f"Проверка оплаты для пользователя {user_id}...")
    # Здесь можно добавить задержку, чтобы имитировать проверку
    await asyncio.sleep(5)
    return True # В реальном приложении здесь будет логика проверки

# --- ADSGRAM Просмотры ---
async def show_ads(user_id: int):
    if not ADSGRAM_API_KEY:
        logger.warning("ADSGRAM_API_KEY не установлен. Реклама не будет показана.")
        return

    # Логика показа рекламы через AdsGram API (если применимо и поддерживается aiogram)
    # Это может быть вызов внешнего API AdsGram для показа рекламы
    # или просто счетчик просмотров в вашей БД, который уменьшается
    
    # Для примера, просто логируем
    logger.info(f"Реклама показана пользователю {user_id} через AdsGram (API Key: {ADSGRAM_API_KEY[:5]}...)")
    # В реальном приложении здесь будет вызов AdsGram API

# --- Обработчики команд и сообщений ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    if not user_data:
        await update_user_data(user_id, {"user_id": user_id, "daily_horoscopes_given": 0})
        logger.info(f"Новый пользователь добавлен в БД: {user_id}")
    
    await message.answer(
        "Привет! Я бот-гороскоп. Выбери свой знак зодиака:",
        reply_markup=get_main_keyboard()
    )
    await state.set_state(UserState.choosing_sign)

@dp.message(F.text, UserState.choosing_sign)
async def process_chosen_sign(message: types.Message, state: FSMContext):
    signs = [
        "♈ Овен", "♉ Телец", "♊ Близнецы", "♋ Рак", "♌ Лев", "♍ Дева",
        "♎ Весы", "♏ Скорпион", "♐ Стрелец", "♑ Козерог", "♒ Водолей", "♓ Рыбы"
    ]
    chosen_sign = message.text

    if chosen_sign == "⭐️ Выбрать свой знак":
        await message.answer("Для выбора своего знака, пожалуйста, укажите вашу дату рождения (день.месяц.год):")
        # Здесь можно перейти в новое состояние для обработки даты рождения
        await state.set_state(UserState.waiting_for_birth_date) # Пример нового состояния
        return
        
    if chosen_sign not in signs:
        await message.answer("Пожалуйста, выберите знак из предложенных на клавиатуре.")
        return

    await state.update_data(chosen_sign=chosen_sign)
    await message.answer(
        f"Отлично! Вы выбрали {chosen_sign}. Теперь выберите, на какой период вам нужен гороскоп:",
        reply_markup=get_date_keyboard()
    )
    await state.set_state(UserState.choosing_date)

# Обработчик для выбора даты рождения
@dp.message(F.text, UserState.waiting_for_birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    # Очень простая валидация даты рождения (ДД.ММ.ГГГГ)
    date_match = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", message.text)
    if not date_match:
        await message.answer("Пожалуйста, введите дату в формате ДД.ММ.ГГГГ (например, 01.01.2000).")
        return
    
    day, month, year = map(int, date_match.groups())

    try:
        birth_date = datetime(year, month, day)
    except ValueError:
        await message.answer("Неверная дата. Проверьте день, месяц или год.")
        return

    # Логика определения знака зодиака по дате рождения
    def get_zodiac_sign(day, month):
        if (month == 3 and day >= 21) or (month == 4 and day <= 19): return "♈ Овен"
        if (month == 4 and day >= 20) or (month == 5 and day <= 20): return "♉ Телец"
        if (month == 5 and day >= 21) or (month == 6 and day <= 20): return "♊ Близнецы"
        if (month == 6 and day >= 21) or (month == 7 and day <= 22): return "♋ Рак"
        if (month == 7 and day >= 23) or (month == 8 and day <= 22): return "♌ Лев"
        if (month == 8 and day >= 23) or (month == 9 and day <= 22): return "♍ Дева"
        if (month == 9 and day >= 23) or (month == 10 and day <= 22): return "♎ Весы"
        if (month == 10 and day >= 23) or (month == 11 and day <= 21): return "♏ Скорпион"
        if (month == 11 and day >= 22) or (month == 12 and day <= 21): return "♐ Стрелец"
        if (month == 12 and day >= 22) or (month == 1 and day <= 19): return "♑ Козерог"
        if (month == 1 and day >= 20) or (month == 2 and day <= 18): return "♒ Водолей"
        if (month == 2 and day >= 19) or (month == 3 and day <= 20): return "♓ Рыбы"
        return "Неизвестный знак" # Не должен сработать при корректных датах

    zodiac_sign = get_zodiac_sign(day, month)

    await state.update_data(chosen_sign=zodiac_sign)
    await message.answer(
        f"Ваш знак зодиака: {zodiac_sign}. Теперь выберите, на какой период вам нужен гороскоп:",
        reply_markup=get_date_keyboard()
    )
    await state.set_state(UserState.choosing_date)

@dp.callback_query(F.data.startswith("date_"), UserState.choosing_date)
async def process_chosen_date(callback: types.CallbackQuery, state: FSMContext):
    date_type = callback.data.split("_")[1] # 'today', 'tomorrow', 'week'
    await state.update_data(chosen_date=date_type)
    await callback.message.edit_text(
        f"Вы выбрали гороскоп на {date_type}. Теперь выберите тип гороскопа:",
        reply_markup=get_horoscope_type_keyboard()
    )
    await callback.answer()
    await state.set_state(UserState.choosing_type)

@dp.callback_query(F.data.startswith("type_"), UserState.choosing_type)
async def process_chosen_type(callback: types.CallbackQuery, state: FSMContext):
    horoscope_type = callback.data.split("_")[1] # 'general', 'love', 'business', 'health'
    data = await state.get_data()
    chosen_sign = data.get("chosen_sign")
    chosen_date = data.get("chosen_date")
    user_id = callback.from_user.id

    user_db_data = await get_user_data(user_id)
    horoscopes_given_today = user_db_data.get("daily_horoscopes_given", 0)
    last_horoscope_date = user_db_data.get("last_horoscope_date")

    today = datetime.now().date()

    if last_horoscope_date and last_horoscope_date < today:
        # Сброс счетчика, если день изменился
        horoscopes_given_today = 0
        await update_user_data(user_id, {"daily_horoscopes_given": 0, "last_horoscope_date": today})
        
    if horoscopes_given_today >= 2: # Ограничение на 2 бесплатных гороскопа в день
        await callback.message.edit_text(
            "Вы использовали все бесплатные гороскопы на сегодня. Для получения дополнительного гороскопа, пожалуйста, оплатите.",
            reply_markup=get_payment_keyboard(user_id)
        )
        await state.set_state(UserState.waiting_for_payment)
        await callback.answer()
        return

    horoscope_text = await generate_horoscope(chosen_sign, chosen_date, horoscope_type)
    
    # Обновляем счетчик бесплатных гороскопов
    await update_user_data(user_id, {
        "daily_horoscopes_given": horoscopes_given_today + 1,
        "last_horoscope_date": today
    })

    await callback.message.edit_text(
        f"**Ваш гороскоп:**\n\n{horoscope_text}",
        reply_markup=get_main_menu_keyboard() # Кнопка для возврата в главное меню
    )
    await callback.answer()
    await state.clear() # Сброс состояния после получения гороскопа
    
    # Дополнительная функция для показа рекламы после получения гороскопа
    await show_ads(user_id)


@dp.callback_query(F.data == "check_payment", UserState.waiting_for_payment)
async def check_payment(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.edit_text("Проверяю оплату... Это может занять до 30 секунд.")
    await callback.answer()

    if await check_payment_status(user_id):
        # Если оплата подтверждена, разрешаем еще один гороскоп
        await update_user_data(user_id, {"daily_horoscopes_given": 0}) # Сброс счетчика после оплаты
        await callback.message.answer(
            "Оплата подтверждена! Теперь вы можете получить еще один гороскоп. Выберите знак зодиака:",
            reply_markup=get_main_keyboard()
        )
        await state.set_state(UserState.choosing_sign)
    else:
        await callback.message.answer(
            "Оплата не найдена. Попробуйте еще раз или выберите другой способ оплаты.",
            reply_markup=get_payment_keyboard(user_id)
        )

@dp.callback_query(F.data == "start_over")
async def start_over(callback: types.CallbackQuery, state: FSMContext):
    await state.clear() # Сбрасываем все состояния
    await callback.message.answer(
        "Вы вернулись в главное меню. Выберите свой знак зодиака:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# --- Функции запуска и завершения ---

# Функция для установки вебхука и инициализации БД
async def on_startup(passed_bot: Bot) -> None:
    logger.info("Инициализация...")
    await init_mongodb() # Инициализируем MongoDB
    logger.info("Установка вебхука...")
    if WEBHOOK_URL:
        # Устанавливаем вебхук. drop_pending_updates=True очищает старые обновления,
        # чтобы бот не обрабатывал их после перезапуска.
        await passed_bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        logger.info(f"Вебхук установлен на: {WEBHOOK_URL}")
    else:
        logger.warning("WEBHOOK_URL не установлен. Вебхук не будет настроен. Убедитесь, что переменная окружения WEBHOOK_HOST или RENDER_EXTERNAL_HOSTNAME задана.")


# Закрытие соединения с БД при завершении
async def on_shutdown(passed_bot: Bot) -> None:
    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB соединение закрыто.")
    logger.info("Завершение работы...")


# Основная точка входа для локального запуска (если WEBHOOK_URL не установлен)
async def main():
    await on_startup(bot)
    try:
        if not WEBHOOK_URL: # Если WEBHOOK_URL не задан, это локальный запуск
            logger.info("Запуск бота в режиме long-polling (для локальной разработки).")
            await dp.start_polling(bot)
        else:
            logger.info("Бот настроен для вебхуков. Ожидание входящих запросов от Uvicorn/ASGI сервера.")
            # Для вебхуков, Uvicorn сам вызывает ASGI-приложение, которое мы настроили в api/index.py.
            # Здесь нет необходимости запускать что-либо дополнительно.
            pass # Основная логика запускается через ASGI сервер
    finally:
        await on_shutdown(bot)

# Этот блок будет выполняться только при прямом запуске astro.py
if __name__ == "__main__":
    # Если вы хотите тестировать локально через long-polling, убедитесь, что WEBHOOK_HOST не установлен в .env
    # или его значение пустое, чтобы WEBHOOK_URL стал None.
    # Если WEBHOOK_HOST установлен, то бот попытается использовать вебхуки даже локально,
    # что может привести к ошибкам, если нет публично доступного URL.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
