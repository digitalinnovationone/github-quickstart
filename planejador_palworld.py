"""Algoritmos simples para planejar uma base inspirada em Palworld."""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass


class AnalisadorDeArgumentos(argparse.ArgumentParser):
    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "uso:", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "uso:", 1)

    def error(self, mensagem: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: erro: {mensagem}\n")


def _exigir_inteiro_positivo(valor: int, descricao: str) -> None:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise ValueError(f"{descricao} deve ser um inteiro positivo.")


@dataclass(frozen=True)
class Receita:
    nome: str
    materiais: dict[str, int]
    producao_por_lote: int = 1

    def __post_init__(self) -> None:
        if not self.nome.strip():
            raise ValueError("A receita precisa ter um nome.")
        _exigir_inteiro_positivo(self.producao_por_lote, "A produção por lote")
        if not self.materiais:
            raise ValueError("A receita precisa conter ao menos um material.")
        for material, quantidade in self.materiais.items():
            if not material.strip():
                raise ValueError("O nome do material não pode ficar vazio.")
            _exigir_inteiro_positivo(quantidade, f"A quantidade de {material}")


@dataclass(frozen=True)
class Pal:
    nome: str
    aptidoes_de_trabalho: dict[str, int]

    def __post_init__(self) -> None:
        if not self.nome.strip():
            raise ValueError("O Pal precisa ter um nome.")
        for tarefa, nivel in self.aptidoes_de_trabalho.items():
            if not tarefa.strip():
                raise ValueError("O nome da tarefa não pode ficar vazio.")
            if isinstance(nivel, bool) or not isinstance(nivel, int) or nivel < 0:
                raise ValueError(
                    f"A aptidão de {tarefa} deve ser um inteiro não negativo."
                )


def calcular_materiais_necessarios(
    receita: Receita, quantidade_desejada: int
) -> dict[str, int]:
    """Calcula os materiais considerando lotes completos de produção."""
    _exigir_inteiro_positivo(quantidade_desejada, "A quantidade desejada")
    lotes = math.ceil(quantidade_desejada / receita.producao_por_lote)
    return {
        material: quantidade * lotes
        for material, quantidade in receita.materiais.items()
    }


def calcular_materiais_em_falta(
    necessarios: dict[str, int], inventario: dict[str, int]
) -> dict[str, int]:
    """Retorna quanto falta de cada material necessário."""
    for material, quantidade in inventario.items():
        if not material.strip():
            raise ValueError("O nome do material no inventário não pode ficar vazio.")
        if isinstance(quantidade, bool) or not isinstance(quantidade, int) or quantidade < 0:
            raise ValueError(
                f"A quantidade de {material} no inventário deve ser "
                "um inteiro não negativo."
            )
    return {
        material: max(0, quantidade - inventario.get(material, 0))
        for material, quantidade in necessarios.items()
    }


def recomendar_pals(
    pals: tuple[Pal, ...] | list[Pal], tarefa: str, limite: int | None = None
) -> list[tuple[Pal, int]]:
    """Ordena os Pals com aptidão positiva para a tarefa informada."""
    tarefa_chave = tarefa.strip().casefold()
    if not tarefa_chave:
        raise ValueError("Informe uma tarefa para buscar.")
    if limite is not None:
        _exigir_inteiro_positivo(limite, "O limite")

    candidatos = []
    for pal in pals:
        nivel = next(
            (
                valor
                for aptidao, valor in pal.aptidoes_de_trabalho.items()
                if aptidao.casefold() == tarefa_chave
            ),
            0,
        )
        if nivel > 0:
            candidatos.append((pal, nivel))

    candidatos.sort(key=lambda candidato: (-candidato[1], candidato[0].nome.casefold()))
    return candidatos if limite is None else candidatos[:limite]


RECEITA_EXEMPLO = Receita(
    nome="kit de construção",
    materiais={"madeira": 3, "pedra": 2},
    producao_por_lote=2,
)

PALS_EXEMPLO = (
    Pal("Pal de Plantio", {"plantio": 3, "coleta": 1}),
    Pal("Pal de Transporte", {"transporte": 3, "artesanato": 1}),
    Pal("Pal Artesão", {"artesanato": 3, "plantio": 1}),
    Pal("Pal de Apoio", {"transporte": 1}),
)


def _interpretar_item_do_inventario(valor: str) -> tuple[str, int]:
    material, separador, quantidade_bruta = valor.partition("=")
    if not separador or not material.strip():
        raise argparse.ArgumentTypeError(
            "use o formato recurso=quantidade, por exemplo madeira=10"
        )
    try:
        quantidade = int(quantidade_bruta)
    except ValueError as erro:
        raise argparse.ArgumentTypeError("a quantidade deve ser um inteiro") from erro
    if quantidade < 0:
        raise argparse.ArgumentTypeError("a quantidade não pode ser negativa")
    return material.strip(), quantidade


def executar() -> None:
    analisador = AnalisadorDeArgumentos(
        add_help=False,
        usage="%(prog)s [opções]",
        description="Planeja materiais e trabalhadores para uma base inspirada em Palworld."
    )
    opcoes = analisador.add_argument_group("opções")
    opcoes.add_argument(
        "-h",
        "--ajuda",
        action="help",
        help="mostra esta mensagem de ajuda e encerra",
    )
    opcoes.add_argument(
        "--quantidade",
        type=int,
        default=3,
        help="quantidade desejada da receita (padrão: 3)",
    )
    opcoes.add_argument(
        "--inventario",
        action="append",
        type=_interpretar_item_do_inventario,
        default=[],
        metavar="RECURSO=QUANTIDADE",
        help="material disponível; pode ser informado mais de uma vez",
    )
    argumentos = analisador.parse_args()

    try:
        necessarios = calcular_materiais_necessarios(
            RECEITA_EXEMPLO, argumentos.quantidade
        )
        inventario = dict(argumentos.inventario)
        faltas = calcular_materiais_em_falta(necessarios, inventario)
    except ValueError as erro:
        analisador.error(str(erro))

    print("=== Planejador de base de Palworld ===")
    print(f"Receita: {RECEITA_EXEMPLO.nome}")
    print(f"Unidades desejadas: {argumentos.quantidade}\n")
    print("Materiais:")
    for material, quantidade in necessarios.items():
        disponivel = inventario.get(material, 0)
        print(
            f"- {material}: precisa de {quantidade}, tem {disponivel}, "
            f"faltam {faltas[material]}"
        )

    print("\nPals recomendados para artesanato:")
    recomendacoes = recomendar_pals(PALS_EXEMPLO, "artesanato")
    if not recomendacoes:
        print("- Nenhum Pal tem aptidão para essa tarefa.")
    else:
        for pal, nivel in recomendacoes:
            print(f"- {pal.nome} (aptidão {nivel})")


if __name__ == "__main__":
    executar()
