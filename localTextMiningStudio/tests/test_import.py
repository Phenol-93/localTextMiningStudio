from importlib import import_module


def test_app_main_module_can_be_imported() -> None:
    module = import_module("app.main")

    assert hasattr(module, "main")
