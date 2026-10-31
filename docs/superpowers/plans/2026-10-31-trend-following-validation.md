# Trend Following Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar no backtester a candidata A (trend following multi-prazo com controle de volatilidade) e o controle B (SMA200), rodar o protocolo de validação pré-registrado e gerar um relatório com APROVADO/REPROVADO por critério e a recomendação.

**Architecture:** `backtest/trend.py` contém funções puras (sinais e simulação diária com execução na abertura de t+1). `backtest/validate.py` orquestra os testes 4.2.1–4.2.5, avalia C1–C5 e escreve o relatório. Reaproveita `backtest/data.py` (com ajuste para ativos listados tarde e detecção de lacunas) e `backtest/metrics.py`.

**Tech Stack:** Python 3.11+, pandas ≥ 2.2, numpy, pytest. Sem dependências novas.

**Spec:** `docs/superpowers/specs/2026-10-31-trend-following-validation-design.md`

## Global Constraints

- Dados somente de candles **1d** de `data.binance.vision`, via `backtest/data.py`, período `2019-01` a `2026-09`.
- Decisão no fechamento de `t`, execução na **abertura de `t+1`**; nunca usar dado posterior a `t` para `target[t]`.
- Custos padrão: `fee = 0.001`, `slippage = 0.0005` por execução; custos em dobro: `fee = 0.002`, `slippage = 0.002`.
- Capital padrão `10_000`; carteira principal = 50% BTCUSDT + 50% ETHUSDT, blocos independentes, sem rebalanceamento entre blocos; caixa rende 0%.
- Parâmetros padrão de A: `lookbacks=(20, 50, 100, 200)`, `vol_window=30`, `vol_target=0.50`, `band=0.10`. B: SMA de 200 dias, `band=0`, sem controle de volatilidade.
- Constantes de critério (copiar exatamente): `C1_MAX_DD_RATIO = 0.60`, `C2_MIN_CAGR_RATIO = 0.75`, `C4_MIN_PASS_SHARE = 0.70`, `OOS_ALERT_MIN_ASSETS = 3`.
- `trend.py` sem I/O. Sem preenchimento silencioso de dados faltantes.
- Mensagens de commit terminam com as linhas de atribuição do repositório.

## Review Focus

1. **Preço constante (volatilidade 0)** → `scale` deve ser 1 (não divisão por zero/NaN). Teste em Task 2.
2. **Comprar até 100% com taxa** → o caixa nunca fica negativo; a compra é limitada a `cash / (1 + fee)`. Teste em Task 3.
3. **Último dia da série** → `target` do último dia não tem abertura seguinte; nenhuma operação, nenhum erro de índice. Teste em Task 3.
4. **Ativo listado depois do início comum (SOLUSDT)** → no teste fora da amostra, A e HODL desse ativo começam no primeiro dia aquecido do próprio ativo; nada quebra. Teste em Task 5.
5. **Métrica NaN** (ex.: CAGR indefinido) → o critério correspondente é REPROVADO, sem exceção. Teste em Task 4.

---

### Task 1: Dados — ativos listados tarde e detecção de lacunas

**Files:**
- Modify: `backtest/data.py` (`download`, `load`)
- Test: `backtest/tests/test_data.py` (novo)

**Interfaces:**
- Produces: `class MissingDataError(Exception)`; `download(...)` passa a ignorar meses iniciais com HTTP 404 e levanta `MissingDataError` em 404 após o primeiro mês encontrado; `load(symbol, interval, start, end, data_dir=DEFAULT_DATA_DIR, fetch=True) -> pd.DataFrame` levanta `MissingDataError` quando `interval == "1d"` e o índice não é contínuo diário. Com `fetch=False`, aplica a mesma regra: meses iniciais ausentes no cache são ignorados, ausência interna é erro.

- [ ] **Step 1: Write the failing tests**

Monkeypatch `data._fetch` para servir zips sintéticos de 1d (formato de 12 colunas, como em `test_read_zip_handles_millisecond_and_microsecond_timestamps`) e levantar `urllib.error.HTTPError(url, 404, ...)` para meses ausentes.

