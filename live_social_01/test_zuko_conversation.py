import threading
import unittest
from collections import Counter
from types import SimpleNamespace

from zuko_conversation import Conversation
from zuko_presenter import ZukoPresenter


class FakeClock:
    def __init__(self): self.now=0.0
    def __call__(self): return self.now


def event(author, text):
    return SimpleNamespace(event_type='CHAT_MESSAGE',author_name=author,
        author_key=author.lower(),text=text)


class ZukoConversationTests(unittest.TestCase):
    def test_keeps_last_six_complete_interactions_for_one_participant(self):
        memory=Conversation()
        for index in range(8):
            memory.delivered(event('Ana',f'pergunta {index}'),f'resposta {index}')
        history=memory.context(event('Ana','e isso?'))
        self.assertEqual(len(history),6)
        self.assertEqual([item['comment'] for item in history],
            [f'pergunta {i}' for i in range(2,8)])
        self.assertEqual([item['spoken_reply'] for item in history],
            [f'resposta {i}' for i in range(2,8)])

    def test_participant_history_is_isolated_and_public_context_is_shared(self):
        memory=Conversation()
        memory.delivered(event('Ana','A IA ajuda a caldeira?'),'Analisa os sensores.')
        memory.delivered(event('Bruno','Meu torno está vibrando.'),'Verifique a vibração e os mancais.')
        self.assertEqual(memory.context(event('Ana','E como ela faria?')),
            [{'comment':'A IA ajuda a caldeira?','spoken_reply':'Analisa os sensores.'}])
        self.assertEqual(memory.context(event('Bruno','E esse equipamento?')),
            [{'comment':'Meu torno está vibrando.','spoken_reply':'Verifique a vibração e os mancais.'}])
        shared=memory.recent_public_context()
        self.assertEqual(len(shared),2)
        self.assertEqual([item['comment'] for item in shared],
            ['A IA ajuda a caldeira?','Meu torno está vibrando.'])

    def test_ttl_expires_participant_and_public_history(self):
        clock=FakeClock();memory=Conversation(clock=clock,ttl_seconds=60)
        ana=event('Ana','Fale sobre esse equipamento.')
        memory.delivered(ana,'Posso analisar os dados do equipamento.')
        clock.now=60
        self.assertEqual(memory.context(ana),[])
        self.assertEqual(memory.recent_public_context(),[])
        self.assertEqual(len(memory.turns),0)

    def test_participant_memory_has_a_hard_capacity(self):
        memory=Conversation(max_participants=2)
        for name in ('Ana','Bruno','Caio'):
            memory.delivered(event(name,'Oi.'),'Olá!')
        self.assertLessEqual(len(memory.turns),2)

    def test_only_successfully_delivered_tts_commits_a_completed_turn(self):
        memory=Conversation()
        presenter=object.__new__(ZukoPresenter)
        presenter.lock=threading.RLock();presenter.stats=Counter()
        presenter.deliveries={};presenter.conversation=memory
        presenter.history=[];presenter.config={'local_ai':{'model':'qwen3:1.7b'}}
        presenter.log=lambda event,**data: presenter.history.append({'event':event,**data})
        original=event('Ana','Como a IA ajuda?')
        response=SimpleNamespace(comment_id='reply-1',text='Ela analisa sinais dos sensores.')
        presenter.tts_result('TTS_OK',response)  # No generated/queued delivery entry.
        self.assertEqual(memory.context(original),[])
        presenter.deliveries[response.comment_id]=(original,False,'OLLAMA_LOCAL')
        presenter.tts_result('TTS_CANCELLED',response)
        self.assertEqual(memory.context(original),[])
        presenter.deliveries[response.comment_id]=(original,False,'OLLAMA_LOCAL')
        presenter.tts_result('TTS_OK',response)
        self.assertEqual(memory.context(original),[
            {'comment':'Como a IA ajuda?','spoken_reply':'Ela analisa sinais dos sensores.'}])
        self.assertEqual(presenter.history[-1]['event'],'TTS_DELIVERY_RESULT')
        self.assertEqual(presenter.history[-1]['outcome'],'TTS_OK')
        self.assertEqual(presenter.history[-1]['model'],'qwen3:1.7b')


if __name__=='__main__':
    unittest.main()
