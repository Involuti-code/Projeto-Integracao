import json
import logging
from datetime import datetime, timezone
from typing import Any

import pika

from shared.messaging import QUEUE_ATIVIDADE, get_connection

logger = logging.getLogger(__name__)


def publicar_atividade(
  servico: str,
  mensagem: str,
  nivel: str = "info",
  id_pedido: str | None = None,
  detalhes: dict[str, Any] | None = None,
) -> None:
  try:
    evento = {
      "timestamp": datetime.now(timezone.utc).isoformat(),
      "servico": servico,
      "nivel": nivel,
      "mensagem": mensagem,
      "id_pedido": id_pedido,
      "detalhes": detalhes or {},
    }
    connection = get_connection()
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_ATIVIDADE, durable=False)
    channel.basic_publish(
      exchange="",
      routing_key=QUEUE_ATIVIDADE,
      body=json.dumps(evento, ensure_ascii=False),
      properties=pika.BasicProperties(content_type="application/json"),
    )
    connection.close()
  except Exception:
    logger.debug("Falha ao publicar atividade para o monitor", exc_info=True)
