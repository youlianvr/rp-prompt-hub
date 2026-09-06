import sys
css_file = sys.argv[1]
html_file = sys.argv[2]
css = open(css_file, encoding='utf-8').read()
html = open(html_file, encoding='utf-8').read()
s = html.find('<style>') + 7
e = html.find('</style>')
html = html[:s] + chr(10) + css + html[e:]
open(html_file, 'w', encoding='utf-8').write(html)
print(f'Injected {len(css)} bytes CSS into {html_file}')
