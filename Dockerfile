# trading-django-bakend/Dockerfile
FROM python:3.13-slim

# set workdir
WORKDIR /app

# install system deps
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy application code
COPY . .

# collect static (if needed)
RUN python manage.py collectstatic --no-input

# expose port
EXPOSE 8000

# startup
CMD ["gunicorn", "trading_platform.wsgi:application", "--bind", "0.0.0.0:8000"]
