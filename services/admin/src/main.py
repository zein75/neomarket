from fastapi import FastAPI

from src.api.routers import moderation


app = FastAPI(title="NeoMarket Moderation API", version="0.1.0")

app.include_router(moderation.router)
