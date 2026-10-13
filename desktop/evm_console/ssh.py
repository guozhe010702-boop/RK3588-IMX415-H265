import base64
import hashlib
import json
import queue
import threading
import time
import paramiko
from PySide6.QtCore import QThread, Signal
from .core import REMOTE_ROOT,ACTIONS,data_root,parse_response

class UnknownHost(paramiko.SSHException):
    def __init__(self,host,key): self.host=host; self.key=key; super().__init__('首次连接需要确认 SSH 主机指纹')
    def details(self):
        return {'host':self.host,'type':self.key.get_name(),'key':self.key.get_base64(),
                'fingerprint':'SHA256:'+base64.b64encode(hashlib.sha256(self.key.asbytes()).digest()).decode().rstrip('=')}

class VerifyHost(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self,client,hostname,key): raise UnknownHost(hostname,key)

def connect_ssh(connection,password):
    client=paramiko.SSHClient(); known=data_root()/'known_hosts'
    if known.exists(): client.load_host_keys(str(known))
    client.set_missing_host_key_policy(VerifyHost())
    try:
        client.connect(connection.host,port=connection.port,username=connection.username,
                       password=password if connection.auth=='password' else None,
                       key_filename=connection.key_file if connection.auth=='key' else None,
                       passphrase=password if connection.auth=='key' and password else None,
                       timeout=8,banner_timeout=10,auth_timeout=10,allow_agent=False,look_for_keys=False)
        client.get_transport().set_keepalive(10)
        return client
    except Exception:
        client.close(); raise

def trust_host(details):
    file=data_root()/'known_hosts'; keys=paramiko.HostKeys()
    if file.exists(): keys.load(str(file))
    if details['host'] in keys: raise ValueError('已有主机指纹，不允许覆盖；请先核对板子身份')
    key=paramiko.PKey.from_type_string(details['type'],base64.b64decode(details['key']))
    keys.add(details['host'],details['type'],key); keys.save(str(file))

def invoke(client,action,config=None):
    if action not in ACTIONS: raise ValueError('Unknown action')
    command=f'python3 {REMOTE_ROOT}/avctl.py {action}'
    if config is not None:
        if action!='start': raise ValueError('Configuration only supports start')
        command+=' --config-stdin'
    timeout=80 if action in ('start','stop') else 40
    channel=client.get_transport().open_session(timeout=8)
    try:
        channel.exec_command(command)
        if config is not None: channel.sendall((json.dumps(config)+'\n').encode())
        channel.shutdown_write(); output=bytearray(); errors=bytearray(); deadline=time.monotonic()+timeout
        while True:
            if channel.recv_ready(): output.extend(channel.recv(65536))
            if channel.recv_stderr_ready(): errors.extend(channel.recv_stderr(65536))
            if len(output)>2*1024*1024 or len(errors)>256*1024: raise ValueError('板端输出超过限制')
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready(): break
            if time.monotonic()>deadline: raise TimeoutError('操作超时；远端可能仍在执行，请查询状态，不要重复点击')
            time.sleep(0.01)
        return parse_response(output.decode('utf-8'))
    finally: channel.close()

class SSHWorker(QThread):
    connected=Signal(bool,str); status=Signal(dict); result=Signal(str,dict); failure=Signal(str,str)
    host_key=Signal(dict); busy=Signal(bool)
    def __init__(self):
        super().__init__(); self.jobs=queue.Queue(); self.stop_event=threading.Event(); self.client=None
        self.connection=None; self.password=''; self.want_connection=False
    def submit(self,action,payload=None): self.jobs.put((action,payload))
    def shutdown(self):
        self.stop_event.set()
        if self.client: self.client.close()
    def run(self):
        next_poll=0; retry=0; delay=1
        while not self.stop_event.is_set():
            try: action,payload=self.jobs.get(timeout=0.05)
            except queue.Empty: action=None; payload=None
            if action=='connect':
                if self.client: self.client.close()
                self.client=None; self.connection,self.password=payload; self.want_connection=True; retry=0; delay=1
            elif action=='disconnect':
                self.want_connection=False; self.password=''
                if self.client: self.client.close()
                self.client=None; self.connected.emit(False,'已断开控制连接'); continue
            if self.want_connection and self.client is None and time.monotonic()>=retry:
                self.busy.emit(True)
                try:
                    self.client=connect_ssh(self.connection,self.password)
                    self.connected.emit(True,'SSH 已连接'); delay=1
                    check=invoke(self.client,'check'); self.result.emit('check',check)
                    self.status.emit(invoke(self.client,'status')['result']); next_poll=time.monotonic()+1
                except UnknownHost as error:
                    self.want_connection=False; self.host_key.emit(error.details())
                except (paramiko.AuthenticationException,paramiko.BadHostKeyException) as error:
                    self.want_connection=False; self.failure.emit('connect',str(error)); self.connected.emit(False,'SSH 认证或主机指纹校验失败')
                    if self.client: self.client.close()
                    self.client=None
                except Exception as error:
                    if self.client: self.client.close()
                    self.client=None; self.connected.emit(False,'连接中断，正在重连'); self.failure.emit('connect',str(error))
                    retry=time.monotonic()+delay; delay=min(8,delay*2)
                finally: self.busy.emit(False)
                if self.client is None: continue
            if action in ACTIONS:
                if self.client is None:
                    self.failure.emit(action,'SSH 尚未连接'); continue
                self.busy.emit(True)
                try:
                    response=invoke(self.client,action,payload); self.result.emit(action,response)
                    # A timed-out or failed mutation is never re-issued.
                    self.status.emit(invoke(self.client,'status')['result']); next_poll=time.monotonic()+1
                except Exception as error:
                    self.failure.emit(action,str(error)); self.client.close(); self.client=None
                    self.connected.emit(False,'控制连接中断，正在查询恢复后的状态'); retry=time.monotonic()+1
                finally: self.busy.emit(False)
            elif self.client and time.monotonic()>=next_poll:
                try: self.status.emit(invoke(self.client,'status')['result'])
                except Exception as error:
                    self.failure.emit('status',str(error)); self.client.close(); self.client=None
                    self.connected.emit(False,'状态连接中断，正在重连'); retry=time.monotonic()+1
                next_poll=time.monotonic()+1
        if self.client: self.client.close()
        self.password=''
