from aiohttp import web

# Ваши существующие роуты
routes = web.RouteTableDef()

@routes.get("/")
async def handler(request):
    return web.Response(text="Hello")

def create_app():
    app = web.Application()
    app.add_routes(routes)
    return app