```python
def test_download_skips_leading_missing_months(tmp_path, monkeypatch): ...
    # meses 2020-06, 2020-07 → 404; 2020-08, 2020-09 → existem
    paths = data.download("SOLUSDT", "1d", "2020-06", "2020-09", tmp_path)
    assert [p.name for p in paths] == ["SOLUSDT-1d-2020-08.zip", "SOLUSDT-1d-2020-09.zip"]

def test_download_raises_on_internal_missing_month(tmp_path, monkeypatch): ...
    # 2020-08 existe, 2020-09 → 404, 2020-10 existe
    with pytest.raises(data.MissingDataError): data.download("X", "1d", "2020-08", "2020-10", tmp_path)

def test_load_raises_on_missing_day(tmp_path, monkeypatch): ...
    # zip de 2020-08 sem o dia 2020-08-15
    with pytest.raises(data.MissingDataError): data.load("X", "1d", "2020-08", "2020-08", tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backtest/tests/test_data.py -v`
Expected: FAIL (`MissingDataError` não existe; 404 propaga como `HTTPError`).

- [ ] **Step 3: Implement in `backtest/data.py`**

Capturar `urllib.error.HTTPError` com `code == 404` no download do zip; antes do primeiro mês encontrado, pular; depois, `raise MissingDataError(f"{name} missing")`. Em `load`, após concatenar, para `1d`: comparar com `pd.date_range(df.index[0], df.index[-1], freq="D")` e levantar listando até 3 datas faltantes.

- [ ] **Step 4: Run all backtest tests**

Run: `python3 -m pytest backtest/tests -q`
Expected: todos PASS (inclui os 19 testes existentes).

- [ ] **Step 5: Commit**

```bash
git add backtest/data.py backtest/tests/test_data.py
git commit -m "feat(backtest): skip pre-listing months and fail on data gaps"
```

---

### Task 2: Sinais — `trend_exposure` e `sma_regime`

**Files:**
- Create: `backtest/trend.py`
- Test: `backtest/tests/test_trend.py` (novo)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class TrendParams: lookbacks: tuple = (20, 50, 100, 200); vol_window: int = 30; vol_target: float | None = 0.50; band: float = 0.10`
  - `trend_exposure(close: pd.Series, p: TrendParams) -> pd.Series` — mesmo índice de `close`, valores em [0, 1], `NaN` durante o aquecimento (`max(lookbacks)` dias para os sinais; `vol_window` retornos para a volatilidade).
  - `sma_regime(close: pd.Series, window: int = 200) -> pd.Series` — 1.0 / 0.0, `NaN` nos primeiros `window - 1` dias.
  - `warmup_days(p: TrendParams) -> int` = `max(max(p.lookbacks), p.vol_window + 1 if p.vol_target is not None else 0)`.

- [ ] **Step 1: Write the failing tests**

```python
def daily(prices, start="2020-01-01"):  # helper: Series diária UTC
    ...

def test_rising_series_full_exposure_without_vol_control():
    p = TrendParams(lookbacks=(2, 3), vol_target=None)
    e = trend_exposure(daily([1, 2, 3, 4, 5]), p)
    assert e.isna().tolist() == [True, True, True, False, False]
    assert e.dropna().tolist() == [1.0, 1.0]

def test_falling_series_zero_exposure(): ...  # mesmo formato, valores 0.0

def test_half_of_signals_positive():
    # close[t] > close[t-2] mas < close[t-4] → raw = 0.5 com lookbacks=(2, 4)
    e = trend_exposure(daily([10, 1, 2, 3, 4]), TrendParams(lookbacks=(2, 4), vol_target=None))
    assert e.iloc[-1] == 0.5

def test_vol_scaling_matches_formula():
    # log-retornos alternando +r/-r (r=0.05), vol_window=4 → vol = std(ddof=1) * sqrt(365)
    ...
    assert e.iloc[-1] == pytest.approx(raw * min(1, 0.5 / expected_vol))

def test_constant_price_has_scale_one():           # Review Focus 1
    e = trend_exposure(daily([5.0] * 10), TrendParams(lookbacks=(2,), vol_window=3, vol_target=0.5))
    assert e.iloc[:4].isna().all()                  # warmup_days = max(2, 3 + 1) = 4
    assert e.iloc[4:].notna().all() and (e.iloc[4:] == 0.0).all()   # sem NaN/inf após aquecimento

