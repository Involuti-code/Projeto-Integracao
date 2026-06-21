FROM python:3.12-slim

WORKDIR /app

COPY estoque/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared ./shared
COPY estoque ./estoque

ENV PYTHONPATH=/app
WORKDIR /app/estoque

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
