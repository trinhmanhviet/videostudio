"""VideoStudio for Windows: tray icon by default, the control panel with --panel.

Both use the existing guarded service launchers (start/stop/restart_system.ps1).
"""
import base64
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import urllib.request


def workspace_root():
    base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
    for candidate in (base,base.parent):
        if (candidate/'scripts'/'start_system.ps1').is_file():return candidate
    raise RuntimeError('Đặt VideoStudio.exe trong thư mục source VideoStudio có thư mục scripts.')


def command(root, action):
    scripts={'start':'start_system.ps1','stop':'stop_system.ps1','restart':'restart_system.ps1'}
    script=root/'scripts'/scripts[action]
    expression="$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); & '"+str(script).replace("'","''")+"'; exit $LASTEXITCODE"
    encoded=base64.b64encode(expression.encode('utf-16le')).decode('ascii')
    return ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',encoded]


def read_status():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result={}
    for name,url in [('server','http://127.0.0.1:8877/api/health'),('flow','http://127.0.0.1:8879/api/status'),('comfy','http://127.0.0.1:8188/system_stats')]:
        try:
            with opener.open(url,timeout=1.5) as response:result[name]=json.load(response)
        except (OSError,ValueError):result[name]=None
    return result


def run_action(root,action,emit):
    log=root/'data'/'launcher.log';log.parent.mkdir(parents=True,exist_ok=True)
    # Files avoid inherited pipe handles keeping the UI busy after services start.
    with log.open('wb') as output:
        process=subprocess.Popen(command(root,action),cwd=root,stdout=output,stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        offset=0
        while True:
            with log.open('rb') as reader:
                reader.seek(offset);chunk=reader.read(65536);offset+=len(chunk)
            if chunk:emit(('log',chunk.decode('utf-8',errors='replace')))
            code=process.poll()
            if code is not None:
                with log.open('rb') as reader:
                    reader.seek(offset);tail=reader.read()
                if tail:emit(('log',tail.decode('utf-8',errors='replace')))
                return code
            time.sleep(.2)


def open_studio():
    candidates=[Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',
                Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Google/Chrome/Application/chrome.exe',
                Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe']
    chrome=next((p for p in candidates if p.is_file()),None)
    if chrome is None:raise RuntimeError('Không tìm thấy Chrome. Mở http://localhost:8877 trong Chrome đã cài extension.')
    subprocess.Popen([str(chrome),'http://localhost:8877/'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def panel_main():
    import tkinter as tk
    from tkinter import ttk,messagebox
    try:root_path=workspace_root()
    except RuntimeError as error:
        window=tk.Tk();window.withdraw();messagebox.showerror('VideoStudio',str(error));window.destroy();return 1
    window=tk.Tk();window.title('VideoStudio');window.geometry('780x590');window.minsize(660,460)
    checking='--self-check' in sys.argv
    if checking:window.withdraw()
    style=ttk.Style(window);style.theme_use('clam')
    style.configure('TButton',padding=(14,9));style.configure('Title.TLabel',font=('Segoe UI',22,'bold'))
    panel=ttk.Frame(window,padding=22);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='VideoStudio',style='Title.TLabel').pack(anchor='w')
    ttk.Label(panel,text='Mở hệ thống, rồi làm video trong Chrome như bình thường.').pack(anchor='w',pady=(2,16))
    status=ttk.Frame(panel);status.pack(fill='x',pady=(0,16))
    labels={}
    for name,title in [('server','Studio'),('flow','Chrome · Flow'),('comfy','ComfyUI')]:
        box=ttk.LabelFrame(status,text=title,padding=10);box.pack(side='left',fill='x',expand=True,padx=(0,8))
        labels[name]=ttk.Label(box,text='Đang kiểm tra…');labels[name].pack(anchor='w')
    actions=ttk.Frame(panel);actions.pack(fill='x',pady=(0,12))
    events=queue.Queue();busy=False;polling=False;buttons=[]
    notice=tk.StringVar(value='Bấm Mở hệ thống để bắt đầu.')
    console=tk.Text(panel,height=14,wrap='word',font=('Consolas',10),bg='#14201a',fg='#d6edca',relief='flat',state='disabled')
    def log(text):
        console.configure(state='normal');console.insert('end',text)
        if int(console.index('end-1c').split('.')[0])>1200:console.delete('1.0','300.0')
        console.see('end');console.configure(state='disabled')
    def start_action(action):
        nonlocal busy
        if busy:return
        busy=True
        for button in buttons:button.configure(state='disabled')
        notice.set({'start':'Đang mở hệ thống…','stop':'Đang dừng các dịch vụ…','restart':'Đang khởi động lại…'}[action]);log('\n'+notice.get()+'\n')
        def work():
            try:events.put(('done',(action,run_action(root_path,action,events.put))))
            except Exception as error:events.put(('log',str(error)+'\n'));events.put(('done',(action,1)))
        threading.Thread(target=work,daemon=True).start()
    def browse():
        try:open_studio()
        except Exception as error:messagebox.showerror('Mở Studio',str(error),parent=window)
    for text,action in [('Mở hệ thống','start'),('Khởi động lại','restart'),('Dừng hệ thống','stop')]:
        button=ttk.Button(actions,text=text,command=lambda a=action:start_action(a));button.pack(side='left',padx=(0,8));buttons.append(button)
    ttk.Button(actions,text='Vào Studio ↗',command=browse).pack(side='left')
    ttk.Label(panel,textvariable=notice,wraplength=700).pack(anchor='w',pady=(0,8))
    console.pack(fill='both',expand=True)
    ttk.Label(panel,text='Dừng/khởi động lại sẽ bị chặn nếu có video đang chạy. Đóng cửa sổ này vẫn giữ video chạy.',wraplength=700).pack(anchor='w',pady=(10,3))
    ttk.Label(panel,text=str(root_path),foreground='#58645c').pack(anchor='w')
    def poll():
        nonlocal polling
        if not polling:
            polling=True
            def work():events.put(('status',read_status()))
            threading.Thread(target=work,daemon=True).start()
        window.after(4000,poll)
    def drain():
        nonlocal busy,polling
        while True:
            try:kind,value=events.get_nowait()
            except queue.Empty:break
            if kind=='log':log(value)
            elif kind=='done':
                busy=False
                for button in buttons:button.configure(state='normal')
                action,code=value
                notice.set(('Đã dừng dịch vụ. Bấm Mở hệ thống để dùng lại.' if action=='stop' else 'Hoàn tất. Bấm Vào Studio để làm video.') if code==0 else 'Cần kiểm tra: xem nhật ký bên dưới hoặc data/launcher.log.')
            elif kind=='status':
                polling=False;server=value['server'];flow=value['flow'];comfy=value['comfy']
                mode={'cdp':'chữ qua Chrome riêng','extension':'chữ qua extension'}.get((server or {}).get('text_transport'))
                labels['server'].configure(text=('Đang chạy · '+mode) if server and server.get('service')=='videostudio' and mode else 'Chưa sẵn sàng')
                labels['flow'].configure(text='Đã kết nối' if flow and flow.get('service')=='videostudio-dedicated-cdp' and flow.get('connected') else 'Chưa kết nối')
                labels['comfy'].configure(text='Đang chạy' if comfy and 'system' in comfy and 'devices' in comfy else 'Chưa sẵn sàng')
        window.after(100,drain)
    poll();drain()
    if checking:
        def finish_check():
            destination=Path(sys.argv[sys.argv.index('--self-check')+1]);destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(json.dumps({'ok':True,'root':str(root_path),'tk':window.tk.call('info','patchlevel'),
                'action_buttons':len(buttons),'status_panels':len(labels),
                'scripts_present':all((root_path/'scripts'/s).is_file() for s in ('start_system.ps1','stop_system.ps1','restart_system.ps1'))}),encoding='utf8')
            window.destroy()
        window.after(400,finish_check)
    window.mainloop();return 0


def main():
    if '--panel' in sys.argv or '--self-check' in sys.argv or sys.platform!='win32':
        return panel_main()
    # Sibling module, bundled by PyInstaller; imported lazily so tests can load this file alone.
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from tray_app import tray_main
    return tray_main(sys.argv[1:],sys.modules[__name__])


if __name__=='__main__':sys.exit(main())