def test_no_lookahead():
    close = daily(np.linspace(1, 50, 300))
    full = trend_exposure(close, TrendParams())
    cut = trend_exposure(close.iloc[:250], TrendParams())
    pd.testing.assert_series_equal(full.iloc[:250], cut)

def test_sma_regime_values(): ...  # window=3: [1,2,3,1,5] → [nan, nan, 1, 0, 1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backtest/tests/test_trend.py -v`
Expected: FAIL com `ModuleNotFoundError: backtest.trend`.

- [ ] **Step 3: Implement `TrendParams`, `trend_exposure`, `sma_regime`, `warmup_days` in `backtest/trend.py`**

Vetorizado com `close.shift(L)`, `np.log(close).diff().rolling(vol_window).std() * sqrt(365)`; `scale = (vol_target / vol).clip(upper=1)` com `vol == 0` → `scale = 1`. Sinal estrito: `close > close.shift(L)`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest backtest/tests/test_trend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/trend.py backtest/tests/test_trend.py
git commit -m "feat(backtest): trend exposure and SMA regime signals"
```

---

### Task 3: Simulação diária — `simulate`

**Files:**
- Modify: `backtest/trend.py`
- Test: `backtest/tests/test_trend.py`

**Interfaces:**
- Consumes: `target: pd.Series` de Task 2 (mesmo índice diário que `daily`).
- Produces:
  - `@dataclass class TrendResult: equity: pd.Series; exposure: pd.Series; trades: pd.DataFrame`  (`trades` colunas: `date, side, notional, price, fee`)
  - `simulate(daily: pd.DataFrame, target: pd.Series, capital: float = 10_000.0, band: float = 0.0, fee: float = 0.001, slippage: float = 0.0005, trade_from: pd.Timestamp | None = None) -> TrendResult`
  - Regras (spec 2.3): no dia `d`, usa `target` do dia anterior; pula se `NaN` ou `d < trade_from`; peso `w` avaliado em `open[d]`; opera se `|target - w| > band` ou (`target == 0` e `w > 0`); compra limitada a `cash / (1 + fee)` (em valor a preço de execução); `equity[d] = cash + qty * close[d]`; `exposure[d] = qty * close[d] / equity[d]`.

- [ ] **Step 1: Write the failing tests**

```python
def ohlc(opens, closes): ...  # DataFrame diário com colunas open, close

def test_full_exposure_equals_buy_and_hold_minus_costs():
    df = ohlc([100, 110, 120, 130], [105, 115, 125, 135]); tgt = pd.Series(1.0, index=df.index)
    r = simulate(df, tgt, capital=1000, fee=0.001, slippage=0.0005)
    qty = 1000 / (1 + 0.001) / (110 * 1.0005)     # executa na abertura do dia 2
    assert r.equity.iloc[-1] == pytest.approx(qty * 135)
    assert r.equity.iloc[0] == 1000

def test_zero_exposure_keeps_capital_constant(): ...  # equity ≡ capital, trades vazio

def test_executes_on_next_open_only(): ...  # target muda no dia 2 → trade com date == dia 3 e price == open[dia 3]*(1±slip)

def test_band_blocks_small_changes():
    # target 0.50 → 0.55 → 0.58 com band=0.10: só a primeira operação
    ...
    assert len(r.trades) == 1

def test_target_zero_always_exits(): ...  # w ≈ 0.05, band=0.10, target 0 → venda

def test_cash_never_negative():                    # Review Focus 2
    ... target oscilando 0/1 com fee=0.002, slippage=0.002
    assert (r.equity - r.exposure * r.equity >= -1e-9).all()

def test_last_day_target_is_ignored():             # Review Focus 3
    # target só vira 1 no último dia → nenhuma operação, sem IndexError
    assert r.trades.empty

def test_fees_recorded():
    assert r.trades["fee"].sum() == pytest.approx((r.trades["notional"] * 0.001).sum())

