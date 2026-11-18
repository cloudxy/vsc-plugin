"""Guide source projection and actual list/detail/media route consumers."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import support.paths
from tools.maintenance.guide_capture import project_capture, block_text
from vsc.interfaces.web.creation_guide import install_creation_guide_routes, _build_page


def source_text(text):
    return {'initialAttributedTexts': {'text': {'0': text}, 'attribs': {'0': ''}}}


class CreationGuideTests(unittest.TestCase):
    def test_source_tree_preserves_deep_headings_and_body_once(self):
        records = {'root':dict(type='page',text=source_text('天工工作台说明'),children=['intro','top','deep','image','file']),
            'intro':dict(type='text',text=source_text('原始前言')),
            'top':dict(type='heading4',text=source_text('一级正文')),
            'deep':dict(type='heading8',text=source_text('最深小节')),
            'image':dict(type='image',image=dict(token='picture',caption={})),
            'file':dict(type='file',file=dict(name='讲解.mp4',mimeType='video/mp4'))}
        capture=dict(root='root',records=records,missing=[])
        projected=project_capture(capture,{'picture':dict(local_url='/creation-guide-media/source/picture.png')})
        self.assertEqual(projected['title'],'vsc创作工作台说明')
        self.assertEqual([s['level'] for s in projected['sections']], [0,2,6])
        self.assertEqual(projected['source_blocks'],6)
        html=_build_page(dict(document=dict(title=projected['title']),sections=projected['sections']))
        self.assertEqual(html.count('class="lvl-'),2)
        self.assertEqual(html.count('原始前言'),1)
        self.assertIn('<h6 ',html)
        self.assertIn('<video controls',html)
        self.assertNotIn('gal-toggle',html)
        self.assertNotIn('class="cover"',html)
        with self.assertRaises(ValueError):project_capture(capture,{})
        with self.assertRaises(ValueError):project_capture(dict(capture,missing=['lost']),{})

    def test_attributed_text_handles_unicode_and_base36_attributes(self):
        value=dict(apool=dict(numToAttrib={'10':['bold','true']}),initialAttributedTexts=dict(
            text={'0':'图😀文'},attribs={'0':'+1*a+2+1'}))
        self.assertEqual(block_text(value),'图**😀**文')

    def test_running_routes_list_before_detail_deep_toc_and_video_ranges(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        sections=[dict(level=n,title='标题'+str(n),sort_order=n,body='讲解.mp4' if n==6 else '正文') for n in range(2,7)]
        data=dict(document=dict(slug='tiangong-guide',title='本地文章',cover_media=''),sections=sections,images=[])
        class Store:
            def list_documents(self):return [data['document'],dict(slug='second',title='第二篇')]
            def list_boards(self):return [dict(slug='guides',title='操作说明',summary='已收入的说明'),dict(slug='plaza',title='学习广场',summary='教程和讨论')]
            def get_document(self,slug):return data if slug in ('tiangong-guide','second') else None
        app=FastAPI();install_creation_guide_routes(app,None,None,guide_store=Store())
        with tempfile.TemporaryDirectory() as folder,patch('vsc.interfaces.web.creation_guide.guides_root',return_value=Path(folder)):
            root=Path(folder);(root/'videos').mkdir();(root/'videos'/'讲解.mp4').write_bytes(b'0123456789')
            with TestClient(app) as client:
                listing=client.get('/guide');self.assertEqual(listing.status_code,200)
                self.assertIn('/guide/second',listing.text)
                self.assertIn('学习广场',listing.text)
                self.assertIn('这个板块还没有内容',listing.text)
                detail=client.get('/guide/creation');self.assertEqual(detail.status_code,200)
                self.assertEqual(detail.text.count('class="lvl-'),5)
                self.assertIn('<video controls',detail.text)
                self.assertNotIn('展开全部',detail.text)
                self.assertIn('回复',detail.text)
                self.assertEqual(client.get('/guide/missing').status_code,404)
                media=client.get('/creation-guide-media/讲解.mp4',headers={'Range':'bytes=2-5'})
                self.assertEqual(media.status_code,206);self.assertEqual(media.content,b'2345')
                self.assertEqual(client.get('/creation-guide-media/%2E%2E/%2E%2E/outside.mp4').status_code,404)
