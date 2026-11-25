"""Walk-forward 검증 + 모델 성능 비교표(REPORT.md) 자동 생성.

    python -m backend.models.evaluate                 # 최근 3시즌(진행 중 시즌 포함)을 평가 기간으로
    python -m backend.models.evaluate --test-seasons 2

규칙 (CLAUDE.md 평가 규칙)
- 시간 순서 분할만 쓴다. 랜덤 분할 없음.
- Elo: 경기 전 레이팅만 사용. 레이팅→확률 변환 계수는 평가 시즌 시작 '전' 경기로만 맞춘다 (시즌마다 다시).
- Dixon-Coles: 평가 기간을 1주 단위로 나눠, 매주 그 주 시작 '전'까지 끝난 경기로 다시 학습한 뒤 그 주 경기를 예측.
- 기준선: 홈팀 항상 승, 리그 평균(평가 시즌 전 H/D/A 비율), 배당 내재 확률(있는 리그만, 경기 전 평균 배당).
- 지표: Log loss, Brier score, 정확도(참고), 보정(calibration) 표·그래프.
- 승무패 정답은 90분 결과(result_90). 연장·승부차기 경기는 무승부로 본다.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select

from backend.config import FOOTBALL_ROOT, load_leagues
from backend.db.init_db import make_engine, make_session_factory
from backend.db.schema import MatchOdds, Prediction
from backend.features.data import load_matches
from backend.models.dixon_coles import DCParams, DixonColes, summarize_matrix
from backend.models.elo import EloParams, OrderedLogit, run_elo
from backend.models.ml_model import build_frame, train_final, walk_forward
from backend.models.selection import MIN_GAIN, MIN_MATCHES, save_selection, select_models

REPORT = Path(__file__).resolve().parent / "REPORT.md"
XG_MIN_MATCHES = 60  # xG 모델은 학습 경기가 이보다 적으면 그 주 예측을 건너뛴다
LGBM_WARMUP_DAYS = 300  # Dixon-Coles 검증 예측이 이만큼 쌓인 뒤부터 LightGBM 평가 (그 전 기간은 학습용)
CALIB_PNG = Path(__file__).resolve().parent / "calibration.png"
PRED_CSV = FOOTBALL_ROOT / "data" / "eval" / "predictions.csv"
OUTCOMES = np.array(["H", "D", "A"])
MODEL_NAMES = {"dixon_coles": "Dixon-Coles", "dixon_coles_xg": "xG Dixon-Coles", "lightgbm": "LightGBM", "elo": "Elo", "league_avg": "리그 평균", "home_always": "홈팀 항상 승",
               "odds": "배당 내재 확률"}


# ── 지표 ──

def onehot(y: np.ndarray) -> np.ndarray:
    return (np.asarray(y)[:, None] == OUTCOMES[None, :]).astype(float)


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    pt = np.sum(p * onehot(y), axis=1)
    if np.any(pt <= 0):
        return float("inf")  # 실제 결과에 확률 0을 준 경우 (예: 홈팀 항상 승)
    return float(-np.mean(np.log(pt)))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(np.sum((p - onehot(y)) ** 2, axis=1)))


def accuracy(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(OUTCOMES[np.argmax(p, axis=1)] == np.asarray(y)))


def calibration_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """승·무·패 세 결과의 (예측 확률, 실제 발생) 쌍을 모두 모아 구간별로 비교."""
    probs, hits = p.ravel(), onehot(y).ravel()
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(probs, edges) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        sel = idx == b
        if sel.sum() == 0:
            continue
        rows.append({"구간": f"{edges[b]:.1f}~{edges[b + 1]:.1f}", "예측 평균": probs[sel].mean(),
                     "실제 비율": hits[sel].mean(), "건수": int(sel.sum())})
    return pd.DataFrame(rows)


# ── 평가 기간 ──

def season_order(label: str) -> int:
    return int(str(label)[:4])


def test_seasons_by_league(df: pd.DataFrame, n: int) -> dict[str, list[str]]:
    out = {}
    for lk, g in df.groupby("league_key"):
        labels = sorted(g["season_label"].unique(), key=season_order)
        out[lk] = labels[-n:] if len(labels) > n else labels[1:]  # 첫 시즌은 최소한 학습용으로 남긴다
    return out


# ── 모델별 예측 ──

def predict_elo(df: pd.DataFrame, elo: pd.DataFrame, leagues: dict, tests: dict[str, list[str]]) -> pd.DataFrame:
    d = df.merge(elo, on="match_id")
    fin = d[d["result_90"].isin(OUTCOMES)]
    out = []
    for lk, seasons in tests.items():
        for s in seasons:
            test = fin[(fin["league_key"] == lk) & (fin["season_label"] == s)]
            if test.empty:
                continue
            start = test["kickoff_utc"].min()
            if leagues[lk].type == "cup":
                train = fin[fin["kickoff_utc"] < start]  # 컵 대회는 경기가 적어 전체 대회로 맞춘다
            else:
                train = fin[(fin["league_key"] == lk) & (fin["kickoff_utc"] < start)]
            train = train[train["kickoff_utc"] >= train["kickoff_utc"].min() + pd.Timedelta(days=180)]  # 초기 레이팅 안정 기간 제외
            if len(train) < 100:
                continue
            ol = OrderedLogit().fit(train["elo_diff"], train["result_90"])
            p = ol.predict(test["elo_diff"])
            out.append(pd.DataFrame({"match_id": test["match_id"].values, "model": "elo",
                                     "pH": p[:, 0], "pD": p[:, 1], "pA": p[:, 2]}))
    return pd.concat(out) if out else pd.DataFrame()


def predict_dc(df: pd.DataFrame, leagues: dict, tests: dict[str, list[str]], log=print,
               params: DCParams | None = None, model_name: str = "dixon_coles") -> pd.DataFrame:
    params = params or DCParams()
    out = []
    for lk, seasons in tests.items():
        if leagues[lk].type != "league":
            continue  # 리그 간 경기(ACL)는 리그별 공격·수비력을 비교할 수 없어 Dixon-Coles 대상에서 제외
        lg = df[df["league_key"] == lk]
        test = lg[lg["season_label"].isin(seasons) & lg["result_90"].isin(OUTCOMES)]
        if params.target == "xg":
            test = test[test["h_xg"].notna()]  # xG 모델은 xG가 있는 경기만 평가
        if test.empty:
            continue
        weeks = test["kickoff_utc"].dt.tz_convert("UTC").dt.floor("D") - pd.to_timedelta(
            test["kickoff_utc"].dt.day_of_week, unit="D")
        n_fit = 0
        for week_start, block in test.groupby(weeks):
            model = DixonColes(params)
            try:
                model.fit(lg, as_of=week_start)  # 그 주 시작 전까지 끝난 경기만
            except ValueError:
                continue
            n_fit += 1
            rows = []
            for _, r in block.iterrows():
                s = summarize_matrix(model.score_matrix(r["home_id"], r["away_id"], bool(r["neutral"])))
                rows.append((r["match_id"], s["home_win"], s["draw"], s["away_win"], s["over_2_5"], s["btts"]))
            out.append(pd.DataFrame(rows, columns=["match_id", "pH", "pD", "pA", "p_over25", "p_btts"]).assign(model=model_name))
        log(f"  {MODEL_NAMES[model_name]} {leagues[lk].name_ko}: {n_fit}번 학습, 평가 대상 {len(test)}경기")
    return pd.concat(out) if out else pd.DataFrame()


def predict_baselines(df: pd.DataFrame, tests: dict[str, list[str]]) -> pd.DataFrame:
    fin = df[df["result_90"].isin(OUTCOMES)]
    out = []
    for lk, seasons in tests.items():
        for s in seasons:
            test = fin[(fin["league_key"] == lk) & (fin["season_label"] == s)]
            if test.empty:
                continue
            train = fin[(fin["league_key"] == lk) & (fin["kickoff_utc"] < test["kickoff_utc"].min())]
            if len(train) < 50:
                continue
            freq = train["result_90"].value_counts(normalize=True).reindex(OUTCOMES, fill_value=0).to_numpy()
            ids = test["match_id"].values
            out.append(pd.DataFrame({"match_id": ids, "model": "league_avg", "pH": freq[0], "pD": freq[1], "pA": freq[2]}))
            out.append(pd.DataFrame({"match_id": ids, "model": "home_always", "pH": 1.0, "pD": 0.0, "pA": 0.0}))
    return pd.concat(out) if out else pd.DataFrame()


def predict_odds(session, match_ids) -> pd.DataFrame:
    rows = session.execute(select(MatchOdds.match_id, MatchOdds.home, MatchOdds.draw, MatchOdds.away)
                           .where(MatchOdds.bookmaker == "avg", MatchOdds.kind == "pre")).all()
    o = pd.DataFrame(rows, columns=["match_id", "h", "d", "a"])
    o = o[o["match_id"].isin(set(match_ids))].dropna()
    inv = 1 / o[["h", "d", "a"]].to_numpy()
    p = inv / inv.sum(axis=1, keepdims=True)  # 북메이커 마진 제거 (정규화)
    return pd.DataFrame({"match_id": o["match_id"].values, "model": "odds", "pH": p[:, 0], "pD": p[:, 1], "pA": p[:, 2]})


# ── 보고서 ──

def metrics_row(sub: pd.DataFrame) -> dict:
    p, y = sub[["pH", "pD", "pA"]].to_numpy(), sub["result_90"].to_numpy()
    return {"경기 수": len(sub), "Log loss": log_loss(p, y), "Brier": brier(p, y), "정확도": accuracy(p, y)}


def fmt_table(rows: list[dict], cols: list[str]) -> str:
    def f(v):
        if isinstance(v, float):
            return "∞" if np.isinf(v) else f"{v:.4f}" if v < 10 else f"{v:.1f}"
        return str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(f(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join(lines)


def plot_calibration(preds: pd.DataFrame, path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return False
    ko = [f.name for f in font_manager.fontManager.ttflist
          if any(k in f.name for k in ("Noto Sans CJK", "Nanum", "Malgun", "AppleGothic", "WenQuanYi Zen Hei"))]
    if ko:
        plt.rcParams["font.family"] = ko[0]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(6, 6), dpi=110)
    ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--", label="완벽한 보정")
    for model, color in (("dixon_coles", "#1f6feb"), ("elo", "#d97706"), ("odds", "#16a34a")):
        sub = preds[preds["model"] == model]
        if sub.empty:
            continue
        t = calibration_table(sub[["pH", "pD", "pA"]].to_numpy(), sub["result_90"].to_numpy())
        ax.plot(t["예측 평균"], t["실제 비율"], marker="o", color=color, label=MODEL_NAMES[model])
    ax.set_xlabel("예측 확률")
    ax.set_ylabel("실제 발생 비율")
    ax.set_title("보정 그래프 (승·무·패 확률 전체, 평가 기간)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


def build_report(preds: pd.DataFrame, df: pd.DataFrame, leagues: dict, tests: dict, generated: datetime) -> str:
    preds = preds.merge(df[["match_id", "league_key", "result_90", "hg", "ag"]], on="match_id")
    dc_ids = set(preds.loc[preds["model"] == "dixon_coles", "match_id"])
    elo_ids = set(preds.loc[preds["model"] == "elo", "match_id"])
    common = dc_ids & elo_ids  # 두 메인 모델이 모두 예측한 경기만으로 공정하게 비교

    lines = [
        "# 예측 모델 성능 비교 (자동 생성)", "",
        f"_생성: {generated:%Y-%m-%d %H:%M} UTC — `python -m backend.models.evaluate`_", "",
        "## 평가 방법", "",
        "- **시간 순서 검증(walk-forward)**: 랜덤 분할 없이, 각 경기는 그 경기 이전 데이터로만 학습한 모델로 예측했다.",
        "  - Dixon-Coles: 평가 기간을 주 단위로 나눠 매주 그 주 시작 전까지 끝난 경기(최근 2년, 시간 감쇠)로 다시 학습",
        "  - Elo: 경기 전 레이팅 사용. 레이팅→승무패 확률 변환 계수는 평가 시즌 시작 전 경기로만 맞춤",
        "- **정답**: 90분 결과 (연장·승부차기 경기는 무승부)",
        "- **지표**: Log loss·Brier score는 **낮을수록 좋다**. 정확도는 참고용 (가장 높은 확률을 준 결과가 맞은 비율)",
        "- **기준선**: 홈팀 항상 승(확률 1/0/0), 리그 평균(평가 시즌 전 승무패 비율), 배당 내재 확률(경기 전 평균 배당, 마진 제거)",
        "- 평가 기간: " + ", ".join(f"{leagues[k].name_ko} {'·'.join(v)}" for k, v in tests.items()),
        "",
    ]

    def block(ids, title, note=""):
        sub = preds[preds["match_id"].isin(ids)]
        rows = [{"모델": MODEL_NAMES[m], **metrics_row(sub[sub["model"] == m])}
                for m in ("dixon_coles", "elo", "league_avg", "home_always") if (sub["model"] == m).any()]
        rows.sort(key=lambda r: r["Log loss"])
        return [f"## {title}", "", note, "", fmt_table(rows, ["모델", "경기 수", "Log loss", "Brier", "정확도"]), ""]

    lines += block(common, "전체 (리그 경기, Dixon-Coles·Elo 공통 경기)",
                   "홈팀 항상 승은 무승부·원정승에 확률 0을 주므로 Log loss가 무한대(∞)다.")

    per = []
    for lk in tests:
        if leagues[lk].type != "league":
            continue
        ids = {i for i in common if i in set(df.loc[df["league_key"] == lk, "match_id"])}
        sub = preds[preds["match_id"].isin(ids)]
        if sub.empty:
            continue
        row = {"대회": leagues[lk].name_ko, "경기 수": len(ids)}
        for m in ("dixon_coles", "elo", "league_avg"):
            s = sub[sub["model"] == m]
            if not s.empty:
                row[f"{MODEL_NAMES[m]} LL"] = log_loss(s[["pH", "pD", "pA"]].to_numpy(), s["result_90"].to_numpy())
        best = min((k for k in row if k.endswith("LL")), key=lambda k: row[k])
        row["가장 좋은 모델"] = best.replace(" LL", "")
        per.append(row)
    lines += ["## 대회별 Log loss (낮을수록 좋음)", "",
              fmt_table(per, ["대회", "경기 수", "Dixon-Coles LL", "Elo LL", "리그 평균 LL", "가장 좋은 모델"]), ""]

    odds_ids = set(preds.loc[preds["model"] == "odds", "match_id"]) & common
    if odds_ids:
        sub = preds[preds["match_id"].isin(odds_ids)]
        rows = [{"모델": MODEL_NAMES[m], **metrics_row(sub[sub["model"] == m])} for m in ("odds", "dixon_coles", "elo")]
        lines += ["## 배당 내재 확률과 비교", "",
                  "배당은 시장 정보(부상·라인업 등)가 반영된 강한 기준선이다. 통계 모델이 이보다 나쁜 것은 정상이며, 차이가 얼마나 되는지를 본다.",
                  "(배당은 평가용으로만 쓰며 사이트에는 표시하지 않는다.)", "",
                  fmt_table(rows, ["모델", "경기 수", "Log loss", "Brier", "정확도"]), ""]

    cup = preds[(preds["model"] == "elo") & preds["league_key"].map(lambda k: leagues[k].type == "cup")]
    if not cup.empty:
        rows = [{"모델": "Elo", **metrics_row(cup)}]
        base = preds[(preds["model"] == "league_avg") & preds["match_id"].isin(set(cup["match_id"]))]
        if not base.empty:
            rows.append({"모델": "대회 평균", **metrics_row(base)})
        lines += ["## AFC 챔피언스리그 (컵 대회, Elo만 적용)", "",
                  "서로 다른 리그 팀끼리 만나므로 리그별 Dixon-Coles를 쓸 수 없어 리그 통합 Elo로만 예측한다. 경기 수가 적어 참고용.", "",
                  fmt_table(rows, ["모델", "경기 수", "Log loss", "Brier", "정확도"]), ""]

    lines += ["## 보정(calibration)", "",
              "예측 확률 구간별로 실제 발생 비율을 비교한다. 대각선에 가까울수록 확률을 믿을 수 있다.", ""]
    if CALIB_PNG.exists():
        lines += [f"![보정 그래프]({CALIB_PNG.name})", ""]
    for m in ("dixon_coles", "elo"):
        sub = preds[(preds["model"] == m) & preds["match_id"].isin(common)]
        t = calibration_table(sub[["pH", "pD", "pA"]].to_numpy(), sub["result_90"].to_numpy())
        lines += [f"### {MODEL_NAMES[m]}", "", fmt_table(t.to_dict("records"), list(t.columns)), ""]

    dc = preds[(preds["model"] == "dixon_coles") & preds["match_id"].isin(common)].dropna(subset=["p_over25"])
    if not dc.empty:
        total = dc["hg"] + dc["ag"]
        ou_y = (total > 2.5).astype(float).to_numpy()
        bt_y = ((dc["hg"] > 0) & (dc["ag"] > 0)).astype(float).to_numpy()

        def bin_ll(p, y):
            p = np.clip(p, 1e-12, 1 - 1e-12)
            return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

        lines += ["## 오버/언더 2.5·양팀득점 (Dixon-Coles)", "",
                  fmt_table([
                      {"항목": "2.5골 초과", "경기 수": len(dc), "모델 Log loss": bin_ll(dc["p_over25"].to_numpy(), ou_y),
                       "기준선(50%) Log loss": float(np.log(2)), "예측 평균": float(dc["p_over25"].mean()), "실제 비율": float(ou_y.mean())},
                      {"항목": "양팀 득점", "경기 수": len(dc), "모델 Log loss": bin_ll(dc["p_btts"].to_numpy(), bt_y),
                       "기준선(50%) Log loss": float(np.log(2)), "예측 평균": float(dc["p_btts"].mean()), "실제 비율": float(bt_y.mean())},
                  ], ["항목", "경기 수", "모델 Log loss", "기준선(50%) Log loss", "예측 평균", "실제 비율"]), ""]
    lines += ["## 데이터 한계", "",
              "- 아시아 대회(K리그1·J1·ACL)는 경기 통계·xG가 없어 골 기반 모델만 쓴다.",
              "- UEFA 대회·국내 컵 경기는 수집하지 않아 Elo가 그 경기들의 정보를 반영하지 못한다.",
              "- xG는 2026/27 시즌부터만 있어 xG 기반 모델(8단계)은 데이터가 더 쌓인 뒤 평가한다.", ""]
    return "\n".join(lines)


def advanced_section(preds: pd.DataFrame, df: pd.DataFrame, leagues: dict, sel: dict) -> str:
    p = preds.merge(df[["match_id", "league_key", "result_90"]], on="match_id")
    p = p[p["result_90"].isin(OUTCOMES)]
    lines = ["", "## 8단계: 고급 모델 비교", ""]

    def compare(models, title, note):
        ids = None
        for m in models:
            s_ = set(p.loc[p["model"] == m, "match_id"])
            ids = s_ if ids is None else ids & s_
        if not ids:
            return [f"### {title}", "", "비교할 경기가 없음", ""]
        sub = p[p["match_id"].isin(ids)]
        rows = sorted(({"모델": MODEL_NAMES[m], **metrics_row(sub[sub["model"] == m])} for m in models),
                      key=lambda r: r["Log loss"])
        return [f"### {title}", "", note, "", fmt_table(rows, ["모델", "경기 수", "Log loss", "Brier", "정확도"]), ""]

    lines += compare(["lightgbm", "dixon_coles", "elo"], "LightGBM (전체 리그, 같은 경기로 비교)",
                     "피처: 폼·득실·휴식일·H2H·xG/슈팅(있을 때)·Elo·Dixon-Coles 확률·대회. 매달 1일 그 전까지 끝난 경기로 다시 학습.")
    xg_n = int((p["model"] == "dixon_coles_xg").sum())
    lines += compare(["dixon_coles_xg", "dixon_coles"], "xG Dixon-Coles (xG 있는 리그, 같은 경기로 비교)",
                     f"⚠️ **데이터 부족 — 참고용**: xG는 2026/27 시즌부터만 있어 {xg_n}경기만 평가했고, 학습 데이터도 시즌 초반 몇 달뿐이다. "
                     "시즌이 진행되며 매주 재검증한다.")
    rows = []
    for lk, v in sorted(sel.items(), key=lambda kv: leagues[kv[0]].name_ko):
        best = v["comparisons"].get(v["main"], {}) if v["main"] != v["default"] else {}
        rows.append({"대회": leagues[lk].name_ko, "대표 모델": MODEL_NAMES[v["main"]], "기본": MODEL_NAMES[v["default"]],
                     "개선": f"{best['gain']:.4f}" if best else "-", "이유": v["reason"]})
    lines += ["### 사이트에 반영하는 대표 모델", "",
              f"기본 모델보다 같은 경기에서 Log loss가 {MIN_GAIN} 이상 낮고 비교 경기가 {MIN_MATCHES}개 이상인 모델만 대표로 바꾼다.", "",
              fmt_table(rows, ["대회", "대표 모델", "기본", "개선", "이유"]), "",
              "⚠️ 모델 선택과 이 성능표에 같은 검증 기간을 썼으므로, 선택된 모델의 개선 폭은 실제보다 조금 좋게 보일 수 있다 "
              "(여러 후보 중 가장 좋은 것을 고른 효과). 매주 새로 쌓이는 경기로 다시 검증·선택한다.", ""]
    return "\n".join(lines)


def save_backtest(session, preds: pd.DataFrame) -> None:
    """walk-forward 예측을 predictions 테이블(kind='backtest')에 저장 — 모델 성능 페이지용. 매번 통째로 바꾼다."""
    session.execute(delete(Prediction).where(Prediction.kind == "backtest"))
    made = datetime.now(timezone.utc)
    rows = []
    for r in preds[preds["model"].isin(["dixon_coles", "elo", "lightgbm", "dixon_coles_xg"])].itertuples(index=False):
        rows.append({"match_id": int(r.match_id), "model": r.model, "kind": "backtest", "p_home": float(r.pH),
                     "p_draw": float(r.pD), "p_away": float(r.pA),
                     "p_over_2_5": None if pd.isna(getattr(r, "p_over25", None)) else float(r.p_over25),
                     "p_btts": None if pd.isna(getattr(r, "p_btts", None)) else float(r.p_btts), "made_at": made})
    if rows:
        session.execute(insert(Prediction), rows)
    session.commit()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="walk-forward 검증 후 REPORT.md 생성")
    ap.add_argument("--test-seasons", type=int, default=3)
    args = ap.parse_args(argv)
    leagues = {l.key: l for l in load_leagues()}
    with make_session_factory(make_engine())() as session:
        df = load_matches(session)
        df = df[df["league_key"].isin([k for k, l in leagues.items() if l.enabled])]
        tests = test_seasons_by_league(df, args.test_seasons)
        print("Elo 계산 중...")
        elo = run_elo(df, EloParams())
        parts = [predict_elo(df, elo, leagues, tests)]
        print("Dixon-Coles walk-forward 학습·예측 중...")
        parts.append(predict_dc(df, leagues, tests))
        parts.append(predict_baselines(df, tests))
        preds = pd.concat([p for p in parts if not p.empty], ignore_index=True)
        # ── 8단계: xG Dixon-Coles (xG 있는 시즌만) ──
        print("xG Dixon-Coles walk-forward 학습·예측 중...")
        xg_tests = {k: [v[-1]] for k, v in tests.items() if df.loc[df["league_key"] == k, "h_xg"].notna().any()}
        preds = pd.concat([preds, predict_dc(df, leagues, xg_tests, params=DCParams(target="xg", min_matches=XG_MIN_MATCHES),
                                             model_name="dixon_coles_xg")], ignore_index=True)
        # ── 8단계: LightGBM (Elo·Dixon-Coles 확률·폼·휴식일 등) ──
        print("LightGBM walk-forward 학습·예측 중...")
        types = {k: l.type for k, l in leagues.items() if l.enabled}
        frame = build_frame(df, elo, preds[preds["model"] == "dixon_coles"], types)
        dc_start = df.loc[df["match_id"].isin(preds.loc[preds["model"] == "dixon_coles", "match_id"]), "kickoff_utc"].min()
        lgbm_preds, iters = walk_forward(frame, dc_start + pd.Timedelta(days=LGBM_WARMUP_DAYS), log_fn=print)
        preds = pd.concat([preds, lgbm_preds.assign(model="lightgbm")], ignore_index=True)
        if iters:
            train_final(frame, int(np.median(iters)))  # 사이트용 최종 모델 저장
        # ── 대회별 대표 모델 선택 ──
        sel = select_models(preds.merge(df[["match_id", "league_key", "result_90"]], on="match_id"), types)
        save_selection(sel)
        preds = pd.concat([preds, predict_odds(session, preds["match_id"].unique())], ignore_index=True)
        save_backtest(session, preds)
    PRED_CSV.parent.mkdir(parents=True, exist_ok=True)
    preds.to_csv(PRED_CSV, index=False)
    merged = preds.merge(df[["match_id", "result_90"]], on="match_id")
    plot_calibration(merged[merged["match_id"].isin(set(preds.loc[preds["model"] == "dixon_coles", "match_id"]))], CALIB_PNG)
    REPORT.write_text(build_report(preds, df, leagues, tests, datetime.now(timezone.utc))
                      + advanced_section(preds, df, leagues, sel), encoding="utf-8")
    print(f"보고서 생성: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
