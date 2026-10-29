"""Testes da agenda de eventos do configurador Palworld."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from eventos_palworld import (
    carregar_eventos,
    criar_evento,
    processar_agenda,
    salvar_eventos,
)


def evento_de_teste(
    *,
    inicio: str = "2026-10-20 18:00",
    frequencia: str = "Uma vez",
) -> dict[str, object]:
    return criar_evento(
        nome="Invasão de teste",
        tipo="Invasão",
        inicio=inicio,
        frequencia=frequencia,
        premio="10 Esferas Pal",
    )


class TesteAgendaEventos(unittest.TestCase):
    def test_cria_evento_com_id_e_campos_validos(self) -> None:
        evento = evento_de_teste()
        self.assertTrue(evento["id"])
        self.assertEqual(evento["nome"], "Invasão de teste")

    def test_rejeita_data_invalida(self) -> None:
        with self.assertRaisesRegex(ValueError, "data"):
            evento_de_teste(inicio="20/10/2026 18:00")

    def test_processa_evento_unico_apenas_uma_vez(self) -> None:
        evento = evento_de_teste()
        horario = datetime(2026, 10, 20, 18, 0)
        atualizados, iniciados = processar_agenda([evento], horario)
        self.assertEqual(len(iniciados), 1)
        self.assertFalse(atualizados[0]["ativo"])
        repetidos, iniciados_novamente = processar_agenda(atualizados, horario)
        self.assertEqual(repetidos, atualizados)
        self.assertEqual(iniciados_novamente, [])

    def test_avanca_evento_diario_e_semanal(self) -> None:
        horario = datetime(2026, 10, 20, 18, 0)
        for frequencia, proxima_data in (
            ("Diariamente", "2026-10-21 18:00"),
            ("Semanalmente", "2026-10-27 18:00"),
        ):
            with self.subTest(frequencia=frequencia):
                atualizado, iniciados = processar_agenda(
                    [evento_de_teste(frequencia=frequencia)], horario
                )
                self.assertEqual(len(iniciados), 1)
                self.assertEqual(atualizado[0]["inicio"], proxima_data)

    def test_pula_eventos_recorrentes_perdidos(self) -> None:
        evento = evento_de_teste(frequencia="Diariamente")
        atualizados, iniciados = processar_agenda(
            [evento], datetime(2026, 10, 23, 18, 0)
        )
        self.assertEqual(iniciados, [])
        self.assertEqual(atualizados[0]["inicio"], "2026-10-24 18:00")

    def test_salva_e_carrega_agenda(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "eventos.json"
            eventos = [evento_de_teste(frequencia="Semanalmente")]
            salvar_eventos(caminho, eventos)
            self.assertEqual(carregar_eventos(caminho), eventos)


if __name__ == "__main__":
    unittest.main()
