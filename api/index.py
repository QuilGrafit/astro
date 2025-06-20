# api/index.py
from aiohttp import web

# Переменная для хранения единственного экземпляра приложения aiohttp
_aiohttp_app_instance = None

# Эта асинхронная функция будет нашим прямым ASGI-приложением
async def app(scope, receive, send):
    global _aiohttp_app_instance

    # Создаем экземпляр aiohttp приложения только один раз
    if _aiohttp_app_instance is None:
        _aiohttp_app_instance = web.Application()

        # Добавляем маршрут и обработчик
        async def handle(request):
            return web.Response(text="Hello from Astro Bot!")

        _aiohttp_app_instance.router.add_get('/', handle)
        
        # Опционально: если у вас будут функции запуска/остановки для aiohttp
        # _aiohttp_app_instance.on_startup.append(ваш_on_startup_функция)
        # _aiohttp_app_instance.on_shutdown.append(ваш_on_shutdown_функция)

    # Теперь вызываем наш aiohttp-экземпляр напрямую с полным набором ASGI-аргументов
    await _aiohttp_app_instance(scope, receive, send)
