import asyncio
from app.main import lifespan, app

async def test():
    async with lifespan(app):
        print('DB Success!')

if __name__ == "__main__":
    asyncio.run(test())
