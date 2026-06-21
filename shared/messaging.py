import json
import os
from typing import Any

import pika

EXCHANGE_PEDIDOS = "pedidos"
ROUTING_KEY_PEDIDO_CRIADO = "pedido.criado"
QUEUE_PAGAMENTO = "pagamento.pedido.criado"
QUEUE_NOTIFICACAO = "notificacao.pedido.criado"
DLX_NOTIFICACAO = "notificacao.dlx"
QUEUE_NOTIFICACAO_DLQ = "notificacao.dlq"
QUEUE_ATIVIDADE = "atividade.logs"

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def setup_atividade_consumer(channel: pika.channel.Channel) -> None:
  channel.queue_declare(queue=QUEUE_ATIVIDADE, durable=False)


def get_connection() -> pika.BlockingConnection:
  params = pika.URLParameters(RABBITMQ_URL)
  return pika.BlockingConnection(params)


def setup_publisher(channel: pika.channel.Channel) -> None:
  channel.exchange_declare(exchange=EXCHANGE_PEDIDOS, exchange_type="topic", durable=True)


def setup_pagamento_consumer(channel: pika.channel.Channel) -> None:
  channel.exchange_declare(exchange=EXCHANGE_PEDIDOS, exchange_type="topic", durable=True)
  channel.queue_declare(queue=QUEUE_PAGAMENTO, durable=True)
  channel.queue_bind(
    queue=QUEUE_PAGAMENTO,
    exchange=EXCHANGE_PEDIDOS,
    routing_key=ROUTING_KEY_PEDIDO_CRIADO,
  )


def setup_notificacao_consumer(channel: pika.channel.Channel) -> None:
  channel.exchange_declare(exchange=EXCHANGE_PEDIDOS, exchange_type="topic", durable=True)
  channel.exchange_declare(exchange=DLX_NOTIFICACAO, exchange_type="direct", durable=True)
  channel.queue_declare(queue=QUEUE_NOTIFICACAO_DLQ, durable=True)
  channel.queue_bind(
    queue=QUEUE_NOTIFICACAO_DLQ,
    exchange=DLX_NOTIFICACAO,
    routing_key=QUEUE_NOTIFICACAO_DLQ,
  )
  channel.queue_declare(
    queue=QUEUE_NOTIFICACAO,
    durable=True,
    arguments={
      "x-dead-letter-exchange": DLX_NOTIFICACAO,
      "x-dead-letter-routing-key": QUEUE_NOTIFICACAO_DLQ,
    },
  )
  channel.queue_bind(
    queue=QUEUE_NOTIFICACAO,
    exchange=EXCHANGE_PEDIDOS,
    routing_key=ROUTING_KEY_PEDIDO_CRIADO,
  )


def publicar_pedido_criado(channel: pika.channel.Channel, evento: dict[str, Any]) -> None:
  setup_publisher(channel)
  channel.basic_publish(
    exchange=EXCHANGE_PEDIDOS,
    routing_key=ROUTING_KEY_PEDIDO_CRIADO,
    body=json.dumps(evento, ensure_ascii=False),
    properties=pika.BasicProperties(
      delivery_mode=2,
      content_type="application/json",
    ),
  )
