import json
from pathlib import Path
import tempfile
import unittest
from html.parser import HTMLParser
from macro_agent.task_artifacts import write_report

class Resources(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        self.links.extend(v for k,v in attrs if k in ('src','href'))

class ReportTests(unittest.TestCase):
    def test_blob_preview_has_no_relative_resources_and_escapes_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/'placement.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>')
            for name in ('metrics','acceptance','input-manifest'):
                (p/(name+'.json')).write_text(json.dumps({'name':'</pre><script>alert(1)</script>'}))
            write_report(p);text=(p/'report.html').read_text(encoding='utf-8')
            parser=Resources();parser.feed(text)
            self.assertTrue(all(link.startswith('#') for link in parser.links))
            self.assertIn('<svg ',text);self.assertNotIn('<script>',text)
            self.assertIn('id="acceptance"',text)
    def test_unexpected_active_svg_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for svg in ('<svg><script/></svg>','<svg onload="alert(1)"/>','<svg><g href="https://example.com"/></svg>'):
                (p/'placement.svg').write_text(svg)
                with self.assertRaises(ValueError):write_report(p)

if __name__=='__main__':unittest.main()
