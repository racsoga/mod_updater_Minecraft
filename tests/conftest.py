import pytest

from mod_updater import i18n


@pytest.fixture(autouse=True)
def spanish():
    """Los tests comprueban textos en español; el idioma real depende de Windows."""
    i18n.set_language("es")
    yield
    i18n.set_language("es")
