"""Real deterministic TXT, OOXML, tabular and media-package exports."""
import csv
import html
import io
import json
import re
import shutil
import zipfile
from pathlib import PurePosixPath
from xml.sax.saxutils import escape

from vsc.assets.resource_service import ResourceError


def tool_of(document):
    return document.get("tool") if document.get("format")=="vsc.text-tool-bundle/v1" else document.get("format","").split("/")[-2]


def documents(document):
    if document.get("format")=="vsc.text-tool-bundle/v1":
        return [(row["title"],row["document"]) for row in document["units"]]
    return [("",document)]


def paragraphs(document,timestamps=False,view='translation'):
    if document.get("format")=="vsc.text-tool-bundle/v1":
        lines=[document.get("title","")]
        for title,doc in documents(document):lines.extend([title,*paragraphs(doc,timestamps,view)])
        return lines
    tool=tool_of(document)
    if tool=="novel":return [document.get("body","")]
    if tool=="translation":
        if view=='source':return [document.get('source_text','')]
        if view=='bilingual':return ['原文',document.get('source_text',''),'译文',document.get('body','')]
        terms=["术语："+r["source"]+" → "+r["target"]+("（"+r["aliases"]+"）" if r["aliases"] else "") for r in document["terms"]]
        return [*terms,document.get("body","")]
    if tool=="scoring":
        return [document.get("analysis",""),*[(r["key"]+"："+str(r["score"])+"；"+r["evidence"]+"；"+r["reason"]) for r in document["scores"]]]
    if tool=="breakdown":
        return [((timecode(r["start_ms"])+" --> "+timecode(r["end_ms"])+" ") if timestamps else "")+r["text"] for r in document["observations"]]+([document["body"]] if document.get("body") else [])
    if tool=="qc":return [r["severity"]+" "+r["code"]+" "+r["message"]+" "+r["evidence"] for r in document["issues"]]
    if tool=="overseas":return [document.get("understanding",""),document.get("body",""),*[r["localized_text"] for r in document["segments"]]]
    raise ResourceError("未知文本工具格式")


def timecode(ms):
    seconds,milli=divmod(ms,1000);minutes,second=divmod(seconds,60);hour,minute=divmod(minutes,60)
    return f"{hour:02}:{minute:02}:{second:02}.{milli:03}"


def _put(z,name,value):
    info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
    z.writestr(info,value)


