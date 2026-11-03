"""Same read-only TCP comparison in Work and a user-started Windows session.

Starts only a test-owned Godot when 18765 is free. No voice, Gemini, public
broadcast, security changes, elevation, alternate port or transport.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'live_social_01'),str(ROOT/'npc_runtime')]
from bridge_diagnostics import process_context,exception_details
from show_tcp import ShowClient

HOST='127.0.0.1';PORT=18765


def command_read(args,timeout=8):
    try:
        result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        encoding='oem' if os.name=='nt' else 'utf-8'
        return {'command':args,'returncode':result.returncode,
                'stdout':result.stdout.decode(encoding,errors='replace'),
                'stderr':result.stderr.decode(encoding,errors='replace')}
    except (OSError,subprocess.TimeoutExpired) as error:
        return {'command':args,'unavailable':True,'error':str(error)}


def port_information():
    system=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'
    netstat=command_read([str(system/'netstat.exe'),'-ano','-p','tcp'])
    if 'stdout' in netstat:
        netstat['matching_rows']=[line for line in netstat.pop('stdout').splitlines() if re.search(r':18765\s',line)]
    ranges=command_read([str(system/'netsh.exe'),'interface','ipv4','show','excludedportrange','protocol=tcp'])
    return {'connections':netstat,'excluded_ranges':ranges}


def project_instances():
    rows=[]
    try:
        import psutil
        for process in psutil.process_iter(['pid','ppid','name','cmdline']):
            try:
                info=process.info;args=info['cmdline'] or []
                own_dashboard=any(Path(arg).name=='abrir_zuko_v2.py' for arg in args)
                own_godot=any(str(ROOT/'npc_runtime/godot').casefold() in arg.casefold() for arg in args)
                if (own_dashboard and Path(process.cwd()).resolve()==ROOT) or own_godot:
                    rows.append({'pid':info['pid'],'parent_pid':info['ppid'],'name':info['name'],
                                 'role':'dashboard' if own_dashboard else 'godot'})
            except (psutil.Error,OSError,ValueError):continue
    except ImportError:return {'unavailable':True,'reason':'psutil not available'}
    return {'observed':rows,'note':'Processes whose information is inaccessible are not assumed absent.'}


def resolve_listener(row,known_processes):
    fields=row.split()
    if len(fields)<5 or fields[0].upper()!='TCP' or fields[3].upper()!='LISTENING':return None
    pid_text=fields[4]
    try:pid=int(pid_text)
    except ValueError:return None
    matches=[item for item in known_processes.get('observed',[]) if item.get('pid')==pid]
    owner={'pid':pid,'name':None,'executable':None,'parent_pid':None,'role':None}
    if matches:owner.update(matches[0])
    try:
        import psutil
        process=psutil.Process(pid)
        owner.update({'name':process.name(),'executable':process.exe(),'parent_pid':process.ppid()})
    except (ImportError,OSError,ValueError):pass
    return {'local_address':fields[1],'state':fields[3].upper(),'owner':owner,'netstat_row':row}


def existing_listeners(port_snapshot,known_processes,host,port):
    connections=port_snapshot.get('connections',{})
    rows=connections.get('matching_rows',[])
    expected=host+':'+str(port)
    found=[]
    for row in rows:
        listener=resolve_listener(row,known_processes)
        if listener and listener['local_address']==expected:found.append(listener)
    return found


def wait_status(client,predicate,timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        status=client.poll_status()
        if status and predicate(status):return status
        time.sleep(.03)
    raise TimeoutError('Godot did not return the expected presentation_status. Last state: '+repr(client.status))


def initialize_presentation(client):
    # The existing Dashboard handshake enables status publication in Godot.
    # Keep presentation local and stationary; this does not start a broadcast.
    client.send_presentation(walking=False,live=False)
    return wait_status(client,lambda _state:True)


def offline_tiktok_states():
    """Only after real TCP passes: no SDK networking, AI, voice or public room."""
    from live_tiktok_real_source import TikTokRealEventSource
    results=[]
    for reason,expected in (('CONNECTION_FAILED',4),('AUTH_REQUIRED',1),('NETWORK_ACCESS_DENIED',1)):
        attempts=[]
        source=TikTokRealEventSource('seu_canal')
        def session(generation):
            attempts.append(generation);source._state_set('ERROR',reason)
        source._session_runner=session;source._stopping.wait=lambda _seconds:False
        assert source.health()['connection']=='STOPPED'
        assert source.start();source._thread.join(3)
        assert not source._thread.is_alive() and len(attempts)==expected
        source.stop();assert source.health()['connection']=='STOPPED'
        results.append({'simulated_reason':reason,'attempts':len(attempts),'state_after_stop':'STOPPED'})
    from live_tiktok_source import TikTokSimulatorSource
    from live_tiktok_adapter import TikTokLiveAdapter
    source=TikTokSimulatorSource();source.start();adapter=TikTokLiveAdapter(source)
    event=adapter.normalize({'event_type':'CHAT_MESSAGE','event_id':'tcp-offline-test','author_id':'simulado',
                             'author_name':'SIMULADO','text':'Evento simulado do teste local.'})
    assert event is not None and event.metadata['simulation'] is True and event.source_verified is False
    source.stop()
    return {'result':'PASS','simulation':True,'transport_cases':results,'normalized_simulated_event':True,
            'real_tiktok_connections':0,'real_gemini_calls':0}


def run(context):
    directory=ROOT/'evidence/tcp-10013'/(context+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid()))
    directory.mkdir(parents=True,exist_ok=False)
    report={'context_label':context,'process':process_context(),'endpoint':{'ip':HOST,'port':PORT},
            'processes_before':project_instances(),'ports_before':port_information(),'operations':[],
            'bridge_passed':False,'tiktok_tests':{'result':'NOT_RUN','reason':'Real bridge must pass first.'}}
    report['probe_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result_path=directory/'resultado.json'
    godot=None;log=None;client=ShowClient(port=PORT);probe=None
    try:
        listeners=existing_listeners(report['ports_before'],report['processes_before'],HOST,PORT)
        if listeners:
            report['failure']={'phase':'preflight_existing_listener','operation':'bind_skipped',
                'reason':'A instância existente já atende nesta porta; o diagnóstico não vai iniciar outra instância.',
                'endpoint':{'ip':HOST,'port':PORT,'family':'AF_INET','transport':'TCP'},
                'listeners':listeners,'process':report['process']}
            return report,result_path
        probe=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        try:
            probe.bind((HOST,PORT));report['operations'].append({'operation':'bind','result':'PASS','endpoint':[HOST,PORT]})
            probe.listen(1);report['operations'].append({'operation':'listen','result':'PASS','endpoint':[HOST,PORT]})
        except OSError as error:
            report['failure']=exception_details(error,phase='python_port_preflight',host=HOST,port=PORT)
            return report,result_path
        finally:probe.close();probe=None
        executable=Path(os.environ.get('NPC_GODOT_EXE') or Path.home()/'OneDrive/Desktop/Godot_v3.6-stable_win64.exe')
        if not executable.is_file():raise FileNotFoundError('Existing Godot 3.6 executable not found.')
        log=(directory/'godot.log').open('w',encoding='utf-8')
        godot=subprocess.Popen([str(executable),'--path',str(ROOT/'npc_runtime/godot')],
            cwd=ROOT/'npc_runtime',env=dict(os.environ,NPC_SHOW_PORT=str(PORT)),stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        report['godot']={'pid':godot.pid,'executable':str(executable),'parent_pid':os.getpid()}
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            content=(directory/'godot.log').read_text(encoding='utf-8',errors='replace')
            if 'escutando somente em '+HOST+':'+str(PORT) in content:break
            if godot.poll() is not None:raise RuntimeError('Test-owned Godot exited before listening.')
            time.sleep(.1)
        else:raise TimeoutError('Godot did not confirm listen before the deadline.')
        report['operations'].append({'operation':'Godot.listen','result':'PASS','endpoint':[HOST,PORT],'pid':godot.pid})
        report['ports_listening']=port_information()
        original_connect=socket.socket.connect
        def observed_connect(sock,address):
            try:
                value=original_connect(sock,address)
                report['operations'].append({'operation':'socket.connect','result':'PASS','destination':address,
                                             'local':sock.getsockname(),'pid':os.getpid()})
                return value
            except OSError as error:
                detail=exception_details(error,phase='exact_socket_connect',host=HOST,port=PORT,operation='connect')
                detail['local_address_after_failure']=sock.getsockname()
                report['exact_connect_failure']=detail
                raise
        with patch.object(socket.socket,'connect',observed_connect):client.connect()
        report['operations'].append({'operation':'protocol_identity','result':'PASS','identity':{'app':'NPC_LIVE_SHOW','protocol':1}})
        status=initialize_presentation(client)
        report['operations'].append({'operation':'presentation_initialization','result':'PASS','status':status})
        for animation in ('Wave','Idle'):
            client.send_animation(animation,False)
            status=wait_status(client,lambda state:state['animation']==animation)
            report['operations'].append({'operation':'animation_confirmation','animation':animation,'result':'PASS','status':status})
        client.close();time.sleep(.25)
        client.connect();initialize_presentation(client)
        report['operations'].append({'operation':'reconnect_and_identity','result':'PASS'})
        client.send_control('idle');wait_status(client,lambda state:state['animation']=='Idle')
        client.close();report['operations'].append({'operation':'close_connection','result':'PASS'})
        report['bridge_passed']=True
        report['tiktok_tests']=offline_tiktok_states()
    except Exception as error:
        report['failure']=exception_details(error,phase='godot_probe',host=HOST,port=PORT)
    finally:
        client.close()
        if probe:probe.close()
        if godot:
            if godot.poll() is None:
                godot.terminate()
                try:godot.wait(timeout=4)
                except subprocess.TimeoutExpired:godot.kill();godot.wait(timeout=3)
            report['owned_godot_closed']=godot.poll() is not None
        if log:log.close()
        report['ports_after']=port_information()
        result_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        result_path.with_suffix('.sha256').write_text(hashlib.sha256(result_path.read_bytes()).hexdigest(),encoding='ascii')
    return report,result_path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',choices=('work','usuario'),default='usuario')
    args=parser.parse_args();report,path=run(args.context)
    print('Resultado: '+str(path))
    print('Contexto real do processo: '+json.dumps(report['process'],ensure_ascii=False))
    print('Ponte aprovada: '+str(report['bridge_passed']))
    if report.get('failure'):print('Falha: '+report['failure']['operation']+' | '+report['failure']['exceptions'][-1]['message'])
    print('Somente processos de teste próprios foram encerrados. Nenhuma configuração de segurança foi alterada.')
    sys.exit(0 if report['bridge_passed'] else 1)
