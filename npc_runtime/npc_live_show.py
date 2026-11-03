"""Apresentador independente. Simulação local por padrão; nenhuma transmissão."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen

from show_ai import PresenterAI
from show_sources import simulated, real_source
from show_tcp import ShowClient
from show_voice import ShowVoice

ROOT = Path(__file__).resolve().parent


class Trace:
    def __init__(self, path=None):
        self.path = path or ROOT / 'runtime/events.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, marker, **data):
        record = {'at':time.time(), 'monotonic':time.monotonic(), 'marker':marker, **data}
        print(marker, json.dumps(data, ensure_ascii=False), flush=True)
        if self.path.exists() and self.path.stat().st_size > 1_000_000:
            self.path.replace(self.path.with_suffix('.previous.jsonl'))
        with self.path.open('a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')


class Runtime:
    def __init__(self):
        self.processes = []
        self.logs = []
        (ROOT / 'runtime').mkdir(exist_ok=True)

    def _spawn(self, args, env, name):
        log = (ROOT / 'runtime' / (name + '.log')).open('w', encoding='utf-8')
        self.logs.append(log)
        process = subprocess.Popen(args, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(process)
        return process

    def start_godot(self, port):
        probe = socket.socket()
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as error:
            raise RuntimeError(f'Porta {port} ocupada. Nenhuma instância existente será controlada. Use --port 18765 ou encerre manualmente o outro teste.') from error
        finally:
            probe.close()
        exe = os.environ.get('NPC_GODOT_EXE') or str(Path.home() / 'OneDrive/Desktop/Godot_v3.6-stable_win64.exe')
        if not Path(exe).is_file():
            raise RuntimeError('Configure NPC_GODOT_EXE para o executável existente do Godot 3.6.')
        env = dict(os.environ, NPC_SHOW_PORT=str(port))
        self._spawn([exe, '--path', str(ROOT / 'godot')], env, 'godot')

    def start_local_ai(self, config):
        base = config['url'].split('/api/')[0]
        def ready():
            try:
                with urlopen(base + '/api/tags', timeout=1) as response:
                    return config['model'] in [item['name'] for item in json.load(response).get('models', [])]
            except (OSError, ValueError):
                return False
        if ready():
            return
        if base != 'http://127.0.0.1:11435':
            raise RuntimeError('Inicialização automática permitida somente para a IA local isolada em 11435.')
        exe = shutil.which('ollama') or str(Path.home() / 'AppData/Local/Programs/Ollama/ollama.exe')
        if not Path(exe).is_file():
            raise RuntimeError('Ollama já instalado não encontrado; nenhum download será feito.')
        env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11435', OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1')
        self._spawn([exe, 'serve'], env, 'ollama')
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if ready():
                return
            time.sleep(0.2)
        raise RuntimeError('Modelo local configurado indisponível. Nenhum modelo foi baixado.')

    def close(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        for log in self.logs:
            log.close()


class Presenter:
    def __init__(self, config, client, ai, trace, record=False):
        self.config, self.client, self.ai, self.trace, self.record = config, client, ai, trace, record
        self.counter = 0

    def process(self, event):
        # Ações vêm do tipo normalizado do evento, jamais do texto/modelo.
        mapping = {'CHAT_MESSAGE':'comment', 'GIFT_EVENT':'gift', 'FOLLOW':'follow', 'VIEWER_JOIN':'follow'}
        command = mapping.get(event.event_type)
        if command is None:
            return
        if not self.client.connected:
            self.client.connect()
        self.counter += 1
        self.trace('EVENT', kind=event.event_type, simulation=event.metadata.get('simulation', False))
        response, provider = self.ai.response(event)
        self.trace('RESPONSE', provider=provider, text=response, ai_calls=self.ai.calls)
        if command in ('gift', 'follow'):
            self.client.send_event(command, user=event.spoken_name or event.author_name or '', gift=event.gift_type or '')
            self.trace('REACTION_SENT', event=command)
            time.sleep(0.65 if command == 'gift' else 2.2)
        suffix = 'wav' if self.config['voice'].get('engine') == 'windows' else 'mp3'
        audio = ROOT / 'evidence' / f'voice_{self.counter:02}.{suffix}' if self.record else None
        if audio:
            audio.parent.mkdir(exist_ok=True)
        voice = ShowVoice(self.client, self.config['voice'], self.trace, audio)
        voice.speak(response)
        self.trace('EVENT_FINISHED', kind=event.event_type, provider=provider)
        time.sleep(0.35)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--provider', choices=['local','rules','gemini'], default='local')
    parser.add_argument('--allow-paid-api', action='store_true', help='Autorização manual explícita para Gemini/Vertex; pode gerar cobrança.')
    parser.add_argument('--start-godot', action='store_true')
    parser.add_argument('--start-local-ai', action='store_true', help='Inicia somente Ollama existente, sem baixar modelos.')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--record-evidence', action='store_true')
    parser.add_argument('--event', choices=['comment','gift','follow','join'])
    parser.add_argument('--user', default='Teste')
    parser.add_argument('--text', default='Oi NPC!')
    parser.add_argument('--source', choices=['simulator','tiktok'], default='simulator')
    parser.add_argument('--channel')
    args = parser.parse_args()
    if args.source == 'tiktok' and not args.channel:
        parser.error('Modo TikTok requer --channel explícito; nenhum canal é iniciado por padrão.')
    runtime, client, source = Runtime(), ShowClient(args.port), None
    trace = Trace()
    config = json.loads((ROOT / 'personality.json').read_text(encoding='utf-8'))
    try:
        ai = PresenterAI(config, args.provider, args.allow_paid_api)
        if args.start_godot:
            runtime.start_godot(args.port)
        deadline = time.monotonic() + (25 if args.start_godot else 3)
        while True:
            try:
                client.connect()
                break
            except ConnectionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        if args.start_local_ai and args.provider == 'local':
            runtime.start_local_ai(config['local_ai'])
        presenter = Presenter(config, client, ai, trace, args.record_evidence)
        if args.source == 'tiktok':
            source, adapter = real_source(args.channel)
            source.start()
            print('Somente leitura da LIVE; nenhuma transmissão será iniciada. Ctrl+C encerra.')
            while True:
                event = adapter.read_event()
                if event:
                    presenter.process(event)
                else:
                    time.sleep(0.1)
        elif args.demo:
            for kind, user in [('CHAT_MESSAGE','Teste'), ('GIFT_EVENT','Marina'), ('FOLLOW','Carlos')]:
                presenter.process(simulated(kind, user))
        elif args.event:
            kind = {'comment':'CHAT_MESSAGE','gift':'GIFT_EVENT','follow':'FOLLOW','join':'VIEWER_JOIN'}[args.event]
            presenter.process(simulated(kind, args.user, args.text))
        else:
            while True:
                option = input('\n1 Comentário | 2 Presente | 3 Seguidor | 4 Saudação | 0 Sair: ').strip()
                if option == '0':
                    break
                if option not in ('1','2','3','4'):
                    continue
                user = input('Nome: ').strip() or 'Visitante'
                text = input('Comentário: ').strip() if option == '1' else ''
                kind = {'1':'CHAT_MESSAGE','2':'GIFT_EVENT','3':'FOLLOW','4':'VIEWER_JOIN'}[option]
                try:
                    presenter.process(simulated(kind, user, text))
                except (ConnectionError, OSError, RuntimeError) as error:
                    client.close()
                    trace('EVENT_ERROR', reason=type(error).__name__)
                    print('Reconecte/inicie a cópia do Godot e escolha outro evento para tentar novamente.')
    except KeyboardInterrupt:
        print('\nEncerrando somente a nova plataforma.')
    except Exception as error:
        trace('SHOW_ERROR', reason=type(error).__name__)
        if isinstance(error, (RuntimeError, ConnectionError, ValueError)) and 'http' not in str(error).lower():
            print(str(error))
        return 1
    finally:
        if source:
            source.stop()
        if client.connected:
            try:
                client.send_event('idle')
            except ConnectionError:
                pass
        client.close()
        runtime.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
