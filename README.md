# Termômetro de Ciclo — BTC

Painel diário de acompanhamento de Bitcoin, altcoins, ciclo e macro. Abre no
celular e no notebook, atualiza sozinho e manda o resumo do fechamento no
Telegram às 21h.

**Custo: zero.** Roda inteiramente no plano gratuito do GitHub.

---

## Como funciona

O GitHub Actions busca todas as APIs **do lado do servidor** a cada 30 minutos e
grava um `data.json` no próprio repositório. O painel só lê esse arquivo.

Esse desenho resolve três problemas de uma vez:

- **Sem CORS.** O navegador bloquearia a maior parte dessas APIs se o painel as
  chamasse direto.
- **Chaves protegidas.** Se um dia você quiser uma fonte paga, a chave vive nos
  Secrets e nunca aparece no código do painel.
- **Histórico de graça.** Cada execução vira um commit — você acumula a série
  temporal do ciclo sem montar banco de dados.

Se uma fonte cair, o campo fica vazio e a falha aparece na faixa de saúde no rodapé.
O painel nunca inventa número.

---

## Instalação (uma vez, ~10 minutos)

### 1. Suba o repositório

Crie um repositório novo no GitHub e envie estes arquivos para a raiz dele.

### 2. Ligue o GitHub Pages

**Settings → Pages → Source: Deploy from a branch → Branch: `main` / `(root)` → Save**

Em um ou dois minutos seu painel estará no ar em
`https://SEU-USUARIO.github.io/NOME-DO-REPO/`.

### 3. Crie o bot do Telegram

1. No Telegram, converse com **@BotFather** → `/newbot` → escolha um nome.
   Ele devolve um **token**.
2. Mande qualquer mensagem para o seu bot recém-criado (isso é obrigatório —
   um bot não pode iniciar conversa com você).
3. Abra no navegador: `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`
   e procure o campo `"chat":{"id":...}`. Esse número é o seu **chat_id**.

### 4. Guarde os segredos

**Settings → Secrets and variables → Actions → New repository secret:**

| Nome | Valor |
|---|---|
| `TELEGRAM_TOKEN` | o token do BotFather |
| `TELEGRAM_CHAT_ID` | o número do passo anterior |

Ainda em **Variables** (aba ao lado), crie:

| Nome | Valor |
|---|---|
| `PANEL_URL` | a URL do seu GitHub Pages |

> Cole esses valores direto no GitHub. Não passe o token por chat, e-mail
> ou qualquer outro canal — quem tem o token controla o bot.

### 5. Dê permissão de escrita ao workflow

**Settings → Actions → General → Workflow permissions → Read and write permissions → Save**

Sem isso o Action não consegue gravar o `data.json`.

### 6. Primeira execução

**Actions → Atualizar painel → Run workflow.** Marque `enviar_telegram` para
testar a mensagem também.

Abra o log: ele lista, fonte por fonte, quem respondeu e quem falhou. É aqui
que você descobre se algum símbolo precisa de ajuste.

### 7. Instale no celular

Abra a URL no Chrome (Android) ou Safari (iPhone) → **Adicionar à tela de
início**. Vira um app com ícone próprio.

---

## Trocar altcoins

Tudo em `scripts/config.py`, lista `ALTCOINS`. O `id` **não é o ticker** — é o
identificador da CoinGecko, que aparece na URL da moeda no site
(`coingecko.com/en/coins/`**`evervalue-coin`**).

Marque `"vs_btc": True` quando o par contra BTC for a leitura que importa mais
que o preço em dólar.

---

## O que o painel mostra

**Ciclo** — CBBI (score 0–100 de confiança de topo) e as nove métricas por trás
dele: Pi Cycle Top, MVRV Z-Score, Múltiplo de Puell, NUPL/RUPL, RHODL Ratio,
Média Móvel de 2 Anos, Reserve Risk, Trolololo e Top Cap vs CVDD.

**Preço contra os modelos** — Múltiplo de Mayer, MM200, múltiplo da 2Y MA
(o suporte estrutural do ciclo), Pi Cycle, drawdown do topo, retorno no ano.

**Risco** — funding rate, open interest, Medo & Ganância, dominância BTC/ETH.

**Rede** — hashrate, próximo ajuste de dificuldade, taxas, contador do halving.

**Altcoins** — preço, variações e **desempenho contra o BTC**, que é o que
revela se a moeda está de fato ganhando do Bitcoin ou só subindo junto.

**Macro** — DXY, S&P 500, Nasdaq, ouro, Treasury de 10 anos, mais o calendário
econômico dos EUA (CPI, PCE, payroll, FOMC) embutido.

---

## Pendências conhecidas

Coisas que só a primeira execução real vai confirmar — o log do Action mostra
cada uma:

- **IDs da CoinGecko.** Confirmei `evervalue-coin` (EVA). Os demais são os IDs
  esperados, mas se algum não resolver o painel mostra *"id não resolveu"* na
  linha e é só corrigir no `config.py`.
- **Símbolos da Stooq (macro).** São os que eu esperava serem corretos, mas não
  consegui testá-los. Se a faixa "Stooq" acender vermelha, o log diz qual símbolo
  falhou.
- **Métricas do CBBI.** O próprio site avisa que algumas podem ficar
  temporariamente desabilitadas. O painel simplesmente omite as ausentes.

## O que ficou de fora

As métricas proprietárias do João Wedson — Alpha Price, ADCI, Repetition Fractal
Cycle, Alpha Quant Signal, SSR, RVTS — existem só na Alphractal e exigem API
paga por créditos. Se um dia você assinar, a chave entra nos Secrets e o
`build_data.py` ganha mais uma função `@source(...)`. A arquitetura já está
pronta para isso.

---

Nada aqui é recomendação de compra ou venda. São indicadores históricos de
posicionamento de ciclo — leituras, não previsões.
