"""Workspace-scoped OS lock, released automatically when its owner exits."""
from pathlib import Path
import json
import os
import msvcrt

ROOT=Path(__file__).resolve().parents[1]

class DashboardLease:
    def __init__(self,path=None):
        self.path=Path(path) if path else ROOT/'runtime/dashboard-owner.lock'
        self.handle=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        handle=self.path.open('a+b')
        # Windows byte-range locks also prohibit reads by the second owner.
        # Inspect size without touching the byte held by the first instance.
        if os.fstat(handle.fileno()).st_size==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:handle.close();return False
        self.handle=handle
        return True
    def close(self):
        if self.handle:
            self.handle.seek(0);msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            self.handle.close();self.handle=None
