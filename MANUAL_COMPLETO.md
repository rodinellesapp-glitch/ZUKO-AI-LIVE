# Manual completo de controles

O mesmo catálogo está na aba Ajuda, com pesquisa, F1 e botão direito. Estados de disponibilidade mudam durante a operação.

## INICIAR

INICIAR
════════════════════════════════════════

Para que serve
Inicia ou retoma o processamento da fonte selecionada. No teste local, libera a leitura local e a fila.

Quando utilizar
Durante a operação local. Situação típica: No simulador, clique para voltar a processar mensagens.

Ao clicar / selecionar
Inicia ou retoma o processamento da fonte selecionada. No teste local, libera a leitura local e a fila.

Pré-requisitos
Confira a fonte e use o simulador nesta fase.

Riscos e efeitos
Pode ativar um leitor de rede se uma fonte real tiver sido configurada. Não transmite vídeo.

Como interromper ou desfazer
PAUSAR suspende o processamento; PARAR encerra a sessão.

Exemplo
No simulador, clique para voltar a processar mensagens.

Callback real
LiveMonitor.start

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## PAUSAR

PAUSAR
════════════════════════════════════════

Para que serve
Pausa o processamento e a fila pelo comando existente do painel.

Quando utilizar
Durante a operação local. Situação típica: Faça uma pausa no recebimento enquanto organiza o painel.

Ao clicar / selecionar
Pausa o processamento e a fila pelo comando existente do painel.

Pré-requisitos
Sessão iniciada.

Riscos e efeitos
Não equivale necessariamente a interromper o áudio atual.

Como interromper ou desfazer
Use INICIAR para retomar; PAUSAR ZUKO cancela a fala atual.

Exemplo
Faça uma pausa no recebimento enquanto organiza o painel.

Callback real
LiveMonitor.pause

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## PARAR

PARAR
════════════════════════════════════════

Para que serve
Para o processamento da sessão e invalida trabalhos pendentes.

Quando utilizar
Durante a operação local. Situação típica: Pare antes de trocar de plataforma.

Ao clicar / selecionar
Para o processamento da sessão e invalida trabalhos pendentes.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Pode limpar estado de sessão e filas conforme a fonte. Não fecha o painel.

Como interromper ou desfazer
INICIAR começa ou retoma uma sessão.

Exemplo
Pare antes de trocar de plataforma.

Callback real
LiveMonitor.stop

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## ABRIR ZUKO 3D

ABRIR ZUKO 3D
════════════════════════════════════════

Para que serve
Abre o personagem Godot pelo mecanismo existente e confirma a ponte local.

Quando utilizar
Durante a operação local. Situação típica: Abra o ZUKO antes de enviar o primeiro comentário.

Ao clicar / selecionar
Abre o personagem Godot pelo mecanismo existente e confirma a ponte local.

Pré-requisitos
Godot instalado; porta do NPC livre.

Riscos e efeitos
Abre uma janela separada. Não inicia LIVE nem áudio. O controlador evita processos duplicados.

Como interromper ou desfazer
FECHAR ZUKO fecha somente a instância pertencente a este painel.

Exemplo
Abra o ZUKO antes de enviar o primeiro comentário.

Callback real
NPCPanelBridge.open

Arquivo
npc_panel_bridge.py

Disponibilidade
Conforme o estado exibido pelo painel.

## FECHAR ZUKO

FECHAR ZUKO
════════════════════════════════════════

Para que serve
Encerra somente o personagem iniciado por este painel.

Quando utilizar
Durante a operação local. Situação típica: Feche apenas o personagem ao terminar uma prévia.

Ao clicar / selecionar
Encerra somente o personagem iniciado por este painel.

Pré-requisitos
Personagem aberto.

Riscos e efeitos
O painel continua funcionando; eventos antigos não são repetidos na reabertura.

Como interromper ou desfazer
ABRIR ZUKO 3D permite reabrir.

Exemplo
Feche apenas o personagem ao terminar uma prévia.

Callback real
NPCPanelBridge.close_npc

Arquivo
npc_panel_bridge.py

Disponibilidade
Conforme o estado exibido pelo painel.

## MODO TESTE LOCAL

MODO TESTE LOCAL
════════════════════════════════════════

Para que serve
Alterna o modo de entrada local usando o callback original.

Quando utilizar
Durante a operação local. Situação típica: Ative antes de digitar uma mensagem de teste.

Ao clicar / selecionar
Alterna o modo de entrada local usando o callback original.

Pré-requisitos
Pare a leitura real antes de trocar de modo.

Riscos e efeitos
Entrar no teste não conecta TikTok. Sair dele não inicia uma LIVE.

Como interromper ou desfazer
Clique novamente para sair do teste local.

Exemplo
Ative antes de digitar uma mensagem de teste.

