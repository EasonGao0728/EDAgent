import test from 'node:test';
import assert from 'node:assert/strict';
import {renderMarkdown} from '../public/markdown.js';
test('untrusted model text cannot create scripts, event handlers or unsafe links',()=>{
  const html=renderMarkdown('<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n```html\n<script>secret</script>\n```');
  assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script'));assert.ok(!html.includes('href="javascript:'));assert.ok(html.includes('&lt;script&gt;'));
});
test('artifact Markdown links resolve only to verified HTTP delivery routes',()=>{
  const html=renderMarkdown('[report](D:/aiEDA/runs/fixture/report.html)',[{name:'report.html',url:'/api/sessions/silicon-123/artifacts/report.html'}]);
  assert.ok(html.includes('href="/api/sessions/silicon-123/artifacts/report.html"'));
  assert.ok(!renderMarkdown('[x](javascript:bad)',[{name:'javascript:bad',url:'javascript:bad'}]).includes('<a'));
});
