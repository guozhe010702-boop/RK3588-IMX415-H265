import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evm_console.ssh import invoke

class Channel:
    def __init__(self,response): self.output=bytearray(json.dumps(response).encode()); self.closed=False; self.command=None; self.sent=None
    def exec_command(self,command): self.command=command
    def sendall(self,value): self.sent=value
    def shutdown_write(self): pass
    def recv_ready(self): return bool(self.output)
    def recv(self,size): value=bytes(self.output[:9]); del self.output[:9]; return value
    def recv_stderr_ready(self): return False
    def exit_status_ready(self): return not self.output
    def close(self): self.closed=True
class Client:
    def __init__(self,channel): self.channel=channel
    def get_transport(self): return self
    def open_session(self,timeout): return self.channel

def test_config_is_json_stdin_not_shell_interpolation():
    channel=Channel({'ok':True,'result':{'state':'running'}})
    value={'device':'/dev/video44; echo unsafe'}
    assert invoke(Client(channel),'start',value)['ok']
    assert channel.command=='python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py start --config-stdin'
    assert json.loads(channel.sent)==value
    assert channel.closed

def test_remote_failure_is_reported_without_repeating_action():
    channel=Channel({'ok':False,'error':'Camera busy','result':{'recovery':{'restored':True}}})
    result=invoke(Client(channel),'start')
    assert not result['ok'] and result['result']['recovery']['restored']
    assert channel.closed