Callback real
LiveDashboardV2.toggle_local_mode

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## TESTAR INTERAÇÃO

TESTAR INTERAÇÃO
════════════════════════════════════════

Para que serve
Abre Voz e IA e ativa o teste local se necessário.

Quando utilizar
Durante a operação local. Situação típica: Abra e escreva Oi, ZUKO.

Ao clicar / selecionar
Abre Voz e IA e ativa o teste local se necessário.

Pré-requisitos
A troca precisa ser aceita pelo painel.

Riscos e efeitos
Apenas prepara a entrada; não envia uma mensagem automaticamente.

Como interromper ou desfazer
Apague o texto ou saia do modo de teste.

Exemplo
Abra e escreva Oi, ZUKO.

Callback real
LiveDashboardV2.open_test

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## ENVIAR

ENVIAR
════════════════════════════════════════

Para que serve
Envia o texto e autor do campo para a entrada local existente.

Quando utilizar
Durante a operação local. Situação típica: Envie Oi, ZUKO com o nome Marina.

Ao clicar / selecionar
Envia o texto e autor do campo para a entrada local existente.

Pré-requisitos
Teste local ativo; texto preenchido; ZUKO aberto para responder.

Riscos e efeitos
A IA local pode usar CPU e a voz pode tocar se Falar respostas estiver marcado.

Como interromper ou desfazer
PARAR JARVIS interrompe áudio; PAUSAR ZUKO impede novas falas.

Exemplo
Envie Oi, ZUKO com o nome Marina.

Callback real
LiveDashboard.send_local

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## FALAR PELO MICROFONE

FALAR PELO MICROFONE
════════════════════════════════════════

Para que serve
Inicia captura e reconhecimento com o adaptador existente; durante captura o botão permite parar.

Quando utilizar
Durante a operação local. Situação típica: Fale uma frase curta após selecionar seu microfone.

Ao clicar / selecionar
Inicia captura e reconhecimento com o adaptador existente; durante captura o botão permite parar.

Pré-requisitos
Microfone e dependências de reconhecimento disponíveis; teste local ativo.

Riscos e efeitos
Usa microfone. O reconhecimento legado pode enviar áudio ao serviço Google; não foi acionado na validação sem microfone.

Como interromper ou desfazer
Clique novamente para parar ou use PARAR JARVIS.

Exemplo
Fale uma frase curta após selecionar seu microfone.

Callback real
LiveDashboard.toggle_voice

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## PARAR JARVIS

PARAR JARVIS
════════════════════════════════════════

Para que serve
Cancela a fala atual pelo controle existente.

Quando utilizar
Durante a operação local. Situação típica: Interrompa uma fala longa.

Ao clicar / selecionar
Cancela a fala atual pelo controle existente.

Pré-requisitos
Fila de voz disponível.

Riscos e efeitos
Não fecha o personagem nem desliga por si só o modo automático.

Como interromper ou desfazer
Novas mensagens ainda podem gerar respostas; use PAUSAR ZUKO para impedir novas falas.

Exemplo
Interrompa uma fala longa.

Callback real
LiveMonitor.stop_jarvis

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## NOVA CONVERSA

NOVA CONVERSA
════════════════════════════════════════

Para que serve
Limpa o contexto local do autor selecionado pelo callback existente.

Quando utilizar
Durante a operação local. Situação típica: Troque de assunto sem manter o contexto anterior.

Ao clicar / selecionar
Limpa o contexto local do autor selecionado pelo callback existente.

Pré-requisitos
Autor preenchido.

Riscos e efeitos
Remove contexto de conversa; não há restauração automática.

Como interromper ou desfazer
Inicie outra conversa com nova mensagem.

Exemplo
Troque de assunto sem manter o contexto anterior.

Callback real
LiveDashboardV2.build_voice.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## RESET SESSÃO LOCAL

RESET SESSÃO LOCAL
════════════════════════════════════════

Para que serve
Reinicia o estado da sessão local pelo comando original.

Quando utilizar
Durante a operação local. Situação típica: Comece uma demonstração limpa.

Ao clicar / selecionar
Reinicia o estado da sessão local pelo comando original.

Pré-requisitos
Teste local ativo.

Riscos e efeitos
Limpa contexto e visualização local; não existe desfazer automático.

Como interromper ou desfazer
Envie novas mensagens para reconstruir o contexto.

Exemplo
Comece uma demonstração limpa.

Callback real
LiveMonitor.reset_local_session

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## SIMULAR

SIMULAR
════════════════════════════════════════

Para que serve
Envia um evento de teste identificado, usando os contratos e callbacks já existentes.

Quando utilizar
Durante a operação local. Situação típica: Escolha Presente, nome Marina e presente Rosa.

Ao clicar / selecionar
Envia um evento de teste identificado, usando os contratos e callbacks já existentes.

