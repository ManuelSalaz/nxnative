#!/usr/bin/env python3
"""
Step 2 (Linux): Take DmIOS_app.tar.zst and compiled_metals.tar.zst from GitHub Actions,
fan out the deduplicated .metallib binaries into the local shader/ios/b-<chain> directory,
and pack the final .ipa with the local 16 GB RomFS using dm/ios/tools/pack_ipa.py.
"""
import json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parent.parent


def main():
    work = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path('/home/manu/Games/TotK/0100F2C0115B6000_build')
    app_tar = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else REPO / 'DmIOS_app.tar.zst'
    metals_tar = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else REPO / 'compiled_metals.tar.zst'

    for p in (work / 'job.json', work / 'metal_dedup.json', app_tar, metals_tar):
        if not p.is_file():
            sys.exit(f'Missing required file: {p}')

    job = json.loads((work / 'job.json').read_text())
    dedup_map = json.loads((work / 'metal_dedup.json').read_text())
    chain = job['chain']
    romfs_dir = Path(job['romfs_dir'])
    if not romfs_dir.is_dir():
        sys.exit(f'Local RomFS directory not found: {romfs_dir}')

    out_ipa = Path(job['out_ipa']).resolve()
    ios_b = work / 'shader/ios' / f'b-{chain}'

    stage = work / 'pack_stage'
    if stage.exists():
        shutil.rmtree(stage)
    (stage / 'metals').mkdir(parents=True)
    (stage / 'app').mkdir(parents=True)

    print(f'1. Extracting {app_tar.name} ...', flush=True)
    subprocess.run(['tar', '--zstd', '-xf', str(app_tar), '-C', str(stage / 'app')], check=True)
    app_dir = stage / 'app/DmIOS.app'
    if not app_dir.is_dir():
        sys.exit(f'DmIOS.app not found inside {app_tar}')

    print(f'2. Extracting {metals_tar.name} ...', flush=True)
    subprocess.run(['tar', '--zstd', '-xf', str(metals_tar), '-C', str(stage / 'metals')], check=True)

    print(f'3. Populating {len(dedup_map)} unique compiled .metallib shaders into {ios_b} ...', flush=True)
    populated = 0
    missing = 0
    for h, targets in dedup_map.items():
        src = stage / 'metals' / f'{h}.metallib'
        if not src.is_file():
            # Remove uncompiled text placeholder so pack_ipa doesn't pack text as metallib
            for t in targets:
                tp = ios_b / t
                if tp.exists():
                    tp.unlink()
            missing += 1
            continue
        data = src.read_bytes()
        for t in targets:
            (ios_b / t).write_bytes(data)
            populated += 1

    print(f'   Populated {populated} .metallib files ({missing} missing hashes).', flush=True)

    p = 'Payload/DmIOS.app'
    maps = [f'{p}/romfs={romfs_dir}']
    aoc_dir = job.get('aoc_dir')
    if aoc_dir and Path(aoc_dir).is_dir():
        maps.append(f'{p}/aoc={aoc_dir}')
    maps += [f'{p}/msl/b-{chain}={ios_b}', f'{p}={app_dir}']

    cmd = [
        sys.executable,
        str(REPO / 'dm/ios/tools/pack_ipa.py'),
        str(out_ipa),
        '--store', job.get('zip_store', ''),
        '--skip-suffix', '_bp.metallib',
        '--skip', f'{p}/_CodeSignature',
        '--skip', f'{p}/embedded.mobileprovision',
        '--skip', f'{p}/msl',
        '--skip', f'{p}/aoc',
        '--skip', f'{p}/romfs',
        *maps,
    ]
    print(f'4. Packing final IPA -> {out_ipa} ...', flush=True)
    subprocess.run(cmd, check=True)
    shutil.rmtree(stage)
    print(f'\nDone! Final IPA ready: {out_ipa} ({out_ipa.stat().st_size / 2**30:.2f} GB)', flush=True)
    print(f'To install on your iPhone, run:\n  xtool install "{out_ipa}"', flush=True)


if __name__ == '__main__':
    main()
