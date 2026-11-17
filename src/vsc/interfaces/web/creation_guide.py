"""Read-only creation guide: database-backed document reader with Feishu-style UI."""
import html as html_mod
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.responses import JSONResponse

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
# Markdown 渲染（服务端，复刻飞书文档排版）
# ─────────────────────────────────────────────────────────────────────

def _inline(s):
    s = html_mod.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
    return s


def _render_body(body_md: str) -> str:
    """Render a section's markdown body to HTML (paragraphs, lists, tables, callouts)."""
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
        elif stripped.startswith("| ") and "|" in stripped[1:]:
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
            if stripped:
                out.append(f"<p>{_inline(stripped)}</p>")
        elif stripped.startswith("- "):
            if in_ol: out.append("</ol>"); in_ol = False
            if not in_ul: out.append("<ul>"); in_ul = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            if in_ul: out.append("</ul>"); in_ul = False
            if not in_ol: out.append("<ol>"); in_ol = True
            out.append(f"<li>{_inline(re.sub(r'^\d+\.\s', '', stripped))}</li>")
        elif stripped:
            close_lists()
            out.append(f"<p>{_inline(stripped)}</p>")
        else:
            close_lists()
    close_lists()
    if in_table:
        out.append("</tbody></table></div>")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────
# CSS（复刻飞书文档阅读器）
# ─────────────────────────────────────────────────────────────────────

