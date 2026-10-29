"""Instalação do servidor dedicado Palworld pelo SteamCMD oficial."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable
from urllib.request import urlopen


URL_STEAMCMD = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
APP_ID_PALWORLD_SERVER = "2394010"
ESPACO_LIVRE_MINIMO = 6 * 1024**3


def verificar_espaco_destino(
    destino: Path, *, espaco_livre_bytes: int | None = None
) -> int:
    """Garante espaço para a pré-alocação de 5,35 GB observada pelo SteamCMD."""
    pasta = destino.expanduser()
    while not pasta.exists() and pasta != pasta.parent:
        pasta = pasta.parent
    if not pasta.is_dir():
        raise NotADirectoryError(f"O destino da instalação não é uma pasta: {pasta}")
    livre = (
        shutil.disk_usage(pasta).free
        if espaco_livre_bytes is None
        else espaco_livre_bytes
    )
    if livre < ESPACO_LIVRE_MINIMO:
        livre_gb = livre / 1024**3
        minimo_gb = ESPACO_LIVRE_MINIMO / 1024**3
        raise OSError(
            f"Espaço insuficiente na unidade de instalação: há {livre_gb:.1f} GB "
            f"livres; libere pelo menos {minimo_gb:.0f} GB (recomendado: 10 GB) "
            "ou escolha uma pasta em outra unidade."
        )
    return livre


def criar_comando_steamcmd(steamcmd: Path, destino: Path) -> list[str]:
    return [
        str(steamcmd),
        "+force_install_dir",
        str(destino.resolve()),
        "+login",
        "anonymous",
        "+app_update",
        APP_ID_PALWORLD_SERVER,
        "validate",
        "+quit",
    ]


def extrair_steamcmd(arquivo_zip: Path, destino: Path) -> Path:
    """Extrai SteamCMD sem permitir caminhos de arquivo fora da pasta destino."""
    destino.mkdir(parents=True, exist_ok=True)
    raiz = destino.resolve()
    with zipfile.ZipFile(arquivo_zip) as pacote:
        for membro in pacote.infolist():
            caminho = (raiz / membro.filename).resolve()
            if caminho != raiz and raiz not in caminho.parents:
                raise ValueError("O pacote SteamCMD contém um caminho de arquivo inválido.")
        pacote.extractall(raiz)
    executavel = raiz / "steamcmd.exe"
    if not executavel.is_file():
        raise FileNotFoundError("O pacote baixado não contém steamcmd.exe.")
    return executavel


def preparar_steamcmd(
    destino: Path, informar: Callable[[str], None] = lambda _mensagem: None
) -> Path:
    executavel = destino / "steamcmd.exe"
    if executavel.is_file():
        return executavel

    destino.mkdir(parents=True, exist_ok=True)
    informar("Baixando SteamCMD do servidor oficial da Valve...")
    arquivo_temporario: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destino, suffix=".zip", delete=False
        ) as temporario:
            arquivo_temporario = Path(temporario.name)
            with urlopen(URL_STEAMCMD, timeout=60) as resposta:
                shutil.copyfileobj(resposta, temporario)
        informar("Extraindo SteamCMD...")
        return extrair_steamcmd(arquivo_temporario, destino)
    finally:
        if arquivo_temporario is not None:
            arquivo_temporario.unlink(missing_ok=True)


def instalar_servidor_palworld(
    steamcmd: Path,
    destino: Path,
    informar: Callable[[str], None] = lambda _mensagem: None,
) -> None:
    """Instala ou atualiza Palworld Dedicated Server, preservando os dados existentes."""
    verificar_espaco_destino(destino)
    destino.mkdir(parents=True, exist_ok=True)
    comando = criar_comando_steamcmd(steamcmd, destino)
    informar("Instalando ou atualizando o servidor dedicado Palworld...")
    opcoes: dict[str, object] = {
        "cwd": steamcmd.parent,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        opcoes["creationflags"] = subprocess.CREATE_NO_WINDOW
    caminho_log = steamcmd.parent / "instalacao-servidor.log"
    with caminho_log.open("a", encoding="utf-8", errors="replace") as registro:
        processo = subprocess.Popen(comando, **opcoes)
        if processo.stdout is not None:
            for linha in processo.stdout:
                registro.write(linha)
                registro.flush()
                linha = linha.strip()
                if linha:
                    informar(linha[-400:])
        codigo = processo.wait()
    if codigo:
        raise RuntimeError(
            f"O SteamCMD encerrou com código {codigo}. Consulte o registro em "
            f"{caminho_log} e libere espaço suficiente na unidade de destino."
        )
    if not (destino / "PalServer.exe").is_file():
        raise FileNotFoundError(
            "O SteamCMD terminou, mas não encontrei PalServer.exe na pasta escolhida."
        )
