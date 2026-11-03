"""Small Tk presentation components; no pipeline or device control."""
import tkinter as tk
from tkinter import ttk

BG='#09111e'
PANEL='#111e30'
TEXT='#e6edf5'
MUTED='#a5b5c8'

class ScrollPage(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent,style='Base.TFrame')
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0)
        self.scroll=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.body=ttk.Frame(self.canvas,style='Base.TFrame',padding=16)
        self.window=self.canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        self.canvas.bind_all('<MouseWheel>',self.wheel,add='+')

    def wheel(self,event):
        if not self.winfo_viewable():return
        pointed=self.winfo_containing(event.x_root,event.y_root)
        while pointed is not None:
            if pointed is self:
                self.canvas.yview_scroll(-int(event.delta/120),'units');return
            pointed=getattr(pointed,'master',None)

class Tooltip:
    def __init__(self,widget,text):
        self.widget,self.text,self.timer,self.window=widget,text,None,None
        widget.bind('<Enter>',self.schedule,add='+')
        widget.bind('<Leave>',self.hide,add='+')
        widget.bind('<ButtonPress>',self.hide,add='+')
        widget.bind('<Destroy>',self.hide,add='+')

    def schedule(self,event=None):
        self.hide();self.timer=self.widget.after(650,self.show)

    def show(self):
        self.timer=None
        if not self.widget.winfo_exists():return
        self.window=tk.Toplevel(self.widget);self.window.wm_overrideredirect(True)
        self.window.wm_geometry('+%d+%d'%(self.widget.winfo_rootx()+8,self.widget.winfo_rooty()+self.widget.winfo_height()+8))
        tk.Label(self.window,text=self.text+'\nF1: explicação completa',bg='#20324b',fg=TEXT,
            padx=12,pady=8,wraplength=320,justify='left',font=('Segoe UI',10)).pack()

    def hide(self,event=None):
        if self.timer:
            try:self.widget.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None
        if self.window:
            try:self.window.destroy()
            except tk.TclError:pass
            self.window=None

def card(parent,title):
    group=ttk.LabelFrame(parent,text=title,padding=16,style='Card.TLabelframe')
    group.pack(fill='x',pady=(0,14))
    return group

def paragraph(parent,text,muted=False):
    label=ttk.Label(parent,text=text,style='Muted.TLabel' if muted else 'Body.TLabel',wraplength=820,justify='left')
    label.pack(anchor='w',fill='x',pady=(0,8))
    label.bind('<Configure>',lambda e:label.configure(wraplength=max(180,e.width-8)))
    return label