Pré-requisitos
Teste local ativo; nome e campos adequados ao evento.

Riscos e efeitos
Pode gerar reação e voz. Não representa presente, dinheiro ou seguidor reais.

Como interromper ou desfazer
PAUSAR ZUKO ou PARAR interrompe o processamento.

Exemplo
Escolha Presente, nome Marina e presente Rosa.

Callback real
LiveDashboardV2.simulate_event

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## FALAR AGORA

FALAR AGORA
════════════════════════════════════════

Para que serve
Pede uma intervenção manual ao apresentador existente.

Quando utilizar
Durante a operação local. Situação típica: Solicite uma intervenção quando estiver tudo pronto.

Ao clicar / selecionar
Pede uma intervenção manual ao apresentador existente.

Pré-requisitos
ZUKO aberto, fila disponível e sessão local ativa.

Riscos e efeitos
A fala aguarda o diretor e a fila; não é transmissão.

Como interromper ou desfazer
PAUSAR ZUKO ou PARAR JARVIS.

Exemplo
Solicite uma intervenção quando estiver tudo pronto.

Callback real
LiveMonitor.presenter_now

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## APROVAR

APROVAR
════════════════════════════════════════

Para que serve
Aprova uma sugestão do apresentador em modo assistido.

Quando utilizar
Durante a operação local. Situação típica: Revise a sugestão e depois autorize sua fala.

Ao clicar / selecionar
Aprova uma sugestão do apresentador em modo assistido.

Pré-requisitos
Sugestão pendente.

Riscos e efeitos
Não aprova um usuário nem uma ação de moderação. Pode enfileirar fala.

Como interromper ou desfazer
DESCARTAR serve para uma sugestão ainda pendente; interrompa áudio com PAUSAR ZUKO.

Exemplo
Revise a sugestão e depois autorize sua fala.

Callback real
LiveMonitor.presenter_approve

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## DESCARTAR

DESCARTAR
════════════════════════════════════════

Para que serve
Descarta a sugestão pendente do apresentador.

Quando utilizar
Durante a operação local. Situação típica: Recuse um assunto que não combina com o momento.

Ao clicar / selecionar
Descarta a sugestão pendente do apresentador.

Pré-requisitos
Sugestão disponível.

Riscos e efeitos
Não exclui espectadores nem mensagens da plataforma.

Como interromper ou desfazer
Solicite outra sugestão.

Exemplo
Recuse um assunto que não combina com o momento.

Callback real
LiveMonitor.presenter_discard

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## PAUSAR APRESENTADOR

PAUSAR APRESENTADOR
════════════════════════════════════════

Para que serve
Aplica o comando PAUSE existente, que também pausa o ZUKO.

Quando utilizar
Durante a operação local. Situação típica: Pause imediatamente para falar você mesmo.

Ao clicar / selecionar
Aplica o comando PAUSE existente, que também pausa o ZUKO.

Pré-requisitos
Apresentador disponível.

Riscos e efeitos
Interrompe falas do ZUKO e cancela trabalhos pendentes conforme o controlador.

Como interromper ou desfazer
RETOMAR ou RETOMAR ZUKO.

Exemplo
Pause imediatamente para falar você mesmo.

Callback real
LiveDashboardV2.build_zuko.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## RETOMAR

RETOMAR
════════════════════════════════════════

Para que serve
Aplica RESUME ao apresentador e ao ZUKO.

Quando utilizar
Durante a operação local. Situação típica: Volte a operar após sua pausa.

Ao clicar / selecionar
Aplica RESUME ao apresentador e ao ZUKO.

Pré-requisitos
Apresentador pausado.

Riscos e efeitos
Novas interações podem voltar a gerar voz; AUTO só fala se estiver ligado.

Como interromper ou desfazer
PAUSAR APRESENTADOR ou PAUSAR ZUKO.

Exemplo
Volte a operar após sua pausa.

Callback real
LiveDashboardV2.build_zuko.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## PRÓXIMO ASSUNTO

PRÓXIMO ASSUNTO
════════════════════════════════════════

Para que serve
Pede NEXT ao produtor de assuntos existente.

Quando utilizar
Durante a operação local. Situação típica: Troque de assunto quando a conversa esfriar.

Ao clicar / selecionar
Pede NEXT ao produtor de assuntos existente.

Pré-requisitos
Sessão e apresentador disponíveis.

Riscos e efeitos
Pode selecionar e enfileirar uma nova fala.

Como interromper ou desfazer
PAUSAR ZUKO cancela falas pendentes.

Exemplo
Troque de assunto quando a conversa esfriar.

Callback real
LiveDashboardV2.build_zuko.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## PUXAR ASSUNTO

PUXAR ASSUNTO
════════════════════════════════════════

Para que serve
Solicita PULL ao apresentador existente.

