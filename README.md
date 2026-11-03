# ZUKO AI LIVE

ZUKO é um projeto Python com interface desktop para apoiar apresentações ao vivo com personagem virtual. Ele combina leitura de eventos, organização de interações, geração de texto por IA e envio de comandos de animação a uma cena Godot.

## Objetivo

Reunir em um fluxo local os recursos de apresentador virtual do ZUKO: painel de operação, fila inteligente de comentários/eventos, voz, trilhas e personagem animado. A integração com plataformas e provedores externos é opcional e exige configuração explícita.

## Tecnologias e arquitetura

- Python 3.11 ou superior para a interface, motores de conversa, filas, voz e adaptadores.
- Tkinter para o painel desktop.
- Godot 3.6 com GLES2 para o personagem, cenas e animações; a ponte local usa mensagens JSON sobre TCP.
- TikTokLive é uma dependência opcional para leitura de eventos TikTok.
- LiteLLM é uma dependência opcional para provedores compatíveis, inclusive Gemini.
- A configuração do provedor Gemini e da voz Puck requer credencial local. Chamadas podem gerar custos; o uso depende de autorização explícita no painel.

O fluxo principal é: fonte de eventos → normalização e moderação → fila/prioridade → apresentador e IA → voz/áudio → painel e ponte TCP → Godot. A aplicação inclui caminhos de simulação para desenvolvimento.

## Funcionalidades principais

- Painel com estado de conexão, diagnóstico, controles de apresentação e opções de voz/IA.
- Fila de eventos e comentários com prioridade, controle de repetição e overlay de audiência.
- Adaptadores de eventos e modo de simulação; a conexão real depende da configuração de cada usuário.
- Seleção de provedor e limites de autorização para recursos Gemini.
- Voz local e integração de fala sintetizada; o estado de prontidão depende do Windows e do provedor configurado.
- Animações e estados do personagem no Godot, com comunicação local por TCP.
- Controle de trilha sonora com ducking durante a fala. As faixas Kaino incluídas têm aviso CC0 junto dos arquivos.

## Requisitos

- Windows 10/11 (a voz local usa componentes nativos do Windows).
- Python 3.11+ com Tkinter disponível.
- Godot 3.6 para abrir e executar a cena NPC em `npc_runtime/godot`.
- Dependências Python opcionais listadas em [`DEPENDENCIAS.md`](DEPENDENCIAS.md).
- Conta TikTok e chave Gemini somente se você optar por habilitar essas integrações.

## Instalação

1. Clone o repositório e entre na pasta:

   ```powershell
   git clone https://github.com/rodinellesapp-glitch/ZUKO-AI-LIVE.git
   cd ZUKO-AI-LIVE
   ```

2. Crie um ambiente virtual e instale as dependências necessárias para o modo escolhido:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Para voz e áudio local, instale `pygame`: `python -m pip install pygame`. Se usar o pré-lançador NPC, instale também `psutil`: `python -m pip install psutil`. As versões não estão fixadas nem foram validadas neste pacote.

   Para o adaptador TikTok: `python -m pip install -r live_social_01/requirements-tiktok.txt`.
   Para Gemini via LiteLLM: `python -m pip install -r live_social_01/requirements-litellm.txt`.

3. Copie `.env.example` para `.env` e preencha somente no seu computador. O aplicativo lê as variáveis do ambiente do processo; o arquivo `.env` é um modelo de referência e não é carregado automaticamente.

4. Abra `npc_runtime/godot/project.godot` com Godot 3.6 para visualizar a cena. Os recursos gráficos da cena aguardam comprovação de licença e foram omitidos desta cópia preparada; veja a seção de limitações.

## Executar

Para abrir o painel local:

```powershell
python -B abrir_zuko_v2.py
```

O atalho `ABRIR_ZUKO_V2.cmd` inicia o mesmo painel. O fluxo de demonstração/simulador não inicia uma transmissão.

O NPC independente possui instruções próprias em [`npc_runtime/README.md`](npc_runtime/README.md). Não use a opção de fonte TikTok real sem configurar seu identificador e revisar a autorização. A configuração pública do identificador começa vazia nesta cópia.

## Credenciais

Nunca coloque chaves, cookies ou tokens no código, em arquivos versionados ou em capturas de tela. Use as variáveis de ambiente do seu sistema e mantenha `.env` local. O arquivo `.env.example` contém apenas nomes e campos vazios. Não compartilhe limites, histórico, perfis de navegador ou arquivos de sessão.

## Limitações e validação

- O painel, a ponte TCP, a leitura real de eventos, a entrega de voz Gemini Puck e a reprodução do Godot não foram validados de ponta a ponta nesta cópia.
- A conexão TikTok real depende da versão e da disponibilidade do TikTokLive, do canal configurado e de mudanças do serviço.
- Gemini e voz Puck exigem credenciais e podem gerar cobrança; não foram chamados durante a preparação.
- Godot 3.6 e o modelo de personagem têm aviso de licença CC0 preservado. As imagens de cenário não têm licença/proveniência verificável no material encontrado e não estão incluídas; por isso, a apresentação visual completa da cena depende dessa revisão.
- Não há capturas demonstrativas no pacote preparado. Evidências antigas foram excluídas para evitar dados de espectadores, caminhos locais e conteúdo de sessão; imagens serão adicionadas após revisão de direitos e privacidade.
- Este README descreve o código e os caminhos existentes; não declara validação de recursos que dependem de serviços externos ou execução ao vivo.

Consulte [`PREPARACAO_PUBLICACAO.md`](PREPARACAO_PUBLICACAO.md) para a relação de itens mantidos e omitidos nesta cópia.

## Avisos de terceiros

Os avisos CC0 do modelo Quaternius e das faixas Kaino acompanham os respectivos recursos. Dependências Python não são vendorizadas; consulte [`DEPENDENCIAS.md`](DEPENDENCIAS.md) para versões e instalação. O repositório ainda não define licença de redistribuição para o código ZUKO.




