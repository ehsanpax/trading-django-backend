@echo off
cd /d C:\trading_platform\trading-django-backend
call .\.venv\Scripts\activate.bat

REM launch Daphne, redirecting Twisted internals and Python stdout
python -m daphne ^
  --bind 0.0.0.0 --port 8000 ^
  --access-log logs\daphne-access.log ^
  --error-log-file logs\daphne-error.log ^
  trading_platform.asgi:application ^
  >> logs\application.log 2>> logs\error.log


