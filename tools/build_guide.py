"""Render the canonical Markdown guide as a standalone local HTML page.

Build dependency: markdown-it-py (already available in this workspace).
"""
from html import escape
from pathlib import Path
from markdown_it import MarkdownIt
from urllib.parse import unquote
import sys

ROOT = Path(__file__).resolve().parents[1]
sources = [Path(sys.argv[1]).resolve()] if len(sys.argv)>1 else sorted((ROOT / "docs").glob("*.md"))
parser = MarkdownIt("commonmark", {"html": False}).enable("table")
page = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>路线二 · MPP C API 操作与修改指南</title>
<style>
:root{color-scheme:light;--ink:#183246;--sub:#50677a;--line:#d9e4eb;--blue:#086d95}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif;color:var(--ink);background:#f2f6f9}
header{background:#15364a;color:white;padding:28px max(24px,calc((100vw - 1320px)/2));}header a{color:#a7e5ff}header p{margin:8px 0 0;font-size:14px}
.layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:28px;max-width:1320px;margin:28px auto;padding:0 24px}
nav{align-self:start;position:sticky;top:20px;background:white;border:1px solid var(--line);border-radius:12px;padding:20px}nav strong{display:block;margin-bottom:10px}nav a{display:block;font-size:14px;margin:10px 0;line-height:1.6}
main{min-width:0;background:white;border:1px solid var(--line);border-radius:12px;padding:32px 40px}h1{font-size:28px;line-height:1.4;margin-top:0}h2{font-size:23px;border-top:1px solid var(--line);padding-top:28px;margin-top:40px;scroll-margin-top:18px}h3{font-size:19px;scroll-margin-top:18px}p{margin:12px 0}a{color:var(--blue)}code{font:14px/1.6 Consolas,monospace;background:#eef4f7;border-radius:4px;padding:2px 5px;overflow-wrap:anywhere}pre{padding:18px 20px;border-radius:9px;background:#15364a;color:#e8f6ff;overflow-x:auto;line-height:1.65;white-space:pre}pre code{background:transparent;padding:0;color:inherit;overflow-wrap:normal}table{display:block;overflow-x:auto;width:100%;border-collapse:collapse;margin:18px 0;font-size:14px}th,td{border:1px solid var(--line);padding:10px 12px;vertical-align:top;min-width:110px}th{background:#edf5f8}li{margin:6px 0}strong{color:#0d5270}
@media(max-width:900px){.layout{display:block;margin:16px auto;padding:0 14px}nav{position:static;margin-bottom:16px}main{padding:22px 18px}h1{font-size:24px}}@media print{header,nav{display:none}.layout{display:block;max-width:none;padding:0;margin:0}main{border:0;padding:0}pre{white-space:pre-wrap;background:#eee;color:black}h2{break-after:avoid}table{display:table}a{color:inherit}}
img{max-width:100%;height:auto}
</style></head><body><header><a href="../EVM3588-B_音视频实时压缩方案.html">← 返回方案网页</a><p>IMX415 · con7 · H.265 · 每条命令均标明电脑或板端，并解释作用。源码以项目根目录 board/ 为准。</p></header>
<div class="layout"><nav><strong>操作与学习目录</strong>TOC</nav><main>ARTICLE</main></div></body></html>'''
def generate(source):
    tokens=parser.parse(source.read_text(encoding='utf-8'))
    # Markdown remains the source. Local HTML pages navigate to generated guides.
    for token in tokens:
        for child in token.children or []:
            if child.type != 'link_open': continue
            href=child.attrGet('href') or ''
            path,separator,fragment=href.partition('#')
            if '://' in path or not path.endswith('.md'): continue
            target=(source.parent/unquote(path)).resolve()
            if target.parent == ROOT/'docs' and target.is_file():
                child.attrSet('href',path[:-3]+'.html'+(separator+fragment if separator else ''))
    toc=[]; headings=0; title='EVM3588 操作指南'
    for index,token in enumerate(tokens):
        if token.type=='heading_open':
            headings+=1; anchor='section-'+str(headings); token.attrSet('id',anchor)
            if token.tag=='h1': title=tokens[index+1].content
            if token.tag=='h2': toc.append((anchor,tokens[index+1].content))
    article=parser.renderer.render(tokens,parser.options,{})
    links=''.join(f'<a href="#{anchor}">{escape(text)}</a>' for anchor,text in toc)
    content=page.replace('路线二 · MPP C API 操作与修改指南',escape(title)).replace('TOC',links).replace('ARTICLE',article)
    content=content.replace('IMX415 · con7 · H.265 · 每条命令均标明电脑或板端，并解释作用。源码以项目根目录 board/ 为准。','EVM3588-B · IMX415/con7 · FFmpeg / MPP · 操作与设计文档')
    source.with_suffix('.html').write_text(content,encoding='utf-8')
for source in sources: generate(source)
print(f'Generated {len(sources)} standalone HTML guides')
