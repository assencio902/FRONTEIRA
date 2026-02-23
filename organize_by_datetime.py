#!/usr/bin/env python3
"""Organiza imagens por data/hora baseada em EXIF, nome do arquivo ou mtime.

Uso básico:
  python organize_by_datetime.py --source uploads --dest data/images

Por padrão usa formato ISO `YYYY/MM/DD`. Para usar `DD-MM-YY` passe `--format ddmmyy`.
"""
from __future__ import annotations
import os
import re
import shutil
import argparse
from datetime import datetime
from pathlib import Path
import logging

try:
    from PIL import Image, ExifTags
except Exception:
    Image = None

FNAME_RE = re.compile(r"(?P<date>\d{8})[_-]?(?P<time>\d{6})")
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}

def get_exif_datetime(path: Path) -> datetime | None:
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            exif = im._getexif() or {}
            if not exif:
                return None
            # map tag ids to names
            tag_map = {v: k for k, v in ExifTags.TAGS.items()}
            for key in ('DateTimeOriginal', 'DateTime'):
                tag = tag_map.get(key)
                if tag and tag in exif:
                    val = exif[tag]
                    try:
                        return datetime.strptime(val, '%Y:%m:%d %H:%M:%S')
                    except Exception:
                        continue
    except Exception:
        return None
    return None

def get_datetime_from_filename(name: str) -> datetime | None:
    m = FNAME_RE.search(name)
    if not m:
        return None
    try:
        d = m.group('date')
        t = m.group('time')
        return datetime.strptime(d + t, '%Y%m%d%H%M%S')
    except Exception:
        return None

def get_datetime_fallback(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)

def ensure_unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    base = dest.stem
    suf = dest.suffix
    parent = dest.parent
    i = 1
    while True:
        candidate = parent / f"{base}_{i}{suf}"
        if not candidate.exists():
            return candidate
        i += 1

def target_dir_for(dt: datetime, dest_root: Path, fmt: str, by_hour: bool) -> Path:
    if fmt == 'ddmmyy':
        day = dt.strftime('%d-%m-%y')
        if by_hour:
            return dest_root / day / dt.strftime('%H')
        return dest_root / day
    # default ISO
    parts = [dt.strftime('%Y'), dt.strftime('%m'), dt.strftime('%d')]
    if by_hour:
        parts.append(dt.strftime('%H'))
    return dest_root.joinpath(*parts)

def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMG_EXTS

def organize(source: Path, dest: Path, fmt: str = 'iso', move: bool = True, dry: bool = False, by_hour: bool = False):
    source = Path(source)
    dest = Path(dest)
    if not source.exists():
        raise SystemExit(f"Source not found: {source}")
    for p in sorted(source.iterdir()):
        if p.is_dir():
            continue
        if not is_image(p):
            continue
        dt = get_exif_datetime(p) or get_datetime_from_filename(p.name) or get_datetime_fallback(p)
        td = target_dir_for(dt, dest, fmt, by_hour)
        td.mkdir(parents=True, exist_ok=True)
        target = td / p.name
        if target.exists():
            target = ensure_unique(target)
        action = 'mv' if move else 'cp'
        logging.info('%s -> %s (%s)', p, target, dt.isoformat())
        if not dry:
            if move:
                shutil.move(str(p), str(target))
            else:
                shutil.copy2(str(p), str(target))

def main():
    parser = argparse.ArgumentParser(description='Organiza imagens por data/hora (EXIF/nome/mtime).')
    parser.add_argument('--source', '-s', default='uploads', help='Pasta de origem (default: uploads)')
    parser.add_argument('--dest', '-d', default='data/images', help='Pasta destino (default: data/images)')
    parser.add_argument('--format', choices=('iso', 'ddmmyy'), default='iso', help='Formato de pasta (iso ou ddmmyy)')
    parser.add_argument('--copy', action='store_true', help='Copiar em vez de mover')
    parser.add_argument('--dry-run', action='store_true', help='Mostrar ações sem executar')
    parser.add_argument('--by-hour', action='store_true', help='Criar subpastas por hora')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format='%(message)s')
    organize(args.source, args.dest, fmt=args.format, move=not args.copy, dry=args.dry_run, by_hour=args.by_hour)

if __name__ == '__main__':
    main()
