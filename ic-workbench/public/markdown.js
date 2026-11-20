const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function renderMarkdown(text,artifacts=[]){
  const inline=value=>escape(value).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\[([^\]]+)\]\(([^)]+)\)/g,(all,label,url)=>{
    const file=artifacts.find(a=>url.endsWith('/'+a.name)||url===a.name);
    if(file&&/^\/api\/sessions\/[a-z0-9-]+\/artifacts\/[A-Za-z0-9_.%-]+$/.test(file.url))return `<a href="${escape(file.url)}" target="_blank" rel="noopener">${label}</a>`;
    if(/^https:\/\/[^\s<>"']+$/.test(url))return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    return label+' ('+url+')';
  });
  const lines=String(text||'').split('\n'),out=[];let i=0;
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
  while(i<lines.length){let line=lines[i];if(!line.trim()){i++;continue;}
    if(/^```/.test(line)){const code=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))code.push(lines[i++]);i++;out.push('<pre><code>'+escape(code.join('\n'))+'</code></pre>');continue;}
    if(/^#{1,6} /.test(line)){out.push('<h3>'+inline(line.replace(/^#{1,6} /,''))+'</h3>');i++;continue;}
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){const head=cells(line);i+=2;const rows=[];while(i<lines.length&&lines[i].includes('|'))rows.push(cells(lines[i++]));out.push('<div class="message-table"><table><thead><tr>'+head.map(c=>'<th>'+inline(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>');continue;}
    if(/^\s*[-*] /.test(line)){const items=[];while(i<lines.length&&/^\s*[-*] /.test(lines[i]))items.push(lines[i++].replace(/^\s*[-*] /,''));out.push('<ul>'+items.map(c=>'<li>'+inline(c)+'</li>').join('')+'</ul>');continue;}
    const para=[line];i++;while(i<lines.length&&lines[i].trim()&&!/^(?:#{1,6} |```|\s*[-*] )/.test(lines[i])&&!(lines[i].includes('|')&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1]||'')))para.push(lines[i++]);out.push('<p>'+para.map(inline).join('<br>')+'</p>');
  }return out.join('');
}