Quando utilizar
Durante a operação local. Situação típica: Peça um assunto leve durante a preparação.

Ao clicar / selecionar
Solicita PULL ao apresentador existente.

Pré-requisitos
ZUKO aberto e processamento ativo.

Riscos e efeitos
A seleção pode ser bloqueada por estado/fila; não inventa atividade real de público.

Como interromper ou desfazer
PAUSAR ZUKO.

Exemplo
Peça um assunto leve durante a preparação.

Callback real
LiveDashboardV2.build_zuko.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## ZUKO AUTO

ZUKO AUTO
════════════════════════════════════════

Para que serve
Liga ou desliga a apresentação espontânea configurada. Começa desligado.

Quando utilizar
Durante a operação local. Situação típica: Ligue após testar voz e interação.

Ao clicar / selecionar
Liga ou desliga a apresentação espontânea configurada. Começa desligado.

Pré-requisitos
ZUKO aberto e sessão ativa.

Riscos e efeitos
Pode falar sozinho após silêncio, respeitando os limites do arquivo de configuração.

Como interromper ou desfazer
Desligue AUTO; PAUSAR ZUKO interrompe também a fala atual.

Exemplo
Ligue após testar voz e interação.

Callback real
ZukoPresenter.set_auto

Arquivo
zuko_presenter.py

Disponibilidade
Conforme o estado exibido pelo painel.

## PAUSAR ZUKO

PAUSAR ZUKO
════════════════════════════════════════

Para que serve
Alterna a pausa do ZUKO; cancela áudio atual e novas falas pendentes.

Quando utilizar
Durante a operação local. Situação típica: Pause antes de atender uma ligação.

Ao clicar / selecionar
Alterna a pausa do ZUKO; cancela áudio atual e novas falas pendentes.

Pré-requisitos
Controlador ZUKO inicializado.

Riscos e efeitos
Uma inferência já iniciada pode terminar em segundo plano, mas sua resposta é descartada após pausa.

Como interromper ou desfazer
O mesmo botão passa a RETOMAR ZUKO.

Exemplo
Pause antes de atender uma ligação.

Callback real
ZukoPresenter.pause

Arquivo
zuko_presenter.py

Disponibilidade
Conforme o estado exibido pelo painel.

## NOVA SESSÃO LIVE

NOVA SESSÃO LIVE
════════════════════════════════════════

Para que serve
Reinicia a memória de sessão da aplicação.

Quando utilizar
Durante a operação local. Situação típica: Recomece o acompanhamento de uma sessão de teste.

Ao clicar / selecionar
Reinicia a memória de sessão da aplicação.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Limpa tópicos, contexto de audiência e memória da sessão; não abre uma transmissão.

Como interromper ou desfazer
Não há desfazer automático.

Exemplo
Recomece o acompanhamento de uma sessão de teste.

Callback real
LiveMonitor.new_live_session

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## COPIAR LOG

COPIAR LOG
════════════════════════════════════════

Para que serve
Copia os registros visíveis da aplicação para a área de transferência.

Quando utilizar
Durante a operação local. Situação típica: Cole os erros em um relatório local.

Ao clicar / selecionar
Copia os registros visíveis da aplicação para a área de transferência.

Pré-requisitos
Logs disponíveis.

Riscos e efeitos
Pode conter nomes e textos; revise antes de compartilhar.

Como interromper ou desfazer
Copie outro conteúdo para substituir a área de transferência.

Exemplo
Cole os erros em um relatório local.

Callback real
LiveDashboard.copy_log

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## EXPORTAR LOG

EXPORTAR LOG
════════════════════════════════════════

Para que serve
Copia para a área de transferência o caminho do arquivo de sessão que o logger já está gravando.

Quando utilizar
Durante a operação local. Situação típica: Cole o caminho no Explorador para localizar o registro do ensaio.

Ao clicar / selecionar
Copia para a área de transferência o caminho do arquivo de sessão que o logger já está gravando.

Pré-requisitos
Arquivo de log da cópia disponível.

Riscos e efeitos
Não abre um seletor de destino nem cria uma segunda exportação. O caminho local é copiado e registrado no log.

Como interromper ou desfazer
Copie outro conteúdo para substituir a área de transferência; o arquivo de sessão continua existente.

Exemplo
Cole o caminho no Explorador para localizar o registro do ensaio.

Callback real
LiveMonitor._export_log

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## LIMPAR VISUALIZAÇÃO

LIMPAR VISUALIZAÇÃO
════════════════════════════════════════

Para que serve
Limpa somente a lista de logs mostrada pela interface.

Quando utilizar
Durante a operação local. Situação típica: Limpe a tela antes de reproduzir um erro.

Ao clicar / selecionar
Limpa somente a lista de logs mostrada pela interface.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não apaga os arquivos de log já gravados.

