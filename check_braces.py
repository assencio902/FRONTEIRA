import re

with open('ingest/static/dashboard.html', encoding='utf-8') as f:
    lines = f.readlines()
js_lines = lines[2041:7502]

opens = 0; closes = 0; offset = 2042
in_ml_comment = False
for i, line in enumerate(js_lines):
    stripped = line
    # remove comentarios de linha e strings simples
    stripped = re.sub(r'//.*$', '', stripped)
    stripped = re.sub(r'"[^"]*"', '""', stripped)
    stripped = re.sub(r"'[^']*'", "''", stripped)
    opens  += stripped.count('{')
    closes += stripped.count('}')

print(f'Total open : {opens}')
print(f'Total close: {closes}')
print(f'Balanco    : {opens - closes}')
