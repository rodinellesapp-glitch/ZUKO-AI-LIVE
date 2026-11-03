"""Experimental UI integration: isolated Zig Expressividade 1.3 + Walk 1.1 controls."""
from pathlib import Path
import importlib.util
CITY=Path(__file__).resolve().parents[1]/'assistente_avatar/development/zig-walk-1.1'
DEV=CITY/'workspace'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
bridge_module=load('zig111_bridge',DEV/'live_social_01/live_zig_bridge.py')
actions_module=load('zig111_actions',DEV/'live_social_01/zig_actions.py')
panel_module=load('zigwalk11_panel',CITY/'live_social/zig_settings_walk11.py')
def create_bridge(monitor):
    bridge=bridge_module.ViewerEventBridge();bridge.monitor=monitor;bridge.viewer_status={};return bridge.start()
def attach_panel(dashboard):
    # LiveMonitor owns this dashboard; bridge is bound to its existing root.
    bridge=getattr(dashboard.root,'zig_settings_bridge',None)
    dashboard.zig_actions=panel_module.SettingsPanel(dashboard.root,bridge,dashboard.zig_viewer,actions_module.ACTIONS,actions_module.DURATIONS)
    return dashboard.zig_actions
