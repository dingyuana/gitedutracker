from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.api.routes import router
from app.scheduler import start_scheduler

app = FastAPI(title="学生 GitHub 日报追踪器")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.state.templates = templates
app.include_router(router)
start_scheduler()
