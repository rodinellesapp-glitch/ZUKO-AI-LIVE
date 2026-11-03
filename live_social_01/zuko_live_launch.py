"""Eight-stage local preparation. Never controls public broadcast buttons."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from importlib import util,metadata
import os
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
TRACKS=()
STEPS=('Verificar ambiente','Inicializar ZUKO 3D','Validar voz e reprodução','Inicializar IA',
       'Preparar trilha sonora','Conectar leitor TikTok','Verificar LIVE Studio','Liberar apresentador')


def environment_check(monitor):
    import psutil
    if Path.cwd().resolve()!=ROOT:
        raise RuntimeError('Workspace incorreto: abra pelo ABRIR_ZUKO_V2.cmd deste workspace.')
    missing=[name for name in ('pygame','psutil','TikTokLive') if util.find_spec(name) is None]
    if missing:raise RuntimeError('Dependências ausentes: '+', '.join(missing))
    if metadata.version('TikTokLive')!='7.0.1':raise RuntimeError('TikTokLive requer a versão local 7.0.1 já homologada.')
    godot=Path(os.environ.get('NPC_GODOT_EXE') or Path.home()/'OneDrive/Desktop/Godot_v3.6-stable_win64.exe')
    if not godot.is_file() or not (ROOT/'npc_runtime/godot/project.godot').is_file():
        raise RuntimeError('Godot 3.6 ou projeto 3D local não encontrado.')
    if sys.version_info<(3,11):raise RuntimeError('Use Python 3.11 ou posterior.')
    owners=[]
    for process in psutil.process_iter(['pid','name','cmdline']):
        try:
            args=process.info['cmdline'] or []
            if process.pid!=os.getpid() and any(Path(a).name=='abrir_zuko_v2.py' for a in args):
                if Path(process.cwd()).resolve()==ROOT:owners.append(process.pid)
        except (psutil.Error,OSError,ValueError):continue
    if owners:raise RuntimeError('Outro Dashboard deste workspace está aberto. Use uma única instância.')
    return {'workspace':str(ROOT),'python':sys.version.split()[0],'godot_found':True,'duplicate_dashboard':False,
            'tiktok_sdk':metadata.version('TikTokLive'),'public_broadcast':'NOT_CONFIRMED'}


def studio_check():
    import psutil
    names=[]
    for process in psutil.process_iter(['name']):
        try:
            name=process.info['name'] or ''
            compact=name.casefold().replace(' ','').replace('_','')
            if 'tiktoklivestudio' in compact:names.append(name)
        except psutil.Error:continue
    return {'open':bool(names),'processes':sorted(set(names)),
            'capture':'MANUAL','public_broadcast':'NOT_CONFIRMED'}


def soundtrack_check(monitor):
    import pygame
    paths=[ROOT/'musicas'/name for name in TRACKS]
    if not pygame.mixer.get_init():pygame.mixer.init()
    for path in paths:
        with wave.open(str(path),'rb') as audio:
            if audio.getnframes()<100:raise RuntimeError('Trilha WAV vazia: '+path.name)
        pygame.mixer.Sound(str(path))  # Decode locally without starting playback.
    prefs=monitor.soundtrack.snapshot()['preferences']
    if any(str(path) not in {row['path'] for row in prefs['playlist']} for path in paths):
        monitor.soundtrack.add_files(paths,licensed=True)
    return {'tracks':[p.name for p in paths],'mixer':pygame.mixer.get_init(),
            'autoplay':False,'levels':{k:prefs[k] for k in ('normal_volume','speech_volume','duck_ms','restore_ms')}}


class LiveLaunchController:
    BUSY_STATES={'PREPARING_ENV','PREPARING_NPC','PREPARING_VOICE','PREPARING_AI','PREPARING_MUSIC',
                 'CONNECTING_TIKTOK','PREPARING_STUDIO','PREPARING_PRESENTER'}
    def __init__(self,root,monitor_provider,on_update,start_source,stop_source,*,clock=time.monotonic,
                 environment=environment_check,studio=studio_check,music=soundtrack_check,simulation=False):
        self.root=root;self.monitor_provider=monitor_provider;self.on_update=on_update
        self.start_source=start_source;self.stop_source=stop_source;self.clock=clock
        self.environment=environment;self.studio=studio;self.music=music;self.simulation=simulation
        self.state='IDLE';self.detail='';self.steps=[{'name':name,'state':'PENDING','detail':''} for name in STEPS]
        self.facts={'public_broadcast':'NOT_CONFIRMED'};self._generation=0;self._monitor=None
        self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='zuko-local-preparation')
        self._future=None;self._opened_npc=False;self._source_started=False;self._stage=0;self._deadline=0
        self._motion=None;self._speech_seen=False;self._record_offset=0;self._last_detail=None
        self._music_started=False
    @property
    def busy(self):return self.state in self.BUSY_STATES
    def _publish(self,state,detail):
        self.state=state;self.detail=detail
        self.on_update(state,detail)
        monitor=self._monitor
        if monitor and callable(getattr(monitor,'_log',None)) and (state,detail)!=self._last_detail:
            monitor._log('LIVE_PREPARATION | '+state+' | '+detail)
            self._last_detail=(state,detail)
    def snapshot(self):
        return {'state':self.state,'steps':[dict(row) for row in self.steps],'facts':dict(self.facts),
                'detail':self.detail,'simulation':self.simulation}
    def _enter(self,index,state,detail,timeout=30,complete_previous=True):
        if index>0 and complete_previous:self.steps[index-1]['state']='PASS'
        self._stage=index;self.steps[index]['state']='RUNNING';self.steps[index]['detail']=detail
        self._deadline=self.clock()+timeout;self._publish(state,f'Etapa {index+1}/8 · '+detail)
    def start(self):
        if self.busy or self.state in {'READY','OPERATIONAL'}:return False
        monitor=self.monitor_provider()
        if not monitor:return False
        self._monitor=monitor;self._generation+=1;self.facts={'public_broadcast':'NOT_CONFIRMED'}
        self.steps=[{'name':name,'state':'PENDING','detail':''} for name in STEPS]
        self._opened_npc=False;self._source_started=False;self._speech_seen=False;self._motion=None
        self._music_started=False
        monitor._launch_preparing=True
        monitor.zuko.set_auto(False)
        monitor.director.invalidate()
        if monitor.voice.current or monitor.voice.queue:monitor.voice.cancel_current(clear_pending=True)
        self._enter(0,'PREPARING_ENV','Verificando workspace, dependências e instâncias.',15)
        self._future=self._pool.submit(self.environment,monitor)
        self._schedule(self._generation);return True
    def _schedule(self,generation):self.root.after(150,lambda:self._tick(generation))
    def _finish_future(self):
        if not self._future.done():return None
        result=self._future.result();self._future=None;return result
    def _tick(self,generation):
        if generation!=self._generation or not self.busy:return
        try:
            if self.clock()>=self._deadline:raise RuntimeError('Prazo esgotado na etapa '+str(self._stage+1)+'. Consulte Diagnóstico.')
            self._advance()
        except Exception as error:self._fail(str(error));return
        if self.busy:self._schedule(generation)
    def _request_motion(self,name):
        self._record_offset=len(self._monitor.npc.records)
        npc=self._monitor.npc
        # The Idle control releases manual override so TTS can drive speaking.
        accepted=npc.manual_control('idle') if name=='Idle' and callable(getattr(npc,'manual_control',None)) else npc.manual_animation(name,False)
        if not accepted:raise RuntimeError('Godot recusou o movimento de teste '+name)
        self._motion=name
    def _motion_received(self):
        npc=self._monitor.npc
        sent=any(row.get('name')=='MANUAL_SENT' and (row.get('animation')==self._motion or
                 (self._motion=='Idle' and row.get('command')=='idle'))
                 for row in npc.records[self._record_offset:])
        return sent and npc.presentation_status.get('animation')==self._motion
    def _advance(self):
        m=self._monitor
        if self.state=='PREPARING_ENV':
            result=self._finish_future()
            if result is None:return
            self.facts['environment']=result
            self._enter(1,'PREPARING_NPC','Abrindo Godot e validando TCP, Wave e Idle.',40)
            if m.npc.state not in {'ACTIVE','STARTING'}:
                self._opened_npc=True;m.npc.open()
        elif self.state=='PREPARING_NPC':
            if m.npc.state=='ERROR':raise RuntimeError(m.npc.error or 'Godot não abriu.')
            if m.npc.state!='ACTIVE' or not m.npc.presentation_status:return
            if self._motion is None:self._request_motion('Wave');return
            if not self._motion_received():return
            if self._motion=='Wave':self._request_motion('Idle');return
            self.facts['godot']={'tcp_bidirectional':True,'motions':['Wave','Idle']}
            self._enter(2,'PREPARING_VOICE','Inicializando a voz local e reproduzindo uma frase; aguardando fala no Godot.',60)
            if not m.begin_voice_check():raise RuntimeError('Fila de voz ocupada. Aguarde a fala anterior terminar e tente novamente.')
        elif self.state=='PREPARING_VOICE':
            check=m.voice_check_snapshot();status=m.npc.presentation_status
            if status.get('speaking') is True:self._speech_seen=True
            if check['state']=='FAILED':raise RuntimeError('Voz indisponível: '+check.get('error',''))
            if check['state']!='READY':return
            if not self._speech_seen or status.get('speaking') is not False:return
            self.facts['voice']={**m.voice_health.snapshot(),'godot_speech_start_end':True}
            self._enter(3,'PREPARING_AI','Carregando Presenter V3, memória e autorizações existentes.',20)
        elif self.state=='PREPARING_AI':
            engine=getattr(m.zuko,'autonomy',None)
            if engine is None or not getattr(engine,'memory',None):raise RuntimeError('Presenter V3 ou memória não carregados.')
            ai=m.zuko.litellm.readiness_snapshot()
            if ai['state']=='INICIALIZANDO':return
            self.facts['ai']={'presenter_loaded':True,'memory_loaded':True,'gemini_readiness':ai['state'],
                'gemini_authorized':m.zuko.gemini_budget.snapshot(m.session_epoch)['authorized'],'test_calls':0}
            self._enter(4,'PREPARING_MUSIC','Verificando as duas trilhas e o dispositivo de áudio, sem iniciar música.',15)
            self._future=self._pool.submit(self.music,m)
        elif self.state=='PREPARING_MUSIC':
            result=self._finish_future()
            if result is None:return
            self.facts['soundtrack']=result
            self._enter(5,'CONNECTING_TIKTOK','Conectando leitor de eventos configurado; publicação permanece manual.',38)
            simulated=self.simulation or getattr(m.tiktok_source,'simulation',False)
            if not simulated:
                unique_id=os.environ.get('TIKTOK_UNIQUE_ID','').strip().removeprefix('@')
                if not unique_id:raise RuntimeError('Configure TIKTOK_UNIQUE_ID antes de habilitar a fonte TikTok real.')
                if m.local_test_mode:m.set_local_mode(False)
                if not m.set_platform('TIKTOK',tiktok_mode='tiktok',unique_id=unique_id):
                    raise RuntimeError('Pare o leitor anterior antes de trocar a fonte TikTok.')
            if not m.reading:self.start_source();self._source_started=bool(m.reading)
        elif self.state=='CONNECTING_TIKTOK':
            info=m.tiktok_source.health();connection=info['connection']
            # Offline public rooms cannot be connected until the operator
            # starts a broadcast. Local readiness and reader state stay separate.
            if connection in {'WAITING_FOR_LIVE','CONNECTING'}:
                if self.clock()<self._deadline-5:return
            simulated=self.simulation or getattr(m.tiktok_source,'simulation',False)
            confirmed=(connection=='CONNECTED' and not simulated and
                callable(getattr(m.tiktok_source,'is_connected',None)) and m.tiktok_source.is_connected())
            if confirmed:
                self.steps[5].update(state='PASS',detail='Sessão TikTok real confirmada pelo evento de conexão.')
            elif simulated:
                self.steps[5].update(state='SIMULATED',detail='Simulação local; nenhuma conexão TikTok real foi confirmada.')
            elif connection in {'WAITING_FOR_LIVE','CONNECTING','LIVE_OFFLINE','STOPPED','DISCONNECTED'}:
                self.steps[5].update(state='PENDING',detail='Conexão real não confirmada · '+str(info.get('reason') or connection))
            else:
                self.steps[5].update(state='FAIL',detail='Falha do leitor TikTok · '+str(info.get('reason') or connection))
            self.facts['tiktok']={'connection':connection,'reason':info.get('reason',''),
                'broadcaster':info.get('broadcaster',('@'+unique_id) if not simulated else 'canal de demonstração'),'simulation':simulated,
                'confirmed_real':confirmed,'step_state':self.steps[5]['state']}
            self._enter(6,'PREPARING_STUDIO','Detectando LIVE Studio e listando a captura manual necessária.',10,complete_previous=False)
            self._future=self._pool.submit(self.studio)
        elif self.state=='PREPARING_STUDIO':
            result=self._finish_future()
            if result is None:return
            self.facts['studio']=result
            self._enter(7,'PREPARING_PRESENTER','Validando os componentes essenciais antes de liberar AUTO.',10)
        elif self.state=='PREPARING_PRESENTER':
            if m.npc.state!='ACTIVE' or not m.voice_health.snapshot()['ready']:
                raise RuntimeError('Godot ou voz perdeu a prontidão durante a preparação.')
            m._launch_preparing=False
            self.steps[7]['state']='PASS'
            self._publish('READY','Componentes locais validados. Confirme a ativação local; publique manualmente pelo LIVE Studio.')
    def activate(self,*,start_music=False):
        if self.state!='READY':return False
        m=self._monitor
        if m.npc.state!='ACTIVE' or not m.voice_ready_for_text():
            self._fail('Voz ou Godot indisponível; repita a preparação.');return False
        if not m.reading:self.start_source()
        if not m.zuko.set_auto(True):return False
        if start_music:
            self._music_started=bool(m.soundtrack.start())
        self._publish('OPERATIONAL','ZUKO local operacional. Leitor TikTok e transmissão pública têm estados próprios.')
        return True
    def cancel(self):
        if not self.busy:return False
        self._generation+=1
        if self._future:self._future.cancel()
        m=self._monitor;m._launch_preparing=False
        m.voice.cancel_preview()
        if self._source_started:self.stop_source()
        if self._opened_npc and m.npc.state in {'STARTING','ACTIVE','ERROR'}:m.npc.close_npc()
        self._publish('CANCELLED','Preparação cancelada. Transmissão pública continua sob controle manual.')
        return True
    def stop(self):
        if self.busy:return self.cancel()
        if self.state not in {'READY','OPERATIONAL','FAILED'}:return False
        self._generation+=1;m=self._monitor
        m._launch_preparing=False;m.zuko.set_auto(False)
        m.director.invalidate()
        if m.reading:self.stop_source()
        else:
            stop_reader=getattr(m.tiktok_source,'stop',None)
            if callable(stop_reader):stop_reader()
        m.voice.stop();m.soundtrack.stop()
        if m.npc.state=='ACTIVE':m.npc.manual_animation('Idle',False)
        self._publish('IDLE','Componentes do ZUKO encerrados; LIVE Studio e transmissão pública não foram alterados.')
        return True
    def _fail(self,detail):
        self._generation+=1;self.steps[self._stage]['state']='FAIL';self.steps[self._stage]['detail']=detail
        m=self._monitor;m._launch_preparing=False
        m.voice.cancel_preview();m.voice.cancel_current(clear_pending=True);m.zuko.set_auto(False)
        m.director.invalidate()
        if self._music_started:m.soundtrack.stop()
        if self._source_started:self.stop_source()
        if m.npc.state=='ACTIVE':m.npc.manual_animation('Idle',False)
        self._publish('FAILED',detail)
    def check_runtime(self):
        if self.state not in {'READY','OPERATIONAL'}:return
        m=self._monitor
        if m.npc.state!='ACTIVE':self._fail('Conexão com o Godot perdida; AUTO interrompido.');return
        if m.voice_health.snapshot()['state']=='UNAVAILABLE' and not m.voice_ready_for_text():
            self._fail('Voz indisponível; geração interrompida. Execute novamente a preparação.')
            return
        if self.state=='OPERATIONAL' and not m.reading:self.stop()
    def close(self):
        if self.busy:self.cancel()
        elif self.state in {'READY','OPERATIONAL'}:self.stop()
        self._pool.shutdown(wait=False,cancel_futures=True)
