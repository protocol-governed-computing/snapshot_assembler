"""Build-time hook: stage the composition ordinal inside the package.

The repo-root VERSION is the single authored declaration and `release.sh`
enforces agreement across every repo. A wheel has no repo root, so the value is
copied into the package during the build. The copy is a build artifact —
gitignored, regenerated every build, never edited.
"""
from setuptools import build_meta as _orig
from setuptools.build_meta import *          # noqa: F401,F403
import pathlib

def _stage_ordinal():
    root = pathlib.Path(__file__).parent
    src = root / "VERSION"
    if src.is_file():
        (root / "assembler" / "VERSION").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _stage_ordinal()
    return _orig.build_wheel(wheel_directory, config_settings, metadata_directory)

def build_sdist(sdist_directory, config_settings=None):
    _stage_ordinal()
    return _orig.build_sdist(sdist_directory, config_settings)
