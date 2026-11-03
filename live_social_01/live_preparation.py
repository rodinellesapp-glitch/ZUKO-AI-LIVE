"""One-click preparation orchestration for the V2 dashboard.

This controller starts only the already selected event source and the panel's
own Godot instance. It never starts a public broadcast or changes preferences.
"""
import time


def tiktok_event_readiness_lines(snapshot):
    """Summarize actual TikTok reader connection and key event capabilities."""
    connection = str(snapshot.get("TIKTOK_CONNECTION", "UNKNOWN"))
    connection_labels = {
        "CONNECTED": "conectado", "CONNECTING": "conectando",
        "WAITING_FOR_LIVE": "aguardando a LIVE", "LIVE_OFFLINE": "LIVE indisponível",
        "DISCONNECTED": "desconectado", "STOPPED": "parado", "OFFLINE": "desconectado",
        "AUTH_REQUIRED": "autorização do adaptador necessária",
        "RATE_LIMITED": "limite temporário do adaptador", "ERROR": "erro",
        "SIMULATOR": "simulador local",
    }
    labels = (
        ("Comentários", "CHAT", "CHAT_RECEIVED"),
        ("Presentes", "GIFTS", "GIFTS_RECEIVED"),
        ("Seguidores", "FOLLOWS", "FOLLOWS_RECEIVED"),
        ("Curtidas", "LIKES", "LIKES_RECEIVED"),
    )
    lines = [f"Leitor TikTok: {connection_labels.get(connection, connection)} ({connection}).",
             "Eventos (capacidade · contagem):"]
    for label, capability, count_key in labels:
        value = str(snapshot.get("TIKTOK_" + capability, "INDISPONÍVEL"))
        validation = str(snapshot.get("TIKTOK_" + capability + "_VALIDATION", ""))
        if value == "SIMULATOR":
            state = "simulado, sem validação real"
        elif validation == "VERIFIED_REAL":
            state = "validação real confirmada"
        elif validation == "SUPPORTED_UNVERIFIED":
            state = "suportado, ainda sem validação real"
        elif connection in {"WAITING_FOR_LIVE", "CONNECTING", "STOPPED"}:
            state = "aguardando detecção do adaptador"
        else:
            state = "indisponível no adaptador"
        count = snapshot.get("TIKTOK_" + count_key, 0)
        lines.append(f"• {label}: {state} · contagem: {count}")
    reason = snapshot.get("TIKTOK_REASON")
    if reason and reason != "—":
        lines.append("Detalhe do adaptador: " + str(reason))
    return lines


class LivePreparationController:
    BUSY_STATES = {"PREPARING_NPC"}

    def __init__(self, root, monitor_provider, on_update, start_source, stop_source,
                 timeout_seconds=30, clock=time.monotonic):
        self.root = root
        self.monitor_provider = monitor_provider
        self.on_update = on_update
        self.start_source = start_source
        self.stop_source = stop_source
        self.timeout_seconds = timeout_seconds
        self.clock = clock
        self.state = "IDLE"
        self.detail = ""
        self._monitor = None
        self._deadline = 0
        self._generation = 0
        self._opened_npc = False
        self._started_source = False
        self._source_attempted = False

    @property
    def busy(self):
        return self.state in self.BUSY_STATES

    def _publish(self, state, detail):
        self.state, self.detail = state, detail
        self.on_update(state, detail)

    def start(self):
        if self.busy:
            return False
        monitor = self.monitor_provider()
        if monitor is None or not hasattr(monitor, "npc"):
            self._publish("FAILED", "O controlador do ZUKO ainda não está disponível.")
            return False
        self._monitor = monitor
        self._generation += 1
        generation = self._generation
        self._deadline = self.clock() + self.timeout_seconds
        self._opened_npc = False
        self._started_source = False
        self._source_attempted = False
        npc_state = monitor.npc.state
        if npc_state == "CLOSING":
            self._publish("FAILED", "O ZUKO está fechando. Aguarde e tente novamente.")
            return False
        if npc_state not in {"ACTIVE", "STARTING"}:
            self._opened_npc = True
            self._publish("PREPARING_NPC", "Abrindo o ZUKO 3D e aguardando confirmação da ponte local…")
            try:
                monitor.npc.open()
            except Exception as error:
                self._fail(f"Não foi possível solicitar a abertura do ZUKO: {error}")
                return False
        else:
            self._publish("PREPARING_NPC", "Aguardando a confirmação da instância do ZUKO já aberta…")
        self._schedule(generation)
        return True

    def cancel(self):
        if not self.busy:
            return False
        self._generation += 1
        cleanup_errors = self._cleanup_owned_components()
        suffix = " Não foi possível concluir a limpeza: " + "; ".join(cleanup_errors) if cleanup_errors else ""
        self._publish("CANCELLED", "Preparação cancelada; componentes iniciados por esta ação foram encerrados." + suffix)
        return True

    def _schedule(self, generation):
        self.root.after(250, lambda: self._tick(generation))

    def _tick(self, generation):
        if generation != self._generation or not self.busy:
            return
        monitor = self._monitor
        npc_state = monitor.npc.state
        if npc_state == "ERROR":
            self._fail("O ZUKO não abriu. Consulte o diagnóstico da ponte e tente novamente.")
            return
        if npc_state == "CLOSING":
            self._fail("A abertura foi interrompida enquanto o ZUKO fechava.")
            return
        if npc_state == "ACTIVE":
            try:
                self._prepare_source()
            except Exception as error:
                self._fail(f"ZUKO abriu, mas a fonte selecionada não pôde ser preparada: {error}")
                return
            self._publish("READY", self._ready_detail())
            return
        if self.clock() >= self._deadline:
            self._fail("Tempo esgotado aguardando a confirmação do ZUKO. Confira Godot e a porta local 18765.")
            return
        self._schedule(generation)

    def _prepare_source(self):
        if self._source_attempted:
            return
        self._source_attempted = True
        monitor = self._monitor
        if monitor.local_test_mode or monitor.reading:
            return
        was_reading = bool(monitor.reading)
        try:
            self.start_source()
        finally:
            self._started_source = not was_reading and bool(monitor.reading)

    def _ready_detail(self):
        monitor = self._monitor
        if monitor.local_test_mode:
            source = "Entrada em teste local; nenhuma fonte real foi conectada."
        elif monitor.source == "tiktok-sim":
            source = "Fonte selecionada: simulador TikTok; não há conexão com uma LIVE real."
        elif monitor.reading:
            source = "Fonte selecionada iniciada pelo adaptador existente."
        else:
            source = "ZUKO pronto; a fonte selecionada não confirmou leitura. Confira Eventos e Live e os Diagnósticos."
        return "ZUKO 3D pronto (ponte local confirmada). " + source

    def _fail(self, detail):
        self._generation += 1
        cleanup_errors = self._cleanup_owned_components()
        if cleanup_errors:
            detail += " Limpeza incompleta: " + "; ".join(cleanup_errors)
        self._publish("FAILED", detail)

    def _cleanup_owned_components(self):
        monitor = self._monitor
        errors = []
        if monitor and self._started_source and monitor.reading:
            try:
                self.stop_source()
            except Exception as error:
                errors.append(f"fonte: {error}")
        if monitor and self._opened_npc and monitor.npc.state in {"STARTING", "ACTIVE", "ERROR"}:
            try:
                monitor.npc.close_npc()
            except Exception as error:
                errors.append(f"ZUKO: {error}")
        return errors
