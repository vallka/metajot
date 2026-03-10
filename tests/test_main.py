from fotoai.main import FotoApp


def test_fotoapp_greeting():
    app = FotoApp()
    greeting = app.get_greeting()
    assert greeting == "Welcome to FotoAI v0.1.0"