def test_trade_from_delays_first_trade(): ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backtest/tests/test_trend.py -v -k "simulate or exposure_equals or band or exits or cash or last_day or fees or trade_from or next_open"`
Expected: FAIL (`simulate` não existe).

- [ ] **Step 3: Implement `TrendResult` and `simulate` in `backtest/trend.py`**

Loop simples sobre os dias (~2.800); sem vetorização necessária.

- [ ] **Step 4: Run all backtest tests**

Run: `python3 -m pytest backtest/tests -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/trend.py backtest/tests/test_trend.py
git commit -m "feat(backtest): daily next-open simulation with band and costs"
```

---

### Task 4: Carteira e critérios

**Files:**
- Modify: `backtest/metrics.py` (adiciona `combine`)
- Create: `backtest/validate.py` (somente constantes e funções puras de critério nesta task)
- Test: `backtest/tests/test_validate.py` (novo)

**Interfaces:**
- Consumes: dicionários de `metrics.summarize(equity, position=exposure)` com chaves `cagr`, `max_drawdown`, `calmar`.
- Produces:
  - `metrics.combine(equities: list[pd.Series]) -> pd.Series` — soma alinhada; `ValueError` se os índices diferirem.
  - Em `validate.py`: constantes da seção Global Constraints;
    `check_c1(a: dict, hodl: dict) -> bool`, `check_c2(a: dict, hodl: dict) -> bool`, `check_c3(a: dict, hodl: dict, b: dict | None) -> bool` (`b=None` → compara só com HODL, usado para avaliar B), `check_c4(passes: list[bool]) -> bool`, `decide(a_pass: bool, b_pass: bool) -> str` retornando `"integrate-A"`, `"use-B"` ou `"dca-hodl"`, `grid_configs() -> list[TrendParams]` (72 itens, ordem: lookbacks × vol_target × band, valores da spec 4.2.2).

- [ ] **Step 1: Write the failing tests**

```python
H = {"cagr": 0.40, "max_drawdown": -0.80, "calmar": 0.50}

def test_c1_boundary():
    assert check_c1({"max_drawdown": -0.479}, H) is True    # limite 0.60 * 0.80 = 0.48
    assert check_c1({"max_drawdown": -0.481}, H) is False

def test_c2_boundary_and_negative_hodl():
    assert check_c2({"cagr": 0.301}, H) is True              # limite 0.75 * 0.40 = 0.30
    assert check_c2({"cagr": 0.299}, H) is False
    assert check_c2({"cagr": -0.05}, {"cagr": -0.10}) is True
    assert check_c2({"cagr": -0.11}, {"cagr": -0.10}) is False

def test_c3_requires_beating_both(): ...  # calmar > hodl e > b; b=None ignora b

def test_c4_threshold():
    assert check_c4([True] * 51 + [False] * 21) is True
    assert check_c4([True] * 50 + [False] * 22) is False

def test_nan_metrics_fail():                       # Review Focus 5
    nan = {"cagr": float("nan"), "max_drawdown": float("nan"), "calmar": float("nan")}
    assert not (check_c1(nan, H) or check_c2(nan, H) or check_c3(nan, H, None))

def test_decide(): ...  # (T,*)→integrate-A, (F,T)→use-B, (F,F)→dca-hodl

def test_grid_has_72_unique_configs(): ...

