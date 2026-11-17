"""Read-only 创作指引：从 assets/guides 提供操作文档与配图。复刻飞书文档阅读器样式与页面逻辑。"""
import datetime
import html as html_mod
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".avif": "image/avif",
}


def guides_root(root=None):
    from vsc.configuration import get_config
    base = Path(get_config("VSC_MEDIA_ROOT")).parent / "guides" if get_config("VSC_MEDIA_ROOT") else None
    if base and base.is_dir():
        return base
    return Path(__file__).resolve().parents[4] / "assets" / "guides"


# ─────────────────────────────────────────────────────────────────────
# Markdown → HTML（支持 h1/h2/h3、表格、有序/无序列表、嵌套列表、Callout、粗体、行内代码、链接）
# ─────────────────────────────────────────────────────────────────────

def _inline(s):
    s = html_mod.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


def _md_to_html(md: str) -> str:
    lines = md.split("\n")
    out = []
    list_stack = []  # 栈：追踪嵌套列表
    in_table = False

    def close_lists():
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    def open_list(tag):
        if list_stack and list_stack[-1] == tag:
            return
        if list_stack and list_stack[-1] != tag:
            out.append(f"</{list_stack.pop()}>")
        out.append(f"<{tag}>")
        list_stack.append(tag)

    i = 0
    while i < len(lines):
        line = lines[i]

        # 标题
        if line.startswith("### "):
            close_lists()
            if in_table: out.append("</tbody></table>"); in_table = False
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            close_lists()
            if in_table: out.append("</tbody></table>"); in_table = False
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            close_lists()
            if in_table: out.append("</tbody></table>"); in_table = False
            out.append(f"<h1>{_inline(line[2:])}</h1>")

        # Callout（> 开头的引用块）
        elif line.startswith(">"):
            close_lists()
            if in_table: out.append("</tbody></table>"); in_table = False
            # 收集连续 > 行
            quote_lines = [line.lstrip("> ")]
            while i + 1 < len(lines) and lines[i + 1].startswith(">"):
                i += 1
                quote_lines.append(lines[i].lstrip("> "))
            text = "<br>".join(_inline(q) for q in quote_lines if q.strip())
            out.append(f'<div class="callout">{text}</div>')

        # 表格
        elif line.startswith("|"):
            close_lists()
            if i + 1 < len(lines) and re.match(r"^\|[\s:-]+\|", lines[i + 1]):
                if not in_table:
                    out.append("<div class=\"table-wrap\"><table>")
                    in_table = True
                cells = [c.strip() for c in line.split("|")[1:-1]]
                out.append("<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr></thead><tbody>")
                i += 1
            elif in_table:
                cells = [c.strip() for c in line.split("|")[1:-1]]
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            if in_table and (i + 1 >= len(lines) or not lines[i + 1].startswith("|")):
                out.append("</tbody></table></div>")
                in_table = False

        # 嵌套列表（通过缩进判断层级）
        else:
            if in_table: out.append("</tbody></table></div>"); in_table = False

            # 计算缩进层级
            indent = len(line) - len(line.lstrip())
            level = indent // 2  # 每两空格一级

            stripped = line.strip()
            if stripped.startswith("- "):
                close_lists()
                open_list("ul")
                out.append(f"<li>{_inline(stripped[2:])}</li>")
            elif re.match(r"^\d+\.\s", stripped):
                close_lists()
                open_list("ol")
                out.append(f"<li>{_inline(re.sub(r'^\d+\.\s', '', stripped))}</li>")
            elif stripped == "":
                close_lists()
            else:
                close_lists()
                out.append(f"<p>{_inline(stripped)}</p>")
        i += 1

    close_lists()
    if in_table:
        out.append("</tbody></table></div>")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────
# CSS（复刻飞书文档阅读器）
# ─────────────────────────────────────────────────────────────────────