Como interromper ou desfazer
Novos eventos voltam a preencher a visualização.

Exemplo
Limpe a tela antes de reproduzir um erro.

Callback real
LiveDashboard.clear_logs

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## COPIAR DIAGNÓSTICO

COPIAR DIAGNÓSTICO
════════════════════════════════════════

Para que serve
Copia o resumo técnico existente para a área de transferência.

Quando utilizar
Durante a operação local. Situação típica: Copie para comparar antes e depois de um teste.

Ao clicar / selecionar
Copia o resumo técnico existente para a área de transferência.

Pré-requisitos
Telemetria disponível.

Riscos e efeitos
Inclui dados de estado e último erro; revise antes de compartilhar.

Como interromper ou desfazer
Substitua a área de transferência copiando outro texto.

Exemplo
Copie para comparar antes e depois de um teste.

Callback real
LiveDashboard.copy_diagnostic

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## MODO DEV / MODO LIVE

MODO DEV / MODO LIVE
════════════════════════════════════════

Para que serve
Alterna a exibição dos detalhes técnicos, sem mudar a conexão da LIVE.

Quando utilizar
Durante a operação local. Situação típica: Oculte detalhes durante uma demonstração para iniciantes.

Ao clicar / selecionar
Alterna a exibição dos detalhes técnicos, sem mudar a conexão da LIVE.

Pré-requisitos
Interface aberta.

Riscos e efeitos
É apenas uma preferência de visualização.

Como interromper ou desfazer
Clique novamente para mostrar os detalhes.

Exemplo
Oculte detalhes durante uma demonstração para iniciantes.

Callback real
LiveDashboardV2.toggle_mode

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## VER FILA

VER FILA
════════════════════════════════════════

Para que serve
Abre a revisão local de itens sinalizados pela moderação.

Quando utilizar
Durante a operação local. Situação típica: Revise um comentário marcado como suspeito.

Ao clicar / selecionar
Abre a revisão local de itens sinalizados pela moderação.

Pré-requisitos
Itens sinalizados, se houver.

Riscos e efeitos
Não aplica sanções no YouTube/TikTok.

Como interromper ou desfazer
Feche a janela de revisão.

Exemplo
Revise um comentário marcado como suspeito.

Callback real
LiveDashboardV2.show_moderation_queue

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## SIMULAR TRIAGEM

SIMULAR TRIAGEM
════════════════════════════════════════

Para que serve
Executa o cenário de moderação selecionado usando o simulador existente.

Quando utilizar
Durante a operação local. Situação típica: Escolha SPAM e confira o resultado.

Ao clicar / selecionar
Executa o cenário de moderação selecionado usando o simulador existente.

Pré-requisitos
Escolha um cenário.

Riscos e efeitos
Pode adicionar itens de teste à fila; nenhuma ação externa é executada.

Como interromper ou desfazer
Limpe a sessão ou ignore o item na revisão local.

Exemplo
Escolha SPAM e confira o resultado.

Callback real
LiveDashboardV2.build_events.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## SIMULAR DIRETOR

SIMULAR DIRETOR
════════════════════════════════════════

Para que serve
Executa a simulação local existente do diretor e registra sua ordem no log.

Quando utilizar
Durante a operação local. Situação típica: Confira a ordem de prioridade simulada.

Ao clicar / selecionar
Executa a simulação local existente do diretor e registra sua ordem no log.

Pré-requisitos
Módulo de simulação copiado.

Riscos e efeitos
É um teste local, não controla a plataforma real.

Como interromper ou desfazer
Consulte ou limpe a visualização de logs.

Exemplo
Confira a ordem de prioridade simulada.

Callback real
LiveMonitor.simulate_director

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado exibido pelo painel.

## ZIG LIVE

ZIG LIVE
════════════════════════════════════════

Para que serve
Mantém o launcher legado do visualizador ZIG copiado.

Quando utilizar
Durante a operação local. Situação típica: Consulte o estado do módulo legado sem confundi-lo com ZUKO.

Ao clicar / selecionar
Mantém o launcher legado do visualizador ZIG copiado.

Pré-requisitos
Recursos ZIG e serviços locais desse módulo disponíveis.

Riscos e efeitos
Não faz parte dos testes desta fase. Pode iniciar navegador/processos locais; a ponte automática permanece suspensa como na versão de origem.

Como interromper ou desfazer
Feche o visualizador separadamente.

Exemplo
Consulte o estado do módulo legado sem confundi-lo com ZUKO.

Callback real
ZigViewerButton.open

Arquivo
live_zig_viewer.py

Disponibilidade
Conforme o estado exibido pelo painel.

## CONFIGURAÇÕES ZIG

CONFIGURAÇÕES ZIG
════════════════════════════════════════

