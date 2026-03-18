from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from src.api.routers import auth, cart, catalog, favorites, health, orders


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


app = FastAPI(
    title="NeoMarket B2C API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(cart.router)
app.include_router(favorites.router)
app.include_router(orders.router)
app.include_router(catalog.router)
