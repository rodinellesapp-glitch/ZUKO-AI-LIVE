"""Cliente TCP local do NPC. Usa somente a biblioteca padrão do Python."""

import argparse
import json
import socket

HOST = "127.0.0.1"
PORT = 8765
MAX_MESSAGE_BYTES = 4096
EVENTS = ("idle", "talk", "dance", "gift", "comment", "follow")
ANIMATIONS = (
    "Death", "Duck", "HitReact", "Idle", "Idle_Gun", "Idle_Shoot",
    "Jump", "Jump_Idle", "Jump_Land", "No", "Punch", "Run",
    "Run_Gun", "Run_Shoot", "Walk", "Walk_Gun", "Wave", "Yes",
)
AUTO_ANIMATIONS = ("Idle", "Jump", "No", "Walk", "WalkWave", "Wave", "Yes")
WALK_COMBO_ANIMATIONS = ("WalkWave", "WalkYes", "WalkNo")
SPEECH_ANIMATIONS = ("Idle", "Jump", "No", "Wave", "Yes")
CONTROLS = ("stop", "idle", "pause", "resume")


class NPCClient:
    def __init__(self, port=PORT, timeout=3.0):
        self.port = port
        self.timeout = timeout
        self._socket = None

    @property
    def connected(self):
        return self._socket is not None

    def connect(self):
        self.close()
        try:
            self._socket = socket.create_connection((HOST, self.port), self.timeout)
            self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            self.close()
            raise ConnectionError(
                f"Não foi possível conectar a {HOST}:{self.port}. "
                "Inicie o projeto no Godot com F5 e tente novamente."
            ) from exc
        return self

    def _send_payload(self, payload):
        message = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(message) > MAX_MESSAGE_BYTES:
            raise ValueError("Mensagem excede 4096 bytes.")
        if self._socket is None:
            raise ConnectionError("Cliente desconectado. Conecte novamente para enviar.")
        try:
            self._socket.sendall(message + b"\n")
        except OSError as exc:
            self.close()
            raise ConnectionError("Conexão perdida. Reconecte e tente novamente.") from exc

    def send_event(self, event, **metadata):
        payload = dict(event) if isinstance(event, dict) else {"event": event}
        payload.update(metadata)
        if payload.get("event") not in EVENTS:
            raise ValueError("Evento desconhecido.")
        for field in ("user", "gift", "text"):
            if field in payload and not isinstance(payload[field], str):
                raise ValueError(f"O campo {field} deve ser texto.")
        if "gesture" in payload and (payload.get("event") != "talk" or payload["gesture"] not in SPEECH_ANIMATIONS):
            raise ValueError("Gesto de fala desconhecido ou fora de talk.")
        if "speaking" in payload and (payload.get("event") != "talk" or type(payload["speaking"]) is not bool):
            raise ValueError("O campo speaking deve ser booleano em talk.")
        self._send_payload(payload)

    def send_animation(self, animation, repeat=False):
        if animation not in ANIMATIONS:
            raise ValueError("Animação desconhecida.")
        if type(repeat) is not bool:
            raise ValueError("A repetição deve ser booleana.")
        self._send_payload({"command": "animate", "animation": animation, "repeat": repeat})

    def send_control(self, command):
        if command not in CONTROLS:
            raise ValueError("Controle desconhecido.")
        self._send_payload({"command": command})

    def send_presentation(self, **options):
        if set(options) - {'walking', 'speed', 'live', 'resolution'}:
            raise ValueError('Opção de apresentação desconhecida.')
        for key in ('walking', 'live'):
            if key in options and type(options[key]) is not bool:
                raise ValueError('Estado deve ser booleano.')
        if 'speed' in options and (type(options['speed']) not in (int, float) or not .25 <= options['speed'] <= 2.0):
            raise ValueError('Velocidade deve ficar entre 0.25 e 2.0.')
        if 'resolution' in options and options['resolution'] not in ('540x960', '720x1280', '1080x1920'):
            raise ValueError('Resolução desconhecida.')
        self._send_payload({'command': 'presentation', **options})

    def send_auto_mode(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('O modo automático deve ser booleano.')
        self._send_payload({'command': 'auto_mode', 'enabled': enabled})

    def send_walk_wave_mode(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('O modo Walk + Wave deve ser booleano.')
        self._send_payload({'command': 'walk_wave_mode', 'enabled': enabled})

    def send_walk_combo_mode(self, animation, enabled):
        if animation not in ('Yes', 'No') or type(enabled) is not bool:
            raise ValueError('Combinação Walk inválida.')
        self._send_payload({'command': 'walk_combo_mode', 'animation': animation, 'enabled': enabled})

    def send_auto_animation(self, animation):
        if animation not in AUTO_ANIMATIONS:
            raise ValueError('Animação automática não permitida.')
        self._send_payload({'command': 'auto_animate', 'animation': animation})

    def close(self):
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
            self._socket = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_args):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=EVENTS)
    parser.add_argument("--user")
    parser.add_argument("--gift")
    parser.add_argument("--text")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    metadata = {key: getattr(args, key) for key in ("user", "gift", "text") if getattr(args, key) is not None}
    try:
        with NPCClient(port=args.port) as client:
            client.send_event(args.event, **metadata)
        print(f"Evento enviado: {args.event}")
    except (ConnectionError, ValueError) as exc:
        parser.exit(1, f"Erro: {exc}\n")


if __name__ == "__main__":
    raise SystemExit("Use npc_live_show.py, que verifica a identidade da cópia antes de enviar comandos.")
