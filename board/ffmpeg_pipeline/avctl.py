#!/usr/bin/env python3
"""JSON camera control over a local Unix socket; CLI is suitable for SSH.

Only this controller's children are stopped. The camera is encoded once;
preview, snapshot and optional MP4 recording all subscribe to RTSP.
"""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
DEFAULTS = {"device": "/dev/video44", "codec": "h265", "width": 1920,
            "height": 1080, "fps": 30, "bitrate": 2500000, "gop": 30}
URL = "rtsp://127.0.0.1:8554/imx415"
MIN_FREE = 1024 ** 3


class ControlError(Exception):
    pass


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ControlError("Configuration must be an object with known fields")
    result = dict(DEFAULTS, **value)
    if not isinstance(result['device'], str) or not re.fullmatch(r'/dev/video[0-9]+', result['device']):
        raise ControlError("Invalid V4L2 device")
    if result['codec'] not in ('h265', 'h264'):
        raise ControlError("codec must be h265 or h264")
    for key, low, high in [('width',96,8192),('height',64,8192),('fps',1,60),('bitrate',100000,20000000),('gop',1,600)]:
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ControlError("Invalid {} (range {}..{})".format(key,low,high))
    if result['width'] % 2 or result['height'] % 2:
        raise ControlError("NV12 width and height must be even")
    return result


def stamp():
    return datetime.datetime.now().astimezone().isoformat()


def run_id():
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def tail(path, lines=40):
    if not path or not Path(path).is_file():
        return []
    with open(path,'rb') as handle:
        handle.seek(0,2)
        handle.seek(max(0,handle.tell()-16000))
        return handle.read().decode('utf-8',errors='replace').splitlines()[-lines:]


def camera_owners(device):
    if shutil.which('fuser'):
        args=['fuser',device]
    elif shutil.which('lsof'):
        args=['lsof','-t',device]
    else:
        raise ControlError('Install lsof or fuser to verify camera ownership')
    result=subprocess.run(args,capture_output=True,text=True)
    if result.returncode not in (0,1):
        raise ControlError('Camera ownership check failed: '+result.stderr[-1000:])
    return sorted(set(result.stdout.split()))


