# api/index.py
from aiohttp import web

# Просто создаем базовый объект приложения aiohttp
app = web.Application()

# Добавим минимальный обработчик для проверки, что приложение запускается
async def handle(request):
    return web.Response(text="Hello from Astro Bot!")

app.router.add_get('/', handle)
