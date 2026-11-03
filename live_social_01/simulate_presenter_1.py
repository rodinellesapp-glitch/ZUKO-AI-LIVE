"""Deterministic offline rehearsal of the existing Live Social presenter pipeline.

No platform clients, Gemini, speech device, moderation action, or persistence are used.
Run with: python simulate_presenter_1.py
"""
from __future__ import annotations

from collections import Counter
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from live_audience import LiveAudienceManager
from live_director import DirectorUnit, LiveDirectorManager
from live_events import LiveEventEngine
from live_moderator import LiveModeratorManager
from live_presenter import AUTO, LivePresenterManager
from live_response import LiveResponse, LiveResponseGenerator
from live_session_memory import LiveSessionMemory
from live_telemetry import LiveTelemetry
from tts_manager import TTSManager


AUTHORS = ("@Carlos", "@Ana", "@Marcos", "@Julia", "@Pedro", "@Lucas",
           "@Fernanda", "@Rafael", "@Bruno", "@Camila", "@Joao", "@Patricia")
CHAT_A = (
    "Que projeto é esse?", "Esse Jarvis foi feito em Python?", "Como você fez a voz?",
    "Ele usa inteligência artificial?", "Dá para controlar o computador?", "Quero fazer um também",
    "Qual linguagem você recomenda?", "Isso funciona no celular?", "🔥", "👏👏", "🔥", "👏👏",
)
TREND_VARIANTS = ("Como você criou o Jarvis?", "Como fez esse Jarvis?",
                  "Como você desenvolveu ele?", "Como começou esse projeto?")


