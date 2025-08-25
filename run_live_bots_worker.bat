@echo off
REM Dedicated Celery worker for live bot runs (Windows)
cd /d c:\Users\ehsan\trading-platform-root
if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
)
mkdir logs 2>nul
celery -A trading_platform.celery_app worker -Q live_bots -l info -P solo -c 1 --logfile=logs\celery_live_bots.log
