"""Cliente mínimo e restrito à rede local para a API REST do Palworld."""

from __future__ import annotations

import base64
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ErroAPIPalworld(Exception):
    """Falha de comunicação ou resposta inválida da API do servidor."""


class ClienteRESTPalworld:
    def __init__(
        self,
        endereco: str,
        senha_administrador: str,
        *,
        tempo_limite: float = 5,
    ) -> None:
        url = urlsplit(endereco.strip())
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError("Informe um endereço HTTP local, sem caminho adicional.")
        if not self._endereco_local(url.hostname):
            raise ValueError(
                "A API REST não deve ser exposta à Internet. Use localhost ou um IP privado."
            )
        try:
            porta = url.port
        except ValueError as erro:
            raise ValueError("A porta da API REST é inválida.") from erro
        if porta is None:
            porta = 443 if url.scheme == "https" else 80
        if not 1 <= porta <= 65535:
            raise ValueError("A porta da API REST deve estar entre 1 e 65535.")
        if not senha_administrador:
            raise ValueError("Informe a senha de administrador do servidor.")

        self.base_url = f"{url.scheme}://{url.netloc}"
        self.tempo_limite = tempo_limite
        token = base64.b64encode(
            f"admin:{senha_administrador}".encode("utf-8")
        ).decode("ascii")
        self._cabecalho_autorizacao = f"Basic {token}"

    @staticmethod
    def _endereco_local(host: str) -> bool:
        if host.lower() == "localhost":
            return True
        try:
            endereco = ipaddress.ip_address(host)
        except ValueError:
            return False
        return (
            endereco.is_private
            and not endereco.is_link_local
            and not endereco.is_multicast
            and not endereco.is_reserved
        ) or endereco.is_loopback

    def requisitar(
        self, metodo: str, caminho: str, dados: dict[str, object] | None = None
    ) -> object:
        if not caminho.startswith("/") or ".." in caminho:
            raise ValueError("Caminho inválido para a API.")
        corpo = (
            json.dumps(dados, ensure_ascii=False).encode("utf-8")
            if dados is not None
            else None
        )
        requisicao = Request(
            f"{self.base_url}/v1/api{caminho}",
            data=corpo,
            method=metodo,
            headers={
                "Accept": "application/json",
                "Authorization": self._cabecalho_autorizacao,
                **({"Content-Type": "application/json"} if corpo else {}),
            },
        )
        try:
            with urlopen(requisicao, timeout=self.tempo_limite) as resposta:
                conteudo = resposta.read()
        except HTTPError as erro:
            detalhe = erro.read().decode("utf-8", errors="replace").strip()
            raise ErroAPIPalworld(
                f"A API do servidor respondeu com HTTP {erro.code}"
                + (f": {detalhe}" if detalhe else ".")
            ) from erro
        except (URLError, TimeoutError, OSError) as erro:
            raise ErroAPIPalworld(
                f"Não foi possível acessar a API do servidor: {erro}"
            ) from erro
        if not conteudo:
            return None
        try:
            return json.loads(conteudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return conteudo.decode("utf-8", errors="replace")

    def informacoes_servidor(self) -> object:
        return self.requisitar("GET", "/info")

    def listar_jogadores(self) -> list[dict[str, object]]:
        resposta = self.requisitar("GET", "/players")
        if not isinstance(resposta, dict) or not isinstance(
            resposta.get("players"), list
        ):
            raise ErroAPIPalworld(
                "A resposta da API não contém uma lista de jogadores."
            )
        jogadores = resposta["players"]
        if not all(isinstance(jogador, dict) for jogador in jogadores):
            raise ErroAPIPalworld("A API retornou um jogador com formato inválido.")
        return jogadores

    def anunciar(self, mensagem: str) -> object:
        return self.requisitar("POST", "/announce", {"message": mensagem})

    def expulsar(self, user_id: str, mensagem: str = "") -> object:
        return self.requisitar(
            "POST", "/kick", {"userid": user_id, "message": mensagem}
        )

    def banir(self, user_id: str, mensagem: str = "") -> object:
        return self.requisitar(
            "POST", "/ban", {"userid": user_id, "message": mensagem}
        )

    def desbanir(self, user_id: str) -> object:
        return self.requisitar("POST", "/unban", {"userid": user_id})

    def salvar_mundo(self) -> object:
        return self.requisitar("POST", "/save")

    def agendar_desligamento(self, segundos: int, mensagem: str) -> object:
        if isinstance(segundos, bool) or not isinstance(segundos, int) or segundos < 0:
            raise ValueError("O tempo para desligamento deve ser um inteiro não negativo.")
        return self.requisitar(
            "POST", "/shutdown", {"waittime": segundos, "message": mensagem}
        )
