"""Testes de geração segura da configuração do servidor."""

import unittest

from configurador_palworld import (
    gerar_configuracao_portal_hospedagem,
    gerar_pal_world_settings,
)


MODELO = (
    "[/Script/Pal.PalGameWorldSettings]\n"
    'OptionSettings=(ServerName="Servidor",ServerPlayerMaxNum=32,PublicPort=8211,'
    "RESTAPIEnabled=False,RESTAPIPort=8212,RCONEnabled=False,RCONPort=25575)\n"
)


class TesteGeracaoConfiguracao(unittest.TestCase):
    def gerar(self, **alteracoes) -> str:
        valores = {
            "nome": "Servidor dos amigos",
            "descricao": "Servidor privado",
            "quantidade_jogadores": 10,
            "porta": 8211,
            "senha_servidor": "",
            "senha_administrador": "",
            "plataformas": ["Steam"],
        }
        valores.update(alteracoes)
        return gerar_pal_world_settings(MODELO, **valores)

    def test_preserva_opcoes_nao_alteradas_e_grava_servicos_desativados(self) -> None:
        resultado = self.gerar()
        self.assertIn("ServerPlayerMaxNum=10", resultado)
        self.assertIn("RESTAPIEnabled=False", resultado)
        self.assertIn("RCONEnabled=False", resultado)

    def test_ativa_servicos_com_senha_e_portas_configuradas(self) -> None:
        resultado = self.gerar(
            senha_administrador="senha-forte",
            api_rest_ativada=True,
            porta_api_rest=8213,
            rcon_ativado=True,
            porta_rcon=25576,
        )
        self.assertIn("AdminPassword=\"senha-forte\"", resultado)
        self.assertIn("RESTAPIEnabled=True", resultado)
        self.assertIn("RESTAPIPort=8213", resultado)
        self.assertIn("RCONEnabled=True", resultado)
        self.assertIn("RCONPort=25576", resultado)

    def test_nao_ativa_api_sem_senha_administrativa(self) -> None:
        with self.assertRaisesRegex(ValueError, "senha de administrador"):
            self.gerar(api_rest_ativada=True)

    def test_nao_permite_reutilizar_porta_da_api_e_do_rcon(self) -> None:
        with self.assertRaisesRegex(ValueError, "portas diferentes"):
            self.gerar(
                senha_administrador="senha-forte",
                api_rest_ativada=True,
                rcon_ativado=True,
                porta_api_rest=9000,
                porta_rcon=9000,
            )

    def test_valida_intervalo_da_porta_api(self) -> None:
        with self.assertRaisesRegex(ValueError, "porta da API REST"):
            self.gerar(porta_api_rest=70000)

    def test_exporta_enderecos_do_portal_sem_segredos(self) -> None:
        resultado = gerar_configuracao_portal_hospedagem(
            "https://portal.example.com",
            "http://10.0.0.12:8212",
        )
        self.assertIn("PORTAL_PUBLIC_URL=https://portal.example.com", resultado)
        self.assertIn("PALWORLD_API_URL=http://10.0.0.12:8212", resultado)
        self.assertNotIn("PASSWORD", resultado)
        self.assertNotIn("TOKEN", resultado)

    def test_portal_hospedado_exige_https(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            gerar_configuracao_portal_hospedagem("http://portal.example.com")

    def test_nao_exporta_api_publica_para_o_portal(self) -> None:
        with self.assertRaisesRegex(ValueError, "exposta à Internet"):
            gerar_configuracao_portal_hospedagem(
                "https://portal.example.com",
                "http://8.8.8.8:8212",
            )


if __name__ == "__main__":
    unittest.main()
