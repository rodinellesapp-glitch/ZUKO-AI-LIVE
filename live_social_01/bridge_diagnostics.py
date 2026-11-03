"""Read-only context and full exception evidence for the local Godot bridge."""
import ctypes
from ctypes import wintypes
import os
import sys
import traceback


def process_context():
    result={'pid':os.getpid(),'parent_pid':os.getppid(),'executable':sys.executable,
            'python':sys.version.split()[0],'cwd':os.getcwd()}
    if os.name!='nt':return result
    token=wintypes.HANDLE()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    api=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    api.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
    api.IsTokenRestricted.argtypes=[wintypes.HANDLE]
    api.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    api.GetSidSubAuthorityCount.argtypes=[ctypes.c_void_p]
    api.GetSidSubAuthorityCount.restype=ctypes.POINTER(ctypes.c_ubyte)
    api.GetSidSubAuthority.argtypes=[ctypes.c_void_p,wintypes.DWORD]
    api.GetSidSubAuthority.restype=ctypes.POINTER(wintypes.DWORD)
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    try:
        if not api.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        result['restricted_token']=bool(api.IsTokenRestricted(token))
        needed=wintypes.DWORD();container=wintypes.DWORD()
        if api.GetTokenInformation(token,29,ctypes.byref(container),ctypes.sizeof(container),ctypes.byref(needed)):
            result['app_container']=bool(container.value)
        api.GetTokenInformation(token,25,None,0,ctypes.byref(needed))
        buffer=ctypes.create_string_buffer(needed.value)
        if not api.GetTokenInformation(token,25,buffer,len(buffer),ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid=ctypes.c_void_p.from_buffer(buffer).value
        count=api.GetSidSubAuthorityCount(sid).contents.value
        rid=api.GetSidSubAuthority(sid,count-1).contents.value
        result['integrity_rid']=rid
        result['integrity']={4096:'LOW',8192:'MEDIUM',12288:'HIGH',16384:'SYSTEM'}.get(rid,str(rid))
    except OSError as error:result['token_query_error']=str(error)
    finally:
        if token:kernel.CloseHandle(token)
    return result


def exception_details(error,*,phase='bridge_worker',host='127.0.0.1',port=18765,operation=None):
    chain=[];current=error;seen=set();inferred=None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append({'type':type(current).__name__,'message':str(current),
                      'errno':getattr(current,'errno',None),'winerror':getattr(current,'winerror',None)})
        for frame in traceback.extract_tb(current.__traceback__):
            text=frame.line or ''
            for call in ('connect','bind','listen','recv','sendall','send'):
                if '.'+call+'(' in text:inferred=call
        current=current.__cause__ or current.__context__
    return {'phase':phase,'operation':operation or inferred or 'UNDETERMINED',
            'endpoint':{'ip':host,'port':port,'family':'AF_INET','transport':'TCP'},
            'process':process_context(),'exceptions':chain,
            'traceback':''.join(traceback.format_exception(type(error),error,error.__traceback__))}