Para que serve
Abre o painel legado de ajustes ZIG.

Quando utilizar
Durante a operação local. Situação típica: Identifique opções do visualizador ZIG legado.

Ao clicar / selecionar
Abre o painel legado de ajustes ZIG.

Pré-requisitos
Módulo ZIG copiado e ponte compatível, se necessária.

Riscos e efeitos
Não controla o ZUKO; ajustes dependem do módulo legado e não foram exercitados nesta fase.

Como interromper ou desfazer
Feche a janela; consulte a documentação do módulo antes de alterar ajustes.

Exemplo
Identifique opções do visualizador ZIG legado.

Callback real
SettingsPanel.open

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## TESTAR VOZ MARIA

TESTAR VOZ MARIA
════════════════════════════════════════

Para que serve
Enfileira o teste de voz existente, reproduzido pela Microsoft Maria na cópia ZUKO.

Quando utilizar
Durante a operação local. Situação típica: Teste antes de ativar AUTO.

Ao clicar / selecionar
Enfileira o teste de voz existente, reproduzido pela Microsoft Maria na cópia ZUKO.

Pré-requisitos
Voz pt-BR instalada e dispositivo de áudio funcionando.

Riscos e efeitos
Produz áudio local; não chama Edge TTS.

Como interromper ou desfazer
PARAR JARVIS ou PAUSAR ZUKO.

Exemplo
Teste antes de ativar AUTO.

Callback real
LiveDashboardV2.test_voice

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## CONFIGURAÇÕES DE VOZ

CONFIGURAÇÕES DE VOZ
════════════════════════════════════════

Para que serve
Mostra os parâmetros reais da voz ZUKO em uma janela somente de leitura.

Quando utilizar
Durante a operação local. Situação típica: Confira Microsoft Maria e a velocidade Windows configurada.

Ao clicar / selecionar
Mostra os parâmetros reais da voz ZUKO em uma janela somente de leitura.

Pré-requisitos
Arquivo zuko_personality.json disponível.

Riscos e efeitos
Não troca voz, pitch nem mecanismo de síntese.

Como interromper ou desfazer
Feche a janela informativa.

Exemplo
Confira Microsoft Maria e a velocidade Windows configurada.

Callback real
LiveDashboardV2.voice_settings

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## AJUDA DO CONTROLE / F1

AJUDA DO CONTROLE / F1
════════════════════════════════════════

Para que serve
Abre a explicação do controle na aba Ajuda.

Quando utilizar
Durante a operação local. Situação típica: Selecione ABRIR ZUKO e pressione F1.

Ao clicar / selecionar
Abre a explicação do controle na aba Ajuda.

Pré-requisitos
Foque um controle ou use o botão de ajuda.

Riscos e efeitos
Nenhuma ação operacional é executada.

Como interromper ou desfazer
Volte à aba anterior.

Exemplo
Selecione ABRIR ZUKO e pressione F1.

Callback real
LiveDashboardV2._build.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado exibido pelo painel.

## MARCAR OK

MARCAR OK
════════════════════════════════════════

Para que serve
Marca o item selecionado como OK na revisão local.

Quando utilizar
Durante a operação local. Situação típica: Conclua a revisão de um item de teste seguro.

Ao clicar / selecionar
Marca o item selecionado como OK na revisão local.

Pré-requisitos
Selecione um item da fila de moderação.

Riscos e efeitos
Não publica nem desbloqueia usuário na plataforma real.

Como interromper ou desfazer
Consulte novamente a fila; sem desfazer garantido.

Exemplo
Conclua a revisão de um item de teste seguro.

Disponibilidade
Conforme o estado exibido pelo painel.

## IGNORAR

IGNORAR
════════════════════════════════════════

Para que serve
Marca o item selecionado para ignorar na revisão local.

Quando utilizar
Durante a operação local. Situação típica: Ignore um sinal de spam simulado.

Ao clicar / selecionar
Marca o item selecionado para ignorar na revisão local.

Pré-requisitos
Selecione um item da fila.

Riscos e efeitos
Não bane nem exclui usuários reais.

Como interromper ou desfazer
A decisão local pode não ter desfazer.

Exemplo
Ignore um sinal de spam simulado.

Disponibilidade
Conforme o estado exibido pelo painel.

## MANTER EM REVISÃO

MANTER EM REVISÃO
════════════════════════════════════════

Para que serve
Mantém o item na fila local para nova análise.

Quando utilizar
Durante a operação local. Situação típica: Deixe um trecho ambíguo para depois.

Ao clicar / selecionar
Mantém o item na fila local para nova análise.

Pré-requisitos
Item selecionado.

Riscos e efeitos
Não toma decisão externa.

Como interromper ou desfazer
Abra a fila novamente quando puder revisar.

Exemplo
Deixe um trecho ambíguo para depois.

