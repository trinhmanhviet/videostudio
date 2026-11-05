"""Import ChatGPT asset ZIPs (R<n>_backgrounds.zip, *sheet*.zip) from Downloads into
assets/Meme_Animation_Asset_Pack/new/.

  python scripts/ingest_asset_zips.py            # add files that do not exist yet
  python scripts/ingest_asset_zips.py --replace  # a newer ZIP replaces an existing file;
                                                 # the old one is moved to new/_old_style/

Only PNGs named bg_*, prop_* or fx_* are taken (any folder inside the ZIP). Run
scripts/import_meme_library.py afterwards (or just start the next meme job) to cut the prop/fx sheets.
"""
from __future__ import annotations

import argparse
import os
import shutil
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'assets' / 'Meme_Animation_Asset_Pack' / 'new'
PREFIXES = ('bg_', 'prop_', 'fx_')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--src', type=Path, default=Path.home() / 'Downloads')
    parser.add_argument('--dest', type=Path, default=DEST)
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args(argv)
    dest, old_dir = args.dest, args.dest / '_old_style'
    dest.mkdir(parents=True, exist_ok=True)
    zips = {p for pattern in ('*_backgrounds*.zip', '*sheet*.zip') for p in args.src.glob(pattern)}
    # Choose all winners before extracting: extraction time must never decide
    # which archive wins. Equal archive timestamps use filename order; within an
    # archive the last matching member wins, including duplicate basenames.
    selected = {}
    for archive in sorted(zips, key=lambda p: (p.stat().st_mtime_ns, p.name.casefold(), p.name)):
        archive_mtime = archive.stat().st_mtime_ns
        try:
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    base = Path(member.filename).name
                    if member.is_dir() or not base.lower().endswith('.png') or not base.startswith(PREFIXES):
                        continue
                    selected[base] = (archive, member, archive_mtime)
        except zipfile.BadZipFile as exc:
            print(f'bad zip {archive.name}: {exc}')
    done = []
    for base, (archive, member, archive_mtime) in sorted(selected.items()):
        target = dest / base
        if target.exists() and (not args.replace or target.stat().st_mtime_ns >= archive_mtime):
            continue
        with zipfile.ZipFile(archive) as bundle:
            content = bundle.read(member)
        if target.exists():
            if target.read_bytes() == content:
                continue
            old_dir.mkdir(exist_ok=True)
            backup = old_dir / base
            while backup.exists():
                backup = old_dir / f'{time.time_ns()}_{base}'
            shutil.move(str(target), str(backup))
        target.write_bytes(content)
        os.utime(target, ns=(archive_mtime, archive_mtime))
        done.append(base)
    print(f'{len(done)} file(s) imported: {", ".join(done) if done else "-"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
