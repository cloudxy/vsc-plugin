"""Read-only 创作指引：从 assets/guides 提供操作文档与配图。复刻飞书文档阅读器样式。"""
import html as html_mod
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

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


def _md_to_html(md: str) -> str:
    lines = md.split("\n")
    out = []
    in_list = False
    list_tag = "ul"
    in_table = False

    def inline(s):
        s = html_mod.escape(s, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
        return s

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            out.append(f'<h1>{inline(line[2:])}</h1>')
        elif line.startswith("## "):
            if in_list: out.append(f"</{list_tag}>"); in_list = False
            if in_table: out.append("</table>"); in_table = False
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("### "):
            if in_list: out.append(f"</{list_tag}>"); in_list = False
            if in_table: out.append("</table>"); in_table = False
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("|"):
            if i + 1 < len(lines) and re.match(r"^\|[\s:-]+\|", lines[i + 1]):
                if not in_table: out.append("<table>"); in_table = True
                cells = [c.strip() for c in line.split("|")[1:-1]]
                out.append("<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr></thead><tbody>")
                i += 1
            elif in_table:
                cells = [c.strip() for c in line.split("|")[1:-1]]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
        else:
            if in_table: out.append("</tbody></table>"); in_table = False
            if line.startswith("- "):
                if not in_list or list_tag != "ul":
                    if in_list: out.append(f"</{list_tag}>")
                    out.append("<ul>"); in_list = True; list_tag = "ul"
                out.append(f"<li>{inline(line[2:])}</li>")
            elif re.match(r"^\d+\.\s", line):
                if not in_list or list_tag != "ol":
                    if in_list: out.append(f"</{list_tag}>")
                    out.append("<ol>"); in_list = True; list_tag = "ol"
                out.append(f"<li>{inline(re.sub(r'^\d+\.\s', '', line))}</li>")
            else:
                if in_list: out.append(f"</{list_tag}>"); in_list = False
                if line.startswith(">"):
                    out.append(f'<div class="callout">{inline(line[1:])}</div>')
                elif line.strip():
                    out.append(f"<p>{inline(line)}</p>")
        i += 1
    if in_list: out.append(f"</{list_tag}>")
    if in_table: out.append("</tbody></table>")
    return "\n".join(out)


PAGE_CSS = """
:root{
  --bg:#FFFFFF;--fg:#1F2329;--muted:#8F959E;--hover:#F2F3F5;
  --brand:#3370FF;--brand-bg:#EBF1FF;--border:#DEE0E3;
  --callout-bg:#FFF7E6;--callout-border:#FFD591;
  --code-bg:#F5F6F7;--code-fg:#3B5998;
  --toc-w:280px;--doc-w:800px;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Helvetica Neue",sans-serif}

/* ── 布局 ── */
.topbar{position:fixed;top:0;left:0;right:0;height:56px;background:#FFF;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:16px;z-index:10}
.topbar .logo{font-size:16px;font-weight:600;color:var(--fg);text-decoration:none;display:flex;align-items:center;gap:8px}
.topbar .logo svg{width:22px;height:22px}
.topbar .breadcrumb{font-size:13px;color:var(--muted);flex:1}
.topbar .breadcrumb a{color:var(--muted);text-decoration:none}
.topbar .breadcrumb a:hover{color:var(--brand)}

.main{display:flex;padding-top:56px;min-height:calc(100vh - 56px)}

/* ── 目录栏 ── */
.toc{width:var(--toc-w);flex-shrink:0;position:sticky;top:56px;height:calc(100vh - 56px);overflow-y:auto;border-right:1px solid var(--border);padding:16px 0 24px;transition:width .2s}
.toc.collapsed{width:0;padding:0;border:none;overflow:hidden}
.toc-head{display:flex;align-items:center;justify-content:space-between;padding:0 16px 12px;font-size:13px;font-weight:500;color:var(--muted)}
.toc-toggle{background:none;border:none;color:var(--muted);font-size:16px;cursor:pointer;padding:4px;border-radius:4px}
.toc-toggle:hover{background:var(--hover)}
.toc-list{list-style:none}
.toc-list a{display:block;padding:7px 16px 7px 24px;font-size:14px;color:#646A73;text-decoration:none;line-height:22px;cursor:pointer;transition:background .12s,color .12s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.toc-list a:hover{background:var(--hover);color:var(--fg)}
.toc-list a.active{background:var(--brand-bg);color:var(--brand);font-weight:500;border-radius:6px;margin:0 8px;padding-left:16px}
.toc-list .sub a{padding-left:40px;font-size:13px}

/* ── 文档区 ── */
.doc{flex:1;display:flex;justify-content:center;padding:0 40px 120px}
.doc-inner{max-width:var(--doc-w);width:100%;min-width:0}

/* ── 封面 ── */
.cover{margin:0 -40px 24px;border-radius:0;overflow:hidden}
.cover img{width:100%;display:block;max-height:280px;object-fit:cover}

/* ── 标题 ── */
h1{font-size:28px;font-weight:700;color:var(--fg);letter-spacing:-.3px;margin:0 0 6px;line-height:1.35}
h2{font-size:21px;font-weight:600;color:var(--fg);margin:2.2em 0 .5em;padding-bottom:8px;border-bottom:1px solid var(--border);scroll-margin-top:80px}
h3{font-size:17px;font-weight:600;color:var(--fg);margin:1.8em 0 .4em;scroll-margin-top:80px}
.meta{font-size:13px;color:var(--muted);margin-bottom:28px}

/* ── 正文 ── */
p{margin:.65em 0;color:var(--fg);line-height:1.7}
ul,ol{margin:.65em 0 .65em 20px;color:var(--fg)}
li{margin:.3em 0;line-height:1.65}
strong{color:var(--fg);font-weight:600}
code{background:var(--code-bg);padding:2px 6px;border-radius:4px;font:13px/1.5 "SF Mono",Menlo,Consolas,monospace;color:var(--code-fg)}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}

/* ── Callout ── */
.callout{background:var(--callout-bg);border:1px solid var(--callout-border);border-radius:8px;padding:12px 16px;margin:.8em 0;font-size:14px;color:#595959;line-height:1.6}

/* ── 表格 ── */
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:14px}
th{background:var(--hover);color:var(--fg);font-weight:600;text-align:left;padding:10px 14px;border:1px solid var(--border);white-space:nowrap}
td{padding:10px 14px;border:1px solid var(--border);color:#333}
tbody tr:hover td{background:#FAFBFC}

/* ── 画廊 ── */
.gal-toggle{appearance:none;border:1px solid var(--border);background:#FFF;color:var(--fg);padding:10px 20px;border-radius:8px;font:14px inherit;cursor:pointer;margin:2em 0 1em;transition:all .15s}
.gal-toggle:hover{border-color:var(--brand);color:var(--brand)}
.gallery{display:none;columns:3;column-gap:12px;margin:1em 0}
.gallery.open{display:block}
.gallery figure{break-inside:avoid;margin:0 0 12px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:#FFF}
.gallery img{width:100%;display:block;cursor:zoom-in}
.gallery figcaption{padding:6px 10px;font-size:12px;color:var(--muted);border-top:1px solid var(--border)}

/* ── 灯箱 ── */
.lightbox{position:fixed;inset:0;background:rgba(255,255,255,.97);display:none;align-items:center;justify-content:center;z-index:99;cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:92vw;max-height:90vh;border-radius:8px;box-shadow:0 4px 30px rgba(0,0,0,.12)}

/* ── 响应式 ── */
@media(max-width:960px){
  .toc{position:fixed;left:-280px;top:56px;height:calc(100vh - 56px);z-index:20;background:#FFF;box-shadow:2px 0 8px rgba(0,0,0,.08);transition:left .2s}
  .toc.show{left:0}
  .doc{padding:0 16px 80px}
  .cover{margin:0 -16px 20px}
  .gallery{columns:2}
  .topbar .menu-btn{display:block}
}
@media(max-width:500px){
  .gallery{columns:1}
  h1{font-size:24px}
  h2{font-size:18px}
}
.topbar .menu-btn{display:none;background:none;border:none;font-size:20px;color:var(--fg);cursor:pointer;padding:4px}
"""


def _build_page(root: Path) -> str:
    md_path = root / "creation-guide.md"
    md = md_path.read_text("utf-8") if md_path.is_file() else "# 指引文档不在本机"
    body = _md_to_html(md)

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
            f'<button class="gal-toggle" onclick="g=document.getElementById(\'gal\');g.classList.toggle(\'open\');this.textContent=g.classList.contains(\'open\')?\'收起配图\':\'展开全部 {len(images)} 张配图\'">展开全部 {len(images)} 张配图</button>\n'
            f'<div class="gallery" id="gal">{figs}</div>'
        )

    h2_titles = re.findall(r"<h2>(.+?)</h2>", body)
    toc_items = "".join(
        f'<li><a href="#sec-{i}" data-sec="{i}">{t}</a></li>'
        for i, t in enumerate(h2_titles)
    )
    for i, _ in enumerate(h2_titles):
        body = re.sub(r"<h2>", f'<h2 id="sec-{i}">', body, count=1)

    cover_path = root / "images" / "doc" / "cover.gif"
    cover_html = f'<div class="cover"><img src="/creation-guide-media/cover.gif" alt="封面"></div>' if cover_path.exists() else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VSC 工作台创作指引</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<header class="topbar">
