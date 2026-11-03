"""Six-tab presentation adapter. Original pipeline callbacks and dashboard methods are reused."""
import json
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from live_dashboard import LiveDashboard
from live_zig_viewer import ZigViewerButton
from v2_components import ScrollPage,card,paragraph,BG,PANEL,TEXT,MUTED
from v2_help import HelpRegistry
from v2_states import LocalAvailability,presentation
from live_preparation import tiktok_event_readiness_lines
from zuko_live_launch import LiveLaunchController as LivePreparationController
import gemini_limits
import gemini_model_settings

ROOT=Path(__file__).resolve().parents[1]
TABS=('Início','ZUKO','Voz e IA','Eventos e Live','Diagnóstico','Ajuda e instruções')
EVENT_LABELS={'CHAT':'Comentário','GIFT':'Presente','FOLLOW':'Novo seguidor','SUPER_CHAT':'Super Chat (simulado)','MEMBER':'Novo membro','LIKE':'Curtida'}
MOVEMENT_GROUPS={
    'Estados': [('Idle','Parado'),('Idle_Gun','Parado com arma'),('Idle_Shoot','Parado atirando')],
    'Locomoção': [('Walk','Caminhar'),('Run','Correr'),('Walk_Gun','Caminhar com arma'),('Run_Gun','Correr com arma'),('Run_Shoot','Correr atirando')],
    'Saltos': [('Jump','Pular'),('Jump_Idle','No ar'),('Jump_Land','Aterrissar')],
    'Reações e ações': [('Wave','Acenar'),('Yes','Sim'),('No','Não'),('Duck','Agachar'),('HitReact','Reação ao impacto'),('Punch','Soco'),('Death','Morrer')],
}
MOVEMENT_LABELS={clip:label for items in MOVEMENT_GROUPS.values() for clip,label in items}


def connection_health_snapshot(monitor,legacy_health):
    """Separate YouTube DOM, its HTTP bridge, Godot TCP and TikTokLive."""
    result=dict(legacy_health)
    result['GODOT TCP 18765']='OFFLINE'
    npc=getattr(monitor,'npc',None)
    if npc is not None and getattr(npc,'state',None)=='ACTIVE':
        status=getattr(npc,'presentation_status',{})
        animation=status.get('animation') if isinstance(status,dict) else None
        result['GODOT TCP 18765']=('MOVIMENTO CONFIRMADO · '+str(animation) if animation else 'CONECTADO · aguardando estado')
    source=getattr(monitor,'tiktok_source',None)
    if source is not None:
        health=source.health();state=health.get('connection','UNKNOWN')
        if getattr(source,'simulation',False) and state=='SIMULATOR':result['TIKTOKLIVE']='SIMULADOR'
        elif state in {'STOPPED','DISCONNECTED','LIVE_OFFLINE','ERROR','AUTH_REQUIRED','RATE_LIMITED'}:
            result['TIKTOKLIVE']='DESCONECTADO · '+state
        else:result['TIKTOKLIVE']=state
        if health.get('reason'):result['TIKTOKLIVE']+=' · '+str(health['reason'])
    return result


def _zuko_metric_lines(presenter, writer):
    """Format current Presenter metrics separately from legacy Writer totals."""
    presenter=presenter or {}
    writer=writer or {}
    return [
        'TEXTO ZUKO · PRESENTER ATUAL',
        ('Comentários Presenter: '+str(presenter.get('ZUKO_COMMENTS_RECEIVED',0))+' recebidos · '+
         str(presenter.get('ZUKO_COMMENTS_ELIGIBLE',0))+' encaminhados · '+
         str(presenter.get('ZUKO_COMMENT_RESPONSES_ENQUEUED',0))+' respostas enfileiradas · '+
         str(presenter.get('ZUKO_COMMENTS_IGNORED',0))+' ignorados · '+
         str(presenter.get('ZUKO_COMMENTS_FAILED',0))+' falhas · '+
         str(presenter.get('ZUKO_COMMENT_RESPONSES_SPOKEN',0))+' falados'),
        ('Gemini: '+str(presenter.get('ZUKO_GEMINI_REAL_CALLS',0))+' chamadas · '+
         str(presenter.get('ZUKO_GEMINI_SUCCESSES',0))+' gerações OK · '+
         str(presenter.get('ZUKO_GEMINI_ERRORS',0))+' erros · '+
         str(presenter.get('ZUKO_GEMINI_TEXTS',0))+' respostas enfileiradas'),
        ('Modelo Gemini: configurado '+str(presenter.get('ZUKO_GEMINI_CONFIGURED_MODEL','—'))+
         ' · última geração '+str(presenter.get('ZUKO_GEMINI_ACTIVE_MODEL','—'))),
        ('TikTok real: '+str(presenter.get('ZUKO_TIKTOK_CONNECTION','—'))+
         ' · comentários '+str(presenter.get('ZUKO_TIKTOK_REAL_COMMENTS_RECEIVED',0))+
         ' · JOINs '+str(presenter.get('ZUKO_TIKTOK_REAL_JOINS_RECEIVED',0))+
         ' · '+str(presenter.get('ZUKO_TIKTOK_JOIN_CAPABILITY','UNAVAILABLE'))),
        ('JOINs: '+str(presenter.get('ZUKO_JOIN_EVENTS_RECEIVED',0))+' recebidos · '+
         str(presenter.get('ZUKO_JOIN_EVENTS_GROUPED',0))+' agrupados · '+
         str(presenter.get('ZUKO_JOIN_GREETINGS_QUEUED',0))+' enfileirados · '+
         str(presenter.get('ZUKO_JOIN_EVENTS_GREETED',0))+' saudados · falhas '+
         str(presenter.get('ZUKO_JOIN_GREETING_FAILURES',0))),
        ('Interação V4: AUTO '+str(presenter.get('ZUKO_AUTO_ENABLED',False))+
         ' · autonomia '+str(presenter.get('ZUKO_AUTONOMY_STATE','—'))+
         ' · tema '+str(presenter.get('ZUKO_AUTONOMY_TOPIC','—'))+
         ' · Director '+str(presenter.get('ZUKO_DIRECTOR_QUEUE_DEPTH',0))+
         ' aguardando · TTS '+str(presenter.get('ZUKO_TTS_STATE','—'))+
         ' / fila '+str(presenter.get('ZUKO_TTS_QUEUE_DEPTH',0))),
        'Ollama: '+str(presenter.get('ZUKO_LOCAL_AI_TEXTS',0))+' respostas enfileiradas',
        'Fallback de texto: '+str(presenter.get('ZUKO_TEXT_FALLBACKS',0))+' respostas geradas localmente após seleção Gemini',
        'Fallback de voz/TTS: '+str(presenter.get('ZUKO_GEMINI_TTS_FALLBACKS',0))+' · motivos '+
        str(presenter.get('ZUKO_GEMINI_TTS_FALLBACK_REASONS',{})),
        ('Cancelamentos de fala: '+str(presenter.get('ZUKO_TTS_CANCELLED_INTENTIONAL',0))+' intencionais · '+
         str(presenter.get('ZUKO_TTS_CANCELLED_UNCLASSIFIED',0))+' sem causa'),
        'Das chamadas Gemini acima: reflexão '+str(presenter.get('ZUKO_GEMINI_REFLECTION_CALLS',0))+' · sem TTS',
        ('WRITER LEGADO · '+str(writer.get('WRITER MODE','—'))+': Gemini '+
         str(writer.get('GEMINI_WRITER_SPEECH',0))+' · Local '+
         str(writer.get('LOCAL_WRITER_SPEECH',0))+' · fallback '+
         str(writer.get('LOCAL_FALLBACK_SPEECH',0))),
    ]


def _legacy_metric_lines(writer, telemetry):
    writer=writer or {}
    telemetry=telemetry or {}
    return [
        'CONTADORES LEGADOS · não representam o Presenter ZUKO atual',
        ('GEMINI_CALL_ATTEMPTS_SESSION='+str(telemetry.get('GEMINI_CALL_ATTEMPTS_SESSION',0))+ 
         ' · GEMINI_CALL_SUCCESS_SESSION='+str(telemetry.get('GEMINI_CALL_SUCCESS_SESSION',0))+ 
         ' · GEMINI_CALL_ERRORS_SESSION='+str(telemetry.get('GEMINI_CALL_ERRORS_SESSION',0))),
        ('Writer legado: Gemini '+str(writer.get('GEMINI_WRITER_SPEECH',0))+ 
         ' · Local '+str(writer.get('LOCAL_WRITER_SPEECH',0))+ 
         ' · fallback '+str(writer.get('LOCAL_FALLBACK_SPEECH',0))),
    ]


