FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONIOENCODING=utf-8
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
