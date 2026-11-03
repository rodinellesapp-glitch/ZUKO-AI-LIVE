# Guia do iniciante — ZUKO Live Social 2.0

## 1. Abrir o painel certo

Na pasta `C:\JARVIS Web\ZUKO_LIVE_SOCIAL_V2`, dê dois cliques em **ABRIR_ZUKO_V2.cmd**.

O atalho ZUKO da Área de Trabalho continua abrindo a versão anterior: ele não foi alterado. O título da nova janela deve ser **ZUKO LIVE SOCIAL 2.0**.

## 2. Conferir os estados em Início

- **Personagem fechado:** clique ABRIR ZUKO 3D e aguarde a confirmação.
- **IA indisponível agora:** o serviço local pode estar desligado; o mecanismo existente tenta iniciá-lo na primeira resposta. A primeira mensagem pode demorar. Não clique repetidamente em Enviar.
- **Maria instalada:** a voz foi localizada, mas você ainda precisa testar se o áudio sai no dispositivo correto.
- **Simulador:** você está em teste. Isso não significa que uma LIVE TikTok esteja conectada.

O botão para abrir o ZUKO permanece no cabeçalho em todas as abas. Não abra duas versões do personagem ao mesmo tempo. Se a porta estiver ocupada, feche manualmente o personagem da versão anterior; a V2 não assume o controle de processos externos.

## 3. Testar a voz

Clique **TESTAR VOZ MARIA**. Confira o volume e o dispositivo de saída do Windows. O indicador Falando significa que o reprodutor iniciou o áudio; não garante que seus alto-falantes estejam audíveis.

**PARAR JARVIS** interrompe a fala atual. **PAUSAR ZUKO** interrompe a fala e impede novas falas até você retomar. A seleção Microsoft Maria é informativa: não existem outras vozes funcionais do ZUKO para escolher nesta reorganização.

## 4. Conversar com o ZUKO

1. Clique **TESTAR INTERAÇÃO** na aba Início.
2. Em Voz e IA, preencha o nome do espectador.
3. Digite uma mensagem curta, como “Oi, ZUKO! Como está o seu café?”.
4. Clique **ENVIAR** ou pressione Enter. Shift+Enter cria outra linha.
5. Veja a última resposta na própria aba e a conversa recente em Início.

A opção **Falar respostas** foi preservada como controle legado, mas o controlador ZUKO atual não a aplica à resposta que ele cria. Para silenciar com segurança, use **PAUSAR ZUKO**. Essa limitação já existia e o motor não foi alterado nesta fase.

O botão do microfone utiliza o reconhecimento legado e pode depender de serviço externo. Não é necessário usá-lo para testar mensagens digitadas. Ele foi validado com mock, sem capturar seu microfone nesta fase.

## 5. Simular eventos

Abra **Eventos e Live**, mantendo o modo de teste local ativo.

- **Comentário:** preencha nome e comentário; SIMULAR usa a mesma entrada local.
- **Presente:** preencha nome e nome do presente, como Rosa. A quantidade é opcional.
- **Novo seguidor:** preencha o nome. Os outros campos não são usados.
- **Super Chat:** o valor é apenas um dado simulado, sem pagamento.

Clique **SIMULAR** uma vez e confira a fila, os logs e a janela do personagem. Nenhuma dessas ações corresponde a um evento real do público.

## 6. Usar apresentação automática

Na aba ZUKO, **ZUKO AUTO** começa desligado. Teste voz e interação antes de ligá-lo.

AUTO permite saudação e intervenções após silêncio, com os limites existentes. Abrir o personagem não liga AUTO. Desligar AUTO impede novas intervenções espontâneas; use **PAUSAR ZUKO** para interromper também a fala atual. O mesmo botão permite retomar.

Os comandos INICIAR, PAUSAR e PARAR mantêm seus comportamentos anteriores. PAUSAR a sessão não é o mesmo que cancelar o áudio atual. Não escolha uma fonte real e clique INICIAR nesta fase.

## 7. Pedir ajuda

- Passe o mouse sobre um botão para uma explicação curta.
- Foque o controle e pressione **F1**, ou clique com o botão direito.
- Use **Ajuda e instruções** e pesquise por nome ou assunto, como “pausar”, “voz” ou “presente”. A busca aceita palavras sem acentos.

Cada controle tem finalidade, situação de uso, efeito, pré-requisitos, riscos, forma de interromper e exemplo. O catálogo também está em MANUAL_COMPLETO.md.

## 8. Entender moderação e diagnóstico

**VER FILA** abre a revisão local de mensagens sinalizadas. MARCAR OK, IGNORAR e MANTER EM REVISÃO não aplicam sanções no TikTok ou YouTube.

APROVAR e DESCARTAR tratam sugestões do apresentador; não são decisões de moderação.

Em Diagnóstico, os indicadores legados continuam disponíveis, mas podem não representar a IA ou a voz atuais do ZUKO. Os estados específicos do ZUKO são mostrados separadamente. EXPORTAR LOG copia o caminho do arquivo de sessão já gravado; não abre uma janela para escolher um destino.

## 9. Encerrar

1. Desligue AUTO.
2. Use PAUSAR ZUKO para cancelar fala e pendências.
3. Clique PARAR para encerrar o processamento da sessão.
4. Clique FECHAR ZUKO para fechar apenas o personagem.
5. Feche o painel quando terminar.

O painel não transmite vídeo. Preparação no OBS e testes com TikTok real permanecem fora desta fase.
