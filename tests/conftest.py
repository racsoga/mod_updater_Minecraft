import pytest

from mod_updater import i18n


@pytest.fixture(autouse=True)
def spanish(request, monkeypatch):
    """Los tests comprueban textos en español, sea cual sea el idioma de Windows de la máquina
    (en GitHub Actions es inglés). "Automático" se resuelve a español salvo en los tests
    marcados con @pytest.mark.real_language, que prueban la detección del idioma del sistema."""
    if "real_language" not in request.keywords:
        monkeypatch.setattr(i18n, "system_language", lambda: "es")
    i18n.set_language("es")
    yield
    i18n.set_language("es")
