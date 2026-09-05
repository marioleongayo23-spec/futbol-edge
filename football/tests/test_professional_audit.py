from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from futbol_pred.backtest.engine import walk_forward
from futbol_pred.coverage import coverage_for_match
from futbol_pred.match_quality import _state_score
from futbol_pred.model.dixon_coles import _tau
from futbol_pred.model.score_matrix import ScoreMatrix


def test_low_score_likelihood_uses_each_fixture_intensity():
    x = np.array([0, 0, 1, 1, 2])
    y = np.array([0, 1, 0, 1, 2])
    home = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    away = np.array([0.5, 1.0, 1.5, 2.0, 2.5])
    assert _tau(x, y, home, away, -0.1) == pytest.approx([1.05, .8, .85, 1.1, 1])


def test_postponed_result_is_not_seen_by_earlier_round():
    class Spy:
        def fit(self, rows):
            self.seen = {r['home'] for r in rows}
        def predict(self, home, away):
            if home == 'round2':
                assert 'postponed' not in self.seen
            return {'1': .4, 'X': .3, '2': .3}
    def match(home, round_, kickoff):
        return dict(home=home, away='B', matchday=round_, kickoff=kickoff,
                    status='FINISHED', home_goals=1, away_goals=0)
    result = walk_forward([match('early', 1, 1), match('postponed', 1, 100),
                           match('round2', 2, 10)], Spy(), min_train_rounds=1)
    assert len(result.records) == 1
    assert result.records[0]['training_cutoff'] == 10


@pytest.mark.parametrize('rows', [[[float('nan')]], [[-1, 2]], [[float('inf')]], []])
def test_invalid_matrix_rejected(rows):
    with pytest.raises(ValueError):
        ScoreMatrix(np.array(rows))


def test_negative_score_does_not_index_last_row():
    matrix = ScoreMatrix(np.ones((3, 3)))
    assert matrix.correct_score(-1, 0) == 0
    assert matrix.under(-1) == 0


def test_future_collection_is_not_verified_evidence():
    assert _state_score({'state': 'scheduled', 'required': False}) == 0


def test_empty_absence_array_does_not_claim_a_successful_check():
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    match = dict(id='test', status='SCHEDULED', kickoff=(now + timedelta(hours=2)).isoformat(),
                 alineacion={'disponibilidad_local': [], 'disponibilidad_visitante': []})
    coverage = coverage_for_match(match, now)
    assert coverage['items']['absences']['state'] == 'missing'


def test_old_market_observation_is_stale_even_if_feed_is_new():
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    match = dict(id='test', status='SCHEDULED', kickoff=(now + timedelta(hours=2)).isoformat(),
                 updatedAt=now.isoformat(), odds={'1x2': {'odds': {'1': 2, 'X': 3, '2': 4}},
                 'meta': {'provider': 'Source', 'source_updated_at': (now - timedelta(hours=10)).isoformat()}})
    item = coverage_for_match(match, now)['items']['odds']
    assert item['state'] == 'stale'
    assert item['source'] == 'Source'


def test_provider_without_credentials_does_not_block_other_providers(monkeypatch):
    from types import SimpleNamespace
    from futbol_pred import pipeline
    from futbol_pred.ingest.api_football import Fixture
    fixture = Fixture(1, 'laliga', 2026, datetime(2026, 9, 5), 'A', 'B', 'SCHEDULED')
    monkeypatch.setattr(pipeline, 'FootballDataClient', lambda: SimpleNamespace(offline=True))
    monkeypatch.setattr(pipeline, 'ApiFootballClient', lambda: SimpleNamespace(
        offline=False, get_fixtures=lambda *args, **kwargs: [fixture, fixture]))
    assert pipeline.get_fixtures('laliga', 2026) == [fixture]


def test_provider_failure_falls_back_without_synthetic_fixtures(monkeypatch):
    from types import SimpleNamespace
    from futbol_pred import pipeline
    from futbol_pred.ingest.openfootball import OpenFootballClient
    from futbol_pred.ingest.football_data_uk import FootballDataUKClient
    from futbol_pred.ingest.api_football import Fixture
    fixture = Fixture(1, 'laliga', 2026, datetime(2026, 9, 5), 'A', 'B', 'SCHEDULED')
    def fail(*args, **kwargs):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(pipeline, 'FootballDataClient', lambda: SimpleNamespace(offline=False, get_matches=fail))
    monkeypatch.setattr(pipeline, 'ApiFootballClient', lambda: SimpleNamespace(offline=True))
    monkeypatch.setattr(OpenFootballClient, 'get_matches', lambda *args, **kwargs: [])
    monkeypatch.setattr(FootballDataUKClient, 'get_fixtures', lambda *args: [fixture])
    assert pipeline.get_fixtures('laliga', 2026) == [fixture]
    monkeypatch.setattr(FootballDataUKClient, 'get_fixtures', lambda *args: [])
    assert pipeline.get_fixtures('laliga', 2026) == []


def test_fit_cutoff_respects_timezones_and_finished_results(monkeypatch):
    from futbol_pred import pipeline
    from futbol_pred.ingest.api_football import Fixture
    class Spy:
        def fit(self, home, away, hg, ag, days_ago):
            assert home == ['past']
            assert days_ago == pytest.approx([1 / 24])
    monkeypatch.setattr(pipeline, 'DixonColesModel', Spy)
    fixtures = [Fixture(i, 'laliga', 2026, datetime.fromisoformat(kickoff), home, 'B', status, 1, 0)
                for i, (kickoff, home, status) in enumerate([
                    ('2026-09-05T11:00:00+02:00', 'past', 'FT'),
                    ('2026-09-05T11:00:00Z', 'future', 'FT'),
                    ('2026-09-05T08:00:00Z', 'live', 'LIVE'),
                ])]
    pipeline.fit_model_from_fixtures(fixtures, datetime.fromisoformat('2026-09-05T12:00:00+02:00'))


def test_calibration_keeps_same_day_games_together_and_orders_postponements():
    from futbol_pred.backtest.ensemble import _paired_records, temporal_split_index
    rows = [dict(home=str(i), away='B', actual='1', round=(i // 10,),
                 kickoff=(20000 + i // 10) * 86400, probs={'1': .5, 'X': .3, '2': .2}) for i in range(50)]
    unordered = rows[30:] + rows[:30]
    assert _paired_records(unordered, rows)[0][0]['home'] == '0'
    assert temporal_split_index(unordered, rows, 35, 20, 10) == 30
    assert temporal_split_index(rows[:10], rows[:10], 5, 2, 2) is None


def test_old_accepted_ensemble_and_residual_are_not_reused_after_version_change():
    from futbol_pred.dashboard import _previous_ensemble_params, _previous_residual_params
    previous = {'model': {'laliga': {'model_version': 'edge-2.0',
        'ensemble': {'accepted': True, 'production': {'dc_weight': .7, 'temperature': 1}},
        'residual': {'accepted': True, 'production': {'converged': True}}}}}
    assert _previous_ensemble_params(previous, 'laliga')['accepted'] is False
    assert _previous_residual_params(previous, 'laliga')['accepted'] is False


def test_backtest_converter_excludes_live_and_partial_scores():
    from futbol_pred.pipeline import fixtures_to_matches
    from futbol_pred.ingest.api_football import Fixture
    rows = [Fixture(i, 'laliga', 2026, datetime(2026, 9, 1), status, 'B', status, 1, goals)
            for i, (status, goals) in enumerate([('FT', 0), ('LIVE', 0), ('FT', None)])]
    result = fixtures_to_matches(rows)
    assert len(result) == 1 and result[0]['home'] == 'FT'