PAGE_CSS = """
:root{
  --bg:#FFFFFF;--fg:#1F2329;--muted:#8F959E;--hover:#F2F3F5;
  --brand:#3370FF;--brand-bg:#EBF1FF;--border:#DEE0E3;
  --callout-bg:#FFF7E6;--callout-border:#FFD591;
  --code-bg:#F5F6F7;--code-fg:#3B5998;
  --toc-w:280px;--doc-w:800px;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:80px}
body{background:var(--bg);color:var(--fg);font:15px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Helvetica Neue",sans-serif}

/* ── 顶栏 ── */
.topbar{position:fixed;top:0;left:0;right:0;height:56px;background:#FFF;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:12px;z-index:20}
.topbar .logo{font-size:15px;font-weight:600;color:var(--fg);text-decoration:none;display:flex;align-items:center;gap:8px;flex-shrink:0}
.topbar .logo:hover{color:var(--brand)}
.topbar .crumb{font-size:13px;color:var(--muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.topbar .crumb a{color:var(--muted);text-decoration:none}
.topbar .crumb a:hover{color:var(--brand)}
.topbar .btn{background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer;padding:6px;border-radius:6px;flex-shrink:0}
.topbar .btn:hover{background:var(--hover);color:var(--fg)}

/* ── 布局 ── */
.main{display:flex;padding-top:56px;min-height:calc(100vh - 56px)}

/* ── 目录栏 ── */
.toc{width:var(--toc-w);flex-shrink:0;position:sticky;top:56px;height:calc(100vh - 56px);overflow-y:auto;border-right:1px solid var(--border);padding:16px 0 40px;scrollbar-width:thin;scrollbar-color:#DEE0E3 transparent}
.toc::-webkit-scrollbar{width:4px}
.toc::-webkit-scrollbar-thumb{background:#DEE0E3;border-radius:2px}
.toc-head{display:flex;align-items:center;justify-content:space-between;padding:0 16px 10px;font-size:13px;font-weight:500;color:var(--muted);letter-spacing:.3px}
.toc-collapse{background:none;border:none;color:var(--muted);font-size:14px;cursor:pointer;padding:4px 6px;border-radius:4px}
.toc-collapse:hover{background:var(--hover)}
.toc-list{list-style:none}
.toc-list a{display:block;padding:5px 16px;font-size:14px;color:#646A73;text-decoration:none;line-height:22px;cursor:pointer;transition:background .1s,color .1s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:0}
.toc-list a:hover{background:var(--hover);color:var(--fg)}
.toc-list a.active{background:var(--brand-bg);color:var(--brand);font-weight:500}
.toc-list a.lvl-2{padding-left:16px}
.toc-list a.lvl-3{padding-left:36px;font-size:13px;color:#8F959E}

/* ── 文档区 ── */
.doc{flex:1;display:flex;justify-content:center;padding:0 40px 160px;min-width:0}
.doc-inner{max-width:var(--doc-w);width:100%;min-width:0}

/* ── 封面 ── */
.cover{margin:0 -40px 20px;overflow:hidden;border-radius:0 0 12px 12px;position:relative}
.cover img{width:100%;display:block;max-height:240px;object-fit:cover}
.cover .overlay{position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,rgba(0,0,0,.35));display:flex;align-items:flex-end;padding:24px 40px}
.cover .overlay h1{color:#FFF;font-size:26px;font-weight:700;text-shadow:0 1px 4px rgba(0,0,0,.4)}
.no-cover h1{font-size:28px;font-weight:700;color:var(--fg);letter-spacing:-.3px;margin:28px 0 4px;line-height:1.3}

/* ── 元信息 ── */
.meta{font-size:13px;color:var(--muted);margin:0 0 24px;display:flex;align-items:center;gap:8px}
.meta svg{width:14px;height:14px;flex-shrink:0}

/* ── 标题 ── */
h1{font-size:28px;font-weight:700;color:var(--fg);letter-spacing:-.3px;line-height:1.35}
h2{font-size:21px;font-weight:600;color:var(--fg);margin:2.4em 0 .6em;padding-bottom:8px;border-bottom:1px solid var(--border);line-height:1.4}
h3{font-size:17px;font-weight:600;color:var(--fg);margin:1.8em 0 .4em;line-height:1.4}

/* ── 正文 ── */
p{margin:.6em 0;color:var(--fg);line-height:1.75}
ul,ol{margin:.6em 0 .6em 0;color:var(--fg);padding-left:24px}
li{margin:.3em 0;line-height:1.7}
li>ul,li>ol{margin:.2em 0;padding-left:20px}
strong{color:var(--fg);font-weight:600}
code{background:var(--code-bg);padding:2px 6px;border-radius:4px;font:13px/1.5 "SF Mono",Menlo,Consolas,monospace;color:var(--code-fg)}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}

/* ── Callout 信息框 ── */
.callout{background:var(--callout-bg);border:1px solid var(--callout-border);border-radius:8px;padding:14px 18px;margin:1em 0;font-size:14px;color:#595959;line-height:1.7;position:relative;overflow:hidden}
.callout::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:#FFD591;border-radius:8px 0 0 8px}

/* ── 表格 ── */
.table-wrap{overflow-x:auto;margin:1em 0;border-radius:8px;border:1px solid var(--border)}
table{border-collapse:collapse;width:100%;font-size:14px}
th{background:var(--hover);color:var(--fg);font-weight:600;text-align:left;padding:10px 14px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:10px 14px;border-bottom:1px solid var(--border);color:#333}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:#FAFBFC}

/* ── 画廊 ── */
.gal-toggle{appearance:none;border:1px solid var(--border);background:#FFF;color:var(--fg);padding:10px 20px;border-radius:8px;font:14px inherit;cursor:pointer;margin:2.5em 0 1em;transition:border-color .15s,color .15s;flex-shrink:0}
.gal-toggle:hover{border-color:var(--brand);color:var(--brand)}
.gallery{display:none;columns:3;column-gap:12px;margin:1em 0}
.gallery.open{display:block}
.gallery figure{break-inside:avoid;margin:0 0 12px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:#FFF;transition:box-shadow .15s}
.gallery figure:hover{box-shadow:0 2px 12px rgba(0,0,0,.08)}
.gallery img{width:100%;display:block;cursor:zoom-in}
.gallery figcaption{padding:6px 10px;font-size:12px;color:var(--muted);border-top:1px solid var(--border)}

/* ── 灯箱 ── */
.lightbox{position:fixed;inset:0;background:rgba(255,255,255,.97);display:none;align-items:center;justify-content:center;z-index:99;cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:92vw;max-height:90vh;border-radius:8px;box-shadow:0 4px 30px rgba(0,0,0,.12)}

/* ── 响应式 ── */
@media(max-width:960px){
  .toc{position:fixed;left:-var(--toc-w);top:56px;height:calc(100vh - 56px);z-index:15;background:#FFF;box-shadow:2px 0 12px rgba(0,0,0,.08);transition:left .2s;width:var(--toc-w)}
  .toc.show{left:0}
  .doc{padding:0 16px 100px}
  .cover{margin:0 -16px 16px}
  .gallery{columns:2}
  .topbar .menu-btn{display:block}
  .cover .overlay{padding:16px}
  .cover .overlay h1{font-size:22px}
  .no-cover h1{font-size:24px}
}
@media(max-width:500px){
  .gallery{columns:1}
  h1{font-size:24px}
  h2{font-size:18px}
  h3{font-size:16px}
  .table-wrap{font-size:13px}
  th,td{padding:8px 10px}
}
.topbar .menu-btn{display:none;background:none;border:none;font-size:20px;color:var(--fg);cursor:pointer;padding:4px}
"""


