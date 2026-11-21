from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
import uvicorn

from scripts.seed_demo import seed
from src.config.migrate import upgrade
from src.middlewares.request import limit_body, request_headers
from src.routes.workflow import router


@asynccontextmanager
async def lifespan(app):
    upgrade()
    if os.getenv('SEED_DEMO', 'true').lower() == 'true':
        try:
            seed()
        except Exception:
            logging.exception('Demo seeding failed')
    yield


app = FastAPI(title='Database business workflow', lifespan=lifespan)
app.middleware('http')(limit_body)
app.middleware('http')(request_headers)
app.include_router(router)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
