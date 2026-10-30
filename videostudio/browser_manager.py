"""Explicit lifecycle controls for the single VideoStudio Chrome profile."""
import threading,time
from .chrome_browser import DedicatedChrome

class BrowserManager:
    def __init__(self,launcher=None,active_jobs=None):
        self.launcher=launcher or DedicatedChrome();self.active_jobs=active_jobs or (lambda:0)
        self.lock=threading.Lock();self.last_mode=None
    def _current(self):
        processes=self.launcher.host_state()['processes']
        if len(processes)>1:raise RuntimeError('Có nhiều tiến trình cùng profile; chưa tắt tiến trình nào.')
        return processes[0] if processes else None
    def _idle(self):
        if self.active_jobs():raise ValueError('Đang có video hoặc tác vụ ảnh chạy. Hãy chờ xong hoặc hủy trước khi tắt/đổi chế độ Chrome.')
    def _summary(self,current):
        active=self.active_jobs();mode=current['mode'] if current else 'closed'
        self.last_mode=mode
        return {'running':bool(current),'mode':mode,'debug_ready':bool(mode=='debug' and self.launcher.discover()),'profile':str(self.launcher.config.profile.resolve()),'active_jobs':active,'can_change':active==0,'busy':self.lock.locked()}
    def status(self):return self._summary(self._current())
    def open(self,mode):
        if mode not in ('clean','debug'):raise ValueError('Chọn chế độ sạch hoặc debug.')
        with self.lock:
            current=self._current()
            if not current or current['mode']!=mode:
                self._idle()
                if current:self.launcher.stop_profile(current)
                self.launcher.start_profile(mode)
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    current=self._current()
                    if current and current['mode']==mode and (mode=='clean' or self.launcher.discover()):break
                    time.sleep(.35)
                else:raise RuntimeError('Chrome chưa sẵn sàng. Kiểm tra cửa sổ Chrome riêng rồi thử lại; không mở thêm bản trùng.')
            result=self._summary(current)
        return {**result,'busy':False}
    def stop(self):
        with self.lock:
            self._idle();current=self._current()
            if current:self.launcher.stop_profile(current)
            result=self._summary(None)
        return {**result,'busy':False}

if __name__=='__main__':
    import argparse,json,os,sqlite3,sys
    from pathlib import Path
    from .chrome_browser import ROOT
    sys.stdout.reconfigure(encoding='utf8');sys.stderr.reconfigure(encoding='utf8')
    parser=argparse.ArgumentParser(description='Open/close the fixed VideoStudio Chrome profile without starting the server.')
    parser.add_argument('mode',choices=['clean','debug','stop']);args=parser.parse_args()
    def active_jobs():
        database=Path(os.getenv('VS_DATABASE',str(ROOT/'data/jobs.sqlite3')))
        if not database.exists():return 0
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as connection:
            count=connection.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','retrying')").fetchone()[0]
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scene_image_tasks'").fetchone():
                count+=connection.execute("SELECT COUNT(*) FROM scene_image_tasks WHERE state IN ('queued','running')").fetchone()[0]
            return count
    try:
        manager=BrowserManager(active_jobs=active_jobs)
        result=manager.stop() if args.mode=='stop' else manager.open(args.mode)
        print(json.dumps(result,ensure_ascii=True))
    except Exception as error:
        print(str(error));raise SystemExit(1)
