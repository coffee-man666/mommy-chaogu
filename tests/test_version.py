from importlib.metadata import version

from mommy_chaogu import __version__
from mommy_chaogu.web import create_app


def test_version_has_one_canonical_source() -> None:
    assert __version__ == "1.0.0"
    assert version("mommy-chaogu") == __version__
    assert create_app().version == __version__