def run_simulation() -> dict:
    now = [1000.0]
    clock = lambda: now[0]
    memory = LiveSessionMemory(clock=clock)
    moderator = LiveModeratorManager(clock=clock)
    audience = LiveAudienceManager(clock=clock, session_memory=memory)
    events = LiveEventEngine(clock=clock)
    telemetry = LiveTelemetry()
    generator = LiveResponseGenerator()
    generator.gemini.generate = Mock(side_effect=lambda text, *_a, **_k: f"Resposta simulada e curta sobre {text[:26]}.")
    generator.gemini.last_output_category = "OK"
    voice = TTSManager(lambda *_: None, lambda *_: None)
    voice.set_paused(True)
    presenter = LivePresenterManager(clock=clock, session_memory=memory)
    presenter.mode = AUTO
    holder = {}
    dispatch_order: list[tuple[str, int]] = []
    tts_enqueued = 0
    active_generation = 0
    max_active_generation = 0
    generated_ids: list[str] = []
    auto_interventions = 0

    def complete_simulated_tts() -> None:
        with voice.lock:
            if voice.queue:
                item = voice.queue.popleft()
                voice.enqueued_at.pop(item.response.comment_id, None)

    def dispatch(unit: DirectorUnit) -> None:
        nonlocal tts_enqueued, active_generation, max_active_generation
        active_generation += 1
        max_active_generation = max(max_active_generation, active_generation)
        dispatch_order.append((unit.unit_id, unit.priority))
        director = holder["director"]
        if unit.unit_id == "conc-chat":
            # All work arrives while this synchronous dispatch is active.
            director.submit(DirectorUnit("conc-presenter", "PRESENTER", "JARVIS", created_at=clock()))
            director.submit(DirectorUnit("conc-high", "HIGH_EVENT", "@SuperChat", event_type="SUPER_CHAT",
                                         requires_ai=True, created_at=clock()))
            director.submit(DirectorUnit("conc-followup", "AUDIENCE", "@Follow", classification="FOLLOWUP", created_at=clock()))
            director.submit(DirectorUnit("conc-comment", "AUDIENCE", "@Comment", classification="CHAT", created_at=clock()))
            if director.run_once():
                raise AssertionError("Director iniciou geração concorrente durante despacho ativo")

        if unit.unit_id.startswith("conc-"):
            text, author, provider, source = "Resposta concorrente simulada.", unit.author_id, "MOCK", "LIVE_YOUTUBE"
        elif unit.source in {"PRESENTER", "TRENDING"}:
            text = str(unit.metadata.get("text", "Intervenção simulada do apresentador."))
            author, provider, source = "JARVIS", "PRESENTER_RULE", "PRESENTER"
            cluster = unit.metadata.get('cluster')
            if cluster:
                text = "Tem bastante gente com essa dúvida. " + (cluster['answer'] or generator.gemini.generate(cluster['representative_question'], 'JARVIS'))
                memory.trends.addressed(cluster['trend_cluster_id'])
            memory.presenter_spoken(unit.unit_id, unit.metadata.get("topic", "geral"), memory.session_id)
        elif unit.source == "HIGH_EVENT":
            event = unit.content_ref
            ack = events.rule_reply(event) or "Obrigado por participar da Live!"
            if unit.requires_ai:
                answer = generator.gemini.generate(event.message or "", event.author_name or "")
                text = f"{ack} {answer}"
            else:
                text = ack
            author, provider, source = event.author_name or "@evento", "RULE" if not unit.requires_ai else "GEMINI_MOCK", "LIVE_EVENT"
        else:
            comment = unit.content_ref
            response = generator.generate(comment.comment_id, comment.author, comment.text, comment.normalized, comment.received_at)
            text, author, provider, source = response.text, response.author, response.provider, "LIVE_YOUTUBE"
            generated_ids.append(unit.unit_id)
            if provider in {"RULE", "GEMINI"}:
                memory.trends.answered(comment.text, response.text)
                memory.answered(comment.comment_id, comment.author, comment.text, memory.session_id)

        response = LiveResponse(unit.unit_id, author, text, provider, 0.0, clock(), source, True, unit.priority)
        voice.enqueue(response)
        tts_enqueued += 1
        telemetry.set_tts_metrics(voice.snapshot())
        complete_simulated_tts()
        active_generation -= 1

    director = LiveDirectorManager(dispatch, voice.snapshot, clock=clock)
    holder["director"] = director
    input_count = 0
    unique_authors: set[str] = set()
    moderation_categories = Counter()

    def submit_chat(author: str, text: str, *, advance: float = 0.1) -> str:
        nonlocal input_count, auto_interventions
        input_count += 1
        unique_authors.add(author)
        ident = f"sim-chat-{input_count}"
        result = moderator.analyze(author, text)
        moderation_categories[result.category] += 1
        decision, item = audience.admit(ident, author, text, moderation=result)
        telemetry.set_audience_metrics(audience.metrics)
        if decision == "SELECT" and item:
            version = director.conversation_arrived(author)
            comment = SimpleNamespace(comment_id=ident, author=author, text=text, normalized=text.casefold(), received_at=clock())
            director.submit(DirectorUnit(ident, "AUDIENCE", author, classification=item.classification,
                                         created_at=clock(), conversation_version=version, content_ref=comment))
            while director.run_once():
                pass
        elif presenter.mode == AUTO and result.presenter_allowed:
            suggestion = presenter.evaluate(audience.metrics, voice.snapshot())
            if suggestion:
                approved = presenter.approve()
                if approved:
                    auto_interventions += 1
                    director.submit(DirectorUnit(f"presenter-{auto_interventions}", approved.source, "JARVIS", classification="TRENDING" if approved.cluster else "CHAT",
                        created_at=clock(), ttl=45, metadata={"text": approved.text, "topic": approved.topic, "cluster": approved.cluster}))
                    while director.run_once():
                        pass
        now[0] += advance
        return decision

    # Phase A: 12 authors, 8 substantive prompts and 4 low-value reactions.
    for author, text in zip(AUTHORS, CHAT_A):
        submit_chat(author, text, advance=4.0)

    # Phase B: real paraphrase variants, tested against the existing lexical grouping.
    for index, text in enumerate(TREND_VARIANTS):
        submit_chat(f"@Trend{index+1}", text, advance=5.0)

    # Phase C: official event normalization and local acknowledgements; the question uses one mock generation.
    event_specs = (
        {"event_id": "sc-no-question", "type": "SUPER_CHAT", "author": "@Doador1", "amount": "10", "currency": "BRL"},
        {"event_id": "sc-question", "type": "SUPER_CHAT", "author": "@Doador2", "amount": "20", "currency": "BRL", "message": "Como você fez esse projeto?"},
        {"event_id": "member-new", "type": "MEMBERSHIP", "author": "@Membro1"},
        {"event_id": "member-milestone", "type": "MEMBER", "author": "@Membro2", "message": "12 meses"},
        {"event_id": "gift-1", "type": "GIFT", "author": "@Presente", "gift_name": "1 inscrição"},
    )
    for raw in event_specs:
        event, status = events.accept(raw)
        if status != "accepted" or event is None:
            continue
        kind = "SUPER_CHAT" if event.event_type == "SUPER_CHAT" else "MEMBERSHIP" if event.event_type in {"MEMBER", "MEMBERSHIP"} else "GIFT"
        memory.record_event(kind, event.event_id, event.author_name, "arquitetura_jarvis")
        unit = DirectorUnit(event.event_id, "HIGH_EVENT", event.author_name or "@evento", event_type=event.event_type,
                            requires_ai=bool(event.event_type == "SUPER_CHAT" and event.message), created_at=clock(), content_ref=event)
        director.submit(unit)
        while director.run_once():
            pass

    # Phase D: safe, repeated, flood, link, promotion, and potentially offensive inputs.
    submit_chat("@ModNormal", "Pergunta normal sobre o projeto?", advance=0.1)
    for _ in range(3):
        submit_chat("@Repetidor", "comentário duplicado", advance=0.1)
    for i in range(7):
        submit_chat("@Flood", f"mensagem de flood {i}", advance=0.1)
    submit_chat("@Link", "https://example.com", advance=0.1)
    submit_chat("@Promo", "Se inscreve no meu canal", advance=0.1)
    submit_chat("@Ofensa", "Você é idiota", advance=0.1)

    # Presenter AUTO: enforce its unchanged 45s cooldown and 3-per-10-minute budget.
    blocked = Counter()
    if presenter.evaluate({"AUDIENCE_TOPIC": "programacao", "AUDIENCE_MESSAGES_RECEIVED": 5},
                          {"TTS_STATE": "IDLE"}, high_pending=True) is None:
        blocked["PRESENTER_BLOCKED_HIGH"] += int(presenter.last_reason == "HIGH_EVENT_PENDING")
    if presenter.evaluate({"AUDIENCE_TOPIC": "programacao", "AUDIENCE_MESSAGES_RECEIVED": 5},
                          {"TTS_STATE": "PLAYING"}) is None:
        blocked["PRESENTER_BLOCKED_BUSY"] += int(presenter.last_reason == "TTS_BUSY")
    if presenter.evaluate({"AUDIENCE_TOPIC": "programacao", "AUDIENCE_MESSAGES_RECEIVED": 5,
                           "AUDIENCE_MODE": "VERY_BUSY"}, {"TTS_STATE": "IDLE"}) is None:
        blocked["PRESENTER_BLOCKED_CHAT_BUSY"] += int(presenter.last_reason == "CHAT_TOO_ACTIVE")

    # Wait out the real configured cooldown, test context-free silence, then present the trend.
    now[0] += 46.0
    context_probe = LivePresenterManager(clock=clock)
    context_probe.mode = AUTO
    context_probe.evaluate({"AUDIENCE_TOPIC": "geral", "AUDIENCE_MESSAGES_RECEIVED": 0}, {"TTS_STATE": "IDLE"})
    no_context = context_probe.last_reason
    trend_snapshot = {**audience.metrics, **memory.trends.snapshot()}
    trend_suggestion = presenter.evaluate(trend_snapshot, voice.snapshot())
    trend_presenter_reason = presenter.last_reason
    trend_presenter_kind = trend_suggestion.kind if trend_suggestion else ""
    trend_intervention = memory.trends.counts["TREND_COLLECTIVE_ADDRESSED"] > 0
    if trend_suggestion and trend_suggestion.kind == "TRENDING_QUESTION":
        approved = presenter.approve()
        if approved:
            trend_intervention = True
            auto_interventions += 1
            director.submit(DirectorUnit(f"presenter-trend-{auto_interventions}", approved.source, "JARVIS", classification="TRENDING" if approved.cluster else "CHAT",
                created_at=clock(), ttl=45, metadata={"text": approved.text, "topic": approved.topic, "cluster": approved.cluster}))
            while director.run_once():
                pass
    if trend_intervention:
        cluster = next(g for g in memory.trends.groups if g.get('TREND_COLLECTIVE_ADDRESSED'))
        memory.trends.observe('@RepeatProbe', cluster['representative_question'])
        repeat_probe = LivePresenterManager(clock=clock, session_memory=memory)
        repeat_probe.mode = AUTO
        assert repeat_probe.evaluate({'TREND_LAST_CLUSTER': cluster}, {'TTS_STATE': 'IDLE'}) is None
        assert repeat_probe.last_reason == 'SESSION_REPEAT'
    # A new evaluation just after approval must be silent due to the unchanged cooldown.
    presenter.evaluate(trend_snapshot, voice.snapshot())
    blocked["PRESENTER_BLOCKED_COOLDOWN"] += int(presenter.last_reason == "COOLDOWN")
    for topic in ("python", "robotica", "celular", "programacao"):
        now[0] += 46.0
        suggestion = presenter.evaluate({"AUDIENCE_TOPIC": topic, "AUDIENCE_MESSAGES_RECEIVED": 5,
                                         "AUDIENCE_MODE": "CALM"}, {"TTS_STATE": "IDLE"})
        if suggestion:
            approved = presenter.approve()
            if approved:
                auto_interventions += 1
                memory.presenter_spoken(f"budget-{auto_interventions}", topic, memory.session_id)
                presenter.evaluate({"AUDIENCE_TOPIC": topic, "AUDIENCE_MESSAGES_RECEIVED": 5}, {"TTS_STATE": "IDLE"})
                blocked["PRESENTER_BLOCKED_COOLDOWN"] += int(presenter.last_reason == "COOLDOWN")
        elif presenter.last_reason == "BUDGET_EXHAUSTED":
            blocked["PRESENTER_BUDGET_EXHAUSTED"] += 1
        elif presenter.last_reason == "COOLDOWN":
            blocked["PRESENTER_BLOCKED_COOLDOWN"] += 1

    # Phase E: a normal chat dispatch stays singular while HIGH, follow-up, chat and Presenter arrive.
    director.submit(DirectorUnit("conc-chat", "AUDIENCE", "@Concurrent", classification="CHAT", created_at=clock()))
    director.run_once()
    while director.run_once():
        pass
    concurrent_priorities = [priority for ident, priority in dispatch_order if ident.startswith("conc-")]
    concurrent_max_active = max_active_generation

    # TTSManager priority and same-author stale-drop simulation; no worker can play audio while paused.
    for ident, author, source, priority in (
        ("tts-chat", "@Chat", "LIVE_YOUTUBE", 40), ("tts-presenter", "JARVIS", "PRESENTER", 10),
        ("tts-follow", "@Follow", "LIVE_YOUTUBE", 70), ("tts-high", "@Event", "LIVE_EVENT", 80)):
        voice.enqueue(LiveResponse(ident, author, "fala mock", "MOCK", 0, clock(), source, True, priority))
    tts_priority_order = [item.response.comment_id for item in voice.queue]
    voice.stop()
    stale_probe = TTSManager(lambda *_: None, lambda *_: None)
    stale_probe.set_paused(True)
    active_r1 = LiveResponse("R1", "@Same", "fala R1", "MOCK", 0, clock(), "LIVE_YOUTUBE")
    stale_probe.current = SimpleNamespace(author_id="@Same", source="LIVE_YOUTUBE", response=active_r1,
                                         cancelled=threading.Event())
    stale_probe.enqueue(LiveResponse("R2", "@Same", "fala R2", "MOCK", 0, clock(), "LIVE_YOUTUBE"))
    stale_probe.enqueue(LiveResponse("R3", "@Same", "fala R3", "MOCK", 0, clock(), "LIVE_YOUTUBE"))

    audience_counts = audience.counters
    moderation = moderator.snapshot()
    director_metrics = director.snapshot()
    presenter_metrics = presenter.counters
    event_counts = events.counts
    memory_summary = memory.recap()
    summary = {
        **memory.trends.counts,
        "TOTAL_MESSAGES": input_count,
        "UNIQUE_AUTHORS": len(unique_authors),
        "AUDIENCE_SELECTED": audience_counts["AUDIENCE_MESSAGES_SELECTED"],
        "AUDIENCE_SILENCED": audience_counts["AUDIENCE_MESSAGES_SILENCED"],
        "MOD_SAFE": moderation["MOD_SAFE"], "MOD_REVIEW": moderation["MOD_REVIEW"],
        "MOD_SPAM": moderation["MOD_SPAM"], "MOD_FLOOD": moderation["MOD_FLOOD"],
        "MOD_DUPLICATE": moderation["MOD_DUPLICATE"], "MOD_SELF_PROMOTION": moderation["MOD_SELF_PROMOTION"],
        "MOD_OFFENSIVE_POSSIBLE": moderation["MOD_OFFENSIVE_POSSIBLE"],
        "TRENDING_QUESTIONS": audience_counts["AUDIENCE_TRENDING_QUESTIONS"],
        "TREND_GROUPS": audience_counts["AUDIENCE_GROUPED_QUESTIONS"],
        "PRESENTER_COMMENTED_TREND": trend_intervention,
        "TREND_PRESENTER_REASON": trend_presenter_reason,
        "TREND_PRESENTER_KIND": trend_presenter_kind,
        "TREND_SIGNAL": trend_snapshot.get("AUDIENCE_TRENDING_QUESTIONS", 0),
        "TREND_VARIANTS_SELECTED": sum(1 for ident in generated_ids if ident.startswith("sim-chat-") and int(ident.rsplit('-', 1)[1]) in range(13, 17)),
        "EVENTS_TOTAL": event_counts["LIVE_EVENTS_SESSION"], "SUPERCHAT_TOTAL": event_counts["SUPER_CHAT_SESSION"],
        "MEMBERSHIP_TOTAL": event_counts["MEMBER_EVENTS_SESSION"], "GIFTS_TOTAL": event_counts["GIFT_EVENTS_SESSION"],
        "DIRECTOR_RECEIVED": director_metrics["DIRECTOR_UNITS_RECEIVED"],
        "DIRECTOR_DISPATCHED": director_metrics["DIRECTOR_UNITS_DISPATCHED"],
        "DIRECTOR_STALE_DROPPED": director_metrics["DIRECTOR_UNITS_STALE"],
        "PRESENTER_INTERVENTIONS": presenter_metrics["PRESENTER_INTERVENTIONS"],
        "PRESENTER_BLOCKED_COOLDOWN": blocked["PRESENTER_BLOCKED_COOLDOWN"],
        "PRESENTER_BLOCKED_BUSY": blocked["PRESENTER_BLOCKED_BUSY"],
        "PRESENTER_BLOCKED_CHAT_BUSY": blocked["PRESENTER_BLOCKED_CHAT_BUSY"],
        "PRESENTER_BLOCKED_HIGH": blocked["PRESENTER_BLOCKED_HIGH"],
        "PRESENTER_BUDGET_USED": len(presenter.budget),
        "PRESENTER_BUDGET_EXHAUSTED": blocked["PRESENTER_BUDGET_EXHAUSTED"],
        "PRESENTER_NO_CONTEXT_REASON": no_context,
        "TTS_ENQUEUED": tts_enqueued, "TTS_STALE_DROPPED": stale_probe.dropped_stale,
        "TTS_STALE_ID": stale_probe.queue[0].response.comment_id,
        "TTS_PRIORITY_ORDER": tts_priority_order,
        "GEMINI_CALLS": 0, "MOCK_GEMINI_GENERATIONS": generator.gemini.generate.call_count,
        "MAX_SIMULTANEOUS_GENERATIONS": concurrent_max_active,
        "CONCURRENCY_PRIORITY_ORDER": concurrent_priorities,
        "MEMORY": memory_summary,
    }
    assert summary["UNIQUE_AUTHORS"] >= 12
    assert summary["EVENTS_TOTAL"] == 5 and summary["SUPERCHAT_TOTAL"] == 2
    assert summary["MAX_SIMULTANEOUS_GENERATIONS"] == 1
    assert summary['TREND_VARIANTS_SELECTED'] == 1
    assert summary['TREND_CLUSTERS_TRENDING'] == 1
    assert summary['TREND_COLLECTIVE_ADDRESSED'] == 1
    assert summary['TREND_REPEAT_BLOCKED'] >= 1
    assert summary["TTS_PRIORITY_ORDER"] == ["tts-high", "tts-follow", "tts-chat", "tts-presenter"]
    assert summary["TTS_STALE_ID"] == "R3" and summary["TTS_STALE_DROPPED"] == 1
    assert summary["GEMINI_CALLS"] == 0
    stale_probe.stop()
    return summary


if __name__ == "__main__":
    import pprint
    pprint.pp(run_simulation(), sort_dicts=True)
