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
    done = []
    for archive in sorted(zips, key=lambda p: p.stat().st_mtime):
        try:
            bundle = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as exc:
            print(f'bad zip {archive.name}: {exc}')
            continue
        with bundle:
            for name in bundle.namelist():
                base = Path(name).name
                if not base.lower().endswith('.png') or not base.startswith(PREFIXES):
                    continue
                target = dest / base
                if target.exists():
                    # skip unless asked to replace AND this zip is newer than the file we already have
                    if not args.replace or target.stat().st_mtime >= archive.stat().st_mtime:
                        continue
                    old_dir.mkdir(exist_ok=True)
                    backup = old_dir / base
                    if backup.exists():
                        backup = old_dir / f'{int(time.time())}_{base}'
                    shutil.move(str(target), str(backup))
                target.write_bytes(bundle.read(name))
                done.append(base)
    print(f'{len(done)} file(s) imported: {", ".join(done) if done else "-"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
