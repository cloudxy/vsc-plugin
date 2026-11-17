"""Read-only 创作指引：从 assets/guides 提供操作文档与配图。"""
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
    workspace = Path(__file__).resolve().parents[4]
    return workspace / "assets" / "guides"


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
            out.append(f'<h1 id="top">{inline(line[2:])}</h1>')
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
                    out.append(f"<blockquote><p>{inline(line[1:])}</p></blockquote>")
                elif line.strip():
                    out.append(f"<p>{inline(line)}</p>")
        i += 1
    if in_list: out.append(f"</{list_tag}>")
    if in_table: out.append("</tbody></table>")
    return "\n".join(out)


PAGE_CSS = """
:root{
  --bg:#FAFAF7;--fg:#1A1A1A;--muted:#6B6B6B;--accent:#4A6FA5;
  --accent-light:#EBF0F7;--border:#E5E2DD;--code-bg:#F0EDE8;
  --sidebar-w:240px;--content-w:720px;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif}

/* 布局 */
.layout{display:flex;max-width:calc(var(--sidebar-w) + var(--content-w) + 80px);margin:0 auto;padding:0 24px;gap:40px}
.sidebar{width:var(--sidebar-w);flex-shrink:0;position:sticky;top:0;height:100vh;overflow-y:auto;padding:48px 0 24px;border-right:1px solid var(--border)}
.content{flex:1;min-width:0;padding:48px 0 120px;max-width:var(--content-w)}

/* 封面 */
.cover{margin:-48px -24px 32px;padding:0;border-radius:0 0 16px 16px;overflow:hidden}
.cover img{width:100%;display:block;max-height:280px;object-fit:cover}

/* 标题 */
h1{font-size:28px;font-weight:700;color:var(--fg);margin:0 0 8px;letter-spacing:-.5px}
h2{font-size:22px;font-weight:600;color:var(--fg);margin:2.5em 0 .6em;padding-bottom:.4em;border-bottom:2px solid var(--accent);scroll-margin-top:24px}
h3{font-size:18px;font-weight:600;color:var(--fg);margin:2em 0 .4em;scroll-margin-top:24px}

/* 正文 */
p{margin:.7em 0;color:#333}
ul,ol{margin:.7em 0 .7em 1.4em;color:#333}
li{margin:.35em 0}
strong{color:var(--fg);font-weight:600}
code{background:var(--code-bg);padding:2px 6px;border-radius:4px;font:14px/1.5 "SF Mono",Menlo,monospace;color:#3B5998}
a{color:var(--accent);text-decoration:none;border-bottom:1px solid transparent;transition:border-color .15s}
a:hover{border-bottom-color:var(--accent)}
blockquote{border-left:3px solid var(--accent);padding:8px 16px;margin:1em 0;background:var(--accent-light);border-radius:0 8px 8px 0}
blockquote p{margin:.3em 0;color:#4A4A4A}

/* 表格 */
table{border-collapse:collapse;width:100%;margin:1.2em 0;font-size:14px}
th{background:var(--accent-light);color:var(--fg);font-weight:600;text-align:left;padding:10px 14px;border:1px solid var(--border)}
td{padding:10px 14px;border:1px solid var(--border);color:#444}
tbody tr:nth-child(even){background:#F5F3F0}

/* 侧栏目录 */
.toc-title{font-size:13px;font-weight:600;color:var(--muted);text-transform:none;letter-spacing:.5px;margin-bottom:12px}
.toc-nav{list-style:none;margin:0;padding:0}
.toc-nav a{display:block;padding:6px 12px;font-size:14px;color:var(--muted);border-left:2px solid transparent;border-bottom:none;transition:color .15s,border-color .15s}
.toc-nav a:hover{color:var(--accent)}
.toc-nav a.active{color:var(--accent);border-left-color:var(--accent);font-weight:500}

/* 画廊 */
.gallery-toggle{appearance:none;border:1px solid var(--border);background:#fff;color:var(--fg);padding:10px 20px;border-radius:8px;font:15px inherit;cursor:pointer;margin:2em 0 1em;transition:border-color .15s}
.gallery-toggle:hover{border-color:var(--accent)}
.gallery{display:none;columns:3;column-gap:12px;margin:1em 0}
.gallery.open{display:block}
.gallery figure{break-inside:avoid;margin:0 0 12px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:#fff}
.gallery img{width:100%;display:block;cursor:zoom-in;transition:transform .15s}
.gallery img:hover{transform:scale(1.02)}
.gallery figcaption{padding:6px 10px;font-size:12px;color:var(--muted);border-top:1px solid var(--border)}

/* 灯箱 */
.lightbox{position:fixed;inset:0;background:rgba(250,250,247,.96);display:none;align-items:center;justify-content:center;z-index:99;cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:92vw;max-height:90vh;border-radius:8px;box-shadow:0 8px 40px rgba(0,0,0,.15)}

/* 面包屑 */
.crumb{font-size:13px;color:var(--muted);margin-bottom:16px}
.crumb a{color:var(--muted);border-bottom:none}
.crumb a:hover{color:var(--accent)}

/* 响应式 */
@media(max-width:900px){
  .layout{flex-direction:column;gap:0;padding:0 16px}
  .sidebar{position:static;width:100%;height:auto;border-right:none;border-bottom:1px solid var(--border);padding:20px 0}
  .content{padding:24px 0 80px}
  .cover{margin:-24px -16px 24px}
  .gallery{columns:2}
}
@media(max-width:500px){
  .gallery{columns:1}
  h1{font-size:24px}
  h2{font-size:19px}
}
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
            f'<button class="gallery-toggle" onclick="document.getElementById(\'gal\').classList.toggle(\'open\');this.textContent=this.textContent.includes(\'展开\')?\'收起配图\':\'展开全部 {len(images)} 张配图\'">展开全部 {len(images)} 张配图</button>\n'
            f'<div class="gallery" id="gal">{figs}</div>'
        )

    # 目录
    h2_titles = re.findall(r"<h2>(.+?)</h2>", body)
    toc_items = "".join(
        f'<li><a href="#sec-{i}" data-sec="{i}">{t}</a></li>'
        for i, t in enumerate(h2_titles)
    )
    # 给每个 h2 加 id
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
<div class="layout">
<nav class="sidebar">
<div class="toc-title">章节</div>
<ul class="toc-nav">{toc_items}</ul>
</nav>
<main class="content">
{cover_html}
{body}
{gallery_html}
</main>
</div>
<div class="lightbox" id="lbx" onclick="this.classList.remove('open')"><img id="lbi" alt="预览"></div>
<script>
function lb(src){{document.getElementById('lbi').src=src;document.getElementById('lbx').classList.add('open')}}
// 目录高亮
const links=document.querySelectorAll('.toc-nav a');
const obs=new IntersectionObserver(es=>{{
  es.forEach(e=>{{
    if(e.isIntersecting){{
      links.forEach(l=>l.classList.remove('active'));
      const active=document.querySelector(`.toc-nav a[data-sec="${{e.target.id.replace('sec-','')}}"]`);
      if(active)active.classList.add('active');
    }}
  }});
}},{{rootMargin:'-20% 0px -60% 0px'}});
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
