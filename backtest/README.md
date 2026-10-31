# Backtest da estratégia trailing

Simula a estratégia do bot (`app/cronjob/trailingTrade`) sobre candles históricos
de 1 minuto da Binance e compara com **buy & hold** e **DCA semanal**, com taxas e
slippage. O objetivo é responder: *o bot ganha de simplesmente segurar o ativo?*

## Uso

```bash
pip install -r backtest/requirements.txt
python -m backtest.run --symbols BTCUSDT ETHUSDT --start 2019-01 --end 2026-09
python -m pytest backtest/tests
```

- Os dados vêm de `https://data.binance.vision` (arquivos mensais oficiais,
  validados por SHA256) e ficam em cache em `backtest/data/` (fora do git).
  ~2 MB por mês por símbolo em 1m.
- O relatório é gravado em `backtest/report.md`.
- `--start` inclui o período de aquecimento (100h, 30 dias de ATH e 200 dias
  para a variante com filtro de tendência). Todas as estratégias e benchmarks
  começam a operar no mesmo instante, depois do maior aquecimento.
- Opções: `--fee` (padrão 0.1%/execução), `--slippage` (padrão 0.05%/execução),
  `--variants`, `--interval`, `--no-fetch`, `--data-dir`.

## Variantes

| nome | descrição |
|---|---|
| `bot-default` | configuração padrão de `config/default.json` (1 grid, stop-loss desligado) |
| `bot+stoploss` | stop-loss a mercado em -20%, compras bloqueadas por 360 min |
| `bot+trend200` | **não existe no bot**: só abre posição se o último fechamento diário > SMA200 |
| `bot+trend200+stoploss` | as duas anteriores |

## O que é modelado

- Mínima de 100 candles de 1h (incluindo o candle em formação) e restrição de
  ATH (máxima de 30 candles diários x 0.9), como em `get-indicators`.
- Compra quando o preço faz nova mínima: STOP_LOSS_LIMIT em +2% / +2.1%,
  cancelado e recolocado quando o preço cai (`handle-open-orders`), ou seja,
  o stop acompanha o fundo.
- Venda a partir de +6% sobre o preço de compra: STOP_LOSS_LIMIT em -2% / -2.1%,
  acompanhando o topo.
- 100% do capital alocado por compra (juros compostos), uma posição por vez.

## Limitações (leia antes de confiar nos números)

1. **Caminho intrabarra aproximado.** Cada candle de 1m vira 4 ticks
   (abertura → mínima → máxima → fechamento, ou o inverso em candle vermelho).
   O bot real reage a cada ~1s.
2. **Preço contínuo.** Ordens stop executam exatamente no preço de stop (mais
   slippage). Em quedas bruscas, uma STOP_LOSS_LIMIT real pode **não ser
   executada** se o preço passar do limite; o modelo é **otimista** nas saídas.
3. Não modela: grids múltiplos, venda forçada pelo TradingView, desconto de
   taxa com BNB, arredondamento de lote/tick, `minNotional`, latência e falhas
   de API, limite de ordens abertas entre símbolos.
4. **Viés de seleção.** BTC e ETH sobreviveram e valorizaram; testar só neles
   favorece estratégias compradas. Inclua pares que caíram ou morreram.
5. Os parâmetros padrão não foram otimizados aqui, então não há viés de
   *in-sample*. **Ao otimizar parâmetros, use validação walk-forward**
   (otimizar num período, avaliar no seguinte) — senão o resultado é
   sobreajuste.

## Validação trend following (BTC/ETH)

Valida a estratégia trend following (candidata A) contra HODL e o controle SMA200 (B)
com critérios pré-registrados em
`docs/superpowers/specs/2026-10-31-trend-following-validation-design.md`.

```bash
python -m backtest.validate --start 2019-01 --end 2026-09 \
    --out backtest/results/2026-10-31-trend-validation.md
```

Usa candles **1d** (baixados para `backtest/data/<SYMBOL>/1d/`). O relatório traz
APROVADO/REPROVADO para os critérios C1–C5, a recomendação, o teste principal,
ano a ano, custos em dobro, a grade de 72 configurações e o diagnóstico fora da
amostra (LTC, XRP, BNB, ADA, SOL). Na tabela de métricas, `time_in_market` de A e B
é a exposição média (posições fracionárias).
