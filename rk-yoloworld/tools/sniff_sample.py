"""Read-only board-side capture of our outgoing UDP payload, no camera access."""

import json, subprocess
from board_link import ROOT, remote, ADB


def main():
    code = """import socket,time,json,subprocess,struct
from pathlib import Path
route=json.loads(subprocess.check_output(['ip','-j','route','get','192.168.2.165']))[0]
s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3))
s.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024)
s.bind((route['dev'],0));s.settimeout(.5)
path=Path('/userdata/rk-yoloworld-test/detection-sample.ts');n=0;packets=0;start=time.monotonic()
with path.open('wb') as out:
 while time.monotonic()-start<8:
  try:b,addr=s.recvfrom(65536)
  except socket.timeout:continue
  if len(b)<42 or b[12:14]!=b'\\x08\\x00':continue
  ip=b[14:];ihl=(ip[0]&15)*4
  if ip[9]!=17 or ip[16:20]!=socket.inet_aton('192.168.2.165'):continue
  udp=ip[ihl:]
  if len(udp)<8 or struct.unpack('!H',udp[2:4])[0]!=1235:continue
  length=struct.unpack('!H',udp[4:6])[0];payload=udp[8:length]
  if not payload:continue
  out.write(payload);n+=len(payload);packets+=1
elapsed=time.monotonic()-start
stats=s.getsockopt(263,6,8);seen,dropped=struct.unpack('II',stats)
buffer=s.getsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF);s.close()
print(json.dumps({'seconds':elapsed,'bytes':n,'datagrams':packets,'udp_payload_mbps':n*8/elapsed/1e6,'interface':route['dev'],'capture_socket_packets':seen,'capture_socket_drops':dropped,'capture_socket_buffer':buffer}))
"""
    data = json.loads(remote(code, 20))
    (ROOT / "build/network-sample.json").write_text(json.dumps(data, indent=2))
    print(data)
    if not data["bytes"]:
        raise SystemExit("No outgoing test stream packets")
    if data["capture_socket_drops"]:
        raise SystemExit("Capture socket dropped packets; sample is invalid, not encoder evidence")
    subprocess.run(
        [
            str(ADB),
            "pull",
            "/userdata/rk-yoloworld-test/detection-sample.ts",
            str(ROOT / "build/detection-sample.ts"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    main()
