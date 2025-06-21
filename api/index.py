# api/index.py
from aiohttp import web
from starlette.applications import Starlette
from starlette.routing import Mount

# Создаем экземпляр aiohttp приложения
_aiohttp_app_instance = web.Application()

async def aiohttp_handle(request):
    # Этот обработчик принадлежит приложению aiohttp
    return web.Response(text="Hello from Astro Bot!")

_aiohttp_app_instance.router.add_get('/', aiohttp_handle)

# Создаем приложение Starlette и монтируем в него aiohttp приложение
# Приложение Starlette будет основной точкой входа ASGI для Uvicorn
app = Starlette(
    routes=[
        Mount("/", app=_aiohttp_app_instance), # Монтируем aiohttp приложение в корневой путь
    ]
)