Disponibilidade
Conforme o estado exibido pelo painel.

## Modo legado de IA

Modo legado de IA
════════════════════════════════════════

Para que serve
MISTO e GEMINI+ mantêm os callbacks originais de redação. O ZUKO desta cópia usa o motor local; estes seletores não trocam seu motor. Gemini em caminhos legados pode gerar cobrança e não é chamado nos testes.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
MISTO e GEMINI+ mantêm os callbacks originais de redação. O ZUKO desta cópia usa o motor local; estes seletores não trocam seu motor. Gemini em caminhos legados pode gerar cobrança e não é chamado nos testes.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
LiveMonitor.set_writer_mode

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado real do controle.

## Plataforma

Plataforma
════════════════════════════════════════

Para que serve
YouTube/TikTok seleciona a fonte pelo callback existente. A troca é bloqueada enquanto há leitura ou teste local ativo. Não conecte fontes reais nesta fase; mudar a seleção não transmite vídeo.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
YouTube/TikTok seleciona a fonte pelo callback existente. A troca é bloqueada enquanto há leitura ou teste local ativo. Não conecte fontes reais nesta fase; mudar a seleção não transmite vídeo.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
LiveMonitor.set_platform

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado real do controle.

## Modo do apresentador

Modo do apresentador
════════════════════════════════════════

Para que serve
OFF deixa AUTO desligado. ASSISTIDO usa sugestões/aprovação. AUTO é sincronizado com ZUKO AUTO. Respeita fila e pausa.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
OFF deixa AUTO desligado. ASSISTIDO usa sugestões/aprovação. AUTO é sincronizado com ZUKO AUTO. Respeita fila e pausa.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
LiveMonitor.set_presenter_mode

Arquivo
live_monitor.py

Disponibilidade
Conforme o estado real do controle.

## Filtro de logs

Filtro de logs
════════════════════════════════════════

Para que serve
Filtra apenas a visualização por componente; não altera o processamento.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
Filtra apenas a visualização por componente; não altera o processamento.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
LiveDashboardV2.build_diagnostics.<locals>.<lambda>

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado real do controle.

## Cenário de triagem

Cenário de triagem
════════════════════════════════════════

Para que serve
Escolhe a simulação de moderação usada por SIMULAR TRIAGEM.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
Escolhe a simulação de moderação usada por SIMULAR TRIAGEM.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
seleção local; consumida pelo controle associado

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado real do controle.

## Tipo de evento simulado

Tipo de evento simulado
════════════════════════════════════════

Para que serve
Escolha comentário, presente, seguidor ou um evento legado. Os campos explicam quais valores são utilizados. Nenhum evento é prova de atividade real.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
Escolha comentário, presente, seguidor ou um evento legado. Os campos explicam quais valores são utilizados. Nenhum evento é prova de atividade real.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
LiveDashboardV2.select_event_type

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado real do controle.

## Microfone

Microfone
════════════════════════════════════════

Para que serve
Selecione um dispositivo para o adaptador de captura existente. O microfone não é ativado ao selecionar.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
Selecione um dispositivo para o adaptador de captura existente. O microfone não é ativado ao selecionar.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
seleção local; consumida pelo controle associado

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado real do controle.

## Voz em uso

Voz em uso
════════════════════════════════════════

Para que serve
Microsoft Maria é a voz fixa funcional do ZUKO. A seleção é informativa: não há troca de motor nesta reorganização.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
Microsoft Maria é a voz fixa funcional do ZUKO. A seleção é informativa: não há troca de motor nesta reorganização.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
seleção local; consumida pelo controle associado

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado real do controle.

## FALAR RESPOSTAS

FALAR RESPOSTAS
════════════════════════════════════════

Para que serve
Envia a preferência para a entrada local legada. No controlador ZUKO atual, a resposta é criada com voz ativada; desmarcar não silencia esse caminho. Para interromper ou impedir fala do ZUKO, use PAUSAR ZUKO. O mecanismo existente não foi alterado nesta reorganização.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
Envia a preferência para a entrada local legada. No controlador ZUKO atual, a resposta é criada com voz ativada; desmarcar não silencia esse caminho. Para interromper ou impedir fala do ZUKO, use PAUSAR ZUKO. O mecanismo existente não foi alterado nesta reorganização.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
variável consumida por send_local/start_local_voice

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado real do controle.

## ENVIAR AUTOMATICAMENTE

ENVIAR AUTOMATICAMENTE
════════════════════════════════════════

Para que serve
Após reconhecer uma fala do microfone, envia o texto automaticamente se marcado; desmarcado deixa o texto no campo para revisão.

Quando utilizar
Antes de executar a ação associada.

Ao clicar / selecionar
Após reconhecer uma fala do microfone, envia o texto automaticamente se marcado; desmarcado deixa o texto no campo para revisão.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Não aciona uma transmissão por si só.

