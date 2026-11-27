import pytest


@pytest.fixture(autouse=True)
def _no_network_forecast(monkeypatch):
    """다른 탭 차트의 예상선은 야후에서 봉을 받으므로, 테스트에서는 끈다 (해당 테스트에서 따로 확인)."""
    from autostock import board
    monkeypatch.setattr(board, "quick_forecast", lambda *a, **k: None)
