"""Native desktop UI for Intel macOS Ventura. All Tk work stays on the UI thread."""
import json
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from numpy_streamer import Stopped
import mobile_service as service

BG = '#10151e'
SURFACE = '#1d2735'
FG = '#e7edf6'
MUTED = '#a2b2c5'
ACCENT = '#5ce0b8'


class App:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.closed = False
        self.events = queue.Queue()
        self.controls = []
        self.entries = []
        self.last_metrics = {}
        self.saved_chats = []
        self.loaded_name = ''
        root.title('RamPilot 2.1 · Local AI')
        root.geometry('1080x800')
        root.minsize(940, 720)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=('Helvetica', 11))
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(18, 10), background=SURFACE)
        style.map('TNotebook.Tab', background=[('selected', '#2c3d50')])
        style.configure('TButton', padding=(10, 7), background=SURFACE)
        style.map('TButton', background=[('active', '#304358')])
        style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, foreground=FG, rowheight=42)
        style.map('Treeview', background=[('selected', '#315867')])
        style.configure('TEntry', fieldbackground=SURFACE, foreground=FG)
        style.configure('TSpinbox', fieldbackground=SURFACE, foreground=FG)
        style.configure('TCombobox', fieldbackground=SURFACE, foreground=FG)
        data = Path.home() / 'Library/Application Support/RamPilot2'
        result = json.loads(service.configure(str(data), str(Path(__file__).with_name('catalog.json'))))
        self.preferences = result['settings']
        self.context = tk.StringVar(value=str(self.preferences['context']))
        self.budget = tk.StringVar(value=str(self.preferences['budget_mib']))
        self.max_tokens = tk.StringVar(value=str(self.preferences['max_tokens']))
        self.temperature = tk.StringVar(value=str(self.preferences['temperature']))
        self.keep_history = tk.BooleanVar(value=self.preferences['save_history'])
        self.status = tk.StringVar(value='Choose a small model in Models to get started.')
        self.model_title = tk.StringVar(value='Your private AI workspace')
        self.stats_text = tk.StringVar(value='CPU inference · model weights are read one block at a time')
        self.download_text = tk.StringVar(value='Downloads resume after interruption. Each file is SHA-256 verified.')
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        sidebar = tk.Frame(root, bg='#18202c', padx=16, pady=22, width=220)
        sidebar.grid(row=0, column=0, sticky='nsew')
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(5, weight=1)
        tk.Label(sidebar, text='RamPilot', font=('Helvetica', 25, 'bold'), bg='#18202c', fg=FG).grid(sticky='w')
        tk.Label(sidebar, text='2.1  ·  LOCAL AI', bg='#18202c', fg=ACCENT).grid(sticky='w', pady=(2, 20))
        self.button(sidebar, '+  New conversation', self.new_chat).grid(sticky='ew', pady=(0, 14))
        tk.Label(sidebar, text='SAVED CONVERSATIONS', font=('Helvetica', 9), bg='#18202c', fg=MUTED).grid(sticky='w')
        self.search = tk.StringVar()
        search_entry = ttk.Entry(sidebar, textvariable=self.search)
        search_entry.grid(sticky='ew', pady=(8, 8))
        self.search.trace_add('write', lambda *_: self.refresh_chats())
        self.sessions = tk.Listbox(sidebar, bg='#18202c', fg=FG, selectbackground='#315867',
                                   borderwidth=0, highlightthickness=0, exportselection=False,
                                   font=('Helvetica', 11), activestyle='none')
        self.sessions.grid(sticky='nsew')
        self.sessions.bind('<Double-1>', lambda _: self.open_selected_chat())
        self.button(sidebar, 'Open selected chat', self.open_selected_chat).grid(sticky='ew', pady=(8, 6))
        self.button(sidebar, 'Export chat', self.export).grid(sticky='ew', pady=3)
        self.button(sidebar, 'Export diagnostics', self.export_diagnostics).grid(sticky='ew', pady=3)
        tk.Label(sidebar, text='No account. No API bill.\nYour chats stay on this Mac.', bg='#18202c', fg=MUTED,
                 justify='left', font=('Helvetica', 10)).grid(sticky='w', pady=(18, 0))
        main = tk.Frame(root, bg=BG, padx=22, pady=20)
        main.grid(row=0, column=1, sticky='nsew')
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        tk.Label(main, textvariable=self.model_title, bg=BG, fg=FG, font=('Helvetica', 21, 'bold'), anchor='w').grid(sticky='ew')
        self.status_label = tk.Label(main, textvariable=self.status, bg=BG, fg=ACCENT, justify='left',
                                     anchor='w', wraplength=740, height=3)
        self.status_label.grid(sticky='ew', pady=(4, 8))
        self.tabs = ttk.Notebook(main)
        self.tabs.grid(sticky='nsew')
        self.chat_page = ttk.Frame(self.tabs, padding=(0, 12))
        self.models_page = ttk.Frame(self.tabs, padding=14)
        self.settings_page = ttk.Frame(self.tabs, padding=14)
        for page, title in [(self.chat_page, 'Chat'), (self.models_page, 'Models'), (self.settings_page, 'Settings')]:
            self.tabs.add(page, text=title)
        self.build_chat()
        self.build_models(result['models'])
        self.build_settings()
        tk.Label(main, textvariable=self.stats_text, fg=MUTED, bg=BG, anchor='w', justify='left',
                 wraplength=740, height=3, font=('Helvetica', 9)).grid(sticky='ew', pady=(6, 0))
        self.render_history(result['history'])
        self.refresh_chats()
        self.poll_id = root.after(50, self.poll)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Command-n>', lambda _: self.new_chat())
        root.bind('<Control-n>', lambda _: self.new_chat())
        root.bind('<Escape>', lambda _: service.cancel() if self.busy else None)

    def button(self, parent, title, action):
        button = ttk.Button(parent, text=title, command=action)
        self.controls.append(button)
        return button

    def build_chat(self):
        page = self.chat_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        area = ttk.Frame(page)
        area.grid(sticky='nsew')
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.chat = tk.Text(area, height=8, wrap='word', state='disabled', bg=SURFACE, fg=FG,
                            font=('Helvetica', 12), padx=16, pady=14, borderwidth=0, highlightthickness=0)
        self.chat.grid(sticky='nsew')
        self.chat.tag_configure('heading', foreground=ACCENT, font=('Helvetica', 10, 'bold'))
        self.chat.tag_configure('notice', foreground=MUTED)
        scroll = ttk.Scrollbar(area, command=self.chat.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.chat.configure(yscrollcommand=scroll.set)
        tk.Label(page, text='Return to send · Shift+Return for a new line · Escape to stop', bg=BG, fg=MUTED,
                 font=('Helvetica', 9)).grid(sticky='w', pady=(10, 5))
        self.input = tk.Text(page, height=4, wrap='word', bg=SURFACE, fg=FG, insertbackground=FG,
                             font=('Helvetica', 12), padx=10, pady=8, highlightthickness=0, borderwidth=0)
        self.input.grid(sticky='ew')
        self.input.bind('<Return>', self.enter)
        actions = ttk.Frame(page)
        actions.grid(sticky='ew', pady=(10, 0))
        self.button(actions, 'Send message', self.send).pack(side='left')
        self.stop_button = ttk.Button(actions, text='Stop', command=service.cancel, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.button(actions, 'Copy last reply', self.copy_last).pack(side='right')

    def build_models(self, models):
        page = self.models_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ttk.Label(page, text='Start small. Qwen 2.5 0.5B is the recommended first model.', wraplength=650).grid(sticky='w', pady=(0, 12))
        self.model_tree = ttk.Treeview(page, columns=('name', 'size', 'state'), show='headings', selectmode='browse', height=4)
        for name, title, width in [('name', 'Model', 240), ('size', 'Disk space', 110), ('state', 'State', 140)]:
            self.model_tree.heading(name, text=title)
            self.model_tree.column(name, width=width, minwidth=70)
        self.model_tree.grid(sticky='nsew')
        self.model_tree.bind('<<TreeviewSelect>>', self.describe_model)
        # Retained as an internal selection interface for simple scripted UI tests.
        self.models = ttk.Combobox(page, values=[m['name'] for m in models], state='readonly')
        self.models.current(min(self.preferences['selected_model'], len(models)-1))
        self.refresh_models()
        self.model_tree.selection_set(str(self.models.current()))
        self.model_description = tk.StringVar(value='')
        ttk.Label(page, textvariable=self.model_description, wraplength=650, justify='left').grid(sticky='ew', pady=14)
        buttons = ttk.Frame(page)
        buttons.grid(sticky='ew')
        self.button(buttons, 'Download / verify / resume', self.download).pack(side='left')
        self.button(buttons, 'Load model', self.load).pack(side='left', padx=6)
        self.button(buttons, 'Import folder', self.import_folder).pack(side='left', padx=2)
        self.button(buttons, 'Unload', lambda: self.task(self.unload)).pack(side='right')
        self.progress = ttk.Progressbar(page, maximum=100)
        self.progress.grid(sticky='ew', pady=(18, 8))
        ttk.Label(page, textvariable=self.download_text, wraplength=650, justify='left').grid(sticky='ew')
        ttk.Label(page, text='An SSD is strongly recommended. Every generated token rereads the model weights.\n'
                  'Import: standard dense Qwen2/Qwen2.5 SafeTensors. GGUF and quantized weights are unsupported.',
                  wraplength=650, foreground=MUTED, justify='left').grid(sticky='ew', pady=(20, 0))

    def build_settings(self):
        page = self.settings_page
        page.columnconfigure(1, weight=1)
        fields = [('Context tokens', self.context, 64, 2048, 64),
                  ('Planning RAM budget (MB)', self.budget, 512, 16384, 256),
                  ('Maximum reply tokens', self.max_tokens, 1, 1024, 32),
                  ('Temperature (0 = repeatable greedy)', self.temperature, 0, 2, .1)]
        for row, (label, variable, minimum, maximum, step) in enumerate(fields):
            ttk.Label(page, text=label).grid(row=row, column=0, sticky='w', padx=(0, 16), pady=7)
            entry = ttk.Spinbox(page, textvariable=variable, from_=minimum, to=maximum, increment=step, width=12)
            entry.grid(row=row, column=1, sticky='w', pady=7)
            self.entries.append(entry)
        self.context_entry, self.budget_entry = self.entries[:2]
        ttk.Label(page, text='System instructions').grid(row=4, column=0, sticky='nw', pady=(14, 6))
        self.system_prompt = tk.Text(page, height=5, wrap='word', bg=SURFACE, fg=FG, insertbackground=FG,
                                     font=('Helvetica', 11), highlightthickness=0, padx=8, pady=8)
        self.system_prompt.insert('1.0', self.preferences['system_prompt'])
        self.system_prompt.grid(row=4, column=1, sticky='ew', pady=(14, 6))
        self.entries.append(self.system_prompt)
        self.history_toggle = ttk.Checkbutton(page, text='Save future conversations locally as plain JSON', variable=self.keep_history)
        self.history_toggle.grid(row=5, column=0, columnspan=2, sticky='w', pady=10)
        self.controls.append(self.history_toggle)
        self.button(page, 'Save settings', self.save_preferences).grid(row=6, column=0, sticky='w', pady=8)
        ttk.Label(page, text='Context and RAM changes require reloading the model. The RAM budget checks planned\n'
                  'allocations; it is not an operating-system memory cap. macOS RAM figures show peak RSS.\n'
                  'Turning off saving does not delete previously saved conversations.',
                  wraplength=650, foreground=MUTED, justify='left').grid(row=7, column=0, columnspan=2, sticky='w', pady=14)

    def number(self, variable, default, minimum, maximum):
        try: return max(minimum, min(maximum, int(variable.get())))
        except (ValueError, TypeError): return default

    def parameters(self):
        return self.number(self.context,512,64,2048), self.number(self.budget,2048,512,16384)

    def options(self):
        context, budget = self.parameters()
        try: temperature = float(self.temperature.get())
        except ValueError: temperature = .7
        return dict(context=context, budget_mib=budget, max_tokens=self.number(self.max_tokens,128,1,1024),
                    temperature=temperature, system_prompt=self.system_prompt.get('1.0','end').strip(),
                    save_history=self.keep_history.get(), selected_model=self.selected_model())

    def save_preferences(self):
        if self.busy: return
        try:
            previous = self.preferences
            self.preferences = service.save_settings(self.options())
            self.context.set(str(self.preferences['context'])); self.budget.set(str(self.preferences['budget_mib']))
            self.temperature.set(str(self.preferences['temperature'])); self.max_tokens.set(str(self.preferences['max_tokens']))
            if any(previous[k] != self.preferences[k] for k in ['context','budget_mib']): self.unload()
            self.status.set('Settings saved. Context and RAM changes apply after loading the model.')
            self.refresh_chats()
        except Exception as error: messagebox.showerror('RamPilot', str(error))

    def onStatus(self, text): self.events.put(('status',str(text)))
    def onToken(self, text): self.events.put(('token',str(text)))
    def onProgress(self, text): self.events.put(('progress',str(text)))
    def onMetrics(self, text): self.events.put(('metrics',str(text)))

    def append(self, text, tag=None):
        self.chat.configure(state='normal')
        self.chat.insert('end', text, tag or '')
        self.chat.configure(state='disabled')
        self.chat.see('end')

    def render_history(self, history):
        self.chat.configure(state='normal'); self.chat.delete('1.0','end'); self.chat.configure(state='disabled')
        if not history:
            self.append('Welcome to RamPilot\n\n','heading')
            self.append('Open Models, download Qwen 2.5 0.5B, then load it.\n\n'
                        'Your model runs locally on your CPU. Just one decoder block is loaded at a time.\n\n','notice')
        for message in history:
            self.append(message['role'].upper()+'\n','heading'); self.append(message['content']+'\n\n')

    def poll(self):
        if self.closed: return
        for _ in range(200):
            try: kind, data = self.events.get_nowait()
            except queue.Empty: break
            if kind == 'status': self.status.set(data)
            elif kind == 'token': self.append(data)
            elif kind == 'error': messagebox.showerror('RamPilot', data)
            elif kind == 'metrics':
                value = json.loads(data); self.last_metrics = value
                memory = value.get('rss_bytes',0)/1048576
                self.stats_text.set(f"{value.get('current_group','idle')} · live blocks {value.get('live_weight_groups',0)} · peak RAM {memory:.0f} MB\n"
                                    f"{value.get('generated_tokens',0)} reply tokens · {value.get('tokens_per_second',0):.2f} tok/s including prompt · disk reads {value.get('bytes_read',0)/1073741824:.2f} GB")
            elif kind == 'progress':
                value = json.loads(data); self.progress['value'] = value['done']/max(1,value['total'])*100
                self.download_text.set(f"{value['done']/1048576:.1f} / {value['total']/1048576:.1f} MB · {value['bytes_per_second']/1048576:.1f} MB/s")
            elif kind == 'loaded':
                self.loaded_name = data; self.model_title.set(data); self.tabs.select(self.chat_page)
            elif kind == 'sent':
                self.input.configure(state='normal'); self.input.delete('1.0','end'); self.input.configure(state='disabled'); self.append('\n\n')
            elif kind == 'reply_error':
                self.append('\n[Reply interrupted: '+data+']\nYour message is kept below so you can retry.\n\n','notice')
            elif kind == 'done':
                self.busy = False; self.input.configure(state='normal'); self.models.configure(state='readonly')
                self.model_tree.state(['!disabled']); self.sessions.configure(state='normal')
                for control in self.controls: control.configure(state='normal')
                for entry in self.entries: entry.configure(state='normal')
                self.stop_button.configure(state='disabled'); self.refresh_models(); self.refresh_chats(); self.input.focus_set()
        self.poll_id = self.root.after(50, self.poll)

    def task(self, action, reply=False):
        if self.busy or self.closed: return
        self.busy = True; self.input.configure(state='disabled'); self.models.configure(state='disabled')
        self.model_tree.state(['disabled']); self.sessions.configure(state='disabled')
        for control in self.controls: control.configure(state='disabled')
        for entry in self.entries: entry.configure(state='disabled')
        self.stop_button.configure(state='normal')
        def work():
            try: action()
            except Stopped as error:
                self.onStatus('Stopped')
                if reply: self.events.put(('reply_error',str(error)))
            except Exception as error:
                self.onStatus('Operation needs attention')
                self.events.put(('reply_error' if reply else 'error',str(error)))
            finally: self.events.put(('done',''))
        threading.Thread(target=work, daemon=True).start()

    def send(self):
        if self.busy: return
        text = self.input.get('1.0','end').strip()
        if not text: return
        if not service.is_loaded():
            self.status.set('Download and load a model in Models first.'); self.tabs.select(self.models_page); return
        self.append('YOU\n','heading'); self.append(text+'\n\n'); self.append('ASSISTANT\n','heading')
        maximum = self.preferences['max_tokens']
        def action(): service.respond(text,maximum,self); self.events.put(('sent',''))
        self.task(action,reply=True)

    def enter(self, event):
        if event.state & 1: return
        self.send(); return 'break'

    def selected_model(self):
        selected = self.model_tree.selection()
        return int(selected[0]) if selected else max(0,self.models.current())

    def describe_model(self, _=None):
        if not hasattr(self,'model_description'): return
        index = self.selected_model(); value = service.model_status()[index]; self.models.current(index)
        self.model_description.set(value['name']+' · '+value['license']+'\n'
                                  +('Verified download marker present.' if value['ready'] else 'Not ready yet. Download / resume first.')
                                  +' Load to begin CPU inference.')

    def refresh_models(self):
        values = service.model_status()
        for i, value in enumerate(values):
            row = (value['name'],f"{value['bytes']/1073741824:.2f} GB",'Ready' if value['ready'] else 'Download needed')
            if self.model_tree.exists(str(i)): self.model_tree.item(str(i),values=row)
            else: self.model_tree.insert('', 'end', iid=str(i), values=row)
        self.describe_model()

    def download(self):
        index = self.selected_model(); self.task(lambda: service.download(index,self))

    def load(self):
        index = self.selected_model(); context,budget = self.parameters(); name = service.model_status()[index]['name']
        def action(): service.load(index,context,budget,self); self.events.put(('loaded',name))
        self.task(action)

    def import_folder(self):
        if self.busy: return
        folder = filedialog.askdirectory(title='Choose a Qwen2/Qwen2.5 SafeTensors folder')
        if folder:
            context,budget = self.parameters()
            def action(): service.load_folder(folder,context,budget,self); self.events.put(('loaded',Path(folder).name))
            self.task(action)

    def unload(self):
        service.unload()
        self.events.put(('loaded','Your private AI workspace'))
        self.onStatus('Model unloaded. Live weight tensors and KV cache released.')

    def refresh_chats(self):
        query = self.search.get().casefold() if hasattr(self,'search') else ''
        self.saved_chats = [item for item in service.conversations() if query in item['title'].casefold()]
        self.sessions.delete(0,'end')
        for item in self.saved_chats: self.sessions.insert('end',item['title'])

    def open_selected_chat(self):
        if self.busy: return
        selected = self.sessions.curselection()
        if not selected: return
        try:
            item = self.saved_chats[selected[0]]
            self.render_history(service.open_chat(item['id'])); self.tabs.select(self.chat_page)
            self.status.set('Opened '+item['title'])
        except Exception as error: messagebox.showerror('RamPilot',str(error))

    def new_chat(self):
        if self.busy: return
        try:
            service.new_chat(); self.render_history([]); self.refresh_chats(); self.input.delete('1.0','end')
            self.status.set('New conversation. Saved chats remain in the sidebar.'); self.tabs.select(self.chat_page)
        except Exception as error: messagebox.showerror('RamPilot',str(error))

    def copy_last(self):
        if service.current_history():
            self.root.clipboard_clear(); self.root.clipboard_append(service.current_history()[-1]['content'])
            self.status.set('Last completed reply copied.')

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.txt',initialfile='RamPilot-chat.txt')
        if path:
            try: Path(path).write_text(self.chat.get('1.0','end'),'utf-8'); self.status.set('Chat exported.')
            except OSError as error: messagebox.showerror('RamPilot',str(error))

    def export_diagnostics(self):
        path = filedialog.asksaveasfilename(defaultextension='.json',initialfile='RamPilot-diagnostics.json')
        if path:
            try:
                Path(path).write_text(json.dumps(service.diagnostics(),indent=2),'utf-8')
                self.status.set('Diagnostics exported. No chat text, usernames or model paths are included.')
            except OSError as error: messagebox.showerror('RamPilot',str(error))

    def close(self):
        if self.closed: return
        self.closed = True; service.cancel(); self.root.after_cancel(self.poll_id); self.root.destroy()


if __name__ == '__main__':
    try: App(tk.Tk()).root.mainloop()
    except Exception:
        log = Path.home() / 'Library/Logs/RamPilot2-error.log'
        log.parent.mkdir(parents=True,exist_ok=True); log.write_text(traceback.format_exc()); raise
