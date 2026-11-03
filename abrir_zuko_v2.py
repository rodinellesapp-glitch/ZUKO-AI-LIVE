"""V2 entry point: replace presentation only, keep the existing monitor and engines."""
from pathlib import Path
import sys
import os,json,hashlib
import tkinter as tk
from tkinter import messagebox

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'live_social_01'))


def runtime_identity_lines(runtime, modules):
    lines=['ZUKO_RUNTIME_ID | '+json.dumps(runtime,ensure_ascii=False)]
    lines.extend('ZUKO_RUNTIME_MODULE | '+json.dumps({'name':name,**modules[name]},ensure_ascii=False)
                 for name in sorted(modules))
    return lines
import live_monitor
from live_dashboard_v2 import LiveDashboardV2

def main():
    from zuko_runtime_lease import DashboardLease
    lease=DashboardLease()
    if not lease.acquire():
        dialog=tk.Tk();dialog.withdraw()
        messagebox.showinfo('ZUKO já aberto','Já existe um Dashboard neste workspace. Use a janela aberta.',parent=dialog)
        dialog.destroy();return
    live_monitor.LiveDashboard=LiveDashboardV2
    root=tk.Tk();monitor=live_monitor.LiveMonitor(root,source='tiktok-sim')
    root.title('ZUKO LIVE SOCIAL V3 — Command Center experimental')
    root.geometry('1200x680+25+20');root.minsize(960,600)
    monitor.dashboard.attach_runtime(monitor)
    modules={name:{'path':str(Path(sys.modules[name].__file__).resolve()),'sha256':hashlib.sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()} for name in ('live_monitor','zuko_presenter','zuko_litellm','live_dashboard_v2')}
    runtime={'pid':os.getpid(),'python':sys.executable,'cwd':os.getcwd(),'entry':str(Path(__file__).resolve())}
    for line in runtime_identity_lines(runtime,modules):monitor._log(line)
    root.after(300,monitor.dashboard.toggle_local_mode)
    try:root.mainloop()
    finally:
        monitor.npc.worker.join(timeout=8)
        lease.close()

if __name__=='__main__':main()