class Controller:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        for folder in ('state','logs','recordings','snapshots'):
            (self.root/folder).mkdir(parents=True,exist_ok=True)
        self.ffmpeg = str(self.root/'runtime/bin/ffmpeg')
        self.ffprobe = str(self.root/'runtime/bin/ffprobe')
        self.environment = dict(os.environ, LD_LIBRARY_PATH=str(self.root/'runtime/lib')+':'+str(self.root/'runtime/lib64'))
        self.lock = threading.RLock()
        self.capture = self.recorder = self.preview = None
        self.capture_log = self.record_log = None
        self.capture_started = self.record_started = None
        self.record_temp = None
        self.progress = {}
        self.last_frame_at = 0.0
        self.last_error = None
        self.want_capture = False
        self.want_preview = False
        self.retry_at = 0.0
        self.retry_times = []
        self.last_recording = None
        previous=self.root/'state/last-recording.json'
        if previous.exists():
            try: self.last_recording=json.loads(previous.read_text())
            except ValueError: pass
        self.closed = False
        self.config = validate_config(json.loads((self.root/'config.json').read_text()) if (self.root/'config.json').exists() else {})

    def active(self, process):
        return process is not None and process.poll() is None

    def check(self):
        encoders = []
        if Path(self.ffmpeg).is_file():
            result = subprocess.run([self.ffmpeg,'-hide_banner','-encoders'],env=self.environment,capture_output=True,text=True,timeout=10)
            encoders = [name for name in ('hevc_rkmpp','h264_rkmpp') if re.search(r'\b'+name+r'\b',result.stdout)]
        return {'ffmpeg':self.ffmpeg,'encoders':encoders,'vpuDevicePresent':Path('/dev/mpp_service').exists(),
                'cameraPresent':Path(self.config['device']).exists(),'config':self.config,
                'runtimeBuilt':Path(self.root/'runtime/build-manifest.json').exists(),
                'freeBytes':shutil.disk_usage(self.root).free}

    def media_path(self):
        try:
            with urllib.request.urlopen('http://127.0.0.1:9997/v3/paths/get/imx415',timeout=0.7) as response:
                return json.load(response)
        except (OSError,ValueError):
            return {}

    def status(self):
        with self.lock:
            media = self.media_path()
            capture_alive = self.active(self.capture)
            recent = self.last_frame_at > time.monotonic()-4
            device_open = False
            if capture_alive:
                for fd in Path('/proc/{}/fd'.format(self.capture.pid)).glob('*'):
                    try:
                        if os.readlink(str(fd)) in ('/dev/mpp_service','/dev/mpp-service','/dev/rkvenc'):
                            device_open = True
                    except OSError:
                        pass
            frame = int(self.progress.get('frame','0') or 0)
            return {'sampledAt':stamp(),'state':'running' if capture_alive and recent and media.get('ready') else ('starting' if capture_alive else ('recovering' if self.want_capture else 'stopped')),
                    'config':self.config,'encoder':'hevc_rkmpp' if self.config['codec']=='h265' else 'h264_rkmpp',
                    'capturePid':self.capture.pid if capture_alive else None,'captureStartedAt':self.capture_started,
                    'frame':frame,'fps':self.progress.get('fps'),'outTimeUs':self.progress.get('out_time_us'),
                    'duplicateFrames':self.progress.get('dup_frames'),'droppedFrames':self.progress.get('drop_frames'),
                    'lastFrameAgeSeconds':round(time.monotonic()-self.last_frame_at,3) if self.last_frame_at else None,
                    'vpuDeviceOpen':device_open,'rtspReady':bool(media.get('ready')),'rtspPath':'/imx415','rtspPort':8554,
                    'readers':len(media.get('readers',[])),'previewRunning':self.active(self.preview),
                    'recording':self.active(self.recorder),'recordingStartedAt':self.record_started,
                    'recordingFile':str(self.record_temp) if self.record_temp else None,
                    'lastRecording':self.last_recording,'freeBytes':shutil.disk_usage(self.root).free,
                    'lastError':self.last_error}

    def read_progress(self, process):
        block = {}
        try:
            for line in process.stdout:
                key, separator, value = line.strip().partition('=')
                if separator:
                    block[key] = value
                if key == 'progress':
                    with self.lock:
                        if process is self.capture:
                            if int(block.get('frame','0') or 0) > int(self.progress.get('frame','0') or 0):
                                self.last_frame_at = time.monotonic()
                            self.progress = dict(block)
                    block = {}
        finally:
            process.stdout.close()

    def spawn_logged(self, arguments, log_path, progress=False, private=True):
        with open(log_path,'ab',buffering=0) as output:
            return subprocess.Popen(arguments,env=self.environment if private else os.environ,
                                    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE if progress else subprocess.DEVNULL,
                                    stderr=output,text=progress,bufsize=1 if progress else -1,start_new_session=True)

    def begin_capture(self):
        device = self.config['device']
        owners = camera_owners(device)
        if owners:
            raise ControlError('Camera busy; owner PID(s): '+' '.join(owners))
        c = self.config
        encoder = 'hevc_rkmpp' if c['codec']=='h265' else 'h264_rkmpp'
        if encoder not in self.check()['encoders']:
            raise ControlError('Required hardware encoder unavailable: '+encoder)
        self.capture_log = self.root/'logs'/('capture-'+run_id()+'.log')
        args = [self.ffmpeg,'-hide_banner','-nostdin','-nostats','-loglevel','info','-stats_period','1','-progress','pipe:1',
                '-f','v4l2','-input_format','nv12','-video_size','{}x{}'.format(c['width'],c['height']),
                '-framerate',str(c['fps']),'-i',device,'-map','0:v:0','-an','-c:v',encoder,'-rc_mode','CBR',
                '-b:v',str(c['bitrate']),'-maxrate',str(c['bitrate']),'-minrate',str(c['bitrate']),
                '-g',str(c['gop']),'-bf','0','-r',str(c['fps']),'-f','rtsp','-rtsp_transport','tcp',URL]
        self.progress = {}; self.last_frame_at = 0.0
        self.capture = self.spawn_logged(args,self.capture_log,progress=True)
        self.capture_started = stamp()
        threading.Thread(target=self.read_progress,args=(self.capture,),daemon=True).start()

    def stop_child(self, process, timeout=15):
        if self.active(process):
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
                return False
        return True

    def start(self, config=None):
        with self.lock:
            requested = validate_config(config if config is not None else self.config)
            if self.recorder is not None:
                raise ControlError('Stop and finalize recording before changing the stream')
            if self.active(self.capture) and requested == self.config:
                return self.status()
            self.want_capture = False
            self.stop_child(self.capture)
            self.stop_child(self.preview,3); self.preview=None
            self.capture = None
            self.config = requested
            atomic_json(self.root/'config.json',self.config)
            self.retry_times = []
            self.begin_capture()
            self.want_capture = True
            self.last_error = None
        deadline=time.monotonic()+10
        while time.monotonic() < deadline:
            state=self.status()
            if state['state']=='running': return state
            if not self.active(self.capture): break
            time.sleep(0.1)
        with self.lock:
            self.want_capture=False
            self.stop_child(self.capture)
            self.capture=None
            self.last_error={'at':stamp(),'message':'Encoder did not produce a ready stream','log':tail(self.capture_log,15)}
        raise ControlError(json.dumps(self.last_error))

    def record_start(self):
        with self.lock:
            if self.recorder is not None:
                raise ControlError('A recording is already open')
            if self.status()['state']!='running':
                raise ControlError('Start a ready live stream before recording')
            if shutil.disk_usage(self.root).free < MIN_FREE:
                raise ControlError('Less than 1 GiB free; recording refused')
            name='imx415-'+run_id()
            self.record_temp=self.root/'recordings'/(name+'.partial.mp4')
            self.record_log=self.root/'logs'/(name+'.log')
            args=[self.ffmpeg,'-hide_banner','-nostdin','-loglevel','info','-rtsp_transport','tcp','-i',URL,
                  '-map','0:v:0','-an','-c:v','copy','-movflags','+faststart','-n']
            if self.config['codec']=='h265': args += ['-tag:v','hvc1']
            args += [str(self.record_temp)]
            self.recorder=self.spawn_logged(args,self.record_log)
            self.record_started=stamp()
        time.sleep(0.3)
        if not self.active(self.recorder):
            self.record_stop()
            raise ControlError('Recording failed to start: '+str(tail(self.record_log,12)))
        return self.status()

    def record_stop(self):
        with self.lock:
            if self.recorder is None:
                return {'recording':False,'lastRecording':self.last_recording}
            normal=self.stop_child(self.recorder)
            temporary=self.record_temp
            self.recorder=None; self.record_started=None; self.record_temp=None
            info=None
            if normal and temporary and temporary.exists():
                probe=subprocess.run([self.ffprobe,'-v','error','-show_entries','stream=codec_name,width,height,nb_frames:format=duration',
                                      '-of','json',str(temporary)],env=self.environment,capture_output=True,text=True,timeout=10)
                if probe.returncode==0:
                    info=json.loads(probe.stdout)
            if not info or not info.get('streams') or float(info.get('format',{}).get('duration','0'))<=0:
                self.last_error={'at':stamp(),'message':'Recording did not finalize; partial file retained','file':str(temporary),'log':tail(self.record_log,12)}
                return {'recording':False,'error':self.last_error}
            final=temporary.with_name(temporary.name.replace('.partial.mp4','.mp4'))
            temporary.rename(final)
            self.last_recording={'file':str(final),'bytes':final.stat().st_size,'finishedAt':stamp(),'probe':info}
            atomic_json(self.root/'state/last-recording.json',self.last_recording)
            return {'recording':False,'lastRecording':self.last_recording}

    def preview_start(self):
        with self.lock:
            if self.active(self.preview): return self.status()
            if self.status()['state']!='running': raise ControlError('Stream is not ready')
            display=':0'
            auth=next(iter(sorted(Path('/run/user').glob('*/gdm/Xauthority'))),None)
            env=dict(os.environ,DISPLAY=display)
            if auth: env['XAUTHORITY']=str(auth)
            with open(self.root/'logs/preview.log','ab',buffering=0) as log:
                self.preview=subprocess.Popen(['/usr/bin/ffplay','-hide_banner','-loglevel','warning','-rtsp_transport','tcp',
                                               '-fflags','nobuffer','-flags','low_delay','-framedrop',URL],env=env,
                                              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log,start_new_session=True)
        time.sleep(0.5)
        if not self.active(self.preview): raise ControlError('HDMI preview failed: '+str(tail(self.root/'logs/preview.log',10)))
        self.want_preview=True
        return self.status()

    def preview_stop(self):
        with self.lock:
            self.want_preview=False
            self.stop_child(self.preview,5); self.preview=None
            return {'previewRunning':False}

    def snapshot(self):
        if self.status()['state']!='running': raise ControlError('Stream is not ready')
        output=self.root/'snapshots'/('imx415-'+run_id()+'.jpg')
        result=subprocess.run([self.ffmpeg,'-hide_banner','-loglevel','error','-rtsp_transport','tcp','-i',URL,
                               '-map','0:v:0','-frames:v','1','-c:v','mjpeg','-q:v','2','-update','1','-n',str(output)],env=self.environment,
                              capture_output=True,text=True,timeout=10)
        if result.returncode or not output.exists(): raise ControlError('Snapshot failed: '+result.stderr[-2000:])
        return {'file':str(output),'bytes':output.stat().st_size,'createdAt':stamp()}

    def stop(self):
        with self.lock:
            self.want_capture=False
            record_result=self.record_stop()
            self.preview_stop()
            self.stop_child(self.capture); self.capture=None
            self.progress={}; self.last_frame_at=0.0
            return {'state':'stopped','recordingResult':record_result}

    def monitor(self):
        while not self.closed:
            time.sleep(1)
            with self.lock:
                try:
                    if self.recorder is not None and (not self.active(self.recorder) or shutil.disk_usage(self.root).free<MIN_FREE):
                        reason='Recorder exited or disk free space reached 1 GiB limit'
                        self.record_stop(); self.last_error={'at':stamp(),'message':reason}
                    if self.want_capture and not self.active(self.capture):
                        if self.recorder is not None: self.record_stop()
                        if self.capture is not None:
                            self.last_error={'at':stamp(),'message':'Encoder exited; retrying','log':tail(self.capture_log,10)}
                            self.capture=None; self.retry_at=time.monotonic()+1
                            self.stop_child(self.preview,3); self.preview=None
                        now=time.monotonic()
                        if now >= self.retry_at:
                            self.retry_times=[t for t in self.retry_times if t>now-60]
                            if len(self.retry_times)>=5:
                                self.want_capture=False
                                self.last_error={'at':stamp(),'message':'Five restart failures within 60 seconds; stopped'}
                            else:
                                self.retry_times.append(now)
                                self.begin_capture(); self.retry_at=now+2
                    if self.want_preview and not self.active(self.preview) and self.status()['state']=='running':
                        self.preview_start()
                    atomic_json(self.root/'state/status.json',self.status())
                except Exception as error:
                    self.last_error={'at':stamp(),'message':str(error)}

    def execute(self, action, payload):
        if action=='start': return self.start(payload.get('config'))
        methods={'check':self.check,'status':self.status,'stop':self.stop,'record-start':self.record_start,
                 'record-stop':self.record_stop,'preview-start':self.preview_start,'preview-stop':self.preview_stop,'snapshot':self.snapshot}
        if action=='logs':
            lines=payload.get('lines',40)
            if type(lines) is not int or not 1<=lines<=500: raise ControlError('lines must be 1..500')
            return {'capture':tail(self.capture_log,lines),'recording':tail(self.record_log,lines),'preview':tail(self.root/'logs/preview.log',lines)}
        if action not in methods: raise ControlError('Unknown action')
        return methods[action]()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request=json.loads(self.rfile.readline(16385))
            if not isinstance(request,dict): raise ControlError('Request must be an object')
            result=self.server.controller.execute(request.get('action'),request.get('payload',{}))
            response={'ok':not (isinstance(result,dict) and 'error' in result),'result':result}
            if not response['ok']: response['error']=result['error']
        except Exception as error:
            response={'ok':False,'error':str(error)}
        self.wfile.write((json.dumps(response,ensure_ascii=False)+'\n').encode('utf-8'))


