import base64,sys
b64 = sys.stdin.read().strip()
css = base64.b64decode(b64).decode()
with open('projects/rp-hub/new_css.txt','w',encoding='utf-8') as f: f.write(css)
print(f"Wrote {len(css)} bytes")