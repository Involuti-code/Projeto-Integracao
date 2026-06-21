FROM python:3.12-slim

WORKDIR /app

COPY pagamento/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared ./shared
COPY pagamento ./pagamento

ENV PYTHONPATH=/app
WORKDIR /app/pagamento

CMD ["python", "main.py"]
