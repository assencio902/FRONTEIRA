import re
with open('/app/static/dashboard.html','r',encoding='utf-8') as f:
    content = f.read()

# pega numero da linha do <script>
all_lines = content.splitlines()
script_start = next(i for i,l in enumerate(all_lines) if '<script>' in l)

m = re.search(r'<script>(.*)</script>', content, re.DOTALL)
js = m.group(1)
lines = js.splitlines()
depth = 0
prev_depth = 0
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
                if depth < prev_depth - 1:
                    print(f'CHAVE EXTRA na linha JS {i} (html linha ~{script_start+i}):')
                    print(f'  {line.strip()[:120]}')
                    print(f'  depth virou: {depth}')
        j += 1
    prev_depth = depth

print(f'\nDepth final: {depth}')