def test_combine_sums_and_rejects_misaligned(): ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backtest/tests/test_validate.py -v`
Expected: FAIL (`backtest.validate` não existe).

- [ ] **Step 3: Implement `combine` and the criteria functions**

Comparações com os limites inclusivos como nos testes (`<=`, `>=`); qualquer operando NaN → `False`.

- [ ] **Step 4: Run all backtest tests**

Run: `python3 -m pytest backtest/tests -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/metrics.py backtest/validate.py backtest/tests/test_validate.py
git commit -m "feat(backtest): portfolio combine and pre-registered criteria"
```

---

### Task 5: Orquestração e relatório (`validate.py` CLI)

**Files:**
- Modify: `backtest/validate.py`
- Modify: `backtest/README.md` (seção "Validação trend following": comando e onde sai o relatório)
- Test: `backtest/tests/test_validate.py`

**Interfaces:**
- Consumes: `data.load` (Task 1), `trend.trend_exposure`, `trend.sma_regime`, `trend.warmup_days`, `trend.simulate` (Tasks 2–3), critérios e `metrics.combine` (Task 4), `metrics.summarize`, `metrics.buy_and_hold`, `metrics.dca`, `metrics.yearly_returns`.
- Produces:
  - `run_portfolio(daily_by_symbol: dict[str, pd.DataFrame], target_fn: Callable[[pd.Series], pd.Series], band: float, fee: float, slippage: float, start: pd.Timestamp, capital: float) -> tuple[pd.Series, pd.Series]` — (equity da carteira a partir de `start`, exposição média ponderada); capital dividido igualmente entre os símbolos.
  - `hodl_portfolio(daily_by_symbol, fee, slippage, start, capital) -> pd.Series` — `buy_and_hold` por símbolo sobre `daily[start:]` com capital dividido, combinado.
  - `main(argv=None)` com opções `--start 2019-01`, `--end 2026-09`, `--data-dir`, `--no-fetch`, `--out backtest/results/<AAAA-MM-DD>-trend-validation.md`.
  - Relatório: tabelas de métricas (A, B, HODL 50/50, DCA 50/50, HODL BTC, HODL ETH) — para A e B incluir também número de operações (`len(trades)` somado) e custos pagos (`fee` somado + slippage estimada `notional × slippage`), retorno e drawdown ano a ano, tabela da grade (72 linhas com C1/C3), custos em dobro, fora da amostra por ativo (com ALERTA quando aplicável), tabela C1–C5 de A e de B com APROVADO/REPROVADO e a recomendação de `decide`.
  - Janelas conforme spec 4.1: início principal = primeiro dia com `trend.warmup_days(TrendParams())` e 200 dias de histórico em todos os símbolos principais; início da grade = mesmo cálculo com o maior `warmup_days` da grade; fora da amostra = início por ativo.

- [ ] **Step 1: Write the failing tests**

```python
def test_main_end_to_end_on_synthetic_data(tmp_path, monkeypatch):
    # gera zips 1d sintéticos para BTCUSDT, ETHUSDT e os 5 ativos fora da amostra
    # (SOLUSDT começando 6 meses depois — Review Focus 4), roda main com --no-fetch
    validate.main(["--start", "2019-01", "--end", "2021-12", "--no-fetch",
                   "--data-dir", str(tmp_path), "--out", str(tmp_path / "r.md")])
    text = (tmp_path / "r.md").read_text()
    for key in ["C1", "C2", "C3", "C4", "C5", "Recomendação", "SOLUSDT"]:
        assert key in text
    assert text.count("APROVADO") + text.count("REPROVADO") >= 9

def test_run_portfolio_splits_capital_equally(): ...  # target ≡ 0 → equity ≡ capital

def test_late_listed_asset_starts_at_own_warmup(): ...  # Review Focus 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backtest/tests/test_validate.py -v`
Expected: FAIL (`main`, `run_portfolio` não existem).

- [ ] **Step 3: Implement orchestration, report and README section**

Reaproveitar o formato de tabela markdown de `backtest/run.py` (`to_markdown`, `yearly_markdown`) importando-os, sem duplicar.

- [ ] **Step 4: Run all backtest tests**

Run: `python3 -m pytest backtest/tests -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/validate.py backtest/tests/test_validate.py backtest/README.md
git commit -m "feat(backtest): trend following validation CLI and report"
```

---

### Task 6: Executar a validação com dados reais

**Files:**
- Create: `backtest/results/2026-10-31-trend-validation.md` (gerado)

- [ ] **Step 1: Download e execução**

Run: `python3 -m backtest.validate --start 2019-01 --end 2026-09 --out backtest/results/2026-10-31-trend-validation.md`
Expected: termina sem erro; relatório contém C1–C5 para A e B e uma recomendação.

- [ ] **Step 2: Conferência de sanidade**

Verificar no relatório: HODL BTC na janela principal tem CAGR na mesma ordem do backtest anterior (~33% em `2019-07-20..2026-09`, diferença esperada por janela/fonte diária); exposição média de A entre 0 e 1; número de operações de A ≪ número de dias. Se algo divergir, parar e investigar antes de commitar.

- [ ] **Step 3: Commit**

```bash
git add backtest/results/2026-10-31-trend-validation.md
git commit -m "docs(backtest): trend following validation results"
```
