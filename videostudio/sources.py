"""Bounded public reference retrieval. Fetched content is data, not tool instructions.
Only explicitly allowed public reference domains; no host-local URLs or credentials.
"""
import hashlib,ipaddress,json,socket
from html.parser import HTMLParser
from urllib.parse import urlparse,urljoin
from pathlib import Path
import httpx
ALLOWED=('wikipedia.org','britannica.com','si.edu','nasa.gov','loc.gov','archives.gov','gov.vn')
class PlainText(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','iframe','svg'):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','iframe','svg') and self.skip:self.skip-=1
        if tag in ('p','h1','h2','h3','li','div'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)
    def text(self):return '\n'.join(' '.join(line.split()) for line in ''.join(self.parts).splitlines() if line.strip())
def validate_url(url,resolve=True):
    u=urlparse(url);host=(u.hostname or '').lower()
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443):raise ValueError('Only public HTTPS references permitted')
    if not any(host==d or host.endswith('.'+d) for d in ALLOWED):raise ValueError('Reference domain not in public-source allowlist')
    if resolve:
        addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('Non-public reference address')
    return url

def fetch_source(url,output,client=None,resolve=True):
    original=url;content=None
    owns=client is None;client=client or httpx.Client(trust_env=False,timeout=20,follow_redirects=False)
    try:
        for _ in range(4):
            validate_url(url,resolve)
            with client.stream('GET',url,headers={'User-Agent':'VideoStudioLocal/0.1 reference-check'}) as r:
                if r.status_code in (301,302,303,307,308):url=urljoin(url,r.headers.get('location',''));continue
                r.raise_for_status()
                kind=r.headers.get('content-type','').lower()
                if 'text/html' not in kind and 'text/plain' not in kind:raise ValueError('Unsupported reference content type')
                chunks=[];size=0
                for chunk in r.iter_bytes():
                    size+=len(chunk)
                    if size>1500000:raise ValueError('Reference exceeds retrieval budget')
                    chunks.append(chunk)
                content=b''.join(chunks);break
        if content is None:raise ValueError('Too many reference redirects')
        decoded=content.decode('utf8',errors='replace')
        if 'text/html' in kind:
            parser=PlainText();parser.feed(decoded);text=parser.text()
        else:text=decoded
        if len(text.strip())<200:raise ValueError('Reference has insufficient readable evidence')
        text=text[:60000];path=Path(output);path.write_text(text,encoding='utf8')
        return {'url':url,'requested_url':original,'path':str(path),'text':text,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'retrieval':'public_https_allowlist','untrusted_reference_data':True}
    finally:
        if owns:client.close()
