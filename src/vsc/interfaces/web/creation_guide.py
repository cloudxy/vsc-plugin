"""Read-only creation guide: database-backed document reader with Feishu-style UI."""
import html as html_mod
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".svg": "image/svg+xml", ".avif": "image/avif"}


def guides_root(root=None):
    from vsc.configuration import get_config
    base = Path(get_config("VSC_MEDIA_ROOT")).parent / "guides" if get_config("VSC_MEDIA_ROOT") else None
    if base and base.is_dir():
        return base
    return Path(__file__).resolve().parents[4] / "assets" / "guides"


def _inline(s):
    s = html_mod.escape(s, quote=False)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1" class="inline-img" onclick="lb(this.src)">', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
    return s


def _render_body(body_md):
    if not body_md:
        return ""
    lines = body_md.split("\n")
    out = []
    in_ul = False
    in_ol = False
    in_table = False
    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul: out.append("</ul>"); in_ul = False
        if in_ol: out.append("</ol>"); in_ol = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("> "):
            close_lists()
            out.append(f'<div class="callout">{_inline(stripped[2:])}</div>')
        elif stripped.startswith("| ") and stripped.count("|") >= 2:
            close_lists()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if not in_table:
                out.append('<div class="table-wrap"><table><thead><tr>')
                out.append("".join(f"<th>{_inline(c)}</th>" for c in cells))
                out.append("</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
        elif in_table and not stripped.startswith("|"):
            out.append("</tbody></table></div>")
            in_table = False
            if stripped: out.append(f"<p>{_inline(stripped)}</p>")
        elif stripped.startswith("- "):
            if in_ol: out.append("</ol>"); in_ol = False
            if not in_ul: out.append("<ul>"); in_ul = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            if in_ul: out.append("</ul>"); in_ul = False
            if not in_ol: out.append("<ol>"); in_ol = True
            out.append(f"<li>{_inline(re.sub(r'^\d+\.\s', '', stripped))}</li>")
        elif stripped.startswith("!["):
            close_lists()
            out.append(_inline(stripped))
        elif stripped:
            close_lists()
            out.append(f"<p>{_inline(stripped)}</p>")
        else:
            close_lists()
    close_lists()
    if in_table: out.append("</tbody></table></div>")
    return "\n".join(out)


PAGE_CSS = """
:root{--bg:#FFF;--fg:#1F2329;--muted:#8F959E;--hover:#F2F3F5;--brand:#3370FF;
--brand-bg:#EBF1FF;--border:#DEE0E3;--callout-bg:#FFF7E6;--callout-border:#FFD591;
--code-bg:#F5F6F7;--code-fg:#3B5998;--toc-w:260px;--doc-w:780px}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:72px}
body{background:var(--bg);color:var(--fg);font:14px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Helvetica Neue",sans-serif}

/* ── 顶栏（飞书样式：白底+面包屑+浅色） ── */
.topbar{position:fixed;top:0;left:0;right:0;height:48px;background:#FFF;
border-bottom:1px solid var(--border);display:flex;align-items:center;
padding:0 16px;gap:8px;z-index:20}
.topbar .crumb{font-size:13px;color:var(--muted);flex:1;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap;display:flex;align-items:center;gap:4px}
.topbar .crumb a{color:var(--muted);text-decoration:none}
.topbar .crumb a:hover{color:var(--brand)}
.topbar .crumb .sep{color:#DEE0E3;font-size:11px}
.topbar .crumb .current{color:var(--fg);font-weight:500}
.topbar .btn{background:none;border:none;color:var(--muted);font-size:16px;
cursor:pointer;padding:4px 8px;border-radius:4px;flex-shrink:0;line-height:1}
.topbar .btn:hover{background:var(--hover);color:var(--fg)}
.topbar .menu-btn{display:none}

/* ── 布局 ── */
.main{display:flex;padding-top:48px;min-height:calc(100vh - 48px)}

/* ── 目录（飞书样式：浅灰底+紧凑行距+折叠） ── */
.toc{width:var(--toc-w);flex-shrink:0;position:sticky;top:48px;
height:calc(100vh - 48px);overflow-y:auto;background:#FAFBFC;
border-right:1px solid var(--border);padding:12px 0 32px;
scrollbar-width:thin;scrollbar-color:#DEE0E3 transparent}
.toc::-webkit-scrollbar{width:4px}
.toc::-webkit-scrollbar-thumb{background:#DEE0E3;border-radius:2px}
.toc-head{display:flex;align-items:center;justify-content:space-between;
padding:0 12px 6px;font-size:12px;font-weight:500;color:var(--muted);
text-transform:uppercase;letter-spacing:.5px}
.toc-collapse{background:none;border:none;color:var(--muted);font-size:13px;
cursor:pointer;padding:2px 6px;border-radius:4px}
.toc-collapse:hover{background:var(--hover);color:var(--fg)}
.toc-list{list-style:none}
.toc-list a{display:block;padding:3px 12px;font-size:13px;color:#646A73;
text-decoration:none;line-height:20px;transition:background .08s,color .08s;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:4px;margin:0 4px}
.toc-list a:hover{background:var(--hover);color:var(--fg)}
.toc-list a.active{background:var(--brand-bg);color:var(--brand);font-weight:500}
.toc-list a.lvl-2{font-size:13px;padding-left:12px}
.toc-list a.lvl-3{padding-left:28px;font-size:12px;color:#8F959E}

/* ── 文档区 ── */
.doc{flex:1;display:flex;justify-content:center;padding:0 48px 120px;min-width:0}
.doc-inner{max-width:var(--doc-w);width:100%;min-width:0}

/* ── 标题区（飞书样式：面包屑+标题+元信息，不用封面横幅） ── */
.doc-header{padding:28px 0 0}
.doc-header .breadcrumb{font-size:13px;color:var(--muted);margin-bottom:8px;
display:flex;align-items:center;gap:4px}
.doc-header .breadcrumb a{color:var(--muted);text-decoration:none}
.doc-header .breadcrumb a:hover{color:var(--brand)}
.doc-header .breadcrumb .sep{color:#DEE0E3;font-size:11px}
h1{font-size:26px;font-weight:700;color:var(--fg);letter-spacing:-.3px;
line-height:1.35;margin:8px 0 4px}
.meta{font-size:12px;color:var(--muted);margin:0 0 20px;display:flex;
align-items:center;gap:8px}
.meta .dot{color:#DEE0E3}

/* ── 封面图（在标题下方，等比缩放不裁切） ── */
.cover{margin:0 0 20px;overflow:hidden;border-radius:8px;border:1px solid var(--border)}
.cover img{width:100%;height:auto;display:block;object-fit:contain}

/* ── 正文标题 ── */
h2{font-size:20px;font-weight:600;color:var(--fg);margin:2em 0 .5em;
padding-bottom:6px;border-bottom:1px solid var(--border)}
h3{font-size:16px;font-weight:600;color:var(--fg);margin:1.6em 0 .3em}

/* ── 正文 ── */
p{margin:.5em 0;color:var(--fg);line-height:1.75}
ul,ol{margin:.5em 0;color:var(--fg);padding-left:20px}
li{margin:.2em 0;line-height:1.7}
strong{color:var(--fg);font-weight:600}
code{background:var(--code-bg);padding:1px 5px;border-radius:3px;
font:13px/1.5 "SF Mono",Menlo,monospace;color:var(--code-fg)}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}

/* ── Callout（飞书样式） ── */
.callout{background:var(--callout-bg);border:1px solid var(--callout-border);
border-radius:6px;padding:10px 14px;margin:.8em 0;font-size:13px;
color:#595959;line-height:1.65}

/* ── 内嵌图片 ── */
.inline-img{max-width:100%;min-width:200px;height:auto;border-radius:8px;
border:1px solid var(--border);margin:12px auto;display:block;cursor:zoom-in;
box-shadow:0 2px 8px rgba(0,0,0,.06);transition:box-shadow .15s}
.inline-img:hover{box-shadow:0 4px 16px rgba(0,0,0,.12)}

/* ── 表格 ── */
.table-wrap{overflow-x:auto;margin:.8em 0;border-radius:6px;border:1px solid var(--border)}
table{border-collapse:collapse;width:100%;font-size:13px}
th{background:var(--hover);color:var(--fg);font-weight:600;text-align:left;
padding:8px 12px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--border);color:#333}
tbody tr:last-child td{border-bottom:none}

/* ── 画廊 ── */
.gal-toggle{appearance:none;border:1px solid var(--border);background:#FFF;
color:var(--fg);padding:8px 16px;border-radius:6px;font:13px inherit;
cursor:pointer;margin:2em 0 .8em}
.gal-toggle:hover{border-color:var(--brand);color:var(--brand)}
.gallery{display:none;columns:3;column-gap:10px;margin:.8em 0}
.gallery.open{display:block}
.gallery figure{break-inside:avoid;margin:0 0 10px;border:1px solid var(--border);
border-radius:6px;overflow:hidden;background:#FFF}
.gallery img{width:100%;display:block;cursor:zoom-in}
.gallery figcaption{padding:4px 8px;font-size:11px;color:var(--muted);
border-top:1px solid var(--border)}

/* ── 灯箱 ── */
.lightbox{position:fixed;inset:0;background:rgba(255,255,255,.97);display:none;
align-items:center;justify-content:center;z-index:99;cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:92vw;max-height:90vh;border-radius:6px;
box-shadow:0 4px 24px rgba(0,0,0,.1)}

/* ── 响应式 ── */
@media(max-width:960px){
  .toc{position:fixed;left:-260px;top:48px;height:calc(100vh - 48px);z-index:15;
  background:#FFF;box-shadow:2px 0 10px rgba(0,0,0,.06);transition:left .2s}
  .toc.show{left:0}
  .doc{padding:0 16px 80px}
  .gallery{columns:2}
  .topbar .menu-btn{display:block}
}
@media(max-width:500px){
  .gallery{columns:1}
  h1{font-size:22px}
  h2{font-size:17px}
  h3{font-size:15px}
}
"""


def _build_page(data):
    doc = data["document"]
    sections = data["sections"]
    images = data.get("images", [])

    toc_items = []
    body_parts = []
    h2_idx = 0
    section_map = {}
    for sec in sections:
        sid = sec["id"]
        if sec["level"] == 2:
            anchor = f"s2-{h2_idx}"
            h2_idx += 1
            toc_items.append(f'<li><a href="#{anchor}" data-target="{anchor}" class="lvl-2">{html_mod.escape(sec["title"])}</a></li>')
            callout_html = f'<div class="callout">{_inline(sec["callout"])}</div>' if sec.get("callout") else ""
            body_html = _render_body(sec.get("body", ""))
            body_parts.append(f'<h2 id="{anchor}">{html_mod.escape(sec["title"])}</h2>{callout_html}{body_html}')
            section_map[sid] = anchor
        elif sec["level"] == 3:
            parent_anchor = section_map.get(sec.get("parent_id"), "")
            anchor = f"{parent_anchor}-{sec['sort_order']}" if parent_anchor else f"s3-{sec['sort_order']}"
            toc_items.append(f'<li><a href="#{anchor}" data-target="{anchor}" class="lvl-3">{html_mod.escape(sec["title"])}</a></li>')
            callout_html = f'<div class="callout">{_inline(sec["callout"])}</div>' if sec.get("callout") else ""
            body_html = _render_body(sec.get("body", ""))
            body_parts.append(f'<h3 id="{anchor}">{html_mod.escape(sec["title"])}</h3>{callout_html}{body_html}')

    gallery_html = ""
    if images:
        figs = "".join(
            f'<figure><img src="{img["media_url"]}" loading="lazy" alt="{html_mod.escape(img.get("alt_text",""))}" onclick="lb(this.src)">'
            f"<figcaption>{html_mod.escape(img['filename'])}</figcaption></figure>"
            for img in images)
        gallery_html = (
            f'<button class="gal-toggle" onclick="var g=document.getElementById(\'gal\');g.classList.toggle(\'open\');'
            f'this.textContent=g.classList.contains(\'open\')?\'收起配图\':\'展开全部 {len(images)} 张配图\'">'
            f'展开全部 {len(images)} 张配图</button>\n<div class="gallery" id="gal">{figs}</div>')

    cover_path = Path(str(guides_root())) / "images" / "doc" / "cover.gif"
    cover_html = f'<div class="cover"><img src="/creation-guide-media/cover.gif" alt="封面"></div>' if cover_path.exists() else ""

    updated = doc.get("updated_at")
    date_str = f"{updated.month}月{updated.day}日" if hasattr(updated, "month") else str(updated or "")[:10] if updated else ""

    title = html_mod.escape(doc["title"])
    toc_html = "".join(toc_items)
    body_html = "\n".join(body_parts)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/guide/creation.css">
</head>
<body>
<header class="topbar">
<button class="btn menu-btn" onclick="document.getElementById('toc').classList.toggle('show')" aria-label="目录">☰</button>
<span class="crumb">
<a href="/">首页</a><span class="sep">›</span><span class="current">{title}</span>
</span>
<button class="btn" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="回到顶部">↑</button>
</header>
<div class="main">
<nav class="toc" id="toc">
<div class="toc-head"><span>目录</span><button class="toc-collapse" onclick="document.getElementById('toc').style.display='none';document.querySelector('.menu-btn').style.display='block'" title="收起目录">«</button></div>
<ul class="toc-list">{toc_html}</ul>
</nav>
<main class="doc"><div class="doc-inner">
<div class="doc-header">
<div class="breadcrumb"><a href="/">VSC 工作台</a><span class="sep">›</span><span>{title}</span></div>
<h1>{title}</h1>
<div class="meta"><span>最近修改：{date_str}</span><span class="dot">·</span><span>{len(sections)} 个章节</span></div>
</div>
{cover_html}
{body_html}
{gallery_html}
</div></main>
</div>
<div class="lightbox" id="lbx" onclick="this.classList.remove('open')"><img id="lbi" alt=""></div>
<script>
function lb(s){{document.getElementById('lbi').src=s;document.getElementById('lbx').classList.add('open')}}
var links=document.querySelectorAll('.toc-list a');
var obs=new IntersectionObserver(function(es){{
  es.forEach(function(e){{
    if(e.isIntersecting){{
      links.forEach(function(l){{l.classList.remove('active')}});
      var a=document.querySelector('.toc-list a[data-target="'+e.target.id+'"]');
      if(a)a.classList.add('active');
    }}
  }});
}},{{rootMargin:'-30% 0px -60% 0px'}});
document.querySelectorAll('h2[id^="s"],h3[id^="s"]').forEach(function(h){{obs.observe(h)}});
</script>
</body>
</html>"""


def _jsonable(obj):
    import datetime as dt
    import uuid as uuid_mod
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, uuid_mod.UUID):
        return str(obj)
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    return obj


def install_creation_guide_routes(app, etag, read_actor, guide_store=None):
    def root():
        return guides_root()

    def store():
        if guide_store is not None:
            return guide_store
        from sqlalchemy import create_engine
        from vsc.configuration import get_config
        from vsc.assets.guide_store import GuideStore
        return GuideStore(create_engine(get_config("VSC_DATABASE_URL"), pool_pre_ping=True))

    @app.get("/guide/creation", response_class=HTMLResponse)
    def guide_page():
        data = store().get_document("tiangong-guide") or store().get_document("creation-guide")
        if not data:
            raise HTTPException(404, "指引文档不在数据库中")
        return HTMLResponse(_build_page(data))

    @app.get("/guide/creation.css")
    def guide_css():
        return PlainTextResponse(PAGE_CSS, media_type="text/css; charset=utf-8")

    @app.get("/api/v1/guide/documents")
    def guide_documents():
        return JSONResponse(_jsonable(store().list_documents()))

    @app.get("/api/v1/guide/documents/{slug}")
    def guide_document(slug: str):
        data = store().get_document(slug)
        if not data:
            raise HTTPException(404, "文档不存在")
        return JSONResponse(_jsonable(data))

    @app.get("/creation-guide-media/{path:path}")
    def guide_media(path: str):
        safe = Path(path)
        for sub in ("images/full", "images/doc", "images"):
            candidate = root() / sub / safe
            if candidate.is_file() and candidate.suffix in MEDIA_TYPES:
                return FileResponse(candidate, media_type=MEDIA_TYPES[candidate.suffix])
        raise HTTPException(404, "配图不在本机")
