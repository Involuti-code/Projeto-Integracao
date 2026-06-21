import asyncio
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pika
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.messaging import QUEUE_ATIVIDADE, RABBITMQ_URL, get_connection, setup_atividade_consumer

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [Monitor] %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MAX_EVENTOS = int(os.getenv("MAX_EVENTOS", "200"))
eventos: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTOS)
subscribers: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None


def _notificar_assinantes(evento: dict[str, Any]) -> None:
  eventos.append(evento)
  if _loop is None or not _loop.is_running():
    return
  for fila in list(subscribers):
    asyncio.run_coroutine_threadsafe(fila.put(evento), _loop)


def _consumir_atividades() -> None:
  while True:
    try:
      connection = get_connection()
      channel = connection.channel()
      setup_atividade_consumer(channel)

      def on_message(channel, method, properties, body):
        try:
          evento = json.loads(body)
          _notificar_assinantes(evento)
        except json.JSONDecodeError:
          logger.warning("Evento de atividade malformado ignorado")
        channel.basic_ack(delivery_tag=method.delivery_tag)

      channel.basic_qos(prefetch_count=10)
      channel.basic_consume(queue=QUEUE_ATIVIDADE, on_message_callback=on_message)
      logger.info("Consumindo fila %s em %s", QUEUE_ATIVIDADE, RABBITMQ_URL)
      channel.start_consuming()
    except pika.exceptions.AMQPConnectionError:
      logger.warning("RabbitMQ indisponivel. Reconectando em 5s...")
      time.sleep(5)
    except Exception:
      logger.exception("Erro no consumidor de atividades. Reconectando em 5s...")
      time.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
  global _loop
  _loop = asyncio.get_running_loop()
  thread = threading.Thread(target=_consumir_atividades, daemon=True)
  thread.start()
  yield


app = FastAPI(title="Monitor de Atividades", version="1.0.0", lifespan=lifespan)
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)


@app.get("/", summary="Status do monitor")
def status():
  return {
    "status": "ok",
    "servico": "monitor",
    "eventos_em_memoria": len(eventos),
    "assinantes_sse": len(subscribers),
  }


@app.get("/eventos", summary="Ultimos eventos de atividade")
def listar_eventos(limit: int = 100):
  limite = max(1, min(limit, MAX_EVENTOS))
  return {"eventos": list(eventos)[-limite:]}


@app.get("/eventos/stream", summary="Stream SSE de eventos em tempo real")
async def stream_eventos():
  fila: asyncio.Queue = asyncio.Queue()
  subscribers.append(fila)

  async def gerar():
    try:
      yield ": connected\n\n"
      while True:
        try:
          evento = await asyncio.wait_for(fila.get(), timeout=15.0)
          yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
          yield ": keepalive\n\n"
    finally:
      if fila in subscribers:
        subscribers.remove(fila)

  return StreamingResponse(
    gerar(),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  )
