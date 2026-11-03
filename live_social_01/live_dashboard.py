"""Tk Command Center view. It observes LiveMonitor; it never controls the pipeline."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from live_zig_viewer import ZigViewerButton

_BG, _PANEL, _CYAN, _TEXT, _MUTED = "#07111f", "#0c1c2d", "#39d7ff", "#e6f7ff", "#7da1b8"


def tts_mean_label(snapshot,seconds=False):
    if not snapshot.get('tts_available'):return 'N/D'
    ms=snapshot['tts_avg']
    return f'{ms/1000:.1f}s' if seconds and ms>=100 else f'{ms:g}ms'


class LiveDashboard:
    def __init__(self, root: tk.Tk, controls: dict[str, object], telemetry, source: str) -> None:
        self.root, self.controls, self.telemetry, self.source = root, controls, telemetry, source
        self.live_mode, self.local_mode, self.log_filter = tk.BooleanVar(value=False), False, tk.StringVar(value="TODOS")
        self.local_author, self.local_microphone = tk.StringVar(value="@LOCAL_USER"), tk.StringVar(value="Padrão do sistema")
        self.local_auto_send, self.local_speak = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self.local_voice_state, self.local_transcript = tk.StringVar(value="FALAR"), tk.StringVar(value="")
        self.state, self.last_author, self.last_question, self.last_response, self.topic = "AGUARDANDO", "—", "—", "—", "—"
        self.logs: list[tuple[str, str]] = []
        self._build()
        self._tick()

    def _build(self) -> None:
        self.root.configure(bg=_BG)
        style = ttk.Style(self.root); style.theme_use("clam")
        style.configure("CC.TFrame", background=_BG); style.configure("Panel.TFrame", background=_PANEL)
        style.configure("CC.TLabel", background=_BG, foreground=_TEXT); style.configure("Panel.TLabel", background=_PANEL, foreground=_TEXT)
        root = ttk.Frame(self.root, style="CC.TFrame", padding=12); root.pack(fill="both", expand=True)
        header = ttk.Frame(root, style="CC.TFrame"); header.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(header, text="JARVIS LIVE SOCIAL", style="CC.TLabel", font=("Segoe UI", 18, "bold")).pack(side="left")
        self.npc_close_button = ttk.Button(header, text="FECHAR NPC", state="disabled", width=11)
        self.npc_close_button.pack(side="right", padx=2)
        self.npc_button = ttk.Button(header, text="ABRIR NPC 3D", width=15)
        self.npc_button.pack(side="right", padx=2)
        self.mode_button = ttk.Button(header, text="MODO DEV", command=self.toggle_mode); self.mode_button.pack(side="right")
        self.zig_button = ttk.Button(header, text="ZIG LIVE")
        self.zig_button.pack(side="right", padx=3)
        self.zig_viewer = ZigViewerButton(self.root, self.zig_button)
        from zig_settings import attach_panel
        self.zig_settings = attach_panel(self)
        self.zig_settings_button = ttk.Button(header, text='CONFIGURAÇÕES ZIG', command=self.zig_settings.open)
        self.zig_settings_button.pack(side='right', padx=3)
        writer_bar = ttk.Frame(root, style='Panel.TFrame', padding=4)
        self.zuko_bar = writer_bar
        writer_bar.grid(row=4, column=0, columnspan=3, sticky='ew')
        self.writer_mode = tk.StringVar(value='MISTO')
        ttk.Label(writer_bar,text='MODO DE FALA',style='Panel.TLabel').pack(side='left')
        for mode in ('MISTO','GEMINI+'):
            ttk.Radiobutton(writer_bar,text=mode,value=mode,variable=self.writer_mode,
                command=lambda:self.controls.get('writer_mode',lambda _:None)(self.writer_mode.get())).pack(side='left',padx=5)
        self.writer_status = ttk.Label(writer_bar,text='WRITER: MISTO',style='Panel.TLabel')
        self.writer_status.pack(side='left',padx=12)
        self.platform = tk.StringVar(value='TIKTOK' if self.source in {'tiktok','tiktok-sim'} else 'YOUTUBE')
        ttk.Label(writer_bar,text='PLATAFORMA',style='Panel.TLabel').pack(side='left',padx=6)
        for platform in ('YOUTUBE','TIKTOK'):
            ttk.Radiobutton(writer_bar,text=platform,value=platform,variable=self.platform,
                command=lambda:self.controls.get('platform',lambda _:None)(self.platform.get())).pack(side='left',padx=3)
        self.platform_status = ttk.Label(root,text='',style='Panel.TLabel',wraplength=1350)
        self.platform_status.grid(row=5,column=0,columnspan=3,sticky='ew')
        self.local_mode_button = ttk.Button(header, text="MODO TESTE LOCAL", command=self.toggle_local_mode); self.local_mode_button.pack(side="right", padx=3)
        for label, action in (("PARAR", self.controls["stop"]), ("PAUSAR", self.controls["pause"]), ("INICIAR", self.controls["start"])):
            ttk.Button(header, text=label, command=action).pack(side="right", padx=3)
        self.chat = tk.Text(root, bg="#071827", fg=_TEXT, insertbackground=_TEXT, relief="flat", font=("Segoe UI", 11), wrap="word", state="disabled")
        self.chat.grid(row=1, column=0, sticky="nsew", padx=(0,8), pady=10)
        center = ttk.Frame(root, style="Panel.TFrame", padding=10); center.grid(row=1, column=1, sticky="nsew", pady=10)
        self.core = tk.Canvas(center, width=265, height=245, bg=_PANEL, highlightthickness=0); self.core.pack(fill="x")
        self.core.create_oval(48, 28, 217, 197, outline=_CYAN, width=2, tags="ring1"); self.core.create_oval(70, 50, 195, 175, outline="#1a7796", width=2, tags="ring2")
        self.core.create_oval(111, 91, 154, 134, fill=_CYAN, outline="", tags="core")
        self.core.create_text(132, 218, text="AGUARDANDO", fill=_TEXT, font=("Consolas", 12, "bold"), tags="state")
        self.info = {}
        for key in ("ASSUNTO", "FALANDO COM", "PERGUNTA", "JARVIS"):
            ttk.Label(center, text=key, style="Panel.TLabel", foreground=_CYAN, font=("Consolas", 9, "bold")).pack(anchor="w", pady=(5,0))
            value = ttk.Label(center, text="—", style="Panel.TLabel", wraplength=260); value.pack(anchor="w"); self.info[key] = value
        right = ttk.Frame(root, style="Panel.TFrame", padding=10); right.grid(row=1, column=2, sticky="nsew", padx=(8,0), pady=10)
        ttk.Label(right, text="SAÚDE DO SISTEMA", style="Panel.TLabel", foreground=_CYAN, font=("Consolas", 10, "bold")).pack(anchor="w")
        self.health = ttk.Label(right, text="", style="Panel.TLabel", justify="left", font=("Consolas", 9)); self.health.pack(anchor="w", pady=6)
        self.metrics = ttk.Label(right, text="", style="Panel.TLabel", justify="left", font=("Consolas", 9)); self.metrics.pack(anchor="w")
        self.progress_metrics = ttk.Label(right, text="", style="Panel.TLabel", justify="left", font=("Consolas", 9)); self.progress_metrics.pack(anchor="w", pady=(4,0))
        self.guard_metrics = ttk.Label(right, text="", style="Panel.TLabel", justify="left", font=("Consolas", 9)); self.guard_metrics.pack(anchor="w", pady=(4,0))
        self.audience_metrics = ttk.Label(right, text="", style="Panel.TLabel", justify="left", font=("Consolas", 9)); self.audience_metrics.pack(anchor="w", pady=(4,0))
        self.director_summary = ttk.Label(center, text='DIRETOR · IDLE', style='Panel.TLabel', wraplength=260)
        self.director_summary.pack(anchor='w', pady=8)
        self.memory_summary = ttk.Label(center, text='MEMÓRIA DA LIVE', style='Panel.TLabel', wraplength=260)
        self.memory_summary.pack(anchor='w', pady=4)
        ttk.Button(center, text='NOVA SESSÃO LIVE', command=lambda: self.controls['new_live_session']()).pack(anchor='w')
        self.local_panel = ttk.Frame(root, style="Panel.TFrame", padding=8)
        ttk.Label(self.local_panel, text="CONVERSAR COM JARVIS", style="Panel.TLabel", foreground=_CYAN, font=("Consolas", 10, "bold")).pack(anchor="w")
        options = ttk.Frame(self.local_panel, style="Panel.TFrame"); options.pack(fill="x", pady=(4,2))
        ttk.Label(options, text="AUTOR", style="Panel.TLabel").pack(side="left")
        ttk.Entry(options, textvariable=self.local_author, width=16).pack(side="left", padx=4)
        ttk.Label(options, text="MICROFONE", style="Panel.TLabel").pack(side="left", padx=(8,0))
        self.microphones = ttk.OptionMenu(options, self.local_microphone, "Padrão do sistema", "Padrão do sistema"); self.microphones.pack(side="left", padx=4)
        ttk.Checkbutton(options, text="ENVIAR AUTOMATICAMENTE", variable=self.local_auto_send).pack(side="left", padx=8)
        ttk.Checkbutton(options, text="FALAR RESPOSTAS", variable=self.local_speak).pack(side="left")
        self.local_text = tk.Text(self.local_panel, height=3, bg="#071827", fg=_TEXT, insertbackground=_TEXT, relief="flat", font=("Segoe UI", 10), wrap="word")
        self.local_text.pack(fill="x", pady=4); self.local_text.bind("<Return>", self._send_on_enter)
        self.root.bind("<Control-Return>", self._hotkey_send); self.root.bind("<Control-m>", self._hotkey_voice)
        actions = ttk.Frame(self.local_panel, style="Panel.TFrame"); actions.pack(fill="x")
        ttk.Button(actions, text="ENVIAR", command=self.send_local).pack(side="left", padx=2)
        self.voice_button = ttk.Button(actions, text="🎤 FALAR", command=self.toggle_voice); self.voice_button.pack(side="left", padx=2)
        ttk.Button(actions, text="PARAR JARVIS", command=self.controls["stop_jarvis"]).pack(side="left", padx=2)
        ttk.Button(actions, text="NOVA CONVERSA", command=lambda: self.controls["new_local_conversation"](self.local_author.get())).pack(side="left", padx=2)
        ttk.Button(actions, text="RESET SESSÃO LOCAL", command=self.controls["reset_local_session"]).pack(side="left", padx=2)
        ttk.Label(self.local_panel, textvariable=self.local_transcript, style="Panel.TLabel", wraplength=900).pack(anchor="w", pady=(4,0))
        events = ttk.Frame(self.local_panel, style="Panel.TFrame"); events.pack(fill="x", pady=(5,0))
        self.event_type, self.event_amount, self.event_count = tk.StringVar(value="SUPER_CHAT"), tk.StringVar(value=""), tk.StringVar(value="")
        ttk.Label(events, text="SIMULAR EVENTO", style="Panel.TLabel").pack(side="left")
        ttk.OptionMenu(events, self.event_type, "SUPER_CHAT", "CHAT", "SUPER_CHAT", "MEMBER", "GIFT", "LIKE").pack(side="left", padx=3)
        ttk.Entry(events, textvariable=self.event_amount, width=8).pack(side="left", padx=2)
        ttk.Entry(events, textvariable=self.event_count, width=6).pack(side="left", padx=2)
        ttk.Button(events, text="SIMULAR", command=self.simulate_event).pack(side="left", padx=2)
        self.dev = ttk.Frame(root, style="Panel.TFrame", padding=8); self.dev.grid(row=3, column=0, columnspan=3, sticky="nsew")
        tools = ttk.Frame(self.dev, style="Panel.TFrame"); tools.pack(fill="x")
        ttk.Button(tools, text="COPIAR LOG", command=self.copy_log).pack(side="left", padx=2)
        ttk.Button(tools, text="EXPORTAR LOG", command=self.controls["export_log"]).pack(side="left", padx=2)
        ttk.Button(tools, text="LIMPAR VISUALIZAÇÃO", command=self.clear_logs).pack(side="left", padx=2)
        ttk.Button(tools, text="COPIAR DIAGNÓSTICO", command=self.copy_diagnostic).pack(side="left", padx=2)
        self.presenter_mode = tk.StringVar(value="OFF")
        ttk.OptionMenu(tools, self.presenter_mode, "OFF", "OFF", "ASSISTIDO", "AUTO", command=self.controls["presenter_mode"]).pack(side="left", padx=2)
        ttk.Button(tools, text="FALAR AGORA", command=self.controls["presenter_now"]).pack(side="left", padx=2)
        ttk.Button(tools, text="APROVAR", command=self.controls["presenter_approve"]).pack(side="left", padx=2)
        ttk.Button(tools, text="DESCARTAR", command=self.controls["presenter_discard"]).pack(side="left", padx=2)
        if 'presenter_control' in self.controls:
            operator = ttk.Frame(self.dev, style='Panel.TFrame'); operator.pack(fill='x', pady=3)
            for label,command in (('PAUSAR APRESENTADOR','PAUSE'),('RETOMAR','RESUME'),('PRÓXIMO ASSUNTO','NEXT'),('PUXAR ASSUNTO','PULL')):
                ttk.Button(operator,text=label,command=lambda c=command:self.controls['presenter_control'](c)).pack(side='left',padx=2)
        self.presenter_summary = ttk.Label(self.dev, style='Panel.TLabel', wraplength=1300)
        self.presenter_summary.pack(anchor='w',pady=3)
        ttk.OptionMenu(tools, self.log_filter, "TODOS", "TODOS", "DOM", "GEMINI", "TTS", "RULE", "FALLBACK", "SISTEMA", command=lambda *_: self._render_logs()).pack(side="right")
        self.diag = tk.Text(self.dev, height=8, bg="#050c14", fg="#b9d8e7", relief="flat", font=("Consolas", 9), state="disabled", wrap="none")
        self.diag.pack(fill="both", expand=True, pady=(6,0))
        mod = ttk.Frame(self.dev, style='Panel.TFrame'); mod.pack(fill='x', pady=4)
        self.mod_summary = ttk.Label(mod, style='Panel.TLabel', text='MODERAÇÃO'); self.mod_summary.pack(side='left')
        ttk.Button(mod, text='VER FILA', command=self.show_moderation_queue).pack(side='left', padx=4)
        self.mod_scenario = tk.StringVar(value='NORMAL')
        ttk.OptionMenu(mod, self.mod_scenario, 'NORMAL', 'NORMAL', 'SPAM', 'FLOOD', 'LINK', 'SELF_PROMOTION', 'OFFENSIVE_POSSIBLE', 'SUPER_CHAT_FLAGGED').pack(side='left')
        ttk.Button(mod, text='SIMULAR TRIAGEM', command=lambda: self.controls['moderation_simulate'](self.mod_scenario.get())).pack(side='left')
        ttk.Button(mod, text='SIMULAR DIRETOR', command=lambda: self.controls['director_simulate']()).pack(side='left', padx=4)
        root.columnconfigure(0, weight=4); root.columnconfigure(1, weight=3); root.columnconfigure(2, weight=2); root.rowconfigure(1, weight=1)

    def toggle_mode(self) -> None:
        self.live_mode.set(not self.live_mode.get()); self.dev.grid_remove() if self.live_mode.get() else self.dev.grid(); self.mode_button.configure(text="MODO DEV" if self.live_mode.get() else "MODO LIVE")

    def show_moderation_queue(self):
        window = tk.Toplevel(self.root); window.title('Revisão local — sem ações no YouTube')
        table = ttk.Treeview(window, columns=('author','excerpt','category','severity','time'), show='headings')
        for name, label in zip(table['columns'], ('Autor','Trecho','Classificação','Severidade','Horário')):
            table.heading(name, text=label)
        table.pack(fill='both', expand=True)
        def refresh():
            if not window.winfo_exists(): return
            selected = table.selection()
            table.delete(*table.get_children())
            for row in self.controls['moderation_reviews']():
                table.insert('', 'end', iid=row['id'], values=tuple(row[k] for k in table['columns']))
            for ident in selected:
                if table.exists(ident): table.selection_add(ident)
            window.after(1000, refresh)
        def act(action):
            for ident in table.selection(): self.controls['moderation_review'](ident, action)
        for label, action in (('MARCAR OK','OK'),('IGNORAR','IGNORE'),('MANTER EM REVISÃO','KEEP')):
            ttk.Button(window, text=label, command=lambda a=action: act(a)).pack(side='left')
        refresh()

    def toggle_local_mode(self) -> None:
        active = not self.local_mode
        if self.controls["set_local_mode"](active):
            self.local_mode = active
            if active:
                self.local_panel.grid(row=2, column=0, columnspan=3, sticky="ew")
                self.local_mode_button.configure(text="MODO LIVE")
            else:
                self.local_panel.grid_remove(); self.local_mode_button.configure(text="MODO TESTE LOCAL")

    def _send_on_enter(self, event) -> str | None:
        if event.state & 0x0001: return None
        self.send_local(); return "break"

    def _hotkey_send(self, _event=None) -> str:
        self.send_local(); return "break"

    def _hotkey_voice(self, _event=None) -> str:
        self.toggle_voice(); return "break"

    def send_local(self) -> None:
        text = self.local_text.get("1.0", "end-1c")
        if self.controls["send_local"](text, self.local_author.get(), "LOCAL_TEXT", self.local_speak.get()):
            self.local_text.delete("1.0", "end")

    def toggle_voice(self) -> None:
        if self.local_voice_state.get() in {"OUVINDO...", "PROCESSANDO..."}:
            self.controls["stop_local_voice"](); return
        self.controls["start_local_voice"](self.local_author.get(), self.local_microphone.get(), self.local_auto_send.get(), self.local_speak.get())

    def simulate_event(self) -> None:
        payload = {"event_id": f"local-event-{__import__('time').time_ns()}", "type": self.event_type.get(),
                   "author": self.local_author.get(), "message": self.local_text.get("1.0", "end-1c").strip() or None,
                   "amount": self.event_amount.get().strip() or None, "count": int(self.event_count.get()) if self.event_count.get().isdigit() else None,
                   "platform": "local"}
        self.controls["simulate_event"](payload)

    def set_microphones(self, names: list[str]) -> None:
        menu = self.microphones["menu"]; menu.delete(0, "end")
        for name in names: menu.add_command(label=name, command=tk._setit(self.local_microphone, name))
        self.local_microphone.set(names[0] if names else "Padrão do sistema")

    def set_local_voice_state(self, state: str) -> None:
        self.local_voice_state.set(state)
        self.voice_button.configure(text="PARAR" if state in {"OUVINDO...", "PROCESSANDO..."} else "🎤 FALAR")

    def show_local_transcript(self, text: str) -> None: self.local_transcript.set(f'VOCÊ DISSE · LOCAL_VOICE: "{text}"')
    def show_local_voice_error(self, text: str) -> None: self.local_transcript.set(text)
    def set_local_text(self, text: str) -> None:
        self.local_text.delete("1.0", "end"); self.local_text.insert("1.0", text)
    def clear_local_chat(self) -> None:
        self.chat.configure(state="normal"); self.chat.delete("1.0", "end"); self.chat.configure(state="disabled")

    def append_comment(self, author: str, text: str, status: str = "RECEBIDO") -> None:
        self.chat.configure(state="normal"); self.chat.insert("end", f"[{status}] {author}\n{text}\n\n");
        if int(self.chat.index("end-1c").split(".")[0]) > 240: self.chat.delete("1.0", "4.0")
        self.chat.see("end"); self.chat.configure(state="disabled"); self.last_author, self.last_question = author, text

    def update_response(self, author: str, response: str, provider: str, topic: str = "", source: str = "") -> None:
        self.last_author, self.last_response = author, response
        if topic: self.topic = topic
        self.append_comment("ZUKO" if provider.startswith("ZUKO_") else "JARVIS", response, f"{source or 'LIVE'} · {provider}")

    def set_state(self, state: str) -> None: self.state = {"WATCHING":"AGUARDANDO", "THINKING":"PENSANDO", "SPEAKING":"FALANDO", "PAUSED":"PAUSADO"}.get(state, state)
    def log(self, component: str, event: str, level: str = "INFO") -> None:
        self.logs.append((component, f"{component:<8} | {event} | {level}")); del self.logs[:-300]; self._render_logs()
    def _render_logs(self) -> None:
        selected = self.log_filter.get(); rows = [row for component,row in self.logs if selected == "TODOS" or component == selected]
        self.diag.configure(state="normal"); self.diag.delete("1.0", "end"); self.diag.insert("1.0", "\n".join(rows[-180:])); self.diag.configure(state="disabled")
    def clear_logs(self) -> None: self.logs.clear(); self._render_logs()
    def copy_log(self) -> None: self._copy("\n".join(row for _, row in self.logs))
    def copy_diagnostic(self) -> None:
        s = self.telemetry.snapshot()
        tts_label = tts_mean_label(s,seconds=True)
        calls = "\n".join(f"{name}={s.get(name, 0)}" for name in (
            'GEMINI_CALL_ATTEMPTS_SESSION', 'GEMINI_CALL_SUCCESS_SESSION', 'GEMINI_CALL_ERRORS_SESSION'))
        if isinstance(getattr(self,'controls',None),dict) and 'writer_snapshot' in self.controls:
            calls += '\n'+'\n'.join(f'{k}={v}' for k,v in self.controls['writer_snapshot']().items())
        if isinstance(getattr(self,'controls',None),dict) and 'platform_snapshot' in self.controls:
            calls += '\n'+'\n'.join(f'{k}={v}' for k,v in self.controls['platform_snapshot']().items())
        self._copy(f"LIVE SOCIAL DIAGNÓSTICO\n\nDOM: {s['health']['DOM']}\nPONTE: {s['health']['PONTE 8766']}\nGEMINI: {s['health']['GEMINI']}\nTTS: {s['health']['TTS']}\n\nMensagens: {s.get('received',0)}\nRespondidas: {s.get('responses',0)}\nChamadas Gemini: {s['gemini_calls']}\n{calls}\nRespostas Gemini: {s.get('gemini',0)}\nRULE: {s.get('rule',0)}\nFallback: {s.get('fallback',0)}\n429: {s.get('429',0)}\n\nLatência Gemini média: {s['gemini_avg']/1000:.1f}s\nTTS média: {tts_label}\n\nÚltimo erro: {s['last_error']}")
    def _copy(self, value: str) -> None: self.root.clipboard_clear(); self.root.clipboard_append(value); self.root.update()
    def _tick(self) -> None:
        if 'platform_snapshot' in self.controls:
            p=self.controls['platform_snapshot']()
            self.platform.set(p['PLATFORM'])
            self.platform_status.configure(text=' · '.join(f'{k}={v}' for k,v in p.items() if not k.endswith('_RECEIVED') and not k.startswith('TIKTOK_EVENTS_')))
        if 'writer_snapshot' in self.controls:
            w=self.controls['writer_snapshot']()
            self.writer_mode.set(w['WRITER MODE'])
            if callable(getattr(self,'refresh_writer_status',None)):
                self.refresh_writer_status()
            else:
                self.writer_status.configure(text=f"WRITER: {w['WRITER MODE']} · Gemini {w['GEMINI_WRITER_SPEECH']} · Local {w['LOCAL_WRITER_SPEECH']} · Fallback {w['LOCAL_FALLBACK_SPEECH']}")
        if 'presenter_snapshot' in self.controls:
            p=self.controls['presenter_snapshot']()
            cooldowns=' '.join(f"{key}:{int(value)}s" for key,value in p.get('CTA_COOLDOWNS',{}).items())
            cooldowns+=f" · pergunta {p.get('PRESENTER_QUESTION_WINDOW','INATIVA')} · respostas {p.get('PRESENTER_QUESTION_RESPONSES',0)} / autores {p.get('PRESENTER_QUESTION_UNIQUE_AUTHORS',0)}"
            self.presenter_summary.configure(text=f"PRESENTER {p.get('PRESENTER_MODE','OFF')} · {p.get('PRESENTER_STATE','LISTENING')} · silêncio {p.get('SILENCE_TIMER',0):.0f}s / nível {p.get('PRESENTER_SILENCE_LEVEL','0')} · mood {p.get('AUDIENCE_MOOD','QUIET')}\nTema {p.get('PRESENTER_ACTIVE_TOPIC','—')} · reação {p.get('REACTION_ACTIVE','—')} · última ação {p.get('LAST_ENGAGEMENT_ACTION','—')} · {cooldowns}")
        if 'memory_snapshot' in self.controls:
            m = self.controls['memory_snapshot']()
            self.memory_summary.configure(text=(f"MEMÓRIA DA LIVE · {int(m['LIVE_MEMORY_SESSION_AGE']//60)} min\n"
                f"Tópicos: {m['LIVE_MEMORY_TOPICS']} · perguntas: {m['LIVE_MEMORY_QUESTIONS']}\n"
                f"Participantes: {m['LIVE_MEMORY_PARTICIPANTS']} · eventos: {m['LIVE_MEMORY_EVENTS']}\n"
                f"Tema: {m['LIVE_MEMORY_CURRENT_TOPIC']}"))
        if 'director_snapshot' in self.controls:
            d = self.controls['director_snapshot']()
            self.director_summary.configure(text=(f"DIRETOR · {d['DIRECTOR_STATE']}\nAtivo: {d['DIRECTOR_ACTIVE']}\n"
                f"Fila: {d['DIRECTOR_QUEUE_DEPTH']} · próximo: {d['DIRECTOR_NEXT']}\n"
                f"Stale: {d['DIRECTOR_UNITS_STALE']} · dropped: {d['DIRECTOR_UNITS_DROPPED']}"))
        if 'moderation_snapshot' in self.controls:
            m = self.controls['moderation_snapshot']()
            self.mod_summary.configure(text=f"MODERAÇÃO · fila {m['MOD_REVIEW_QUEUE']} · spam {m['MOD_SPAM']} · flood {m['MOD_FLOOD']} · links {m['MOD_SUSPICIOUS_LINK']} · possível ofensa {m['MOD_OFFENSIVE_POSSIBLE']}\n{m['MOD_LAST_ALERT']}")
        phase = (self.core.coords("core")[0] if self.core.coords("core") else 0) + 1
        color = {"FALANDO":"#66f2ff", "PENSANDO":"#299cca", "COOLDOWN":"#e3b341", "ERRO":"#e45d6d"}.get(self.state, _CYAN)
        self.core.itemconfigure("core", fill=color); self.core.itemconfigure("state", text=self.state)
        self.info["ASSUNTO"].configure(text=self.topic); self.info["FALANDO COM"].configure(text=self.last_author); self.info["PERGUNTA"].configure(text=self.last_question); self.info["JARVIS"].configure(text=self.last_response)
        s=self.telemetry.snapshot(); self.health.configure(text="\n".join(f"{k:<13} {v}" for k,v in s["health"].items()))
        ratio = s.get('received', 0) / max(1, s['gemini_calls'])
        self.metrics.configure(text=f"LAT TOTAL  {s['total_avg']:.0f}ms\nLAT DOM    {s['dom_avg']:.0f}ms\nLAT GEMINI {s['gemini_avg']:.0f}ms\nLAT TTS    {tts_mean_label(s)}\nFILA       {s['queue']}\n\nRECEBIDOS  {s.get('received',0)}\nRESPOND.   {s.get('responses',0)}\nRULE       {s.get('rule',0)}\nRESP. IA   {s.get('gemini',0)}\nFALLBACK   {s.get('fallback',0)}\nERROS/429  {s.get('erros',0)}/{s.get('429',0)}\nCHAMADAS GEMINI {s['gemini_calls']}\nCALL OK/ERRO {s.get('GEMINI_CALL_SUCCESS_SESSION',0)}/{s.get('GEMINI_CALL_ERRORS_SESSION',0)}\nMSG/CALL   {ratio:.2f}\nTÓPICO     {s.get('ACTIVE_TOPIC','geral')}\nTROCAS     {s.get('TOPIC_SWITCHES_SESSION',0)}\nPENDING    {s.get('PENDING_QUESTION_ACTIVE',0)}\nPENDING CLR {s.get('PENDING_QUESTION_CLEARED',0)}\nFATOS      {s.get('CONTEXT_FACTS_COUNT',0)}\nRAJADAS    {s.get('bursts_consolidated',0)}\nMESCLADAS  {s.get('messages_consolidated',0)}\nOBSOLETAS  {s.get('stale_dropped',0)}")
        self.guard_metrics.configure(text=f"LOOPS      {s.get('RESPONSE_LOOPS_SESSION',0)}\nMAX TOKENS {s.get('FINISH_MAX_TOKENS_SESSION',0)}\nFIM/CHARS  {s.get('LAST_FINISH_REASON','—')}/{s.get('LAST_OUTPUT_CHARS',0)}\nTTS        {s.get('TTS_STATE','IDLE')} / fila {s.get('TTS_QUEUE_DEPTH',0)}\nTTS stale/barge {s.get('TTS_STALE_DROPPED_SESSION',0)}/{s.get('TTS_BARGE_IN_SESSION',0)}")
        self.audience_metrics.configure(text=f"AUDIÊNCIA {s.get('AUDIENCE_MODE','CALM')} · {s.get('AUDIENCE_CHAT_RATE',0)}/min\nREC/SEL/RESP {s.get('AUDIENCE_MESSAGES_RECEIVED',0)}/{s.get('AUDIENCE_MESSAGES_SELECTED',0)}/{s.get('AUDIENCE_MESSAGES_ANSWERED',0)}\nSIL/SPAM   {s.get('AUDIENCE_MESSAGES_SILENCED',0)}/{s.get('AUDIENCE_SPAM_IGNORED',0)}\nPENDENTES  {s.get('AUDIENCE_PENDING_QUEUE',0)} · TÓPICO {s.get('AUDIENCE_TOPIC','geral')}\nTREND clusters/promovidos {s.get('TREND_CLUSTERS_CREATED',0)}/{s.get('TREND_CLUSTERS_TRENDING',0)} · coletivas {s.get('TREND_COLLECTIVE_ADDRESSED',0)}\nPRESENTER {s.get('PRESENTER_INTERVENTIONS',0)} intervenções · EVENTS {s.get('LIVE_EVENTS_SESSION',0)}")
        self.progress_metrics.configure(text=f"ETAPA      {s.get('CONVERSATION_STAGE','—')}\nPONTOS     {s.get('DELIVERED_POINTS_COUNT',0)}\nAVANÇOS    {s.get('DIALOGUE_ADVANCES_SESSION',0)}\nREPETIÇÕES EVITADAS {s.get('DIALOGUE_REPEATS_PREVENTED',0)}")
        self.root.after(250, self._tick)