PAGE_CSS = """
:root{--bg:#FFF;--fg:#1F2329;--muted:#8F959E;--hover:#F2F3F5;--brand:#3370FF;--brand-bg:#EBF1FF;--border:#DEE0E3;--callout-bg:#FFF7E6;--callout-border:#FFD591;--code-bg:#F5F6F7;--code-fg:#3B5998;--toc-w:280px;--doc-w:800px}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:80px}
body{background:var(--bg);color:var(--fg);font:15px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif}
.topbar{position:fixed;top:0;left:0;right:0;height:56px;background:#FFF;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:12px;z-index:20}
.topbar .logo{font-size:15px;font-weight:600;color:var(--fg);text-decoration:none;display:flex;align-items:center;gap:8px;flex-shrink:0}
.topbar .crumb{font-size:13px;color:var(--muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.topbar .crumb a{color:var(--muted);text-decoration:none}
.topbar .btn{background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer;padding:6px;border-radius:6px;flex-shrink:0}
.topbar .btn:hover{background:var(--hover);color:var(--fg)}
.topbar .menu-btn{display:none}
.main{display:flex;padding-top:56px;min-height:calc(100vh - 56px)}
.toc{width:var(--toc-w);flex-shrink:0;position:sticky;top:56px;height:calc(100vh - 56px);overflow-y:auto;border-right:1px solid var(--border);padding:16px 0 40px;scrollbar-width:thin;scrollbar-color:#DEE0E3 transparent}
.toc::-webkit-scrollbar{width:4px}
.toc::-webkit-scrollbar-thumb{background:#DEE0E3;border-radius:2px}
.toc-head{display:flex;align-items:center;justify-content:space-between;padding:0 16px 10px;font-size:13px;font-weight:500;color:var(--muted)}
.toc-list{list-style:none}
.toc-list a{display:block;padding:5px 16px;font-size:14px;color:#646A73;text-decoration:none;line-height:22px;transition:background .1s,color .1s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.toc-list a:hover{background:var(--hover);color:var(--fg)}
.toc-list a.active{background:var(--brand-bg);color:var(--brand);font-weight:500}
.toc-list a.lvl-3{padding-left:36px;font-size:13px;color:#8F959E}
.doc{flex:1;display:flex;justify-content:center;padding:0 40px 160px;min-width:0}
.doc-inner{max-width:var(--doc-w);width:100%;min-width:0}
.cover{margin:0 -40px 20px;overflow:hidden;border-radius:0 0 12px 12px;position:relative}
.cover img{width:100%;display:block;max-height:240px;object-fit:cover}
.cover .overlay{position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,rgba(0,0,0,.35));display:flex;align-items:flex-end;padding:24px 40px}
.cover .overlay h1{color:#FFF;font-size:26px;font-weight:700;text-shadow:0 1px 4px rgba(0,0,0,.4)}
h1{font-size:28px;font-weight:700;color:var(--fg);letter-spacing:-.3px;line-height:1.35}
h2{font-size:21px;font-weight:600;color:var(--fg);margin:2.4em 0 .6em;padding-bottom:8px;border-bottom:1px solid var(--border)}
h3{font-size:17px;font-weight:600;color:var(--fg);margin:1.8em 0 .4em}
.meta{font-size:13px;color:var(--muted);margin:0 0 24px;display:flex;align-items:center;gap:6px}
p{margin:.6em 0;color:var(--fg);line-height:1.75}
ul,ol{margin:.6em 0;color:var(--fg);padding-left:24px}
li{margin:.3em 0;line-height:1.7}
strong{color:var(--fg);font-weight:600}
code{background:var(--code-bg);padding:2px 6px;border-radius:4px;font:13px/1.5 "SF Mono",Menlo,monospace;color:var(--code-fg)}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}
.callout{background:var(--callout-bg);border:1px solid var(--callout-border);border-radius:8px;padding:14px 18px;margin:1em 0;font-size:14px;color:#595959;line-height:1.7;position:relative;overflow:hidden}
.callout::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:#FFD591;border-radius:8px 0 0 8px}
.table-wrap{overflow-x:auto;margin:1em 0;border-radius:8px;border:1px solid var(--border)}
table{border-collapse:collapse;width:100%;font-size:14px}
th{background:var(--hover);color:var(--fg);font-weight:600;text-align:left;padding:10px 14px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:10px 14px;border-bottom:1px solid var(--border);color:#333}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:#FAFBFC}
.gal-toggle{appearance:none;border:1px solid var(--border);background:#FFF;color:var(--fg);padding:10px 20px;border-radius:8px;font:14px inherit;cursor:pointer;margin:2.5em 0 1em}
.gal-toggle:hover{border-color:var(--brand);color:var(--brand)}
.gallery{display:none;columns:3;column-gap:12px;margin:1em 0}
.gallery.open{display:block}
.gallery figure{break-inside:avoid;margin:0 0 12px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:#FFF}
.gallery figure:hover{box-shadow:0 2px 12px rgba(0,0,0,.08)}
.gallery img{width:100%;display:block;cursor:zoom-in}
.gallery figcaption{padding:6px 10px;font-size:12px;color:var(--muted);border-top:1px solid var(--border)}
.lightbox{position:fixed;inset:0;background:rgba(255,255,255,.97);display:none;align-items:center;justify-content:center;z-index:99;cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:92vw;max-height:90vh;border-radius:8px;box-shadow:0 4px 30px rgba(0,0,0,.12)}
@media(max-width:960px){.toc{position:fixed;left:-280px;top:56px;height:calc(100vh - 56px);z-index:15;background:#FFF;box-shadow:2px 0 12px rgba(0,0,0,.08);transition:left .2s}.toc.show{left:0}.doc{padding:0 16px 100px}.cover{margin:0 -16px 16px}.gallery{columns:2}.topbar .menu-btn{display:block}}
@media(max-width:500px){.gallery{columns:1}h1{font-size:24px}h2{font-size:18px}h3{font-size:16px}.table-wrap{font-size:13px}th,td{padding:8px 10px}}
"""


