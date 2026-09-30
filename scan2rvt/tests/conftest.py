import pytest

from scan2rvt import sintetico
from scan2rvt.config import Settings


@pytest.fixture(scope="session")
def demo():
    return sintetico.generar()


@pytest.fixture()
def ajustes():
    return Settings()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Raíz portátil temporal, con espacios en la ruta como en E:\\000 APPS JAMh."""
    raiz = tmp_path / "000 APPS JAMh" / "Scan2RVT"
    monkeypatch.setenv("SCAN2RVT_HOME", str(raiz))
    from scan2rvt import paths

    paths.ensure_dirs()
    return raiz
