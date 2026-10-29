"""Comandos Discord para a loja, missões e administração do servidor."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from palworld_admin import ClienteRESTPalworld, ErroAPIPalworld
from portal_palworld import (
    DATABASE_PADRAO,
    abrir_banco,
    atualizar_progresso_exploracao,
    criar_meta_exploracao,
    criar_missao,
    criar_produto,
    _normalizar_ids,
    _valor_em_centavos,
)

load_dotenv()


LOG = logging.getLogger(__name__)
CAMINHO_BANCO = Path(os.environ.get("PORTAL_DATABASE_PATH", str(DATABASE_PADRAO)))
IDS_ADMIN = _normalizar_ids(os.environ.get("DISCORD_ADMIN_IDS", ""))
ID_SERVIDOR_DISCORD = os.environ.get("DISCORD_GUILD_ID", "")
ID_CARGO_VIP = os.environ.get("DISCORD_VIP_ROLE_ID", "")


async def somente_admin(interacao: discord.Interaction) -> bool:
    return str(interacao.user.id) in IDS_ADMIN


def cliente_jogo() -> ClienteRESTPalworld:
    endereco = os.environ.get("PALWORLD_API_URL", "")
    senha = os.environ.get("PALWORLD_ADMIN_PASSWORD", "")
    if not endereco or not senha:
        raise ValueError(
            "Configure PALWORLD_API_URL e PALWORLD_ADMIN_PASSWORD no ambiente do bot."
        )
    return ClienteRESTPalworld(endereco, senha)


def dinheiro_centavos(valor: str) -> int:
    try:
        decimal = Decimal(valor.replace(",", "."))
    except (InvalidOperation, AttributeError) as erro:
        raise ValueError("Informe o preço em reais, por exemplo 19,90.") from erro
    centavos = _valor_em_centavos(decimal)
    if centavos is None or centavos <= 0 or centavos > 100_000_000:
        raise ValueError("O preço deve ficar entre R$ 0,01 e R$ 1.000.000,00.")
    return centavos


def formatar_reais(centavos: int) -> str:
    return f"{centavos / 100:.2f}".replace(".", ",")


class BotPortal(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=discord.Intents.none())

    async def setup_hook(self) -> None:
        if ID_SERVIDOR_DISCORD.isdigit():
            servidor = discord.Object(id=int(ID_SERVIDOR_DISCORD))
            self.tree.copy_global_to(guild=servidor)
            await self.tree.sync(guild=servidor)
        else:
            await self.tree.sync()
        expirar_beneficios.start()


bot = BotPortal()


@bot.tree.command(name="portal-ajuda", description="Mostra os comandos administrativos do portal.")
@app_commands.check(somente_admin)
async def portal_ajuda(interacao: discord.Interaction) -> None:
    await interacao.response.send_message(
        "**Comandos administrativos do portal**\n"
        "`/missao-criar`, `/missao-pendentes`, `/missao-decidir`\n"
        "`/meta-criar`, `/meta-atualizar`, `/meta-listar`\n"
        "`/loja-criar`, `/loja-listar`, `/vip-reaplicar`\n"
        "`/servidor-status`, `/servidor-jogadores`, `/servidor-anunciar`, "
        "`/servidor-expulsar`, `/servidor-banir`, `/servidor-desbanir`, "
        "`/servidor-salvar`, `/servidor-desligar`",
        ephemeral=True,
    )


@bot.tree.command(name="missao-criar", description="Publica uma missão no painel do jogador.")
@app_commands.check(somente_admin)
@app_commands.describe(
    titulo="Título curto da missão",
    objetivo="Como o jogador conclui a missão",
    premio="Prêmio que a equipe entregará",
)
async def missao_criar(
    interacao: discord.Interaction,
    titulo: str,
    objetivo: str,
    premio: str,
) -> None:
    try:
        missao_id = await asyncio.to_thread(
            criar_missao, CAMINHO_BANCO, titulo, objetivo, premio
        )
    except (OSError, ValueError) as erro:
        await interacao.response.send_message(f"Não foi possível criar a missão: {erro}", ephemeral=True)
        return
    await interacao.response.send_message(
        f"Missão **#{missao_id} — {titulo}** publicada. As comprovações aparecem em `/missao-pendentes`.",
        ephemeral=True,
    )


@bot.tree.command(name="missao-pendentes", description="Lista comprovações aguardando análise.")
@app_commands.check(somente_admin)
async def missao_pendentes(interacao: discord.Interaction) -> None:
    with abrir_banco(CAMINHO_BANCO) as banco:
        itens = banco.execute(
            """
            SELECT r.id, r.discord_id, r.prova, r.criada_em, m.titulo, m.premio
            FROM reivindicacoes r JOIN missoes m ON m.id = r.missao_id
            WHERE r.status = 'pendente' ORDER BY r.criada_em LIMIT 10
            """
        ).fetchall()
    if not itens:
        await interacao.response.send_message("Não há comprovações pendentes.", ephemeral=True)
        return
    linhas = []
    for item in itens:
        prova = item["prova"][:500]
        linhas.append(
            f"**#{item['id']} — {item['titulo']}** · <@{item['discord_id']}>\n"
            f"Prêmio: {item['premio']}\nComprovação: {prova}"
        )
    mensagem = "\n\n".join(linhas)
    await interacao.response.send_message(mensagem[:1900], ephemeral=True)


@bot.tree.command(name="missao-decidir", description="Aprova ou recusa uma comprovação de missão.")
@app_commands.check(somente_admin)
@app_commands.choices(
    decisao=[
        app_commands.Choice(name="Aprovar", value="aprovada"),
        app_commands.Choice(name="Recusar", value="recusada"),
    ]
)
async def missao_decidir(
    interacao: discord.Interaction,
    id_comprovacao: int,
    decisao: app_commands.Choice[str],
    motivo: str = "",
) -> None:
    if decisao.value == "recusada" and not motivo.strip():
        await interacao.response.send_message(
            "Informe um motivo ao recusar a comprovação.", ephemeral=True
        )
        return
    with abrir_banco(CAMINHO_BANCO) as banco:
        cursor = banco.execute(
            """
            UPDATE reivindicacoes
            SET status = ?, revisado_por = ?, revisado_em = ?
            WHERE id = ? AND status = 'pendente'
            """,
            (
                decisao.value,
                str(interacao.user.id),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                id_comprovacao,
            ),
        )
    if not cursor.rowcount:
        await interacao.response.send_message(
            "Comprovação não encontrada ou já analisada.", ephemeral=True
        )
        return
    resposta = "Missão aprovada. Entregue o prêmio no jogo e avise o jogador."
    if decisao.value == "recusada":
        resposta = f"Comprovação recusada. Motivo: {motivo.strip()}"
    await interacao.response.send_message(resposta, ephemeral=True)


@bot.tree.command(name="meta-criar", description="Cadastra um contador de exploração no painel.")
@app_commands.check(somente_admin)
async def meta_criar(
    interacao: discord.Interaction, titulo: str, total: app_commands.Range[int, 1, 100000]
) -> None:
    try:
        meta_id = await asyncio.to_thread(
            criar_meta_exploracao, CAMINHO_BANCO, titulo, total
        )
    except (OSError, ValueError) as erro:
        await interacao.response.send_message(f"Não foi possível criar a meta: {erro}", ephemeral=True)
        return
    await interacao.response.send_message(
        f"Meta **#{meta_id} — {titulo}** criada com total {total}. Use `/meta-atualizar` para registrar o progresso.",
        ephemeral=True,
    )


@bot.tree.command(name="meta-atualizar", description="Atualiza o contador de exploração de um jogador.")
@app_commands.check(somente_admin)
async def meta_atualizar(
    interacao: discord.Interaction,
    membro: discord.Member,
    id_meta: int,
    quantidade: app_commands.Range[int, 0, 100000],
) -> None:
    try:
        await asyncio.to_thread(
            atualizar_progresso_exploracao,
            CAMINHO_BANCO,
            id_meta,
            str(membro.id),
            quantidade,
            str(interacao.user.id),
        )
    except (OSError, ValueError) as erro:
        await interacao.response.send_message(f"Não foi possível atualizar o progresso: {erro}", ephemeral=True)
        return
    await interacao.response.send_message(
        f"Progresso de <@{membro.id}> atualizado para **{quantidade}**.",
        ephemeral=True,
    )


@bot.tree.command(name="meta-listar", description="Lista os contadores de exploração cadastrados.")
@app_commands.check(somente_admin)
async def meta_listar(interacao: discord.Interaction) -> None:
    with abrir_banco(CAMINHO_BANCO) as banco:
        metas = banco.execute(
            "SELECT id, titulo, total FROM metas_exploracao WHERE ativa = 1 ORDER BY id"
        ).fetchall()
    if not metas:
        await interacao.response.send_message("Nenhuma meta de exploração cadastrada.", ephemeral=True)
        return
    texto = "\n".join(
        f"**#{meta['id']} — {meta['titulo']}**: {meta['total']}"
        for meta in metas
    )
    await interacao.response.send_message(texto[:1900], ephemeral=True)


@bot.tree.command(name="loja-criar", description="Adiciona produto à loja do portal.")
@app_commands.check(somente_admin)
@app_commands.describe(
    titulo="Nome do produto ou pacote VIP",
    preco="Preço em reais, por exemplo 19,90",
    dias_vip="0 para produto sem VIP, -1 para VIP permanente ou quantidade de dias",
    descricao="Descrição exibida no site",
)
async def loja_criar(
    interacao: discord.Interaction,
    titulo: str,
    preco: str,
    dias_vip: int = 0,
    descricao: str = "",
) -> None:
    try:
        centavos = dinheiro_centavos(preco)
        produto_id = await asyncio.to_thread(
            criar_produto, CAMINHO_BANCO, titulo, descricao, centavos, dias_vip
        )
    except (OSError, ValueError) as erro:
        await interacao.response.send_message(f"Não foi possível criar o produto: {erro}", ephemeral=True)
        return
    await interacao.response.send_message(
        f"Produto **#{produto_id} — {titulo}** cadastrado por R$ "
        f"{formatar_reais(centavos)}.",
        ephemeral=True,
    )


@bot.tree.command(name="loja-listar", description="Lista os produtos ativos da loja.")
@app_commands.check(somente_admin)
async def loja_listar(interacao: discord.Interaction) -> None:
    with abrir_banco(CAMINHO_BANCO) as banco:
        produtos = banco.execute(
            "SELECT id, titulo, preco_centavos, dias_vip FROM produtos WHERE ativo = 1 ORDER BY id"
        ).fetchall()
    if not produtos:
        await interacao.response.send_message("A loja ainda não tem produtos ativos.", ephemeral=True)
        return
    texto = "\n".join(
        f"**#{p['id']} {p['titulo']}** — R$ "
        f"{formatar_reais(p['preco_centavos'])}"
        + (
            " · VIP permanente"
            if p["dias_vip"] == -1
            else f" · VIP por {p['dias_vip']} dias"
            if p["dias_vip"] > 0
            else ""
        )
        for p in produtos
    )
    await interacao.response.send_message(texto[:1900], ephemeral=True)


@bot.tree.command(name="vip-reaplicar", description="Reaplica o cargo VIP de um jogador.")
@app_commands.check(somente_admin)
async def vip_reaplicar(
    interacao: discord.Interaction, membro: discord.Member
) -> None:
    if not ID_CARGO_VIP:
        await interacao.response.send_message(
            "Configure DISCORD_VIP_ROLE_ID antes de usar este comando.", ephemeral=True
        )
        return
    with abrir_banco(CAMINHO_BANCO) as banco:
        beneficio = banco.execute(
            """
            SELECT 1 FROM beneficios_vip
            WHERE discord_id = ?
                AND (expira_em IS NULL OR expira_em > ?)
            LIMIT 1
            """,
            (str(membro.id), datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ).fetchone()
    if not beneficio:
        await interacao.response.send_message(
            "Esse membro não possui um VIP ativo registrado.", ephemeral=True
        )
        return
    cargo = interacao.guild.get_role(int(ID_CARGO_VIP)) if interacao.guild else None
    if cargo is None:
        await interacao.response.send_message(
            "Não encontrei o cargo configurado neste servidor.", ephemeral=True
        )
        return
    try:
        await membro.add_roles(cargo, reason=f"VIP confirmado pela equipe {interacao.user.id}")
    except discord.HTTPException as erro:
        await interacao.response.send_message(
            f"O Discord recusou a alteração de cargo: {erro}", ephemeral=True
        )
        return
    await interacao.response.send_message(
        f"Cargo {cargo.mention} aplicado a {membro.mention}.", ephemeral=True
    )


@bot.tree.command(name="servidor-status", description="Consulta informações do servidor de jogo.")
@app_commands.check(somente_admin)
async def servidor_status(interacao: discord.Interaction) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        dados = await asyncio.to_thread(cliente.informacoes_servidor)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao consultar o servidor: {erro}", ephemeral=True)
        return
    await interacao.followup.send(
        f"```json\n{str(dados)[:1700]}\n```", ephemeral=True
    )


@bot.tree.command(name="servidor-jogadores", description="Lista os jogadores conectados.")
@app_commands.check(somente_admin)
async def servidor_jogadores(interacao: discord.Interaction) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        jogadores = await asyncio.to_thread(cliente.listar_jogadores)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao consultar jogadores: {erro}", ephemeral=True)
        return
    if not jogadores:
        await interacao.followup.send("Não há jogadores conectados.", ephemeral=True)
        return
    linhas = []
    for jogador in jogadores[:30]:
        nome = str(jogador.get("name", "Nome indisponível"))[:80]
        user_id = str(jogador.get("userId", "ID indisponível"))[:100]
        linhas.append(f"**{nome}** — `{user_id}`")
    await interacao.followup.send("\n".join(linhas)[:1900], ephemeral=True)


@bot.tree.command(name="servidor-anunciar", description="Envia um aviso dentro do jogo.")
@app_commands.check(somente_admin)
async def servidor_anunciar(interacao: discord.Interaction, mensagem: str) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        await asyncio.to_thread(cliente.anunciar, mensagem)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao enviar o aviso: {erro}", ephemeral=True)
        return
    await interacao.followup.send("Aviso enviado ao servidor.", ephemeral=True)


@bot.tree.command(name="servidor-expulsar", description="Expulsa um jogador pelo ID de usuário.")
@app_commands.check(somente_admin)
async def servidor_expulsar(
    interacao: discord.Interaction, id_jogador: str, motivo: str = ""
) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        await asyncio.to_thread(cliente.expulsar, id_jogador, motivo)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao expulsar o jogador: {erro}", ephemeral=True)
        return
    await interacao.followup.send("Jogador expulso.", ephemeral=True)


@bot.tree.command(name="servidor-banir", description="Bane um jogador pelo ID de usuário.")
@app_commands.check(somente_admin)
async def servidor_banir(
    interacao: discord.Interaction, id_jogador: str, motivo: str = ""
) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        await asyncio.to_thread(cliente.banir, id_jogador, motivo)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao banir o jogador: {erro}", ephemeral=True)
        return
    await interacao.followup.send("Jogador banido.", ephemeral=True)


@bot.tree.command(name="servidor-desbanir", description="Remove o banimento pelo ID de usuário.")
@app_commands.check(somente_admin)
async def servidor_desbanir(interacao: discord.Interaction, id_jogador: str) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        await asyncio.to_thread(cliente.desbanir, id_jogador)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao remover banimento: {erro}", ephemeral=True)
        return
    await interacao.followup.send("Banimento removido.", ephemeral=True)


@bot.tree.command(name="servidor-salvar", description="Salva o mundo do servidor.")
@app_commands.check(somente_admin)
async def servidor_salvar(interacao: discord.Interaction) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        await asyncio.to_thread(cliente.salvar_mundo)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao salvar o mundo: {erro}", ephemeral=True)
        return
    await interacao.followup.send("Solicitação de salvamento enviada.", ephemeral=True)


@bot.tree.command(name="servidor-desligar", description="Agenda o desligamento do servidor.")
@app_commands.check(somente_admin)
async def servidor_desligar(
    interacao: discord.Interaction,
    segundos: app_commands.Range[int, 0, 3600] = 60,
    mensagem: str = "O servidor será desligado em breve.",
) -> None:
    await interacao.response.defer(ephemeral=True)
    try:
        cliente = cliente_jogo()
        await asyncio.to_thread(cliente.agendar_desligamento, segundos, mensagem)
    except (ValueError, ErroAPIPalworld, OSError) as erro:
        await interacao.followup.send(f"Falha ao agendar desligamento: {erro}", ephemeral=True)
        return
    await interacao.followup.send(
        f"Desligamento agendado para daqui a {segundos} segundos.", ephemeral=True
    )


@tasks.loop(minutes=10)
async def expirar_beneficios() -> None:
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with abrir_banco(CAMINHO_BANCO) as banco:
        expirados = banco.execute(
            """
            SELECT DISTINCT discord_id FROM beneficios_vip
            WHERE expira_em IS NOT NULL AND expira_em <= ?
                AND expiracao_sincronizada = 0
            """,
            (agora,),
        ).fetchall()
    if not expirados:
        return
    if not ID_SERVIDOR_DISCORD.isdigit() or not ID_CARGO_VIP.isdigit():
        LOG.error("Não foi possível sincronizar expiração VIP: IDs Discord ausentes.")
        return
    servidor = bot.get_guild(int(ID_SERVIDOR_DISCORD))
    cargo = servidor.get_role(int(ID_CARGO_VIP)) if servidor else None
    if servidor is None or cargo is None:
        LOG.error("Servidor ou cargo VIP não encontrado para expiração.")
        return
    for linha in expirados:
        discord_id = linha["discord_id"]
        with abrir_banco(CAMINHO_BANCO) as banco:
            ativo = banco.execute(
                """
                SELECT 1 FROM beneficios_vip
                WHERE discord_id = ?
                    AND (expira_em IS NULL OR expira_em > ?)
                LIMIT 1
                """,
                (discord_id, agora),
            ).fetchone()
        try:
            if not ativo:
                membro = await servidor.fetch_member(int(discord_id))
                await membro.remove_roles(cargo, reason="Expiração do VIP")
        except discord.NotFound:
            pass
        except (ValueError, discord.HTTPException):
            LOG.exception("Falha ao remover VIP expirado do Discord %s", discord_id)
            continue
        with abrir_banco(CAMINHO_BANCO) as banco:
            banco.execute(
                """
                UPDATE beneficios_vip SET expiracao_sincronizada = 1
                WHERE discord_id = ? AND expira_em IS NOT NULL AND expira_em <= ?
                """,
                (discord_id, agora),
            )


@expirar_beneficios.before_loop
async def esperar_bot_pronto() -> None:
    await bot.wait_until_ready()


@bot.tree.error
async def erro_comando(
    interacao: discord.Interaction, erro: app_commands.AppCommandError
) -> None:
    if isinstance(erro, app_commands.CheckFailure):
        mensagem = "Este comando está disponível apenas para a equipe autorizada."
    else:
        LOG.exception("Erro em comando Discord", exc_info=erro)
        mensagem = "O comando falhou; confira o registro do bot para obter detalhes."
    if interacao.response.is_done():
        await interacao.followup.send(mensagem, ephemeral=True)
    else:
        await interacao.response.send_message(mensagem, ephemeral=True)


def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Defina DISCORD_BOT_TOKEN para iniciar o bot do portal.")
    if not IDS_ADMIN:
        raise SystemExit("Defina DISCORD_ADMIN_IDS com os IDs da equipe.")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