def _build_page(data: dict) -> str:
    """Build the HTML page from database query results."""
    doc = data["document"]
    sections = data["sections"]
    images = data.get("images", [])

    # Build TOC (h2 + h3 with parent tracking)
    toc_items = []
    body_parts = []

    # Cover
    cover_html = ""
    if doc.get("cover_media"):
        cover_html = (
            f'<div class="cover"><img src="{doc["cover_media"]}" alt="封面">'
            f'<div class="overlay"><h1>{html_mod.escape(doc["title"])}</h1></div></div>'
        )
        h1_html = ""
    else:
        h1_html = f"<h1>{html_mod.escape(doc['title'])}</h1>"

    # Date
    updated = doc.get("updated_at")
    date_str = f"{updated.month}月{updated.day}日" if updated else ""

    # Sections
    h2_idx = 0
    section_map = {}
    for sec in sections:
        sec_id = sec["id"]
        if sec["level"] == 2:
            anchor = f"s2-{h2_idx}"
            h2_idx += 1
            toc_items.append(f'<li><a href="#{anchor}" data-target="{anchor}" class="lvl-2">{html_mod.escape(sec["title"])}</a></li>')
            callout_html = f'<div class="callout">{_inline(sec["callout"])}</div>' if sec.get("callout") else ""
            body_html = _render_body(sec.get("body", ""))
            body_parts.append(f'<h2 id="{anchor}">{html_mod.escape(sec["title"])}</h2>{callout_html}{body_html}')
            section_map[sec_id] = anchor
        elif sec["level"] == 3:
            parent_anchor = section_map.get(sec.get("parent_id"), "")
            anchor = f"{parent_anchor}-{sec['sort_order']}" if parent_anchor else f"s3-{sec['sort_order']}"
            toc_items.append(f'<li><a href="#{anchor}" data-target="{anchor}" class="lvl-3">{html_mod.escape(sec["title"])}</a></li>')
            callout_html = f'<div class="callout">{_inline(sec["callout"])}</div>' if sec.get("callout") else ""
            body_html = _render_body(sec.get("body", ""))
            body_parts.append(f'<h3 id="{anchor}">{html_mod.escape(sec["title"])}</h3>{callout_html}{body_html}')

    # Gallery
    gallery_html = ""
    if images:
        figs = "".join(
            f'<figure><img src="{img["media_url"]}" loading="lazy" alt="{html_mod.escape(img.get("alt_text",""))}" onclick="lb(this.src)">'
            f"<figcaption>{html_mod.escape(img['filename'])}</figcaption></figure>"
            for img in images
        )
        gallery_html = (
            f'<button class="gal-toggle" onclick="var g=document.getElementById(\'gal\');g.classList.toggle(\'open\');'
            f'this.textContent=g.classList.contains(\'open\')?\'收起配图\':\'展开全部 {len(images)} 张配图\'">'
            f'展开全部 {len(images)} 张配图</button>\n<div class="gallery" id="gal">{figs}</div>'
        )

    toc_html = "".join(toc_items)
    body_html = "\n".join(body_parts)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_mod.escape(doc['title'])}</title>
<link rel="stylesheet" href="/guide/creation.css">
</head>
<body>
<header class="topbar">
<button class="btn menu-btn" onclick="document.getElementById('toc').classList.toggle('show')">☰</button>
<a class="logo" href="/"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V4h6l3 3h9v12H3V7h18M16 13h7M20 10v6"/></svg>VSC 工作台</a>
<span class="crumb">› <a href="/">首页</a> › {html_mod.escape(doc['title'])}</span>
<button class="btn" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="回到顶部">↑</button>
</header>
<div class="main">
<nav class="toc" id="toc">
<div class="toc-head"><span>目录</span></div>
<ul class="toc-list">{toc_html}</ul>
</nav>
<main class="doc"><div class="doc-inner">
{cover_html}{h1_html}
<div class="meta">最近修改：{date_str}</div>
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
    """递归转换 UUID/datetime 为 JSON 可序列化类型。"""
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
            raise HTTPException(404, "指引文档不在数据库中；请先运行种子导入")
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

    @app.get("/creation-guide-media/{name}")
    def guide_media(name: str):
        safe = Path(name).name
        for sub in ("images/doc", "images"):
            candidate = root() / sub / safe
            if candidate.is_file() and candidate.suffix in MEDIA_TYPES:
                return FileResponse(candidate, media_type=MEDIA_TYPES[candidate.suffix])
        raise HTTPException(404, "配图不在本机")
