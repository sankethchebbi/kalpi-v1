"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routes import auth_routes, broker_routes, execute_routes, settings_routes, ws_routes

app = FastAPI(title="Portfolio Trade Execution Engine")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth_routes.router)
app.include_router(settings_routes.router)
app.include_router(broker_routes.router)
app.include_router(execute_routes.router)
app.include_router(ws_routes.router)


# Serve the single-page frontend at /
@app.get("/")
def index():
    return FileResponse("frontend/index.html")
