"""Synthetic Office/PDF byte fixtures for source intake tests."""
import io
import zipfile


def office_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def docx_bytes():
    return office_bytes({"word/document.xml": '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
    <w:p><w:r><w:t>SC1</w:t></w:r></w:p><w:p><w:r><w:t>Alice: Hello</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>He walks away.</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    </w:body></w:document>'''})


def xlsx_bytes():
    return office_bytes({
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Script" sheetId="1" r:id="r1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="2"><c r="A2" t="inlineStr"><is><t>SC1</t></is></c><c r="B2" t="inlineStr"><is><t>Alice</t></is></c><c r="C2" t="inlineStr"><is><t>Hello</t></is></c></row></sheetData></worksheet>'})


def pdf_bytes(text="SC1\\nAlice: Hello"):
    # Minimal valid one-page PDF, with a real xref table; no external library.
    content = b"BT /F1 12 Tf 50 750 Td (" + text.encode().replace(b"\\n", b") Tj 0 -20 Td (") + b") Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    raw, positions = b"%PDF-1.4\n", [0]
    for number, obj in enumerate(objects, 1):
        positions.append(len(raw))
        raw += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    offset = len(raw)
    raw += b"xref\n0 6\n0000000000 65535 f \n"
    raw += b"".join((f"{position:010d} 00000 n \n").encode() for position in positions[1:])
    return raw + b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(offset).encode() + b"\n%%EOF\n"


