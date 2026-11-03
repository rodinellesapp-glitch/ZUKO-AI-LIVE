"""Identical offline fixtures, actual routing, deterministic model/audio doubles."""
import json
from pathlib import Path
from unittest.mock import Mock, patch
from simulate_live_flow_4 import build_monitor as base_monitor, simulate as base_simulate, scenario_100


def model_double(m):
    def generate(text, *args):
        m.mock_calls += 1
        raw=text if text.startswith('WRITER_CONTEXT=') else args[-1] if args else ''
        try: ctx=json.JSONDecoder().raw_decode(raw.removeprefix('WRITER_CONTEXT='))[0]
        except (ValueError,TypeError): ctx={}
        m.writer_inputs.append(ctx)
        message=ctx.get('untrusted_message',text).lower()
        if 'doido' in message:return 'Só um pouquinho, minha sanidade ainda está em versão beta!'
        if 'horrível' in message:return 'Essa conseguiu reprovar até no teste de piada ruim!'
        if 'esquilo' in message:return 'O esquilo fugiu com o controle; agora só passa documentário de castanha!'
        if '67'==message:return '67 apareceu do nada! É nota, idade ou um código misterioso?'
        if 'sol' in message and ('vermelh' in message or 'avermelh' in message):
            return ('No pôr do sol, a luz atravessa mais atmosfera. O azul se espalha pelo caminho, '
                    'e mais vermelho e laranja chegam aos nossos olhos. Poeira e gotículas também influenciam as cores.')
        if ctx.get('factual_anchor'):return ctx['factual_anchor']
        if ctx.get('action')=='THANK':return 'Obrigado pelo apoio! Valeu demais pelo carinho.'
        if ctx.get('reaction'):return 'Essa piada quase pediu desculpa antes de terminar!'
        if ctx.get('action') in {'TALK_TO_RODINELES','PASS_TO_HOST'}:return 'Rodineles, qual é a sua escolha?'
        if ctx.get('action')=='ACKNOWLEDGE':return 'Chega junto! Bom ter você por aqui.'
        if ctx.get('action')=='MAKE_CTA':
            return {'CTA_FOLLOW':'Segue o canal pra acompanhar as próximas!',
                    'CTA_CHAT':'Qual filme você veria de novo?',
                    'CTA_GIFT':'Se quiser apoiar com um presente, valeu demais!'}.get(ctx.get('cta_goal'),'Curtiu? Deixa um like!')
        topic=ctx.get('current_topic','GENERAL_LIVE')
        label='carros' if topic=='carros' else 'futebol' if topic=='futebol' else 'cinema'
        lines=('Imagina um esquilo alugando a Lua só pra esconder castanhas.',
            'Café frio é uma notificação de que você esqueceu da própria felicidade.',
            'A geladeira devia cobrar ingresso de tanto que a gente visita sem comprar nada.',
            'Segunda-feira é o tutorial que ninguém pediu para repetir.',
            'O despertador tem talento para escolher a melhor parte do sonho.',
            'Pizza quadrada em caixa redonda seria uma pequena rebelião geométrica.',
            'Um polvo digitando deve ser o pesadelo do corretor automático.',
            'O controle remoto desaparece com precisão de agente secreto.',
            'Se dragão espirrasse no inverno, acabava a conta de aquecimento.',
            'Pinguim de chinelo: a moda finalmente chegou ao frio.',
            'O gato derruba um copo e chama isso de pesquisa sobre gravidade.',
            'Férias deveriam vir com botão de salvar progresso.',
            'Bolacha quebrada continua deliciosa. Algumas falhas são só cosméticas.',
            'O elevador poderia tocar aplausos quando chega no seu andar.',
            'Meu superpoder imaginário seria achar a ponta da fita adesiva de primeira.',
            'Livro com cheiro de pizza seria uma armadilha editorial.',
            'Na versão pirata do conto, a carruagem vira purê à meia-noite.',
            'O último biscoito do pacote carrega uma responsabilidade enorme.',
            'Uma tartaruga com patins ainda chegaria elegante.',
            'O sorvete derretido é um milk-shake que desistiu da embalagem.',
            'Guarda-chuva invertido inventou a antena de temporal.',
            'A cadeira cheia de roupa foi promovida a guarda-roupa auxiliar.',
            'Um vampiro dentista teria um conflito de interesses complicado.',
            'Chave perdida sempre aparece no último lugar. Afinal, ninguém continua procurando.')
        i=m.mock_calls-1
        prefix=f'Pensando em {label}: ' if topic!='GENERAL_LIVE' else ''
        return prefix+lines[i%len(lines)]
    return generate


