#!/usr/bin/env python3
"""
Runs dmsh_build.py on Linux (12 cores) using native Linux dmsh_xlate + spirv-cross!
Instead of calling Apple's xcrun metal on Linux, it writes the exact .metal source into each
target .metallib in IOSOUT so that a parallel GitHub Actions matrix can compile all unique
.metal -> .metallib in ~3 minutes!
"""
import os, re, shutil, subprocess, sys, runpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = os.path.join(REPO, 'dm/gfx/tools')
IOS_TOOLS = os.path.join(REPO, 'dm/ios/tools')
sys.path.insert(0, TOOLS)
sys.path.insert(0, IOS_TOOLS)

import dmsh_chain
import dmsh_mtlcache
import ios_metal

# Bypass tool lock check and compiler_id xcrun call on Linux
dmsh_chain.check_tools = lambda: []
dmsh_mtlcache.compiler_id = lambda sdk: f'linux-pretranslate-{sdk}'

# Replace ios_metal.compile with copying the .metal source into the target .metallib path
def fake_ios_compile(msl, air, lib):
    shutil.copyfile(msl, lib)

ios_metal.compile = fake_ios_compile

# Patch subprocess.run when dmsh_build calls xcrun -sdk macosx metal/metallib
_orig_run = subprocess.run

def patched_run(cmd, *args, **kwargs):
    if isinstance(cmd, (list, tuple)) and len(cmd) >= 4 and cmd[0] == 'xcrun' and cmd[1] == '-sdk' and cmd[2] == 'macosx':
        if '-o' in cmd:
            out_path = cmd[cmd.index('-o') + 1]
            with open(out_path, 'wb') as f:
                f.write(b'MacPlaceholder')
        return subprocess.CompletedProcess(cmd, 0, '', '')
    return _orig_run(cmd, *args, **kwargs)

subprocess.run = patched_run

# Skip pull_finish (_bp) since TotK has pso_mtl4=off and skips _bp.metallib
import dmsh_pull
dmsh_pull.variant = lambda full: (None, 'no stage input')

sys.argv = [os.path.join(TOOLS, 'dmsh_build.py'), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name='__main__')