def _build_page(root: Path) -> str:
    md_path = root / "creation-guide.md"
    md = md_path.read_text("utf-8") if md_path.is_file() else "# 指引文档不在本机"
    body = _md_to_html(md)

    # 自动提取修改日期
    mtime = datetime.datetime.fromtimestamp(md_path.stat().st_mtime) if md_path.is_file() else datetime.datetime.now()
    date_str = f"{mtime.month}月{mtime.day}日" if mtime.year == datetime.datetime.now().year else f"{mtime.year}年{mtime.month}月{mtime.day}日"

    # 构建两级目录（h2 + h3）
    headings = []
    for m in re.finditer(r"^(##|###)\s+(.+)$", md, re.MULTILINE):
        level = 2 if m.group(1) == "##" else 3
        headings.append({"level": level, "text": m.group(2).strip()})

    # 给 h2/h3 加 id
    sec_h2 = 0
    sec_h3 = 0
    for h in headings:
        if h["level"] == 2:
            sec_h3 = 0
            body = re.sub(r"<h2>", f'<h2 id="s2-{sec_h2}">', body, count=1)
            h["id"] = f"s2-{sec_h2}"
            sec_h2 += 1
        else:
            body = re.sub(r"<h3>", f'<h3 id="s3-{sec_h2-1}-{sec_h3}">', body, count=1)
            h["id"] = f"s3-{sec_h2-1}-{sec_h3}"
            sec_h3 += 1

    toc_items = "".join(
        f'<li><a href="#{h["id"]}" data-target="{h["id"]}" class="lvl-{h["level"]}">{html_mod.escape(h["text"])}</a></li>'
        for h in headings
    )

    images_dir = root / "images" / "doc"
    images = sorted(p.name for p in images_dir.iterdir() if p.suffix in MEDIA_TYPES) if images_dir.is_dir() else []
    gallery_html = ""
    if images:
        figs = "".join(
            f'<figure><img src="/creation-guide-media/{name}" loading="lazy" alt="{name}" onclick="lb(this.src)">'
            f"<figcaption>{name}</figcaption></figure>"
            for name in images
        )
        gallery_html = (
            f'<button class="gal-toggle" id="galBtn" onclick="var g=document.getElementById(\'gal\');g.classList.toggle(\'open\');this.textContent=g.classList.contains(\'open\')?\'收起配图\':\'展开全部 {len(images)} 张配图\'">展开全部 {len(images)} 张配图</button>\n'
            f'<div class="gallery" id="gal">{figs}</div>'
        )

    cover_path = root / "images" / "doc" / "cover.gif"
    has_cover = cover_path.exists()

    # 封面模式：有封面图时叠加标题；无封面图时标题独立展示
    if has_cover:
        hero = f'''<div class="cover"><img src="/creation-guide-media/cover.gif" alt="封面"><div class="overlay"><h1>VSC 工作台内容创作指引</h1></div></div>'''
        h1_area = ""
    else:
        hero = ""
        h1_area = '<div class="no-cover"><h1>VSC 工作台内容创作指引</h1></div>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VSC 工作台创作指引</title>
