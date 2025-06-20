# api/index.py
from aiohttp import web

# Определяем функцию-фабрику, которая будет создавать и возвращать приложение
# Теперь эта функция и будет нашим ASGI-приложением для Uvicorn
def create_app():
    app_instance = web.Application()

    async def handle(request):
        return web.Response(text="Hello from Astro Bot!")

    app_instance.router.add_get('/', handle)
    return app_instance

# Uvicorn будет вызывать эту функцию (app) с флагом --factory
app = create_app
