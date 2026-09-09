from quantedge.gate.evaluate import GateInput, NO_DEMOSTRADO, SUPERADO, evaluate_gate

THR = {
    "target_daily": 0.004, "median_monthly_min": 0.0, "max_drawdown_limit": 0.15,
    "min_markets": 3, "max_single_month_share": 0.5, "min_future_sessions": 60,
    "dsr_min": 0.95, "pbo_max": 0.5, "bootstrap_geo_daily_lb_min": 0.0,
}


def _passing_input() -> GateInput:
    return GateInput(
        oos_monthly_geo_daily_mean_mean=0.0050,
        oos_monthly_geo_daily_mean_median=0.0045,
        oos_max_drawdown=0.10,
        oos_geo_daily_mean=0.0050,
        benchmark_geo_daily_mean=0.0010,
        deflated_sharpe=0.99,
        pbo=0.10,
        bootstrap_geo_daily_lb=0.0008,
        n_markets_total=6,
        n_markets_meeting_target=4,
        max_single_month_share=0.3,
        geo_daily_leave_best_out=0.004,
        cost_stress={"1.0": 0.005, "1.5": 0.003, "2.0": 0.001},
        n_future_sessions=90,
        all_shadow_only=True,
        data_is_real_dual_source=True,
        forward_sessions_are_live=True,
    )


def test_all_conditions_pass_gives_superado():
    res = evaluate_gate(_passing_input(), THR)
    assert res.decision == SUPERADO
    assert res.missing_evidence == []


def test_single_failure_blocks():
    inp = _passing_input()
    inp.data_is_real_dual_source = False  # una sola condición falla
    res = evaluate_gate(inp, THR)
    assert res.decision == NO_DEMOSTRADO
    assert any("datos_reales" in m for m in res.missing_evidence)


def test_target_miss_blocks():
    inp = _passing_input()
    inp.oos_monthly_geo_daily_mean_mean = 0.001  # por debajo del objetivo
    res = evaluate_gate(inp, THR)
    assert res.decision == NO_DEMOSTRADO


def test_cost_stress_negative_blocks():
    inp = _passing_input()
    inp.cost_stress = {"1.0": 0.005, "2.0": -0.001}
    res = evaluate_gate(inp, THR)
    assert res.decision == NO_DEMOSTRADO
