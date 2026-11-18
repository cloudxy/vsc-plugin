"""Creation plaza: database-backed boards, articles and a reply slot.

The page uses the workbench dark surfaces. Articles stay readable; boards can
receive later posts without turning the index into one flat document list.
"""
import html as html_mod
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".svg": "image/svg+xml", ".avif": "image/avif",
               ".mp4": "video/mp4", ".webm": "video/webm"}


def guides_root(root=None):
    from vsc.configuration import get_config
    media = root if root is not None else get_config("VSC_MEDIA_ROOT")
    if isinstance(media, (str, Path)) and str(media).strip():
        base = Path(str(media)).expanduser().parent / "guides"
        if base.is_dir():
            return base
    fallback = Path(__file__).resolve().parents[4] / "assets" / "guides"
    return fallback


def _inline(s):
    s = html_mod.escape(s, quote=True)
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
        video = re.fullmatch(r'\[video:([^\]]+)\]\((/creation-guide-media/[^)]+)\)', stripped)
        if video:
            close_lists()
            out.append('<figure class="guide-video"><video controls preload="metadata" src="'+html_mod.escape(video[2], quote=True)+'"></video><figcaption>'+html_mod.escape(video[1])+'</figcaption></figure>')
        elif stripped.startswith("> "):
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
        elif stripped.endswith(".mp4") or stripped.endswith(".webm"):
            close_lists()
            name = Path(stripped).name
            src = "/creation-guide-media/" + quote(name)
            out.append(
                f'<figure class="guide-video"><video controls preload="metadata" src="{html_mod.escape(src)}"></video>'
                f"<figcaption>{html_mod.escape(name)}</figcaption></figure>"
            )
        elif stripped:
            close_lists()
            out.append(f"<p>{_inline(stripped)}</p>")
        else:
            close_lists()
    close_lists()
    if in_table: out.append("</tbody></table></div>")
    return "\n".join(out)


