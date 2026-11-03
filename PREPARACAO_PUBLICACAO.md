# Preparação para publicação

Estado: repositório privado criado em 2026-11-03; cópia revisada pronta para o primeiro envio.

## Destino proposto

- Nome: `ZUKO-AI-LIVE`
- Visibilidade pretendida na primeira etapa: privado
- Conta proprietária: `rodinellesapp-glitch`.
- URL: https://github.com/rodinellesapp-glitch/ZUKO-AI-LIVE (privado).

## Conteúdo mantido

- Código Python e testes da interface e do motor principal em `live_social_01/`.
- Código, cenas Godot 3.6, materiais e configuração do NPC em `npc_runtime/`.
- Inicializadores, configuração sem segredo e guias/manual do usuário.
- Personalidade e prompts de execução usados pelo projeto.
- Cinco faixas Kaino com o aviso de licença CC0 e proveniência original preservados.
- Modelo `Character.gltf` com `License.txt` CC0 do pacote Quaternius.
- `.gitignore`, `.env.example`, `README.md` e `DEPENDENCIAS.md` novos.

## Exclusões por segurança, tamanho e licença

- `.git` do checkout JARVIS e qualquer histórico do repositório pai. O diretório de origem não tinha arquivos rastreados nem commits próprios.
- Identificador real do canal TikTok, substituído por configuração vazia que exige `TIKTOK_UNIQUE_ID` local.
- Configurações locais de limites/modelo/voz e dados de sessão.
- `.env`, credenciais, cookies e perfis de navegador, logs, telemetria, capturas e evidências.
- Backups, arquivos temporários, caches Python/Godot, manifestos locais, binários e dependências vendorizadas.
- Pacotes LiteLLM e TikTokLive instalados localmente; suas versões opcionais estão documentadas em `DEPENDENCIAS.md`.
- Faixas WAV locais e recursos de `assistente_avatar` sem documentação de redistribuição encontrada.
- Imagens de cenário Paulista e ícone do Godot: não foi encontrada licença/proveniência no material da pasta. As referências permanecem nas cenas, mas esses arquivos não estão incluídos até revisão de direitos.
- Capturas demonstrativas: as capturas existentes pertencem ao diretório de evidências e não foram reutilizadas por poderem conter dados de sessão/espectadores ou informação local.

## Varreduras e limitações

A cópia foi revisada por padrões comuns de chaves, tokens e chaves privadas em arquivos textuais. Nenhum padrão foi encontrado. Dados locais e logs foram excluídos integralmente; portanto, esta conclusão se refere ao conteúdo preparado, não a todo o computador.

As cenas Godot estão presentes, mas a cena visual principal aponta para as imagens omitidas acima. O projeto visual ainda depende da confirmação de licença ou da aprovação para substituir esses recursos por arte original de demonstração. Não publique como projeto Godot visualmente completo antes de resolver esse item.

O painel, TikTok real, Gemini/Puck, áudio e execução visual Godot não foram testados nesta preparação. Não houve transmissão TikTok, chamada Gemini, nem alteração no atalho `ZUKO.lnk`.

## Próximos passos condicionados

1. Revisar e concluir o envio privado desta cópia preparada.
2. Confirmar os direitos das imagens de cenário e do ícone, ou autorizar substitutos originais na cópia preparada.
3. Revisar a lista acima e então criar e enviar o repositório. Qualquer mudança posterior para público requer aprovação separada.

