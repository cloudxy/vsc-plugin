"""Real offline media conversions; no provider, database or approval side effects."""
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from support.paths import ROOT
from support.fixtures.media import production_media
from vsc.assets.resource_service import ResourceError
from vsc.post.previews import PreviewConverter, RECIPE_VERSION


def fixture_pdf():
    stream = b"BT /F1 14 Tf 20 90 Td (Preview fixture) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 220 140] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    result, positions = b"%PDF-1.4\n", [0]
    for index, content in enumerate(objects, 1):
        positions.append(len(result))
        result += str(index).encode() + b" 0 obj\n" + content + b"\nendobj\n"
    xref = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(("%010d 00000 n \n" % offset).encode() for offset in positions[1:])
    return result + b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"


class PreviewConversionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires installed FFmpeg")
    def test_image_video_audio_conversions_keep_original_bytes_and_record_recipe(self):
        from vsc.adapters.media.qa import LocalProbeAdapter
        samples = production_media()
        converter = PreviewConverter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for purpose, key, modality, mime in [("thumbnail", "png", "image", "image/png"), ("poster", "mp4", "video", "video/mp4"),
                    ("waveform", "wav", "audio", "audio/wav"), ("proxy_video", "mp4", "video", "video/mp4")]:
                with self.subTest(purpose=purpose):
                    source = root / ("source." + key)
                    source.write_bytes(samples[key])
                    sha = hashlib.sha256(samples[key]).hexdigest()
                    output, evidence = converter.convert(source, {"modality": modality, "mime_type": mime, "sha256": sha}, purpose, root)
                    self.assertEqual(source.read_bytes(), samples[key])
                    self.assertEqual(evidence["source_sha256"], sha)
                    self.assertEqual(evidence["recipe_version"], RECIPE_VERSION)
                    self.assertIn("ffmpeg version", evidence["tool_version"])
                    probe = LocalProbeAdapter().probe(output)
                    self.assertTrue(probe["streams"])
                    if purpose == "waveform":
                        video = next(row for row in probe["streams"] if row["codec_type"] == "video")
                        self.assertEqual((video["width"], video["height"]), (1200, 240))

    @unittest.skipUnless(shutil.which("pdftoppm"), "requires installed Poppler")
    def test_pdf_first_page_uses_real_converter_and_no_embedded_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            content = fixture_pdf()
            source.write_bytes(content)
            output, evidence = PreviewConverter().convert(source, {"modality": "document", "mime_type": "application/pdf", "sha256": hashlib.sha256(content).hexdigest()}, "document_pages", root)
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(evidence["parameters"]["page"], 1)
            self.assertEqual(source.read_bytes(), content)

    def test_missing_converter_and_wrong_recipe_have_explicit_gaps(self):
        converter = PreviewConverter()
        converter.ffmpeg = None
        media = {"modality": "image", "sha256": "a" * 64}
        with self.assertRaises(ResourceError) as missing:
            converter.convert("unused", media, "thumbnail", ".")
        self.assertEqual(missing.exception.code, "preview_tool_unavailable")
        with self.assertRaises(ResourceError) as recipe:
            converter.convert("unused", media, "thumbnail", ".", "uninstalled-v2")
        self.assertEqual(recipe.exception.code, "preview_recipe_unavailable")