PAGE_CSS = """
:root{--bg:#0b080b;--fg:#fdfbfc;--muted:#a1a0a3;--hover:#292929;--brand:#74ff53;
--brand-bg:#1d1d1d;--border:#343435;--callout-bg:#343029;--callout-border:#6b5424;
--code-bg:#1d1d1d;--code-fg:#c5ff8b;--toc-w:260px;--doc-w:780px;--surface:#131313}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:72px}
body{background:var(--bg);color:var(--fg);font:14px/1.7 "PingFang SC",-apple-system,BlinkMacSystemFont,"Microsoft YaHei",Arial,sans-serif}
a{color:var(--fg);text-decoration:none}a:hover{color:var(--brand)}

.topbar{position:sticky;top:0;height:50px;background:var(--bg);
border-bottom:1px solid var(--border);display:flex;align-items:center;
padding:0 16px 0 0;gap:12px;z-index:20}
.brand{width:218px;height:50px;flex:none;display:flex;align-items:center;gap:7px;
padding:0 16px;background:var(--surface);border-right:1px solid var(--border);color:var(--fg)}
.brand strong{font-size:16px;font-weight:600}.brand span{font-size:14px;font-weight:500}
.brand-mark{width:24px;height:26px;display:grid;place-items:center;background:var(--brand);
color:#101810;font-size:18px;font-weight:900}
.shell-title{color:var(--muted);font-size:13px}
.topbar .crumb{font-size:13px;color:var(--muted);flex:1;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap;display:flex;align-items:center;gap:4px}
.topbar .crumb a{color:var(--muted);text-decoration:none}
.topbar .crumb a:hover{color:var(--brand);text-decoration:none}
.topbar .crumb .sep{color:#DEE0E3;font-size:11px}
.topbar .crumb .current{color:var(--fg);font-weight:500}
.topbar .btn{background:none;border:none;color:var(--muted);font-size:16px;
cursor:pointer;padding:4px 8px;border-radius:4px;flex-shrink:0;line-height:1}
.topbar .btn:hover{background:var(--hover);color:var(--fg)}
.topbar .menu-btn{display:none}

/* ── 布局 ── */
.main{display:flex;min-height:calc(100vh - 50px)}

/* ── 目录（飞书样式：浅灰底+紧凑行距+折叠） ── */
.toc{width:var(--toc-w);flex-shrink:0;position:sticky;top:50px;
height:calc(100vh - 50px);overflow-y:auto;background:var(--surface);
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
.toc-list a{display:block;padding:3px 12px;font-size:13px;color:var(--muted);
text-decoration:none;line-height:20px;transition:background .08s,color .08s;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:4px;margin:0 4px}
.toc-list a:hover{background:var(--hover);color:var(--fg)}
.toc-list a.active{background:var(--brand-bg);color:var(--brand);font-weight:500}
.toc-list a.lvl-2{font-size:13px;padding-left:12px}
.toc-list a.lvl-3{padding-left:28px;font-size:12px;color:#8F959E}
.toc-list a.lvl-4{padding-left:44px;font-size:12px;color:#8F959E}
.toc-list a.lvl-5{padding-left:58px;font-size:12px;color:#8F959E}
.toc-list a.lvl-6{padding-left:72px;font-size:12px;color:#8F959E}

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
h4{font-size:15px;font-weight:600;color:var(--fg);margin:1.3em 0 .25em}
h5{font-size:14px;font-weight:600;color:var(--fg);margin:1.1em 0 .2em}
h6{font-size:13px;font-weight:600;color:var(--fg);margin:1em 0 .2em}

/* ── 正文 ── */
p{margin:.5em 0;color:var(--fg);line-height:1.75}
ul,ol{margin:.5em 0;color:var(--fg);padding-left:20px}
li{margin:.2em 0;line-height:1.7}
strong{color:var(--fg);font-weight:600}
code{background:var(--code-bg);padding:1px 5px;border-radius:3px;
font:13px/1.5 "SF Mono",Menlo,monospace;color:var(--code-fg)}
.doc a{color:var(--brand)}
.doc a:hover{text-decoration:underline}

/* ── Callout（飞书样式） ── */
.callout{background:var(--callout-bg);border:1px solid var(--callout-border);
border-radius:6px;padding:10px 14px;margin:.8em 0;font-size:13px;
color:#f1dcb3;line-height:1.65}

/* ── 内嵌图片 ── */
.inline-img{max-width:100%;min-width:200px;height:auto;border-radius:8px;
border:1px solid var(--border);margin:12px auto;display:block;cursor:zoom-in;
box-shadow:0 2px 8px rgba(0,0,0,.06);transition:box-shadow .15s}
.inline-img:hover{box-shadow:0 4px 16px rgba(0,0,0,.12)}
.guide-video{margin:12px 0}
.guide-video video{width:100%;border-radius:8px;background:#111}
.guide-video figcaption{font-size:12px;color:var(--muted);margin-top:4px}
.plaza{max-width:1180px;margin:0 auto;padding:8px 24px 48px}
.plaza>h1{font-size:32px;line-height:1.4;font-weight:500;margin:4px 0 8px}
.lede{color:var(--muted);margin:0 0 28px}
.board{margin:0 0 36px}
.board-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin:0 0 8px}
.board-head h2{margin:0;border:0;font-size:18px;font-weight:500;padding:0}
.board-head span{color:var(--muted);font-size:12px}
.board>.hint{color:var(--muted);margin:0 0 16px}
.plaza-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px 8px}
.plaza-card{display:block;min-width:0;color:var(--fg)}
.plaza-card:hover{color:var(--fg);text-decoration:none}
.plaza-cover{display:block;aspect-ratio:16/9;border-radius:8px;background:
linear-gradient(160deg,#1d1d1d,#292929 60%,#1a2416);border:1px solid #303030;overflow:hidden}
.plaza-cover img{width:100%;height:100%;object-fit:cover}
.plaza-card strong{display:block;margin:10px 0 3px;font-size:14px;font-weight:400;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.plaza-card small{color:#777;font-size:12px}
.plaza-empty{min-height:160px;display:grid;place-items:center;color:#777;
border:1px dashed #343435;border-radius:12px}
.replies{margin-top:48px;padding-top:20px;border-top:1px solid var(--border)}
.replies h2{border:0;font-size:18px}
.reply{padding:12px 0;border-bottom:1px solid var(--border)}
.reply p{margin:4px 0 0}
.reply small{color:var(--muted)}

/* ── 表格 ── */
.table-wrap{overflow-x:auto;margin:.8em 0;border-radius:6px;border:1px solid var(--border)}
table{border-collapse:collapse;width:100%;font-size:13px}
th{background:var(--hover);color:var(--fg);font-weight:600;text-align:left;
padding:8px 12px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--fg)}
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
.lightbox{position:fixed;inset:0;background:rgba(11,8,11,.96);display:none;
align-items:center;justify-content:center;z-index:99;cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:92vw;max-height:90vh;border-radius:6px;
box-shadow:0 4px 24px rgba(0,0,0,.1)}

/* ── 响应式 ── */
@media(max-width:960px){
  .toc{position:fixed;left:-260px;top:50px;height:calc(100vh - 50px);z-index:15;
  background:var(--surface);box-shadow:2px 0 10px rgba(0,0,0,.4);transition:left .2s}
  .plaza-grid{grid-template-columns:1fr}
  .brand{width:auto;border-right:0;background:transparent}
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

    toc_items = []
    body_parts = []
    heading = {2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6"}
    for sec in sections:
        level = sec["level"]
        if level == 0:
            body_parts.append(_render_body(sec.get("body", "")))
            continue
        tag = heading.get(level)
        if not tag:
            continue
        anchor = f"s{level}-{sec['sort_order']}"
        toc_items.append(
            f'<li><a href="#{anchor}" data-target="{anchor}" class="lvl-{level}">{html_mod.escape(sec["title"])}</a></li>'
        )
        callout_html = f'<div class="callout">{_inline(sec["callout"])}</div>' if sec.get("callout") else ""
        body_html = _render_body(sec.get("body", ""))
        body_parts.append(f'<{tag} id="{anchor}">{html_mod.escape(sec["title"])}</{tag}>{callout_html}{body_html}')

    cover_url = doc.get('cover_media') or ''
    cover_html = '<div class="cover"><img src="'+html_mod.escape(cover_url, quote=True)+'" alt="封面"></div>' if cover_url.startswith('/creation-guide-media/') else ''

    updated = doc.get("updated_at")
    date_str = f"{updated.month}月{updated.day}日" if hasattr(updated, "month") else str(updated or "")[:10] if updated else ""

    title = html_mod.escape(doc["title"])
    toc_html = "".join(toc_items)
    body_html = "\n".join(body_parts)
    replies_html = _replies_html(data.get("replies") or [])

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
<a class="brand" href="/"><span class="brand-mark">V</span><strong>VSC</strong><span>创作工作台</span></a>
<button class="btn menu-btn" onclick="document.getElementById('toc').classList.toggle('show')" aria-label="目录">☰</button>
<span class="crumb">
<a href="/guide">学习广场</a><span class="sep">›</span><span class="current">{title}</span>
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
<div class="breadcrumb"><a href="/guide">学习广场</a><span class="sep">›</span><span>{title}</span></div>
<h1>{title}</h1>
<div class="meta"><span>最近修改：{date_str}</span><span class="dot">·</span><span>{len(toc_items)} 个章节</span></div>
</div>
{cover_html}
{body_html}
{replies_html}
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
document.querySelectorAll('h2[id^="s"],h3[id^="s"],h4[id^="s"],h5[id^="s"],h6[id^="s"]').forEach(function(h){{obs.observe(h)}});
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


def _date_label(updated):
    if hasattr(updated, "month"):
        return f"{updated.month}月{updated.day}日"
    return str(updated or "")[:10]


def _replies_html(replies):
    if not replies:
        return '<section class="replies" aria-label="回复"><h2>回复</h2><p class="plaza-empty">还没有回复。讨论会接在这篇正文下面。</p></section>'
    items = []
    for reply in replies:
        author = html_mod.escape(reply.get("author_label") or "成员")
        when = html_mod.escape(_date_label(reply.get("created_at")))
        body = _render_body(reply.get("body") or "")
        items.append(f'<article class="reply"><small>{author} · {when}</small>{body}</article>')
    return '<section class="replies" aria-label="回复"><h2>回复</h2>' + "\n".join(items) + "</section>"


def _build_plaza(boards):
    sections = []
    for board in boards:
        docs = board.get("documents") or []
        title = html_mod.escape(board.get("title") or "")
        summary = html_mod.escape(board.get("summary") or "")
        if docs:
            cards = []
            for doc in docs:
                slug = html_mod.escape(doc["slug"])
                cover = doc.get("cover_media") or ""
                cover_html = (f'<img src="{html_mod.escape(cover, quote=True)}" alt="" loading="lazy">'
                              if cover.startswith("/creation-guide-media/") else "")
                cards.append(
                    f'<a class="plaza-card" href="/guide/{slug}">'
                    f'<span class="plaza-cover">{cover_html}</span>'
                    f'<strong>{html_mod.escape(doc["title"])}</strong>'
                    f'<small>最近修改：{html_mod.escape(_date_label(doc.get("updated_at")))}</small></a>'
                )
            grid = f'<div class="plaza-grid">{"".join(cards)}</div>'
        else:
            grid = '<p class="plaza-empty">这个板块还没有内容。</p>'
        sections.append(
            f'<section class="board"><div class="board-head"><h2>{title}</h2>'
            f'<span>{len(docs)} 篇</span></div><p class="hint">{summary}</p>{grid}</section>'
        )
    body = "\n".join(sections) or '<p class="plaza-empty">还没有板块。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>学习广场</title>
<link rel="stylesheet" href="/guide/creation.css">
</head>
<body>
<header class="topbar">
<a class="brand" href="/"><span class="brand-mark">V</span><strong>VSC</strong><span>创作工作台</span></a>
<span class="shell-title">学习广场</span>
</header>
<main class="plaza">
<h1>学习广场</h1>
<p class="lede">按板块浏览说明和讨论。打开一篇后按章节阅读，回复接在正文下面。</p>
{body}
</main>
</body></html>"""


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

    @app.get("/guide", response_class=HTMLResponse)
    def guide_list():
        docs = store().list_documents()
        if any(doc['slug'] == 'tiangong-guide' for doc in docs):
            docs = [doc for doc in docs if doc['slug'] != 'creation-guide']
        boards = store().list_boards()
        grouped = {board["slug"]: [] for board in boards}
        unplaced = []
        for doc in docs:
            grouped.get(doc.get("board_slug"), unplaced).append(doc)
        order = lambda doc: (doc["slug"] != "tiangong-guide", doc.get("title") or "")
        for items in grouped.values():
            items.sort(key=order)
        unplaced.sort(key=order)
        page = [{"title": board["title"], "summary": board["summary"], "documents": grouped[board["slug"]]}
                for board in boards]
        if unplaced:
            page.append({"title": "未分板块", "summary": "还没有归入板块的文章。", "documents": unplaced})
        return HTMLResponse(_build_plaza(page))

    @app.get("/guide/creation", response_class=HTMLResponse)
    def guide_page():
        data = store().get_document("tiangong-guide") or store().get_document("creation-guide")
        if not data:
            raise HTTPException(404, "指引文档不在数据库中")
        return HTMLResponse(_build_page(data))

    @app.get("/guide/creation.css")
    def guide_css():
        return PlainTextResponse(PAGE_CSS, media_type="text/css; charset=utf-8")

    @app.get("/guide/{slug}", response_class=HTMLResponse)
    def guide_detail(slug: str):
        data = store().get_document(slug)
        if not data:
            raise HTTPException(404, "文档不存在")
        return HTMLResponse(_build_page(data))

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
        for sub in ("videos", "images/full", "images/doc", "images"):
            base = root().resolve()
            candidate = (base / sub / safe).resolve()
            if not candidate.is_relative_to(base):
                continue
            if candidate.is_file() and candidate.suffix in MEDIA_TYPES:
                return FileResponse(candidate, media_type=MEDIA_TYPES[candidate.suffix])
        raise HTTPException(404, "配图不在本机")
