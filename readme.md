# Menu, palworld server

Projeto de estudo em Python inspirado no planejamento e na hospedagem de um servidor dedicado de Palworld. Inclui um planejador de materiais e um configurador visual em português para Windows.

> Os Pals e as receitas incluídos são exemplos fictícios para demonstrar os algoritmos. Edite os dados em `planejador_palworld.py` para montar seu próprio cenário.

## Funcionalidades

- Calcula quantos lotes de uma receita são necessários para produzir a quantidade desejada.
- Compara os materiais necessários com o inventário e mostra o que ainda falta.
- Ordena os Pals por aptidão para uma tarefa, usando o nome como critério de desempate.
- Valida quantidades e argumentos inválidos com mensagens de erro claras.
- Executa sem instalar bibliotecas de terceiros.

## Requisitos

- Python 3.10 ou superior.

## Como executar

No terminal, na pasta do projeto:

```bash
python planejador_palworld.py
```

O exemplo padrão calcula os materiais para fabricar três unidades e recomenda trabalhadores para artesanato. Informe os materiais disponíveis usando `--inventario`:

```bash
python planejador_palworld.py --quantidade 5 --inventario madeira=6 --inventario pedra=2
```

Cada `--inventario` recebe um recurso no formato `nome=quantidade`. Para ver as opções:

```bash
python planejador_palworld.py --ajuda
```

## Exemplo de saída

```text
=== Planejador de base de Palworld ===
Receita: kit de construção
Unidades desejadas: 3

Materiais:
- madeira: precisa de 6, tem 0, faltam 6
- pedra: precisa de 4, tem 0, faltam 4

Pals recomendados para artesanato:
- Pal Artesão (aptidão 3)
- Pal de Transporte (aptidão 1)
```

## Algoritmos e decisões técnicas

1. **Cálculo de lotes:** usa divisão com arredondamento para cima (`math.ceil`). Se uma receita produz duas unidades por lote e o jogador pede três, o programa calcula dois lotes e multiplica os materiais por dois.
2. **Cálculo de faltas:** para cada material da receita, subtrai o inventário da quantidade necessária e limita o resultado mínimo a zero.
3. **Recomendação de trabalhadores:** filtra quem tem aptidão positiva para a tarefa e ordena por nível decrescente. Em caso de empate, usa o nome em ordem alfabética para manter o resultado previsível.
4. **Separação em funções:** os cálculos ficam em funções reutilizáveis, independentes da interface de terminal, o que facilita testar e evoluir o projeto.

O GitHub Copilot pode apoiar a exploração de alternativas, a escrita de testes e a identificação de casos-limite. As sugestões devem ser revisadas e executadas antes de serem aceitas; neste projeto, os testes registram o comportamento esperado dos algoritmos.

## Configurador visual do servidor

O configurador abre uma janela com abas para o servidor local, hospedagem externa,
eventos e administração:

- **Meu PC:** instale ou atualize o servidor dedicado pelo SteamCMD oficial da Valve, ou selecione uma instalação existente. Configure nome, descrição, limite de jogadores, porta UDP, senhas e plataformas; salve e inicie ou pare o servidor pela janela. A instalação baixa vários GB e não abre portas do Firewall nem altera o roteador.
- **Outra hospedagem:** exporte `PalWorldSettings.ini` e use as informações de porta, jogadores e caminho esperadas pelo seu provedor. O arquivo pode conter senhas; envie-o somente por um canal seguro.
- **Eventos:** organize uma agenda de invasões, chefes, recorrência e prêmios. O configurador avisa quando o horário chega; invocação e distribuição continuam manuais pelo mod.
- **Administração:** com a API REST ativada, consulte jogadores online, anuncie mensagens, expulse ou bane jogadores, remova banimentos, salve o mundo e agende o desligamento. Por segurança, a conexão direta do app aceita apenas localhost ou endereços IP privados.
- **Project Sphere:** abra as versões e o portal de desenvolvedor do Discord, gere um link de convite usando o Application ID criado por você, grave o token no `.env` da pasta local do bot e inicie/pare o bot pelo configurador. O token é guardado em texto nesse arquivo; não o compartilhe nem o publique. O app não cria a aplicação Discord, baixa/atualiza o código do bot nem instala suas dependências.
- **PalDefender:** a aba Administração abre a página oficial do mod e o guia de instalação. O plugin precisa ser instalado separadamente e, conforme a documentação do autor, destina-se a servidores dedicados Windows. O app ativa RCON opcionalmente para integrações compatíveis, mas não baixa nem instala o plugin.

