FROM python:3.12-slim

WORKDIR /app

COPY notificacao/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared ./shared
COPY notificacao ./notificacao

ENV PYTHONPATH=/app
WORKDIR /app/notificacao

CMD ["python", "main.py"]
