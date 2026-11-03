# Dependências e configuração local

O projeto não inclui ambientes virtuais, pacotes instalados, binários de terceiros ou modelos de IA. Isso reduz o tamanho do repositório e permite instalar versões declaradas pelo próprio projeto.

## Base

- Python 3.11+ e Tkinter (biblioteca padrão, pode exigir o componente Tcl/Tk na instalação do Python).
- Godot 3.6 para a cena `npc_runtime/godot`.
- `pygame` para reprodução de áudio e ducking no mixer.
- Componentes de voz do Windows para os caminhos locais que usam System.Speech.

## Opcionais declarados

| Recurso | Arquivo | Versão declarada | Uso |
|---|---|---:|---|
| Leitura de eventos TikTok | `live_social_01/requirements-tiktok.txt` | TikTokLive 7.0.1 | Adaptador opcional; não é necessário para o simulador |
| Gemini via LiteLLM | `live_social_01/requirements-litellm.txt` | LiteLLM 1.106.2 | Geração remota opcional; configure a chave no ambiente |

O NPC independente também usa `pygame` e `psutil`; instale-os apenas se utilizar `npc_runtime`. O executável Ollama e o modelo de IA local são configurados separadamente e não são incluídos no repositório.

Instale apenas o que pretende usar. A instalação desses pacotes não conecta ao TikTok nem chama Gemini por si só.

## Variáveis de ambiente

Consulte `.env.example`. Defina os valores no ambiente antes de iniciar o processo. O código atual não carrega `.env` automaticamente.

- `GEMINI_API_KEY`: chave Gemini, apenas se o recurso for habilitado.
- `TIKTOK_UNIQUE_ID`: identificador público do canal, exigido para a fonte real.
- `TIKTOK_ROOM_ID` e `TIKTOK_ROOM_ID_SOURCE_URL`: opcionais; devem ser informados juntos e apontar para a página canônica do canal.
- `NPC_GODOT_EXE`: caminho opcional do executável Godot 3.6 no modo NPC.

Nunca registre valores reais neste repositório. Não foram incluídas credenciais na cópia.


