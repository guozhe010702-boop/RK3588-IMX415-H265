"""Validate Markdown links, command syntax and the single project web page."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote
import re,subprocess,tempfile

ROOT=Path(__file__).resolve().parents[2]
documents=[ROOT/'README.md']
for folder in ('board','desktop','docs','examples','tools','reference','releases'):
    documents.extend(p for p in (ROOT/folder).rglob('*.md')
                     if not any(part in {'vendor','build','dist','rockchip_sdk','desktop-build'} for part in p.relative_to(ROOT).parts))
blocks=[]
for document in documents:
    text=document.read_text(encoding='utf-8-sig')
    blocks.extend(re.findall(r'```(bash|powershell)\n(.*?)```',text,re.S))
    for target in re.findall(r'\]\(([^)]+)\)',text):
        if '://' not in target and not target.startswith('#'):
            assert (document.parent/unquote(target.split('#',1)[0])).exists(),f'{document}: {target}'
with tempfile.TemporaryDirectory(prefix='av_guide_check_') as folder:
    for i,(language,code) in enumerate(blocks):
        file=Path(folder)/(str(i)+('.sh' if language=='bash' else '.ps1'))
        file.write_text(code,encoding='utf-8-sig' if language=='powershell' else 'utf-8')
        if language=='bash':
            command=[r'C:\Program Files\Git\bin\bash.exe','--noprofile','--norc','-n',str(file)]
        else:
            expression="$e=$null;$t=$null;[System.Management.Automation.Language.Parser]::ParseFile('"+str(file).replace("'","''")+"',[ref]$t,[ref]$e)|Out-Null;if($e.Count){$e|ForEach-Object{$_.Message};exit 1}"
            command=['powershell.exe','-NoProfile','-Command',expression]
        result=subprocess.run(command,capture_output=True)
        if result.returncode: raise ValueError(f'{language} block {i+1}: '+(result.stdout+result.stderr).decode(errors='replace'))
class Links(HTMLParser):
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key not in ('href','src') or not value or value.startswith(('#','data:')) or '://' in value: continue
            path=(ROOT/'web'/unquote(value.split('#',1)[0])).resolve()
            # SDK and released artifacts remain local; source ZIP need not contain them.
            if any(part in {'releases','reference'} for part in path.parts): continue
            assert path.exists(),f'web/index.html: {value}'
Links().feed((ROOT/'web/index.html').read_text(encoding='utf-8'))
assert list(ROOT.glob('*.html'))==[]
assert list((ROOT/'docs').rglob('*.html'))==[]
print(f'OK: {len(documents)} Markdown files, {len(blocks)} command blocks, one web page')
