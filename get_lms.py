import urllib.request
import re

url = "https://raw.githubusercontent.com/LMS-Community/slimserver/public/8.5/Slim/Control/Queries.pm"
req = urllib.request.Request(url)
res = urllib.request.urlopen(req)
code = res.read().decode('utf-8')

for i, line in enumerate(code.splitlines()):
    if re.search(r"\'radios\'|radios\b", line):
        print(f"{i}: {line}")
