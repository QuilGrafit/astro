# api/index.py
from aiohttp import web

# Определяем функцию-фабрику, которая будет создавать и возвращать приложение
def create_app():
    app = web.Application()

    async def handle(request):
        return web.Response(text="Hello from Astro Bot!")

    app.router.add_get('/', handle)
    return app

# app теперь будет не экземпляром приложения, а функцией-фабрикой
app = create_app()
