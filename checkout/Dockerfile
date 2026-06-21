FROM python:3.12-slim

WORKDIR /app

COPY checkout/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared ./shared
COPY checkout ./checkout

ENV PYTHONPATH=/app
WORKDIR /app/checkout

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
