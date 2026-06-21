import logging
import os
import sys
from pathlib import Path
from typing import List

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from shared.activity import publicar_atividade
from shared.messaging import get_connection, publicar_pedido_criado

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [Checkout] %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

ESTOQUE_BASE_URL = os.getenv("ESTOQUE_BASE_URL", "http://localhost:8001")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

PRECOS = {
  "produto_A": 29.90,
  "produto_B": 49.90,
  "produto_C": 19.90,
}

circuit_breaker = CircuitBreaker(
  failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "3")),
  recovery_timeout=int(os.getenv("CB_RECOVERY_TIMEOUT", "30")),
)


class ItemPedido(BaseModel):
  produto_id: str
  quantidade: int


class Pedido(BaseModel):
  id_pedido: str
  cliente: str = "cliente@email.com"
  itens: List[ItemPedido]


class PedidoResponse(BaseModel):
  id_pedido: str
  status: str
  valor_total: float
  mensagem: str


app = FastAPI(title="Checkout API", version="2.0.0")


def calcular_valor_total(itens: List[ItemPedido]) -> float:
  total = 0.0
  for item in itens:
    if item.produto_id not in PRECOS:
      raise HTTPException(
        status_code=400,
        detail=f"Produto {item.produto_id} nao possui preco cadastrado.",
      )
    total += PRECOS[item.produto_id] * item.quantidade
  return round(total, 2)


async def verificar_estoque(client: httpx.AsyncClient, item: ItemPedido) -> None:
  circuit_breaker.before_call()

  try:
    resp = await client.get(
      f"{ESTOQUE_BASE_URL}/produtos/{item.produto_id}/disponibilidade",
      params={"quantidade": item.quantidade},
      timeout=5.0,
    )
  except httpx.RequestError:
    circuit_breaker.record_failure()
    logger.error("Falha na comunicacao com o Estoque (circuit breaker: %s)", circuit_breaker.get_state())
    publicar_atividade(
      "checkout",
      "Falha na comunicacao com o Estoque",
      nivel="error",
      detalhes={"circuit_breaker": circuit_breaker.get_state()},
    )
    raise HTTPException(
      status_code=502,
      detail="Nao foi possivel contactar o Servico de Estoque.",
    )

  if resp.status_code >= 500:
    circuit_breaker.record_failure()
    logger.error("Estoque retornou erro %s (circuit breaker: %s)", resp.status_code, circuit_breaker.get_state())
    publicar_atividade(
      "checkout",
      f"Estoque retornou erro HTTP {resp.status_code}",
      nivel="error",
      detalhes={"circuit_breaker": circuit_breaker.get_state()},
    )
    raise HTTPException(
      status_code=502,
      detail="Servico de Estoque indisponivel.",
    )

  circuit_breaker.record_success()

  if resp.status_code == 404:
    raise HTTPException(
      status_code=400,
      detail=f"Produto {item.produto_id} nao existe no estoque.",
    )

  if resp.status_code == 400:
    raise HTTPException(
      status_code=400,
      detail=f"Requisicao invalida para o estoque: {resp.json().get('detail')}",
    )

  if resp.status_code != 200:
    raise HTTPException(
      status_code=502,
      detail="Falha ao verificar disponibilidade no Servico de Estoque.",
    )

  dados_estoque = resp.json()
  if not dados_estoque.get("disponivel"):
    raise HTTPException(
      status_code=409,
      detail=f"Estoque insuficiente para o produto {item.produto_id}.",
    )


def publicar_evento_pedido_criado(evento: dict) -> None:
  try:
    connection = get_connection()
    channel = connection.channel()
    publicar_pedido_criado(channel, evento)
    connection.close()
    logger.info("Evento PedidoCriado publicado para o pedido %s", evento["id_pedido"])
  except Exception:
    logger.exception("Falha ao publicar evento PedidoCriado no RabbitMQ")
    raise HTTPException(
      status_code=503,
      detail="Pedido criado, mas falha ao publicar evento para processamento assincrono.",
    )


@app.post(
  "/pedidos",
  response_model=PedidoResponse,
  summary="Criar pedido",
  description=(
    "Recebe uma requisicao de compra, verifica o estoque de forma sincrona "
    "(com Circuit Breaker) e publica o evento PedidoCriado no RabbitMQ."
  ),
)
async def criar_pedido(pedido: Pedido):
  if not pedido.itens:
    raise HTTPException(status_code=400, detail="O pedido deve conter ao menos um item.")

  for item in pedido.itens:
    if item.quantidade <= 0:
      raise HTTPException(
        status_code=400,
        detail=f"Quantidade invalida para o produto {item.produto_id}. Deve ser maior que zero.",
      )

  try:
    circuit_breaker.before_call()
  except CircuitBreakerOpenError as exc:
    logger.warning("Requisicao bloqueada pelo Circuit Breaker")
    publicar_atividade("checkout", str(exc), nivel="warning")
    raise HTTPException(status_code=503, detail=str(exc))

  valor_total = calcular_valor_total(pedido.itens)

  async with httpx.AsyncClient() as client:
    for item in pedido.itens:
      await verificar_estoque(client, item)

  evento = {
    "id_pedido": pedido.id_pedido,
    "cliente": pedido.cliente,
    "itens": [item.model_dump() for item in pedido.itens],
    "valor_total": valor_total,
  }

  publicar_evento_pedido_criado(evento)
  logger.info("Pedido %s criado com valor total R$ %.2f", pedido.id_pedido, valor_total)
  publicar_atividade(
    "checkout",
    f"Pedido criado com valor total R$ {valor_total:.2f}. Evento PedidoCriado publicado no RabbitMQ.",
    nivel="success",
    id_pedido=pedido.id_pedido,
    detalhes={"valor_total": valor_total, "cliente": pedido.cliente},
  )

  return PedidoResponse(
    id_pedido=pedido.id_pedido,
    status="criado",
    valor_total=valor_total,
    mensagem="Pedido criado com sucesso. Evento PedidoCriado publicado.",
  )


@app.get("/health/circuit-breaker", summary="Status do Circuit Breaker")
def circuit_breaker_status():
  return {
    "estado": circuit_breaker.get_state(),
    "falhas_consecutivas": circuit_breaker.failure_count,
    "limite_falhas": circuit_breaker.failure_threshold,
    "tempo_recuperacao_segundos": circuit_breaker.recovery_timeout,
  }


@app.get("/", summary="Status do servico de checkout")
def status():
  return {"status": "ok", "servico": "checkout", "rabbitmq": RABBITMQ_URL}
