#!/usr/bin/env python3

"""%(prog)s [options]

Helper to create a symlink to a virtualenv in the source tree.
"""

import argparse
import glob
import os
import sys
import site
from pathlib import Path


def colocate_pyi_stubs(virtualenv_home):
    """Symlink .pyi stubs into .pth roots that have matching .py but no .pyi.

    Type checkers like basedpyright only pair .py and .pyi files when they
    are co-located in the same directory.  When multiple .pth roots contribute
    to the same namespace package (e.g. _virtual_imports/ has .py+.pyi while
    the grpc_pb/ copy only has .py), the type checker may pick up the .py
    without its stub.  This creates relative symlinks to fix that.
    """
    site_dirs = glob.glob(
        os.path.join(virtualenv_home, "lib", "python*", "site-packages")
    )
    if not site_dirs:
        return

    site_dir = site_dirs[0]
    pth_file = os.path.join(site_dir, "_aspect.pth")
    if not os.path.isfile(pth_file):
        return

    # Resolve .pth entries lexically (normpath, not realpath) so that
    # relative .. components navigate the runfiles tree correctly even
    # when the venv directory itself is behind a symlink.
    pth_roots = []
    with open(pth_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            resolved = os.path.normpath(os.path.join(site_dir, line))
            if os.path.isdir(resolved):
                pth_roots.append(resolved)

    if not pth_roots:
        return

    # Collect every .pyi file across all roots.
    # key = relative path (e.g. "houstoncontrol/service/user_pb2.pyi")
    # value = absolute path to the .pyi source
    pyi_sources = {}
    for root in pth_roots:
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if fname.endswith(".pyi"):
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, root)
                    pyi_sources.setdefault(rel_path, abs_path)

    # For each .pyi, symlink it into roots that have the .py but lack the .pyi.
    for rel_pyi, pyi_abs in pyi_sources.items():
        rel_py = rel_pyi[:-1]  # .pyi -> .py
        for root in pth_roots:
            py_in_root = os.path.join(root, rel_py)
            pyi_in_root = os.path.join(root, rel_pyi)
            if os.path.isfile(py_in_root) and not os.path.exists(pyi_in_root):
                rel_link = os.path.relpath(pyi_abs, os.path.dirname(pyi_in_root))
                os.symlink(rel_link, pyi_in_root)


def munge_venv_name(target_package, virtualenv_name):
    acc = (target_package or "").replace("/", "+")
    if acc:
        acc += "+"
    acc += virtualenv_name.lstrip(".")
    return "." + acc
    

if __name__ == "__main__":
    virtualenv_home = os.path.normpath(os.environ["VIRTUAL_ENV"])
    virtualenv_name = os.path.basename(virtualenv_home)
    runfiles_dir = os.path.normpath(os.environ["RUNFILES_DIR"])
    builddir = os.path.normpath(os.environ["BUILD_WORKING_DIRECTORY"])
    target_package, target_name = os.environ["BAZEL_TARGET"].split("//", 1)[1].split(":")

    PARSER = argparse.ArgumentParser(
        prog="link",
        usage=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    PARSER.add_argument(
        "--dest",
        dest="dest",
        default=builddir,
        help="Dir to link the virtualenv into. Default is $BUILD_WORKING_DIRECTORY.",
    )

    PARSER.add_argument(
        "--name",
        dest="name",
        default=munge_venv_name(target_package, virtualenv_name),
        help="Name to link the virtualenv as.",
    )
    
    opts = PARSER.parse_args()
    dest = Path(os.path.join(opts.dest, opts.name))
    print("""

Linking: {venv_home} -> {venv_path}
""".format(
    venv_home = virtualenv_home,
    venv_path = dest,
))

    if dest.exists() and dest.is_symlink() and dest.readlink() == Path(virtualenv_home):
        print("Link is up to date!")

    else:
        try:
            dest.lstat()
            dest.unlink()
        except FileNotFoundError:
            pass

        # From -> to
        dest.symlink_to(virtualenv_home, target_is_directory=True)
        print("Link created!")

    # Ensure .pyi type stubs are co-located with their .py files across
    # all .pth roots so that type checkers resolve them correctly.
    colocate_pyi_stubs(virtualenv_home)

    print("""
To configure the virtualenv in your IDE, configure an interpreter with the homedir
    {venv_path}

    Please note that you may encounter issues if your editor doesn't evaluate
    the `activate` script. If you do please file an issue at
    https://github.com/aspect-build/rules_py/issues/new?template=BUG-REPORT.yaml

To activate the virtualenv in your shell run
    source {venv_path}/bin/activate

virtualenvwrapper users may further want to
    $ ln -s {venv_path} $WORKON_HOME/{venv_name}
""".format(
    venv_home = virtualenv_home,
    venv_name = opts.name,
    venv_path = dest,
))
