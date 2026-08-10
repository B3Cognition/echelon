from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPyWithEchelonBundles(build_py):
    """Include canonical Echelon prose/runtime sources as package resources."""

    def run(self) -> None:
        super().run()
        source_root = Path(__file__).resolve().parent
        bundle_root = Path(self.build_lib) / "echelon" / "bundles"
        for name in ("prosaic", "runtime"):
            source = source_root / name
            destination = bundle_root / name
            shutil.rmtree(destination, ignore_errors=True)
            shutil.copytree(
                source,
                destination,
                copy_function=shutil.copy2,
                ignore=shutil.ignore_patterns(
                    ".DS_Store",
                    ".pytest_cache",
                    "__pycache__",
                    "*.pyc",
                ),
            )


setup(cmdclass={"build_py": BuildPyWithEchelonBundles})
