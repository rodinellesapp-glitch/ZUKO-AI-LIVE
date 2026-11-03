"""Logical 90-minute session: no waiting, network, model or audio."""
from live_session_memory import LiveSessionMemory
from live_presenter import LivePresenterManager


def simulate():
    now=[0.0]
    memory=LiveSessionMemory(clock=lambda:now[0])
    presenter=LivePresenterManager(clock=lambda:now[0],session_memory=memory)
    for minute,topic in ((0,'Python'),(10,'robótica'),(25,'celular'),(40,'Python'),(70,'robótica')):
        now[0]=minute*60
        memory.observe(str(minute),'autor'+str(minute),'Como aprender '+topic+'?')
        if minute==0:
            memory.answered('0','autor0','Como aprender Python?')
            memory.presenter_spoken('presenter','python')
        if minute==10: memory.record_event('SUPER_CHAT','sc','autor1')
        if minute==40: old_status=memory.lookup('Como aprender Python?')['status']
        if minute==70: memory.record_event('MEMBER','member','autor2')
    now[0]=85*60
    for i in range(5): result=memory.observe('again'+str(i),'novo'+str(i),'Como aprender Python?')
    now[0]=90*60
    presenter_result=presenter.evaluate({'AUDIENCE_TOPIC':'python','AUDIENCE_MESSAGES_RECEIVED':20},{},force=True)
    return dict(snapshot=memory.snapshot(),old_status=old_status,repeat_status=result['status'],
                recap=presenter.prepare_recap(),presenter_silenced=presenter_result is None,
                calls={'Gemini':0,'Ollama':0,'YouTube':0})


if __name__=='__main__': print(simulate())
