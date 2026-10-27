#!/usr/bin/env python3
"""
Fast parallel Metal compiler for GitHub Actions matrix shards.
Resolves the real `metal` and `metallib` binaries and iOS SDK path ONCE (zero xcrun overhead per shader)
and compiles all .metal sources in metals_shard_<K>.tar.zst in parallel, printing progress every 10s.
"""
import concurrent.futures as cf
import os, subprocess, sys, tempfile, time
from pathlib import Path


def resolve_ios_tools():
    metal_bin = subprocess.check_output(['xcrun', '-sdk', 'iphoneos', '-f', 'metal'], text=True).strip()
    metallib_bin = subprocess.check_output(['xcrun', '-sdk', 'iphoneos', '-f', 'metallib'], text=True).strip()
    sdk_path = subprocess.check_output(['xcrun', '-sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    return metal_bin, metallib_bin, sdk_path


def main():
    shard_id = int(sys.argv[1])
    tar_in = Path(sys.argv[2]).resolve()
    tar_out = Path(sys.argv[3]).resolve()

    work = Path(tempfile.mkdtemp(prefix=f'shard_{shard_id}_'))
    src_dir = work / 'src'
    out_dir = work / 'out'
    air_dir = work / 'air'
    src_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    air_dir.mkdir(parents=True)

    subprocess.run(['tar', '--zstd', '-xf', str(tar_in), '-C', str(src_dir)], check=True)
    my_files = sorted(src_dir.glob('*.metal'))

    metal_bin, metallib_bin, sdk_path = resolve_ios_tools()
    print(f'[Shard {shard_id}] Resolved metal={metal_bin}, sdk={sdk_path}', flush=True)
    print(f'[Shard {shard_id}] Compiling {len(my_files):,} unique .metal shaders...', flush=True)

    metal_cmd_base = [
        metal_bin,
        '-isysroot', sdk_path,
        '-c',
        '-mios-version-min=18.0',
        '-fmetal-math-mode=relaxed',
        '-fpreserve-invariance',
    ]

    def compile_one(mpath: Path):
        stem = mpath.stem
        air = air_dir / f'{stem}.air'
        lib = out_dir / f'{stem}.metallib'
        r1 = subprocess.run([*metal_cmd_base, str(mpath), '-o', str(air)], capture_output=True)
        if r1.returncode != 0:
            return False
        r2 = subprocess.run([metallib_bin, str(air), '-o', str(lib)], capture_output=True)
        try:
            air.unlink()
        except OSError:
            pass
        return r2.returncode == 0

    t0 = time.time()
    last_print = t0
    done = 0
    ok = 0
    workers = min(8, (os.cpu_count() or 3) * 2)
    with cf.ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(compile_one, p) for p in my_files]
        for fut in cf.as_completed(futures):
            done += 1
            if fut.result():
                ok += 1
            now = time.time()
            if now - last_print >= 10 or done == len(my_files):
                elapsed = now - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(my_files) - done) / rate if rate > 0 else 0
                print(
                    f'[Shard {shard_id}] {done:,}/{len(my_files):,} ({done * 100 / max(1, len(my_files)):.1f}%) '
                    f'| ok={ok:,} | {rate:.1f} sh/s | elapsed {int(elapsed)}s | ETA {int(eta)}s',
                    flush=True,
                )
                last_print = now

    subprocess.run(['tar', '--zstd', '-cf', str(tar_out), '-C', str(out_dir), '.'], check=True)
    print(f'[Shard {shard_id}] Done! Packed {ok:,} metallibs into {tar_out} ({tar_out.stat().st_size / 2**20:.1f} MB)', flush=True)


if __name__ == '__main__':
    main()
