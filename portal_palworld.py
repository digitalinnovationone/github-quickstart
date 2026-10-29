"""Portal web simples para comunidade, loja e missões de Palworld."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from palworld_admin import ClienteRESTPalworld, ErroAPIPalworld
from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()


LOG = logging.getLogger(__name__)
URL_MERCADOPAGO_API = "https://api.mercadopago.com"
URL_DISCORD_API = "https://discord.com/api/v10"
DATABASE_PADRAO = Path(
    os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local"),
    ),
    "ConfiguradorPalworld",
    "portal.sqlite3",
)


class ErroIntegracao(RuntimeError):
    """Falha explícita ao conversar com Mercado Pago ou Discord."""


def conectar_banco(caminho: str | Path) -> sqlite3.Connection:
    banco = sqlite3.connect(str(caminho), timeout=10)
    banco.row_factory = sqlite3.Row
    banco.execute("PRAGMA foreign_keys = ON")
    return banco


@contextmanager
def abrir_banco(caminho: str | Path):
    banco = conectar_banco(caminho)
    try:
        with banco:
            yield banco
    finally:
        banco.close()


def inicializar_banco(caminho: str | Path) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with abrir_banco(caminho) as banco:
        banco.executescript(
            """
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL DEFAULT '',
                preco_centavos INTEGER NOT NULL CHECK (preco_centavos > 0),
                dias_vip INTEGER NOT NULL DEFAULT 0 CHECK (dias_vip >= -1),
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS missoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                premio TEXT NOT NULL,
                ativa INTEGER NOT NULL DEFAULT 1,
                criada_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metas_exploracao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                total INTEGER NOT NULL CHECK (total > 0),
                ativa INTEGER NOT NULL DEFAULT 1,
                criada_em TEXT NOT NULL,
                UNIQUE (titulo)
            );
            CREATE TABLE IF NOT EXISTS progresso_exploracao (
                meta_id INTEGER NOT NULL REFERENCES metas_exploracao(id),
                discord_id TEXT NOT NULL,
                quantidade INTEGER NOT NULL CHECK (quantidade >= 0),
                atualizado_por TEXT NOT NULL,
                atualizado_em TEXT NOT NULL,
                PRIMARY KEY (meta_id, discord_id)
            );
            CREATE TABLE IF NOT EXISTS reivindicacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                missao_id INTEGER NOT NULL REFERENCES missoes(id),
                discord_id TEXT NOT NULL,
                prova TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente'
                    CHECK (status IN ('pendente', 'aprovada', 'recusada')),
                revisado_por TEXT,
                revisado_em TEXT,
                criada_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pedidos (
                id TEXT PRIMARY KEY,
                discord_id TEXT NOT NULL,
                produto_id INTEGER NOT NULL REFERENCES produtos(id),
                titulo_produto TEXT NOT NULL,
                valor_centavos INTEGER NOT NULL,
                dias_vip INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'iniciando',
                id_pagamento TEXT UNIQUE,
                link_checkout TEXT,
                vip_status TEXT NOT NULL DEFAULT 'nao_aplicavel',
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS beneficios_vip (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id TEXT NOT NULL UNIQUE REFERENCES pedidos(id),
                discord_id TEXT NOT NULL,
                expira_em TEXT,
                expiracao_sincronizada INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_reivindicacoes_status
                ON reivindicacoes(status, criada_em);
            CREATE INDEX IF NOT EXISTS idx_pedidos_discord
                ON pedidos(discord_id, criado_em);
            CREATE INDEX IF NOT EXISTS idx_beneficios_discord
                ON beneficios_vip(discord_id, expira_em);
            """
        )
        colunas_vip = {
            coluna["name"]
            for coluna in banco.execute("PRAGMA table_info(beneficios_vip)")
        }
        if "expiracao_sincronizada" not in colunas_vip:
            banco.execute(
                """
                ALTER TABLE beneficios_vip
                ADD COLUMN expiracao_sincronizada INTEGER NOT NULL DEFAULT 0
                """
            )


def criar_produto(
    caminho_banco: str | Path,
    titulo: str,
    descricao: str,
    preco_centavos: int,
    dias_vip: int = 0,
) -> int:
    titulo = titulo.strip()
    if not titulo or len(titulo) > 80:
        raise ValueError("O título do produto deve ter de 1 a 80 caracteres.")
    if len(descricao) > 500:
        raise ValueError("A descrição do produto pode ter até 500 caracteres.")
    if isinstance(preco_centavos, bool) or not isinstance(preco_centavos, int) or preco_centavos <= 0:
        raise ValueError("O preço deve ser um valor positivo em centavos.")
    if preco_centavos > 100_000_000:
        raise ValueError("O preço máximo por produto é R$ 1.000.000,00.")
    if isinstance(dias_vip, bool) or not isinstance(dias_vip, int) or dias_vip < -1:
        raise ValueError("Use -1 para VIP permanente ou informe uma duração positiva.")
    with abrir_banco(caminho_banco) as banco:
        cursor = banco.execute(
            """
            INSERT INTO produtos (titulo, descricao, preco_centavos, dias_vip, criado_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (titulo, descricao.strip(), preco_centavos, dias_vip, _agora()),
        )
        return int(cursor.lastrowid)


def criar_missao(
    caminho_banco: str | Path,
    titulo: str,
    descricao: str,
    premio: str,
) -> int:
    titulo = titulo.strip()
    descricao = descricao.strip()
    premio = premio.strip()
    if not titulo or len(titulo) > 80:
        raise ValueError("O título da missão deve ter de 1 a 80 caracteres.")
    if not descricao or len(descricao) > 1000:
        raise ValueError("A descrição da missão deve ter de 1 a 1000 caracteres.")
    if not premio or len(premio) > 200:
        raise ValueError("Informe um prêmio de até 200 caracteres.")
    with abrir_banco(caminho_banco) as banco:
        cursor = banco.execute(
            """
            INSERT INTO missoes (titulo, descricao, premio, criada_em)
            VALUES (?, ?, ?, ?)
            """,
            (titulo, descricao, premio, _agora()),
        )
        return int(cursor.lastrowid)


def criar_meta_exploracao(
    caminho_banco: str | Path, titulo: str, total: int
) -> int:
    titulo = titulo.strip()
    if not titulo or len(titulo) > 80:
        raise ValueError("O nome da meta deve ter de 1 a 80 caracteres.")
    if isinstance(total, bool) or not isinstance(total, int) or not 1 <= total <= 100_000:
        raise ValueError("O total deve estar entre 1 e 100.000.")
    with abrir_banco(caminho_banco) as banco:
        existente = banco.execute(
            "SELECT id FROM metas_exploracao WHERE titulo = ?", (titulo,)
        ).fetchone()
        if existente:
            raise ValueError("Já existe uma meta com esse nome.")
        cursor = banco.execute(
            """
            INSERT INTO metas_exploracao (titulo, total, criada_em)
            VALUES (?, ?, ?)
            """,
            (titulo, total, _agora()),
        )
        return int(cursor.lastrowid)


def atualizar_progresso_exploracao(
    caminho_banco: str | Path,
    meta_id: int,
    discord_id: str,
    quantidade: int,
    atualizado_por: str,
) -> None:
    if (
        isinstance(quantidade, bool)
        or not isinstance(quantidade, int)
        or quantidade < 0
    ):
        raise ValueError("O progresso deve ser um inteiro não negativo.")
    with abrir_banco(caminho_banco) as banco:
        meta = banco.execute(
            "SELECT total FROM metas_exploracao WHERE id = ? AND ativa = 1",
            (meta_id,),
        ).fetchone()
        if meta is None:
            raise ValueError("Meta inexistente ou desativada.")
        if quantidade > meta["total"]:
            raise ValueError("O progresso não pode ultrapassar o total cadastrado.")
        banco.execute(
            """
            INSERT INTO progresso_exploracao
                (meta_id, discord_id, quantidade, atualizado_por, atualizado_em)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (meta_id, discord_id) DO UPDATE SET
                quantidade = excluded.quantidade,
                atualizado_por = excluded.atualizado_por,
                atualizado_em = excluded.atualizado_em
            """,
            (meta_id, discord_id, quantidade, atualizado_por, _agora()),
        )


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _chamar_api(
    url: str,
    *,
    metodo: str = "GET",
    token: str,
    dados: dict[str, Any] | None = None,
    cabecalhos: dict[str, str] | None = None,
    tempo_limite: float = 10,
) -> dict[str, Any]:
    corpo = (
        json.dumps(dados, ensure_ascii=False).encode("utf-8")
        if dados is not None
        else None
    )
    requisicao = Request(
        url,
        data=corpo,
        method=metodo,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if corpo else {}),
            **(cabecalhos or {}),
        },
    )
    try:
        with urlopen(requisicao, timeout=tempo_limite) as resposta:
            conteudo = resposta.read()
    except HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="replace")[:300]
        raise ErroIntegracao(
            f"O serviço externo respondeu HTTP {erro.code}: {detalhe}"
        ) from erro
    except (URLError, TimeoutError, OSError) as erro:
        raise ErroIntegracao(f"Não foi possível acessar o serviço externo: {erro}") from erro
    if not conteudo:
        return {}
    try:
        resultado = json.loads(conteudo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise ErroIntegracao("O serviço externo retornou uma resposta inválida.") from erro
    if not isinstance(resultado, dict):
        raise ErroIntegracao("O serviço externo retornou um formato inesperado.")
    return resultado


def validar_assinatura_webhook(
    assinatura: str | None,
    requisicao_id: str | None,
    id_dado: str | None,
    segredo: str,
) -> bool:
    if not assinatura or not requisicao_id or not id_dado or not segredo:
        return False
    partes = {}
    for parte in assinatura.split(","):
        chave, separador, valor = parte.strip().partition("=")
        if separador and chave in ("ts", "v1"):
            partes[chave] = valor
    timestamp = partes.get("ts", "")
    assinatura_recebida = partes.get("v1", "")
    if (
        not timestamp.isdigit()
        or len(assinatura_recebida) != 64
        or any(caractere not in "0123456789abcdefABCDEF" for caractere in assinatura_recebida)
    ):
        return False
    manifesto = f"id:{id_dado.lower()};request-id:{requisicao_id};ts:{timestamp};"
    esperada = hmac.new(
        segredo.encode("utf-8"), manifesto.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(esperada, assinatura_recebida)


def _normalizar_ids(valor: str) -> set[str]:
    return {parte.strip() for parte in valor.split(",") if parte.strip()}


def criar_app(configuracao: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    chave_configurada = os.environ.get("PORTAL_SECRET_KEY")
    app.config.from_mapping(
        SECRET_KEY=chave_configurada or secrets.token_hex(32),
        DATABASE_PATH=os.environ.get(
            "PORTAL_DATABASE_PATH", str(DATABASE_PADRAO)
        ),
        PORTAL_PUBLIC_URL=os.environ.get(
            "PORTAL_PUBLIC_URL", "http://127.0.0.1:5000"
        ).rstrip("/"),
        DISCORD_CLIENT_ID=os.environ.get("DISCORD_CLIENT_ID", ""),
        DISCORD_CLIENT_SECRET=os.environ.get("DISCORD_CLIENT_SECRET", ""),
        DISCORD_ADMIN_IDS=os.environ.get("DISCORD_ADMIN_IDS", ""),
        DISCORD_BOT_TOKEN=os.environ.get("DISCORD_BOT_TOKEN", ""),
        DISCORD_GUILD_ID=os.environ.get("DISCORD_GUILD_ID", ""),
        DISCORD_VIP_ROLE_ID=os.environ.get("DISCORD_VIP_ROLE_ID", ""),
        PALWORLD_API_URL=os.environ.get("PALWORLD_API_URL", ""),
        PALWORLD_ADMIN_PASSWORD=os.environ.get("PALWORLD_ADMIN_PASSWORD", ""),
        MERCADOPAGO_ACCESS_TOKEN=os.environ.get("MERCADOPAGO_ACCESS_TOKEN", ""),
        MERCADOPAGO_WEBHOOK_SECRET=os.environ.get("MERCADOPAGO_WEBHOOK_SECRET", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("PORTAL_PUBLIC_URL", "").startswith(
            "https://"
        ),
    )
    if configuracao:
        app.config.update(configuracao)
    if "SESSION_COOKIE_SECURE" not in (configuracao or {}):
        app.config["SESSION_COOKIE_SECURE"] = app.config[
            "PORTAL_PUBLIC_URL"
        ].startswith("https://")
    if os.environ.get("PORTAL_ENV") == "production" and not chave_configurada:
        raise RuntimeError("Defina PORTAL_SECRET_KEY antes de iniciar em produção.")
    if os.environ.get("PORTAL_ENV") == "production":
        origem = urlsplit(app.config["PORTAL_PUBLIC_URL"])
        if (
            len(chave_configurada or "") < 32
            or chave_configurada == "gere-uma-chave-aleatoria-forte"
        ):
            raise RuntimeError("PORTAL_SECRET_KEY precisa ser uma chave aleatória forte.")
        if (
            origem.scheme != "https"
            or not origem.hostname
            or origem.path not in ("", "/")
            or origem.username
            or origem.password
            or origem.query
            or origem.fragment
        ):
            raise RuntimeError("Em produção, PORTAL_PUBLIC_URL deve ser uma origem HTTPS.")

    inicializar_banco(app.config["DATABASE_PATH"])

    @app.before_request
    def carregar_banco() -> None:
        g.banco = conectar_banco(current_app.config["DATABASE_PATH"])

    @app.teardown_appcontext
    def fechar_banco(_erro: BaseException | None = None) -> None:
        banco = g.pop("banco", None)
        if banco is not None:
            banco.close()

    def login_obrigatorio(funcao):
        @wraps(funcao)
        def protegida(*args, **kwargs):
            if not session.get("discord_id"):
                return redirect(url_for("login", proximo=request.path))
            return funcao(*args, **kwargs)

        return protegida

    def verificar_csrf() -> None:
        fornecido = request.form.get("csrf_token", "")
        esperado = session.get("csrf_token", "")
        if not esperado or not secrets.compare_digest(fornecido, esperado):
            abort(400, description="Formulário expirado ou inválido. Atualize a página.")

    def usuario_e_admin() -> bool:
        return session.get("discord_id", "") in _normalizar_ids(
            current_app.config["DISCORD_ADMIN_IDS"]
        )

    def gerar_token_csrf() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    @app.context_processor
    def contexto_global() -> dict[str, Any]:
        return {
            "usuario": session.get("discord_nome"),
            "discord_id": session.get("discord_id"),
            "csrf_token": gerar_token_csrf(),
            "eh_admin": usuario_e_admin(),
        }

    @app.template_filter("moeda_brasileira")
    def moeda_brasileira(valor_centavos: int) -> str:
        valor = f"{valor_centavos / 100:,.2f}"
        valor = valor.replace(",", "TEMP").replace(".", ",").replace("TEMP", ".")
        return f"R$ {valor}"

    @app.get("/")
    def inicio():
        produtos = g.banco.execute(
            "SELECT * FROM produtos WHERE ativo = 1 ORDER BY id DESC"
        ).fetchall()
        missoes = g.banco.execute(
            "SELECT * FROM missoes WHERE ativa = 1 ORDER BY id DESC"
        ).fetchall()
        pedidos = []
        reivindicacoes = []
        progresso = []
        if session.get("discord_id"):
            pedidos = g.banco.execute(
                """
                SELECT titulo_produto, valor_centavos, status, vip_status, criado_em
                FROM pedidos WHERE discord_id = ? ORDER BY criado_em DESC LIMIT 10
                """,
                (session["discord_id"],),
            ).fetchall()
            reivindicacoes = g.banco.execute(
                """
                SELECT r.id, r.status, r.prova, r.criada_em, m.titulo, m.premio
                FROM reivindicacoes r JOIN missoes m ON m.id = r.missao_id
                WHERE r.discord_id = ? ORDER BY r.criada_em DESC LIMIT 10
                """,
                (session["discord_id"],),
            ).fetchall()
            progresso = g.banco.execute(
                """
                SELECT m.id, m.titulo, m.total,
                       COALESCE(p.quantidade, 0) AS quantidade
                FROM metas_exploracao m
                LEFT JOIN progresso_exploracao p
                    ON p.meta_id = m.id AND p.discord_id = ?
                WHERE m.ativa = 1
                ORDER BY m.id
                """,
                (session["discord_id"],),
            ).fetchall()
        return render_template(
            "portal.html",
            produtos=produtos,
            missoes=missoes,
            pedidos=pedidos,
            reivindicacoes=reivindicacoes,
            progresso=progresso,
        )

    @app.get("/api/mapa/jogadores")
    @login_obrigatorio
    def mapa_jogadores():
        endereco = current_app.config["PALWORLD_API_URL"]
        senha = current_app.config["PALWORLD_ADMIN_PASSWORD"]
        if not endereco or not senha:
            resposta = jsonify({
                "erro": "A conexão privada com a API do servidor ainda não foi configurada."
            })
            resposta.status_code = 503
            resposta.headers["Cache-Control"] = "no-store"
            return resposta
        try:
            jogadores = ClienteRESTPalworld(
                endereco, senha, tempo_limite=5
            ).listar_jogadores()
        except (ValueError, ErroAPIPalworld) as erro:
            LOG.warning("Falha ao carregar posições do servidor: %s", erro)
            resposta = jsonify(
                {"erro": "Não foi possível consultar a posição dos jogadores."}
            )
            resposta.status_code = 503
            resposta.headers["Cache-Control"] = "no-store"
            return resposta
        posicoes = []
        for jogador in jogadores:
            x = jogador.get("location_x")
            y = jogador.get("location_y")
            nivel = jogador.get("level")
            if (
                isinstance(x, bool)
                or not isinstance(x, (int, float))
                or isinstance(y, bool)
                or not isinstance(y, (int, float))
            ):
                continue
            posicoes.append(
                {
                    "nome": str(jogador.get("name", "Jogador"))[:80],
                    "x": x,
                    "y": y,
                    "nivel": nivel if isinstance(nivel, int) and not isinstance(nivel, bool) else None,
                }
            )
        resposta = jsonify({
            "jogadores": posicoes,
            "quantidade": len(posicoes),
            "atualizado_em": _agora(),
        })
        resposta.headers["Cache-Control"] = "no-store"
        return resposta

    @app.get("/login")
    def login():
        if not current_app.config["DISCORD_CLIENT_ID"] or not current_app.config[
            "DISCORD_CLIENT_SECRET"
        ]:
            flash("O login do Discord ainda não foi configurado.", "erro")
            return redirect(url_for("inicio"))
        estado = secrets.token_urlsafe(32)
        session["oauth_state"] = estado
        session["proxima_pagina"] = request.args.get("proximo", "/")
        redirecionamento = current_app.config["PORTAL_PUBLIC_URL"] + url_for(
            "retorno_discord"
        )
        parametros = urlencode(
            {
                "client_id": current_app.config["DISCORD_CLIENT_ID"],
                "redirect_uri": redirecionamento,
                "response_type": "code",
                "scope": "identify",
                "state": estado,
            }
        )
        return redirect(f"https://discord.com/oauth2/authorize?{parametros}")

    @app.get("/auth/discord")
    def retorno_discord():
        estado = request.args.get("state", "")
        esperado = session.pop("oauth_state", "")
        codigo = request.args.get("code", "")
        if not esperado or not secrets.compare_digest(estado, esperado) or not codigo:
            abort(400, description="Não foi possível validar o retorno do Discord.")
        redirect_uri = current_app.config["PORTAL_PUBLIC_URL"] + url_for(
            "retorno_discord"
        )
        corpo = urlencode(
            {
                "client_id": current_app.config["DISCORD_CLIENT_ID"],
                "client_secret": current_app.config["DISCORD_CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": codigo,
                "redirect_uri": redirect_uri,
            }
        ).encode("utf-8")
        requisicao = Request(
            f"{URL_DISCORD_API}/oauth2/token",
            data=corpo,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urlopen(requisicao, timeout=10) as resposta:
                token_json = json.loads(resposta.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as erro:
            raise ErroIntegracao("Falha ao autenticar com o Discord.") from erro
        if not isinstance(token_json, dict) or not token_json.get("access_token"):
            raise ErroIntegracao("O Discord não retornou um token de acesso válido.")
        usuario_discord = _chamar_api(
            f"{URL_DISCORD_API}/users/@me", token=token_json["access_token"]
        )
        if not usuario_discord.get("id") or not usuario_discord.get("username"):
            raise ErroIntegracao("O Discord não retornou o perfil esperado.")
        destino = session.get("proxima_pagina", "/")
        session.clear()
        session["discord_id"] = str(usuario_discord["id"])
        session["discord_nome"] = str(usuario_discord["username"])
        if not isinstance(destino, str) or not destino.startswith("/") or destino.startswith("//"):
            destino = "/"
        return redirect(destino)

    @app.post("/sair")
    def sair():
        verificar_csrf()
        session.clear()
        return redirect(url_for("inicio"))

    @app.post("/missoes/<int:missao_id>/enviar")
    @login_obrigatorio
    def enviar_reivindicacao(missao_id: int):
        verificar_csrf()
        prova = request.form.get("prova", "").strip()
        if len(prova) < 10 or len(prova) > 1000:
            flash("Descreva a comprovação da missão (de 10 a 1000 caracteres).", "erro")
            return redirect(url_for("inicio"))
        missao = g.banco.execute(
            "SELECT id FROM missoes WHERE id = ? AND ativa = 1", (missao_id,)
        ).fetchone()
        if missao is None:
            abort(404)
        pendente = g.banco.execute(
            """
            SELECT id FROM reivindicacoes
            WHERE missao_id = ? AND discord_id = ? AND status IN ('pendente', 'aprovada')
            """,
            (missao_id, session["discord_id"]),
        ).fetchone()
        if pendente:
            flash("Você já enviou essa missão ou ela já foi aprovada.", "aviso")
            return redirect(url_for("inicio"))
        g.banco.execute(
            """
            INSERT INTO reivindicacoes (missao_id, discord_id, prova, criada_em)
            VALUES (?, ?, ?, ?)
            """,
            (missao_id, session["discord_id"], prova, _agora()),
        )
        g.banco.commit()
        flash("Comprovação enviada para análise da equipe.", "sucesso")
        return redirect(url_for("inicio"))

    @app.post("/loja/<int:produto_id>/comprar")
    @login_obrigatorio
    def comprar(produto_id: int):
        verificar_csrf()
        token = current_app.config["MERCADOPAGO_ACCESS_TOKEN"]
        if not token:
            flash("A loja ainda não foi configurada para receber pagamentos.", "erro")
            return redirect(url_for("inicio"))
        produto = g.banco.execute(
            "SELECT * FROM produtos WHERE id = ? AND ativo = 1", (produto_id,)
        ).fetchone()
        if produto is None:
            abort(404)
        pedido_id = str(uuid.uuid4())
        horario = _agora()
        g.banco.execute(
            """
            INSERT INTO pedidos
                (id, discord_id, produto_id, titulo_produto, valor_centavos,
                 dias_vip, status, vip_status, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, 'iniciando', ?, ?, ?)
            """,
            (
                pedido_id,
                session["discord_id"],
                produto["id"],
                produto["titulo"],
                produto["preco_centavos"],
                produto["dias_vip"],
                "pendente" if produto["dias_vip"] else "nao_aplicavel",
                horario,
                horario,
            ),
        )
        g.banco.commit()
        base_url = current_app.config["PORTAL_PUBLIC_URL"]
        preferencia = {
            "items": [
                {
                    "id": str(produto["id"]),
                    "title": produto["titulo"],
                    "description": produto["descricao"] or produto["titulo"],
                    "quantity": 1,
                    "unit_price": float(Decimal(produto["preco_centavos"]) / 100),
                    "currency_id": "BRL",
                }
            ],
            "external_reference": pedido_id,
            "notification_url": f"{base_url}{url_for('webhook_mercadopago')}",
            "back_urls": {
                "success": f"{base_url}/?pagamento=retorno",
                "pending": f"{base_url}/?pagamento=pendente",
                "failure": f"{base_url}/?pagamento=falha",
            },
            "auto_return": "approved",
            "metadata": {"pedido_id": pedido_id},
        }
        requisicao = Request(
            f"{URL_MERCADOPAGO_API}/checkout/preferences",
            data=json.dumps(preferencia).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Idempotency-Key": pedido_id,
            },
        )
        try:
            with urlopen(requisicao, timeout=10) as resposta:
                retorno = json.loads(resposta.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as erro:
            LOG.exception("Falha ao criar checkout do pedido %s", pedido_id)
            g.banco.execute(
                "UPDATE pedidos SET status = 'falha_checkout', atualizado_em = ? WHERE id = ?",
                (_agora(), pedido_id),
            )
            g.banco.commit()
            flash("Não foi possível iniciar o pagamento. Tente novamente mais tarde.", "erro")
            return redirect(url_for("inicio"))
        link = retorno.get("init_point") if isinstance(retorno, dict) else None
        if not isinstance(link, str) or not link.startswith("https://"):
            g.banco.execute(
                "UPDATE pedidos SET status = 'falha_checkout', atualizado_em = ? WHERE id = ?",
                (_agora(), pedido_id),
            )
            g.banco.commit()
            LOG.error("Mercado Pago não retornou init_point HTTPS para o pedido %s", pedido_id)
            flash("O Mercado Pago não retornou um checkout seguro. Tente novamente.", "erro")
            return redirect(url_for("inicio"))
        g.banco.execute(
            "UPDATE pedidos SET status = 'aguardando_pagamento', link_checkout = ?, atualizado_em = ? WHERE id = ?",
            (link, _agora(), pedido_id),
        )
        g.banco.commit()
        return redirect(link)

    @app.get("/webhooks/mercadopago")
    @app.post("/webhooks/mercadopago")
    def webhook_mercadopago():
        id_pagamento = request.args.get("data.id") or request.args.get("id")
        if not validar_assinatura_webhook(
            request.headers.get("x-signature"),
            request.headers.get("x-request-id"),
            id_pagamento,
            current_app.config["MERCADOPAGO_WEBHOOK_SECRET"],
        ):
            abort(401)
        token = current_app.config["MERCADOPAGO_ACCESS_TOKEN"]
        if not token or not id_pagamento or not id_pagamento.isdigit():
            abort(400)
        pagamento = _chamar_api(
            f"{URL_MERCADOPAGO_API}/v1/payments/{id_pagamento}", token=token
        )
        pedido_id = pagamento.get("external_reference")
        if not isinstance(pedido_id, str):
            LOG.warning("Pagamento validado sem external_reference: %s", id_pagamento)
            return "", 200
        pedido = g.banco.execute(
            "SELECT * FROM pedidos WHERE id = ?", (pedido_id,)
        ).fetchone()
        if pedido is None:
            LOG.warning("Pagamento validado sem pedido correspondente: %s", id_pagamento)
            return "", 200
        valor_centavos = _valor_em_centavos(pagamento.get("transaction_amount"))
        if (
            pagamento.get("currency_id") != "BRL"
            or valor_centavos != pedido["valor_centavos"]
        ):
            LOG.error("Valor/moeda divergente no pagamento %s", id_pagamento)
            abort(400)
        pagamento_existente = g.banco.execute(
            "SELECT id FROM pedidos WHERE id_pagamento = ? AND id != ?",
            (str(id_pagamento), pedido_id),
        ).fetchone()
        if pagamento_existente:
            abort(409)
        status = str(pagamento.get("status", "desconhecido"))
        g.banco.execute(
            """
            UPDATE pedidos SET status = ?, id_pagamento = ?, atualizado_em = ?
            WHERE id = ?
            """,
            (status, str(id_pagamento), _agora(), pedido_id),
        )
        if status == "approved" and pedido["dias_vip"] != 0:
            _registrar_beneficio_vip(g.banco, pedido)
        elif status in ("refunded", "charged_back") and pedido["dias_vip"] != 0:
            g.banco.execute(
                "DELETE FROM beneficios_vip WHERE pedido_id = ?", (pedido_id,)
            )
        g.banco.commit()
        if status == "approved" and pedido["dias_vip"] != 0:
            _sincronizar_cargo_vip(pedido["discord_id"], adicionar=True)
            g.banco.execute(
                "UPDATE pedidos SET vip_status = 'aplicado', atualizado_em = ? WHERE id = ?",
                (_agora(), pedido_id),
            )
            g.banco.commit()
        elif status in ("refunded", "charged_back") and pedido["dias_vip"] != 0:
            vip_ativo = g.banco.execute(
                """
                SELECT 1 FROM beneficios_vip
                WHERE discord_id = ?
                    AND (expira_em IS NULL OR expira_em > ?)
                LIMIT 1
                """,
                (pedido["discord_id"], _agora()),
            ).fetchone()
            if not vip_ativo:
                _sincronizar_cargo_vip(pedido["discord_id"], adicionar=False)
            g.banco.execute(
                "UPDATE pedidos SET vip_status = ?, atualizado_em = ? WHERE id = ?",
                ("removido" if not vip_ativo else "mantido", _agora(), pedido_id),
            )
            g.banco.commit()
        return "", 200

    @app.get("/saude")
    def saude():
        return {"estado": "ok"}

    def _sincronizar_cargo_vip(discord_id: str, *, adicionar: bool) -> None:
        bot_token = current_app.config["DISCORD_BOT_TOKEN"]
        guild_id = current_app.config["DISCORD_GUILD_ID"]
        role_id = current_app.config["DISCORD_VIP_ROLE_ID"]
        if not bot_token or not guild_id or not role_id:
            raise ErroIntegracao("Configure bot, servidor e cargo VIP do Discord.")
        url = (
            f"{URL_DISCORD_API}/guilds/{guild_id}/members/{discord_id}"
            f"/roles/{role_id}"
        )
        requisicao = Request(
            url,
            method="PUT" if adicionar else "DELETE",
            headers={
                "Authorization": f"Bot {bot_token}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(requisicao, timeout=10):
                return
        except HTTPError as erro:
            detalhe = erro.read().decode("utf-8", errors="replace")[:300]
            raise ErroIntegracao(
                f"Não foi possível atualizar o cargo VIP no Discord (HTTP {erro.code}): {detalhe}"
            ) from erro
        except (URLError, TimeoutError, OSError) as erro:
            raise ErroIntegracao(f"Falha ao atualizar o cargo VIP no Discord: {erro}") from erro

    def _registrar_beneficio_vip(
        banco: sqlite3.Connection, pedido: sqlite3.Row
    ) -> None:
        existente = banco.execute(
            "SELECT id FROM beneficios_vip WHERE pedido_id = ?", (pedido["id"],)
        ).fetchone()
        if existente:
            return
        expiracao = None
        if pedido["dias_vip"] > 0:
            atual = datetime.now(timezone.utc)
            expiracao_atual = banco.execute(
                """
                SELECT MAX(expira_em) AS maximo FROM beneficios_vip
                WHERE discord_id = ? AND expira_em IS NOT NULL AND expira_em > ?
                """,
                (pedido["discord_id"], atual.isoformat(timespec="seconds")),
            ).fetchone()["maximo"]
            if expiracao_atual:
                atual = max(atual, datetime.fromisoformat(expiracao_atual))
            expiracao = (atual + timedelta(days=pedido["dias_vip"])).isoformat(
                timespec="seconds"
            )
        banco.execute(
            """
            INSERT INTO beneficios_vip (pedido_id, discord_id, expira_em)
            VALUES (?, ?, ?)
            """,
            (pedido["id"], pedido["discord_id"], expiracao),
        )

    app.extensions["portal_login_obrigatorio"] = login_obrigatorio
    app.extensions["portal_usuario_e_admin"] = usuario_e_admin
    app.extensions["portal_verificar_csrf"] = verificar_csrf
    app.extensions["portal_sincronizar_cargo_vip"] = _sincronizar_cargo_vip

    @app.after_request
    def adicionar_cabecalhos_seguranca(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resposta.headers.setdefault("Cache-Control", "no-store")
        resposta.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'",
        )
        if current_app.config["PORTAL_PUBLIC_URL"].startswith("https://"):
            resposta.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resposta

    return app


def _valor_em_centavos(valor: object) -> int | None:
    try:
        quantia = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None
    if not quantia.is_finite() or quantia < 0:
        return None
    centavos = quantia * 100
    if centavos != centavos.to_integral_value():
        return None
    return int(centavos)


app = criar_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("PORTAL_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORTAL_PORT", "5000")),
        debug=False,
    )
