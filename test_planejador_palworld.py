import unittest

from planejador_palworld import (
    Pal,
    Receita,
    calcular_materiais_necessarios,
    calcular_materiais_em_falta,
    recomendar_pals,
)


class TestesDeCalculoDosMateriaisNecessarios(unittest.TestCase):
    def test_arredonda_para_cima_lotes_inteiros(self):
        receita = Receita("kit", {"madeira": 3, "pedra": 2}, producao_por_lote=2)

        self.assertEqual(
            calcular_materiais_necessarios(receita, 3),
            {"madeira": 6, "pedra": 4},
        )

    def test_rejeita_quantidade_desejada_nao_positiva(self):
        receita = Receita("kit", {"madeira": 3})

        with self.assertRaises(ValueError):
            calcular_materiais_necessarios(receita, 0)

    def test_receita_rejeita_quantidade_invalida_de_material(self):
        with self.assertRaises(ValueError):
            Receita("kit", {"madeira": 0})


class TestesDeCalculoDosMateriaisEmFalta(unittest.TestCase):
    def test_retorna_faltas_e_zero_quando_o_estoque_e_suficiente(self):
        faltas = calcular_materiais_em_falta(
            {"madeira": 6, "pedra": 4},
            {"madeira": 8, "pedra": 1},
        )

        self.assertEqual(faltas, {"madeira": 0, "pedra": 3})

    def test_rejeita_estoque_negativo(self):
        with self.assertRaises(ValueError):
            calcular_materiais_em_falta({"madeira": 2}, {"madeira": -1})


class TestesDeRecomendacaoDePals(unittest.TestCase):
    def setUp(self):
        self.pals = [
            Pal("Pal Z", {"artesanato": 2}),
            Pal("Pal B", {"Artesanato": 3}),
            Pal("Pal A", {"artesanato": 3}),
            Pal("Pal sem aptidão", {"plantio": 2}),
        ]

    def test_ordena_por_nivel_e_nome_e_ignora_maiusculas(self):
        recomendacoes = recomendar_pals(self.pals, "ARTESANATO")

        self.assertEqual(
            [(pal.nome, nivel) for pal, nivel in recomendacoes],
            [("Pal A", 3), ("Pal B", 3), ("Pal Z", 2)],
        )

    def test_aplica_limite_de_resultados(self):
        recomendacoes = recomendar_pals(self.pals, "artesanato", limite=1)

        self.assertEqual([pal.nome for pal, _ in recomendacoes], ["Pal A"])

    def test_rejeita_tarefa_vazia(self):
        with self.assertRaises(ValueError):
            recomendar_pals(self.pals, " ")


if __name__ == "__main__":
    unittest.main()