Para abrir no Windows, dê dois cliques em `INICIAR_CONFIGURADOR.bat`. Também é possível executar no terminal:

```bash
python configurador_palworld.py
```

Na primeira instalação, abra **Meu PC**, confirme a pasta de destino e selecione **Instalar/atualizar servidor**. O aplicativo verifica o espaço livre, baixa o SteamCMD oficial e instala o Palworld Dedicated Server por login anônimo; não é necessário possuir ou manter o jogo cliente aberto. Reserve pelo menos 6 GB livres na unidade de destino (10 GB recomendados). Se o SteamCMD falhar, o registro detalhado fica em `%LOCALAPPDATA%\ConfiguradorPalworld\SteamCMD\instalacao-servidor.log`. A mesma ação atualiza uma instalação existente. Faça cópia dos arquivos do mundo antes de atualizar. Depois, configure e use **Iniciar servidor**. O executável, os arquivos do mundo e os registros ficam na pasta escolhida.

O aplicativo não altera o Firewall do Windows nem configura o roteador. Para amigos fora da rede local, permita a porta UDP do jogo no firewall e encaminhe a mesma porta no roteador para o IP local do computador. A aba **Meu PC** mostra os endereços de rede que consegue detectar.

As plataformas selecionadas são gravadas em `CrossplayPlatforms`; o acesso entre plataformas também depende do suporte e da versão do jogo para cada plataforma. Confirme a compatibilidade antes de compartilhar o endereço do servidor.

#### Administração e hospedagem externa

A API REST e o RCON ficam desativados por padrão. Ative apenas os serviços necessários, defina uma senha administrativa forte e reinicie o servidor para aplicar as opções. A API REST oficial usa autenticação HTTP Basic sem criptografia adicional quando configurada em HTTP e a documentação recomenda não expô-la diretamente à Internet. Prefira localhost ou uma rede privada confiável e não encaminhe as portas REST/RCON no roteador. O painel integrado é destinado ao próprio computador ou à rede privada; para administração remota, prefira uma VPN ou a integração com bot, seguindo os requisitos e as permissões do provedor.

