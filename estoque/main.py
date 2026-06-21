import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.activity import publicar_atividade

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [Estoque] %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Servico de Estoque", version="2.0.0")

SIMULAR_FALHA = os.getenv("SIMULAR_FALHA", "false").lower() == "true"
_falha_ativa = SIMULAR_FALHA


class DisponibilidadeResponse(BaseModel):
  produto_id: str
  quantidade_solicitada: int
  disponivel: bool
  quantidade_estoque: int


ESTOQUE = {
  "produto_A": 10,
  "produto_B": 5,
  "produto_C": 0,
}


@app.get(
  "/produtos/{produto_id}/disponibilidade",
  response_model=DisponibilidadeResponse,
  summary="Verificar disponibilidade de um produto",
)
def verificar_disponibilidade(produto_id: str, quantidade: int = 1):
  if _falha_ativa:
    logger.warning("Falha simulada ativa - retornando erro 503")
    publicar_atividade("estoque", "Falha simulada ativa — servico indisponivel (503)", nivel="error")
    raise HTTPException(status_code=503, detail="Servico de Estoque indisponivel (falha simulada).")

  if quantidade <= 0:
    raise HTTPException(status_code=400, detail="Quantidade invalida. Deve ser maior que zero.")

  if produto_id not in ESTOQUE:
    raise HTTPException(status_code=404, detail="Produto nao encontrado.")

  quantidade_estoque = ESTOQUE[produto_id]
  disponivel = quantidade_estoque >= quantidade

  logger.info(
    "Verificacao: %s | solicitado=%d | estoque=%d | disponivel=%s",
    produto_id,
    quantidade,
    quantidade_estoque,
    disponivel,
  )
  publicar_atividade(
    "estoque",
    f"Verificacao de {produto_id}: solicitado={quantidade}, estoque={quantidade_estoque}, disponivel={disponivel}",
    nivel="success" if disponivel else "warning",
    detalhes={"produto_id": produto_id, "quantidade_solicitada": quantidade, "disponivel": disponivel},
  )

  return DisponibilidadeResponse(
    produto_id=produto_id,
    quantidade_solicitada=quantidade,
    disponivel=disponivel,
    quantidade_estoque=quantidade_estoque,
  )


@app.post("/admin/simular-falha", summary="Ativar/desativar falha simulada (demo Circuit Breaker)")
def simular_falha(ativo: bool = True):
  global _falha_ativa
  _falha_ativa = ativo
  estado = "ativada" if ativo else "desativada"
  logger.warning("Falha simulada %s", estado)
  publicar_atividade(
    "estoque",
    f"Falha simulada {estado} (demo Circuit Breaker)",
    nivel="warning" if ativo else "info",
  )
  return {"falha_simulada": ativo, "mensagem": f"Falha simulada {estado}."}


@app.get("/", summary="Status do servico de estoque")
def status():
  return {"status": "ok", "servico": "estoque", "falha_simulada": _falha_ativa}
