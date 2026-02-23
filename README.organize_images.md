Organizar imagens por data/hora
================================

Script: `organize_by_datetime.py`

O que faz
- Lê o timestamp principal das imagens via EXIF (`DateTimeOriginal`).
- Se EXIF não existir ou estiver inválido, tenta extrair do nome do arquivo (padrão `YYYYMMDD_HHMMSS`).
- Como último recurso usa o `mtime` do arquivo.
- Move (ou copia) as imagens para pastas organizadas por data.

Uso rápido
```
python organize_by_datetime.py --source uploads --dest data/images
```

Opções úteis
- `--format iso|ddmmyy` — `iso` cria `YYYY/MM/DD`, `ddmmyy` cria `DD-MM-YY`.
- `--by-hour` — cria subpastas por hora.
- `--dry-run` — apenas mostra ações.
- `--copy` — copia em vez de mover.

Dependências
- `Pillow` (já listado em `ingest/requirements.txt`)

Recomendação
- Preferível usar o formato `iso` para ordenação natural. Use `ddmmyy` apenas para exibição humana.
