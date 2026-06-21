import json
import logging
import os
import sys
import time
from pathlib import Path

import pika

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.messaging import (
  QUEUE_NOTIFICACAO,
  QUEUE_NOTIFICACAO_DLQ,
  RABBITMQ_URL,
  get_connection,
  setup_notificacao_consumer,
)
from shared.activity import publicar_atividade

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [Notificacao] %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
SIMULAR_FALHA = os.getenv("SIMULAR_FALHA", "false").lower() == "true"


def enviar_notificacao(evento: dict) -> None:
  if SIMULAR_FALHA:
    raise RuntimeError("Falha simulada no envio de notificacao")

  id_pedido = evento.get("id_pedido")
  cliente = evento.get("cliente", "cliente@email.com")
  logger.info("E-mail enviado para %s confirmando o pedido %s", cliente, id_pedido)
  publicar_atividade(
    "notificacao",
    f"E-mail enviado para {cliente} confirmando o pedido {id_pedido}",
    nivel="success",
    id_pedido=id_pedido,
    detalhes={"cliente": cliente},
  )


def get_retry_count(properties: pika.BasicProperties) -> int:
  if not properties.headers:
    return 0
  return int(properties.headers.get("x-retry-count", 0))


def on_message(channel, method, properties, body):
  retry_count = get_retry_count(properties)

  try:
    evento = json.loads(body)
    logger.info(
      "Evento PedidoCriado recebido: %s (tentativa %d/%d)",
      evento.get("id_pedido"),
      retry_count + 1,
      MAX_RETRIES,
    )
    publicar_atividade(
      "notificacao",
      f"Evento PedidoCriado recebido (tentativa {retry_count + 1}/{MAX_RETRIES})",
      nivel="info",
      id_pedido=evento.get("id_pedido"),
    )
    enviar_notificacao(evento)
    channel.basic_ack(delivery_tag=method.delivery_tag)
  except json.JSONDecodeError:
    logger.error("Mensagem malformada. Enviando para DLQ.")
    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
  except Exception:
    logger.exception("Falha ao enviar notificacao")

    if retry_count + 1 >= MAX_RETRIES:
      logger.error(
        "Numero maximo de tentativas (%d) atingido. Mensagem enviada para DLQ.",
        MAX_RETRIES,
      )
      publicar_atividade(
        "notificacao",
        f"Numero maximo de tentativas ({MAX_RETRIES}) atingido. Mensagem enviada para DLQ.",
        nivel="error",
        detalhes={"fila_dlq": QUEUE_NOTIFICACAO_DLQ},
      )
      channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
      return

    headers = dict(properties.headers or {})
    headers["x-retry-count"] = retry_count + 1

    channel.basic_publish(
      exchange="",
      routing_key=QUEUE_NOTIFICACAO,
      body=body,
      properties=pika.BasicProperties(
        delivery_mode=2,
        content_type="application/json",
        headers=headers,
      ),
    )
    channel.basic_ack(delivery_tag=method.delivery_tag)
    logger.info("Mensagem reenfileirada para nova tentativa (%d/%d).", retry_count + 1, MAX_RETRIES)
    publicar_atividade(
      "notificacao",
      f"Falha no envio — reenfileirando tentativa {retry_count + 1}/{MAX_RETRIES}",
      nivel="warning",
    )


def main():
  logger.info("Iniciando Servico de Notificacao...")
  logger.info("MAX_RETRIES=%d | SIMULAR_FALHA=%s", MAX_RETRIES, SIMULAR_FALHA)
  logger.info("Conectando ao RabbitMQ em %s", RABBITMQ_URL)

  while True:
    try:
      connection = get_connection()
      channel = connection.channel()
      setup_notificacao_consumer(channel)
      channel.basic_qos(prefetch_count=1)
      channel.basic_consume(queue=QUEUE_NOTIFICACAO, on_message_callback=on_message)
      logger.info("Aguardando eventos PedidoCriado na fila %s...", QUEUE_NOTIFICACAO)
      logger.info("DLQ configurada na fila %s", QUEUE_NOTIFICACAO_DLQ)
      channel.start_consuming()
    except pika.exceptions.AMQPConnectionError:
      logger.warning("RabbitMQ indisponivel. Tentando reconectar em 5s...")
      time.sleep(5)


if __name__ == "__main__":
  main()
