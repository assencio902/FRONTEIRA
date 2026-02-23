import re
with open('/app/static/dashboard.html','r',encoding='utf-8') as f:
    content = f.read()
m = re.search(r'<script>(.*)</script>', content, re.DOTALL)
js = m.group(1)
lines = js.splitlines()
depth = 0
last_open = []
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
                depth += 1; last_open.append(i)
            elif c == '}':
                depth -= 1
                if last_open: last_open.pop()
        j += 1

print(f'Profundidade final: {depth}')
print(f'Ultimas 5 aberturas nao fechadas (linhas JS): {last_open[-5:]}')

# Procura outros erros comuns
problems = []
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith('//'):
        continue
    # template literals (backtick) usados
    if '`' in line:
        problems.append(f'Backtick linha {i}: {stripped[:80]}')
    # unicode com chaves
    if r'\u{' in line:
        problems.append(f'Unicode-braces linha {i}: {stripped[:80]}')

if problems:
    print('PROBLEMAS:')
    for p in problems: print(' ', p)
else:
    print('Nenhum backtick ou unicode-braces encontrado.')
