import json
import threading
import select
from npc_client import NPCClient, ANIMATIONS, WALK_COMBO_ANIMATIONS


class ShowClient(NPCClient):
    """Só controla a cópia identificada como NPC_LIVE_SHOW."""
    def __init__(self, port=8765):
        super().__init__(port)
        self.lock = threading.RLock()
        self.status = None
        self._status_buffer = bytearray()

    def connect(self):
        with self.lock:
            self.status = None
            self._status_buffer.clear()
            super().connect()
            try:
                banner = bytearray()
                while b'\n' not in banner and len(banner) < 512:
                    byte = self._socket.recv(1)
                    if not byte:
                        raise ConnectionError('Servidor encerrou antes de se identificar.')
                    banner.extend(byte)
                identity = json.loads(banner.decode('utf-8'))
                if identity != {'app': 'NPC_LIVE_SHOW', 'protocol': 1}:
                    raise ConnectionError('A porta não pertence ao NPC LIVE SHOW.')
            except Exception as error:
                self.close()
                raise ConnectionError('Identidade do NPC LIVE SHOW não confirmada; nenhum evento enviado.') from error
        return self

    def send_event(self, event, **metadata):
        with self.lock:
            return super().send_event(event, **metadata)

    def send_animation(self, animation, repeat=False):
        with self.lock:
            return super().send_animation(animation, repeat)

    def send_control(self, command):
        with self.lock:
            return super().send_control(command)

    def send_presentation(self, **options):
        with self.lock:
            return super().send_presentation(**options)

    def send_auto_mode(self, enabled):
        with self.lock:
            return super().send_auto_mode(enabled)

    def send_auto_animation(self, animation):
        with self.lock:
            return super().send_auto_animation(animation)

    def send_audience_queue(self, state):
        with self.lock:
            self._send_payload(dict(state,command='audience_queue'))

    def poll_status(self):
        with self.lock:
            if self._socket is None:
                raise ConnectionError('Godot desconectado.')
            if not select.select([self._socket], [], [], 0)[0]:
                return self.status
            chunk = self._socket.recv(8192)
            if not chunk:
                self.close()
                raise ConnectionError('Godot encerrou a conexão.')
            self._status_buffer.extend(chunk)
            if len(self._status_buffer) > 32768:
                raise ConnectionError('Resposta Godot excedeu o limite.')
            while b'\n' in self._status_buffer:
                line, _, rest = self._status_buffer.partition(b'\n')
                self._status_buffer = bytearray(rest)
                row = json.loads(line.decode('utf-8'))
                state = row.get('state', {})
                if row.get('type') != 'presentation_status' or not isinstance(state, dict):
                    continue
                if any(type(state.get(k)) is not bool for k in ('walking','live','paused','manual')):
                    raise ConnectionError('Estado Godot inválido.')
                if 'speaking' in state and type(state.get('speaking')) is not bool:
                    raise ConnectionError('Estado de fala Godot inválido.')
                if ('automatic' in state and type(state.get('automatic')) is not bool) or ('reacting' in state and type(state.get('reacting')) is not bool):
                    raise ConnectionError('Estado de automação Godot inválido.')
                for key in ('walk_wave_enabled','walk_wave_available','walk_wave_active','scenery_moving'):
                    if key in state and type(state.get(key)) is not bool:
                        raise ConnectionError('Estado Walk + Wave Godot inválido.')
                if 'walk_combos' in state and (not isinstance(state.get('walk_combos'),dict) or any(k not in ('Wave','Yes','No') or type(v) is not bool for k,v in state['walk_combos'].items())):
                    raise ConnectionError('Estado de combinações Walk Godot inválido.')
                if 'walk_combo_available' in state and (not isinstance(state.get('walk_combo_available'),dict) or any(k not in ('Wave','Yes','No') or type(v) is not bool for k,v in state['walk_combo_available'].items())):
                    raise ConnectionError('Disponibilidade de combinações Walk Godot inválida.')
                if 'walk_combo_errors' in state and (not isinstance(state.get('walk_combo_errors'),dict) or any(k not in ('Wave','Yes','No') or not isinstance(v,str) for k,v in state['walk_combo_errors'].items())):
                    raise ConnectionError('Falhas de combinações Walk Godot inválidas.')
                if 'walk_combo_active' in state and state.get('walk_combo_active') not in ('','Wave','Yes','No'):
                    raise ConnectionError('Combinação Walk ativa inválida.')
                if 'walk_combo_bones' in state and (not isinstance(state.get('walk_combo_bones'),list) or any(not isinstance(v,str) for v in state['walk_combo_bones'])):
                    raise ConnectionError('Trilhas da combinação Walk inválidas.')
                if 'walk_combo_tracks' in state and (not isinstance(state.get('walk_combo_tracks'),list) or any(not isinstance(v,str) for v in state['walk_combo_tracks'])):
                    raise ConnectionError('Caminhos de trilha da combinação Walk inválidos.')
                if 'walk_wave_error' in state and not isinstance(state.get('walk_wave_error'),str):
                    raise ConnectionError('Diagnóstico Walk + Wave Godot inválido.')
                if 'source' in state and state.get('source') not in ('GODOT','MANUAL','AUTOMÁTICO'):
                    raise ConnectionError('Origem de movimento Godot inválida.')
                if state.get('animation') not in ANIMATIONS + WALK_COMBO_ANIMATIONS + ('',):
                    raise ConnectionError('Animação no estado Godot inválida.')
                self.status = state
            return self.status
