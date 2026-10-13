import os
from pathlib import Path,PurePosixPath
import queue
import stat
import threading
from PySide6.QtCore import QThread,Signal
from .core import REMOTE_ROOT
from .ssh import connect_ssh

def checked_remote(sftp,path):
    pure=PurePosixPath(path)
    if pure.parent.as_posix() not in (REMOTE_ROOT+'/recordings',REMOTE_ROOT+'/snapshots'):
        raise ValueError('文件必须位于板端录像或截图目录')
    if pure.suffix.lower() not in ('.mp4','.jpg') or pure.name.endswith('.partial.mp4'):
        raise ValueError('只下载已完成的 MP4 或 JPEG')
    actual=sftp.normalize(str(pure))
    if actual!=str(pure): raise ValueError('拒绝下载目录外的链接文件')
    info=sftp.lstat(actual)
    if not stat.S_ISREG(info.st_mode): raise ValueError('下载对象不是普通文件')
    return actual,info

def copy_remote(sftp,remote,directory,cancel,progress):
    remote,info=checked_remote(sftp,remote); folder=Path(directory); folder.mkdir(parents=True,exist_ok=True)
    final=folder/PurePosixPath(remote).name
    if final.exists():
        if final.stat().st_size==info.st_size: return str(final)
        raise ValueError('本地已有同名且大小不同的文件，请更换下载目录')
    partial=final.with_name(final.name+'.part'); done=0
    try:
        with sftp.open(remote,'rb') as source,partial.open('wb') as output:
            source.prefetch(info.st_size,max_concurrent_requests=16)
            while True:
                if cancel.is_set(): raise InterruptedError('下载已取消，临时文件已清理')
                chunk=source.read(256*1024)
                if not chunk: break
                output.write(chunk); done+=len(chunk); progress(done,info.st_size)
        if done!=info.st_size or sftp.stat(remote).st_size!=info.st_size: raise ValueError('文件长度发生变化或下载不完整，请重新下载')
        partial.replace(final); return str(final)
    except Exception:
        partial.unlink(missing_ok=True); raise

class FileWorker(QThread):
    listing=Signal(list); progress=Signal(str,object,object); completed=Signal(str,str)
    failure=Signal(str); busy=Signal(bool)
    def __init__(self):
        super().__init__(); self.jobs=queue.Queue(); self.stop_event=threading.Event(); self.cancel=threading.Event()
        self.connection=None; self.password=''; self.client=None
    def configure(self,connection,password): self.connection=connection; self.password=password
    def submit(self,action,payload=None): self.jobs.put((action,payload))
    def shutdown(self):
        self.stop_event.set(); self.cancel.set()
        if self.client: self.client.close()
    def run(self):
        while not self.stop_event.is_set():
            try: action,payload=self.jobs.get(timeout=0.1)
            except queue.Empty: continue
            self.busy.emit(True); self.cancel.clear(); sftp=None
            try:
                if not self.connection: raise ValueError('请先连接开发板')
                self.client=connect_ssh(self.connection,self.password); sftp=self.client.open_sftp(); sftp.get_channel().settimeout(10)
                if action=='list':
                    rows=[]
                    for folder in ('recordings','snapshots'):
                        for info in sftp.listdir_attr(REMOTE_ROOT+'/'+folder):
                            if stat.S_ISREG(info.st_mode) and info.filename.endswith(('.mp4','.jpg')):
                                rows.append({'path':REMOTE_ROOT+'/'+folder+'/'+info.filename,'name':info.filename,'bytes':info.st_size,
                                             'modified':info.st_mtime,'complete':not info.filename.endswith('.partial.mp4')})
                    self.listing.emit(sorted(rows,key=lambda row:row['modified'],reverse=True))
                elif action=='download':
                    remote,folder=payload
                    local=copy_remote(sftp,remote,folder,self.cancel,lambda done,total:self.progress.emit(remote,done,total))
                    self.completed.emit(remote,local)
            except Exception as error:
                if not self.stop_event.is_set(): self.failure.emit(str(error))
            finally:
                if sftp: sftp.close()
                if self.client: self.client.close()
                self.client=None; self.busy.emit(False)
        self.password=''
