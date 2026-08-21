"""App web (Streamlit) del sistema de predicción de fútbol.

Ejecuta en vivo el pipeline con datos reales (football-data.org para fixtures/
resultados, football-data.co.uk para estadísticas) y ofrece:
  * Predicciones de la próxima jornada (1X2, marcador, goles, over/under, BTTS).
  * Jugar con líneas y cuotas: mueve la línea ± y ve prob. del modelo, cuota
    justa y value contra la cuota que introduzcas.
  * Estadísticas por equipo y totales: remates, tiros a puerta, córners, faltas,
    tarjetas, con prob. over/under de cualquier línea.
  * La quiniela (14 + Pleno al 15) con dobles/triples en los inciertos.
  * Value bets del día con stake sugerido (Kelly).

Despliegue: Streamlit Community Cloud (ver football/docs/DESPLIEGUE.md).
Local:  streamlit run football/webapp/app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

# Los Secrets de Streamlit Cloud se inyectan como variables de entorno ANTES de
# importar la config (que las lee con os.getenv al cargarse).
try:
    for _k in ("FOOTBALL_DATA_API_KEY", "API_FOOTBALL_KEY", "ODDS_API_KEY",
               "DATABASE_URL"):
        if _k in st.secrets:
            os.environ.setdefault(_k, str(st.secrets[_k]))
except Exception:
    pass  # sin fichero de secrets (desarrollo local): se usa el entorno normal

# Permite importar futbol_pred sin instalar el paquete.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from futbol_pred.config import LEAGUE_META, settings  # noqa: E402
from futbol_pred.ingest.football_data import FootballDataClient  # noqa: E402
from futbol_pred.ingest.football_data_uk import FootballDataUKClient  # noqa: E402
from futbol_pred.model import DixonColesModel  # noqa: E402
from futbol_pred.model.stats_markets import StatsPredictor  # noqa: E402
from futbol_pred.pipeline import fit_model_from_fixtures  # noqa: E402
from futbol_pred.scheduling import next_fixtures  # noqa: E402
from futbol_pred.value import find_value  # noqa: E402
from futbol_pred.value.bankroll import BankrollPolicy  # noqa: E402

st.set_page_config(page_title="Predicción Fútbol", page_icon="⚽", layout="wide")

LEAGUES = {"LaLiga": "laliga", "Segunda": "segunda", "Champions": "champions"}


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=3600, show_spinner="Cargando datos y ajustando modelo...")
def load_league(league: str, season: int):
    """Descarga fixtures + stats y ajusta los modelos (cacheado 1h)."""
    fd = FootballDataClient()
    fixtures = fd.get_matches(league, season=season)
    model = fit_model_from_fixtures(fixtures)

    stats_pred = None
    if league in ("laliga", "segunda"):
        try:
            rows = FootballDataUKClient().get_stats(league, season)
            stats_pred = StatsPredictor().fit(rows)
        except Exception:
            stats_pred = None

    # Serializamos lo necesario para no arrastrar objetos no cacheables.
    return {
        "fixtures": [_fx_dict(f) for f in fixtures],
        "attack": model.attack,
        "defence": model.defence,
        "home_adv": model.home_adv,
        "rho": model.rho,
        "offline": fd.offline,
        "has_stats": stats_pred is not None,
        "_model": model,
        "_stats": stats_pred,
    }


def _fx_dict(f) -> dict:
    return {
        "home": f.home_team, "away": f.away_team,
        "home_goals": f.home_goals, "away_goals": f.away_goals,
        "matchday": f.matchday, "stage": f.stage,
        "kickoff": f.kickoff.timestamp() if f.kickoff else None,
        "status": f.status,
    }


def upcoming(fixtures: list[dict], league: str) -> list[dict]:
    tpr = LEAGUE_META.get(league, {}).get("teams_per_round")
    return next_fixtures(fixtures, teams_per_round=tpr)


# ------------------------------------------------------------------ UI
st.title("⚽ Sistema de predicción de fútbol")
st.caption("Probabilidades y ventaja estadística — no certezas. Juega con responsabilidad.")

with st.sidebar:
    st.header("Configuración")
    league_label = st.selectbox("Competición", list(LEAGUES))
    league = LEAGUES[league_label]
    season = st.number_input("Temporada (año de inicio)", 2015, 2035, settings.season)
    bankroll = st.number_input("Bankroll (€)", 0, 1_000_000, int(settings.bankroll))
    st.divider()
    st.caption("Datos: football-data.org + football-data.co.uk")

data = load_league(league, int(season))
model: DixonColesModel = data["_model"]
stats: StatsPredictor | None = data["_stats"]

if data["offline"]:
    st.warning("Modo OFFLINE (sin FOOTBALL_DATA_API_KEY): datos de ejemplo. "
               "Configura la clave en los Secrets para datos reales.")

fixtures = data["fixtures"]
next_matches = upcoming(fixtures, league)

tab_jornada, tab_lineas, tab_quiniela, tab_value = st.tabs(
    ["📅 Jornada", "🎚️ Jugar con líneas", "🎫 Quiniela", "💰 Value bets"]
)


def predict_1x2(home: str, away: str):
    if home in model.attack and away in model.attack:
        return model.predict_matrix(home, away)
    return None


def _render_stats_table(sp: dict) -> None:
    import pandas as pd

    labels = {"goals": "Goles", "shots": "Remates", "sot": "Tiros a puerta",
              "corners": "Córners", "fouls": "Faltas", "yellows": "Amarillas",
              "reds": "Rojas"}
    rows = []
    for stat, lab in labels.items():
        if stat in sp:
            d = sp[stat]
            rows.append({"Métrica": lab, "Local": d["home"],
                         "Visitante": d["away"], "Total": d["total"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# --- Tab: predicciones de la jornada -----------------------------------
with tab_jornada:
    st.subheader(f"Próxima jornada — {league_label}")
    if not next_matches:
        st.info("No hay partidos próximos detectados para esta competición/temporada.")
    for m in next_matches:
        sm = predict_1x2(m["home"], m["away"])
        with st.container(border=True):
            st.markdown(f"### {m['home']} vs {m['away']}")
            if sm is None:
                st.caption("Sin datos suficientes del modelo para este partido.")
                continue
            p = sm.one_x_two()
            eh, ea = sm.expected_goals()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("1", f"{p['1']*100:.0f}%")
            c2.metric("X", f"{p['X']*100:.0f}%")
            c3.metric("2", f"{p['2']*100:.0f}%")
            top = sm.top_correct_scores(1)[0]
            c4.metric("Marcador", f"{top[0]}-{top[1]}")
            c5, c6, c7 = st.columns(3)
            c5.metric("xG local / visit.", f"{eh:.2f} / {ea:.2f}")
            c6.metric("Over 2.5", f"{sm.over(2.5)*100:.0f}%")
            c7.metric("BTTS", f"{sm.btts()['yes']*100:.0f}%")

            if stats:
                sp = stats.predict_fixture(m["home"], m["away"])
                if sp:
                    st.markdown("**Estadísticas esperadas (local · visitante · total)**")
                    _render_stats_table(sp)


# --- Tab: jugar con líneas y cuotas ------------------------------------
with tab_lineas:
    st.subheader("Jugar con líneas y cuotas")
    teams = sorted(model.attack)
    colh, cola = st.columns(2)
    home = colh.selectbox("Local", teams, index=0)
    away = cola.selectbox("Visitante", teams, index=min(1, len(teams) - 1))
    sm = predict_1x2(home, away)
    if sm is None:
        st.info("Elige dos equipos con datos del modelo.")
    else:
        market = st.radio("Mercado", ["Over/Under goles", "Hándicap asiático",
                                       "BTTS", "1X2"], horizontal=True)
        if market == "Over/Under goles":
            line = st.slider("Línea de goles", 0.5, 6.5, 2.5, 0.5)
            prob = sm.over(line)
            side = "Over"
        elif market == "Hándicap asiático":
            line = st.slider("Hándicap (local)", -3.0, 3.0, -0.5, 0.25)
            ah = sm.asian_handicap(line, "home")
            prob = ah["win"]
            side = f"Local {line:+g}"
        elif market == "BTTS":
            prob = sm.btts()["yes"]
            side = "BTTS Sí"
            line = None
        else:
            sel = st.radio("Signo", ["1", "X", "2"], horizontal=True)
            prob = sm.one_x_two()[sel]
            side = sel
            line = None

        fair = 1 / prob if prob > 0 else float("inf")
        c1, c2, c3 = st.columns(3)
        c1.metric("Prob. del modelo", f"{prob*100:.1f}%")
        c2.metric("Cuota justa", f"{fair:.2f}")
        odds = c3.number_input("Cuota de la casa", 1.01, 100.0, round(fair, 2), 0.01)
        bet = find_value(prob, odds, market, side, bankroll=bankroll,
                         policy=BankrollPolicy(min_edge=settings.min_edge))
        if bet.edge > 0:
            st.success(f"✅ VALUE en «{side}»: edge {bet.edge*100:.1f}% · "
                       f"stake sugerido {bet.stake:.2f} € (Kelly)")
        else:
            st.info(f"Sin value en «{side}» a cuota {odds:.2f} "
                    f"(edge {bet.edge*100:.1f}%).")

        if stats and market == "Over/Under goles":
            st.divider()
            st.markdown("**Over/Under de otras estadísticas**")
            stat_lbl = {"corners": "Córners", "shots": "Remates",
                        "sot": "Tiros a puerta", "fouls": "Faltas",
                        "yellows": "Amarillas"}
            colst, colside, colline = st.columns(3)
            stat = colst.selectbox("Estadística", list(stat_lbl),
                                   format_func=lambda s: stat_lbl[s])
            sside = colside.selectbox("Lado", ["total", "home", "away"])
            sline = colline.slider("Línea", 0.5, 20.5, 9.5, 1.0)
            try:
                mk = stats.market(home, away, stat, sside, sline)
                st.metric(f"P(over {sline} {stat_lbl[stat]} · {sside})",
                          f"{mk['prob_over']*100:.0f}%",
                          help=f"media esperada: {mk['mean']}")
            except KeyError:
                st.caption("Estadística no disponible para estos equipos.")


# --- Tab: quiniela ------------------------------------------------------
with tab_quiniela:
    st.subheader("Quiniela")
    quiniela_matches = next_matches[:14]
    if len(quiniela_matches) < 14:
        st.info(f"Se necesitan 14 partidos; hay {len(quiniela_matches)} en la próxima "
                "jornada. La quiniela oficial mezcla 1ª y 2ª división.")
    triples = st.slider("Triples (partidos con los 3 signos)", 0, 6, 2)
    doubles = st.slider("Dobles (2 signos)", 0, 8, 4)
    from futbol_pred.quiniela import MatchForecast, generate_quiniela

    forecasts = []
    for m in quiniela_matches:
        sm = predict_1x2(m["home"], m["away"])
        if sm is None:
            continue
        forecasts.append(MatchForecast(m["home"], m["away"], sm.one_x_two()))
    if len(forecasts) == 14:
        bet = generate_quiniela(forecasts, triples=triples, doubles=doubles)
        import pandas as pd
        rows = []
        for i, f in enumerate(forecasts):
            sel = bet.multiples.get(i, [bet.base[i]])
            rows.append({
                "Nº": i + 1, "Local": f.home, "Visitante": f.away,
                "1": f"{f.probs['1']*100:.0f}%", "X": f"{f.probs['X']*100:.0f}%",
                "2": f"{f.probs['2']*100:.0f}%",
                "Signo": "".join(sel),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(f"Coste: {bet.cost_columns} columnas · "
                   f"Prob. pleno al 14: {bet.prob_all_correct(forecasts)*100:.3f}%")


# --- Tab: value bets ----------------------------------------------------
with tab_value:
    st.subheader("Value bets de la jornada")
    st.caption("Introduce cuotas 1X2 de tu casa para detectar ventaja. "
               "Deja a 0 para omitir un partido.")
    policy = BankrollPolicy(min_edge=settings.min_edge)
    import pandas as pd
    results = []
    for m in next_matches:
        sm = predict_1x2(m["home"], m["away"])
        if sm is None:
            continue
        p = sm.one_x_two()
        with st.expander(f"{m['home']} vs {m['away']}  —  "
                         f"1 {p['1']*100:.0f}% · X {p['X']*100:.0f}% · 2 {p['2']*100:.0f}%"):
            c1, c2, c3 = st.columns(3)
            o1 = c1.number_input("Cuota 1", 0.0, 100.0, 0.0, 0.01, key=f"o1_{m['home']}")
            ox = c2.number_input("Cuota X", 0.0, 100.0, 0.0, 0.01, key=f"ox_{m['home']}")
            o2 = c3.number_input("Cuota 2", 0.0, 100.0, 0.0, 0.01, key=f"o2_{m['home']}")
            for sel, odd in (("1", o1), ("X", ox), ("2", o2)):
                if odd > 1.0:
                    bet = find_value(p[sel], odd, "1x2", sel, bankroll=bankroll,
                                     policy=policy)
                    if bet.edge > settings.min_edge:
                        results.append({
                            "Partido": f"{m['home']} vs {m['away']}",
                            "Sel": sel, "Cuota": odd,
                            "Edge": f"{bet.edge*100:.1f}%",
                            "Stake": f"{bet.stake:.2f} €",
                        })
    if results:
        st.markdown("### 🎯 Value detectado")
        st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
