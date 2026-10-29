"""Interface visual em português para configurar um servidor dedicado Palworld."""

from __future__ import annotations

import ipaddress
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote, urlsplit
import webbrowser

from instalador_servidor import (
    instalar_servidor_palworld,
    preparar_steamcmd,
    verificar_espaco_destino,
)
from eventos_palworld import (
    FREQUENCIAS,
    TIPOS_EVENTO,
    carregar_eventos,
    criar_evento,
    formatar_proxima_execucao,
    processar_agenda,
    salvar_eventos,
)
from palworld_admin import ClienteRESTPalworld, ErroAPIPalworld


NOME_CONFIGURACAO = "PalWorldSettings.ini"
NOME_MODELO = "DefaultPalWorldSettings.ini"
CAMINHO_CONFIGURACAO = Path(
    "Pal", "Saved", "Config", "WindowsServer", NOME_CONFIGURACAO
)
PORTA_PADRAO = 8211
JOGADORES_PADRAO = 10
JOGADORES_MAXIMO = 32
PLATAFORMAS = ("Steam", "Xbox", "PS5", "Mac")
PORTA_REST_PADRAO = 8212
URL_SPHERE_RELEASES = "https://github.com/projectsphere/sphere/releases"
URL_DISCORD_DEVELOPER = "https://discord.com/developers/applications"
URL_PALDEFENDER = "https://www.nexusmods.com/palworld/mods/451"
URL_PALDEFENDER_GUIA = "https://ultimeit.github.io/PalDefender/"
CAMINHO_EVENTOS = Path(
    os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local"),
    ),
    "ConfiguradorPalworld",
    "eventos.json",
)
PASTA_DADOS_APP = Path(
    os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local"),
    ),
    "ConfiguradorPalworld",
)
CAMINHO_SERVIDOR_PADRAO = PASTA_DADOS_APP / "PalServer"
CAMINHO_STEAMCMD = PASTA_DADOS_APP / "SteamCMD"
URL_PORTAL_LOCAL = "http://127.0.0.1"
PASTAS_SERVIDOR_COMUNS = (
    CAMINHO_SERVIDOR_PADRAO,
    Path(r"C:\SteamLibrary\steamapps\common\PalServer"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\PalServer"),
    Path(r"C:\Program Files\Steam\steamapps\common\PalServer"),
)


def gerar_configuracao_portal_hospedagem(
    url_publica: str, url_api_privada: str = ""
) -> str:
    origem = urlsplit(url_publica.strip())
    if (
        origem.scheme != "https"
        or not origem.hostname
        or origem.username
        or origem.password
        or origem.path not in ("", "/")
        or origem.query
        or origem.fragment
    ):
        raise ValueError("O endereço público do portal precisa ser uma origem HTTPS válida.")
    try:
        origem.port
    except ValueError as erro:
        raise ValueError("A porta do endereço público do portal é inválida.") from erro

    linhas = [
        "# Configuração não secreta do Portal Pandora para o provedor.",
        "# Cadastre credenciais e senhas no cofre de segredos do provedor.",
        f"PORTAL_PUBLIC_URL={origem.scheme}://{origem.netloc}",
    ]
    endereco_api = url_api_privada.strip()
    if endereco_api:
        ClienteRESTPalworld(endereco_api, "validacao-local")
        linhas.append(f"PALWORLD_API_URL={endereco_api.rstrip('/')}")
    return "\n".join(linhas) + "\n"


def encontrar_servidor() -> Path | None:
    """Localiza o PalServer em alguns diretórios comuns da Steam."""
    for pasta in PASTAS_SERVIDOR_COMUNS:
        if (pasta / "PalServer.exe").is_file():
            return pasta
    return None


def validar_configuracao(
    nome: str,
    quantidade_jogadores: int,
    porta: int,
    plataformas: list[str] | tuple[str, ...],
) -> None:
    if not nome.strip():
        raise ValueError("Informe um nome para o servidor.")
    if "\n" in nome or "\r" in nome or '"' in nome:
        raise ValueError("O nome não pode conter aspas nem quebras de linha.")
    if (
        isinstance(quantidade_jogadores, bool)
        or not isinstance(quantidade_jogadores, int)
        or not 1 <= quantidade_jogadores <= JOGADORES_MAXIMO
    ):
        raise ValueError(
            f"O limite de jogadores precisa estar entre 1 e {JOGADORES_MAXIMO}."
        )
    if isinstance(porta, bool) or not isinstance(porta, int) or not 1 <= porta <= 65535:
        raise ValueError("A porta UDP precisa estar entre 1 e 65535.")
    if any(plataforma not in PLATAFORMAS for plataforma in plataformas):
        raise ValueError("A lista contém uma plataforma não suportada.")


def interpretar_opcoes(linha: str) -> dict[str, str]:
    """Lê pares Opção=Valor, respeitando vírgulas entre aspas ou parênteses."""
    conteudo = linha.strip()
    prefixo = "OptionSettings=("
    if not conteudo.startswith(prefixo) or not conteudo.endswith(")"):
        raise ValueError("O modelo não contém uma linha OptionSettings válida.")

    conteudo = conteudo[len(prefixo) : -1]
    opcoes: dict[str, str] = {}
    inicio = 0
    profundidade = 0
    entre_aspas = False
    escape = False
    partes: list[str] = []

    for indice, caractere in enumerate(conteudo):
        if escape:
            escape = False
            continue
        if entre_aspas and caractere == "\\":
            escape = True
            continue
        if caractere == '"':
            entre_aspas = not entre_aspas
        elif not entre_aspas:
            if caractere == "(":
                profundidade += 1
            elif caractere == ")":
                profundidade -= 1
            elif caractere == "," and profundidade == 0:
                partes.append(conteudo[inicio:indice])
                inicio = indice + 1
    partes.append(conteudo[inicio:])

    for parte in partes:
        chave, separador, valor = parte.partition("=")
        if not separador or not chave.strip():
            raise ValueError("O modelo contém uma opção inválida.")
        opcoes[chave.strip()] = valor.strip()
    return opcoes


def carregar_opcoes_modelo(texto: str) -> tuple[str, dict[str, str]]:
    linhas = texto.splitlines()
    for indice, linha in enumerate(linhas):
        if linha.strip().startswith("OptionSettings=("):
            return "\n".join(linhas[:indice]), interpretar_opcoes(linha)
    raise ValueError("O arquivo não contém OptionSettings.")


def _formatar_texto_ini(valor: str) -> str:
    if "\n" in valor or "\r" in valor:
        raise ValueError("Os textos do servidor não podem conter quebras de linha.")
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def gerar_pal_world_settings(
    modelo: str,
    *,
    nome: str,
    descricao: str,
    quantidade_jogadores: int,
    porta: int,
    senha_servidor: str,
    senha_administrador: str,
    plataformas: list[str] | tuple[str, ...],
    api_rest_ativada: bool = False,
    porta_api_rest: int = PORTA_REST_PADRAO,
    rcon_ativado: bool = False,
    porta_rcon: int = 25575,
) -> str:
    validar_configuracao(nome, quantidade_jogadores, porta, plataformas)
    if isinstance(porta_api_rest, bool) or not isinstance(porta_api_rest, int) or not 1 <= porta_api_rest <= 65535:
        raise ValueError("A porta da API REST precisa estar entre 1 e 65535.")
    if isinstance(porta_rcon, bool) or not isinstance(porta_rcon, int) or not 1 <= porta_rcon <= 65535:
        raise ValueError("A porta RCON precisa estar entre 1 e 65535.")
    if api_rest_ativada and rcon_ativado and porta_api_rest == porta_rcon:
        raise ValueError("A API REST e o RCON precisam usar portas diferentes.")
    if (api_rest_ativada or rcon_ativado) and not senha_administrador:
        raise ValueError(
            "Defina uma senha de administrador antes de ativar a API REST ou o RCON."
        )
    if "\n" in descricao or "\r" in descricao:
        raise ValueError("A descrição não pode conter quebras de linha.")
    if any("\n" in senha or "\r" in senha for senha in (senha_servidor, senha_administrador)):
        raise ValueError("As senhas não podem conter quebras de linha.")

    cabecalho, opcoes = carregar_opcoes_modelo(modelo)
    opcoes.update(
        {
            "ServerName": _formatar_texto_ini(nome.strip()),
            "ServerDescription": _formatar_texto_ini(descricao.strip()),
            "ServerPlayerMaxNum": str(quantidade_jogadores),
            "PublicPort": str(porta),
            "ServerPassword": _formatar_texto_ini(senha_servidor),
            "AdminPassword": _formatar_texto_ini(senha_administrador),
            "bIsMultiplay": "True",
            "CrossplayPlatforms": f"({','.join(plataformas)})",
            "RESTAPIEnabled": str(api_rest_ativada),
            "RESTAPIPort": str(porta_api_rest),
            "RCONEnabled": str(rcon_ativado),
            "RCONPort": str(porta_rcon),
        }
    )
    linha_opcoes = "OptionSettings=(" + ",".join(
        f"{chave}={valor}" for chave, valor in opcoes.items()
    ) + ")"
    return f"{cabecalho.rstrip()}\n{linha_opcoes}\n"


def gravar_configuracao_segura(
    destino: Path, conteudo: str, *, criar_backup: bool = True
) -> Path | None:
    """Preserva uma cópia da configuração anterior e substitui o arquivo atomicamente."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if criar_backup and destino.exists() and destino.stat().st_size:
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = destino.with_name(f"{destino.name}.{carimbo}.bak")
        sufixo = 1
        while backup.exists():
            backup = destino.with_name(f"{destino.name}.{carimbo}-{sufixo}.bak")
            sufixo += 1
        shutil.copy2(destino, backup)

    arquivo_temporario: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destino.parent,
            prefix=f".{destino.name}.",
            suffix=".tmp",
            delete=False,
        ) as arquivo:
            arquivo.write(conteudo)
            arquivo_temporario = Path(arquivo.name)
        os.replace(arquivo_temporario, destino)
    except OSError:
        if arquivo_temporario is not None:
            arquivo_temporario.unlink(missing_ok=True)
        raise
    return backup


def listar_enderecos_locais() -> list[str]:
    """Retorna endereços IPv4 privados encontrados no computador."""
    enderecos: set[str] = set()
    try:
        resultados = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    for resultado in resultados:
        endereco = resultado[4][0]
        ip = ipaddress.ip_address(endereco)
        if ip.is_private and not ip.is_loopback and not ip.is_link_local:
            enderecos.add(endereco)
    return sorted(enderecos)


class ConfiguradorPalworld:
    def __init__(
        self, janela: tk.Tk, *, caminho_eventos: Path = CAMINHO_EVENTOS
    ) -> None:
        self.janela = janela
        self.janela.title("Menu, palworld server")
        self.janela.minsize(800, 760)
        self.pasta_servidor = tk.StringVar(
            value=str(encontrar_servidor() or CAMINHO_SERVIDOR_PADRAO)
        )
        self.nome_servidor = tk.StringVar(value="Servidor dos Amigos")
        self.descricao_servidor = tk.StringVar(value="Servidor privado")
        self.quantidade_jogadores = tk.StringVar(value=str(JOGADORES_PADRAO))
        self.porta = tk.StringVar(value=str(PORTA_PADRAO))
        self.senha_servidor = tk.StringVar()
        self.senha_administrador = tk.StringVar()
        self.api_rest_ativada = tk.BooleanVar(value=False)
        self.porta_api_rest = tk.StringVar(value=str(PORTA_REST_PADRAO))
        self.rcon_ativado = tk.BooleanVar(value=False)
        self.porta_rcon = tk.StringVar(value="25575")
        self.endereco_api = tk.StringVar(value="http://127.0.0.1")
        self.status_api = tk.StringVar(
            value="API local: configure a senha de administrador e salve a configuração."
        )
        self.mensagem_admin = tk.StringVar()
        self.alvo_admin = tk.StringVar()
        self.pasta_sphere = tk.StringVar()
        self.sphere_app_id = tk.StringVar()
        self.sphere_token = tk.StringVar()
        self.sphere_prefixo = tk.StringVar(value="!")
        self.plataformas_ativas = {
            plataforma: tk.BooleanVar(value=True) for plataforma in PLATAFORMAS
        }
        self.status = tk.StringVar(value="Servidor parado")
        self._processo: subprocess.Popen[bytes] | None = None
        self._arquivo_log = None
        self._fila_instalacao: queue.Queue[tuple[str, str]] = queue.Queue()
        self._instalacao_em_andamento = False
        self._processo_sphere: subprocess.Popen[bytes] | None = None
        self._arquivo_log_sphere = None
        self.portal_public_url = tk.StringVar(value="https://SEU-DOMINIO")
        self.portal_api_url = tk.StringVar()
        self.portal_porta = tk.StringVar(value="5000")
        self.status_portal = tk.StringVar(value="Portal Pandora parado.")
        self._processo_portal: subprocess.Popen[bytes] | None = None
        self._arquivo_log_portal = None
        self._portal_aberto = False
        self.caminho_eventos = caminho_eventos
        try:
            self.eventos = carregar_eventos(self.caminho_eventos)
            self._agenda_disponivel = True
        except (OSError, ValueError) as erro:
            self.eventos = []
            self._agenda_disponivel = False
            messagebox.showerror("Agenda indisponível", str(erro))
        self._montar_interface()
        self.janela.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self._atualizar_enderecos()
        self._atualizar_lista_eventos()
        if self._agenda_disponivel:
            self.janela.after(10_000, self._verificar_agenda)

    def _montar_interface(self) -> None:
        raiz = ttk.Frame(self.janela, padding=16)
        raiz.pack(fill="both", expand=True)
        raiz.columnconfigure(0, weight=1)
        raiz.rowconfigure(2, weight=1)

        ttk.Label(
            raiz,
            text="Menu, palworld server",
            font=("", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            raiz,
            text="Configure seu servidor para até 10 amigos ou exporte os dados para outra hospedagem.",
            wraplength=700,
        ).grid(row=1, column=0, sticky="w", pady=(5, 12))

        abas = ttk.Notebook(raiz)
        abas.grid(row=2, column=0, sticky="nsew")
        aba_local = ttk.Frame(abas, padding=14)
        aba_externa = ttk.Frame(abas, padding=14)
        aba_eventos = ttk.Frame(abas, padding=14)
        aba_admin = ttk.Frame(abas, padding=14)
        aba_portal = ttk.Frame(abas, padding=14)
        abas.add(aba_local, text="Meu PC")
        abas.add(aba_externa, text="Outra hospedagem")
        abas.add(aba_eventos, text="Eventos")
        abas.add(aba_admin, text="Administração")
        abas.add(aba_portal, text="Portal Pandora")
        self._montar_aba_local(aba_local)
        self._montar_aba_externa(aba_externa)
        self._montar_aba_eventos(aba_eventos)
        self._montar_aba_administracao(aba_admin)
        self._montar_aba_portal(aba_portal)

        ttk.Label(raiz, textvariable=self.status).grid(
            row=3, column=0, sticky="w", pady=(10, 0)
        )

    def _montar_aba_local(self, aba: ttk.Frame) -> None:
        aba.columnconfigure(1, weight=1)
        ttk.Label(aba, text="Pasta do servidor dedicado:").grid(
            row=0, column=0, sticky="w", pady=4
        )
        ttk.Entry(aba, textvariable=self.pasta_servidor).grid(
            row=0, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(aba, text="Procurar...", command=self._escolher_pasta_servidor).grid(
            row=0, column=2, pady=4
        )

        self._adicionar_campo(aba, 1, "Nome do servidor:", self.nome_servidor)
        self._adicionar_campo(aba, 2, "Descrição:", self.descricao_servidor)
        self._adicionar_campo(
            aba, 3, "Limite de jogadores (1 a 32):", self.quantidade_jogadores
        )
        self._adicionar_campo(aba, 4, "Porta do jogo (UDP):", self.porta)
        self._adicionar_campo(
            aba, 5, "Senha para entrar (opcional):", self.senha_servidor, ocultar=True
        )
        self._adicionar_campo(
            aba,
            6,
            "Senha de administrador:",
            self.senha_administrador,
            ocultar=True,
        )

        plataformas = ttk.LabelFrame(aba, text="Plataformas permitidas", padding=8)
        plataformas.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(9, 3))
        for indice, plataforma in enumerate(PLATAFORMAS):
            ttk.Checkbutton(
                plataformas,
                text=plataforma,
                variable=self.plataformas_ativas[plataforma],
            ).grid(row=0, column=indice, padx=(0, 16), sticky="w")
        ttk.Label(
            aba,
            text=(
                "A lista é gravada na configuração do jogo; o acesso entre plataformas "
                "também depende das versões e do suporte oficial do Palworld."
            ),
            wraplength=680,
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(4, 8))
        ttk.Checkbutton(
            aba,
            text="Ativar API REST local para administração pelo app",
            variable=self.api_rest_ativada,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._adicionar_campo(
            aba, 10, "Porta da API REST:", self.porta_api_rest
        )
        ttk.Checkbutton(
            aba,
            text="Ativar RCON para integrações como Project Sphere/PalDefender",
            variable=self.rcon_ativado,
        ).grid(row=11, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._adicionar_campo(aba, 12, "Porta RCON:", self.porta_rcon)

        botoes = ttk.Frame(aba)
        botoes.grid(row=13, column=0, columnspan=3, sticky="ew", pady=8)
        self.botao_instalar_servidor = ttk.Button(
            botoes,
            text="Instalar/atualizar servidor",
            command=self._instalar_servidor,
        )
        self.botao_instalar_servidor.pack(side="left")
        ttk.Button(
            botoes, text="Salvar configuração", command=self._salvar_local
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            botoes, text="Iniciar servidor", command=self._iniciar_servidor
        ).pack(side="left", padx=8)
        self.botao_parar = ttk.Button(
            botoes, text="Parar servidor", command=self._parar_servidor, state="disabled"
        )
        self.botao_parar.pack(side="left")
        ttk.Button(
            botoes, text="Abrir pasta", command=self._abrir_pasta_servidor
        ).pack(side="right")

        rede = ttk.LabelFrame(aba, text="Conexão e acesso", padding=8)
        rede.grid(row=14, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        self.texto_enderecos = tk.Text(rede, height=6, wrap="word")
        self.texto_enderecos.pack(fill="both", expand=True)
        self.texto_enderecos.configure(state="disabled")
        ttk.Button(
            rede, text="Atualizar dados de conexão", command=self._atualizar_enderecos
        ).pack(anchor="e", pady=(6, 0))
        ttk.Label(
            aba,
            text=(
                "A API REST e o RCON são serviços administrativos: use senha forte e "
                "não encaminhe essas portas para a Internet. Para hospedagem externa, "
                "use as ferramentas do provedor ou uma conexão privada."
            ),
            wraplength=680,
            justify="left",
        ).grid(row=15, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _montar_aba_portal(self, aba: ttk.Frame) -> None:
        aba.columnconfigure(1, weight=1)
        ttk.Label(
            aba,
            text=(
                "Inicie e abra o Portal Pandora neste computador ou prepare os "
                "endereços para publicar o site em uma hospedagem."
            ),
            wraplength=700,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._adicionar_campo(
            aba, 1, "Porta do portal local:", self.portal_porta
        )
        botoes_local = ttk.Frame(aba)
        botoes_local.grid(row=2, column=0, columnspan=3, sticky="w", pady=5)
        ttk.Button(
            botoes_local, text="Iniciar e abrir site local", command=self._iniciar_portal
        ).pack(side="left")
        self.botao_parar_portal = ttk.Button(
            botoes_local,
            text="Parar site local",
            command=self._parar_portal,
            state="disabled",
        )
        self.botao_parar_portal.pack(side="left", padx=8)
        ttk.Label(aba, textvariable=self.status_portal).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(3, 10)
        )

        hospedagem = ttk.LabelFrame(
            aba, text="Vincular o site a uma hospedagem", padding=8
        )
        hospedagem.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        hospedagem.columnconfigure(1, weight=1)
        ttk.Label(hospedagem, text="Endereço público HTTPS do site:").grid(
            row=0, column=0, sticky="w", pady=4
        )
        ttk.Entry(hospedagem, textvariable=self.portal_public_url).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=4
        )
        ttk.Label(hospedagem, text="API privada do servidor Palworld:").grid(
            row=1, column=0, sticky="w", pady=4
        )
        ttk.Entry(hospedagem, textvariable=self.portal_api_url).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=4
        )
        ttk.Button(
            hospedagem,
            text="Exportar configuração para o host...",
            command=self._exportar_configuracao_portal,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 4))
        ttk.Label(
            hospedagem,
            text=(
                "O arquivo exportado contém somente endereços, nunca senhas ou tokens. "
                "Cadastre os segredos no provedor. Para ligar o portal hospedado ao "
                "jogo, use uma VPN/rede privada; não exponha REST/RCON publicamente. "
                "A hospedagem precisa aceitar Python/Docker e armazenamento persistente."
            ),
            wraplength=690,
            justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _montar_aba_externa(self, aba: ttk.Frame) -> None:
        aba.columnconfigure(0, weight=1)
        instrucoes = (
            "Para usar outra hospedagem, gere o arquivo PalWorldSettings.ini e envie-o "
            "pelo painel ou pelo método indicado pelo provedor.\n\n"
            "O arquivo contém o nome, o limite de jogadores, a porta, as plataformas e "
            "as senhas definidas na aba Meu PC. Trate-o como confidencial.\n\n"
            "Dados para cadastrar no provedor:\n"
            f"• Porta do jogo: {PORTA_PADRAO}/UDP (ou a porta escolhida)\n"
            "• Jogadores: limite escolhido na aba Meu PC\n"
            "• Arquivo de configuração: PalWorldSettings.ini\n\n"
            "A instalação de servidor oferecida pelo provedor pode exigir outros campos. "
            "Confirme com o suporte da hospedagem o caminho esperado para o arquivo e "
            "se ela aceita servidores dedicados de Palworld."
        )
        ttk.Label(aba, text=instrucoes, wraplength=700, justify="left").grid(
            row=0, column=0, sticky="nw", pady=(0, 16)
        )
        ttk.Button(
            aba,
            text="Exportar PalWorldSettings.ini...",
            command=self._exportar_configuracao,
        ).grid(row=1, column=0, sticky="w")

    def _montar_aba_eventos(self, aba: ttk.Frame) -> None:
        aba.columnconfigure(0, weight=1)
        aba.rowconfigure(1, weight=1)
        ttk.Label(
            aba,
            text=(
                "Cadastre invasões, chefes e outros eventos, escolha a recorrência "
                "e defina o prêmio para os participantes."
            ),
            wraplength=700,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        tabela = ttk.Treeview(
            aba,
            columns=("tipo", "frequencia", "inicio", "premio", "estado"),
            show="headings",
            selectmode="browse",
            height=12,
        )
        self.tabela_eventos = tabela
        for coluna, titulo, largura in (
            ("tipo", "Tipo", 130),
            ("frequencia", "Recorrência", 105),
            ("inicio", "Próximo início", 145),
            ("premio", "Prêmio por participante", 230),
            ("estado", "Estado", 95),
        ):
            tabela.heading(coluna, text=titulo)
            tabela.column(coluna, width=largura, anchor="w")
        tabela.grid(row=1, column=0, sticky="nsew")
        barra = ttk.Scrollbar(aba, orient="vertical", command=tabela.yview)
        barra.grid(row=1, column=1, sticky="ns")
        tabela.configure(yscrollcommand=barra.set)

        botoes = ttk.Frame(aba)
        botoes.grid(row=2, column=0, sticky="ew", pady=(10, 8))
        self.botoes_eventos: list[ttk.Button] = []
        for texto, comando in (
            ("Adicionar evento", self._adicionar_evento),
            ("Editar", self._editar_evento),
            ("Ativar/Pausar", self._alternar_evento),
            ("Remover", self._remover_evento),
        ):
            botao = ttk.Button(botoes, text=texto, command=comando)
            botao.pack(side="left", padx=(0, 6))
            self.botoes_eventos.append(botao)
        if not self._agenda_disponivel:
            for botao in self.botoes_eventos:
                botao.configure(state="disabled")

        ttk.Label(
            aba,
            text=(
                "O configurador precisa permanecer aberto para mostrar os avisos. "
                "A invocação do Pal/boss e a entrega do prêmio a cada participante "
                "são manuais pelo Creative Menu (F1); o mod precisa estar instalado "
                "no servidor e no cliente, com permissão de administrador."
            ),
            wraplength=700,
            justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(4, 0))

    def _montar_aba_administracao(self, aba: ttk.Frame) -> None:
        tela = tk.Canvas(aba, highlightthickness=0)
        rolagem = ttk.Scrollbar(aba, orient="vertical", command=tela.yview)
        tela.configure(yscrollcommand=rolagem.set)
        tela.grid(row=0, column=0, sticky="nsew")
        rolagem.grid(row=0, column=1, sticky="ns")
        aba.rowconfigure(0, weight=1)
        aba.columnconfigure(0, weight=1)
        conteudo = ttk.Frame(tela, padding=(0, 0, 8, 8))
        id_janela = tela.create_window((0, 0), window=conteudo, anchor="nw")
        conteudo.bind(
            "<Configure>",
            lambda _evento: tela.configure(scrollregion=tela.bbox("all")),
        )
        tela.bind(
            "<Configure>",
            lambda evento: tela.itemconfigure(id_janela, width=evento.width),
        )
        aba = conteudo
        aba.columnconfigure(0, weight=1)
        aba.rowconfigure(2, weight=1)
        painel = ttk.LabelFrame(aba, text="Administração direta (rede local)", padding=8)
        painel.grid(row=0, column=0, sticky="ew")
        painel.columnconfigure(1, weight=1)
        ttk.Label(painel, text="Endereço base:").grid(
            row=0, column=0, sticky="w", pady=3
        )
        ttk.Entry(painel, textvariable=self.endereco_api).grid(
            row=0, column=1, sticky="ew", padx=6, pady=3
        )
        ttk.Label(painel, text="Porta REST:").grid(
            row=0, column=2, sticky="w", padx=(8, 0), pady=3
        )
        ttk.Entry(painel, textvariable=self.porta_api_rest, width=8).grid(
            row=0, column=3, sticky="w", padx=(6, 0), pady=3
        )
        ttk.Button(painel, text="Conectar / atualizar", command=self._atualizar_jogadores).grid(
            row=0, column=4, padx=(8, 0), pady=3
        )
        ttk.Label(
            painel,
            text=(
                "A senha de administrador informada na aba Meu PC é usada na autenticação. "
                "A API REST usa HTTP Basic: prefira localhost ou uma rede privada confiável. "
                "Por segurança, o app rejeita endereços públicos."
            ),
            wraplength=690,
            justify="left",
        ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 6))
        ttk.Label(painel, textvariable=self.status_api).grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(0, 4)
        )

        jogadores_frame = ttk.LabelFrame(aba, text="Jogadores online", padding=8)
        jogadores_frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        jogadores_frame.columnconfigure(0, weight=1)
        jogadores_frame.rowconfigure(0, weight=1)
        self.tabela_jogadores = ttk.Treeview(
            jogadores_frame,
            columns=("nome", "nivel", "user_id"),
            show="headings",
            selectmode="browse",
            height=7,
        )
        for coluna, titulo, largura in (
            ("nome", "Jogador", 210),
            ("nivel", "Nível", 70),
            ("user_id", "ID do jogador (UserID)", 300),
        ):
            self.tabela_jogadores.heading(coluna, text=titulo)
            self.tabela_jogadores.column(coluna, width=largura, anchor="w")
        self.tabela_jogadores.grid(row=0, column=0, sticky="nsew")
        barra = ttk.Scrollbar(
            jogadores_frame, orient="vertical", command=self.tabela_jogadores.yview
        )
        barra.grid(row=0, column=1, sticky="ns")
        self.tabela_jogadores.configure(yscrollcommand=barra.set)
        self.tabela_jogadores.bind(
            "<<TreeviewSelect>>", self._selecionar_jogador_admin
        )

        acoes = ttk.LabelFrame(aba, text="Ações administrativas", padding=8)
        acoes.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        acoes.columnconfigure(1, weight=1)
        ttk.Label(acoes, text="ID do jogador:").grid(
            row=0, column=0, sticky="w", pady=3
        )
        ttk.Entry(acoes, textvariable=self.alvo_admin).grid(
            row=0, column=1, sticky="ew", padx=6, pady=3
        )
        ttk.Label(acoes, text="Aviso/motivo:").grid(
            row=1, column=0, sticky="w", pady=3
        )
        ttk.Entry(acoes, textvariable=self.mensagem_admin).grid(
            row=1, column=1, sticky="ew", padx=6, pady=3
        )
        botoes = ttk.Frame(acoes)
        botoes.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(botoes, text="Anunciar", command=self._anunciar).pack(
            side="left", padx=(0, 5)
        )
        ttk.Button(botoes, text="Expulsar", command=self._expulsar_jogador).pack(
            side="left", padx=5
        )
        ttk.Button(botoes, text="Banir", command=self._banir_jogador).pack(
            side="left", padx=5
        )
        ttk.Button(botoes, text="Desbanir ID", command=self._desbanir_jogador).pack(
            side="left", padx=5
        )
        ttk.Button(botoes, text="Salvar mundo", command=self._salvar_mundo).pack(
            side="left", padx=5
        )
        ttk.Button(
            botoes, text="Desligar em 60 s", command=self._desligar_servidor
        ).pack(side="left", padx=5)

        integracoes = ttk.LabelFrame(
            aba, text="Integrações e configuração guiada", padding=8
        )
        integracoes.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(
            integracoes,
            text=(
                "Project Sphere (sucessor comunitário do PalBot): bot self-hosted para "
                "Discord; exige criar um aplicativo/bot no Discord Developer Portal e "
                "rodar o projeto numa máquina sempre ligada."
            ),
            wraplength=690,
            justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        botoes_sphere = ttk.Frame(integracoes)
        botoes_sphere.grid(row=1, column=0, columnspan=4, sticky="w", pady=4)
        ttk.Button(
            botoes_sphere,
            text="Abrir versões do Project Sphere",
            command=lambda: webbrowser.open(URL_SPHERE_RELEASES),
        ).pack(side="left", padx=(0, 5))
        ttk.Button(
            botoes_sphere,
            text="Abrir Discord Developer Portal",
            command=lambda: webbrowser.open(URL_DISCORD_DEVELOPER),
        ).pack(side="left", padx=5)
        ttk.Label(integracoes, text="Application ID para convite:").grid(
            row=2, column=0, sticky="w", pady=3
        )
        ttk.Entry(integracoes, textvariable=self.sphere_app_id, width=26).grid(
            row=2, column=1, sticky="w", padx=6, pady=3
        )
        ttk.Button(
            integracoes,
            text="Abrir convite do bot no Discord",
            command=self._abrir_convite_sphere,
        ).grid(row=2, column=2, sticky="w", padx=4, pady=3)
        ttk.Label(
            integracoes,
            text=(
                "O convite não concede permissões automaticamente; revise as permissões "
                "solicitadas no Discord. Este app não cria o bot nem pode obter o token "
                "por você."
            ),
            wraplength=690,
            justify="left",
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 5))
        ttk.Label(integracoes, text="Pasta local do Project Sphere:").grid(
            row=4, column=0, sticky="w", pady=3
        )
        ttk.Entry(integracoes, textvariable=self.pasta_sphere).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=6, pady=3
        )
        ttk.Button(
            integracoes,
            text="Procurar...",
            command=self._escolher_pasta_sphere,
        ).grid(row=4, column=3, sticky="w", pady=3)
        ttk.Label(integracoes, text="Token do bot:").grid(
            row=5, column=0, sticky="w", pady=3
        )
        ttk.Entry(integracoes, textvariable=self.sphere_token, show="*").grid(
            row=5, column=1, sticky="ew", padx=6, pady=3
        )
        ttk.Label(integracoes, text="Prefixo:").grid(
            row=5, column=2, sticky="e", padx=6, pady=3
        )
        ttk.Entry(integracoes, textvariable=self.sphere_prefixo, width=8).grid(
            row=5, column=3, sticky="w", pady=3
        )
        ttk.Button(
            integracoes,
            text="Gerar arquivo .env do bot",
            command=self._salvar_configuracao_sphere,
        ).grid(row=6, column=0, sticky="w", pady=(5, 3))
        botoes_bot = ttk.Frame(integracoes)
        botoes_bot.grid(row=6, column=1, columnspan=3, sticky="w", pady=(5, 3))
        self.botao_iniciar_sphere = ttk.Button(
            botoes_bot, text="Iniciar bot", command=self._iniciar_sphere
        )
        self.botao_iniciar_sphere.pack(side="left", padx=(0, 5))
        self.botao_parar_sphere = ttk.Button(
            botoes_bot,
            text="Parar bot",
            command=self._parar_sphere,
            state="disabled",
        )
        self.botao_parar_sphere.pack(side="left", padx=5)
        self.status_sphere = tk.StringVar(value="Bot do Discord parado.")
        ttk.Label(
            integracoes,
            text=(
                "A configuração salva o token em texto no arquivo .env da pasta escolhida. "
                "Mantenha essa pasta privada e não compartilhe o arquivo."
            ),
            wraplength=690,
            justify="left",
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Label(integracoes, textvariable=self.status_sphere).grid(
            row=8, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )

        paldefender = ttk.LabelFrame(
            aba, text="PalDefender (proteção e comandos via RCON)", padding=8
        )
        paldefender.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(
            paldefender,
            text=(
                "O PalDefender é um plugin comunitário para servidor dedicado Windows. "
                "O Project Sphere oferece algumas ações PalDefender pelo Discord. "
                "A instalação do plugin é feita separadamente; hospedagens externas "
                "precisam aceitar plugins nativos e permitir o acesso necessário."
            ),
            wraplength=690,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(
            paldefender,
            text="Abrir PalDefender oficial",
            command=lambda: webbrowser.open(URL_PALDEFENDER),
        ).grid(row=1, column=0, sticky="w", pady=(5, 0), padx=(0, 5))
        ttk.Button(
            paldefender,
            text="Abrir guia de instalação",
            command=lambda: webbrowser.open(URL_PALDEFENDER_GUIA),
        ).grid(row=1, column=1, sticky="w", pady=(5, 0), padx=5)

    def _salvar_eventos(self, eventos: list[dict[str, object]]) -> bool:
        try:
            salvar_eventos(self.caminho_eventos, eventos)
        except (OSError, ValueError) as erro:
            messagebox.showerror("Não foi possível salvar a agenda", str(erro))
            return False
        self.eventos = eventos
        self._atualizar_lista_eventos()
        return True

    def _atualizar_lista_eventos(self) -> None:
        if not hasattr(self, "tabela_eventos"):
            return
        for identificador in self.tabela_eventos.get_children():
            self.tabela_eventos.delete(identificador)
        for evento in self.eventos:
            estado = "Ativo" if evento["ativo"] else "Pausado/concluído"
            self.tabela_eventos.insert(
                "",
                "end",
                iid=evento["id"],
                values=(
                    evento["tipo"],
                    evento["frequencia"],
                    formatar_proxima_execucao(evento),
                    evento["premio"],
                    estado,
                ),
            )

    def _evento_selecionado(self) -> dict[str, object] | None:
        selecionados = self.tabela_eventos.selection()
        if not selecionados:
            messagebox.showinfo("Selecione um evento", "Selecione um evento na lista.")
            return None
        identificador = selecionados[0]
        return next(
            (evento for evento in self.eventos if evento["id"] == identificador),
            None,
        )

    def _adicionar_evento(self) -> None:
        self._abrir_editor_evento()

    def _editar_evento(self) -> None:
        evento = self._evento_selecionado()
        if evento is not None:
            self._abrir_editor_evento(evento)

    def _abrir_editor_evento(self, evento: dict[str, object] | None = None) -> None:
        agora = (datetime.now() + timedelta(minutes=5)).replace(second=0, microsecond=0)
        valores = evento or {
            "nome": "",
            "tipo": TIPOS_EVENTO[0],
            "inicio": agora.strftime("%Y-%m-%d %H:%M"),
            "frequencia": FREQUENCIAS[0],
            "premio": "",
            "ativo": True,
        }
        janela = tk.Toplevel(self.janela)
        janela.title("Editar evento" if evento else "Novo evento")
        janela.transient(self.janela)
        janela.grab_set()
        janela.columnconfigure(1, weight=1)

        nome = tk.StringVar(value=str(valores["nome"]))
        tipo = tk.StringVar(value=str(valores["tipo"]))
        inicio = tk.StringVar(value=str(valores["inicio"]))
        frequencia = tk.StringVar(value=str(valores["frequencia"]))
        premio = tk.StringVar(value=str(valores["premio"]))
        ativo = tk.BooleanVar(value=bool(valores["ativo"]))

        ttk.Label(janela, text="Nome do evento:").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4)
        )
        ttk.Entry(janela, textvariable=nome, width=42).grid(
            row=0, column=1, sticky="ew", padx=(8, 12), pady=(12, 4)
        )
        ttk.Label(janela, text="Tipo:").grid(
            row=1, column=0, sticky="w", padx=12, pady=4
        )
        ttk.Combobox(
            janela, textvariable=tipo, values=TIPOS_EVENTO, state="readonly"
        ).grid(row=1, column=1, sticky="ew", padx=(8, 12), pady=4)
        ttk.Label(janela, text="Início (AAAA-MM-DD HH:MM):").grid(
            row=2, column=0, sticky="w", padx=12, pady=4
        )
        ttk.Entry(janela, textvariable=inicio).grid(
            row=2, column=1, sticky="ew", padx=(8, 12), pady=4
        )
        ttk.Label(janela, text="Recorrência:").grid(
            row=3, column=0, sticky="w", padx=12, pady=4
        )
        ttk.Combobox(
            janela, textvariable=frequencia, values=FREQUENCIAS, state="readonly"
        ).grid(row=3, column=1, sticky="ew", padx=(8, 12), pady=4)
        ttk.Label(janela, text="Prêmio por participante:").grid(
            row=4, column=0, sticky="w", padx=12, pady=4
        )
        ttk.Entry(janela, textvariable=premio).grid(
            row=4, column=1, sticky="ew", padx=(8, 12), pady=4
        )
        ttk.Checkbutton(janela, text="Evento ativo", variable=ativo).grid(
            row=5, column=1, sticky="w", padx=(8, 12), pady=4
        )

        def salvar() -> None:
            try:
                atualizado = criar_evento(
                    nome=nome.get(),
                    tipo=tipo.get(),
                    inicio=inicio.get(),
                    frequencia=frequencia.get(),
                    premio=premio.get(),
                    ativo=ativo.get(),
                    identificador=str(evento["id"]) if evento else None,
                )
            except ValueError as erro:
                messagebox.showerror("Dados inválidos", str(erro), parent=janela)
                return
            eventos = [
                atualizado if existente["id"] == atualizado["id"] else existente
                for existente in self.eventos
            ]
            if evento is None:
                eventos.append(atualizado)
            if self._salvar_eventos(eventos):
                janela.destroy()

        botoes = ttk.Frame(janela)
        botoes.grid(row=6, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        ttk.Button(botoes, text="Cancelar", command=janela.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(botoes, text="Salvar", command=salvar).pack(side="right")

    def _alternar_evento(self) -> None:
        evento = self._evento_selecionado()
        if evento is None:
            return
        eventos = [
            {**existente, "ativo": not bool(existente["ativo"])}
            if existente["id"] == evento["id"]
            else existente
            for existente in self.eventos
        ]
        self._salvar_eventos(eventos)

    def _remover_evento(self) -> None:
        evento = self._evento_selecionado()
        if evento is None or not messagebox.askyesno(
            "Remover evento",
            f"Deseja remover o evento “{evento['nome']}”?",
        ):
            return
        self._salvar_eventos(
            [existente for existente in self.eventos if existente["id"] != evento["id"]]
        )

    def _verificar_agenda(self) -> None:
        eventos_atualizados, iniciados = processar_agenda(
            self.eventos, datetime.now()
        )
        if eventos_atualizados != self.eventos:
            if not self._salvar_eventos(eventos_atualizados):
                self.janela.after(10_000, self._verificar_agenda)
                return
        for evento in iniciados:
            messagebox.showinfo(
                f"Evento Palworld: {evento['nome']}",
                f"O evento “{evento['nome']}” começou.\n\n"
                f"Tipo: {evento['tipo']}\n"
                f"Prêmio planejado para cada participante: {evento['premio']}\n\n"
                "No jogo, use o Creative Menu (F1) para iniciar o evento e, "
                "ao final, entregar manualmente o prêmio a cada participante.",
            )
        self.janela.after(10_000, self._verificar_agenda)

    def _obter_cliente_api(self) -> ClienteRESTPalworld:
        if not self.api_rest_ativada.get():
            raise ValueError(
                "Ative a API REST na aba Meu PC, salve a configuração e reinicie o servidor."
            )
        try:
            porta = int(self.porta_api_rest.get())
        except ValueError as erro:
            raise ValueError("A porta da API REST precisa ser um número inteiro.") from erro
        endereco = f"{self.endereco_api.get().strip().rstrip('/')}:{porta}"
        return ClienteRESTPalworld(endereco, self.senha_administrador.get())

    def _executar_acao_api(self, acao, mensagem_sucesso: str) -> None:
        try:
            resultado = acao(self._obter_cliente_api())
        except (ErroAPIPalworld, OSError, ValueError) as erro:
            self.status_api.set(f"Falha: {erro}")
            messagebox.showerror("Administração do servidor", str(erro))
            return
        detalhe = f" Resposta: {resultado}" if resultado not in (None, "", {}) else ""
        self.status_api.set(mensagem_sucesso + detalhe)

    def _atualizar_jogadores(self) -> None:
        try:
            cliente = self._obter_cliente_api()
            informacoes = cliente.informacoes_servidor()
            jogadores = cliente.listar_jogadores()
        except (ErroAPIPalworld, OSError, ValueError) as erro:
            self.status_api.set(f"Falha ao conectar: {erro}")
            messagebox.showerror("API REST do Palworld", str(erro))
            return
        for identificador in self.tabela_jogadores.get_children():
            self.tabela_jogadores.delete(identificador)
        for indice, jogador in enumerate(jogadores):
            user_id = str(jogador.get("userId", ""))
            nome = str(jogador.get("name", jogador.get("accountName", "Sem nome")))
            nivel = str(jogador.get("level", ""))
            iid = user_id or f"jogador-{indice}"
            self.tabela_jogadores.insert(
                "", "end", iid=iid, values=(nome, nivel, user_id)
            )
        if isinstance(informacoes, dict):
            nome_servidor = informacoes.get("servername", "Servidor")
            versao = informacoes.get("version", "")
            self.status_api.set(
                f"Conectado: {nome_servidor} {versao} — {len(jogadores)} jogador(es) online."
            )
        else:
            self.status_api.set(
                f"Conectado à API — {len(jogadores)} jogador(es) online."
            )

    def _selecionar_jogador_admin(self, _evento=None) -> None:
        selecao = self.tabela_jogadores.selection()
        if selecao:
            valores = self.tabela_jogadores.item(selecao[0], "values")
            if len(valores) >= 3 and valores[2]:
                self.alvo_admin.set(str(valores[2]))

    def _anunciar(self) -> None:
        mensagem = self.mensagem_admin.get().strip()
        if not mensagem:
            messagebox.showerror("Mensagem vazia", "Escreva o aviso que será enviado.")
            return
        self._executar_acao_api(
            lambda cliente: cliente.anunciar(mensagem), "Aviso enviado."
        )

    def _obter_user_id_admin(self) -> str | None:
        user_id = self.alvo_admin.get().strip()
        if not user_id:
            messagebox.showerror(
                "ID do jogador necessário",
                "Selecione um jogador online ou informe o UserID.",
            )
            return None
        if "\n" in user_id or "\r" in user_id:
            messagebox.showerror("ID inválido", "O UserID informado é inválido.")
            return None
        return user_id

    def _expulsar_jogador(self) -> None:
        user_id = self._obter_user_id_admin()
        if user_id is None or not messagebox.askyesno(
            "Expulsar jogador", f"Deseja expulsar o jogador {user_id}?"
        ):
            return
        motivo = self.mensagem_admin.get().strip()
        self._executar_acao_api(
            lambda cliente: cliente.expulsar(user_id, motivo),
            f"Pedido de expulsão enviado para {user_id}.",
        )

    def _banir_jogador(self) -> None:
        user_id = self._obter_user_id_admin()
        if user_id is None or not messagebox.askyesno(
            "Banir jogador",
            f"Deseja banir {user_id}? Essa ação impede que entre novamente.",
        ):
            return
        motivo = self.mensagem_admin.get().strip()
        self._executar_acao_api(
            lambda cliente: cliente.banir(user_id, motivo),
            f"Pedido de banimento enviado para {user_id}.",
        )

    def _desbanir_jogador(self) -> None:
        user_id = self._obter_user_id_admin()
        if user_id is None or not messagebox.askyesno(
            "Desbanir jogador", f"Deseja remover o banimento de {user_id}?"
        ):
            return
        self._executar_acao_api(
            lambda cliente: cliente.desbanir(user_id),
            f"Pedido de desbanimento enviado para {user_id}.",
        )

    def _salvar_mundo(self) -> None:
        self._executar_acao_api(
            lambda cliente: cliente.salvar_mundo(),
            "Pedido de gravação do mundo enviado.",
        )

    def _desligar_servidor(self) -> None:
        if not messagebox.askyesno(
            "Desligar servidor",
            "O servidor anunciará o desligamento e será encerrado em 60 segundos. "
            "Deseja continuar?",
        ):
            return
        mensagem = self.mensagem_admin.get().strip() or "Servidor encerrando em 60 segundos."
        self._executar_acao_api(
            lambda cliente: cliente.agendar_desligamento(60, mensagem),
            "Desligamento agendado para daqui a 60 segundos.",
        )

    def _escolher_pasta_sphere(self) -> None:
        pasta = filedialog.askdirectory(
            title="Selecione a pasta do Project Sphere"
        )
        if pasta:
            self.pasta_sphere.set(pasta)

    def _salvar_configuracao_sphere(self) -> None:
        pasta = Path(self.pasta_sphere.get()).expanduser()
        if not (pasta / "main.py").is_file():
            messagebox.showerror(
                "Project Sphere não encontrado",
                "Selecione a pasta extraída do Project Sphere que contém main.py.",
            )
            return
        token = self.sphere_token.get()
        prefixo = self.sphere_prefixo.get()
        if not token.strip() or any(caractere in token for caractere in "\r\n"):
            messagebox.showerror("Token inválido", "Informe o token do bot do Discord.")
            return
        if not prefixo or any(caractere in prefixo for caractere in "\r\n"):
            messagebox.showerror("Prefixo inválido", "Informe um prefixo sem quebras de linha.")
            return
        if not messagebox.askyesno(
            "Salvar token do Discord",
            "O token será gravado em texto no arquivo .env da pasta do Project Sphere. "
            "Não compartilhe esse arquivo nem o envie ao GitHub. Deseja continuar?",
        ):
            return
        destino = pasta / ".env"
        try:
            linhas_existentes = (
                destino.read_text(encoding="utf-8").splitlines()
                if destino.is_file()
                else []
            )
            linhas = [
                linha
                for linha in linhas_existentes
                if not linha.startswith(("BOT_TOKEN=", "BOT_PREFIX="))
            ]
            linhas.extend((f"BOT_TOKEN={token.strip()}", f"BOT_PREFIX={prefixo}"))
            conteudo = "\n".join(linhas) + "\n"
            backup = gravar_configuracao_segura(destino, conteudo)
        except (OSError, UnicodeError) as erro:
            messagebox.showerror("Falha ao salvar .env", str(erro))
            return
        aviso = f"Configuração salva em {destino}."
        if backup:
            aviso += f"\nCópia anterior: {backup.name}"
        aviso += (
            "\n\nInstale as dependências indicadas pelo Project Sphere antes de iniciar "
            "o bot. Não publique o arquivo .env."
        )
        messagebox.showinfo("Project Sphere configurado", aviso)

    def _iniciar_sphere(self) -> None:
        if (
            self._processo_sphere is not None
            and self._processo_sphere.poll() is None
        ):
            messagebox.showinfo("Project Sphere", "O bot já está em execução.")
            return
        if sys.version_info < (3, 11):
            messagebox.showerror(
                "Python incompatível",
                "O Project Sphere requer Python 3.11 ou superior. "
                "Instale essa versão e abra o configurador com ela.",
            )
            return
        pasta = Path(self.pasta_sphere.get()).expanduser()
        if not (pasta / "main.py").is_file() or not (pasta / ".env").is_file():
            messagebox.showerror(
                "Project Sphere não configurado",
                "Selecione uma pasta válida, gere o arquivo .env e instale as "
                "dependências do projeto antes de iniciar o bot.",
            )
            return
        try:
            log_path = pasta / "ConfiguradorPalworld-Sphere.log"
            self._arquivo_log_sphere = log_path.open("ab")
            opcoes = {
                "cwd": pasta,
                "stdout": self._arquivo_log_sphere,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            self._processo_sphere = subprocess.Popen(
                [sys.executable, "-u", "main.py"], **opcoes
            )
        except OSError as erro:
            if self._arquivo_log_sphere:
                self._arquivo_log_sphere.close()
                self._arquivo_log_sphere = None
            messagebox.showerror("Falha ao iniciar Project Sphere", str(erro))
            return
        self.status_sphere.set(
            f"Inicializando bot. Registro: {pasta / 'ConfiguradorPalworld-Sphere.log'}"
        )
        self.botao_iniciar_sphere.configure(state="disabled")
        self.botao_parar_sphere.configure(state="normal")
        self.janela.after(2000, self._verificar_sphere)

    def _verificar_sphere(self) -> None:
        processo = self._processo_sphere
        if processo is None:
            return
        codigo_saida = processo.poll()
        if codigo_saida is None:
            self.status_sphere.set("Bot do Discord em execução.")
            self.janela.after(5000, self._verificar_sphere)
            return
        self.status_sphere.set(
            f"O bot encerrou com código {codigo_saida}. Consulte o arquivo de registro."
        )
        self._finalizar_sphere()

    def _parar_sphere(self) -> None:
        processo = self._processo_sphere
        if processo is None or processo.poll() is not None:
            self._finalizar_sphere()
            return
        if not messagebox.askyesno(
            "Parar Project Sphere", "Deseja enviar o sinal de encerramento ao bot?"
        ):
            return
        try:
            if os.name == "nt":
                processo.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                processo.send_signal(signal.SIGINT)
        except OSError as erro:
            messagebox.showerror("Não foi possível parar o bot", str(erro))
            return
        self.status_sphere.set("Solicitando encerramento do bot...")
        self.janela.after(1000, self._aguardar_sphere, processo)

    def _aguardar_sphere(self, processo: subprocess.Popen[bytes]) -> None:
        if processo.poll() is None:
            self.janela.after(1000, self._aguardar_sphere, processo)
            return
        self._finalizar_sphere()
        self.status_sphere.set("Bot do Discord parado.")

    def _finalizar_sphere(self) -> None:
        self._processo_sphere = None
        self.botao_iniciar_sphere.configure(state="normal")
        self.botao_parar_sphere.configure(state="disabled")
        if self._arquivo_log_sphere:
            self._arquivo_log_sphere.close()
            self._arquivo_log_sphere = None

    def _abrir_convite_sphere(self) -> None:
        application_id = self.sphere_app_id.get().strip()
        if not application_id.isdigit():
            messagebox.showerror(
                "Application ID inválido",
                "Crie a aplicação do seu bot no Discord Developer Portal e informe o Application ID.",
            )
            return
        url = (
            "https://discord.com/oauth2/authorize?"
            f"client_id={quote(application_id)}"
            "&scope=bot%20applications.commands&permissions=0"
        )
        webbrowser.open(url)

    def _adicionar_campo(
        self,
        aba: ttk.Frame,
        linha: int,
        rotulo: str,
        variavel: tk.StringVar,
        *,
        ocultar: bool = False,
    ) -> None:
        ttk.Label(aba, text=rotulo).grid(row=linha, column=0, sticky="w", pady=4)
        ttk.Entry(
            aba,
            textvariable=variavel,
            show="*" if ocultar else "",
        ).grid(row=linha, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=4)

    def _escolher_pasta_servidor(self) -> None:
        pasta = filedialog.askdirectory(title="Selecione a pasta do servidor Palworld")
        if pasta:
            self.pasta_servidor.set(pasta)

    def _instalar_servidor(self) -> None:
        if self._instalacao_em_andamento:
            return
        pasta = Path(self.pasta_servidor.get()).expanduser()
        if not messagebox.askyesno(
            "Instalar servidor Palworld",
            "O aplicativo baixará o SteamCMD oficial da Valve e vários GB do "
            "servidor dedicado Palworld.\n\n"
            f"Pasta de instalação:\n{pasta}\n\n"
            "Se já houver uma instalação, faça uma cópia dos arquivos de mundo "
            "antes de atualizar. Deseja continuar?",
        ):
            return

        self._instalacao_em_andamento = True
        self.botao_instalar_servidor.configure(state="disabled")
        self.status.set("Preparando a instalação...")
        threading.Thread(
            target=self._executar_instalacao_servidor,
            args=(pasta,),
            daemon=True,
        ).start()
        self.janela.after(200, self._verificar_fila_instalacao)

    def _executar_instalacao_servidor(self, pasta: Path) -> None:
        try:
            verificar_espaco_destino(pasta)
            steamcmd = preparar_steamcmd(
                CAMINHO_STEAMCMD,
                lambda mensagem: self._fila_instalacao.put(("mensagem", mensagem)),
            )
            instalar_servidor_palworld(
                steamcmd,
                pasta,
                lambda mensagem: self._fila_instalacao.put(("mensagem", mensagem)),
            )
        except Exception as erro:
            self._fila_instalacao.put(("erro", str(erro)))
        else:
            self._fila_instalacao.put(("concluido", str(pasta)))

    def _verificar_fila_instalacao(self) -> None:
        try:
            while True:
                tipo, mensagem = self._fila_instalacao.get_nowait()
                if tipo == "mensagem":
                    self.status.set(f"Instalação: {mensagem}")
                else:
                    self._instalacao_em_andamento = False
                    self.botao_instalar_servidor.configure(state="normal")
                    if tipo == "concluido":
                        self.pasta_servidor.set(mensagem)
                        self.status.set(f"Servidor instalado em {mensagem}")
                        messagebox.showinfo(
                            "Instalação concluída",
                            "O servidor dedicado foi instalado/atualizado. "
                            "Configure suas opções e use “Iniciar servidor”.",
                        )
                    else:
                        self.status.set("Falha na instalação do servidor.")
                        messagebox.showerror(
                            "Falha na instalação", mensagem or "Erro não identificado."
                        )
        except queue.Empty:
            pass
        if self._instalacao_em_andamento:
            self.janela.after(200, self._verificar_fila_instalacao)

    def _obter_valores(self) -> tuple[str, str, int, int, str, str, list[str]]:
        try:
            jogadores = int(self.quantidade_jogadores.get())
            porta = int(self.porta.get())
        except ValueError as erro:
            raise ValueError("O limite de jogadores e a porta precisam ser números inteiros.") from erro
        plataformas = [
            plataforma
            for plataforma in PLATAFORMAS
            if self.plataformas_ativas[plataforma].get()
        ]
        nome = self.nome_servidor.get().strip()
        validar_configuracao(nome, jogadores, porta, plataformas)
        return (
            nome,
            self.descricao_servidor.get(),
            jogadores,
            porta,
            self.senha_servidor.get(),
            self.senha_administrador.get(),
            plataformas,
        )

    def _modelo_e_base(self, pasta: Path) -> tuple[str, Path]:
        modelo_path = pasta / NOME_MODELO
        config_path = pasta / CAMINHO_CONFIGURACAO
        origem = config_path if config_path.is_file() and config_path.stat().st_size else modelo_path
        if not origem.is_file():
            raise FileNotFoundError(
                f"Não encontrei {NOME_MODELO} nem uma configuração existente em {pasta}."
            )
        return origem.read_text(encoding="utf-8-sig"), config_path

    def _criar_configuracao(self, pasta: Path) -> tuple[str, Path, int]:
        nome, descricao, jogadores, porta, senha, admin, plataformas = self._obter_valores()
        try:
            porta_api_rest = int(self.porta_api_rest.get())
            porta_rcon = int(self.porta_rcon.get())
        except ValueError as erro:
            raise ValueError(
                "As portas da API REST e do RCON precisam ser números inteiros."
            ) from erro
        modelo, destino = self._modelo_e_base(pasta)
        conteudo = gerar_pal_world_settings(
            modelo,
            nome=nome,
            descricao=descricao,
            quantidade_jogadores=jogadores,
            porta=porta,
            senha_servidor=senha,
            senha_administrador=admin,
            plataformas=plataformas,
            api_rest_ativada=self.api_rest_ativada.get(),
            porta_api_rest=porta_api_rest,
            rcon_ativado=self.rcon_ativado.get(),
            porta_rcon=porta_rcon,
        )
        return conteudo, destino, porta

    def _salvar_local(self) -> bool:
        pasta = Path(self.pasta_servidor.get()).expanduser()
        if not (pasta / "PalServer.exe").is_file():
            messagebox.showerror(
                "Servidor não encontrado",
                "Selecione a pasta que contém o arquivo PalServer.exe.",
            )
            return False
        try:
            conteudo, destino, _ = self._criar_configuracao(pasta)
            backup = gravar_configuracao_segura(destino, conteudo)
        except (OSError, ValueError) as erro:
            messagebox.showerror("Não foi possível salvar", str(erro))
            return False
        self.status.set(f"Configuração salva em {destino}")
        if backup:
            self.status.set(f"Configuração salva. Cópia anterior: {backup.name}")
        return True

    def _iniciar_portal(self) -> None:
        processo = self._processo_portal
        if processo is not None and processo.poll() is None:
            messagebox.showinfo("Portal Pandora", "O portal já está em execução.")
            return
        try:
            porta = int(self.portal_porta.get())
        except ValueError:
            messagebox.showerror("Porta inválida", "Informe uma porta entre 1 e 65535.")
            return
        if not 1 <= porta <= 65535:
            messagebox.showerror("Porta inválida", "Informe uma porta entre 1 e 65535.")
            return

        endereco_api = ""
        if self.api_rest_ativada.get():
            endereco_api = self.portal_api_url.get().strip() or (
                f"http://127.0.0.1:{self.porta_api_rest.get().strip()}"
            )
            try:
                ClienteRESTPalworld(endereco_api, self.senha_administrador.get())
            except ValueError as erro:
                messagebox.showerror("Conexão privada inválida", str(erro))
                return

        raiz_projeto = Path(__file__).resolve().parent
        script_portal = raiz_projeto / "portal_palworld.py"
        if not script_portal.is_file():
            messagebox.showerror(
                "Portal não encontrado", f"Não encontrei o arquivo:\n{script_portal}"
            )
            return
        try:
            PASTA_DADOS_APP.mkdir(parents=True, exist_ok=True)
            self._arquivo_log_portal = (PASTA_DADOS_APP / "PortalPandora.log").open("ab")
            ambiente = os.environ.copy()
            ambiente.update(
                {
                    "PORTAL_HOST": "127.0.0.1",
                    "PORTAL_PORT": str(porta),
                    "PORTAL_PUBLIC_URL": f"{URL_PORTAL_LOCAL}:{porta}",
                    "PALWORLD_API_URL": endereco_api,
                    "PALWORLD_ADMIN_PASSWORD": (
                        self.senha_administrador.get() if endereco_api else ""
                    ),
                }
            )
            opcoes = {
                "cwd": raiz_projeto,
                "env": ambiente,
                "stdout": self._arquivo_log_portal,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            self._processo_portal = subprocess.Popen(
                [sys.executable, "-u", str(script_portal)], **opcoes
            )
        except OSError as erro:
            if self._arquivo_log_portal:
                self._arquivo_log_portal.close()
                self._arquivo_log_portal = None
            messagebox.showerror("Falha ao iniciar Portal Pandora", str(erro))
            return
        self.status_portal.set(
            f"Iniciando em {URL_PORTAL_LOCAL}:{porta}..."
        )
        self.botao_parar_portal.configure(state="normal")
        self.janela.after(1500, self._verificar_portal)

    def _verificar_portal(self) -> None:
        processo = self._processo_portal
        if processo is None:
            return
        codigo_saida = processo.poll()
        if codigo_saida is not None:
            self._finalizar_portal()
            self.status_portal.set(
                f"O portal encerrou com código {codigo_saida}. Consulte o registro."
            )
            return
        try:
            porta = int(self.portal_porta.get())
        except ValueError:
            porta = 5000
        endereco = f"{URL_PORTAL_LOCAL}:{porta}"
        self.status_portal.set(f"Portal Pandora em execução: {endereco}")
        if not self._portal_aberto:
            self._portal_aberto = True
            webbrowser.open(endereco)
        self.janela.after(5000, self._verificar_portal)

    def _parar_portal(self) -> None:
        processo = self._processo_portal
        if processo is None or processo.poll() is not None:
            self._finalizar_portal()
            return
        if not messagebox.askyesno(
            "Parar Portal Pandora", "Deseja parar o site neste computador?"
        ):
            return
        processo.terminate()
        self.status_portal.set("Parando Portal Pandora...")
        self.janela.after(500, self._aguardar_portal, processo)

    def _aguardar_portal(self, processo: subprocess.Popen[bytes]) -> None:
        if processo.poll() is None:
            self.janela.after(500, self._aguardar_portal, processo)
            return
        self._finalizar_portal()
        self.status_portal.set("Portal Pandora parado.")

    def _finalizar_portal(self) -> None:
        self._processo_portal = None
        self._portal_aberto = False
        self.botao_parar_portal.configure(state="disabled")
        if self._arquivo_log_portal:
            self._arquivo_log_portal.close()
            self._arquivo_log_portal = None

    def _exportar_configuracao_portal(self) -> None:
        try:
            conteudo = gerar_configuracao_portal_hospedagem(
                self.portal_public_url.get(), self.portal_api_url.get()
            )
        except ValueError as erro:
            messagebox.showerror("Configuração inválida", str(erro))
            return
        destino = filedialog.asksaveasfilename(
            title="Salvar configuração do Portal Pandora para hospedagem",
            defaultextension=".env",
            filetypes=[("Configuração de ambiente", "*.env"), ("Todos os arquivos", "*.*")],
            initialfile="portal-pandora-host.env",
        )
        if not destino:
            return
        try:
            backup = gravar_configuracao_segura(Path(destino), conteudo)
        except OSError as erro:
            messagebox.showerror("Falha ao exportar configuração", str(erro))
            return
        mensagem = (
            f"Configuração de endereços salva em:\n{destino}\n\n"
            "Cadastre os segredos do Discord, Mercado Pago e a senha da API "
            "privada no cofre de segredos do provedor."
        )
        if backup:
            mensagem += f"\n\nCópia anterior: {backup.name}"
        messagebox.showinfo("Configuração exportada", mensagem)

    def _iniciar_servidor(self) -> None:
        if self._processo is not None and self._processo.poll() is None:
            messagebox.showinfo("Servidor em execução", "O servidor já está rodando.")
            return
        pasta = Path(self.pasta_servidor.get()).expanduser()
        executavel = pasta / "PalServer.exe"
        if not executavel.is_file():
            messagebox.showerror(
                "Servidor não encontrado",
                "Selecione a pasta de instalação que contém PalServer.exe.",
            )
            return
        if not self._salvar_local():
            return
        try:
            jogadores = int(self.quantidade_jogadores.get())
            porta = int(self.porta.get())
            log_path = pasta / "ServidorPalworld.log"
            self._arquivo_log = log_path.open("ab")
            opcoes = {
                "cwd": pasta,
                "stdout": self._arquivo_log,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            self._processo = subprocess.Popen(
                [str(executavel), f"-port={porta}", f"-players={jogadores}"],
                **opcoes,
            )
        except (OSError, ValueError) as erro:
            if self._arquivo_log:
                self._arquivo_log.close()
                self._arquivo_log = None
            messagebox.showerror("Falha ao iniciar", str(erro))
            return
        self.status.set(
            f"Servidor iniciando na porta UDP {porta}. Registro: {log_path}"
        )
        self.botao_parar.configure(state="normal")
        self.janela.after(2000, self._verificar_processo)
        self._atualizar_enderecos()

    def _parar_servidor(self) -> None:
        processo = self._processo
        if processo is None or processo.poll() is not None:
            self._processo = None
            self.botao_parar.configure(state="disabled")
            self.status.set("Servidor parado")
            return
        if not messagebox.askyesno(
            "Parar servidor",
            "Deseja enviar o sinal de encerramento ao servidor? "
            "Aguarde a gravação do mundo antes de fechar esta janela.",
        ):
            return
        try:
            if os.name == "nt":
                processo.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                processo.send_signal(signal.SIGINT)
        except OSError as erro:
            messagebox.showerror(
                "Não foi possível parar",
                f"O sinal de encerramento não foi enviado: {erro}",
            )
            return
        self.status.set("Solicitando encerramento seguro; aguardando o servidor...")
        self.janela.after(1000, self._aguardar_encerramento, processo)

    def _aguardar_encerramento(self, processo: subprocess.Popen[bytes]) -> None:
        if processo.poll() is None:
            self.janela.after(1000, self._aguardar_encerramento, processo)
            return
        self._processo = None
        self.botao_parar.configure(state="disabled")
        self.status.set("Servidor parado")
        if self._arquivo_log:
            self._arquivo_log.close()
            self._arquivo_log = None

    def _verificar_processo(self) -> None:
        if self._processo is None:
            return
        codigo_saida = self._processo.poll()
        if codigo_saida is None:
            self.status.set("Servidor em execução")
            self.janela.after(5000, self._verificar_processo)
        else:
            self.status.set(
                f"O servidor encerrou com código {codigo_saida}. Consulte o registro."
            )
            self._processo = None
            self.botao_parar.configure(state="disabled")
            if self._arquivo_log:
                self._arquivo_log.close()
                self._arquivo_log = None

    def _atualizar_enderecos(self) -> None:
        porta = self.porta.get().strip()
        linhas = [
            "Endereço local (mesma rede Wi-Fi/roteador):",
            *(
                f"  {endereco}:{porta}"
                for endereco in listar_enderecos_locais()
            ),
        ]
        if len(linhas) == 1:
            linhas.append("  Não foi possível detectar um endereço local.")
        linhas.extend(
            [
                "",
                "Acesso pela Internet:",
                f"  IP público ou domínio: (consulte no roteador) :{porta}",
                f"  Porta do jogo: UDP {porta}",
                "",
                "Para amigos fora da rede: permita esta porta UDP no Firewall "
                "do Windows e encaminhe a mesma porta no roteador para o IP local "
                "deste PC. Nenhuma regra de rede foi alterada por este programa.",
                "Confirme a compatibilidade de crossplay com as versões do jogo "
                "dos seus amigos.",
            ]
        )
        self.texto_enderecos.configure(state="normal")
        self.texto_enderecos.delete("1.0", tk.END)
        self.texto_enderecos.insert("1.0", "\n".join(linhas))
        self.texto_enderecos.configure(state="disabled")

    def _exportar_configuracao(self) -> None:
        try:
            modelo, _ = self._modelo_e_base(
                Path(self.pasta_servidor.get()).expanduser()
            )
            valores = self._obter_valores()
            conteudo = gerar_pal_world_settings(
                modelo,
                nome=valores[0],
                descricao=valores[1],
                quantidade_jogadores=valores[2],
                porta=valores[3],
                senha_servidor=valores[4],
                senha_administrador=valores[5],
                plataformas=valores[6],
                api_rest_ativada=self.api_rest_ativada.get(),
                porta_api_rest=int(self.porta_api_rest.get()),
                rcon_ativado=self.rcon_ativado.get(),
                porta_rcon=int(self.porta_rcon.get()),
            )
        except (OSError, ValueError) as erro:
            messagebox.showerror("Configuração inválida", str(erro))
            return
        destino = filedialog.asksaveasfilename(
            title="Exportar configuração do servidor",
            initialfile=NOME_CONFIGURACAO,
            defaultextension=".ini",
            filetypes=[("Configuração INI", "*.ini")],
        )
        if not destino:
            return
        destino_path = Path(destino)
        if destino_path.exists() and not messagebox.askyesno(
            "Substituir arquivo",
            f"{destino_path.name} já existe. Deseja substituí-lo?",
        ):
            return
        try:
            backup = gravar_configuracao_segura(destino_path, conteudo)
        except OSError as erro:
            messagebox.showerror("Falha na exportação", str(erro))
            return
        mensagem = f"Configuração exportada para:\n{destino_path}"
        if backup:
            mensagem += f"\n\nCópia anterior: {backup}"
        mensagem += "\n\nO arquivo pode conter senhas; envie-o somente pelo canal seguro do provedor."
        messagebox.showinfo("Exportação concluída", mensagem)

    def _abrir_pasta_servidor(self) -> None:
        pasta = Path(self.pasta_servidor.get()).expanduser()
        if not pasta.is_dir():
            messagebox.showerror("Pasta não encontrada", f"Não existe:\n{pasta}")
            return
        os.startfile(pasta)

    def _ao_fechar(self) -> None:
        if self._instalacao_em_andamento:
            messagebox.showinfo(
                "Instalação em andamento",
                "Mantenha o configurador aberto até a instalação do servidor terminar.",
            )
            return
        servidor_ativo = self._processo is not None and self._processo.poll() is None
        bot_ativo = (
            self._processo_sphere is not None
            and self._processo_sphere.poll() is None
        )
        portal_ativo = (
            self._processo_portal is not None
            and self._processo_portal.poll() is None
        )
        if servidor_ativo or bot_ativo or portal_ativo:
            processos = []
            if servidor_ativo:
                processos.append("o servidor Palworld")
            if bot_ativo:
                processos.append("o bot do Discord")
            if portal_ativo:
                processos.append("o Portal Pandora")
            verbo = "continuarão" if len(processos) > 1 else "continuará"
            fechar = messagebox.askyesno(
                "Serviços em execução",
                f"{' e '.join(processos)} {verbo} rodando se você fechar a janela. "
                "Deseja fechar o configurador mesmo assim?",
            )
            if not fechar:
                return
        if self._arquivo_log:
            self._arquivo_log.close()
            self._arquivo_log = None
        if self._arquivo_log_sphere:
            self._arquivo_log_sphere.close()
            self._arquivo_log_sphere = None
        if self._arquivo_log_portal:
            self._arquivo_log_portal.close()
            self._arquivo_log_portal = None
        self.janela.destroy()


def main() -> None:
    janela = tk.Tk()
    ConfiguradorPalworld(janela)
    janela.mainloop()


if __name__ == "__main__":
    main()
