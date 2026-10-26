#!/usr/bin/env python3
"""
Step 2 (Linux): Take mac_output.tar.zst from GitHub Actions and pack it with the
local 16 GB RomFS into the final .ipa using dm/ios/tools/pack_ipa.py.
"""
import json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parent.parent


def main():
    tar_in = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / 'mac_output.tar.zst').resolve()
    if not tar_in.is_file():
        sys.exit(f'Missing {tar_in}')

    stage = REPO / 'linux_pack_stage'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    print(f'Extracting {tar_in} ...')
    subprocess.run(['tar', '--zstd', '-xf', str(tar_in), '-C', str(stage)], check=True)

    job = json.loads((stage / 'job.json').read_text())
    romfs_dir = Path(job['romfs_dir'])
    if not romfs_dir.is_dir():
        sys.exit(f'Local RomFS directory not found: {romfs_dir}')

    out_ipa = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(job['out_ipa']).resolve()
    msl_root = stage / 'msl'
    msl_sub = next(msl_root.iterdir())
    app_dir = stage / 'DmIOS.app'

    p = 'Payload/DmIOS.app'
    maps = [f'{p}/romfs={romfs_dir}']
    aoc_dir = job.get('aoc_dir')
    if aoc_dir and Path(aoc_dir).is_dir():
        maps.append(f'{p}/aoc={aoc_dir}')
    maps += [f'{p}/msl/{msl_sub.name}={msl_sub}', f'{p}={app_dir}']

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
    print(f'Packing final IPA -> {out_ipa} ...')
    subprocess.run(cmd, check=True)
    shutil.rmtree(stage)
    print(f'\nDone! Final IPA ready: {out_ipa} ({out_ipa.stat().st_size / 2**30:.2f} GB)')
    print(f'To install on your iPhone, run:\n  xtool install "{out_ipa}"')


if __name__ == '__main__':
    main()
