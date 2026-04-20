from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(
    title="encodr API",
    version="0.1.0",
    description="API scaffold for the encodr media ingestion preparation service.",
)
app.include_router(router)