def simulate(mode='MISTO', **kwargs):
    def build(clock):
        m=base_monitor(clock);m.set_writer_mode(mode);m.writer_inputs=[]
        m.generator.gemini.generate=Mock(side_effect=model_double(m))
        return m
    with patch('simulate_live_flow_4.build_monitor',build):r=base_simulate(**kwargs)
    m=r['monitor'];w=m.writer.snapshot();v=r['metrics']
    v.update(speech_selected=m.telemetry.snapshot().get('responses',0),
        gemini_writer_speech=w['GEMINI_WRITER_SPEECH'],local_writer_speech=w['LOCAL_WRITER_SPEECH'],
        fallback=w['LOCAL_FALLBACK_SPEECH'],gemini_calls=w['GEMINI_WRITER_ATTEMPTS'],
        meta_speech_blocked=w.get('META_SPEECH_BLOCKED',0),
        stale_dropped=m.telemetry.snapshot().get('stale_dropped',0))
    stamps=[at for at,_ in m.voice.spoken]
    v['average_interval_seconds']=round((stamps[-1]-stamps[0])/max(1,len(stamps)-1),1) if stamps else None
    return r


def report():
    scenarios={'100_events':{},'empty_10min':dict(rows=[],seconds=600),
        'hyper_50':dict(rows=[(i*.6,dict(event_id=str(i),event_type='CHAT_MESSAGE',author_id='A'+str(i),
            author_name='Ana',text='Como começar?' if i%10==0 else 'olha isso')) for i in range(50)],seconds=40),
        'host_5min':dict(rows=[],seconds=330,host_controls=((0,'Jarvis, segura um pouco.'),(300,'Voltei.'))),
        'cars_detour':dict(rows=[(100,dict(event_id='topic',event_type='CHAT_MESSAGE',author_id='Ana',author_name='Ana',
             text='vamos falar de futebol'))],seconds=1200,theme='carros')}
    results={};samples={}
    for mode in ('MISTO','GEMINI+'):
        results[mode]={};samples[mode]=[]
        for name,options in scenarios.items():
            r=simulate(mode,**options);results[mode][name]=r['metrics']
            if name=='empty_10min':samples[mode]=[dict(provider=s.provider,text=s.text) for s in r['speech'][:20]]
        if len(samples[mode])<20:
            r=simulate(mode,rows=[],seconds=1200)
            samples[mode]=[dict(provider=s.provider,text=s.text) for s in r['speech'][:20]]
    result=dict(note='Respostas Gemini são mocks: não comprovam naturalidade real. Sem vencedor automático.',
                real_calls=dict(Gemini=0,Ollama=0,YouTube=0,TikTok=0),comparison=results,samples=samples)
    Path(__file__).with_name('live_flow_41_simulation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Live Flow 4.1 — validação local','',
        'Gemini, TTS e plataformas foram simulados. As amostras não comprovam a naturalidade do Gemini real.',
        'Não foi calculada nota artificial de qualidade nem escolhido vencedor automático.','',
        'MISTO é o padrão. O seletor é mantido em RAM; a preferência não persiste após reinício, pois não existe mecanismo geral apropriado. O arquivo de preferências existente é exclusivo da voz e não foi alterado.','',
        'O Director mantém seleção, prioridade e geração serializada. O Writer redige a ação escolhida, reutiliza cliente/lock/circuit breaker existentes e alimenta a fila TTS existente.','',
        'Duas asserções antigas de percentual mínimo de perguntas foram removidas porque a versão 4.1 pede perguntas opcionais e pausa maior em LOW_RESPONSE. Limites máximos, fila, 429, DOM, TTS e demais testes anteriores foram preservados.','',
        'Limitações: guardas semânticos são heurísticas, não prova universal. Callbacks em RAM reconhecem esquilo, Batman e geladeira. Sem tabela de preços confiável configurada, custo monetário não foi estimado; tokens só aparecem quando a API retorna metadados.','',
        '|Modo / cenário|Falas|Chamadas mock|Palavras médias/máx.|Perguntas|Duplicadas|Intervalo médio|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for mode,scenarios in results.items():
        for name,v in scenarios.items():
            lines.append(f"|{mode} / {name}|{v['spoken_responses']}|{v['gemini_calls']}|{v['average_words']}/{v['max_words']}|{v['questions_percent']}%|{v['duplicate_phrases']}|{v['average_interval_seconds']}s|")
    for mode,rows in samples.items():
        lines.extend(['',f'## Amostras {mode}',''])
        lines.extend(f"{i}. **{row['provider']}** — {row['text']}" for i,row in enumerate(rows,1))
    Path(__file__).with_name('live_flow_41_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    r=report();print(json.dumps(r['comparison'],ensure_ascii=False,indent=2))
