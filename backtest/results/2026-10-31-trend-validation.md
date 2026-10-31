# Validação trend following — BTC/ETH spot

Período de dados 2019-01..2026-09; janela principal a partir de 2019-07-20; grade a partir de 2019-10-28. Custos 0.10% + slippage 0.05% por execução. Spec: docs/superpowers/specs/2026-10-31-trend-following-validation-design.md

## Critérios

| critério | descrição | A | B |
|---|---|---|---|
| C1 | |MaxDD| <= 60% do HODL | APROVADO | REPROVADO |
| C2 | CAGR >= 75% do HODL | REPROVADO | APROVADO |
| C3 | Calmar > HODL (e > B, para A) | APROVADO | APROVADO |
| C4 | >= 70% da grade passa C1 e C3 (13/72) | REPROVADO | - |
| C5 | custos em dobro: C1 e C3 | REPROVADO | REPROVADO |

**Recomendação:** A e B reprovadas: recomendar DCA/HODL e não integrar estratégia ao bot.

## Teste principal (carteira 50/50)

| metric | A (trend) | B (SMA200) | HODL 50/50 | DCA 50/50 | HODL BTC | HODL ETH |
|---|---|---|---|---|---|---|
| total_return | 475.1% | 858.8% | 878.9% | 241.1% | 678.6% | 1077.0% |
| cagr | 27.5% | 36.9% | 37.3% | 18.6% | 33.0% | 40.9% |
| max_drawdown | -40.2% | -54.4% | -77.6% | -65.1% | -76.6% | -79.3% |
| volatility | 32.1% | 50.0% | 70.4% | 46.9% | 60.2% | 80.1% |
| sharpe | 0.92 | 0.88 | 0.81 | 0.60 | 0.78 | 0.83 |
| calmar | 0.68 | 0.68 | 0.48 | 0.29 | 0.43 | 0.52 |
| time_in_market | 45.4% | 56.0% | - | - | - | - |
| trades | 1040.00 | 108.00 | - | - | - | - |
| costs | 6167.18 | 3602.50 | - | - | - | - |

## Ano a ano — retorno

| year | A (trend) | B (SMA200) | HODL 50/50 |
|---|---|---|---|
| 2019 | -17.0% | -26.2% | -38.2% |
| 2020 | 162.5% | 137.3% | 379.4% |
| 2021 | 67.9% | 128.8% | 245.7% |
| 2022 | -24.5% | -13.1% | -66.8% |
| 2023 | 43.7% | 59.0% | 105.4% |
| 2024 | 38.0% | 57.0% | 67.3% |
| 2025 | -0.8% | -7.6% | -9.3% |
| 2026 | 5.8% | 19.4% | -7.7% |

## Ano a ano — drawdown máximo no ano

| year | A (trend) | B (SMA200) | HODL 50/50 |
|---|---|---|---|
| 2019 | -20.0% | -30.5% | -45.8% |
| 2020 | -27.5% | -50.7% | -58.5% |
| 2021 | -25.2% | -52.7% | -55.0% |
| 2022 | -25.4% | -16.0% | -71.1% |
| 2023 | -22.1% | -21.0% | -24.5% |
| 2024 | -33.1% | -25.7% | -39.8% |
| 2025 | -23.7% | -33.4% | -47.3% |
| 2026 | -15.4% | -5.1% | -48.0% |

## Custos em dobro

| metric | A (trend) | B (SMA200) | HODL 50/50 |
|---|---|---|---|
| total_return | 335.6% | 746.6% | 878.9% |
| cagr | 22.7% | 34.5% | 37.3% |
| max_drawdown | -42.7% | -55.6% | -77.6% |
| volatility | 32.2% | 50.0% | 70.4% |
| sharpe | 0.80 | 0.85 | 0.81 |
| calmar | 0.53 | 0.62 | 0.48 |
| time_in_market | 45.4% | 56.0% | - |
| trades | 1040.00 | 108.00 | - |
| costs | 13909.16 | 8806.01 | - |

## Sensibilidade (72 configurações, janela da grade)

