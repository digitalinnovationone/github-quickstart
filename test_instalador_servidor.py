"""Testes offline para preparação e instalação do servidor dedicado."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from instalador_servidor import (
    APP_ID_PALWORLD_SERVER,
    ESPACO_LIVRE_MINIMO,
    criar_comando_steamcmd,
    extrair_steamcmd,
    verificar_espaco_destino,
)


class TesteInstaladorServidor(unittest.TestCase):
    def test_comando_instala_servidor_anonimamente_pelo_steamcmd(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            comando = criar_comando_steamcmd(
                raiz / "steamcmd.exe", raiz / "PalServer"
            )
        self.assertIn("+login", comando)
        self.assertIn("anonymous", comando)
        self.assertIn(APP_ID_PALWORLD_SERVER, comando)
        self.assertIn("+app_update", comando)
        self.assertIn("validate", comando)

    def test_extrai_pacote_do_steamcmd(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            pacote = raiz / "steamcmd.zip"
            with zipfile.ZipFile(pacote, "w") as arquivo:
                arquivo.writestr("steamcmd.exe", b"steamcmd")
            executavel = extrair_steamcmd(pacote, raiz / "SteamCMD")
            self.assertEqual(executavel.read_bytes(), b"steamcmd")

    def test_rejeita_caminho_de_extracao_fora_da_pasta(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            pacote = raiz / "steamcmd.zip"
            with zipfile.ZipFile(pacote, "w") as arquivo:
                arquivo.writestr("../fora.txt", b"nao")
            with self.assertRaisesRegex(ValueError, "caminho de arquivo inválido"):
                extrair_steamcmd(pacote, raiz / "SteamCMD")
            self.assertFalse((raiz / "fora.txt").exists())

    def test_informa_quando_espaco_livre_e_insuficiente(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            with self.assertRaisesRegex(OSError, "escolha uma pasta em outra unidade"):
                verificar_espaco_destino(
                    Path(temporario),
                    espaco_livre_bytes=1024**3,
                )

    def test_aceita_minimo_de_espaco_livre(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            livre = verificar_espaco_destino(
                Path(temporario),
                espaco_livre_bytes=ESPACO_LIVRE_MINIMO,
            )
        self.assertEqual(livre, ESPACO_LIVRE_MINIMO)


if __name__ == "__main__":
    unittest.main()