def _docx(lines):
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w") as z:
        _put(z,"[Content_Types].xml",'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        _put(z,"_rels/.rels",'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        body="".join('<w:p><w:r><w:t xml:space="preserve">'+escape(line)+'</w:t></w:r></w:p>' for paragraph in lines for line in str(paragraph).split("\n"))
        _put(z,"word/document.xml",'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')
    return out.getvalue()


def report_rows(document):
    tool=tool_of(document)
    if tool=="scoring":
        rows=[["单元","标准","分数","满分","权重","证据","理由","人工复核","复核理由","运行","输入版本","类型","频道","首卡起行","首卡末行","首卡正文","风险分","质量分","置信度","分析"]]
        for title,doc in documents(document):
            criteria={r["key"]:r for r in doc["criteria"]}
            runs=doc.get('runs') or [{'id':'当前人工稿','input_version_id':doc.get('fixed_version_id',''),'card':doc.get('card',{}),'result':{'patch':doc}}]
            for run in runs:
                patch=(run.get('result') or {}).get('patch',{})
                for score in patch.get('scores',[]):
                    c=criteria.get(score['key'],{'label':score['key'],'max_score':'','weight':''});card=run.get('card',{})
                    rows.append([title,c['label'],score['score'],c['max_score'],c['weight'],score['evidence'],score['reason'],doc['review_decision'],doc['review_reason'],run['id'],run['input_version_id'],doc.get('category',''),doc['channel'],card.get('start_line',''),card.get('end_line',''),card.get('text',''),patch.get('risk_score',''),patch.get('quality_score',''),patch.get('confidence',''),patch.get('analysis','')])
        return rows
    rows=[["单元","媒体","开始毫秒","结束毫秒","级别","检查项","问题","证据","原字幕","建议字幕","人工处理","处理理由","规则版本"]]
    for title,doc in documents(document):
        decisions={r['issue_index']:r for r in doc.get('review_decisions',[])}
        for index,row in enumerate(doc.get("issues",[])):
            decision=decisions.get(index,{})
            rows.append([title,row["media_id"],row["start_ms"],row["end_ms"],row["severity"],row["code"],row["message"],row["evidence"],row.get('original_subtitle',''),row.get('suggested_subtitle',''),decision.get('decision','open'),decision.get('reason',''),row.get('rule_version','')])
    return rows


def _xlsx(rows,images=()):
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w") as z:
        _put(z,"[Content_Types].xml",'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'+('<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>' if images else '')+'</Types>')
        _put(z,"_rels/.rels",'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        _put(z,"xl/workbook.xml",'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>')
        _put(z,"xl/_rels/workbook.xml.rels",'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        cells=[]
        for i,row in enumerate(rows,1):
            values=[]
            for j,value in enumerate(row):
                ref=chr(65+j)+str(i)
                values.append('<c r="'+ref+'"><v>'+str(value)+'</v></c>' if type(value) in (int,float) else '<c r="'+ref+'" t="inlineStr"><is><t xml:space="preserve">'+escape(str(value))+'</t></is></c>')
            cells.append('<row r="'+str(i)+'">'+"".join(values)+'</row>')
        _put(z,"xl/worksheets/sheet1.xml",'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetData>'+"".join(cells)+'</sheetData>'+('<drawing r:id="rId1"/>' if images else '')+'</worksheet>')
        if images:
            _put(z,'xl/worksheets/_rels/sheet1.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>')
            drawings=[];relations=[]
            for index,(row,raw) in enumerate(images,1):
                _put(z,'xl/media/evidence'+str(index)+'.png',raw)
                relations.append('<Relationship Id="rId'+str(index)+'" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/evidence'+str(index)+'.png"/>')
                drawings.append('<xdr:oneCellAnchor><xdr:from><xdr:col>13</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>'+str(row)+'</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="2286000" cy="1285875"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="'+str(index)+'" name="Evidence '+str(index)+'"/><xdr:cNvPicPr/></xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId'+str(index)+'"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor>')
            _put(z,'xl/drawings/drawing1.xml','<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'+''.join(drawings)+'</xdr:wsDr>')
            _put(z,'xl/drawings/_rels/drawing1.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(relations)+'</Relationships>')
    return out.getvalue()


def export_document(document,format,media_loader=None,view='translation'):
    from vsc.assets.text_tools import TOOLS
    tool=tool_of(document)
    if tool not in TOOLS or format not in TOOLS[tool]["formats"]:raise ResourceError("此工具不支持所选导出格式")
    if view not in {'source','translation','bilingual'}:raise ResourceError('导出内容须为原文、译文或双语')
    if format=='json':
        if tool=='translation' and view in {'source','bilingual'}:
            document={'format':'vsc.translation-export/v1','view':view,'units':[{'title':title,'source_text':doc.get('source_text',''),**({'body':doc.get('body',''),'terms':doc.get('terms',[]),'characters':doc.get('translation_characters',[])} if view=='bilingual' else {})} for title,doc in documents(document)]}
        return json.dumps(document,ensure_ascii=False,indent=2).encode(),"application/json","report.json"
    if format in {"txt","timestamp-txt"}:return "\n".join(paragraphs(document,format=="timestamp-txt",view)).encode(),"text/plain; charset=utf-8","report.txt"
    if format=="docx":return _docx(paragraphs(document,view=view)),"application/vnd.openxmlformats-officedocument.wordprocessingml.document","report.docx"
    rows=report_rows(document)
    images=[];offset=1;total_images=0
    if format in {'xlsx','zip'}:
        for _,doc in documents(document):
            for ref in doc.get('evidence_images',[]):
                path,media=media_loader(ref['media_id'])
                if media['sha256']!=ref['sha256']:raise ResourceError('固定证据图片摘要不符')
                raw=path.read_bytes();total_images+=len(raw)
                if total_images>32*1024*1024:raise ResourceError('嵌入证据图片超过32MiB，请拆分报告')
                if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ResourceError('报告证据须为实际PNG帧')
                images.append((offset+ref['issue_index'],raw))
            offset+=len(doc.get('issues',[]))
    if format=="csv":
        out=io.StringIO();writer=csv.writer(out)
        for row in rows:writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in row])
        return ("\ufeff"+out.getvalue()).encode(),"text/csv; charset=utf-8","report.csv"
    if format=="html":
        body="<table>"+"".join("<tr>"+"".join("<th>"+html.escape(str(v))+"</th>" if i==0 else "<td>"+html.escape(str(v))+"</td>" for v in row)+"</tr>" for i,row in enumerate(rows))+"</table>"
        return ('<!doctype html><html lang="zh"><meta charset="utf-8"><title>VSC工具报告</title><style>body{font:16px system-ui;margin:2rem}table{border-collapse:collapse}th,td{padding:.6rem;border:1px solid #aaa;text-align:left;white-space:pre-wrap}</style><h1>VSC工具报告</h1>'+body+"</html>").encode(),"text/html; charset=utf-8","report.html"
    if format=="xlsx":return _xlsx(rows,images),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","report.xlsx"
    if format=="zip":
        out=io.BytesIO();total=0
        with zipfile.ZipFile(out,"w") as z:
            _put(z,"report.json",json.dumps(document,ensure_ascii=False,indent=2).encode())
            _put(z,"report.xlsx",_xlsx(rows,images))
            for index,(title,doc) in enumerate(documents(document),1):
                for vno,video in enumerate(doc["videos"],1):
                    path,media=media_loader(video["media_id"]);total+=path.stat().st_size
                    if total>256*1024*1024:raise ResourceError("单次ZIP已超过256MiB，请分批下载")
                    name=PurePosixPath(media["name"].replace("\\","/")).name
                    name=re.sub(r"[^\w.\-\u4e00-\u9fff]","_",name)[:150] or "video.mp4"
                    info=zipfile.ZipInfo(f"{index:03}/videos/{vno:03}-{name}",date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_STORED
                    with z.open(info,"w") as target,open(path,"rb") as source:shutil.copyfileobj(source,target)
                for sno,subtitle in enumerate(doc["subtitles"],1):_put(z,f"{index:03}/subtitles/{sno:03}."+PurePosixPath(subtitle['filename']).suffix.lstrip('.'),subtitle["text"].encode())
        return out.getvalue(),"application/zip","report.zip"
    raise ResourceError("导出格式未实现")