<button class="menu-btn" onclick="document.querySelector('.toc').classList.toggle('show')">☰</button>
<a class="logo" href="/">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7V4h6l3 3h9v12H3V7h18M16 13h7M20 10v6" stroke-linecap="round" stroke-linejoin="round"/></svg>
VSC 工作台</a>
<span class="breadcrumb">› <a href="/">首页</a> › 创作指引</span>
</header>
<div class="main">
<nav class="toc" id="toc">
<div class="toc-head"><span>目录</span><button class="toc-toggle" onclick="document.getElementById('toc').classList.add('collapsed');document.querySelector('.menu-btn').style.display='block'">«</button></div>
<ul class="toc-list">{toc_items}</ul>
</nav>
<main class="doc"><div class="doc-inner">
{cover_html}
{body}
{gallery_html}
</div></main>
</div>
<div class="lightbox" id="lbx" onclick="this.classList.remove('open')"><img id="lbi" alt="预览"></div>
<script>
function lb(s){{document.getElementById('lbi').src=s;document.getElementById('lbx').classList.add('open')}}
// 目录高亮
const links=document.querySelectorAll('.toc-list a');
const obs=new IntersectionObserver(es=>{{
  es.forEach(e=>{{
    if(e.isIntersecting){{
      links.forEach(l=>l.classList.remove('active'));
      const a=document.querySelector('.toc-list a[data-sec="'+e.target.id.replace('sec-','')+'"]');
      if(a)a.classList.add('active');
    }}
  }});
}},{{rootMargin:'-30% 0px -60% 0px'}});
document.querySelectorAll('h2[id^="sec-"]').forEach(h=>obs.observe(h));
</script>
</body>
</html>"""


def install_creation_guide_routes(app, etag, read_actor):
    def root():
        return guides_root()

    @app.get("/guide/creation", response_class=HTMLResponse)
    def guide_page():
        return HTMLResponse(_build_page(root()))

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
