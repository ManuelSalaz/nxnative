#!/usr/bin/env python3
"""
Builds ONLY DmIOS.app via Xcode on macOS (takes ~90 seconds), using the pre-generated
c1_full.tsv, cb_extent.tsv, and inputs.tsv from Linux!
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
import build_ipa_from_nsp as b


def main():
    tar_in = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / 'mac_app_input.tar.zst').resolve()
    tables_tar = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    work = REPO / 'ci_app_work'
    b.rmtree(work)
    work.mkdir(parents=True)
    subprocess.run(['tar', '--zstd', '-xf', str(tar_in), '-C', str(work)], check=True)
    if tables_tar and tables_tar.is_file():
        subprocess.run(['tar', '--zstd', '-xf', str(tables_tar), '-C', str(work)], check=True)

    job = json.loads((work / 'job.json').read_text())
    game_id = job['game_id']
    env = dict(os.environ, PATH=os.pathsep.join(b.TOOL_PATHS + [os.environ.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')]))
    env.setdefault('USER', os.environ.get('USER', 'runner'))

    sys.path.insert(0, str(REPO / 'dm/games'))
    import game as gamemod
    g = gamemod.load(game_id)

    # Copy pre-generated c1_full.tsv and cb_extent.tsv into profile dir
    for tname in ('c1_full.tsv', 'cb_extent.tsv'):
        if (work / 'tables' / tname).is_file():
            shutil.copyfile(work / 'tables' / tname, g.table(tname))

    logs = work / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    b.chain_header(py, REPO, env, logs)
    chain = b.chain_of(REPO)

    # Create dummy MSL_IOS directory with inputs.tsv and one dummy _b.metallib so build_ipa.sh passes validation
    dummy_msl = work / 'dummy_msl'
    msl_sub = dummy_msl / f'b-{chain}'
    msl_sub.mkdir(parents=True)
    shutil.copyfile(work / 'tables/inputs.tsv', msl_sub / 'inputs.tsv')
    (msl_sub / '0000000000000000_b.metallib').write_bytes(b'Dummy')

    dummy_romfs = work / 'dummy_romfs'
    marker = job.get('romfs_marker') or g.get('romfs_marker')
    if marker:
        mp = dummy_romfs / marker
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_bytes(b'')
    else:
        dummy_romfs.mkdir(parents=True, exist_ok=True)

    if (work / 'meta/control.nacp').is_file():
        shutil.copyfile(work / 'meta/control.nacp', work / 'control.nacp')
    if (work / 'meta/icon.jpg').is_file():
        shutil.copyfile(work / 'meta/icon.jpg', work / 'icon.jpg')

    ipa_work = work / 'ipa'
    dummy_ipa = work / 'dummy.ipa'
    ipa_env = dict(
        env,
        GAME=g.id,
        W=str(ipa_work),
        PATCHED=str(work / 'patched'),
        ROMFS=str(dummy_romfs),
        MSL_IOS=str(dummy_msl),
        GFXAPI=job['gfx'],
        FONT_PY=py,
        DM_DISPLAY_NAME=job['app_name'],
        DM_APP_VERSION=job['app_version'],
        DM_BUNDLE_ID=job['bundle_id'],
        AOC='',
        DM_XCODE_DERIVED_DATA=str(work / 'xcode-derived-data'),
        DM_TEAM_ID='0000000000',
        DM_LANG=job['lang'],
        DM_SHOW_FPS='1',
        DM_PSO_GPUS='none',
    )
    if (work / 'icon.jpg').is_file():
        ipa_env['DM_ICON'] = str(work / 'icon.jpg')

    b.run(['bash', REPO / 'dm/ios/tools/build_ipa.sh', dummy_ipa], logs / 'build_ipa.log', env=ipa_env)
    app_dir = ipa_work / 'build/ios/pkg/dd/Build/Products/Release-iphoneos/DmIOS.app'
    if not app_dir.is_dir():
        sys.exit(f'Built app not found at {app_dir}')

    out_stage = work / 'app_stage'
    out_stage.mkdir(parents=True)
    shutil.copytree(app_dir, out_stage / 'DmIOS.app', symlinks=True)
    tar_out = REPO / 'DmIOS_app.tar.zst'
    b.rmtree(tar_out)
    subprocess.run(['tar', '--zstd', '-cf', str(tar_out), '-C', str(out_stage), '.'], check=True)
    print(f'Built DmIOS.app -> {tar_out} ({tar_out.stat().st_size / 2**20:.1f} MB)', flush=True)


if __name__ == '__main__':
    main()
