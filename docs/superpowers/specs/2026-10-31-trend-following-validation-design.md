# Validação de estratégia trend following (BTC/ETH spot)

- Data: 2026-10-31
- Status: aguardando revisão
- Escopo: somente backtester (`backtest/`). Integração ao bot é um projeto
  separado, condicionado à aprovação nos critérios desta especificação.

## 1. Contexto e objetivo

O backtest de 2019-07 a 2026-09 (`backtest/results/2026-10-31-default-config.md`)
mostrou que a estratégia trailing atual do bot, na configuração padrão, perdeu
do buy & hold em 4 de 5 pares com o mesmo drawdown (-75% a -88%), porque passa
83–96% do tempo comprada, limita os ganhos em +6% e nunca realiza perdas.

**Objetivo definido pelo usuário:** retorno próximo ao HODL de BTC/ETH com cerca
de metade do drawdown máximo, operando apenas no mercado spot.

**Decisões já tomadas:**

| tema | decisão |
|---|---|
| objetivo | menos risco: retorno próximo ao HODL, ~metade do drawdown |
| ativos | BTC e ETH, 50% do capital para cada, blocos independentes |
| mercado | spot, sem alavancagem, sem futuros |
| entrega | validação no backtester primeiro; integração ao bot fica fora |
| abordagem | candidata A (trend following multi-prazo + controle de volatilidade), controle B (SMA200) |

## 2. Regras das estratégias

Todas as decisões usam candles diários (UTC). A decisão do dia `t` usa apenas
dados até o fechamento de `t` e é executada na **abertura do dia `t+1`**.

### 2.1 Candidata A — trend following multi-prazo com controle de volatilidade

Parâmetros padrão (escolhidos a priori, não otimizados):

| parâmetro | valor |
|---|---|
| `lookbacks` | (20, 50, 100, 200) dias |
| `vol_window` | 30 dias |
| `vol_target` | 0.50 (50% ao ano); `None` desliga o controle |
| `band` | 0.10 (10 pontos percentuais) |

No fechamento do dia `t`, para cada ativo:

1. Sinal por prazo: `s_L = 1 se close[t] > close[t-L], senão 0`.
2. Exposição bruta: `raw = média(s_L)` ∈ {0, 0.25, 0.5, 0.75, 1}.
3. Volatilidade: `vol = desvio-padrão(log(close[k]/close[k-1]), k = t-29..t) × √365`.
4. Escala: `scale = min(1, vol_target / vol)`; se `vol_target is None`, `scale = 1`.
5. Exposição desejada: `target[t] = raw × scale` ∈ [0, 1].

Enquanto algum termo não estiver definido (aquecimento), não há operação.

### 2.2 Controle B — regime pela média de 200 dias

`target[t] = 1 se close[t] > SMA200(close)[t], senão 0`. Sem controle de
volatilidade, `band = 0`.

### 2.3 Execução (comum a A e B)

Cada bloco (ativo) começa com 50% do capital da carteira, em caixa (USDT, rende 0%).
Na abertura do dia `t+1`:

1. Peso atual `w = valor_da_posição / patrimônio_do_bloco`, avaliados no preço de abertura.
2. Opera se `|target[t] − w| > band` **ou** `target[t] == 0 e w > 0` (saída total
   sempre executa).
3. Ao operar, ajusta a posição para exatamente `target[t]`. Preço de execução:
   `open × (1 + slippage)` na compra, `open × (1 − slippage)` na venda.
   Taxa: `fee × valor negociado`, debitada do caixa.
4. Custos padrão: `fee = 0.001`, `slippage = 0.0005` por execução.

Não há rebalanceamento entre blocos. A carteira é a soma dos dois blocos.

## 3. Dados

- Fonte: arquivos mensais oficiais de candles **1d** de `data.binance.vision`
  (mesmo downloader de `backtest/data.py`, com verificação SHA256). A abertura do
  candle diário é igual à abertura do primeiro minuto do dia, então 1d é
  suficiente para regras diárias e execução na abertura.
- Período: 2019-01 a 2026-09 (inclui aquecimento).
- Ativos principais: BTCUSDT, ETHUSDT.
- Ativos fora da amostra: LTCUSDT, XRPUSDT, BNBUSDT, ADAUSDT, SOLUSDT.
- Ativos listados depois do início (ex.: SOLUSDT, 2020-08) começam no primeiro
  mês disponível: meses iniciais inexistentes (HTTP 404) são ignorados.
- Mês ausente no meio da série ou dias faltando: **erro explícito**, nunca
  preenchimento silencioso.

## 4. Protocolo de validação

### 4.1 Janelas

- Teste principal, custos e ativos fora da amostra: início comum no primeiro
  dia em que A (200 + 1 dias) e B (200 dias) estão aquecidos. Benchmarks começam
  no mesmo dia.
- Grade de sensibilidade: início comum no primeiro dia em que a configuração de
  maior aquecimento (prazo 300) está pronta; HODL e B são recalculados nessa
  mesma janela.

### 4.2 Testes

