from pathlib import Path


def test_shadow_no_tiene_wiring_en_modelo_de_produccion():
    root = Path(__file__).resolve().parents[1] / "src" / "futbol_pred"
    dashboard = (root / "dashboard.py").read_text(encoding="utf-8")
    pipeline = (root / "pipeline.py").read_text(encoding="utf-8")
    hot = (root / "hot_refresh.py").read_text(encoding="utf-8")

    assert "stat_shadow" not in dashboard
    assert "stat_shadow" not in pipeline
    assert "stat_shadow" not in hot


def test_shadow_solo_se_conecta_a_snapshot_prepartido():
    root = Path(__file__).resolve().parents[1] / "src" / "futbol_pred"
    snapshots = (root / "prediction_snapshots.py").read_text(encoding="utf-8")
    assert "build_stat_shadow(match)" in snapshots
    assert 'out["stat_challengers"] = shadow' in snapshots
    assert '"stat_challengers",' not in snapshots
