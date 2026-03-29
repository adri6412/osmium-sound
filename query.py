import urllib.request
import json
url = 'https://raw.githubusercontent.com/LMS-Community/slimserver/public/8.5/HTML/EN/html/docs/cli-api.html'
req = urllib.request.Request(url)
res = urllib.request.urlopen(req)
html = res.read().decode('utf-8')
for i, line in enumerate(html.splitlines()):
  if 'radios' in line:
    print(line)