def serve():
    state=ROOT/'state'; state.mkdir(exist_ok=True)
    lockfile=open(state/'controller.lock','w')
    fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
    endpoint=state/'control.sock'
    if endpoint.exists(): endpoint.unlink()
    controller=Controller()
    server=socketserver.ThreadingUnixStreamServer(str(endpoint),Handler)
    server.daemon_threads=True; server.controller=controller
    os.chmod(endpoint,0o600)
    threading.Thread(target=controller.monitor,daemon=True).start()
    def stop_signal(signum,frame):
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGINT,stop_signal); signal.signal(signal.SIGTERM,stop_signal)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        controller.closed=True; controller.stop(); server.server_close()
        if endpoint.exists(): endpoint.unlink()


def request(action,payload):
    endpoint=ROOT/'state/control.sock'
    if action in ('start','preview-start'):
        result=subprocess.run(['systemctl','start','evm-mediamtx.service','evm-ffmpeg-control.service'],capture_output=True,text=True,timeout=20)
        if result.returncode: raise ControlError('Install services first: '+result.stderr.strip())
        deadline=time.monotonic()+5
        while not endpoint.exists() and time.monotonic()<deadline: time.sleep(0.05)
    if not endpoint.exists():
        if action=='check': return {'ok':True,'result':Controller().check()}
        if action in ('status','stop','record-stop','preview-stop'): return {'ok':True,'result':{'state':'stopped','recording':False}}
        raise ControlError('Controller is not running')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(35); client.connect(str(endpoint))
        client.sendall((json.dumps({'action':action,'payload':payload})+'\n').encode('utf-8'))
        with client.makefile('rb') as reader: return json.loads(reader.readline())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','start','stop','status','record-start','record-stop','preview-start','preview-stop','snapshot','logs','_serve'])
    parser.add_argument('--config-stdin',action='store_true',help='Read configuration JSON from stdin; start only')
    parser.add_argument('--lines',type=int,default=40)
    args=parser.parse_args()
    if args.action=='_serve': serve(); return 0
    try:
        payload={'lines':args.lines} if args.action=='logs' else {}
        if args.config_stdin:
            if args.action!='start': raise ControlError('--config-stdin is only supported for start')
            payload['config']=validate_config(json.load(sys.stdin))
        response=request(args.action,payload)
    except Exception as error:
        response={'ok':False,'error':str(error)}
    print(json.dumps(response,ensure_ascii=False))
    return 0 if response['ok'] else 1


if __name__=='__main__':
    sys.exit(main())
