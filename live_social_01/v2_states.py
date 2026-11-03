"""Read-only presentation of actual local state; never starts engines or readers."""
import json
import threading
import time
from urllib.request import urlopen
from urllib.parse import urlsplit

class LocalAvailability:
    def __init__(self):
        self.ai='Não verificada';self.voice='Não verificada';self.running=False;self.last=0

    def refresh(self,config):
        if self.running or time.monotonic()-self.last<15:return
        self.running=True;self.last=time.monotonic()
        def probe():
            try:
                import winreg
                names=[]
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Speech\Voices\Tokens') as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):names.append(winreg.EnumKey(key,i))
                self.voice='Maria instalada · teste o áudio' if any('MARIA' in x.upper() for x in names) else 'Maria não confirmada'
            except OSError:self.voice='Instalação de voz não verificada'
            try:
                settings=config['local_ai'];url=settings['url'];parts=urlsplit(url)
                if parts.hostname!='127.0.0.1' or parts.scheme!='http':raise ValueError('Somente loopback')
                base=url.split('/api/')[0]
                with urlopen(base+'/api/tags',timeout=1.5) as response:data=json.load(response)
                self.ai='Disponível · modelo local instalado' if settings['model'] in [x['name'] for x in data.get('models',[])] else 'Modelo configurado não encontrado'
            except (OSError,ValueError,KeyError):self.ai='Indisponível agora · ativa ao responder'
            finally:self.running=False
        threading.Thread(target=probe,daemon=True,name='v2-readonly-availability').start()

def presentation(monitor,availability):
    npc=monitor.npc;zuko=monitor.zuko;voice=monitor.voice.snapshot()
    source='Simulador · sem conexão real' if monitor.source=='tiktok-sim' else 'Desconectado / fonte não iniciada'
    if monitor.source!='tiktok-sim':
        snap=monitor.platform_snapshot()
        source=('TikTok · '+str(snap.get('TIKTOK_CONNECTION','Desconhecido'))) if monitor.source=='tiktok' else 'YouTube · '+('leitura ativa' if monitor.reading and not monitor.local_test_mode else 'sem leitura real')
    last=next((r for r in reversed(npc.records) if r['name'] in {'TCP_SENT','SPEECH_START','SPEECH_END'}),{})
    command={'comment':'Wave','talk':'Wave','gift':'Jump','follow':'Yes','idle':'Idle'}.get(last.get('command'),'Wave' if last.get('name')=='SPEECH_START' else 'Idle' if last.get('name')=='SPEECH_END' else 'Nenhuma')
    speaking=voice.get('TTS_STATE')=='PLAYING'
    state='Desconectado' if npc.state!='ACTIVE' else 'Pausado' if zuko.paused else 'Falando' if speaking else 'Reagindo' if time.monotonic()<getattr(npc,'reaction_until',0) or not npc.commands.empty() else 'Idle'
    voice_label='Falando · reprodução confirmada' if speaking else availability.voice
    runtime_health=getattr(monitor,'voice_health',None)
    if runtime_health and not speaking:
        checked=runtime_health.snapshot()
        voice_label=(checked['voice']+' · reprodução validada') if checked['ready'] else 'Voz não validada · use TESTAR VOZ ou INICIAR LIVE'
        if checked['state']=='UNAVAILABLE':voice_label='Voz indisponível · novas gerações bloqueadas'
    observed=next((r for r in reversed(npc.records) if r['name']=='VOICE_OBSERVED'),None)
    if observed and not speaking and not (runtime_health and runtime_health.snapshot()['ready']):
        voice_label={'TTS_OK':'Pronta · último áudio concluído','TTS_ERRO':'Erro na última reprodução · veja Diagnóstico','TTS_CANCELLED':'Áudio interrompido pelo operador'}.get(observed.get('event'),voice_label)
    actual=getattr(npc,'presentation_status',{}).get('animation')
    return {'npc':{'ACTIVE':'Aberto · ponte confirmada','OFF':'Fechado','STARTING':'Abrindo…','CLOSING':'Fechando…','ERROR':'Erro ao abrir · tente novamente'}.get(npc.state,npc.state),
        'ai':availability.ai,'voice':voice_label,'source':source,'state':state,'auto':'Ligado' if zuko.auto else 'Desligado',
        'paused':'Sim' if zuko.paused else 'Não','last_animation':(actual+' · confirmação recebida do Godot') if actual else command+' · solicitação sem confirmação',
        'queue':f"Falas pendentes: {voice.get('TTS_QUEUE_DEPTH',0)} · eventos do diretor: {len(monitor.director.pending_units)} · animações a enviar: {npc.commands.qsize()}",
        'connection':f"Personagem: {npc.state} · TCP local 127.0.0.1:{npc.port} · ponte da interface: "+('ativa nesta instância' if monitor.bridge._owns_server else 'não disponível nesta instância')}
