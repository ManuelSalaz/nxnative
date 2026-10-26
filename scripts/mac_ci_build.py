#!/usr/bin/env python3
"""
Runs on GitHub Actions macOS runner:
Unpacks mac_input.tar.zst, compiles iOS Metal shaders (.metallib) and DmIOS.app via Xcode,
and outputs mac_output.tar.zst (~150-300 MB) without needing the 16 GB RomFS.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
import build_ipa_from_nsp as b


def main():
    tar_in = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / 'mac_input.tar.zst').resolve()
    if not tar_in.is_file():
        sys.exit(f'Missing {tar_in}')

    work = REPO / 'ci_work'
    b.rmtree(work)
    work.mkdir(parents=True)
    subprocess.run(['tar', '--zstd', '-xf', str(tar_in), '-C', str(work)], check=True)

    job = json.loads((work / 'job.json').read_text())
    game_id = job['game_id']
    env = dict(os.environ, PATH=os.pathsep.join(b.TOOL_PATHS + [os.environ.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')]))
    env.setdefault('USER', os.environ.get('USER', 'runner'))
    b.configure_dotnet(env)
    env.setdefault('J', str(os.cpu_count() or 4))

    if job.get('derived') and (work / 'profile' / game_id).is_dir():
        pdir = work / 'profile'
        os.environ['DM_GAMES_DIR'] = env['DM_GAMES_DIR'] = str(pdir)
        os.environ['DM_GAMES_FIRST'] = env['DM_GAMES_FIRST'] = '1'

    sys.path.insert(0, str(REPO / 'dm/games'))
    import game as gamemod
    g = gamemod.load(game_id)

    logs = work / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    (work / 'tmp').mkdir(parents=True, exist_ok=True)
    env.update(DM_GAME=g.id, DM_ROOT=str(work), WORK=str(work / 'tmp'))

    py = sys.executable
    b.chain_header(py, REPO, env, logs)
    xlate = REPO / 'dm/gfx/tools/dmsh_xlate_bin/dmsh_xlate'
    sh = work / 'shader'
    ios_msl = b.build_shaders(py, REPO, sh, xlate, env, logs, g, pkg_key=None, mac=False)

    # Create dummy RomFS with the marker so build_ipa.sh passes the marker check
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
        MSL_IOS=str(ios_msl),
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

    out_stage = work / 'mac_out_stage'
    out_stage.mkdir(parents=True)
    shutil.copytree(app_dir, out_stage / 'DmIOS.app', symlinks=True)
    chain = b.chain_of(REPO)
    msl_sub = f'b-{chain}' if job['gfx'] == 'nvn' else ('vk' if job['gfx'] == 'vulkan' else 'gl')
    shutil.copytree(ios_msl / msl_sub, out_stage / 'msl' / msl_sub, symlinks=True)
    shutil.copyfile(work / 'job.json', out_stage / 'job.json')

    tar_out = REPO / 'mac_output.tar.zst'
    b.rmtree(tar_out)
    subprocess.run(['tar', '--zstd', '-cf', str(tar_out), '-C', str(out_stage), '.'], check=True)
    print(f'Created {tar_out} ({tar_out.stat().st_size / 2**20:.1f} MB)')


if __name__ == '__main__':
    main()