Como interromper ou desfazer
Restaure a seleção anterior quando o painel permitir.

Exemplo
Confira a seleção antes de um teste local.

Callback real
variável consumida por send_local/start_local_voice

Arquivo
live_dashboard_v2.py

Disponibilidade
Conforme o estado real do controle.

## Primeiros passos

Primeiros passos
════════════════════════════════════════

Para que serve
1. Abra ABRIR_ZUKO_V2.cmd.
2. Na aba Início, confira personagem, IA, voz e fonte.
3. Clique ABRIR ZUKO 3D.
4. Use TESTAR VOZ MARIA.
5. Abra TESTAR INTERAÇÃO e envie Oi, ZUKO.
6. Consulte F1 sobre qualquer controle antes de ativar AUTO. Não inicie uma transmissão nesta fase.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.

## Como abrir e fechar ZUKO

Como abrir e fechar ZUKO
════════════════════════════════════════

Para que serve
Na aba Início ou ZUKO, clique ABRIR ZUKO 3D. Aguarde Aberto e a confirmação da ponte. A janela Godot é separada. FECHAR ZUKO fecha apenas essa instância. Se outra versão ocupar a porta, encerre manualmente o personagem dessa versão; o painel não toma o controle de processos externos.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.

## Como testar voz e microfone

Como testar voz e microfone
════════════════════════════════════════

Para que serve
TESTAR VOZ MARIA enfileira áudio local; confira o volume do Windows. Falando indica reprodução detectada pelo pygame. Instalada não garante que os alto-falantes estejam audíveis. PARAR JARVIS cancela a fala. FALAR PELO MICROFONE usa outro caminho: captura e reconhecimento legado podem depender de serviço externo. Se não houver dispositivo, não inventamos uma causa; consulte o erro em Diagnóstico.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.

## Como simular comentário, presente e seguidor

Como simular comentário, presente e seguidor
════════════════════════════════════════

Para que serve
Ative o teste local. Em Eventos e Live, escolha CHAT e preencha nome/comentário. SIMULAR usa a entrada local existente. Para GIFT, digite o nome do presente; para FOLLOW, apenas o espectador. Os eventos são sintéticos, nunca prova de atividade real. A fila pode descartar entradas repetidas, obsoletas ou bloqueadas pela moderação.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.

## Como ativar AUTO e pausar

Como ativar AUTO e pausar
════════════════════════════════════════

Para que serve
Abra o personagem, teste voz/interação e clique ZUKO AUTO. Ele começa desligado em cada abertura. A saudação e os assuntos após silêncio passam pelo diretor e pela mesma fila de voz. PAUSAR ZUKO cancela áudio atual e falas pendentes. O botão passa a RETOMAR ZUKO. Desligar AUTO impede novas intervenções automáticas; não substitui a pausa do áudio atual.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.

## Como interpretar indicadores

Como interpretar indicadores
════════════════════════════════════════

Para que serve
Aberto: processo próprio e ponte identificada. AUTO ligado: apresentação espontânea habilitada. Falando: áudio real em reprodução. Reagindo: estimativa local de animação. Última animação solicitada não é confirmação de execução, pois o protocolo não retorna telemetria. Simulador nunca significa TikTok real conectado. IA indisponível agora pode ser ativada automaticamente ao responder; a primeira resposta pode demorar.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.

## Como identificar falhas

Como identificar falhas
════════════════════════════════════════

Para que serve
Confira o estado na aba Início e os registros em Diagnóstico. Porta ocupada impede abertura do personagem; não encerre processos desconhecidos. Se a voz estiver instalada mas não audível, confira o dispositivo/volume manualmente. Se o serviço local de IA não responder, a aplicação pode usar fallback rotulado. Só apresentamos causa confirmada pelo código; os indicadores legados podem não representar o motor do ZUKO.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.

## Como encerrar com segurança

Como encerrar com segurança
════════════════════════════════════════

Para que serve
Desligue ZUKO AUTO. Use PAUSAR ZUKO para cancelar áudio e pendências. Clique PARAR para encerrar o processamento da sessão. FECHAR ZUKO fecha somente o personagem. Feche a janela do painel para encerrar seus próprios processos. NEXUS, ZIG e os projetos anteriores não são substituídos por esta versão.

Quando utilizar
Durante a preparação e operação local.

Ao clicar / selecionar
Consulta somente; não executa comandos.

Pré-requisitos
Painel aberto.

Riscos e efeitos
Nenhuma ação é executada ao ler o guia.

Como interromper ou desfazer
Volte à aba desejada.

Exemplo
Siga a sequência antes de preparar uma captura no OBS.

Arquivo
v2_help.py

Disponibilidade
Sempre disponível.