1. **Principal:** carteira 50/50 de A contra HODL 50/50, B 50/50 e DCA semanal 50/50.
2. **Sensibilidade (72 configurações):** `lookbacks` ∈ {(10,20,50,100),
   (20,50,100,200), (50,100,200,300)} × `vol_target` ∈ {0.30, 0.40, 0.50, 0.60,
   0.80, None} × `band` ∈ {0, 0.05, 0.10, 0.20}.
3. **Custos em dobro:** `fee = 0.002`, `slippage = 0.002` para A, B e HODL.
4. **Fora da amostra:** cada ativo isolado (100% do capital), A com parâmetros
   padrão contra HODL do próprio ativo.
5. **Ano a ano:** retorno anual e drawdown por ano para A, B e HODL na carteira 50/50.

### 4.3 Métricas

Sobre o patrimônio diário: retorno total, CAGR, drawdown máximo (MaxDD),
volatilidade anual, Sharpe (rf = 0), Calmar = `CAGR / |MaxDD|`, exposição média,
número de operações e custos pagos.

### 4.4 Critérios de aprovação da candidata A (pré-registrados)

Todos obrigatórios. Valores fixados como constantes em `backtest/validate.py`
antes da primeira execução.

| # | critério |
|---|---|
| C1 | `|MaxDD_A| ≤ 0.60 × |MaxDD_HODL|` |
| C2 | `CAGR_A ≥ 0.75 × CAGR_HODL`; se `CAGR_HODL ≤ 0`, exige `CAGR_A ≥ CAGR_HODL` |
| C3 | `Calmar_A > Calmar_HODL` **e** `Calmar_A > Calmar_B` |
| C4 | ≥ 70% das 72 configurações (≥ 51) passam em C1 e C3 na janela da grade |
| C5 | com custos em dobro, A passa em C1 e C3 |

O teste fora da amostra (4.2.4) é diagnóstico: o relatório marca **ALERTA** se
em 3 ou mais dos 5 ativos `Calmar_A < Calmar_HODL` ou `|MaxDD_A| > |MaxDD_HODL|`.

Para o controle B, "passar" significa C1, C2, C3 (somente contra HODL) e C5.

### 4.5 Regra de decisão

| resultado | recomendação |
|---|---|
| A aprovada | abrir projeto de integração ao bot (spec própria), depois testnet e capital pequeno |
| A reprovada, B aprovada | recomendar B (mais simples) |
| ambas reprovadas | recomendar DCA/HODL; não integrar estratégia ao bot |

Aprovação é evidência, não prova: ~7 anos (≈ 1,5 ciclo de mercado).

## 5. Arquitetura

| arquivo | responsabilidade |
|---|---|
| `backtest/data.py` | ajuste: ignorar meses iniciais 404; erro para lacunas internas |
| `backtest/trend.py` (novo) | `TrendParams`; `trend_exposure(close, params) -> pd.Series`; `sma_regime(close, window) -> pd.Series`; `simulate(daily, target, fee, slippage, capital, band, trade_from) -> Result` — funções puras, sem I/O |
| `backtest/metrics.py` | acrescenta `combine(equities) -> pd.Series` (soma de blocos); reaproveita `summarize`, `buy_and_hold`, `dca`, `yearly_returns` |
| `backtest/validate.py` (novo) | CLI: carrega dados, roda testes 4.2.1–4.2.5, avalia C1–C5, escreve `backtest/results/AAAA-MM-DD-trend-validation.md` com APROVADO/REPROVADO por critério e a recomendação de 4.5 |

Fluxo: `candles 1d → target (A|B) → simulate → patrimônio por ativo → combine → summarize → critérios → relatório`.

`Result` de `simulate`: `equity` (diário), `exposure` (peso após a execução de
cada dia), `trades` (data, lado, valor negociado, preço, taxa).

## 6. Testes (TDD, séries sintéticas, `backtest/tests/test_trend.py`)

1. **Sem look-ahead:** alterar `close[t+1..]` não altera `target[..t]`; a
   operação baseada em `target[t]` ocorre na abertura de `t+1`.
2. Sinais: série monotônica crescente → `raw = 1`; decrescente → `raw = 0`;
   série construída com 2 de 4 prazos positivos → `raw = 0.5`.
3. Volatilidade: série com retornos log alternando ±r tem `vol` conhecida;
   `scale` e o limite em 1 conferem.
4. Banda: variações de `target` menores que `band` não geram operação; `target = 0`
   sempre zera a posição.
5. Contabilidade: `target ≡ 1` reproduz buy & hold menos uma taxa e slippage;
   `target ≡ 0` mantém o patrimônio constante; taxas somadas = soma de `fee × valor`.
6. `combine` soma blocos corretamente.
7. Avaliador de critérios: casos de fronteira de C1–C5, incluindo `CAGR_HODL ≤ 0`.
8. Dados: meses iniciais 404 ignorados; lacuna interna gera erro.

## 7. Fora do escopo

Integração ao bot, otimização de parâmetros, alavancagem, futuros, rendimento
do caixa em USDT, cestas de altcoins, execução intradiária.
