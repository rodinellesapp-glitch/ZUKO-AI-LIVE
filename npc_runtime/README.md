# NPC LIVE SHOW

Plataforma independente: eventos normalizados → personalidade → IA local → voz → TCP JSONL → Godot 3.6/GLES2. Não importa o monitor original, Tools ou ZIG. Não transmite vídeo.

## Iniciar

Na pasta deste projeto, execute:

```powershell
python -B npc_live_show.py --start-godot --start-local-ai --port 18765
```

A porta padrão continua 8765. Use 18765 enquanto o NPC anterior estiver aberto. O inicializador recusa uma porta ocupada; o cliente exige a identificação NPC_LIVE_SHOW antes de enviar comandos. `iniciar_npc_live_show.cmd` utiliza a porta padrão.

Use o menu para comentário, presente, seguidor e saudação. Digite 0 para sair. A aplicação encerra somente os processos que iniciou. Para demonstração sequencial acrescente `--demo`. Para respostas de regras sem IA, use `--provider rules` e omita `--start-local-ai`.

Requer Python 3.11, pygame, Ollama e o modelo local configurado pelo operador. O código não baixa modelos. Defina NPC_GODOT_EXE para o executável Godot 3.6.

## Personalidade e voz

Edite personality.json para estilo, frases e voz. Comentários usam IA; presentes e seguidores usam frases rotativas para reduzir consumo. Comentários são dados, não comandos. Eventos determinam os gestos, sem ferramentas acessíveis à IA.

A voz padrão é Microsoft Maria Desktop (pt-BR), via System.Speech do Windows. O áudio é reproduzido pelo pygame reutilizado de voz.py. Edge TTS retornou HTTP 403 no teste; sua opção permanece disponível, mas não está validada neste ambiente. A voz Windows não aplica o pitch do Edge.

O comando talk mantém Wave durante a reprodução e volta a Idle ao terminar. Presentes acionam Jump; seguidores acionam Yes antes da fala. Não há sincronização labial.

Gemini Vertex está desativado por padrão. Exige escolha manual `--provider gemini --allow-paid-api`; pode gerar cobrança e não foi chamado neste trabalho. Nenhuma credencial foi copiada.

## TikTok e transmissão

O conector existente foi copiado, com importações locais. Para leitura real, há a opção explícita `--source tiktok --channel SEU_CANAL`. Não a execute junto com outro leitor do mesmo canal. A conexão real não foi testada: presentes/seguidores reais ainda precisam de validação. O modo padrão usa o simulador existente.

OBS está instalado, mas não foi iniciado. Próximo passo: revisar o visual e capturar manualmente a janela NPC_LIVE_SHOW e seu áudio no OBS, em prévia local. Depois validar o leitor TikTok com autorização. Este projeto não inicia transmissão nem faz deploy.

## Arquivos

- npc_live_show.py: inicialização, menu e orquestração.
- personality.json, show_ai.py: configuração e respostas.
- show_sources.py: simulador e conector TikTok reutilizados.
- show_voice.py: reprodução e gestos durante a voz.
- npc_client.py, show_tcp.py: cliente e identificação da cópia.
- Adaptadores e proteção de saída permanecem no código-fonte próprio do projeto; dependências de terceiros não são vendorizadas.
- godot/: cópia do NPC. Apenas LocalTcpServer.gd e o nome da aplicação em project.godot foram alterados. Modelo, Main.gd, Main.tscn, câmera e animações preservados.

As limitações e o estado de validação estão documentados no README principal. Cópia independente preserva os originais e permite rollback encerrando esta aplicação e removendo somente sua nova pasta.

