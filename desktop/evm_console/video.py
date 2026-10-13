import os
import subprocess
import threading
import time
from PySide6.QtCore import QThread, Signal
from .core import FrameAssembler,executable

class VideoWorker(QThread):
    state=Signal(str); log=Signal(str)
    def __init__(self):
        super().__init__(); self.lock=threading.Lock(); self.desired=None; self.process=None
        self.stop_event=threading.Event(); self.latest=None; self.sequence=0; self.last_frame=0
        self.frames=0; self.reconnects=0; self.pid=None; self.width=0; self.height=0
    def configure(self,url,width,height,token):
        width=min(1280,width); height=max(2,int(height*width/max(1,token[1]))//2*2)
        value=(url,width,height,token)
        with self.lock:
            changed=self.desired!=value; self.desired=value
            process=self.process
        if changed and process and process.poll() is None: process.terminate()
    def pause(self):
        with self.lock: self.desired=None; process=self.process; self.latest=None
        if process and process.poll() is None: process.terminate()
        self.state.emit('未播放')
    def shutdown(self): self.stop_event.set(); self.pause()
    def take_frame(self):
        with self.lock: value=self.latest; self.latest=None
        return value
    def run(self):
        while not self.stop_event.is_set():
            with self.lock: desired=self.desired
            if not desired: self.stop_event.wait(0.1); continue
            url,width,height,token=desired; process=None
            try:
                self.state.emit('连接视频流…')
                args=[executable('ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin']
                if url.startswith('rtsp://'):
                    args+=['-timeout','5000000','-rtsp_transport','tcp','-fflags','nobuffer','-flags','low_delay','-threads','2']
                else: args+=['-stream_loop','-1','-re','-threads','2']
                args+=['-i',url,'-map','0:v:0','-an','-filter_threads','1',
                      '-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
                      '-pix_fmt','bgr24','-threads','1','-f','rawvideo','pipe:1']
                process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                with self.lock: self.process=process; self.pid=process.pid
                stderr=threading.Thread(target=self.drain_log,args=(process,),daemon=True); stderr.start()
                began=time.monotonic(); self.last_frame=began
                watchdog=threading.Thread(target=self.watchdog,args=(process,desired),daemon=True); watchdog.start()
                assembler=FrameAssembler(width*height*3); first=True
                while not self.stop_event.is_set():
                    with self.lock: current=self.desired
                    if current!=desired: break
                    chunk=process.stdout.read1(65536)
                    if not chunk: break
                    frame=assembler.feed(chunk)
                    if frame:
                        self.last_frame=time.monotonic(); self.frames+=1
                        with self.lock:
                            self.sequence+=1; self.latest=(frame,width,height,self.sequence)
                        if first: self.state.emit('实时画面'); first=False
                if self.desired==desired and not self.stop_event.is_set():
                    self.reconnects+=1; self.state.emit('视频中断，正在重连…')
            except Exception as error:
                self.log.emit(str(error)); self.state.emit('视频连接失败，正在重试…')
            finally:
                if process:
                    if process.poll() is None: process.terminate()
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
                    process.stdout.close(); stderr.join(timeout=1); process.stderr.close()
                with self.lock: self.process=None; self.pid=None
            self.stop_event.wait(0.5)
    def watchdog(self,process,desired):
        while process.poll() is None and not self.stop_event.wait(0.25):
            if self.desired!=desired or time.monotonic()-self.last_frame>4:
                if process.poll() is None: process.terminate()
                return
    def drain_log(self,process):
        try:
            for line in process.stderr:
                text=line.decode('utf-8',errors='replace').strip()
                if text: self.log.emit(text[:1000])
        except (ValueError,OSError): pass
