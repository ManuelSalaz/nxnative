#!/usr/bin/env python3
"""
Step 1 (Linux): Extract NSP(s), rewrite Switch NSO binaries, split shaders,
and pack only the lightweight Mac compilation inputs (~50-80 MB) into mac_input.tar.zst.
The 16 GB RomFS stays on your local Linux disk.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
import build_ipa_from_nsp as b


def main():
    args = b.parse_args(sys.argv[1:])
    b.PROG.mode = b.progress_mode(args.progress or b.PROGRESS)
    b.ALLOW_DAMAGED = args.allow_damaged or b.ALLOW_DAMAGED

    nsp_dir = Path(os.path.expanduser(args.nsp_dir or b.NSP_DIR or b.ask('NSP folder: ', 'the NSP folder'))).resolve()
    keys = Path(os.path.expanduser(args.keys or b.PROD_KEYS or b.ask('path of prod.keys: ', 'prod.keys (-k)'))).resolve()
    if not nsp_dir.is_dir():
        raise b.BuildError(f'not a folder: {nsp_dir}')
    if not keys.is_file():
        raise b.BuildError(f'no such file: {keys}')

    sys.path.insert(0, str(REPO / 'dm/games'))
    import game as gamemod
    import profile_guess as pg
    b.pg = pg
    sys.path.insert(0, str(REPO / 'dm/tools'))
    import nacp
    b.nacp = nacp

    lang_in = args.language or b.LANGUAGE
    want_lang = b.language_code(lang_in) if lang_in else 'en-US'

    env = dict(os.environ, PATH=os.pathsep.join(b.TOOL_PATHS + [os.environ.get('PATH', '/usr/bin:/bin')]))
    b.configure_dotnet(env)
    env.setdefault('J', str(os.cpu_count() or 8))
    py = sys.executable

    app, fam = b.scan_nsps(nsp_dir)
    fam = b.decompress_nsz(nsp_dir, app, fam, keys, env)
    g = gamemod.by_title(app)
    provisional = False
    if g is None:
        raise b.BuildError(f'Game {app:016X} has no profile in dm/games')

    b.say(f'game profile: {g.id} ({g.get("name", "")})')
    builds, need = g.builds(), g.words('shader_versions')
    have, derived = b.nsp_versions(fam, builds), False
    pkg_ver = args.package or b.PACKAGE or max(have, key=b.vnum)
    if pkg_ver not in builds:
        derived = f'{pkg_ver} is not a registered version'
    elif not all(v in have for v in need):
        derived = f'folder lacks {", ".join(v for v in need if v not in have)}'

    versions = [pkg_ver] if derived else need + ([pkg_ver] if pkg_ver not in need else [])
    work = nsp_dir / f'{g.id}_build'
    env.update(DM_GAME=g.id, DM_ROOT=str(work), WORK=str(work / 'tmp'))
    logs = work / 'logs'
    ex = work / 'extract'
    ex.mkdir(parents=True, exist_ok=True)
    (work / 'tmp').mkdir(exist_ok=True)

    picks = b.pick_nsps(fam, have, versions)
    b.PROG.plan(1 + len(versions) + 3)
    b.PROG.stage('build nx_extract')
    nx = b.build_nx_extract(REPO, work, logs, env)
    b.PROG.end()

    dirs, clone = {}, None
    for ver in versions:
        base_nsp, upd_nsp = picks[ver]
        dirs[ver] = b.extract(nx, keys, ex, ver, base_nsp, upd_nsp, clone, logs, g)

    bad = [] if derived else [f'{v}: {x}' for v in versions for x in b.build_mismatch(dirs[v], v, g)]
    if bad:
        derived = f'build mismatch: {"; ".join(bad)}'
        versions, dirs = [pkg_ver], {pkg_ver: dirs[pkg_ver]}

    pdir = work / 'profile'
    if derived:
        b.say(f'{derived}: deriving profile for {pkg_ver}')
        disp = b.derive_profile(g, pdir / g.id, pkg_ver, dirs[pkg_ver], g.words('modules'), app)
        os.environ['DM_GAMES_DIR'] = env['DM_GAMES_DIR'] = str(pdir)
        os.environ['DM_GAMES_FIRST'] = env['DM_GAMES_FIRST'] = '1'
        g = gamemod.load(g.id)
        b.say(f'derived game profile for {pkg_ver} ({disp}): {g.dir}')

    sv = versions if derived else need
    game = dirs[pkg_ver]
    src = pg.build_sources(game / 'ExeFS', game / 'RomFS', g.words('modules'))
    gfx = src['graphics'][0]
    aoc = b.extract_aoc(nx, keys, REPO, work, app, fam, logs)
    base = next((dirs[v] for v in versions if picks[v][1] is None), dirs[versions[0]])

    app_name = args.app_name or b.APP_NAME or nacp.name(base / 'control.nacp')
    bundle_id = args.bundle_id or b.BUNDLE_ID or f'org.nxnative.{app:016x}'
    app_version = nacp.version(game / 'control.nacp') or nacp.version(base / 'control.nacp') or '1.0'
    have_langs = nacp.languages(game / 'control.nacp') or nacp.languages(base / 'control.nacp')
    lang = b.game_language(want_lang, bool(lang_in), have_langs)

    patched = work / f'patched_{pkg_ver}'
    g = b.rewrite(py, REPO, game / 'ExeFS', patched, env, logs, g, provisional)
    b.chain_header(py, REPO, env, logs)
    if derived:
        b.provisional_prep(py, REPO, env, logs, g)
        g = b.refine_after_rewrite(g, game, patched, None)

    sh = work / 'shader'
    own = bool(provisional or derived)
    b.split_shaders(py, REPO, [dirs[v] / 'RomFS' for v in sv], [dirs[v] / 'ExeFS/main' for v in sv], sh / 'pkg', env, logs, g, own, None)

    icon = next((d / 'icon.jpg' for d in (game, base) if (d / 'icon.jpg').exists()), None)
    out_ipa = Path(os.path.expanduser(args.out or b.OUT_IPA)).resolve() if (args.out or b.OUT_IPA) else nsp_dir / g.get('ipa')

    # Bundle lightweight Mac inputs into mac_input.tar.zst
    b.PROG.stage('pack mac_input.tar.zst')
    stage_dir = work / 'mac_stage'
    b.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    shutil.copytree(patched, stage_dir / 'patched')
    shutil.copytree(sh / 'pkg', stage_dir / 'shader/pkg')
    if (sh / 'pso_pairs.tsv').is_file():
        shutil.copyfile(sh / 'pso_pairs.tsv', stage_dir / 'shader/pso_pairs.tsv')
    if derived and (pdir / g.id).is_dir():
        shutil.copytree(pdir / g.id, stage_dir / 'profile' / g.id)

    (stage_dir / 'meta').mkdir(parents=True)
    if (game / 'control.nacp').is_file():
        shutil.copyfile(game / 'control.nacp', stage_dir / 'meta/control.nacp')
    if (base / 'control.nacp').is_file():
        shutil.copyfile(base / 'control.nacp', stage_dir / 'meta/base_control.nacp')
    if icon and icon.is_file():
        shutil.copyfile(icon, stage_dir / 'meta/icon.jpg')

    job = {
        'game_id': g.id,
        'pkg_ver': pkg_ver,
        'app_name': app_name,
        'app_version': app_version,
        'bundle_id': bundle_id,
        'lang': lang,
        'gfx': gfx,
        'derived': bool(derived),
        'romfs_marker': g.get('romfs_marker'),
        'zip_store': g.get('zip_store'),
        'romfs_dir': str(game / 'RomFS'),
        'aoc_dir': str(aoc) if aoc else '',
        'out_ipa': str(out_ipa),
        'chain': b.chain_of(REPO),
    }
    (stage_dir / 'job.json').write_text(json.dumps(job, indent=2))
    (work / 'job.json').write_text(json.dumps(job, indent=2))

    tar_out = REPO / 'mac_input.tar.zst'
    b.rmtree(tar_out)
    subprocess.run(['tar', '--zstd', '-cf', str(tar_out), '-C', str(stage_dir), '.'], check=True)
    b.rmtree(stage_dir)
    b.PROG.end(f'{tar_out} ({tar_out.stat().st_size / 2**20:.1f} MB)')
    b.say(f'Ready for GitHub Actions: {tar_out} ({tar_out.stat().st_size / 2**20:.1f} MB)')


if __name__ == '__main__':
    main()
