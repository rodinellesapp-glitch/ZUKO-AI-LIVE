"""Independent Command Center entry point; default starts without platform readers."""
from pathlib import Path
import sys
import tkinter as tk

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'live_social_01'))
from live_monitor import LiveMonitor

def main():
    root=tk.Tk()
    monitor=LiveMonitor(root,source='tiktok-sim')
    root.after(300,monitor.dashboard.toggle_local_mode)
    # No live connection or paid calls are started by this experimental launcher.
    root.mainloop()
    monitor.npc.worker.join(timeout=8)

if __name__=='__main__': main()