<link rel="stylesheet" href="/guide/creation.css">
</head>
<body>
<header class="topbar">
<button class="btn menu-btn" onclick="document.getElementById('toc').classList.toggle('show')" aria-label="目录">☰</button>
<a class="logo" href="/">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V4h6l3 3h9v12H3V7h18M16 13h7M20 10v6"/></svg>
VSC 工作台</a>
<span class="crumb">› <a href="/">首页</a> › 创作指引</span>
<button class="btn" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" aria-label="回到顶部" title="回到顶部">↑</button>
</header>
<div class="main">
<nav class="toc" id="toc">
<div class="toc-head"><span>目录</span><button class="toc-collapse" onclick="document.getElementById('toc').style.display='none'" title="收起目录">«</button></div>
<ul class="toc-list">{toc_items}</ul>
</nav>
<main class="doc"><div class="doc-inner">
{hero}
{h1_area}
<div class="meta"><svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 3a5 5 0 100 10A5 5 0 008 3zm0-3a8 8 0 110 16A8 8 0 018 0zm.5 4H7v5l4 2 .5-1-3-1.5V4z"/></svg>最近修改：{date_str}</div>
{body}
{gallery_html}
</div></main>
</div>
<div class="lightbox" id="lbx" onclick="this.classList.remove('open')"><img id="lbi" alt="预览"></div>
<script>
function lb(s){{document.getElementById('lbi').src=s;document.getElementById('lbx').classList.add('open')}}

// 目录滚动同步（IntersectionObserver）
var links=document.querySelectorAll('.toc-list a');
var obs=new IntersectionObserver(function(es){{
  es.forEach(function(e){{
    if(e.isIntersecting){{
      links.forEach(function(l){{l.classList.remove('active')}});
      var a=document.querySelector('.toc-list a[data-target="'+e.target.id+'"]');
      if(a)a.classList.add('active');
      // 确保活跃项在可视区
      var toc=document.getElementById('toc');
      var aRect=a.getBoundingClientRect();
      var tocRect=toc.getBoundingClientRect();
      if(aRect.top<tocRect.top+60||aRect.bottom>tocRect.bottom-60){{
        a.scrollIntoView({{block:'nearest'}});
      }}
    }}
  }});
}},{{rootMargin:'-30% 0px -60% 0px'}});

document.querySelectorAll('h2[id^="s"],h3[id^="s"]').forEach(function(h){{obs.observe(h)}});
</script>
</body>
</html>"""


def install_creation_guide_routes(app, etag, read_actor):
    def root():
        return guides_root()

    @app.get("/guide/creation", response_class=HTMLResponse)
    def guide_page():
        return HTMLResponse(_build_page(root()))

    @app.get("/guide/creation.css")
    def guide_css():
        return PlainTextResponse(PAGE_CSS, media_type="text/css; charset=utf-8")

    @app.get("/api/v1/creation-guide/md")
    def guide_md():
        path = root() / "creation-guide.md"
        if not path.is_file():
            raise HTTPException(404, "指引文档不在本机")
        return FileResponse(path, media_type="text/markdown; charset=utf-8")

    @app.get("/creation-guide-media/{name}")
    def guide_media(name: str):
        safe = Path(name).name
        for sub in ("images/doc", "images"):
            candidate = root() / sub / safe
            if candidate.is_file() and candidate.suffix in MEDIA_TYPES:
                return FileResponse(candidate, media_type=MEDIA_TYPES[candidate.suffix])
        raise HTTPException(404, "配图不在本机")