class LiveDashboardV2(LiveDashboard):
    def apply_selected_gemini_model(self):
        model_id=gemini_model_settings.ID_BY_LABEL.get(self.gemini_model_var.get())
        if not model_id:
            self.gemini_model_apply_error='modelo não reconhecido'
            self.refresh_gemini_model_panel()
            return False
        try:
            result=self.controls['gemini_model_apply'](model_id)
        except Exception as error:
            self.gemini_model_apply_error=type(error).__name__
            self.refresh_gemini_model_panel()
            return False
        if not result.get('ok'):
            self.gemini_model_apply_error=str(result.get('code','não aplicado'))
            self.refresh_gemini_model_panel()
            return False
        self.gemini_model_apply_error=None
        self._gemini_model_selection_initialized=False
        self.refresh_gemini_model_panel()
        return True

    def restore_functional_gemini_model(self):
        try:
            result=self.controls['gemini_model_restore']()
        except Exception as error:
            self.gemini_model_apply_error=type(error).__name__
            self.refresh_gemini_model_panel()
            return False
        if not result.get('ok'):
            self.gemini_model_apply_error=str(result.get('code','modelo anterior indisponível'))
            self.refresh_gemini_model_panel()
            return False
        self.gemini_model_apply_error=None
        self._gemini_model_selection_initialized=False
        self.refresh_gemini_model_panel()
        return True

    def refresh_writer_status(self):
        """One renderer for legacy, Presenter and V3 refresh timers."""
        monitor=getattr(self,'runtime_monitor',None)
        if not monitor or not hasattr(self,'writer_status'):return
        zuko=getattr(monitor,'zuko',None)
        writer=getattr(monitor,'writer',None)
        if not zuko or not callable(getattr(writer,'snapshot',None)):return
        stats=writer.snapshot()
        provider_status=getattr(zuko,'provider_status_text',None)
        current=provider_status() if callable(provider_status) else 'Seleção: aguardando'
        text=current+'\n'+f"WRITER LEGADO: {stats['WRITER MODE']} · Gemini {stats['GEMINI_WRITER_SPEECH']} · Local {stats['LOCAL_WRITER_SPEECH']} · Fallback {stats['LOCAL_FALLBACK_SPEECH']}"
        if self.writer_status.cget('text')!=text:self.writer_status.configure(text=text)
        self.refresh_gemini_model_panel()

    def refresh_gemini_model_panel(self):
        if not hasattr(self,'gemini_model_state_label'):
            return
        try:
            snapshot=self.controls['gemini_model_snapshot']()
        except Exception:
            snapshot={'status':'ERRO · controlador indisponível','configured_model':'—',
                      'last_used_model':'não disponível','last_changed_at':None}
        if not isinstance(snapshot,dict):
            snapshot={'status':'ERRO · resposta de estado inválida','configured_model':'—',
                      'selected_model':None,'last_used_model':'não disponível','last_changed_at':None}
        if not getattr(self,'_gemini_model_selection_initialized',False):
            selected=snapshot.get('selected_model') or snapshot.get('configured_model')
            if selected in gemini_model_settings.LABEL_BY_ID:
                self.gemini_model_var.set(gemini_model_settings.LABEL_BY_ID[selected])
            self._gemini_model_selection_initialized=True
        selected=gemini_model_settings.ID_BY_LABEL.get(self.gemini_model_var.get())
        configured=snapshot.get('configured_model','—')
        manual_error=getattr(self,'gemini_model_apply_error',None)
        if manual_error:
            status='ERRO · '+str(manual_error)
        elif selected and selected!=configured:
            status='ALTERAÇÃO PENDENTE · clique em APLICAR MODELO'
        else:
            status=snapshot.get('status','AGUARDANDO AUTORIZAÇÃO')
        self.gemini_model_configured_label.configure(text='Modelo configurado: '+str(configured))
        self.gemini_model_used_label.configure(text='Último modelo realmente usado: '+str(snapshot.get('last_used_model','—')))
        self.gemini_model_state_label.configure(text='Estado: '+str(status))
        changed=snapshot.get('last_changed_at') or 'ainda não alterado pelo painel'
        self.gemini_model_changed_label.configure(text='Última alteração: '+str(changed))
        route=snapshot.get('route','Google AI Studio / Gemini API')
        key='presente no ambiente' if snapshot.get('api_key_present') else 'ausente no ambiente'
        project=snapshot.get('project_label','associação não verificada')
        self.gemini_model_route_label.configure(
            text=f'Rota: {route} · GEMINI_API_KEY {key} · projeto informado: {project}')
        ollama='ATIVADO por ação explícita' if snapshot.get('ollama_enabled') else 'DESATIVADO · sem pré-carregamento ou fallback local'
        self.ollama_model_state_label.configure(text='Ollama local: '+ollama)

    def set_ollama_local(self,enabled):
        try:
            result=self.controls['ollama_set_enabled'](bool(enabled))
        except Exception as error:
            self.ollama_model_state_label.configure(text='Ollama local: ERRO · '+type(error).__name__)
            return False
        if not result.get('ok'):
            self.ollama_model_state_label.configure(text='Ollama local: ERRO · '+str(result.get('code','não aplicado')))
            return False
        self.refresh_gemini_model_panel()
        return True

    def _gemini_model_selection_changed(self):
        self.gemini_model_apply_error=None
        self.refresh_gemini_model_panel()

    def copy_diagnostic(self):
        super().copy_diagnostic()
        monitor=self.monitor()
        if not monitor or not getattr(monitor,'zuko',None):return
        try:existing=self.root.clipboard_get()
        except Exception:existing=''
        writer_component=getattr(monitor,'writer',None)
        writer_snapshot=getattr(writer_component,'snapshot',None)
        writer=writer_snapshot() if callable(writer_snapshot) else {}
        telemetry=monitor.telemetry.snapshot() if hasattr(monitor,'telemetry') else {}
        text='\n'.join(filter(None,[existing,'\nZUKO V2 · Presenter atual',
            *_zuko_metric_lines(monitor.zuko.snapshot(),writer),
            *_legacy_metric_lines(writer,telemetry)]))
        self.root.clipboard_clear();self.root.clipboard_append(text)

    def _tick(self):
        super()._tick()
        monitor=getattr(self,'runtime_monitor',None)
        if monitor and getattr(monitor,'zuko',None):
            monitor.zuko._refresh_provider_status()
            zuko=monitor.zuko
            ready=zuko.litellm.readiness_snapshot()['state']
            grant=zuko.gemini_budget.snapshot(monitor.session_epoch)
            health=dict(monitor.telemetry.snapshot()['health']) if hasattr(monitor,'telemetry') else {}
            health['GEMINI']='SDK/ADC '+ready+' | '+('AUTORIZADO' if grant['authorized'] else 'SEM AUTORIZAÇÃO DE TEXTO')
            if hasattr(self,'health'):self.health.configure(text='\n'.join(f'{key}: {value}' for key,value in health.items()))
            if hasattr(self,'metrics'):
                stats=zuko.snapshot()
                writer_component=getattr(monitor,'writer',None)
                writer_snapshot=getattr(writer_component,'snapshot',None)
                writer=writer_snapshot() if callable(writer_snapshot) else {}
                lines=str(self.metrics.cget('text')).splitlines()
                dynamic_prefixes=('CHAMADAS GEMINI','CALL OK/ERRO','TEXTO ZUKO · PRESENTER ATUAL',
                    'Comentários Presenter:','Gemini:','Modelo Gemini:','TikTok real:','JOINs:','Interação V4:',
                    'Ollama:','Fallback de texto:','Fallback de voz/TTS:',
                    'Cancelamentos de fala:','WRITER LEGADO ·','Duplicatas Gemini bloqueadas:')
                lines=[line for line in lines if not line.startswith(dynamic_prefixes)]
                lines=[('RESP. IA (telemetria legada)'+line[len('RESP. IA'):] if line.startswith('RESP. IA') else
                        'FALLBACK (telemetria legada)'+line[len('FALLBACK'):] if line.startswith('FALLBACK') else
                        'LAT GEMINI (telemetria legada)'+line[len('LAT GEMINI'):] if line.startswith('LAT GEMINI') else
                        line) for line in lines]
                lines.extend(_zuko_metric_lines(stats,writer))
                lines.append('Duplicatas Gemini bloqueadas: '+str(stats['ZUKO_GEMINI_DUPLICATES_BLOCKED']))
                self.metrics.configure(text='\n'.join(lines))
            if hasattr(self,'writer_status') and callable(getattr(getattr(monitor,'writer',None),'snapshot',None)):
                self.refresh_writer_status()

    def _build(self):
        self.registry=HelpRegistry(self);self.control_inventory=[];self.runtime_monitor=None
        self.probe=LocalAvailability();self.short_states={};self.help_keys=[]
        self.root.configure(bg=BG)
        style=ttk.Style(self.root);style.theme_use('clam')
        style.configure('.',font=('Segoe UI',10),background=BG,foreground=TEXT)
        for name,color in [('Base.TFrame',BG),('Panel.TFrame',PANEL)]:style.configure(name,background=color)
        for name,color in [('Body.TLabel',TEXT),('Muted.TLabel',MUTED),('Title.TLabel',TEXT),('CC.TLabel',TEXT)]:style.configure(name,background=BG,foreground=color)
        style.configure('Title.TLabel',font=('Segoe UI',21,'bold'))
        style.configure('Card.TLabelframe',background=BG,bordercolor='#293c55',relief='solid')
        style.configure('Card.TLabelframe.Label',background=BG,foreground='#9ab9df',font=('Segoe UI',10,'bold'))
        style.configure('TButton',padding=(13,9),background='#22334b',foreground=TEXT,borderwidth=0)
        style.map('TButton',background=[('active','#314c70'),('disabled','#172335')],foreground=[('disabled','#6e7e92')])
        style.configure('Primary.TButton',background='#2263c4',foreground='white')
        style.configure('Danger.TButton',background='#71353e',foreground='white')
        style.configure('TNotebook',background=BG,borderwidth=0)
        style.configure('TNotebook.Tab',padding=(15,11),background='#142137',foreground=MUTED)
        style.map('TNotebook.Tab',background=[('selected','#24568c')],foreground=[('selected','white')])
        style.configure('TEntry',fieldbackground='#142338',foreground=TEXT,insertcolor=TEXT,padding=7)
        style.configure('TCombobox',fieldbackground='#142338',foreground=TEXT,padding=6)
        style.map('TCombobox',fieldbackground=[('readonly','#142338')],foreground=[('readonly',TEXT)])
        style.configure('TMenubutton',background='#20334c',foreground=TEXT,padding=(10,7))
        style.configure('TCheckbutton',background=BG,foreground=TEXT,padding=5)
        style.configure('TRadiobutton',background=BG,foreground=TEXT,padding=5)
        style.configure('Treeview',background='#122137',fieldbackground='#122137',foreground=TEXT,rowheight=28)
        style.configure('Treeview.Heading',background='#22334b',foreground=TEXT,padding=7)
        style.map('Treeview',background=[('selected','#24568c')],foreground=[('selected','white')])
        shell=ttk.Frame(self.root,style='Base.TFrame',padding=(16,12));shell.pack(fill='both',expand=True)
        header=ttk.Frame(shell,style='Base.TFrame');header.pack(fill='x',pady=(0,12))
        ttk.Label(header,text='ZUKO LIVE SOCIAL V4',style='Title.TLabel').pack(side='left')
        self.help_button=self.button(header,'AJUDA · F1',lambda:self.open_help('help'),'help',side='right')
        self.live_prepare_button=self.button(header,'INICIAR LIVE',self.toggle_live_preparation,'live_prepare',side='right',style='Primary.TButton')
        self.quick_open=self.button(header,'ABRIR ZUKO 3D',lambda:self.npc_button.invoke(),'npc_open',side='right',style='Primary.TButton')
        self.global_status=ttk.Label(shell,text='Em teste local · nenhuma transmissão iniciada',style='Muted.TLabel')
        self.global_status.pack(anchor='w',pady=(0,10))
        prepare_status_frame=ttk.Frame(shell,style='Base.TFrame',height=72)
        prepare_status_frame.pack(fill='x',pady=(0,8));prepare_status_frame.pack_propagate(False)
        self.live_prepare_status=ttk.Label(prepare_status_frame,text='Preparação não iniciada · nenhuma transmissão pública será iniciada por este botão.',style='Muted.TLabel',wraplength=1100,justify='left')
        self.live_prepare_status.pack(anchor='w',fill='both',expand=True)
        self.live_preparation=LivePreparationController(
            self.root,self.monitor,self._live_preparation_update,
            self.controls['start'],self.controls['stop'])
        self.notebook=ttk.Notebook(shell);self.notebook.pack(fill='both',expand=True)
        self.pages={}
        for name in TABS:
            page=ScrollPage(self.notebook);self.notebook.add(page,text=name);self.pages[name]=page
        ttk.Label(shell,text='F1 ou botão direito: ajuda do controle  •  Rolagem vertical disponível em cada aba',style='Muted.TLabel').pack(anchor='w',pady=(8,0))
        self.build_home();self.build_zuko();self.build_voice();self.build_events();self.build_diagnostics();self.build_help()
        self.root.bind('<F1>',self.focus_help,add='+')

    def register(self,widget,key,callback=''):
        if callable(callback):
            callback_name=getattr(callback,'__qualname__',repr(callback))
            owner=getattr(callback,'__self__',None)
            file='live_monitor.py' if owner and type(owner).__name__=='LiveMonitor' else 'live_dashboard_v2.py'
        else:callback_name=callback;file='live_dashboard_v2.py'
        self.registry.attach(widget,key,callback_name,file)
        self.control_inventory.append({'widget':str(widget),'name':self.registry.entries[key]['name'],'help':key,'callback':callback_name,'file':file})
        return widget

    def button(self,parent,label,callback,key,side='left',style='TButton'):
        widget=ttk.Button(parent,text=label,command=callback,style=style)
        widget.pack(side=side,padx=(0,8),pady=4)
        return self.register(widget,key,callback)

    def row(self,parent):
        frame=ttk.Frame(parent,style='Base.TFrame');frame.pack(fill='x',pady=2);return frame

    def selector(self,parent,label,variable,values,key,command=None):
        frame=self.row(parent);ttk.Label(frame,text=label+'  ',style='Body.TLabel',width=23).pack(side='left')
        widget=ttk.OptionMenu(frame,variable,variable.get(),*values,command=command)
        widget.pack(side='left');self.register(widget,key,command or 'seleção local; consumida pelo controle associado')
        return widget

    def field(self,parent,label,variable=None):
        ttk.Label(parent,text=label,style='Body.TLabel').pack(anchor='w',pady=(8,3))
        widget=ttk.Entry(parent,textvariable=variable);widget.pack(fill='x',pady=(0,5));return widget

    def build_home(self):
        page=self.pages['Início'].body
        launch=card(page,'PREPARAÇÃO DA LIVE · OITO ETAPAS')
        progress_frame=ttk.Frame(launch,style='Base.TFrame',height=170)
        progress_frame.pack(fill='x');progress_frame.pack_propagate(False)
        self.launch_progress=ttk.Label(progress_frame,text='Clique em INICIAR LIVE para verificar os componentes locais.',style='Body.TLabel',justify='left',anchor='nw')
        self.launch_progress.pack(fill='both',expand=True)
        paragraph(page,'Seu ponto de partida',False)
        paragraph(page,'Prepare e teste o personagem aqui. O painel controla eventos e áudio; a janela Godot mostra o ZUKO.',True)
        status=card(page,'VISÃO GERAL')
        for key,label in [('npc','Personagem'),('ai','Inteligência local'),('voice','Voz Microsoft Maria'),('source','Fonte de eventos')]:
            frame=self.row(status);ttk.Label(frame,text=label,width=24,style='Body.TLabel').pack(side='left')
            self.short_states[key]=ttk.Label(frame,text='Verificando…',style='Body.TLabel');self.short_states[key].pack(side='left',fill='x',expand=True)
        actions=card(page,'OPERAÇÃO')
        line=self.row(actions)
        self.home_open=self.button(line,'ABRIR ZUKO 3D',lambda:self.npc_button.invoke(),'npc_open',style='Primary.TButton')
        self.button(line,'INICIAR',self.controls['start'],'start')
        self.button(line,'PAUSAR',self.controls['pause'],'pause')
        self.button(line,'PARAR',self.controls['stop'],'stop',style='Danger.TButton')
        line=self.row(actions)
        self.local_mode_button=self.button(line,'MODO TESTE LOCAL',self.toggle_local_mode,'local')
        self.button(line,'TESTAR INTERAÇÃO',self.open_test,'quick_test')
        self.button(line,'TESTAR VOZ MARIA',self.test_voice,'voice_test')
        guide=card(page,'PRIMEIROS PASSOS')
        paragraph(guide,'1  Confira os quatro estados acima.\n2  Abra o ZUKO e aguarde a confirmação.\n3  Teste a voz Microsoft Maria.\n4  Envie uma mensagem na aba Voz e IA ou simule um evento.\n5  Prepare sua captura no software de transmissão, sem iniciar uma LIVE nesta fase.')
        self.chat=self.text_box(card(page,'CONVERSA RECENTE'),height=8)

    def build_zuko(self):
        page=self.pages['ZUKO'].body
        group=card(page,'PERSONAGEM E APRESENTADOR SÃO ESTADOS DIFERENTES')
        line=self.row(group)
        self.npc_button=self.button(line,'ABRIR ZUKO 3D',None,'npc_open',style='Primary.TButton')
        self.npc_close_button=self.button(line,'FECHAR ZUKO',None,'npc_close');self.npc_close_button.configure(state='disabled')
        self.zuko_overview=paragraph(group,'Personagem: fechado · AUTO: desligado · fala: aguardando')
        self.animation_status=paragraph(group,'Última animação solicitada: nenhuma',True)
        self.movement_status=paragraph(group,'Godot: desconectado · Movimento solicitado (sem retorno do estado do Godot)',True)
        self.zuko_bar=self.row(group)
        paragraph(group,'Abrir o personagem não liga AUTO. Falando significa reprodução de áudio confirmada; Reagindo é uma estimativa do controlador.',True)
        walk=card(page,'CAMINHADA LIVE · SIMULAÇÃO LOCAL')
        line=self.row(walk)
        self.walk_button=ttk.Button(line,text='INICIAR CAMINHADA',command=self.toggle_walk,style='Primary.TButton')
        self.walk_button.pack(side='left',padx=4,pady=4)
        self.live_mode_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(line,text='MODO LIVE · ocultar diagnóstico / 9:16',variable=self.live_mode_var,command=self.apply_live_mode).pack(side='left',padx=12)
        self.walk_status_label=paragraph(walk,'Abra o ZUKO para iniciar a caminhada.',True)
        self.walk_speed=tk.DoubleVar(value=1.0)
        line=self.row(walk)
        ttk.Label(line,text='Velocidade do fundo',style='Body.TLabel').pack(side='left')
        ttk.Scale(line,from_=0.25,to=2.0,variable=self.walk_speed,command=self.schedule_walk_speed,length=250).pack(side='left',padx=12)
        self.live_resolution=tk.StringVar(value='540x960')
        ttk.Label(line,text='Renderização',style='Body.TLabel').pack(side='left')
        self.live_resolution_box=ttk.Combobox(line,textvariable=self.live_resolution,values=['540x960','720x1280','1080x1920'],state='readonly',width=14)
        self.live_resolution_box.pack(side='left',padx=8)
        self.live_resolution_box.bind('<<ComboboxSelected>>',lambda _e:self.apply_live_mode())
        paragraph(walk,'540 × 960 é o padrão leve para a GT 730; 1080 × 1920 é opcional. A janela se ajusta à tela. Desmarque MODO LIVE para restaurar o diagnóstico. Walk fica em loop; reações curtas voltam à caminhada. Movimento manual repetido assume o controle e encerra a caminhada.',True)
        paragraph(walk,'Fundo: panorâmica suave limitada, com ida e volta; sem emendas, deformação ou percurso 3D real. A imagem estática não simula avanço contínuo pela rua.',True)
        movements=card(page,'MOVIMENTOS DO ZUKO')
        paragraph(movements,'Selecione uma animação pelo nome exato do pacote e execute no Godot conectado. Os botões abaixo selecionam; não confirmam que o movimento foi renderizado.',True)
        self.movement_choice=tk.StringVar(value='Idle')
        self.movement_repeat=tk.BooleanVar(value=False)
        self.movement_description=paragraph(movements,'Selecionada: '+MOVEMENT_LABELS['Idle'],True)
        self.movement_buttons={}
        movement_help={}
        for _category,_items in MOVEMENT_GROUPS.items():
            for _clip,_description in _items:
                movement_help['movement_'+_clip.lower()]=(_clip,'Seleciona '+_clip+' ('+_description+').','Escolha a animação e use EXECUTAR MOVIMENTO.','Seleciona somente um nome disponível no Character.gltf.','Godot conectado para execução.','A animação pode não importar ou parecer como esperado até ser testada no Godot.','Selecione outra animação ou volte ao Idle.')
        movement_help.update({
            'movement_execute':('EXECUTAR MOVIMENTO','Envia a animação selecionada para o Godot.','Depois de selecionar um clipe e abrir o personagem.','Envia somente um comando local pela ponte NPC.','Godot conectado e sem pausa manual.','Sobrepõe temporariamente as reações automáticas.','Use VOLTAR AO IDLE para liberar AUTO.'),
            'movement_stop':('PARAR MOVIMENTO','Interrompe o clipe atual e mantém a prioridade manual.','Quando quiser interromper a simulação.','Godot conectado.','Eventos automáticos permanecem suspensos até Idle.','Não equivale à pausa retomável.','Use VOLTAR AO IDLE para retomar AUTO.'),
            'movement_return_idle':('VOLTAR AO IDLE','Retorna ao estado Idle e libera a prioridade manual.','Ao terminar a simulação.','Godot conectado.','Um evento automático poderá ser processado depois.','Não encerra o processo Godot.','Nenhuma reversão necessária.'),
            'movement_pause':('PAUSAR MOVIMENTO','Pausa o clipe manual atual.','Durante a simulação.','Um movimento atual e Godot conectado.','AUTO fica suspenso até retorno ao Idle.','A pausa preserva posição para retomada.','Use RETOMAR.'),
            'movement_resume':('RETOMAR MOVIMENTO','Continua o clipe manual pausado.','Depois de PAUSAR MOVIMENTO.','Um movimento pausado e Godot conectado.','AUTO permanece suspenso.','Retorna ao ponto salvo do clipe.','Use PARAR ou VOLTAR AO IDLE.'),
            'movement_walk_wave':('WALK + WAVE','Ativa a combinação local de caminhada e aceno na caminhada automática de inatividade.','Personagem Godot aberto e MOVIMENTOS AUTOMÁTICOS ligado.','Não altera os clipes originais; eventos, fala e controles manuais mantêm suas prioridades.','Desmarque para voltar a Walk.','A cena continua se deslocando durante o clipe combinado; consulte os registros WALK_WAVE na aba Diagnóstico.','Desmarque WALK + WAVE.'),
        })
        for _gesture in ('Yes','No'):
            movement_help['movement_walk_'+_gesture.lower()]=('WALK + '+_gesture.upper(),'Permite o gesto '+_gesture+' durante a caminhada automática e em comandos manuais desse gesto.','Caminhada ativa e runtime Godot conectado.','Preserva o ciclo de caminhada e a animação original; a combinação começa desligada.','Desmarque para executar '+_gesture+' como ação separada.','Prioridades manuais e eventos continuam valendo; veja WALK_COMBO na aba Diagnóstico.','Desmarque WALK + '+_gesture.upper()+'.')
        for _key,_values in movement_help.items():
            _name,_purpose,_when,_result,_requirements,_risk,_undo=_values
            self.registry.entries[_key]={'name':_name,'purpose':_purpose,'when':_when,'result':_result,'requirements':_requirements,'risk':_risk,'undo':_undo,'example':'Use os controles da seção MOVIMENTOS DO ZUKO.','callback':'','file':'live_dashboard_v2.py','availability':'Sempre disponível na V2.'}
        for category,items in MOVEMENT_GROUPS.items():
            section=ttk.LabelFrame(movements,text=category,style='Card.TLabelframe',padding=8)
            section.pack(fill='x',pady=6)
            for index,(clip,description) in enumerate(items):
                button=ttk.Button(section,text=description,command=lambda c=clip,d=description:self.select_movement(c,d))
                button.grid(row=index//4,column=index%4,sticky='ew',padx=4,pady=4)
                section.columnconfigure(index%4,weight=1)
                self.movement_buttons[clip]=self.register(button,'movement_'+clip.lower(),'Seleciona '+description+'; execute pelo controle MOVIMENTO')
        line=self.row(movements)
        self.button(line,'EXECUTAR MOVIMENTO',self.execute_movement,'movement_execute',style='Primary.TButton')
        self.button(line,'PARAR MOVIMENTO',lambda:self.control_movement('stop'),'movement_stop',style='Danger.TButton')
        self.button(line,'VOLTAR AO IDLE',lambda:self.control_movement('idle'),'movement_return_idle')
        self.button(line,'PAUSAR',lambda:self.control_movement('pause'),'movement_pause')
        self.button(line,'RETOMAR',lambda:self.control_movement('resume'),'movement_resume')
        ttk.Checkbutton(movements,text='Repetir movimento (quando suportado)',variable=self.movement_repeat).pack(anchor='w',pady=4)
        self.auto_movements_var=tk.BooleanVar(master=self.root,value=False)
        self.auto_movements_button=ttk.Checkbutton(movements,text='MOVIMENTOS AUTOMÁTICOS — DESLIGADO',variable=self.auto_movements_var,command=self.toggle_auto_movements)
        self.auto_movements_button.pack(anchor='w',pady=4)
        self.auto_movements_status=paragraph(movements,'Seleção local e determinística · preferência desligada até você ativar.',True)
        self.walk_cycle_seconds=tk.IntVar(master=self.root,value=180)
        self.rest_cycle_seconds=tk.IntVar(master=self.root,value=30)
        cycle=self.row(movements)
        ttk.Label(cycle,text='Ciclo automático · andar (s)').pack(side='left',padx=(4,6))
        walk_spin=ttk.Spinbox(cycle,from_=1,to=3600,width=6,textvariable=self.walk_cycle_seconds)
        walk_spin.pack(side='left',padx=(0,14))
        self.register(walk_spin,'walk_cycle_seconds','Define a duração da caminhada automática, de 1 a 3600 segundos.')
        ttk.Label(cycle,text='parado (s)').pack(side='left',padx=(0,6))
        rest_spin=ttk.Spinbox(cycle,from_=1,to=3600,width=6,textvariable=self.rest_cycle_seconds)
        rest_spin.pack(side='left',padx=(0,10))
        self.register(rest_spin,'rest_cycle_seconds','Define a duração da pausa entre caminhadas automáticas, de 1 a 3600 segundos.')
        self.button(cycle,'SALVAR CICLO',self.save_walk_cycle,'walk_cycle_save')
        self.walk_cycle_status=paragraph(movements,'Padrão local: 180 s andando · 30 s parado. O ciclo só atua quando MOVIMENTOS AUTOMÁTICOS estiver ligado.',True)
        self.walk_wave_var=tk.BooleanVar(master=self.root,value=False)
        self.walk_wave_button=ttk.Checkbutton(movements,text='WALK + WAVE — DESLIGADO',variable=self.walk_wave_var,command=self.toggle_walk_wave)
        self.walk_wave_button.pack(anchor='w',pady=4)
        self.register(self.walk_wave_button,'movement_walk_wave',self.toggle_walk_wave)
        self.walk_wave_status=paragraph(movements,'Combinação local desativada por padrão; atua somente na caminhada automática.',True)
        self.walk_combo_vars={};self.walk_combo_buttons={};self.walk_combo_statuses={}
        for gesture in ('Yes','No'):
            variable=tk.BooleanVar(master=self.root,value=False)
            button=ttk.Checkbutton(movements,text='WALK + '+gesture.upper()+' — DESLIGADO',variable=variable,command=lambda g=gesture:self.toggle_walk_combo(g))
            button.pack(anchor='w',pady=2)
            self.register(button,'movement_walk_'+gesture.lower(),self.toggle_walk_combo)
            status=paragraph(movements,'Combinação local desativada por padrão.',True)
            self.walk_combo_vars[gesture]=variable;self.walk_combo_buttons[gesture]=button;self.walk_combo_statuses[gesture]=status
        self.root.after(0,self.load_walk_cycle)
        self.root.after(0,self.load_walk_wave)
        presenter=card(page,'APRESENTAÇÃO')
        self.presenter_mode=tk.StringVar(value='OFF')
        self.selector(presenter,'Modo do apresentador',self.presenter_mode,['OFF','ASSISTIDO','AUTO'],'presenter_mode',self.controls['presenter_mode'])
        line=self.row(presenter)
        for label,key,command in [('PAUSAR APRESENTADOR','presenter_pause','PAUSE'),('RETOMAR','resume','RESUME'),('PRÓXIMO ASSUNTO','next','NEXT'),('PUXAR ASSUNTO','pull','PULL')]:
            self.button(line,label,lambda c=command:self.controls['presenter_control'](c),key)
        self.button(self.row(presenter),'FALAR AGORA',self.controls['presenter_now'],'presenter_now')
        self.presenter_summary=paragraph(presenter,'Apresentador aguardando',True)
        self.director_summary=paragraph(card(page,'FILA DO DIRETOR'),'Aguardando',True)
        details=card(page,'CONTEXTO DA CONVERSA')
        self.info={}
        for key in ['ASSUNTO','FALANDO COM','PERGUNTA','JARVIS']:
            paragraph(details,'Resposta do ZUKO' if key=='JARVIS' else key.title(),True)
            self.info[key]=paragraph(details,'—')
        self.memory_summary=paragraph(details,'Memória de sessão',True)
        self.button(self.row(details),'NOVA SESSÃO LIVE',self.controls['new_live_session'],'session')

    def toggle_walk(self):
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if not npc or not npc.set_presentation(walking=not npc.walking_requested):
            self.walk_status_label.configure(text='Abra o personagem e retome a pausa antes de iniciar.')

    def apply_live_mode(self):
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if not npc or not npc.set_presentation(live=self.live_mode_var.get(),resolution=self.live_resolution.get()):
            self.walk_status_label.configure(text='Abra o personagem para aplicar o modo de apresentação.')

    def schedule_walk_speed(self,_value=None):
        if getattr(self,'_walk_speed_after',None): self.root.after_cancel(self._walk_speed_after)
        self._walk_speed_after=self.root.after(250,self.send_walk_speed)

    def send_walk_speed(self):
        self._walk_speed_after=None
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if npc: npc.set_presentation(speed=round(self.walk_speed.get(),2))

    def select_movement(self,clip,description):
        self.movement_choice.set(clip)
        self.movement_description.configure(text='Selecionada: '+description)

    def toggle_auto_movements(self):
        enabled=bool(self.auto_movements_var.get())
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if not npc or not npc.set_auto_movements(enabled):
            self.auto_movements_var.set(bool(getattr(npc,'auto_movements_enabled',False)))
            self.auto_movements_button.configure(text='MOVIMENTOS AUTOMÁTICOS — '+('LIGADO' if self.auto_movements_var.get() else 'DESLIGADO'))
            self.auto_movements_status.configure(text=getattr(npc,'error','Abra o painel ZUKO para aplicar a preferência.') if npc else 'Controlador do ZUKO indisponível.')
            return
        self.auto_movements_button.configure(text='MOVIMENTOS AUTOMÁTICOS — '+('LIGADO' if enabled else 'DESLIGADO'))
        cycle=f"ciclo de {npc.idle_walk_seconds} s andando / {npc.idle_rest_seconds} s parado" if npc else 'ciclo configurado'
        self.auto_movements_status.configure(text=('Ativo: reações seguras e '+cycle+'.' if enabled else 'Desativado: somente comandos manuais e caminhada solicitada.'))

    def load_walk_cycle(self):
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if npc:
            walk,rest=npc.get_idle_cycle()
            self.walk_cycle_seconds.set(walk);self.rest_cycle_seconds.set(rest)
            self.walk_cycle_status.configure(text=f'Ciclo salvo: {walk} s andando · {rest} s parado. Requer MOVIMENTOS AUTOMÁTICOS ligado.')

    def save_walk_cycle(self):
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        try:walk,rest=int(self.walk_cycle_seconds.get()),int(self.rest_cycle_seconds.get())
        except (ValueError,tk.TclError):
            self.walk_cycle_status.configure(text='Informe tempos inteiros entre 1 e 3600 segundos.')
            return
        if not npc or not npc.set_idle_cycle(walk,rest):
            self.walk_cycle_status.configure(text=getattr(npc,'error','Controlador do ZUKO indisponível.') if npc else 'Controlador do ZUKO indisponível.')
            return
        self.walk_cycle_status.configure(text=f'Ciclo salvo: {walk} s andando · {rest} s parado. Requer MOVIMENTOS AUTOMÁTICOS ligado.')

    def load_walk_wave(self):
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if npc:
            enabled=npc.get_walk_wave()
            self.walk_wave_var.set(enabled)
            self.walk_wave_button.configure(text='WALK + WAVE — '+('LIGADO' if enabled else 'DESLIGADO'))
            self.walk_wave_status.configure(text='Ativo na caminhada automática.' if enabled else 'Combinação local desativada por padrão; atua somente na caminhada automática.')

    def toggle_walk_wave(self):
        enabled=bool(self.walk_wave_var.get())
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if not npc or not npc.set_walk_wave(enabled):
            self.walk_wave_var.set(bool(npc.get_walk_wave()) if npc else False)
            self.walk_wave_button.configure(text='WALK + WAVE — '+('LIGADO' if self.walk_wave_var.get() else 'DESLIGADO'))
            self.walk_wave_status.configure(text=getattr(npc,'error','Abra o painel ZUKO para aplicar a combinação.') if npc else 'Controlador do ZUKO indisponível.')
            return
        self.walk_wave_button.configure(text='WALK + WAVE — '+('LIGADO' if enabled else 'DESLIGADO'))
        if not enabled:detail='Desativado; a caminhada automática usará Walk.'
        elif not npc.auto_movements_enabled:detail='Habilitado; requer MOVIMENTOS AUTOMÁTICOS ligado.'
        else:detail='Ativo na próxima caminhada automática.'
        self.walk_wave_status.configure(text=detail)

    def toggle_walk_combo(self,gesture):
        enabled=bool(self.walk_combo_vars[gesture].get())
        monitor=self.monitor();npc=getattr(monitor,'npc',None) if monitor else None
        if not npc or not npc.set_walk_combo(gesture,enabled):
            self.walk_combo_vars[gesture].set(bool(npc.walk_combo_enabled.get(gesture,False)) if npc else False)
            self.walk_combo_buttons[gesture].configure(text='WALK + '+gesture.upper()+' — '+('LIGADO' if self.walk_combo_vars[gesture].get() else 'DESLIGADO'))
            self.walk_combo_statuses[gesture].configure(text=getattr(npc,'error','Abra o painel ZUKO para aplicar a combinação.') if npc else 'Controlador do ZUKO indisponível.')
            return
        self.walk_combo_buttons[gesture].configure(text='WALK + '+gesture.upper()+' — '+('LIGADO' if enabled else 'DESLIGADO'))
        detail=('Aguardando confirmação do Godot.' if npc.state=='ACTIVE' else 'Preferência salva; aguardando abrir o personagem.') if enabled else 'Desativado; a ação usa a animação original.'
        self.walk_combo_statuses[gesture].configure(text=detail)

    def execute_movement(self):
        monitor=self.monitor()
        npc=getattr(monitor,'npc',None) if monitor else None
        if npc and npc.manual_animation(self.movement_choice.get(),self.movement_repeat.get()):
            self.animation_status.configure(text='Última animação solicitada: '+MOVEMENT_LABELS.get(self.movement_choice.get(),self.movement_choice.get()))
        else:
            self.movement_status.configure(text='Godot: indisponível · Abra o ZUKO 3D antes de executar.')

    def control_movement(self,command):
        monitor=self.monitor()
        npc=getattr(monitor,'npc',None) if monitor else None
        if npc and npc.manual_control(command):
            names={'stop':'Parar solicitado','idle':'Idle solicitado','pause':'Pausa solicitada','resume':'Retomada solicitada'}
            self.animation_status.configure(text='Última animação solicitada: '+names[command])
        else:
            self.movement_status.configure(text='Godot: indisponível · Abra o ZUKO 3D antes de enviar comandos.')

    def build_voice(self):
        page=self.pages['Voz e IA'].body
        model_card=card(page,'MODELO GEMINI TEXT · ZUKO V4')
        paragraph(model_card,'O modelo selecionado controla o Presenter V4 para comentários, eventos sociais e planejamento autônomo. Aplicar apenas salva a configuração; não faz chamada de API.',True)
        line=self.row(model_card)
        ttk.Label(line,text='Modelo Gemini:',style='Body.TLabel',width=23).pack(side='left')
        self.gemini_model_var=tk.StringVar(master=self.root,
            value=gemini_model_settings.LABEL_BY_ID[gemini_model_settings.PREFERRED_MODEL])
        self.gemini_model_selector=ttk.Combobox(line,textvariable=self.gemini_model_var,
            values=[label for label,_model,_stage in gemini_model_settings.CATALOG],
            state='readonly',width=30)
        self.gemini_model_selector.pack(side='left',padx=(0,8))
        self.gemini_model_selector.bind('<<ComboboxSelected>>',lambda _event:self._gemini_model_selection_changed())
        self.register(self.gemini_model_selector,'gemini_model_select','LiveMonitor.apply_gemini_model após clique em APLICAR MODELO')
        line=self.row(model_card)
        self.button(line,'APLICAR MODELO',self.apply_selected_gemini_model,'gemini_model_apply',style='Primary.TButton')
        self.button(line,'RESTAURAR ÚLTIMO FUNCIONAL',self.restore_functional_gemini_model,'gemini_model_restore')
        self.gemini_model_configured_label=paragraph(model_card,'Modelo configurado: carregando…',True)
        self.gemini_model_used_label=paragraph(model_card,'Último modelo realmente usado: —',True)
        self.gemini_model_state_label=paragraph(model_card,'Estado: carregando…',True)
        self.gemini_model_changed_label=paragraph(model_card,'Última alteração: —',True)
        self.gemini_model_route_label=paragraph(model_card,'Rota Gemini API; chave nunca exibida.',True)
        self.ollama_model_state_label=paragraph(model_card,'Ollama local: DESATIVADO · sem pré-carregamento ou fallback local',True)
        line=self.row(model_card)
        self.button(line,'ATIVAR OLLAMA LOCAL',lambda:self.set_ollama_local(True),'ollama_enable')
        self.button(line,'DESATIVAR OLLAMA LOCAL',lambda:self.set_ollama_local(False),'ollama_disable')
        paragraph(model_card,'O ID será aplicado sem troca silenciosa. A confirmação de compatibilidade com a conta exige uma chamada de texto autorizada; Gemini 3.1 Pro está em prévia. Limites e autorização de sessão continuam valendo.',True)
        self._gemini_model_selection_initialized=False
        self.local_panel=card(page,'CONVERSAR COM JARVIS / ZUKO · ENTRADA LOCAL')
        paragraph(self.local_panel,'O personagem responde como ZUKO. Os controles de conversa legados continuam usando seus callbacks existentes.',True)
        self.field(self.local_panel,'Nome do espectador / autor da conversa',self.local_author)
        self.microphones=self.selector(self.local_panel,'Microfone',self.local_microphone,['Padrão do sistema'],'microphone')
        line=self.row(self.local_panel)
        for label,var,key in [('ENVIAR AUTOMATICAMENTE',self.local_auto_send,'auto_send'),('FALAR RESPOSTAS',self.local_speak,'speak')]:
            w=ttk.Checkbutton(line,text=label,variable=var);w.pack(side='left',padx=(0,10));self.register(w,key,'variável consumida por send_local/start_local_voice')
        paragraph(self.local_panel,'Para silenciar o ZUKO, use PAUSAR ZUKO. A preferência Falar respostas é legada e não é aplicada pelo controlador ZUKO atual.',True)
        paragraph(self.local_panel,'Mensagem (Enter envia; Shift+Enter cria uma nova linha)')
        self.local_text=tk.Text(self.local_panel,height=4,bg='#122137',fg=TEXT,insertbackground=TEXT,font=('Segoe UI',11),wrap='word',relief='flat',padx=10,pady=8)
        self.local_text.pack(fill='x');self.local_text.bind('<Return>',self._send_on_enter)
        self.root.bind('<Control-Return>',self._hotkey_send);self.root.bind('<Control-m>',self._hotkey_voice)
        line=self.row(self.local_panel)
        self.button(line,'ENVIAR',self.send_local,'send',style='Primary.TButton')
        self.voice_button=self.button(line,'FALAR PELO MICROFONE',self.toggle_voice,'mic')
        self.button(line,'PARAR JARVIS',self.controls['stop_jarvis'],'stop_voice',style='Danger.TButton')
        line=self.row(self.local_panel)
        self.button(line,'NOVA CONVERSA',lambda:self.controls['new_local_conversation'](self.local_author.get()),'new_conversation')
        self.button(line,'RESET SESSÃO LOCAL',self.controls['reset_local_session'],'reset')
        self.voice_last_response=paragraph(self.local_panel,'Última resposta: aguardando',True)
        ttk.Label(self.local_panel,textvariable=self.local_transcript,style='Body.TLabel',wraplength=780).pack(anchor='w',pady=8)
        voice=card(page,'VOZ DO ZUKO')
        import zuko_voice_config as voice_config
        saved_limits=gemini_limits.load_limits()
        self._saved_gemini_text_limit=saved_limits['gemini_text']
        voice_config.configure_limit(saved_limits['gemini_tts'])
        active=voice_config.load()
        self.voice_engine=tk.StringVar(value=active['engine'])
        self._last_voice_engine=active['engine']
        self.voice_selection=tk.StringVar(value=active.get('voice') or 'Puck')
        self.voice_style=tk.StringVar(value=active.get('style',voice_config.DEFAULT['style']))
        self.gemini_text_limit_var=tk.IntVar(master=self.root,value=saved_limits['gemini_text'] or 100)
        self.gemini_text_unlimited_var=tk.BooleanVar(master=self.root,value=saved_limits['gemini_text'] is None)
        self.gemini_text_status_var=tk.StringVar(master=self.root,value='Gemini texto · bloqueado')
        self.voice_test_text=tk.StringVar(value='Eu sou o ZUKO! Meu café entrou no modo economia de energia, mas a diversão continua ligada!')
        self.selector(voice,'Motor',self.voice_engine,['Microsoft Maria','Gemini TTS'],'voice_engine',self._voice_engine_changed)
        self.voice_selector=self.selector(voice,'Voz Gemini',self.voice_selection,['Puck','Fenrir'],'voice',self._voice_selection_changed)
        self.selector(voice,'Estilo vocal',self.voice_style,[
            'Cartoon masculino jovem, engraçado e expressivo.',
            'Natural, jovem e descontraído.',
            'Superanimado, expressivo e engraçado.',
            'Personalizado'
        ],'voice_style',self._voice_style_changed)
        paragraph(voice,'Estilo Gemini aplicado como instrução textual; não há controle técnico de pitch ou velocidade neste painel.',True)
        self.voice_custom_style=ttk.Entry(voice);self.voice_custom_style.insert(0,active.get('style',voice_config.DEFAULT['style']))
        self.voice_custom_style.pack(fill='x',pady=(0,5))
        self.field(voice,'Texto para Maria (Gemini usa amostras locais já geradas)',self.voice_test_text)
        line=self.row(voice)
        self.button(line,'TESTAR VOZ',self.preview_selected_voice,'voice_test',style='Primary.TButton')
        self.button(line,'COMPARAR VOZES',self.compare_voice_previews,'voice_compare')
        self.button(line,'SALVAR CONFIGURAÇÃO',self.save_voice_settings,'voice_save')
        self.button(line,'RESTAURAR MARIA',self.restore_maria,'voice_restore')
        self.button(line,'PARAR ÁUDIO',self.stop_voice_preview,'voice_preview_stop',style='Danger.TButton')
        paragraph(voice,'Limites Gemini salvos são restaurados ao abrir o painel e reaplicados por INICIAR LIVE. ILIMITADO remove o teto interno; não significa uso gratuito. Chamadas podem gerar cobrança.',True)
        line=self.row(voice)
        ttk.Label(line,text='Gemini Text · chamadas/sessão (1–100):',style='Body.TLabel').pack(side='left',padx=(0,8))
        self.gemini_text_limit_spin=ttk.Spinbox(line,from_=1,to=100,width=4,textvariable=self.gemini_text_limit_var)
        self.gemini_text_limit_spin.pack(side='left',padx=(0,8))
        self.gemini_text_unlimited=ttk.Checkbutton(line,text='ILIMITADO (sem teto interno)',variable=self.gemini_text_unlimited_var,command=lambda:self._toggle_limit_spin(self.gemini_text_limit_spin,self.gemini_text_unlimited_var))
        self.gemini_text_unlimited.pack(side='left',padx=(0,8))
        self._toggle_limit_spin(self.gemini_text_limit_spin,self.gemini_text_unlimited_var)
        self.button(line,'AUTORIZAR TEXTO',self.authorize_gemini_text,'gemini_authorize',style='Primary.TButton')
        self.button(line,'REVOGAR TEXTO',self.revoke_gemini_text,'gemini_revoke',style='Danger.TButton')
        ttk.Label(voice,textvariable=self.gemini_text_status_var,style='Muted.TLabel').pack(anchor='w',pady=(0,6))
        self.gemini_text_counter=paragraph(voice,'Gemini Text · 0 chamadas usadas nesta sessão',True)
        line=self.row(voice)
        ttk.Label(line,text='Gemini TTS · chamadas/sessão (1–100):',style='Body.TLabel').pack(side='left',padx=(0,8))
        self.voice_call_limit=tk.StringVar(value=str(saved_limits['gemini_tts'] or 1))
        self.voice_unlimited_var=tk.BooleanVar(master=self.root,value=saved_limits['gemini_tts'] is None)
        self.voice_limit_spin=ttk.Spinbox(line,from_=1,to=voice_config.MAX_SESSION_CALLS,width=4,textvariable=self.voice_call_limit)
        self.voice_limit_spin.pack(side='left',padx=(0,8))
        self.voice_unlimited=ttk.Checkbutton(line,text='ILIMITADO (sem teto interno)',variable=self.voice_unlimited_var,command=lambda:self._toggle_limit_spin(self.voice_limit_spin,self.voice_unlimited_var))
        self.voice_unlimited.pack(side='left',padx=(0,8))
        self._toggle_limit_spin(self.voice_limit_spin,self.voice_unlimited_var)
        self.button(line,'AUTORIZAR TTS',self.authorize_voice_tts,'voice_authorize',style='Primary.TButton')
        self.button(line,'REVOGAR TTS',self.revoke_voice_tts,'voice_revoke',style='Danger.TButton')
        line=self.row(voice)
        self.button(line,'SALVAR LIMITES',self.save_gemini_limits,'gemini_limits_save',style='Primary.TButton')
        self.gemini_tts_counter=paragraph(voice,'Gemini TTS · 0 chamadas usadas nesta sessão',True)
        self.voice_active=paragraph(voice,'Voz ativa: '+active['engine']+(' · '+active['voice'] if active.get('voice') else ''),True)
        self.voice_latency=paragraph(voice,'Histórico Gemini (2 testes anteriores) · Puck: 5,22s geração / 5,29s até áudio · Fenrir: 5,00s / 5,01s. A pré-escuta local não mede geração.',True)
        self.voice_warning=paragraph(voice,'Gemini TTS requer autorização própria, separada do Gemini texto; ambas começam bloqueadas.',True)
        self._voice_engine_changed()
        self._refresh_voice_status()
        self.refresh_gemini_model_panel()
        ai=card(page,'PROVEDOR DE TEXTO ZUKO')
        paragraph(ai,'O ZUKO gera respostas com Gemini via Google AI Studio/Gemini API e LiteLLM quando o texto está autorizado. Ollama fica desativado até ativação explícita. TTS tem autorização independente.')
        paragraph(ai,'A seleção vale também no teste local. Selecione GEMINI+ e use AUTORIZAR TEXTO para liberar a sessão. A seleção não concede autorização automaticamente; o resultado e o motivo de fallback aparecem abaixo.',True)
        self.writer_mode=tk.StringVar(value='MISTO')
        line=self.row(ai)
        for mode in ['MISTO','GEMINI+']:
            w=ttk.Radiobutton(line,text=mode,value=mode,variable=self.writer_mode,command=lambda:self.controls['writer_mode'](self.writer_mode.get()))
            w.pack(side='left',padx=8);self.register(w,'writer',self.controls['writer_mode'])
        self.writer_status=paragraph(ai,'Seleção: MISTO | Última resposta: aguardando',True)
        v3_help={
            'v3_auto':('MODO AUTÔNOMO','Inicia ou encerra a programação gerada por IA na sessão local ou na fonte já iniciada.'),
            'v3_mode':('INTENSIDADE','Ajusta intervalos, pausas, desafios e intensidade máxima dos gestos.'),
            'v4_plan':('APLICAR TEMA E FREQUÊNCIA','Sugere um tema para a próxima fala e define intervalo de 10 a 300 segundos após concluir a fala. Não interrompe o áudio atual nem autoriza Gemini.'),
            'v3_pause':('PAUSAR PROGRAMA','Pausa ZUKO e cancela trabalho pendente pelo Director e pela fila de voz existentes.'),
            'v3_resume':('RETOMAR PROGRAMA','Retoma o programa após a pausa manual, respeitando a cadência da voz.'),
            'v3_end':('ENCERRAR PROGRAMA','Desliga autonomia e salva um resumo agregado da sessão; não inicia outra sessão.'),
            'v3_limits':('APLICAR LIMITES V3','Aplica limites adicionais de chamadas autônomas, minuto e reserva para público, sem alterar a autorização Gemini existente.'),
            'v3_reflection':('REFLEXÃO GEMINI OPCIONAL','Permite sugestões curtas de programação. Exige autorização de texto e usa sua cota; começa desligada.'),
            'v3_review_approve':('APROVAR PADRÃO','Aprova um padrão recorrente para ajustar levemente a variedade de quadros; não modifica regras nem prompt.'),
            'v3_review_reject':('REJEITAR PADRÃO','Mantém o padrão selecionado fora dos ajustes de variedade.'),
        }
        for key,(name,purpose) in v3_help.items():
            self.registry.entries[key]={'name':name,'purpose':purpose,'when':'Durante uma sessão local controlada ou fonte já iniciada.',
                'result':purpose,'requirements':'ZUKO V2 aberto; para Gemini, autorização de texto existente.',
                'risk':'Conteúdo Gemini autorizado consome os limites existentes; nenhuma transmissão é iniciada por este controle.',
                'undo':'Use PAUSAR ou ENCERRAR PROGRAMA; padrões aprovados podem ser rejeitados.',
                'example':'Comece com teste local e MODO AUTÔNOMO desligado até estar pronto.',
                'callback':'','file':'live_dashboard_v2.py','availability':'Na aba Voz e IA da V2.'}
        autonomous=card(page,'ZUKO V4 · AUTONOMIA CONVERSACIONAL')
        paragraph(autonomous,'Conduz uma resenha do cotidiano com conteúdo gerado por IA. Começa desligado; habilitar não inicia uma fonte nem transmissão. Os limites Gemini Text existentes continuam obrigatórios.',True)
        line=self.row(autonomous)
        self.v3_enabled=tk.BooleanVar(master=self.root,value=False)
        toggle=ttk.Checkbutton(line,text='AUTONOMIA LIGADA/DESLIGADA',variable=self.v3_enabled,command=self.toggle_autonomy)
        toggle.pack(side='left',padx=4);self.register(toggle,'v3_auto','ZukoPresenter.set_auto')
        self.v3_mode=tk.StringVar(master=self.root,value='NORMAL')
        mode=ttk.Combobox(line,textvariable=self.v3_mode,values=['CALMO','NORMAL','ALTA ENERGIA'],state='readonly',width=16)
        mode.pack(side='left',padx=8);mode.bind('<<ComboboxSelected>>',lambda _event:self.apply_autonomy_mode())
        self.register(mode,'v3_mode','AutonomousEngine.set_mode')
        self.button(line,'PAUSAR',lambda:self.autonomy_pause(True),'v3_pause')
        self.button(line,'RETOMAR',lambda:self.autonomy_pause(False),'v3_resume')
        self.button(line,'ENCERRAR PROGRAMA',self.end_autonomy,'v3_end',style='Danger.TButton')
        line=self.row(autonomous)
        ttk.Label(line,text='Tema sugerido (opcional)',style='Body.TLabel').pack(side='left',padx=4)
        self.v4_topic=tk.StringVar(master=self.root,value='')
        self._v4_plan_syncing=False
        self._v4_last_confirmed=None
        self._v4_last_applied=''
        self._v4_plan_error=''
        topic=ttk.Entry(line,textvariable=self.v4_topic,width=38)
        topic.pack(side='left',fill='x',expand=True,padx=6)
        self.v4_topic.trace_add('write',self._v4_plan_edited)
        self.register(topic,'v4_plan','AutonomousEngine.configure_planning')
        line=self.row(autonomous)
        self.v4_interval=tk.IntVar(master=self.root,value=25)
        ttk.Label(line,text='Intervalo entre falas (s)',style='Body.TLabel').pack(side='left',padx=4)
        frequency=ttk.Spinbox(line,from_=10,to=300,width=5,textvariable=self.v4_interval)
        frequency.pack(side='left',padx=6)
        self.v4_interval.trace_add('write',self._v4_plan_edited)
        self.register(frequency,'v4_plan','AutonomousEngine.configure_planning')
        self.button(line,'APLICAR TEMA E FREQUÊNCIA',self.apply_autonomy_plan,'v4_plan')
        self.v4_plan_status=paragraph(autonomous,
            'TEMA ATIVO: não confirmado · INTERVALO ATIVO: não confirmado · STATUS: aguardando controlador · ÚLTIMA APLICAÇÃO: —',True)
        self.v4_pending_status=paragraph(autonomous,'Comentários aguardando: 0 · eventos aguardando: 0',True)
        self.v4_real_status=paragraph(autonomous,'Presentes e seguidores reais: ainda não verificados.',True)
        line=self.row(autonomous)
        self.v3_call_limit=tk.IntVar(master=self.root,value=20)
        self.v3_rpm=tk.IntVar(master=self.root,value=2)
        self.v3_reserve=tk.IntVar(master=self.root,value=10)
        for label,variable,minimum,maximum in [('Chamadas autônomas/sessão',self.v3_call_limit,1,100),
                ('Por minuto',self.v3_rpm,1,4),('Reserva para público',self.v3_reserve,0,100)]:
            ttk.Label(line,text=label,style='Body.TLabel').pack(side='left',padx=4)
            ttk.Spinbox(line,from_=minimum,to=maximum,width=4,textvariable=variable).pack(side='left',padx=4)
        self.button(line,'APLICAR LIMITES V3',self.apply_autonomy_limits,'v3_limits')
        self.v3_status=paragraph(autonomous,'Autônomo desligado · nenhum programa inicia ao abrir o Dashboard.',True)
        line=self.row(autonomous)
        self.v3_reflection_gemini=tk.BooleanVar(master=self.root,value=False)
        reflection=ttk.Checkbutton(line,text='Reflexão Gemini opcional · usa a autorização e a cota de texto',
            variable=self.v3_reflection_gemini,command=self.apply_reflection_mode)
        reflection.pack(side='left',padx=4);self.register(reflection,'v3_reflection','LiveDashboardV2.apply_reflection_mode')
        self.v3_review_frame=tk.StringVar(master=self.root,value='')
        self.v3_review_selector=ttk.Combobox(line,textvariable=self.v3_review_frame,values=[],state='readonly',width=23)
        self.v3_review_selector.pack(side='left',padx=8)
        self.button(line,'APROVAR PADRÃO',lambda:self.review_autonomy_pattern(True),'v3_review_approve')
        self.button(line,'REJEITAR PADRÃO',lambda:self.review_autonomy_pattern(False),'v3_review_reject')
        self.v3_learning_status=paragraph(autonomous,'Aprendizado entre sessões exige evidência recorrente e revisão. Nenhum identificador pessoal é necessário.',True)
        self.build_soundtrack(page)

    def build_soundtrack(self,page):
        descriptions={
            'music_enable':('ATIVAR TRILHA','Ativa a playlist local no canal de música; começa desligada a cada abertura.'),
            'music_add':('ADICIONAR MÚSICAS','Escolhe MP3/WAV locais e pede confirmação dos direitos de transmissão; não baixa arquivos.'),
            'music_remove':('REMOVER FAIXA','Remove da playlist sem apagar o arquivo de áudio.'),
            'music_up':('SUBIR FAIXA','Move a faixa selecionada para cima.'),
            'music_down':('DESCER FAIXA','Move a faixa selecionada para baixo.'),
            'music_clear':('LIMPAR PLAYLIST','Esvazia a playlist e para a trilha, preservando os arquivos locais.'),
            'music_play':('TOCAR SELECIONADA','Inicia explicitamente a faixa escolhida; a lista volta ao início após a última faixa.'),
            'music_prev':('FAIXA ANTERIOR','Volta à faixa anterior da playlist.'),
            'music_next':('PRÓXIMA FAIXA','Avança para a próxima faixa da playlist.'),
            'music_pause':('PAUSAR MÚSICA','Pausa somente a trilha, preservando a voz.'),
            'music_resume':('RETOMAR MÚSICA','Retoma a trilha na posição pausada e respeita o volume da fala.'),
            'music_stop':('PARAR MÚSICA','Interrompe somente a trilha.'),
            'music_save':('SALVAR VOLUMES','Salva volume normal, durante a fala e tempos de transição, sem ativar reprodução.'),
            'music_mute':('MUTE DA TRILHA','Silencia somente a música, mantendo posição e voz.'),
            'music_playlist':('PLAYLIST LOCAL','Selecione uma faixa; duplo clique inicia essa faixa explicitamente.'),
        }
        for key,(name,purpose) in descriptions.items():
            self.registry.entries[key]={'name':name,'purpose':purpose,'when':'Durante teste local ou apresentação.',
                'result':purpose,'requirements':'Arquivos locais MP3/WAV com licença adequada para transmissão.',
                'risk':'O programa não verifica direitos autorais automaticamente; use somente faixas autorizadas.',
                'undo':'Use PARAR ou desmarque ATIVAR TRILHA. Remover da lista não apaga arquivos.',
                'example':'Volume normal 35%, durante fala 8%; redução 300 ms e restauração 800 ms.',
                'callback':'','file':'live_dashboard_v2.py','availability':'Na aba Voz e IA da V2.'}
        music=card(page,'TRILHA SONORA LOCAL · VOZ E MÚSICA COM VOLUMES INDEPENDENTES')
        paragraph(music,'Playlist instrumental em loop, sem início automático. Adicione somente músicas com licença para transmissão. A trilha abaixa antes da voz audível e permanece baixa em falas consecutivas.',True)
        line=self.row(music)
        self.music_enabled=tk.BooleanVar(master=self.root,value=False)
        toggle=ttk.Checkbutton(line,text='ATIVAR TRILHA',variable=self.music_enabled,command=self.toggle_soundtrack)
        toggle.pack(side='left',padx=4);self.register(toggle,'music_enable',self.toggle_soundtrack)
        self.music_mute=tk.BooleanVar(master=self.root,value=False)
        mute=ttk.Checkbutton(line,text='MUTE SÓ DA TRILHA',variable=self.music_mute,command=self.mute_soundtrack)
        mute.pack(side='left',padx=12);self.register(mute,'music_mute',self.mute_soundtrack)
        self.music_normal=tk.IntVar(master=self.root,value=35);self.music_speech=tk.IntVar(master=self.root,value=8)
        self.music_duck_ms=tk.IntVar(master=self.root,value=300);self.music_restore_ms=tk.IntVar(master=self.root,value=800)
        line=self.row(music)
        for title,variable,maximum in [('Normal %',self.music_normal,100),('Durante fala %',self.music_speech,100),
                ('Redução ms',self.music_duck_ms,5000),('Restauração ms',self.music_restore_ms,5000)]:
            ttk.Label(line,text=title,style='Body.TLabel').pack(side='left',padx=4)
            ttk.Spinbox(line,from_=0,to=maximum,width=5,textvariable=variable).pack(side='left',padx=4)
        self.button(line,'SALVAR AJUSTES',self.save_soundtrack_levels,'music_save')
        self.music_list=tk.Listbox(music,height=5,exportselection=False,bg='#142338',fg=TEXT,selectbackground='#24568c')
        self.music_list.pack(fill='x',pady=6);self.music_list.bind('<Double-Button-1>',lambda _event:self.play_soundtrack_selected())
        self.register(self.music_list,'music_playlist',self.play_soundtrack_selected)
        self.music_shuffle=tk.BooleanVar(master=self.root,value=False)
        shuffle=ttk.Checkbutton(music,text='ORDEM ALEATÓRIA · SEM REPETIR A FAIXA ATUAL',variable=self.music_shuffle,command=self.set_soundtrack_shuffle)
        shuffle.pack(anchor='w',pady=3)
        line=self.row(music)
        for label,callback,key in [('ADICIONAR MP3/WAV',self.add_soundtrack_files,'music_add'),
                ('REMOVER',lambda:self.soundtrack_edit('remove'),'music_remove'),
                ('SUBIR',lambda:self.soundtrack_edit('up'),'music_up'),
                ('DESCER',lambda:self.soundtrack_edit('down'),'music_down'),
                ('LIMPAR LISTA',lambda:self.soundtrack_action('clear'),'music_clear')]:
            self.button(line,label,callback,key)
        line=self.row(music)
        for label,callback,key in [('TOCAR SELECIONADA',self.play_soundtrack_selected,'music_play'),
                ('ANTERIOR',lambda:self.soundtrack_action('next_track',-1),'music_prev'),
                ('PRÓXIMA',lambda:self.soundtrack_action('next_track',1),'music_next'),
                ('PAUSAR',lambda:self.soundtrack_action('pause'),'music_pause'),
                ('RETOMAR',lambda:self.soundtrack_action('resume'),'music_resume'),
                ('PARAR',lambda:self.soundtrack_action('stop'),'music_stop')]:
            self.button(line,label,callback,key)
        self.music_status=paragraph(music,'Trilha parada · nenhuma música inicia ao abrir o programa.',True)
        self.music_feedback=paragraph(music,'Duas trilhas originais locais disponíveis na playlist. A reprodução começa somente por comando.',True)
        paragraph(music,'Voz e trilha usam a saída de áudio padrão deste processo. Para capturar as duas juntas, use uma única captura dessa saída no software de transmissão; evite duplicar a mesma saída em duas fontes. Este painel não modifica OBS ou LIVE Studio.',True)

    def _soundtrack(self):
        return getattr(self.monitor(),'soundtrack',None)

    def _music_selection(self):
        selected=self.music_list.curselection()
        return int(selected[0]) if selected else None

    def soundtrack_action(self,action,*args):
        music=self._soundtrack()
        if not music:return False
        try:
            result=getattr(music,action)(*args)
            if result is False:self.music_feedback.configure(text='Ação não iniciada; confira a playlist e o estado da trilha.')
            else:self.music_feedback.configure(text='Ajuste aplicado somente à trilha sonora.')
            self._refresh_soundtrack_status()
            if result is not False and action in {'start','next_track'} and music.snapshot()['preferences']['playlist']:
                self.music_list.selection_clear(0,'end');self.music_list.selection_set(music.snapshot()['selected'])
            return result
        except (OSError,ValueError,tk.TclError) as error:
            self.music_feedback.configure(text=str(error));return False

    def add_soundtrack_files(self):
        from tkinter import filedialog,messagebox
        paths=filedialog.askopenfilenames(parent=self.root,title='Selecionar músicas locais licenciadas',
            filetypes=[('Áudio MP3/WAV','*.mp3 *.wav'),('MP3','*.mp3'),('WAV','*.wav')])
        if not paths:return False
        if not messagebox.askyesno('Licença para transmissão',
            'Confirma que possui licença ou autorização adequada para usar todas as faixas selecionadas em transmissão?',parent=self.root):return False
        music=self._soundtrack()
        if not music:return False
        try:
            music.add_files(paths,licensed=True);self.music_feedback.configure(text='Faixas adicionadas. A reprodução só começa ao ativar a trilha ou tocar uma faixa.')
            self._refresh_soundtrack_status();return True
        except (OSError,ValueError) as error:self.music_feedback.configure(text=str(error));return False

    def soundtrack_edit(self,action):
        index=self._music_selection()
        if index is None:return False
        if action=='remove':return self.soundtrack_action('remove',index)
        delta=-1 if action=='up' else 1
        result=self.soundtrack_action('move',index,delta)
        if result is not False:
            self.music_list.selection_clear(0,'end');self.music_list.selection_set(index+delta)
        return result

    def toggle_soundtrack(self):
        if self.music_enabled.get():return self.soundtrack_action('start',self._music_selection())
        return self.soundtrack_action('stop')

    def play_soundtrack_selected(self):
        index=self._music_selection()
        if index is None:return False
        return self.soundtrack_action('start',index)

    def mute_soundtrack(self):return self.soundtrack_action('set_mute',bool(self.music_mute.get()))

    def set_soundtrack_shuffle(self):return self.soundtrack_action('set_shuffle',bool(self.music_shuffle.get()))

    def save_soundtrack_levels(self):
        try:values=[int(variable.get()) for variable in (self.music_normal,self.music_speech,self.music_duck_ms,self.music_restore_ms)]
        except (ValueError,tk.TclError):
            self.music_feedback.configure(text='Informe volumes e tempos como números inteiros.');return False
        return self.soundtrack_action('save_levels',*values)

    def _refresh_soundtrack_status(self):
        if not hasattr(self,'music_status'):return
        music=self._soundtrack()
        if not music:return
        state=music.snapshot();prefs=state['preferences']
        self.music_enabled.set(state['enabled']);self.music_mute.set(prefs['mute'])
        if hasattr(self,'music_shuffle'):self.music_shuffle.set(prefs.get('shuffle',False))
        signature=(tuple(row['path'] for row in prefs['playlist']),state['selected'],state['enabled'],state['state'],prefs.get('shuffle',False))
        if signature!=getattr(self,'_music_signature',None):
            selected=self._music_selection();self.music_list.delete(0,'end')
            for index,row in enumerate(prefs['playlist']):
                mark='▶ ' if state['enabled'] and index==state['selected'] else ''
                self.music_list.insert('end',mark+str(index+1)+'. '+Path(row['path']).name)
            if prefs['playlist']:
                self.music_list.selection_set(min(selected if selected is not None else state['selected'],len(prefs['playlist'])-1))
            self._music_signature=signature
        labels={'STOPPED':'Parada','STARTING':'Preparando','PLAYING':'Tocando','PAUSED':'Pausada','ERROR':'Erro','CLOSED':'Encerrada'}
        self.music_status.configure(text=(f"Trilha: {labels.get(state['state'],state['state'])} · {state['current'] or 'nenhuma faixa em reprodução'} · volume atual {state['volume']:.1f}%\n"
            f"Normal {prefs['normal_volume']}% · durante fala {prefs['speech_volume']}% · redução {prefs['duck_ms']} ms · restauração {prefs['restore_ms']} ms · {'mute' if prefs['mute'] else 'som ativo'}\n"
            +(state['error'] or 'Playlist em loop · volume da voz e volume geral do Windows preservados.')))

    def build_events(self):
        page=self.pages['Eventos e Live'].body
        source=card(page,'FONTE DE EVENTOS · TESTE SEPARADO DE CONEXÃO REAL')
        self.platform=tk.StringVar(value='TIKTOK' if self.source in {'tiktok','tiktok-sim'} else 'YOUTUBE')
        line=self.row(source)
        for platform in ['YOUTUBE','TIKTOK']:
            w=ttk.Radiobutton(line,text=platform,value=platform,variable=self.platform,command=self.apply_event_source)
            w.pack(side='left',padx=8);self.register(w,'platform',self.controls['platform'])
        from live_tiktok_config import tiktok_config
        try:public_id,_=tiktok_config()
        except ValueError:public_id=''
        self.tiktok_mode=tk.StringVar(value='SIMULADOR' if self.source=='tiktok-sim' else 'TIKTOK REAL')
        self.tiktok_public_id=tk.StringVar(value=public_id)
        line=self.row(source)
        ttk.Combobox(line,textvariable=self.tiktok_mode,values=['SIMULADOR','TIKTOK REAL'],state='readonly',width=18).pack(side='left',padx=(0,8))
        ttk.Label(line,text='Perfil público @',style='Body.TLabel').pack(side='left')
        ttk.Entry(line,textvariable=self.tiktok_public_id,width=24).pack(side='left',padx=8)
        self.button(line,'APLICAR FONTE',self.apply_event_source,'platform')
        self.source_status=paragraph(source,'Em teste local · nenhuma conexão real')
        self.platform_status=paragraph(source,'Detalhes da fonte',True)
        paragraph(source,'APLICAR FONTE encerra o teste local sem conectar. Depois use INICIAR para receber eventos. TikTok real usa o leitor TikTokLive existente, independente do DOM e da captura de vídeo do LIVE Studio. Para trocar a fonte ativa ou reconectar, use PARAR primeiro. Nenhuma transmissão é iniciada por estes controles.',True)
        simulation=card(page,'SIMULAR EVENTO · NÃO É ATIVIDADE REAL')
        self.event_type=tk.StringVar(value='CHAT');self.event_amount=tk.StringVar();self.event_count=tk.StringVar()
        self.event_type_display=tk.StringVar(value='Comentário')
        self.event_message=tk.StringVar();self.event_author=tk.StringVar(value='Marina')
        self.selector(simulation,'Tipo do evento',self.event_type_display,list(EVENT_LABELS.values()),'event_type',self.select_event_type)
        self.field(simulation,'Nome do espectador',self.event_author)
        self.event_message_label=paragraph(simulation,'Comentário')
        self.event_message_entry=ttk.Entry(simulation,textvariable=self.event_message);self.event_message_entry.pack(fill='x',pady=(0,8))
        self.amount_row=self.row(simulation);ttk.Label(self.amount_row,text='Valor (apenas simulado)',style='Body.TLabel').pack(side='left',padx=(0,10));ttk.Entry(self.amount_row,textvariable=self.event_amount,width=15).pack(side='left')
        self.count_row=self.row(simulation);ttk.Label(self.count_row,text='Quantidade (opcional)',style='Body.TLabel').pack(side='left',padx=(0,10));ttk.Entry(self.count_row,textvariable=self.event_count,width=15).pack(side='left')
        self.simulate_actions=self.row(simulation)
        self.button(self.simulate_actions,'SIMULAR',self.simulate_event,'simulate',style='Primary.TButton')
        self.event_feedback=paragraph(simulation,'Preencha os campos; nenhum evento é enviado automaticamente.',True)
        self.queue_status=paragraph(card(page,'FILA E REAÇÕES'),'Fila aguardando')
        mod=card(page,'MODERAÇÃO LOCAL')
        self.mod_summary=paragraph(mod,'Moderação aguardando',True)
        self.button(self.row(mod),'VER FILA',self.show_moderation_queue,'moderation')
        self.mod_scenario=tk.StringVar(value='NORMAL')
        self.selector(mod,'Cenário',self.mod_scenario,['NORMAL','SPAM','FLOOD','LINK','SELF_PROMOTION','OFFENSIVE_POSSIBLE','SUPER_CHAT_FLAGGED'],'scenario')
        line=self.row(mod)
        self.button(line,'SIMULAR TRIAGEM',lambda:self.controls['moderation_simulate'](self.mod_scenario.get()),'triage')
        self.button(line,'SIMULAR DIRETOR',self.controls['director_simulate'],'director')
        suggestions=card(page,'SUGESTÕES DO APRESENTADOR · NÃO SÃO DECISÕES DE MODERAÇÃO')
        line=self.row(suggestions);self.button(line,'APROVAR',self.controls['presenter_approve'],'approve');self.button(line,'DESCARTAR',self.controls['presenter_discard'],'discard')
        self.update_event_fields()

    def build_diagnostics(self):
        page=self.pages['Diagnóstico'].body
        launch=card(page,'PREPARAÇÃO · VOZ, GODOT, LEITOR E TRANSMISSÃO')
        self.launch_diagnostic=paragraph(launch,'Preparação ainda não executada. Transmissão pública não confirmada.',True)
        paragraph(page,'Detalhes técnicos e registros. As siglas originais continuam acessíveis aqui, sem ocupar a tela inicial.',True)
        self.mode_button=self.button(self.row(page),'MODO LIVE',self.toggle_mode,'mode')
        self.dev=ttk.Frame(page,style='Base.TFrame');self.dev.pack(fill='both',expand=True)
        log=card(self.dev,'LOGS E ALERTAS')
        line=self.row(log)
        self.button(line,'COPIAR LOG',self.copy_log,'copy_log');self.button(line,'EXPORTAR LOG',self.controls['export_log'],'export_log')
        self.button(line,'LIMPAR VISUALIZAÇÃO',self.clear_logs,'clear_log');self.button(line,'COPIAR DIAGNÓSTICO',self.copy_diagnostic,'copy_diag')
        self.selector(log,'Filtro',self.log_filter,['TODOS','DOM','GEMINI','TTS','RULE','FALLBACK','SISTEMA'],'log_filter',lambda *_:self._render_logs())
        self.diag=self.text_box(log,height=13,font=('Consolas',10))
        self.connection_status=paragraph(card(self.dev,'CONEXÕES DESTA INSTÂNCIA'),'Aguardando',True)
        self.readable_health=paragraph(card(self.dev,'DISPONIBILIDADE E DISPOSITIVOS'),'Aguardando',True)
        self.health=paragraph(card(self.dev,'INDICADORES LEGADOS BRUTOS · CONSULTE O ESTADO ZUKO ACIMA'),'Aguardando',True)
        metrics=card(self.dev,'TELEMETRIA COMPLETA')
        grid=ttk.Frame(metrics,style='Base.TFrame');grid.pack(fill='x')
        for i,attribute in enumerate(['metrics','guard_metrics','audience_metrics','progress_metrics']):
            label=ttk.Label(grid,text='',style='Muted.TLabel',justify='left',wraplength=430)
            label.grid(row=i//2,column=i%2,sticky='nw',padx=(0,20),pady=(0,16));setattr(self,attribute,label)
        grid.columnconfigure(0,weight=1);grid.columnconfigure(1,weight=1)
        self.core=tk.Canvas(metrics,width=200,height=60,bg=BG,highlightthickness=0);self.core.pack(anchor='w')
        self.core.create_oval(6,6,28,28,fill='#66f2ff',tags='core');self.core.create_text(100,18,text='Aguardando',fill=TEXT,tags='state')
        legacy=card(self.dev,'MÓDULOS LEGADOS · CONTROLES PRESERVADOS')
        line=self.row(legacy);self.zig_button=self.button(line,'ZIG LIVE',None,'zig')
        self.zig_viewer=ZigViewerButton(self.root,self.zig_button)
        from zig_settings import attach_panel
        self.zig_settings=attach_panel(self)
        self.zig_settings_button=self.button(line,'CONFIGURAÇÕES ZIG',self.zig_settings.open,'zig_settings')
        paragraph(legacy,'ZIG não é ZUKO. A ponte automática ZIG já estava suspensa na versão de origem. Os módulos legados foram copiados, sem alterar os originais.',True)

    def text_box(self,parent,height=8,font=('Segoe UI',10)):
        frame=ttk.Frame(parent,style='Base.TFrame');frame.pack(fill='both',expand=True)
        text=tk.Text(frame,height=height,bg='#101c2c',fg=TEXT,relief='flat',font=font,wrap='word',state='disabled',padx=10,pady=10)
        bar=ttk.Scrollbar(frame,command=text.yview);text.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');text.pack(side='left',fill='both',expand=True);return text

    def build_help(self):
        page=self.pages['Ajuda e instruções'].body
        paragraph(page,'Manual integrado · pesquise um botão ou assunto')
        self.help_search=tk.StringVar();entry=self.field(page,'Pesquisar',self.help_search)
        self.help_search.trace_add('write',lambda *_:self.filter_help())
        group=ttk.Frame(page,style='Base.TFrame');group.pack(fill='both',expand=True)
        self.help_list=tk.Listbox(group,height=10,bg='#142338',fg=TEXT,selectbackground='#24568c',font=('Segoe UI',10),exportselection=False,relief='flat')
        scroll=ttk.Scrollbar(group,command=self.help_list.yview);self.help_list.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.help_list.pack(side='left',fill='both',expand=True);self.help_list.bind('<<ListboxSelect>>',self.select_help)
        self.help_text=self.text_box(page,height=24)
        self.filter_help();self.render_help('help')

    def toggle_live_preparation(self):
        controller=self.live_preparation
        if controller.busy:return controller.cancel()
        if controller.state=='OPERATIONAL':return controller.stop()
        if controller.state=='READY':
            from tkinter import messagebox
            approved=messagebox.askyesno('Ativar ZUKO local',
                'Ativar o apresentador AUTO e as duas trilhas locais agora?\n'
                'A transmissão pública precisa ser iniciada manualmente no TikTok LIVE Studio.',parent=self.root)
            return controller.activate(start_music=True) if approved else False
        try:self._load_and_apply_persisted_gemini_limits()
        except (OSError,ValueError) as error:
            self.live_prepare_status.configure(text='Não foi possível carregar os limites Gemini: '+str(error))
            return False
        return controller.start()

    def _set_gemini_limit_controls(self,limits):
        text_limit=limits['gemini_text'];tts_limit=limits['gemini_tts']
        self.gemini_text_unlimited_var.set(text_limit is None)
        if text_limit is not None:self.gemini_text_limit_var.set(text_limit)
        self.voice_unlimited_var.set(tts_limit is None)
        if tts_limit is not None:self.voice_call_limit.set(str(tts_limit))
        self._toggle_limit_spin(self.gemini_text_limit_spin,self.gemini_text_unlimited_var)
        self._toggle_limit_spin(self.voice_limit_spin,self.voice_unlimited_var)
        self._saved_gemini_text_limit=text_limit

    def _load_and_apply_persisted_gemini_limits(self):
        import zuko_voice_config as voice_config
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None) if monitor else None
        limits,states=gemini_limits.load_and_apply_limits(
            path=gemini_limits.LIMITS_PATH,
            text_budget=zuko.gemini_budget if zuko else None,
            tts_config=voice_config,
            epoch=getattr(monitor,'session_epoch',0) if monitor else None)
        self._set_gemini_limit_controls(limits)
        if zuko:zuko._update_gemini_status()
        self._refresh_voice_status()
        return limits,states

    def _gemini_limit_status_lines(self):
        import zuko_voice_config as voice_config
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None) if monitor else None
        text=zuko.gemini_budget.snapshot(getattr(monitor,'session_epoch',0)) if zuko else {
            'authorized':False,'limit':getattr(self,'_saved_gemini_text_limit',100),'used':0}
        tts=voice_config.authorization_status()
        def describe(state):
            grant='AUTORIZADO' if state['authorized'] else 'BLOQUEADO'
            cap='ILIMITADO' if state['limit'] is None else str(state['limit'])
            return f'{grant} · limite {cap} · {state["used"]} chamadas utilizadas'
        lines=['Gemini Text: '+describe(text),'Gemini TTS: '+describe(tts)]
        if text['limit'] is None or tts['limit'] is None:
            lines.append('ILIMITADO remove o teto interno; chamadas podem gerar cobrança e exigem autorização própria.')
        return lines

    def _live_preparation_update(self,state,detail):
        controller=self.live_preparation
        labels={'IDLE':'INICIAR LIVE','READY':'PRONTO PARA TRANSMITIR','OPERATIONAL':'ENCERRAR LIVE',
                'FAILED':'ERRO — VER DIAGNÓSTICO','CANCELLED':'INICIAR LIVE',
                'CONNECTING_TIKTOK':'CONECTANDO TIKTOK...'}
        self.live_prepare_button.configure(text=labels.get(state,'PREPARANDO...'),
            style='Danger.TButton' if state=='OPERATIONAL' else 'Primary.TButton')
        facts=controller.facts;monitor=self.monitor()
        reader_health=monitor.tiktok_source.health() if monitor else {'connection':'STOPPED'}
        reader=reader_health['connection']
        if reader_health.get('reconnect_attempts'):
            reader+=' · reconexões '+str(reader_health['reconnect_attempts'])+'/'+str(reader_health.get('max_reconnects',3))
        facts['reader_current']={k:reader_health[k] for k in ('connection','reason','reconnect_attempts','max_reconnects') if k in reader_health}
        studio='aberto' if facts.get('studio',{}).get('open') else 'não confirmado'
        local='validado' if state in {'READY','OPERATIONAL'} else 'em preparação' if controller.busy else 'parado / incompleto'
        text=detail+'\n'+f'ZUKO local: {local} · Leitor TikTok: {reader} · LIVE Studio: {studio}'+\
            '\nTransmissão pública: não confirmada pelo ZUKO; publicação e captura são manuais no LIVE Studio.'
        color='#f08a96' if state=='FAILED' else '#7ad6ac' if state in {'READY','OPERATIONAL'} else MUTED
        if self.live_prepare_status.cget('text')!=text:self.live_prepare_status.configure(text=text,foreground=color)
        marks={'PASS':'OK · confirmado','RUNNING':'EM ANDAMENTO','FAIL':'ERRO','PENDING':'PENDENTE','SIMULATED':'SIMULADO · sem conexão real'}
        progress='\n'.join(f"{i+1}. {row['name']}: {marks[row['state']]}" for i,row in enumerate(controller.steps))
        if hasattr(self,'launch_progress') and self.launch_progress.cget('text')!=progress:
            self.launch_progress.configure(text=progress)
        if hasattr(self,'launch_diagnostic'):
            lines=[detail,progress,'',*self._gemini_limit_status_lines(),
                'Transmissão pública: NÃO CONFIRMADA. O leitor TikTok não controla vídeo ou áudio do LIVE Studio.',
                'Captura manual: selecione a janela Godot, uma saída de áudio para voz + trilha e confira a prévia.',
                'Ao encerrar no ZUKO, a publicação do LIVE Studio permanece sob controle do operador.',
                json.dumps(facts,ensure_ascii=False,indent=2)]
            diagnostic='\n'.join(lines)
            if self.launch_diagnostic.cget('text')!=diagnostic:self.launch_diagnostic.configure(text=diagnostic)

    def filter_help(self):
        import unicodedata
        def normalized(text):return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
        query=normalized(self.help_search.get()).strip()
        self.help_keys=[k for k,e in self.registry.entries.items() if query in normalized(e['name']+' '+e['purpose']+' '+e['example'])]
        self.help_list.delete(0,'end')
        for key in self.help_keys:self.help_list.insert('end',self.registry.entries[key]['name'])
        if not self.help_keys:
            self.help_text.configure(state='normal');self.help_text.delete('1.0','end');self.help_text.insert('end','Nenhum resultado. Tente voz, pausa, simular ou ZUKO.');self.help_text.configure(state='disabled')
        elif query:
            self.help_list.selection_set(0);self.render_help(self.help_keys[0])

    def render_help(self,key):
        self.help_text.configure(state='normal');self.help_text.delete('1.0','end');self.help_text.insert('end',self.registry.text(key));self.help_text.yview_moveto(0);self.help_text.configure(state='disabled')

    def select_help(self,event=None):
        selected=self.help_list.curselection()
        if selected:self.render_help(self.help_keys[selected[0]])

    def open_help(self,key='help'):
        self.notebook.select(self.pages['Ajuda e instruções']);self.help_search.set('');self.render_help(key)
        if key in self.help_keys:
            i=self.help_keys.index(key);self.help_list.selection_clear(0,'end');self.help_list.selection_set(i);self.help_list.see(i)

    def focus_help(self,event=None):
        widget=self.root.focus_get()
        self.open_help(self.registry.widgets.get(str(widget),'help'));return 'break'

    def toggle_mode(self):
        self.live_mode.set(not self.live_mode.get())
        if self.live_mode.get():self.dev.pack_forget();self.mode_button.configure(text='MODO DEV')
        else:self.dev.pack(fill='both',expand=True);self.mode_button.configure(text='MODO LIVE')

    def toggle_local_mode(self):
        active=not self.local_mode
        if self.controls['set_local_mode'](active):
            self.local_mode=active;self.local_mode_button.configure(text='SAIR DO TESTE LOCAL' if active else 'MODO TESTE LOCAL')

    def open_test(self):
        if not self.local_mode:self.toggle_local_mode()
        self.notebook.select(self.pages['Voz e IA']);self.local_text.focus_set()

    def update_event_fields(self):
        kind=self.event_type.get()
        self.event_type_display.set(EVENT_LABELS.get(kind,kind))
        self.event_message_label.configure(text='Nome do presente' if kind=='GIFT' else 'Comentário / mensagem (opcional)' if kind=='SUPER_CHAT' else 'Comentário' if kind=='CHAT' else 'Este evento usa apenas o nome do espectador')
        self.event_message_entry.configure(state='normal' if kind in {'CHAT','GIFT','SUPER_CHAT'} else 'disabled')
        for frame,visible in [(self.amount_row,kind=='SUPER_CHAT'),(self.count_row,kind in {'GIFT','LIKE'})]:
            if visible:frame.pack(fill='x',pady=2,before=self.simulate_actions)
            else:frame.pack_forget()

    def select_event_type(self,label):
        self.event_type.set(next(k for k,v in EVENT_LABELS.items() if v==label));self.update_event_fields()

    def simulate_event(self):
        if not self.local_mode:
            self.event_feedback.configure(text='Ative MODO TESTE LOCAL na aba Início antes de simular.');return
        ident='v2-simulation-'+str(time.time_ns());kind=self.event_type.get();author=self.event_author.get().strip() or 'Visitante'
        message=self.event_message.get().strip()
        if kind=='CHAT':
            if not message:self.event_feedback.configure(text='Digite o comentário antes de simular.');return
            self.controls['send_local'](message,author,'LOCAL_TEXT',self.local_speak.get())
        elif kind=='FOLLOW':
            from live_platform_adapter import PlatformEvent
            self.monitor().accept_platform_event(PlatformEvent('tiktok','FOLLOW',ident,author_name=author,confirmed=True,raw_metadata={'simulation':True}))
        else:
            self.controls['simulate_event']({'event_id':ident,'type':kind,'author':author,'message':message if kind=='SUPER_CHAT' else None,
                'gift_name':message if kind=='GIFT' else None,'amount':self.event_amount.get().strip() or None,
                'count':int(self.event_count.get()) if self.event_count.get().isdigit() else None,'platform':'local'})
        self.event_feedback.configure(text='Evento SIMULADO enviado: '+kind+'. Confira a fila, a janela do ZUKO e os logs.')

    def monitor(self):return self.runtime_monitor or getattr(self.controls['start'],'__self__',None)

    def toggle_autonomy(self):
        monitor=self.monitor()
        if not monitor or not getattr(monitor,'zuko',None):return False
        result=monitor.zuko.set_auto(bool(self.v3_enabled.get()))
        self._refresh_autonomy_status()
        return result

    def apply_autonomy_mode(self):
        monitor=self.monitor()
        if monitor and getattr(monitor.zuko,'autonomy',None):
            monitor.zuko.autonomy.set_mode(self.v3_mode.get())
            if hasattr(self,'v4_interval'):
                self.v4_interval.set(monitor.zuko.autonomy.snapshot()['interval_seconds'])
            self._refresh_autonomy_status()

    def apply_autonomy_plan(self):
        monitor=self.monitor();engine=getattr(getattr(monitor,'zuko',None),'autonomy',None)
        if not engine:
            self._v4_plan_error='Erro: controlador de autonomia indisponível'
            self._refresh_v4_plan_status()
            return False
        try:
            requested_topic=self.v4_topic.get().strip()
            requested_interval=int(self.v4_interval.get())
            accepted=engine.configure_planning(requested_topic,requested_interval)
            if not isinstance(accepted,dict) or accepted.get('accepted') is not True:
                raise RuntimeError('V4_CONTROLLER_ACK_MISSING')
            active_topic=str(accepted.get('operator_topic') or '').strip()
            active_interval=int(accepted['interval_seconds'])
            current=engine.snapshot()
            if (active_interval!=requested_interval or current.get('operator_topic')!=active_topic or
                    int(current.get('interval_seconds',-1))!=active_interval):
                raise RuntimeError('V4_CONTROLLER_CONFIGURATION_MISMATCH')
        except (ValueError,tk.TclError) as error:
            self._v4_plan_error=('Erro: informe um tema de até 160 caracteres e intervalo de 10 a 300 segundos'
                if isinstance(error,ValueError) else 'Erro: o intervalo informado não é válido')
            self._refresh_v4_plan_status(engine)
            return False
        except Exception as error:
            self._v4_plan_error='Erro no controlador: '+type(error).__name__
            self._refresh_v4_plan_status(engine)
            return False
        self._v4_plan_syncing=True
        try:
            self.v4_topic.set(active_topic)
            self.v4_interval.set(active_interval)
        finally:self._v4_plan_syncing=False
        self._v4_last_confirmed=(active_topic,active_interval)
        self._v4_last_applied=time.strftime('%H:%M:%S')
        self._v4_plan_error=''
        self._refresh_v4_plan_status(engine,'Aplicado com sucesso')
        self._refresh_autonomy_status()
        return True

    def _v4_plan_edited(self,*_):
        if getattr(self,'_v4_plan_syncing',False):return
        self._v4_plan_error=''
        self._refresh_v4_plan_status()

    def _refresh_v4_plan_status(self,engine=None,forced_status=None):
        widget=getattr(self,'v4_plan_status',None)
        if widget is None:return
        if engine is None:
            monitor=self.monitor();engine=getattr(getattr(monitor,'zuko',None),'autonomy',None)
        active_topic='não confirmado';active_interval='não confirmado'
        active_subtopic='aguardando planejamento';planning_reason='sem plano ativo'
        status=forced_status or getattr(self,'_v4_plan_error','')
        if engine is None:
            status=status or 'Aguardando controlador'
        else:
            try:
                state=engine.snapshot()
                active_topic=str(state.get('operator_topic') or '').strip()
                active_interval=int(state['interval_seconds'])
                plan=state.get('conversation_plan') or {}
                active_subtopic=str(plan.get('subtopic') or 'aguardando planejamento')
                planning_reason=str(plan.get('planning_reason') or 'sem motivo informado')
                active=(active_topic,active_interval)
                if self._v4_last_confirmed is None:
                    self._v4_last_confirmed=active
                elif self._v4_last_confirmed!=active:
                    self._v4_last_confirmed=active
                    self._v4_last_applied=''
                try:
                    requested=(self.v4_topic.get().strip(),int(self.v4_interval.get()))
                except (ValueError,tk.TclError):
                    requested=None
                    status=status or 'Erro: intervalo informado inválido'
                if requested is not None and requested!=active and not status:
                    status='Alteração pendente'
                if requested==active and not status:
                    status='Aplicado com sucesso' if self._v4_last_applied else 'Configurado no controlador'
            except Exception as error:
                status=status or ('Erro ao ler controlador: '+type(error).__name__)
                active_topic='não confirmado';active_interval='não confirmado'
        topic_label=active_topic or 'automático (sem tema fixo)'
        last=self._v4_last_applied or 'não disponível'
        widget.configure(text=(f'TEMA ATIVO: {topic_label} · SUBTEMA: {active_subtopic} · MOTIVO: {planning_reason}\n'
                               f'INTERVALO ATIVO: {active_interval} s · STATUS: {status or "Aguardando aplicação"} · ÚLTIMA APLICAÇÃO: {last}'))

    def autonomy_pause(self,paused):
        monitor=self.monitor()
        if monitor and getattr(monitor,'zuko',None):monitor.zuko.pause(paused)

    def end_autonomy(self):
        self.v3_enabled.set(False)
        return self.toggle_autonomy()

    def apply_autonomy_limits(self):
        monitor=self.monitor();engine=getattr(getattr(monitor,'zuko',None),'autonomy',None)
        if not engine:return False
        try:
            limit,rpm,reserve=int(self.v3_call_limit.get()),int(self.v3_rpm.get()),int(self.v3_reserve.get())
            if not 1<=limit<=100 or not 1<=rpm<=4 or not 0<=reserve<=100:raise ValueError('limite fora da faixa')
        except (ValueError,tk.TclError):
            self.v3_status.configure(text='Limites V3 inválidos: sessão 1–100, minuto 1–4 e reserva 0–100.')
            return False
        with engine.lock:
            engine.config['limits'].update(autonomous_gemini_per_session=limit,
                autonomous_gemini_per_minute=rpm,audience_reserve_calls=reserve)
        self._refresh_autonomy_status();return True

    def _refresh_autonomy_status(self):
        if not hasattr(self,'v3_status'):return
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None)
        engine=getattr(zuko,'autonomy',None)
        if not engine:return
        state=engine.snapshot();self.v3_enabled.set(state['enabled']);self.v3_mode.set(state['mode'])
        self._refresh_v4_plan_status(engine)
        if hasattr(self,'v4_pending_status'):
            self.v4_pending_status.configure(text=(f"Comentários aguardando: {state.get('audience_waiting',0)} · "
                f"eventos aguardando: {state.get('audience_events_waiting',0)} · intervalo: {state.get('interval_seconds',25)} s"))
            verified=lambda value:'observados' if value=='OBSERVED' else 'não verificados'
            self.v4_real_status.configure(text=(f"Presentes reais: {verified(state.get('real_gifts'))} · "
                f"seguidores reais: {verified(state.get('real_followers'))}"))
        budget=zuko.gemini_budget.snapshot(getattr(monitor,'session_epoch',0))
        cost=('indisponível: tarifas não configuradas' if state['cost_estimate'] is None else
              f"{state['currency']} {state['cost_estimate']:.6f} (estimativa por tokens, não fatura)")
        signals=state['engagement'];sizes=state['memory_sizes']
        activity=('sem dados reais recentes suficientes' if signals['data_status']=='UNKNOWN' else
                  f"{signals['current_events']} eventos reais na janela; variação {signals['activity_delta'] if signals['activity_delta'] is not None else 'ainda desconhecida'}")
        self.v3_status.configure(text=(f"{state.get('controller_state',state['state'])} · {state['state']} · quadro {state['frame']} · tema {state['topic']}\n"
            f"Próxima ação: {state['next_action']} · falas autônomas concluídas: {state['completed']} · pendentes: {state['pending']}\n"
            f"Gemini V3: {state['gemini_calls']}/{state['autonomous_limit']} · até {state['rpm']}/min · reserva público {state['audience_reserve']} · texto total usado {budget['used']}\n"
            f"Circuito: {'aberto; alternativa local' if state['circuit_open'] else 'normal'} · custo {cost}\n"
            f"Engajamento observado: {activity} · associação temporal, sem causalidade presumida\n"
            f"Memória pública: {sizes['turns']} falas · {sizes['events']} sinais recentes\n{state['reason']}"))
        if hasattr(self,'v3_learning_status'):
            learning=state['learning'];reflection=state['reflection']
            self.v3_reflection_gemini.set(reflection['gemini_enabled'])
            patterns=learning['patterns'];self.v3_review_selector.configure(values=list(patterns))
            if self.v3_review_frame.get() not in patterns:self.v3_review_frame.set(next(iter(patterns),''))
            suggestion=reflection['suggestion']
            actions={'maintain':'manter a programação','change_topic':'mudar de tema','reduce_energy':'reduzir energia',
                'increase_energy':'aumentar energia dentro do modo escolhido','create_challenge':'criar um desafio',
                'resume_question':'retomar uma pergunta','avoid_repeat':'variar o conteúdo'}
            reasons={'TIMING_SIGNALS':'sinais de atividade','REPETITION':'repetição observada',
                'CONTINUITY':'continuidade do assunto','INSUFFICIENT_DATA':'dados insuficientes'}
            suggested=(actions[suggestion['action']]+' · '+reasons[suggestion['reason_code']] if suggestion else 'nenhuma sugestão validada ainda')
            assessment=learning.get('last_assessment') or {}
            hypotheses=', '.join(actions[action] for action in assessment.get('hypotheses',[])) or 'aguardando encerramento de uma sessão'
            self.v3_learning_status.configure(text=(f"Sessões resumidas: {learning['sessions']} · padrões aprovados: {learning['approved']} · candidatos: {len(patterns)}\n"
                f"Reflexões: {reflection['used']}/{reflection['limit']} · sugestão: {suggested}\n"
                f"Próxima apresentação: {hypotheses}\nPersistência: {learning['error'] or 'normal; somente catálogos e contadores'}\n"
                'Padrões indicam associação observada, sem causalidade presumida; aprovação ajusta somente a variedade dos quadros.'))

    def apply_reflection_mode(self):
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None)
        if not zuko or not getattr(zuko,'autonomy',None):return False
        requested=bool(self.v3_reflection_gemini.get())
        grant=zuko.gemini_budget.snapshot(monitor.session_epoch)
        if requested and not grant['authorized']:
            zuko.autonomy.reflection_gemini=False
            self.v3_reflection_gemini.set(False)
            self.v3_learning_status.configure(text='Reflexão Gemini bloqueada: use a autorização de texto existente. Reflexão local continua disponível.')
            return False
        zuko.autonomy.reflection_gemini=requested
        self._refresh_autonomy_status();return True

    def review_autonomy_pattern(self,approve):
        monitor=self.monitor();engine=getattr(getattr(monitor,'zuko',None),'autonomy',None)
        if not engine:return False
        result=engine.store.review(self.v3_review_frame.get(),bool(approve))
        self._refresh_autonomy_status()
        if not result:self.v3_learning_status.configure(text='Nenhum padrão válido selecionado ou persistência bloqueada; consulte o diagnóstico.')
        return result

    def apply_event_source(self):
        m=self.monitor()
        if not m:return
        if m.reading and not m.local_test_mode:
            self.source_status.configure(text='Pressione PARAR antes de trocar a fonte de eventos.')
            return
        platform=self.platform.get()
        mode='tiktok-sim' if self.tiktok_mode.get()=='SIMULADOR' else 'tiktok'
        try:
            from live_tiktok_config import tiktok_config
            ident=tiktok_config(self.tiktok_public_id.get())[0] if platform=='TIKTOK' else None
            if m.local_test_mode:
                if not self.controls['set_local_mode'](False):return
                self.local_mode=False
                self.local_mode_button.configure(text='MODO TESTE LOCAL')
            applied=self.controls['platform'](platform,tiktok_mode=mode,unique_id=ident)
        except ValueError:
            self.source_status.configure(text='Perfil inválido: informe apenas o identificador público TikTok, sem URL ou credenciais.')
            return
        text=(self.tiktok_connection_text(m) if m.source in {'tiktok','tiktok-sim'} else 'YouTube selecionado · use INICIAR para receber eventos.') if applied else 'Troca bloqueada: aguarde o leitor anterior encerrar e aplique novamente.'
        self.source_status.configure(text=text)

    @staticmethod
    def tiktok_connection_text(m):
        health=m.tiktok_source.health();state=health['connection']
        if m.tiktok_source.simulation:
            return 'SIMULADOR · '+('conectado ao simulador' if m.tiktok_source.is_connected() else 'desconectado')+' · JOIN apenas simulado · nenhuma conexão TikTok real'
        labels={'STOPPED':'Desconectado','DISCONNECTED':'Desconectado','WAITING_FOR_LIVE':'Conectando',
            'CONNECTING':'Conectando','CONNECTED':'Conectado','LIVE_OFFLINE':'Desconectado · LIVE offline',
            'ERROR':'Desconectado · erro','AUTH_REQUIRED':'Desconectado · acesso não disponível',
            'RATE_LIMITED':'Desconectado · TikTok limitou a descoberta; aguarde o prazo antes de tentar novamente'}
        text='TIKTOK REAL · '+health.get('broadcaster','')+' · '+labels.get(state,state)
        validation=health.get('capability_validation',{})
        join=validation.get('joins',validation.get('JOIN','UNAVAILABLE'))
        join_label={'VERIFIED_REAL':'JOIN recebido nesta sessão',
                    'SUPPORTED_UNVERIFIED':'JOIN suportado pelo TikTokLive, ainda não verificado nesta sessão',
                    'UNAVAILABLE':'JOIN indisponível nesta versão do TikTokLive'}.get(join,'JOIN não verificado')
        text+=' · '+join_label
        if health.get('reason'):text+=' · '+health['reason']
        return text

    def test_voice(self):
        m=self.monitor()
        if m:m._test_voice()

    def _voice_engine_changed(self,*_):
        engine=self.voice_engine.get();gemini=engine=='Gemini TTS'
        if gemini and self._last_voice_engine=='Microsoft Maria':self.voice_selection.set('Puck')
        self._last_voice_engine=engine
        self.voice_selector.configure(state='normal' if gemini else 'disabled')
        self.voice_custom_style.configure(state='normal' if self.voice_style.get()=='Personalizado' else 'disabled')
        self._refresh_voice_status()

    def _voice_selection_changed(self,*_):
        self._refresh_voice_status()

    def _voice_style_changed(self,*_):
        self.voice_custom_style.configure(state='normal' if self.voice_style.get()=='Personalizado' else 'disabled')

    def _selected_voice_style(self):
        choice=self.voice_style.get()
        if choice=='Personalizado':return self.voice_custom_style.get().strip() or 'Cartoon masculino jovem, engraçado e expressivo.'
        return choice

    def save_voice_settings(self):
        import zuko_voice_config as voice_config
        engine=self.voice_engine.get();voice=self.voice_selection.get() if engine=='Gemini TTS' else ''
        try:active=voice_config.save(engine,voice,self._selected_voice_style())
        except Exception as error:
            from tkinter import messagebox
            messagebox.showerror('Configuração de voz',str(error),parent=self.root);return
        if engine=='Microsoft Maria':voice_config.revoke()
        self._refresh_voice_status()

    def restore_maria(self):
        import zuko_voice_config as voice_config
        active=voice_config.restore_maria()
        voice_config.revoke()
        self.voice_engine.set(active['engine']);self.voice_selection.set('Puck');self.voice_style.set(active['style'])
        self.voice_custom_style.configure(state='disabled')
        self._voice_engine_changed()
        self._refresh_voice_status()

    @staticmethod
    def _toggle_limit_spin(spin,unlimited_var):
        spin.configure(state='disabled' if unlimited_var.get() else 'normal')

    def _selected_gemini_limit(self,unlimited_var,value_var,service):
        if unlimited_var.get():return None
        try:value=int(value_var.get())
        except (TypeError,ValueError):raise ValueError(f'Informe um limite inteiro de 1 a 100 para {service}.')
        if not 1<=value<=100:raise ValueError(f'Informe um limite inteiro de 1 a 100 para {service}.')
        return value

    def save_gemini_limits(self):
        import zuko_voice_config as voice_config
        from tkinter import messagebox
        try:
            text_limit=self._selected_gemini_limit(self.gemini_text_unlimited_var,self.gemini_text_limit_var,'Gemini Text')
            tts_limit=self._selected_gemini_limit(self.voice_unlimited_var,self.voice_call_limit,'Gemini TTS')
        except ValueError as error:
            messagebox.showerror('Limites inválidos',str(error),parent=self.root);return False
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None) if monitor else None
        text_state=zuko.gemini_budget.snapshot(getattr(monitor,'session_epoch',0)) if zuko else {'authorized':False,'limit':None,'used':0}
        tts_state=voice_config.authorization_status()
        def increase(old,new,used):
            return new is None and old is not None or (new is not None and old is not None and new>old)
        increases=[]
        if text_state['authorized'] and increase(text_state['limit'],text_limit,text_state['used']):increases.append('Gemini Text')
        if tts_state['authorized'] and increase(tts_state['limit'],tts_limit,tts_state['used']):increases.append('Gemini TTS')
        if increases and not messagebox.askyesno('Aumentar limites autorizados',
            'Aumentar agora o limite autorizado de '+ ' e '.join(increases)+' pode permitir mais chamadas potencialmente pagas nesta sessão. ILIMITADO significa ausência de teto interno, não gratuidade. Deseja aplicar?',parent=self.root):return False
        try:
            gemini_limits.save_limits(text_limit,tts_limit)
            gemini_limits.apply_limits(
                {'gemini_text':text_limit,'gemini_tts':tts_limit},
                text_budget=zuko.gemini_budget if zuko else None,
                tts_config=voice_config,
                epoch=getattr(monitor,'session_epoch',0) if monitor else None)
        except (OSError,ValueError) as error:
            messagebox.showerror('Limites Gemini',f'Não foi possível salvar e aplicar os limites: {error}',parent=self.root);return False
        self._saved_gemini_text_limit=text_limit
        if zuko:zuko._update_gemini_status()
        self._refresh_voice_status()
        return True

    def authorize_gemini_text(self):
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None) if monitor else None
        if not zuko:
            self.gemini_text_status_var.set('Gemini texto · controlador ZUKO indisponível')
            return False
        return zuko.authorize_gemini()

    def revoke_gemini_text(self):
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None) if monitor else None
        if not zuko:return False
        zuko.revoke_gemini()
        return True

    def authorize_voice_tts(self):
        import zuko_voice_config as voice_config
        from tkinter import messagebox
        if self.voice_engine.get()!='Gemini TTS':
            self.voice_warning.configure(text='Selecione e salve Gemini TTS antes de autorizar chamadas pagas.')
            return
        saved=voice_config.load()
        if saved.get('engine')!='Gemini TTS' or saved.get('voice')!=self.voice_selection.get():
            self.voice_warning.configure(text='Salve a preferência Gemini/Puck selecionada antes de autorizar chamadas pagas.')
            return
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None) if monitor else None
        if not zuko or not zuko._is_real_tiktok_session():
            self.voice_warning.configure(text='Gemini TTS só pode ser autorizado durante uma sessão TikTok Real ativa.')
            return
        try:calls=self._selected_gemini_limit(self.voice_unlimited_var,self.voice_call_limit,'Gemini TTS')
        except ValueError:
            self.voice_warning.configure(text=f'Informe um limite inteiro de {voice_config.MIN_SESSION_CALLS} a {voice_config.MAX_SESSION_CALLS} chamadas Gemini TTS.')
            return
        target='ILIMITADO (sem teto interno)' if calls is None else f'{calls}'
        accepted=messagebox.askyesno('Autorizar Gemini TTS',
            f'Autoriza {target} chamadas de Gemini TTS nesta sessão? Cada chamada nova pode gerar cobrança. '
            'ILIMITADO significa ausência de teto interno, não gratuidade. '
            'A seleção da voz não autoriza chamadas. A autorização não altera sua conta; ao atingir o limite, '
            'novas falas usarão Microsoft Maria. Revogar bloqueia chamadas futuras; reautorizar não repõe chamadas usadas.',
            parent=self.root)
        if not accepted:return
        try:voice_config.approve(calls)
        except (PermissionError,ValueError) as error:
            self.voice_warning.configure(text=str(error));return
        self._refresh_voice_status()

    def revoke_voice_tts(self):
        import zuko_voice_config as voice_config
        voice_config.revoke()
        self._refresh_voice_status()

    def _refresh_voice_status(self,last_result=None):
        if not hasattr(self,'voice_active'):return
        import zuko_voice_config as voice_config
        saved=voice_config.load();grant=voice_config.authorization_status()
        selected=self.voice_engine.get();voice=self.voice_selection.get()
        if grant['limit'] is None:
            tts_counter=f'Gemini TTS · ILIMITADO · {grant["used"]} chamadas utilizadas'
        else:
            tts_counter=f'Gemini TTS · {grant["used"]} chamadas utilizadas · limite {grant["limit"]}'
        self.gemini_tts_counter.configure(text=tts_counter)
        monitor=self.monitor();zuko=getattr(monitor,'zuko',None) if monitor else None
        if zuko:
            text_state=zuko.gemini_budget.snapshot(getattr(monitor,'session_epoch',0))
            if text_state['limit'] is None:
                text=f'Gemini Text · ILIMITADO · {text_state["used"]} chamadas utilizadas'
            else:
                text=f'Gemini Text · {text_state["used"]} chamadas usadas nesta sessão · limite {text_state["limit"]} · {text_state["remaining"]} restantes'
            self.gemini_text_counter.configure(text=text)
            zuko._update_gemini_status()
        if selected=='Gemini TTS':
            if not grant.get('session_active',False) and (grant['limit'] is not None):
                lim='ILIMITADO' if grant['limit'] is None else str(grant['limit'])
                self.voice_active.configure(text=f'Gemini TTS · sessão encerrada · {grant["used"]} usadas · limite {lim}')
                warning='A autorização terminou com a sessão TikTok Real; a cota reinicia somente na próxima sessão real.'
            elif grant['authorized'] and grant['remaining'] is None:
                self.voice_active.configure(text=f'Gemini TTS · {voice} autorizado · ILIMITADO · {grant["used"]} chamadas usadas')
                warning='Sem teto interno no painel; chamadas podem gerar cobrança. Revogar bloqueia chamadas futuras.'
            elif grant['authorized'] and grant['remaining']>0:
                state='autorizado' if grant['authorized'] else 'revogado'
                self.voice_active.configure(text=f'Gemini TTS · {voice} {state} · {grant["used"]}/{grant["limit"]} usadas · {grant["remaining"]} restantes')
                warning='Autorização temporária ativa; ao chegar a zero, as próximas falas usam Microsoft Maria.'
            elif grant['limit'] is not None and grant['used']>=grant['limit']:
                self.voice_active.configure(text=f'Gemini TTS esgotado · {grant["used"]}/{grant["limit"]} usadas nesta sessão')
                warning='Limite Gemini TTS esgotado; próximas falas usam Microsoft Maria até nova sessão TikTok Real.'
            elif grant['used']:
                self.voice_active.configure(text=f'Gemini TTS revogado · {grant["used"]} chamadas usadas · limite {grant["limit"] if grant["limit"] is not None else "ILIMITADO"}')
                warning='Gemini TTS revogado; chamadas futuras permanecem bloqueadas até autorização explícita.'
            else:
                self.voice_active.configure(text='Gemini selecionado — uso ao vivo não autorizado · 0 chamadas usadas')
                warning='Falas ao vivo usarão Microsoft Maria até a autorização separada de Gemini TTS.'
            if saved['engine']!='Gemini TTS':warning+=' Salve a preferência para aplicá-la às próximas falas.'
        else:
            if saved['engine']=='Microsoft Maria':
                self.voice_active.configure(text='Microsoft Maria (local) — ativa; sem chamadas Gemini')
            else:
                self.voice_active.configure(text='Microsoft Maria selecionada — salve para aplicar às próximas falas')
            warning='Uso Gemini não autorizado; a autorização de chamadas permanece revogada.'
        if last_result and last_result.get('status')=='error':
            if last_result.get('fallback'):
                warning='Gemini falhou e o fallback Microsoft Maria também falhou: '+last_result.get('fallback_error','falha local')
            else:warning=last_result.get('error','Falha na última reprodução de voz.')
        elif last_result and last_result.get('fallback'):
            warning='Fallback Microsoft Maria utilizado: '+last_result['fallback']
        elif last_result and last_result.get('cache_hit'):
            warning='Áudio Gemini reutilizado do cache local; nenhuma chamada paga nova.'
        if grant.get('last_fallback'):
            warning+=' Último fallback TTS: '+grant['last_fallback']
        runtime=getattr(monitor,'voice_health',None) if monitor else None
        if runtime:
            local=runtime.snapshot()
            if selected=='Microsoft Maria':
                label=local['voice']+' · reprodução local validada' if local['ready'] else 'Voz local ainda não validada'
                if local['state']=='UNAVAILABLE':label='Voz local indisponível · geração automática bloqueada'
                self.voice_active.configure(text=label)
            if local['error']:warning+=' Diagnóstico local: '+local['error']
            if selected=='Gemini TTS' and not grant['authorized'] and local['ready']:
                self.voice_active.configure(text=local['voice']+' local · reprodução validada · Gemini TTS não autorizado')
        self.voice_warning.configure(text=warning)

    def _preview_response(self,text,voice_config,preview_path=None,voice=''):
        from types import SimpleNamespace
        import time,uuid
        cid='voice-preview:'+str(uuid.uuid4())
        response=SimpleNamespace(comment_id=cid,author='Pré-escuta',text=text,provider='VOICE_PREVIEW',
            generation_ms=0.0,received_at=time.monotonic(),source='VOICE_PREVIEW',tts_enabled=True,tts_priority=1,
            _voice_preview=True,_voice_config=dict(voice_config),_preview_audio_path=preview_path)
        if voice:response._voice_config['voice']=voice
        return response

    def _queue_voice_previews(self,rows):
        m=self.monitor();manager=getattr(m,'voice',None) if m else None
        if not manager:return False,'A fila de voz ainda não está disponível.'
        with manager.lock:
            if manager.paused:return False,'A fila está pausada; retome o ZUKO antes da pré-escuta.'
            if manager.current is not None or manager.queue or manager.state!='IDLE':return False,'A fila de voz está ocupada. Aguarde terminar antes da pré-escuta.'
        for response in rows:manager.enqueue(response)
        return True,'Pré-escuta enfileirada na fila única do ZUKO.'

    def preview_selected_voice(self):
        import zuko_voice_config as voice_config
        engine=self.voice_engine.get();style=self._selected_voice_style()
        if engine=='Gemini TTS':
            from tkinter import messagebox
            sample_text='Eu sou o ZUKO! Meu café entrou no modo economia de energia, mas a diversão continua ligada!'
            if self.voice_test_text.get().strip()!=sample_text:
                messagebox.showinfo('Amostra Gemini já gerada','Puck e Fenrir serão reproduzidos pelas amostras locais já existentes, que contêm este texto:\n\n'+sample_text+'\n\nO campo de texto não gera novo áudio nesta etapa.',parent=self.root)
            asset=voice_config.ASSETS/(self.voice_selection.get().lower()+'.wav')
            if not asset.is_file():
                messagebox.showerror('Amostra indisponível','Não encontrei a amostra local '+asset.name+'. Nenhuma chamada Gemini será feita.',parent=self.root);return
            config={'engine':'Gemini TTS','voice':self.voice_selection.get(),'style':style}
            rows=[self._preview_response(sample_text,config,str(asset),self.voice_selection.get())]
        else:
            config={'engine':'Microsoft Maria','windows_rate':2,'volume':100,'style':style}
            rows=[self._preview_response(self.voice_test_text.get().strip() or 'Olá! Eu sou o ZUKO.',config)]
        ok,message=self._queue_voice_previews(rows)
        self.voice_warning.configure(text=message if ok else 'Pré-escuta não iniciada: '+message)

    def compare_voice_previews(self):
        import zuko_voice_config as voice_config
        from tkinter import messagebox
        sample_text='Eu sou o ZUKO! Meu café entrou no modo economia de energia, mas a diversão continua ligada!'
        rows=[]
        for voice in ('Puck','Fenrir'):
            asset=voice_config.ASSETS/(voice.lower()+'.wav')
            if not asset.is_file():
                messagebox.showerror('Amostra indisponível','Falta a amostra local '+asset.name+'. Nenhuma chamada Gemini será feita.',parent=self.root);return
            rows.append(self._preview_response(sample_text,{'engine':'Gemini TTS','voice':voice,'style':self._selected_voice_style()},str(asset),voice))
        ok,message=self._queue_voice_previews(rows)
        self.voice_warning.configure(text='Comparação local Puck → Fenrir, sem geração Gemini.' if ok else 'Comparação não iniciada: '+message)

    def stop_voice_preview(self):
        m=self.monitor();manager=getattr(m,'voice',None) if m else None
        stopped=manager.cancel_preview() if manager else False
        self.voice_warning.configure(text='Pré-escuta parada; falas normais da fila foram preservadas.' if stopped else 'Não há pré-escuta Gemini/Maria para interromper.')

    def show_moderation_queue(self):
        before=set(self.root.winfo_children());super().show_moderation_queue()
        for window in set(self.root.winfo_children())-before:
            window.configure(bg=BG)
            for widget in window.winfo_children():
                if isinstance(widget,ttk.Button):
                    key={'MARCAR OK':'review_ok','IGNORAR':'review_ignore','MANTER EM REVISÃO':'review_keep'}.get(widget.cget('text'))
                    if key:self.register(widget,key,'LiveDashboard.show_moderation_queue.act')

    def attach_runtime(self,monitor):
        self.runtime_monitor=monitor
        if getattr(monitor,'soundtrack',None):
            prefs=monitor.soundtrack.snapshot()['preferences']
            for variable,key in ((self.music_normal,'normal_volume'),(self.music_speech,'speech_volume'),
                    (self.music_duck_ms,'duck_ms'),(self.music_restore_ms,'restore_ms')):variable.set(prefs[key])
            self._refresh_soundtrack_status()
        self.walk_wave_var.set(monitor.npc.walk_wave_enabled)
        self.walk_wave_button.configure(text='WALK + WAVE — '+('LIGADO' if monitor.npc.walk_wave_enabled else 'DESLIGADO'))
        self.walk_wave_status.configure(text='Ativo na próxima caminhada automática.' if monitor.npc.walk_wave_enabled else 'Combinação local desativada por padrão; atua somente na caminhada automática.')
        for gesture in ('Yes','No'):
            enabled=monitor.npc.walk_combo_enabled.get(gesture,False)
            self.walk_combo_vars[gesture].set(enabled)
            self.walk_combo_buttons[gesture].configure(text='WALK + '+gesture.upper()+' — '+('LIGADO' if enabled else 'DESLIGADO'))
            self.walk_combo_statuses[gesture].configure(text='Preferência salva; aguardando abrir o personagem.' if enabled else 'Combinação local desativada por padrão.')
        self.auto_movements_var.set(monitor.npc.auto_movements_enabled)
        self.auto_movements_button.configure(text='MOVIMENTOS AUTOMÁTICOS — '+('LIGADO' if monitor.npc.auto_movements_enabled else 'DESLIGADO'))
        self.auto_movements_status.configure(text='Ativo: reações seguras e caminhada ocasional.' if monitor.npc.auto_movements_enabled else 'Desativado: somente comandos manuais e caminhada solicitada.')
        monitor.npc.walk_button=self.walk_button
        monitor.npc.walk_status_label=self.walk_status_label
        monitor.npc.live_mode_var=self.live_mode_var
        monitor.npc.movement_status=self.movement_status
        monitor.npc.walk_wave_button=self.walk_wave_button
        monitor.npc.walk_wave_status=self.walk_wave_status
        monitor.npc.walk_wave_var=self.walk_wave_var
        monitor.npc.walk_combo_vars=self.walk_combo_vars
        monitor.npc.walk_combo_buttons=self.walk_combo_buttons
        monitor.npc.walk_combo_statuses=self.walk_combo_statuses
        monitor.npc.pause_provider=lambda: bool(monitor.paused or monitor.zuko.paused)
        self.register(monitor.zuko.auto_button,'auto','ZukoPresenter.set_auto')
        self.register(monitor.zuko.pause_button,'zuko_pause','ZukoPresenter.pause')
        self.register(monitor.zuko.gemini_limit_spin,'gemini_limit','ZukoPresenter.authorize_gemini')
        self.register(monitor.zuko.gemini_authorize_button,'gemini_authorize','ZukoPresenter.authorize_gemini')
        self.register(monitor.zuko.gemini_revoke_button,'gemini_revoke','ZukoPresenter.revoke_gemini')
        monitor.zuko.status.pack_forget()  # The V2 summary distinguishes closed/paused/speaking truthfully.
        self.registry.entries['npc_open'].update(callback='NPCPanelBridge.open',file='npc_panel_bridge.py')
        self.registry.entries['npc_close'].update(callback='NPCPanelBridge.close_npc',file='npc_panel_bridge.py')
        self.registry.entries['auto'].update(file='zuko_presenter.py')
        self.registry.entries['zuko_pause'].update(file='zuko_presenter.py')
        self.registry.entries['gemini_limit'].update(file='zuko_presenter.py')
        self.registry.entries['gemini_authorize'].update(file='zuko_presenter.py')
        self.registry.entries['gemini_revoke'].update(file='zuko_presenter.py')
        self.registry.entries['zig'].update(callback='ZigViewerButton.open',file='live_zig_viewer.py')
        for item in self.control_inventory:
            w=self.root.nametowidget(item['widget'])
            item['tk_command']=str(w.cget('command')) if 'command' in w.keys() else ''
            item['availability']=str(w.cget('state')) if 'state' in w.keys() else 'normal'
            if not item['callback']:item['callback']=self.registry.entries[item['help']].get('callback','')
        self.ui_tick()

    def ui_tick(self):
        m=self.monitor()
        if not m or not hasattr(m,'zuko'):self.root.after(500,self.ui_tick);return
        self.probe.refresh(m.zuko.config);state=presentation(m,self.probe)
        for key,label in self.short_states.items():
            value=state[key]
            if key=='voice':
                import zuko_voice_config as voice_config
                active=voice_config.load()
                grant=voice_config.authorization_status()
                if active['engine']!='Gemini TTS':value=state['voice']
                elif not grant['session_active'] and grant['limit'] is not None:
                    value=f'Gemini TTS · sessão encerrada · {grant["used"]}/{grant["limit"]}'
                elif grant['authorized'] and grant['remaining'] is None:
                    value=f'Gemini TTS · {active["voice"]} · ILIMITADO · {grant["used"]} usadas'
                elif grant['authorized']:
                    value=f'Gemini TTS · {active["voice"]} · {grant["used"]}/{grant["limit"]} usadas · {grant["remaining"]} restantes'
                elif grant['limit'] is not None and grant['remaining']:
                    value=f'Gemini TTS revogado · {grant["remaining"]} restantes'
                elif grant['limit'] is not None:
                    value=f'Gemini TTS esgotado · {grant["used"]}/{grant["limit"]}'
                else:value='Gemini selecionado — uso ao vivo não autorizado'
                if active['engine']=='Gemini TTS' and not grant['authorized'] and getattr(m,'voice_health',None):
                    value=state['voice']+' · Gemini TTS não autorizado'
            color='#f2bf66' if any(word in value for word in ['Indisponível','não confirmada','Não verificada']) else '#f08a96' if 'Erro' in value else '#7ad6ac' if any(word in value for word in ['Aberto','Disponível','Pronta','Falando']) else '#91bcf7' if 'Simulador' in value else MUTED
            label.configure(text=value,foreground=color)
        last=None
        try:
            from zuko_voice import results as voice_results
            rows=voice_results()
            if rows:
                last=rows[-1]
                if last.get('engine')=='arquivo de pré-escuta':
                    self.voice_latency.configure(text='Último teste: amostra Gemini pré-gerada tocada localmente; geração não medida.')
                elif last.get('cache_hit'):
                    self.voice_latency.configure(text='Última fala: áudio Gemini reutilizado do cache em memória; nenhuma chamada paga nova.')
                elif last.get('tts_ms') is not None:
                    line='Última geração de voz: '+str(last.get('voice','Maria'))+' · '+f"{last['tts_ms']/1000:.2f}s"
                    if last.get('playback_start_ms') is not None:line+=' até iniciar áudio: '+f"{last['playback_start_ms']/1000:.2f}s"
                    self.voice_latency.configure(text=line)
        except Exception:
            pass
        self._refresh_voice_status(last)
        self._refresh_autonomy_status()
        self._refresh_soundtrack_status()
        shown={'OFF':'Aguardando','PAUSED':'Pausado'}.get(self.state,self.state)
        self.global_status.configure(text=('GEMINI+ SEM AUTORIZAÇÃO · use AUTORIZAR TEXTO em Voz e IA | ' if m.writer.mode=='GEMINI+' and not m.zuko.gemini_budget.snapshot(m.session_epoch)['authorized'] else '')+('Em teste local' if m.local_test_mode or m.source=='tiktok-sim' else 'Fonte: '+m.source)+' · '+shown+' · ZUKO '+state['npc']+' · AUTO '+state['auto'])
        self.voice_last_response.configure(text='Última resposta: '+self.last_response)
        self.home_open.configure(text='ZUKO ABERTO' if m.npc.state=='ACTIVE' else 'ABRIR ZUKO 3D',state='disabled' if m.npc.state in {'STARTING','CLOSING'} else 'normal')
        self.quick_open.configure(text='ZUKO ABERTO' if m.npc.state=='ACTIVE' else 'ABRIR ZUKO 3D',state='disabled' if m.npc.state in {'STARTING','CLOSING'} else 'normal')
        self.zuko_overview.configure(text='Personagem: '+state['npc']+'\nAUTO: '+state['auto']+'  ·  Pausado: '+state['paused']+'  ·  Estado: '+state['state'])
        self.animation_status.configure(text='Última animação solicitada: '+state['last_animation'])
        self.source_status.configure(text=self.tiktok_connection_text(m) if m.source in {'tiktok','tiktok-sim'} else state['source']);self.queue_status.configure(text=state['queue'])
        self.connection_status.configure(text=state['connection'])
        h=connection_health_snapshot(m,m.telemetry.snapshot()['health']);h['GEMINI']='SDK/ADC '+m.zuko.litellm.readiness_snapshot()['state']+' | '+('texto autorizado' if m.zuko.gemini_budget.snapshot(m.session_epoch)['authorized'] else 'texto sem autorização');names={'DOM':'Captura DOM do YouTube','TTS':'Voz (indicador legado)','STT':'Reconhecimento de fala','MICROFONE':'Microfone','GEMINI':'Gemini ZUKO (prontidão e autorização)','PONTE 8766':'Ponte HTTP da captura DOM (YouTube)','GODOT TCP 18765':'Ponte Godot TCP','TIKTOKLIVE':'Leitor de eventos TikTok'}
        self.readable_health.configure(text='\n'.join(names.get(k,k)+': '+str(v) for k,v in h.items())+'\nIA ZUKO: '+state['ai']+'\nVoz ZUKO: '+state['voice'])
        self.live_preparation.check_runtime()
        if self.live_preparation.state in {'READY','OPERATIONAL'}:
            self._live_preparation_update(self.live_preparation.state,self.live_preparation.detail)
        self.root.after(700,self.ui_tick)