Referências na janela da grade: HODL Calmar 0.55, MaxDD -77.7%; B Calmar 0.84.

| lookbacks | vol_target | band | CAGR | MaxDD | Calmar | C1 | C3 |
|---|---|---|---|---|---|---|---|
| (10, 20, 50, 100) | 0.3 | 0.00 | 23.8% | -27.5% | 0.86 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.3 | 0.05 | 23.9% | -27.7% | 0.86 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.3 | 0.10 | 24.5% | -26.2% | 0.94 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.3 | 0.20 | 25.5% | -25.8% | 0.99 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.4 | 0.00 | 30.2% | -34.6% | 0.87 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.4 | 0.05 | 30.3% | -34.0% | 0.89 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.4 | 0.10 | 29.4% | -34.2% | 0.86 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.4 | 0.20 | 30.7% | -32.6% | 0.94 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.5 | 0.00 | 34.5% | -41.5% | 0.83 | APROVADO | REPROVADO |
| (10, 20, 50, 100) | 0.5 | 0.05 | 34.5% | -41.3% | 0.83 | APROVADO | REPROVADO |
| (10, 20, 50, 100) | 0.5 | 0.10 | 34.4% | -40.3% | 0.85 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.5 | 0.20 | 35.6% | -38.8% | 0.92 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.6 | 0.00 | 38.6% | -46.7% | 0.83 | REPROVADO | REPROVADO |
| (10, 20, 50, 100) | 0.6 | 0.05 | 38.8% | -46.5% | 0.84 | APROVADO | REPROVADO |
| (10, 20, 50, 100) | 0.6 | 0.10 | 37.7% | -45.8% | 0.82 | APROVADO | REPROVADO |
| (10, 20, 50, 100) | 0.6 | 0.20 | 38.4% | -42.4% | 0.91 | APROVADO | APROVADO |
| (10, 20, 50, 100) | 0.8 | 0.00 | 43.1% | -50.1% | 0.86 | REPROVADO | APROVADO |
| (10, 20, 50, 100) | 0.8 | 0.05 | 43.1% | -49.7% | 0.87 | REPROVADO | APROVADO |
| (10, 20, 50, 100) | 0.8 | 0.10 | 42.3% | -49.7% | 0.85 | REPROVADO | APROVADO |
| (10, 20, 50, 100) | 0.8 | 0.20 | 43.2% | -47.3% | 0.91 | REPROVADO | APROVADO |
| (10, 20, 50, 100) | None | 0.00 | 45.4% | -50.8% | 0.89 | REPROVADO | APROVADO |
| (10, 20, 50, 100) | None | 0.05 | 45.0% | -50.9% | 0.88 | REPROVADO | APROVADO |
| (10, 20, 50, 100) | None | 0.10 | 45.1% | -50.9% | 0.89 | REPROVADO | APROVADO |
| (10, 20, 50, 100) | None | 0.20 | 45.6% | -50.6% | 0.90 | REPROVADO | APROVADO |
| (20, 50, 100, 200) | 0.3 | 0.00 | 22.2% | -27.7% | 0.80 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.3 | 0.05 | 22.4% | -27.4% | 0.82 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.3 | 0.10 | 22.2% | -25.7% | 0.86 | APROVADO | APROVADO |
| (20, 50, 100, 200) | 0.3 | 0.20 | 21.4% | -27.8% | 0.77 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.4 | 0.00 | 28.1% | -34.8% | 0.81 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.4 | 0.05 | 27.8% | -34.2% | 0.81 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.4 | 0.10 | 28.2% | -33.8% | 0.83 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.4 | 0.20 | 29.1% | -32.1% | 0.91 | APROVADO | APROVADO |
| (20, 50, 100, 200) | 0.5 | 0.00 | 31.9% | -41.2% | 0.77 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.5 | 0.05 | 31.1% | -41.0% | 0.76 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.5 | 0.10 | 31.3% | -40.2% | 0.78 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.5 | 0.20 | 31.5% | -40.7% | 0.77 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.6 | 0.00 | 35.1% | -46.0% | 0.76 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.6 | 0.05 | 35.2% | -45.9% | 0.77 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.6 | 0.10 | 34.6% | -45.0% | 0.77 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.6 | 0.20 | 34.8% | -43.7% | 0.80 | APROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.8 | 0.00 | 38.8% | -48.6% | 0.80 | REPROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.8 | 0.05 | 38.6% | -48.5% | 0.80 | REPROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.8 | 0.10 | 37.3% | -47.9% | 0.78 | REPROVADO | REPROVADO |
| (20, 50, 100, 200) | 0.8 | 0.20 | 37.6% | -47.9% | 0.79 | REPROVADO | REPROVADO |
| (20, 50, 100, 200) | None | 0.00 | 39.2% | -48.8% | 0.80 | REPROVADO | REPROVADO |
| (20, 50, 100, 200) | None | 0.05 | 39.1% | -49.4% | 0.79 | REPROVADO | REPROVADO |
| (20, 50, 100, 200) | None | 0.10 | 39.0% | -49.5% | 0.79 | REPROVADO | REPROVADO |
| (20, 50, 100, 200) | None | 0.20 | 38.7% | -49.4% | 0.78 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.3 | 0.00 | 21.4% | -28.0% | 0.76 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.3 | 0.05 | 22.3% | -28.1% | 0.79 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.3 | 0.10 | 20.8% | -27.9% | 0.74 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.3 | 0.20 | 20.5% | -31.6% | 0.65 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.4 | 0.00 | 27.2% | -35.2% | 0.77 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.4 | 0.05 | 27.4% | -34.4% | 0.80 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.4 | 0.10 | 27.2% | -35.0% | 0.78 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.4 | 0.20 | 27.8% | -37.6% | 0.74 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.5 | 0.00 | 31.1% | -41.8% | 0.74 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.5 | 0.05 | 31.3% | -41.2% | 0.76 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.5 | 0.10 | 32.0% | -40.3% | 0.79 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.5 | 0.20 | 30.7% | -40.0% | 0.77 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.6 | 0.00 | 33.7% | -46.6% | 0.72 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.6 | 0.05 | 34.1% | -46.5% | 0.73 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.6 | 0.10 | 34.0% | -45.7% | 0.74 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.6 | 0.20 | 34.8% | -45.6% | 0.76 | APROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.8 | 0.00 | 37.6% | -48.0% | 0.78 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.8 | 0.05 | 38.1% | -47.2% | 0.81 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.8 | 0.10 | 37.1% | -48.1% | 0.77 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | 0.8 | 0.20 | 35.6% | -48.2% | 0.74 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | None | 0.00 | 37.1% | -49.3% | 0.75 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | None | 0.05 | 37.5% | -49.5% | 0.76 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | None | 0.10 | 37.2% | -49.5% | 0.75 | REPROVADO | REPROVADO |
| (50, 100, 200, 300) | None | 0.20 | 37.8% | -48.9% | 0.77 | REPROVADO | REPROVADO |

## Fora da amostra (diagnóstico, A padrão vs HODL do ativo)

A ficou pior que o HODL em 1 de 5 ativos (limite de alerta: 3).

| ativo | início | CAGR A | CAGR HODL | MaxDD A | MaxDD HODL | Calmar A | Calmar HODL | |
|---|---|---|---|---|---|---|---|---|
| LTCUSDT | 2019-07-20 | 9.0% | -5.4% | -42.6% | -89.4% | 0.21 | -0.06 | ok |
| XRPUSDT | 2019-07-20 | 17.0% | 23.2% | -59.4% | -83.2% | 0.29 | 0.28 | ok |
| BNBUSDT | 2019-07-20 | 29.7% | 56.2% | -48.4% | -70.9% | 0.61 | 0.79 | pior |
| ADAUSDT | 2019-07-20 | 32.5% | 21.0% | -44.1% | -95.2% | 0.74 | 0.22 | ok |
| SOLUSDT | 2021-02-27 | 44.3% | 48.0% | -48.0% | -96.3% | 0.92 | 0.50 | ok |
