import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import pika

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.messaging import QUEUE_PAGAMENTO, RABBITMQ_URL, get_connection, setup_pagamento_consumer
from shared.activity import publicar_atividade

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [Pagamento] %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

TAXA_FALHA = float(os.getenv("TAXA_FALHA", "0.3"))


def processar_pagamento(evento: dict) -> None:
  id_pedido = evento.get("id_pedido")
  valor_total = evento.get("valor_total", 0)

  time.sleep(random.uniform(0.5, 1.5))

  if random.random() < TAXA_FALHA:
    logger.warning("Pagamento FALHOU para pedido %s (valor: R$ %.2f)", id_pedido, valor_total)
    publicar_atividade(
      "pagamento",
      f"Pagamento FALHOU para pedido {id_pedido} (valor: R$ {valor_total:.2f})",
      nivel="error",
      id_pedido=id_pedido,
      detalhes={"valor_total": valor_total},
    )
    return

  logger.info("Pagamento APROVADO para pedido %s (valor: R$ %.2f)", id_pedido, valor_total)
  publicar_atividade(
    "pagamento",
    f"Pagamento APROVADO para pedido {id_pedido} (valor: R$ {valor_total:.2f})",
    nivel="success",
    id_pedido=id_pedido,
    detalhes={"valor_total": valor_total},
  )


def on_message(channel, method, properties, body):
  try:
    evento = json.loads(body)
    logger.info("Evento PedidoCriado recebido: %s", evento.get("id_pedido"))
    publicar_atividade(
      "pagamento",
      f"Evento PedidoCriado recebido — iniciando processamento",
      nivel="info",
      id_pedido=evento.get("id_pedido"),
    )
    processar_pagamento(evento)
    channel.basic_ack(delivery_tag=method.delivery_tag)
  except json.JSONDecodeError:
    logger.error("Mensagem malformada recebida. Descartando.")
    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
  except Exception:
    logger.exception("Erro ao processar pagamento")
    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
  logger.info("Iniciando Servico de Pagamento...")
  logger.info("Conectando ao RabbitMQ em %s", RABBITMQ_URL)

  while True:
    try:
      connection = get_connection()
      channel = connection.channel()
      setup_pagamento_consumer(channel)
      channel.basic_qos(prefetch_count=1)
      channel.basic_consume(queue=QUEUE_PAGAMENTO, on_message_callback=on_message)
      logger.info("Aguardando eventos PedidoCriado na fila %s...", QUEUE_PAGAMENTO)
      channel.start_consuming()
    except pika.exceptions.AMQPConnectionError:
      logger.warning("RabbitMQ indisponivel. Tentando reconectar em 5s...")
      time.sleep(5)


if __name__ == "__main__":
  main()
