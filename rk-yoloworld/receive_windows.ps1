param([int]$Port = 1235, [string]$Ffplay = 'ffplay.exe')
$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be 1..65535' }
& $Ffplay -hide_banner -loglevel warning -fflags nobuffer -flags low_delay -framedrop -sync ext -window_title 'YOLO-World 实时检测' "udp://0.0.0.0:${Port}?fifo_size=8192&overrun_nonfatal=1"
if ($LASTEXITCODE -ne 0) { throw "ffplay exited: $LASTEXITCODE" }
