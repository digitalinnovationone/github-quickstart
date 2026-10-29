"""Testes para a API administrativa local do Palworld."""

import base64
import io
import json
import unittest
from unittest.mock import patch

from palworld_admin import ClienteRESTPalworld, ErroAPIPalworld


class RespostaHTTP:
    def __init__(self, corpo: bytes) -> None:
        self.corpo = io.BytesIO(corpo)

    def __enter__(self) -> "RespostaHTTP":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.corpo.read()


class TesteClienteRESTPalworld(unittest.TestCase):
    def test_rejeita_enderecos_publicos_e_hosts_desconhecidos(self) -> None:
        for endereco in ("http://8.8.8.8:8212", "http://servidor-publico.example:8212"):
            with self.subTest(endereco=endereco):
                with self.assertRaisesRegex(ValueError, "Internet"):
                    ClienteRESTPalworld(endereco, "senha")

    def test_rejeita_url_com_caminho_e_senha_vazia(self) -> None:
        with self.assertRaisesRegex(ValueError, "endereço HTTP local"):
            ClienteRESTPalworld("http://127.0.0.1:8212/v1/api", "senha")
        with self.assertRaisesRegex(ValueError, "senha"):
            ClienteRESTPalworld("http://127.0.0.1:8212", "")

    @patch("palworld_admin.urlopen")
    def test_busca_jogadores_com_autenticacao_basic(self, abrir_url) -> None:
        corpo = json.dumps(
            {"players": [{"name": "Sammy", "userId": "id-jogador"}]}
        ).encode()
        abrir_url.return_value = RespostaHTTP(corpo)
        cliente = ClienteRESTPalworld("http://127.0.0.1:8212", "senha-segura")

        jogadores = cliente.listar_jogadores()

        self.assertEqual(jogadores[0]["userId"], "id-jogador")
        requisicao = abrir_url.call_args.args[0]
        self.assertEqual(
            requisicao.full_url, "http://127.0.0.1:8212/v1/api/players"
        )
        self.assertEqual(
            requisicao.get_header("Authorization"),
            "Basic "
            + base64.b64encode(b"admin:senha-segura").decode("ascii"),
        )

    @patch("palworld_admin.urlopen")
    def test_anuncio_envia_json(self, abrir_url) -> None:
        abrir_url.return_value = RespostaHTTP(b"")
        cliente = ClienteRESTPalworld("http://localhost:8212", "senha")

        resposta = cliente.anunciar("Evento começando!")

        self.assertIsNone(resposta)
        requisicao = abrir_url.call_args.args[0]
        self.assertEqual(requisicao.method, "POST")
        self.assertEqual(
            json.loads(requisicao.data.decode("utf-8")),
            {"message": "Evento começando!"},
        )

    @patch("palworld_admin.urlopen")
    def test_rejeita_resposta_de_jogadores_em_formato_invalido(self, abrir_url) -> None:
        abrir_url.return_value = RespostaHTTP(b'{"players":{}}')
        cliente = ClienteRESTPalworld("http://127.0.0.1:8212", "senha")

        with self.assertRaisesRegex(ErroAPIPalworld, "lista de jogadores"):
            cliente.listar_jogadores()

    def test_desligamento_valida_o_tempo(self) -> None:
        cliente = ClienteRESTPalworld("http://127.0.0.1:8212", "senha")
        with self.assertRaisesRegex(ValueError, "não negativo"):
            cliente.agendar_desligamento(-1, "Encerrando")


if __name__ == "__main__":
    unittest.main()
