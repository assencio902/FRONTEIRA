import re
with open('/app/static/dashboard.html','r',encoding='utf-8') as f:
    content = f.read()

all_lines = content.splitlines()
script_start = next(i for i,l in enumerate(all_lines) if '<script>' in l)

m = re.search(r'<script>(.*)</script>', content, re.DOTALL)
js = m.group(1)
lines = js.splitlines()
depth = 0
min_depth = 0
min_line = 0

for i, line in enumerate(lines, 1):
    in_str = False
    str_char = None
    j = 0
    while j < len(line):
        c = line[j]
        if not in_str and c in ('"', "'"):
            in_str = True; str_char = c
        elif in_str and c == str_char and (j == 0 or line[j-1] != '\\'):
            in_str = False
        elif not in_str:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth < min_depth:
                    min_depth = depth
                    min_line = i
        j += 1

html_line = script_start + min_line
print(f'Chave extra mais funda: JS linha {min_line} = HTML linha ~{html_line}')
print(f'Contexto:')
for k in range(max(0, min_line-3), min(len(lines), min_line+2)):
    marker = '>>> ' if k+1 == min_line else '    '
    print(f'{marker}{script_start+k+1:4d}: {lines[k]}')
