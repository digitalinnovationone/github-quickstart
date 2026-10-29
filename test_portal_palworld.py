"""Testes da loja, do painel do jogador e do webhook do Portal Pandora."""

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from portal_palworld import (
    abrir_banco,
    atualizar_progresso_exploracao,
    _chamar_api,
    criar_app,
    criar_meta_exploracao,
    criar_missao,
    criar_produto,
    validar_assinatura_webhook,
)


class RespostaHTTP:
    def __init__(self, corpo: bytes = b"") -> None:
        self.corpo = corpo

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.corpo


def assinatura_webhook(segredo: str, requisicao_id: str, id_dado: str) -> str:
    timestamp = "1704908010"
    manifesto = f"id:{id_dado.lower()};request-id:{requisicao_id};ts:{timestamp};"
    digest = hmac.new(
        segredo.encode("utf-8"), manifesto.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"ts={timestamp},v1={digest}"


class TestePortalPandora(unittest.TestCase):
    def setUp(self) -> None:
        self.diretorio = tempfile.TemporaryDirectory()
        self.caminho_banco = Path(self.diretorio.name) / "portal.sqlite3"
        self.app = criar_app(
            {
                "TESTING": True,
                "SECRET_KEY": "chave-de-teste",
                "DATABASE_PATH": str(self.caminho_banco),
                "PORTAL_PUBLIC_URL": "https://pandora.example",
                "DISCORD_ADMIN_IDS": "111,222",
                "MERCADOPAGO_ACCESS_TOKEN": "TEST-token",
                "MERCADOPAGO_WEBHOOK_SECRET": "segredo-webhook",
                "DISCORD_BOT_TOKEN": "token-bot",
                "DISCORD_GUILD_ID": "333",
                "DISCORD_VIP_ROLE_ID": "444",
                "PALWORLD_API_URL": "http://127.0.0.1:8212",
                "PALWORLD_ADMIN_PASSWORD": "senha-segura",
                "SESSION_COOKIE_SECURE": False,
            }
        )
        self.cliente = self.app.test_client()

    def tearDown(self) -> None:
        self.diretorio.cleanup()

    def login_como(self, discord_id: str = "123") -> None:
        with self.cliente.session_transaction() as sessao:
            sessao["discord_id"] = discord_id
            sessao["discord_nome"] = "Explorador"
            sessao["csrf_token"] = "token-csrf"

    def test_pagina_inicial_apresenta_marca_pandora(self) -> None:
        resposta = self.cliente.get("/")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"PANDORA", resposta.data)
        self.assertIn(b"uma nova lenda", resposta.data)
        self.assertEqual(resposta.headers["X-Frame-Options"], "DENY")

    def test_oauth_discord_usa_estado_e_bloqueia_redirecionamento_externo(self) -> None:
        self.app.config["DISCORD_CLIENT_ID"] = "client-id"
        self.app.config["DISCORD_CLIENT_SECRET"] = "client-secret"
        resposta_login = self.cliente.get("/login?proximo=https://attacker.example")
        parametros = parse_qs(urlsplit(resposta_login.headers["Location"]).query)
        estado = parametros["state"][0]
        self.assertEqual(
            urlsplit(parametros["redirect_uri"][0]).path, "/auth/discord"
        )
        with patch(
            "portal_palworld.urlopen",
            return_value=RespostaHTTP(b'{"access_token":"access-token"}'),
        ), patch(
            "portal_palworld._chamar_api",
            return_value={"id": "123", "username": "Explorador"},
        ):
            retorno = self.cliente.get(
                f"/auth/discord?code=oauth-code&state={estado}"
            )
        self.assertEqual(retorno.status_code, 302)
        self.assertEqual(retorno.headers["Location"], "/")
        with self.cliente.session_transaction() as sessao:
            self.assertEqual(sessao["discord_id"], "123")

    def test_missao_requer_login_e_protecao_csrf(self) -> None:
        missao_id = criar_missao(
            self.caminho_banco, "Exploração", "Encontre uma ruína", "Baú raro"
        )
        resposta_sem_login = self.cliente.post(
            f"/missoes/{missao_id}/enviar",
            data={"prova": "Concluí a exploração e tenho uma captura.", "csrf_token": "x"},
        )
        self.assertEqual(resposta_sem_login.status_code, 302)

        self.login_como()
        resposta_csrf_invalido = self.cliente.post(
            f"/missoes/{missao_id}/enviar",
            data={"prova": "Concluí a exploração e tenho uma captura.", "csrf_token": "x"},
        )
        self.assertEqual(resposta_csrf_invalido.status_code, 400)

    def test_jogador_envia_comprovacao_para_painel(self) -> None:
        missao_id = criar_missao(
            self.caminho_banco, "Exploração", "Encontre uma ruína", "Baú raro"
        )
        self.login_como()
        resposta = self.cliente.post(
            f"/missoes/{missao_id}/enviar",
            data={
                "prova": "Concluí a exploração e encontrei a ruína norte.",
                "csrf_token": "token-csrf",
            },
            follow_redirects=True,
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"enviada para an", resposta.data)
        with abrir_banco(self.caminho_banco) as banco:
            reivindicacao = banco.execute(
                "SELECT discord_id, status FROM reivindicacoes"
            ).fetchone()
        self.assertEqual(reivindicacao["discord_id"], "123")
        self.assertEqual(reivindicacao["status"], "pendente")

    def test_assinatura_webhook_exige_manifesto_autentico(self) -> None:
        assinatura = assinatura_webhook("segredo", "req-1", "1234")
        self.assertTrue(
            validar_assinatura_webhook(assinatura, "req-1", "1234", "segredo")
        )
        self.assertFalse(
            validar_assinatura_webhook(assinatura, "req-2", "1234", "segredo")
        )

    def test_api_externa_envia_token_como_bearer(self) -> None:
        with patch(
            "portal_palworld.urlopen",
            return_value=RespostaHTTP(b'{"ok":true}'),
        ) as abrir_url:
            retorno = _chamar_api(
                "https://api.example.test/recurso", token="token-de-teste"
            )
        self.assertEqual(retorno, {"ok": True})
        requisicao = abrir_url.call_args.args[0]
        self.assertEqual(requisicao.get_header("Authorization"), "Bearer token-de-teste")

    @patch("portal_palworld.ClienteRESTPalworld.listar_jogadores")
    def test_mapa_entrega_somente_posicoes_minimas(
        self, listar_jogadores
    ) -> None:
        listar_jogadores.return_value = [
            {
                "name": "Explorador",
                "location_x": 120.5,
                "location_y": -45,
                "level": 12,
                "ip": "192.0.2.5",
                "userId": "id-privado",
            }
        ]
        self.login_como()
        resposta = self.cliente.get("/api/mapa/jogadores")
        self.assertEqual(resposta.status_code, 200)
        jogador = resposta.get_json()["jogadores"][0]
        self.assertEqual(jogador, {"nome": "Explorador", "x": 120.5, "y": -45, "nivel": 12})
        self.assertNotIn("ip", jogador)
        self.assertNotIn("userId", jogador)

    def test_painel_mostra_progresso_de_meta_por_jogador(self) -> None:
        meta_id = criar_meta_exploracao(
            self.caminho_banco, "Estátuas", 50
        )
        atualizar_progresso_exploracao(
            self.caminho_banco, meta_id, "123", 1, "111"
        )
        self.login_como("123")
        resposta = self.cliente.get("/")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"1/50", resposta.data)
        self.login_como("999")
        resposta_outro_jogador = self.cliente.get("/")
        self.assertIn(b"0/50", resposta_outro_jogador.data)

    def test_progresso_nao_pode_ultrapassar_total(self) -> None:
        meta_id = criar_meta_exploracao(
            self.caminho_banco, "Estátuas", 50
        )
        with self.assertRaisesRegex(ValueError, "ultrapassar"):
            atualizar_progresso_exploracao(
                self.caminho_banco, meta_id, "123", 51, "111"
            )

    def test_checkout_cria_pedido_com_preco_do_banco(self) -> None:
        produto_id = criar_produto(
            self.caminho_banco, "Pacote de apoiador", "Apoio da comunidade", 1990
        )
        self.login_como()
        resposta_checkout = RespostaHTTP(
            json.dumps(
                {"init_point": "https://www.mercadopago.com/checkout/pedido"}
            ).encode("utf-8")
        )
        with patch(
            "portal_palworld.urlopen", return_value=resposta_checkout
        ) as abrir_checkout:
            resposta = self.cliente.post(
                f"/loja/{produto_id}/comprar",
                data={"csrf_token": "token-csrf"},
            )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(
            resposta.headers["Location"],
            "https://www.mercadopago.com/checkout/pedido",
        )
        requisicao = abrir_checkout.call_args.args[0]
        preferencia = json.loads(requisicao.data.decode("utf-8"))
        self.assertEqual(preferencia["items"][0]["unit_price"], 19.9)
        self.assertTrue(preferencia["external_reference"])
        self.assertEqual(
            preferencia["notification_url"],
            "https://pandora.example/webhooks/mercadopago",
        )
        with abrir_banco(self.caminho_banco) as banco:
            pedido = banco.execute("SELECT status, valor_centavos FROM pedidos").fetchone()
        self.assertEqual(pedido["status"], "aguardando_pagamento")
        self.assertEqual(pedido["valor_centavos"], 1990)

    def test_webhook_verifica_pagamento_e_concede_cargo_vip(self) -> None:
        produto_id = criar_produto(
            self.caminho_banco, "VIP Explorador", "Acesso VIP", 1990, 30
        )
        pedido_id = "pedido-teste-1"
        with abrir_banco(self.caminho_banco) as banco:
            banco.execute(
                """
                INSERT INTO pedidos
                    (id, discord_id, produto_id, titulo_produto, valor_centavos,
                     dias_vip, status, vip_status, criado_em, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, 'aguardando_pagamento', 'pendente', ?, ?)
                """,
                (
                    pedido_id,
                    "123",
                    produto_id,
                    "VIP Explorador",
                    1990,
                    30,
                    "2026-10-28T00:00:00+00:00",
                    "2026-10-28T00:00:00+00:00",
                ),
            )
        id_pagamento = "987654321"
        requisicao_id = "req-pagamento-teste"
        assinatura = assinatura_webhook(
            "segredo-webhook", requisicao_id, id_pagamento
        )
        pagamento = {
            "external_reference": pedido_id,
            "transaction_amount": 19.90,
            "currency_id": "BRL",
            "status": "approved",
        }
        with patch("portal_palworld._chamar_api", return_value=pagamento), patch(
            "portal_palworld.urlopen", return_value=RespostaHTTP()
        ) as chamar_discord:
            resposta = self.cliente.post(
                f"/webhooks/mercadopago?data.id={id_pagamento}",
                headers={
                    "x-signature": assinatura,
                    "x-request-id": requisicao_id,
                },
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(chamar_discord.call_count, 1)
        self.assertEqual(
            chamar_discord.call_args.args[0].full_url,
            "https://discord.com/api/v10/guilds/333/members/123/roles/444",
        )
        with abrir_banco(self.caminho_banco) as banco:
            pedido = banco.execute(
                "SELECT status, vip_status FROM pedidos WHERE id = ?", (pedido_id,)
            ).fetchone()
            beneficio = banco.execute(
                "SELECT discord_id, expira_em FROM beneficios_vip WHERE pedido_id = ?",
                (pedido_id,),
            ).fetchone()
        self.assertEqual(pedido["status"], "approved")
        self.assertEqual(pedido["vip_status"], "aplicado")
        self.assertEqual(beneficio["discord_id"], "123")
        self.assertIsNotNone(beneficio["expira_em"])

    def test_webhook_rejeita_assinatura_invalida(self) -> None:
        resposta = self.cliente.post(
            "/webhooks/mercadopago?data.id=1234",
            headers={"x-signature": "ts=1,v1=inválido", "x-request-id": "req"},
        )
        self.assertEqual(resposta.status_code, 401)


if __name__ == "__main__":
    unittest.main()
