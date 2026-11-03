"""ZIG HUMAN 4.9: local launcher, existing Live Social UI and audio ownership."""
from pathlib import Path
import json
import logging
import msvcrt
import socket
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / 'assistente_avatar/releases/zig-human-4.9/runtime'
CONFIG = json.loads((VIEWER / 'runtime.json').read_text(encoding='utf-8'))
assert CONFIG['host'] == '127.0.0.1'
assert 1024 <= CONFIG['port'] <= 65535
ORIGIN = f"http://127.0.0.1:{CONFIG['port']}"
URL = ORIGIN + CONFIG['viewer_path']
PYTHON = Path.home() / 'AppData/Local/Programs/Python/Python311/pythonw.exe'
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
STATE = ROOT / 'live_social_01/logs/zig-human-4.9'
PROFILE = STATE / 'chrome-profile'
LOCK = ROOT / 'live_social_01/logs/zig-viewer.lock'

def _get(url):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=1) as r:
        return r.read()

def _cdp():
    try:
        port = int((PROFILE / 'DevToolsActivePort').read_text().splitlines()[0])
        if 1024 <= port <= 65535:
            return f'http://127.0.0.1:{port}'
    except (OSError, ValueError, IndexError):
        pass
    return None

def _viewer_target(target):
    u = urlsplit(target.get('url', ''))
    return (target.get('type') == 'page' and u.hostname == '127.0.0.1'
            and u.port == CONFIG['port'] and u.path == urlsplit(URL).path)

def health():
    server = page = False
    targets = []
    try:
        data = json.loads(_get(ORIGIN + '/api/health49'))
        server = data.get('version') == '4.9' and data.get('asset_version') == '4.8.3'
        page = server and b'presenter43.js' in _get(URL)
    except Exception:
        pass
    cdp = _cdp()
    if cdp:
        try:
            targets = [t for t in json.loads(_get(cdp + '/json/list')) if _viewer_target(t)]
        except Exception:
            pass
    return {'server':server, 'page':page, 'targets':targets,
            'state':'ONLINE' if page and len(targets)==1 and targets[0].get('title') == 'ZIG WALK 1.1 · São Paulo Dinâmica' else 'OFFLINE'}

def _occupied():
    try:
        with socket.create_connection(('127.0.0.1',CONFIG['port']),timeout=1):
            return True
    except OSError:
        return False

def _existing_chrome():
    # Inspect only Chrome process arguments, never bridge credentials or browsing data.
    import psutil
    for proc in psutil.process_iter(['name','cmdline']):
        if (proc.info['name'] or '').lower() != 'chrome.exe':
            continue
        args = proc.info['cmdline'] or []
        if any(a.startswith('--app=') and '/zig-live-viewer-352/viewer.html' in a for a in args):
            return True
        if any(a.startswith('--user-data-dir=') and a.split('=',1)[1].lower() == str(PROFILE).lower() for a in args):
            return True
    return False

def open_viewer():
    """Cross-process lock, verified server identity, one managed Chrome window."""
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    STATE.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        deadline = time.monotonic() + 25
        while True:
            try:
                lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError:
                if time.monotonic() >= deadline: raise TimeoutError('ZIG startup lock timed out')
                time.sleep(.1)
        try:
            h = health()
            if len(h['targets']) > 1: raise RuntimeError('Feche as janelas ZIG duplicadas antes de continuar')
            if not h['page']:
                if _occupied(): raise RuntimeError('Porta do Viewer ocupada por outra versao; consulte o rollback 4.9')
                if not PYTHON.is_file() or not (VIEWER/'serve.py').is_file():
                    raise FileNotFoundError('ZIG 4.9 runtime unavailable')
                with (STATE/'server.log').open('a') as log:
                    subprocess.Popen([str(PYTHON),'-B',str(VIEWER/'serve.py')],cwd=str(VIEWER),
                                     stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                for _ in range(100):
                    h=health()
                    if h['page']: break
                    time.sleep(.1)
                if not h['page']: raise TimeoutError('ZIG 4.9 server did not start')
            if not h['targets']:
                if _existing_chrome(): raise RuntimeError('Uma janela ZIG ja esta aberta; feche-a antes de abrir a 4.9')
                if not CHROME.is_file(): raise FileNotFoundError('Chrome unavailable')
                PROFILE.mkdir(parents=True,exist_ok=True)
                subprocess.Popen([str(CHROME),'--app='+URL,'--user-data-dir='+str(PROFILE),
                    '--window-size=900,900','--window-position=80,60','--autoplay-policy=no-user-gesture-required',
                    '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
                    '--disable-background-timer-throttling','--disable-renderer-backgrounding',
                    '--no-first-run','--no-default-browser-check'],cwd=str(VIEWER))
                for _ in range(100):
                    h=health()
                    if h['targets']: break
                    time.sleep(.1)
            if len(h['targets']) != 1: raise RuntimeError('ZIG window unavailable or duplicated')
            if h['targets'][0].get('url') != URL:
                raise RuntimeError('Janela ZIG aberta sem capture=obs; feche e reabra pelo botao')
            _get(_cdp()+'/json/activate/'+h['targets'][0]['id'])
            for _ in range(100):
                h=health()
                if h['state']=='ONLINE': return h
                time.sleep(.1)
            raise TimeoutError('ZIG page did not finish loading')
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


class ZigViewerButton:
    """UI thread only reads state; blocking local work stays in one daemon thread."""
    LABELS = {'OFFLINE': 'ZIG LIVE', 'STARTING': 'ABRINDO...', 'ONLINE': 'ZIG ONLINE', 'ERROR': 'ERRO ZIG'}

    def __init__(self, root, button):
        self.root, self.button = root, button
        self.state, self.error, self.detail = 'OFFLINE', '', {}
        self.worker = None
        self.next_check = 0
        button.configure(command=self.open)
        self._poll()

    def open(self):
        if self.worker and self.worker.is_alive(): return
        self.state, self.error = 'STARTING', ''
        self.button.configure(text=self.LABELS[self.state], state='disabled')
        self.worker = threading.Thread(target=self._open, daemon=True)
        self.worker.start()

    def _open(self):
        try:
            self.detail = open_viewer()
            if self.detail['state'] != 'ONLINE': raise RuntimeError('Viewer health is incomplete')
            self.state = 'ONLINE'
        except Exception as exc:
            self.state, self.error = 'ERROR', str(exc)
            try:
                with (LOCK.parent / 'zig-viewer-errors.log').open('a', encoding='utf-8') as log:
                    log.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + self.error + '\n')
            except OSError:
                logging.exception('Could not record ZIG viewer error')

    def _check(self):
        self.detail = health()
        self.state = self.detail['state']

    def _poll(self):
        busy = self.worker and self.worker.is_alive()
        self.button.configure(text=self.LABELS[self.state], state='disabled' if busy else 'normal')
        if not busy and self.state != 'ERROR' and time.monotonic() >= self.next_check:
            self.next_check = time.monotonic() + 3
            self.worker = threading.Thread(target=self._check, daemon=True)
            self.worker.start()
        self.root.after(150, self._poll)