O [Project Sphere](https://github.com/projectsphere/sphere) é um bot de Discord self-hosted, não um bot público pronto para convidar. Para usá-lo, baixe uma versão publicada, crie seu próprio aplicativo/bot no Discord Developer Portal e instale as dependências do projeto (Python 3.11+), depois selecione a pasta no configurador para salvar o token e iniciar/parar o processo. O botão de convite abre a autorização do aplicativo informado, mas você deve revisar as permissões antes de adicionar o bot ao servidor Discord e configurar o servidor com os comandos do próprio Sphere. Recursos de acesso remoto por SFTP dependem da variante SFTP do Sphere e do suporte da hospedagem; o configurador não envia credenciais nem arquivos ao provedor.

O [PalDefender](https://www.nexusmods.com/palworld/mods/451) é um plugin comunitário de proteção server-side para servidor dedicado Windows. A instalação e as atualizações devem seguir as instruções oficiais e ser verificadas quanto à compatibilidade com a versão atual do Palworld. Em uma hospedagem externa, confirme primeiro se o provedor aceita plugins nativos e permite administrá-los.

### Agenda de eventos

A aba **Eventos** permite cadastrar invasões, chefes, chefes de Raid e eventos personalizados, com início, recorrência (uma vez, diária ou semanal) e prêmio planejado por participante. Os dados ficam em `%LOCALAPPDATA%\ConfiguradorPalworld\eventos.json`.

O configurador precisa permanecer aberto no computador que executa a agenda para exibir os avisos de início. A invocação do Pal/boss e a entrega do prêmio a cada participante são manuais dentro do jogo; o painel não controla o menu do mod nem distribui itens automaticamente.

Para organizar o evento dentro do jogo, use o [Creative Menu original da Oficina Steam](https://steamcommunity.com/sharedfiles/filedetails/?id=3625287786). A página do mod informa que o servidor e o jogador que utilizará o menu precisam do mod, e que o administrador deve conceder permissão para uso em multiplayer. Os demais jogadores podem entrar sem instalar o mod. Use o item original da Oficina e confira as instruções e a compatibilidade com a versão atual antes de instalar. O menu abre com **F1**; ele também pode invocar variantes Raid.

## Portal Pandora

O Portal Pandora é um site separado do configurador Windows, com identidade visual
original de fantasia cósmica e bioluminescente inspirada no nome Pandora. Ele não
reutiliza imagens ou personagens de outras franquias.

### Executar no próprio PC

1. Instale Python 3.10 ou superior.
2. Na pasta do projeto, execute `py -3 -m pip install -r requirements.txt`. Se o Python
   não tiver o pip instalado, execute antes `py -3 -m ensurepip --upgrade`.
3. Copie `.env.example` para `.env` e preencha as configurações do Discord e do Mercado
   Pago. O arquivo `.env` está ignorado pelo Git e não deve ser compartilhado.
4. No configurador Windows, abra a aba **Portal Pandora** e use **Iniciar e abrir site local**. Também é possível executar `INICIAR_PORTAL.bat`. Para habilitar os comandos da equipe, execute `INICIAR_BOT_PORTAL.bat` em outra janela.

O site local fica em `http://127.0.0.1:5000` por padrão e é acessível apenas no próprio
computador. O configurador inicia e para o processo local do portal e abre o navegador.
Se a API REST estiver ativa na aba **Meu PC**, o portal local usa a senha administrativa
informada na interface e o endereço privado configurado. O banco SQLite e os dados ficam
no caminho configurado por `PORTAL_DATABASE_PATH`.

Na aba **Portal Pandora**, informe a origem HTTPS pública e, opcionalmente, o endereço
privado da API do servidor. **Exportar configuração para o host** cria um arquivo com
somente `PORTAL_PUBLIC_URL` e `PALWORLD_API_URL`, sem senhas ou tokens, para cadastrar
no provedor. A implantação do site continua sendo feita no provedor com Docker/Python;
cadastre os segredos Discord/Mercado Pago e `PALWORLD_ADMIN_PASSWORD` no cofre de
segredos da hospedagem. O host precisa alcançar o servidor por uma VPN/rede privada
compatível. O app não envia arquivos, segredos ou comandos administrativos ao provedor.

### Hospedar em um provedor

O repositório inclui um `Dockerfile` e um `Procfile` para provedores que aceitam Python
ou Docker. Configure os mesmos valores de ambiente em um cofre de segredos do provedor,
ative HTTPS e mantenha um volume persistente para o banco SQLite. O site e o processo do
bot precisam acessar o mesmo banco; para esta versão, use somente uma instância web e
um volume durável compartilhado. Não publique o arquivo `.env` nem o banco.

Uma hospedagem pública precisa de um domínio HTTPS para o login OAuth do Discord e para
os webhooks do Mercado Pago. Em **Redirects** do aplicativo OAuth, cadastre
`https://SEU-DOMINIO/auth/discord`; configure `PORTAL_PUBLIC_URL` com a mesma origem.
Não exponha diretamente as portas REST/RCON do jogo. Para conectar um portal externo ao
servidor, use uma VPN/rede privada e informe o endereço privado em `PALWORLD_API_URL`.
O cliente do app rejeita endereços públicos.

### Discord, comandos e VIP

Crie um aplicativo/bot próprio para o Portal Pandora, diferente do Project Sphere.
Configure `identify` para login do site, ative os comandos de aplicação e convide o bot
para o Discord. Dê a ele **Gerenciar cargos** e coloque o cargo do bot acima do cargo
VIP na hierarquia. Preencha `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
`DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_VIP_ROLE_ID` e `DISCORD_ADMIN_IDS`.
O ID do jogador no Discord deve ser informado em `DISCORD_ADMIN_IDS` para autorizar
comandos; nenhum usuário pode administrar apenas por entrar no site.

Comandos iniciais da equipe:

- `/portal-ajuda`
- `/loja-criar` e `/loja-listar`
- `/missao-criar`, `/missao-pendentes` e `/missao-decidir`
- `/meta-criar`, `/meta-listar` e `/meta-atualizar`
- `/vip-reaplicar`
- `/servidor-status`, `/servidor-jogadores`, `/servidor-anunciar`,
  `/servidor-expulsar`, `/servidor-banir`, `/servidor-desbanir`,
  `/servidor-salvar` e `/servidor-desligar`

O `/loja-criar` aceita `dias_vip=0` para um produto sem VIP, `-1` para cargo permanente
ou um número positivo de dias. A expiração de cargos temporários é sincronizada pelo bot
enquanto ele estiver em execução. O Discord precisa permitir que o bot gerencie esse
cargo e o membro precisa estar no servidor Discord.

### Mercado Pago

A loja usa Checkout Pro: o comprador finaliza o pagamento no ambiente do Mercado Pago,
e o site só ativa o VIP depois de confirmar a situação do pagamento pela API e validar
a assinatura do webhook. Configure credenciais de **teste** primeiro e cadastre a URL
`https://SEU-DOMINIO/webhooks/mercadopago` para notificações de pagamentos. Em produção,
use `MERCADOPAGO_ACCESS_TOKEN` e `MERCADOPAGO_WEBHOOK_SECRET` de produção apenas no
provedor, nunca em código ou no Git. Defina uma chave aleatória forte em
`PORTAL_SECRET_KEY`.

O recurso atual registra o pedido e concede um cargo VIP no Discord. Não concede
vantagens nem itens dentro do Palworld. Antes de vender qualquer benefício, confira os
termos do jogo, do provedor de hospedagem, do Discord e do Mercado Pago, além das
obrigações legais aplicáveis.

### Mapa ao vivo, missões e limites de dados

Depois que o Discord autentica o jogador, o portal consulta a lista da API REST privada
do servidor a cada 15 segundos e plota os jogadores online pelas coordenadas X/Y
retornadas pelo jogo. O radar mostra nomes, nível e coordenadas; não mostra IP nem IDs
da conta. Ao selecionar um marcador, o jogador vê os dados básicos da posição. Essa API
oficial não fornece uma imagem/terreno do mapa, contador de estátuas, inventário de
coletáveis ou conquistas por jogador. O radar é uma visualização dinâmica de
coordenadas, não um mapa de terreno. Fonte: [API REST oficial de jogadores do
Palworld](https://docs.palworldgame.com/api/rest-api/players/).

O painel aceita comprovação de missão e os administradores analisam pelo Discord. A
entrega de itens no jogo permanece manual. A equipe pode criar contadores, por exemplo
`/meta-criar título:Estátuas total:50`, e registrar o valor individual com
`/meta-atualizar`; o painel do jogador exibe `1/50`. Esses contadores são manuais nesta
versão, não uma lista completa ou sincronizada de conquistas do jogo. A contagem
automática de estátuas/coletáveis exige uma integração server-side que emita esses
eventos e uma forma confiável de vincular a conta do jogo ao Discord. Essa telemetria
não está disponível na API REST oficial e ainda não foi implementada; não instale mods
nos jogadores sem verificar compatibilidade e segurança. Hospedagens externas precisam
permitir a instalação do plugin server-side escolhido.

O Project Sphere e o PalDefender continuam sendo componentes separados: o bot do
Portal Pandora usa seu próprio aplicativo Discord, o Project Sphere não recebe estes
comandos automaticamente, e o PalDefender/Creative Menu precisam ser instalados e
configurados manualmente conforme a Oficina/mod e as permissões do provedor.

## Créditos e atribuições

Este projeto foi desenvolvido por **Samuel Oliveira**, com assistência do **GitHub
Copilot** para apoiar implementação, documentação e testes. O código específico do
planejador, configurador, agenda de eventos e Portal Pandora foi criado para este
repositório; as ferramentas de terceiros abaixo mantêm seus próprios autores, marcas,
termos e licenças.

- **DIO / GitHub Quick Start:** desafio educacional e repositório-base que inspiraram
  este trabalho: [digitalinnovationone/github-quickstart](https://github.com/digitalinnovationone/github-quickstart).
- **Palworld / Pocketpair:** jogo, servidor dedicado, nomes e demais marcas pertencem
  aos respectivos titulares. O projeto não é oficial nem afiliado à Pocketpair.
  Referências: [documentação oficial da API](https://docs.palworldgame.com/) e
  [página do Palworld na Steam](https://store.steampowered.com/app/1623730/Palworld/).
- **Valve / SteamCMD:** ferramenta oficial usada para baixar e atualizar o servidor
  dedicado: [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD).
- **Python e bibliotecas:** [Python](https://www.python.org/), [Flask](https://flask.palletsprojects.com/),
  [discord.py](https://discordpy.readthedocs.io/), [python-dotenv](https://github.com/theskumar/python-dotenv)
  e [Gunicorn](https://gunicorn.org/). O Tkinter faz parte da distribuição padrão
  do Python usada no Windows.
- **Discord:** serviço de autenticação OAuth e plataforma do bot; sujeito aos
  [termos para desenvolvedores](https://discord.com/developers/docs/policies-and-agreements/terms-of-service).
- **Mercado Pago:** serviço externo de Checkout Pro e notificações de pagamento;
  sujeito aos [termos e condições aplicáveis](https://www.mercadopago.com.br/ajuda/termos-e-condicoes_299).
- **Project Sphere:** projeto comunitário separado, opcional e não incluído neste
  repositório: [projectsphere/sphere](https://github.com/projectsphere/sphere).
- **PalDefender:** plugin comunitário separado, opcional e não incluído neste
  repositório: [página do projeto](https://www.nexusmods.com/palworld/mods/451) e
  [guia de instalação](https://ultimeit.github.io/PalDefender/).
- **Creative Menu:** mod da Oficina Steam, separado e opcional, sujeito às regras e
  instruções do autor: [página do item](https://steamcommunity.com/sharedfiles/filedetails/?id=3625287786).

Esses créditos não implicam endosso, parceria ou inclusão dos produtos externos no
aplicativo. Consulte as licenças e os termos de cada titular antes de redistribuir,
modificar ou usar os respectivos serviços e complementos.

## Testes

Para executar também os testes do Portal Pandora, instale os pacotes descritos em
`requirements.txt`:

```bash
python -m pip install -r requirements.txt
python -m unittest -v
```

## Estrutura

```text
.
├── planejador_palworld.py
├── test_planejador_palworld.py
├── eventos_palworld.py
├── test_eventos_palworld.py
├── palworld_admin.py
├── test_palworld_admin.py
├── test_configurador_palworld.py
├── configurador_palworld.py
├── portal_palworld.py
├── bot_portal.py
├── test_portal_palworld.py
├── templates/portal.html
├── static/mapa.js
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .env.example
├── Procfile
├── INICIAR_CONFIGURADOR.bat
├── INICIAR_PORTAL.bat
├── INICIAR_BOT_PORTAL.bat
└── README.md
```
