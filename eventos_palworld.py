"""Agenda local de eventos para o configurador de servidor Palworld."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


TIPOS_EVENTO = ("Invasão", "Chefe", "Chefe de Raid", "Evento personalizado")
FREQUENCIAS = ("Uma vez", "Diariamente", "Semanalmente")
TOLERANCIA_ATRASO = timedelta(minutes=5)


def validar_evento(evento: dict[str, Any]) -> None:
    campos_texto = ("id", "nome", "tipo", "inicio", "frequencia", "premio")
    if any(not isinstance(evento.get(campo), str) for campo in campos_texto):
        raise ValueError("O evento tem campos de texto inválidos.")
    if not evento["nome"].strip():
        raise ValueError("Informe um nome para o evento.")
    if "\n" in evento["nome"] or "\r" in evento["nome"]:
        raise ValueError("O nome do evento não pode conter quebras de linha.")
    if evento["tipo"] not in TIPOS_EVENTO:
        raise ValueError("Selecione um tipo de evento válido.")
    if evento["frequencia"] not in FREQUENCIAS:
        raise ValueError("Selecione uma frequência válida.")
    if not evento["premio"].strip():
        raise ValueError("Descreva o prêmio do evento.")
    try:
        inicio = datetime.strptime(evento["inicio"], "%Y-%m-%d %H:%M")
    except ValueError as erro:
        raise ValueError("A data deve seguir o formato AAAA-MM-DD HH:MM.") from erro
    if inicio.strftime("%Y-%m-%d %H:%M") != evento["inicio"]:
        raise ValueError("A data do evento não é válida.")
    if not isinstance(evento.get("ativo"), bool):
        raise ValueError("O estado ativo do evento é inválido.")


def criar_evento(
    *,
    nome: str,
    tipo: str,
    inicio: str,
    frequencia: str,
    premio: str,
    ativo: bool = True,
    identificador: str | None = None,
) -> dict[str, Any]:
    evento: dict[str, Any] = {
        "id": identificador or str(uuid.uuid4()),
        "nome": nome.strip(),
        "tipo": tipo,
        "inicio": inicio,
        "frequencia": frequencia,
        "premio": premio.strip(),
        "ativo": ativo,
    }
    validar_evento(evento)
    return evento


def carregar_eventos(caminho: Path) -> list[dict[str, Any]]:
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        raise ValueError(f"Não foi possível ler a agenda de eventos: {erro}") from erro
    if not isinstance(dados, list):
        raise ValueError("O arquivo da agenda precisa conter uma lista de eventos.")
    eventos: list[dict[str, Any]] = []
    identificadores: set[str] = set()
    for evento in dados:
        if not isinstance(evento, dict):
            raise ValueError("A agenda contém um evento inválido.")
        validar_evento(evento)
        if evento["id"] in identificadores:
            raise ValueError("A agenda contém identificadores de evento duplicados.")
        identificadores.add(evento["id"])
        eventos.append(evento)
    return eventos


def salvar_eventos(caminho: Path, eventos: list[dict[str, Any]]) -> None:
    identificadores: set[str] = set()
    for evento in eventos:
        validar_evento(evento)
        if evento["id"] in identificadores:
            raise ValueError("A agenda contém identificadores de evento duplicados.")
        identificadores.add(evento["id"])

    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=caminho.parent,
            prefix=f".{caminho.name}.",
            suffix=".tmp",
            delete=False,
        ) as arquivo:
            json.dump(eventos, arquivo, ensure_ascii=False, indent=2)
            arquivo.write("\n")
            temporario = Path(arquivo.name)
        os.replace(temporario, caminho)
    except OSError:
        if temporario is not None:
            temporario.unlink(missing_ok=True)
        raise


def formatar_proxima_execucao(evento: dict[str, Any]) -> str:
    if not evento["ativo"]:
        return "Pausado ou concluído"
    inicio = datetime.strptime(evento["inicio"], "%Y-%m-%d %H:%M")
    return inicio.strftime("%d/%m/%Y às %H:%M")


def processar_agenda(
    eventos: list[dict[str, Any]], agora: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Avança recorrências e retorna eventos cujo horário chegou."""
    atualizados: list[dict[str, Any]] = []
    iniciados: list[dict[str, Any]] = []
    for evento_original in eventos:
        evento = dict(evento_original)
        validar_evento(evento)
        if evento["ativo"]:
            inicio = datetime.strptime(evento["inicio"], "%Y-%m-%d %H:%M")
            atraso = agora - inicio
            if timedelta(0) <= atraso <= TOLERANCIA_ATRASO:
                iniciados.append(dict(evento))
                if evento["frequencia"] == "Uma vez":
                    evento["ativo"] = False
                else:
                    intervalo = timedelta(
                        days=1 if evento["frequencia"] == "Diariamente" else 7
                    )
                    intervalos_pulados = atraso // intervalo
                    proximo = inicio + intervalo * (intervalos_pulados + 1)
                    evento["inicio"] = proximo.strftime("%Y-%m-%d %H:%M")
            elif atraso > TOLERANCIA_ATRASO:
                if evento["frequencia"] == "Uma vez":
                    evento["ativo"] = False
                else:
                    intervalo = timedelta(
                        days=1 if evento["frequencia"] == "Diariamente" else 7
                    )
                    intervalos_pulados = atraso // intervalo
                    proximo = inicio + intervalo * (intervalos_pulados + 1)
                    evento["inicio"] = proximo.strftime("%Y-%m-%d %H:%M")
        atualizados.append(evento)
    return atualizados, iniciados
