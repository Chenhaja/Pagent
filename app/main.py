from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging(get_settings())

app = FastAPI(title="Patent Agent")
app.include_router(router)
