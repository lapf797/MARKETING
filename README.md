# Marketing — Leilões no Facebook Ads com IA

Sistema de marketing automatizado para promover ativos de leilão (imóveis, veículos,
máquinas, equipamentos etc.) no Facebook Ads, com três camadas:

1. **Recomendação de público-alvo** — para cada novo ativo, a Claude analisa o histórico
   de performance da conta e sugere o público-alvo ideal.
2. **Otimização diária automática** — todo dia, a Claude analisa a performance recente de
   todas as campanhas ativas e propõe ajustes (orçamento, pausas, retomadas). Essas ações
   passam por um conjunto de **guardrails de segurança** (limites configuráveis por você)
   antes de serem aplicadas de verdade no Facebook Ads.
3. **Dashboard web** — um painel estático (`docs/index.html`, publicável via GitHub Pages)
   mostra gasto, conversões, a decisão da IA de hoje e o que as guardrails aprovaram ou
   bloquearam — sem precisar de nenhuma ferramenta externa.
4. **Power BI em tempo real** — métricas de performance, ações aplicadas e recomendações de
   público são enviadas continuamente para um dataset de push do Power BI, para relatórios
   mais robustos e compartilhamento com a equipe.

Tudo isso roda sozinho via GitHub Actions, uma vez por dia, sem precisar de servidor.

## Como funciona (visão geral)

```
GitHub Actions (todo dia)
        │
        ▼
scripts/run_daily_optimization.py
        │
        ├─► Facebook Graph API ──► busca performance dos últimos N dias
        │
        ├─► Claude (Anthropic API) ──► analisa e propõe ações (aumentar/diminuir
        │                               orçamento, pausar, retomar, sinalizar público
        │                               esgotado)
        │
        ├─► src/safety/guardrails.py ──► aprova, ajusta ou rejeita cada ação proposta
        │                                 com base nos limites em config/settings.yaml
        │                                 (nenhuma ação da IA escapa destes limites)
        │
        ├─► Facebook Graph API ──► aplica as ações aprovadas (ou simula, em dry-run)
        │
        ├─► logs/audit_log.jsonl ──► registra TODA decisão (aplicada, simulada ou
        │                             rejeitada, com motivo e confiança) — versionado
        │                             no próprio repositório git
        │
        ├─► docs/dashboard_data.json ──► snapshot para o dashboard web (docs/index.html)
        │
        └─► Power BI (Push Dataset API) ──► métricas + ações + recomendações em tempo real
```

Separadamente, `scripts/suggest_audience.py` é usado sob demanda sempre que você tem um
**novo ativo** para anunciar. Como a maioria dos seus anúncios vem de leilões, o jeito mais
rápido é passar o link da página do lote:

```bash
python scripts/suggest_audience.py --url "https://milanleiloes.com.br/leilao/imoveis/15498" --budget 100
```

A IA lê a página sozinha (usa a ferramenta de busca na web da própria Claude, que roda nos
servidores da Anthropic — não depende de nada instalado localmente), extrai categoria,
descrição, localização e valor do lote, mostra tudo no terminal para você conferir, gera a
recomendação de público, registra tudo (dashboard + Power BI) e cria um rascunho de campanha
**pausada** no Facebook Ads para sua revisão antes de ativar. Se a extração falhar ou vier
incompleta (site fora do ar, layout incomum, exige login), complete manualmente com
`--category`/`--description`/`--location`/`--value` — essas flags também servem para
*corrigir* um campo específico que a IA leu errado, mesmo usando `--url`. Sem link, dá para
usar só as flags manuais, como antes.

## Estrutura do projeto

```
config/settings.yaml           # limites de segurança e parâmetros (versionado, sem segredos)
src/facebook_ads/               # cliente da Graph API + coleta de métricas
src/ai/                         # prompts e chamadas à Claude (recomendação + otimização)
src/safety/                     # guardrails + trilha de auditoria + log de recomendações
src/reporting/                  # push para o Power BI
scripts/run_daily_optimization.py   # roda todo dia via GitHub Actions
scripts/suggest_audience.py         # roda sob demanda para um novo ativo
scripts/setup_powerbi_dataset.py    # roda uma única vez, na configuração inicial
scripts/rollback.py                 # reverte manualmente a última ação em um alvo
.github/workflows/daily-optimization.yml   # agenda a execução diária
.github/workflows/ci.yml                   # roda os testes em cada PR
docs/index.html                 # dashboard web (publicável via GitHub Pages)
docs/dashboard_data.json        # dados que alimentam o dashboard (gerado pelo pipeline)
logs/audit_log.jsonl            # trilha de auditoria (append-only, versionada no git)
logs/audience_recommendations.jsonl   # histórico de recomendações de público
tests/                          # testes das guardrails de segurança
```

## Configuração inicial

### 1. Requisitos

- Python 3.11+
- Uma conta de anúncios do Facebook (Business Manager) com um App no
  [Meta for Developers](https://developers.facebook.com/) e um **token de acesso** com as
  permissões `ads_management`, `ads_read` e `business_management`. Para automação diária,
  use um **token de usuário do sistema (System User)** de longa duração, não o token de um
  usuário pessoal (que expira). Veja `docs/SETUP_FACEBOOK.md`.
- Uma chave de API da Anthropic (`ANTHROPIC_API_KEY`).
- Um workspace do Power BI Pro/PPU + um App Registration no Azure AD para autenticação via
  client credentials. Veja `docs/SETUP_POWERBI.md`.

### 2. Instalação local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# edite .env com suas credenciais
```

### 3. Configurar o Power BI (uma única vez)

```bash
python scripts/setup_powerbi_dataset.py
```

Isso cria o dataset de push no seu workspace e imprime o `dataset_id` — copie esse valor
para `POWERBI_DATASET_ID` no `.env` (local) e nos Secrets do GitHub (produção).

### 4. Ajustar os limites de segurança

Abra `config/settings.yaml` e revise **especialmente**:

- `safety.account_daily_budget_cap_cents` — o teto máximo que a soma dos orçamentos diários
  de todas as campanhas ativas pode atingir. **Ajuste para o seu orçamento mensal real.**
- `safety.dry_run` — comece com `true`. Nesse modo o sistema faz tudo (analisa, decide,
  registra no log e envia ao Power BI) menos aplicar mudanças reais no Facebook.
- `facebook.conversion_action_type` — o tipo de conversão que representa um resultado de
  verdade para o seu negócio (lead, compra, etc.). Veja `docs/SETUP_FACEBOOK.md`.

### 5. Testar localmente em dry-run

```bash
python scripts/run_daily_optimization.py
```

Revise a saída no terminal e o arquivo `logs/audit_log.jsonl` gerado. Rode algumas vezes
(em dias diferentes, com dados reais) até confiar no comportamento da IA e das guardrails.
Esse comando também grava `docs/dashboard_data.json` — abra `docs/index.html` direto no
navegador (duplo clique) para ver os dados reais no dashboard antes mesmo de publicar
qualquer coisa.

### 6. Configurar os Secrets no GitHub

Em **Settings → Secrets and variables → Actions** do repositório, cadastre:

`FB_ACCESS_TOKEN`, `FB_AD_ACCOUNT_ID`, `FB_APP_ID`, `FB_APP_SECRET`, `ANTHROPIC_API_KEY`,
`POWERBI_TENANT_ID`, `POWERBI_CLIENT_ID`, `POWERBI_CLIENT_SECRET`, `POWERBI_WORKSPACE_ID`,
`POWERBI_DATASET_ID`.

O workflow `.github/workflows/daily-optimization.yml` roda todo dia às 09:00 UTC
(06:00 no horário de Brasília) — ajuste o `cron` se quiser outro horário. Ele só é
disparado automaticamente no branch padrão do repositório; após o merge desta branch,
confirme que o `cron` está ativo em **Actions**.

### 7. Publicar o dashboard (GitHub Pages)

Passo único, manual (a API do GitHub Pages exige isso na primeira vez):

1. No repositório, vá em **Settings → Pages**.
2. Em **Source**, escolha **Deploy from a branch**.
3. Em **Branch**, escolha o branch padrão (ex: `main`) e a pasta **`/docs`**. Salve.
4. Em alguns minutos o dashboard fica disponível em
   `https://<seu-usuario>.github.io/<repositorio>/`.

A partir da primeira execução do workflow diário (ou de `scripts/suggest_audience.py`
com o commit dos dados), o dashboard passa a mostrar dados reais automaticamente — não
precisa repetir esse passo depois.

### 8. Ligar a automação de verdade

Depois de validar o comportamento em dry-run, edite `config/settings.yaml`,
mude `safety.dry_run` para `false`, e faça commit. A partir daí o sistema passa a aplicar
mudanças reais nas suas campanhas, sempre dentro dos limites configurados.

## Dashboard web

`docs/index.html` é um painel estático de página única — sem servidor, sem build, sem
dependências externas. Ele tenta carregar `docs/dashboard_data.json` (gerado a cada
execução do pipeline); se esse arquivo ainda não existir (repositório recém-criado),
mostra dados de exemplo com um aviso no topo, para você já ver o layout funcionando.

Mostra: gasto/conversões/CPA do período, o resumo que a própria IA escreveu sobre a
execução do dia, um gráfico de gasto diário, a tabela de performance por adset, o feed
de decisões da IA (aplicadas, simuladas ou bloqueadas pelas guardrails, com o motivo do
bloqueio) e as recomendações de público-alvo mais recentes.

## Sistema de segurança (guardrails)

A IA **propõe**, mas nunca aplica nada diretamente — toda ação passa por
`src/safety/guardrails.py`, que aplica, de forma determinística (sem IA envolvida nessa
etapa):

- **Variação máxima de orçamento por dia** (`max_budget_change_pct_per_day`) — nenhuma
  mudança pode passar disso, mesmo que a IA sugira algo maior (o valor é limitado/"clipado").
- **Teto de gasto da conta** (`account_daily_budget_cap_cents`) — nenhum aumento pode fazer
  a soma dos orçamentos ultrapassar esse teto.
- **Cooldown** (`cooldown_hours_between_changes`) — o mesmo adset/campanha não pode ser
  alterado duas vezes seguidas em menos de X horas, evitando oscilação.
- **Dados mínimos** (`min_spend_before_action_cents`) — a IA não pode agir sobre um
  adset com gasto insuficiente para uma decisão confiável.
- **Confiança mínima** (`require_ai_confidence`) — ações com confiança baixa reportada pela
  própria IA são descartadas.
- **Limite de ações por execução** (`max_actions_per_run`, `max_pauses_per_run`) — limita o
  "raio de explosão" de uma única rodada.

Toda decisão (aprovada, ajustada ou rejeitada) é registrada. As rejeitadas aparecem no log
de execução do GitHub Actions, para você acompanhar o que a IA queria fazer mas foi barrado.

### Rollback manual

Se uma ação automática precisar ser desfeita:

```bash
python scripts/rollback.py <id_do_objeto_no_facebook>
```

Isso reverte a campanha/adset para o valor anterior registrado na trilha de auditoria.

## Limitações conhecidas

- `scripts/suggest_audience.py` cria a campanha **pausada** e sugere interesses por nome —
  o Meta exige IDs específicos de segmentação (busca via Graph API), então revise e resolva
  os interesses/localizações no Gerenciador de Anúncios antes de ativar. Isso é intencional:
  criar uma campanha nova com orçamento real sem revisão humana é um risco desnecessário.
- O otimizador diário só age sobre campanhas/adsets já ativos com histórico — campanhas
  novíssimas (sem gasto) não sofrem ação até acumularem dados mínimos.
- Se a campanha usa **Orçamento de Campanha Otimizado (CBO)**, o orçamento é controlado no
  nível da campanha, não do adset — os metadados coletados já identificam isso
  (`budget_control_level`), mas vale conferir se as ações propostas fazem sentido no seu
  setup.
- O dashboard (`docs/index.html`) atualiza uma vez por dia, junto com a execução do
  workflow — não é "ao vivo" minuto a minuto. Para isso, use o Power BI.
- A extração via `--url` (`src/ai/listing_extractor.py`) foi construída e testada com dados
  simulados, mas **não pôde ser testada contra um site real de leilão** — o ambiente onde
  este projeto foi desenvolvido não tem acesso geral à internet. A extração depende da
  ferramenta de busca na web da Claude conseguir acessar e ler a página; sites que exigem
  login, têm proteção anti-bot agressiva, ou renderizam o conteúdo só via JavaScript pesado
  podem não funcionar bem. Teste com uma URL real assim que configurar o `ANTHROPIC_API_KEY`
  — se a extração falhar ou vier incompleta para o seu site de leilão, o comando informa o
  motivo e você pode completar manualmente com `--category`/`--description`/`--location`.

## Próximos passos sugeridos

- Criar relatórios/dashboards no Power BI em cima das tabelas `CampaignPerformance`,
  `OptimizerActions` e `AudienceRecommendations`.
- Expandir os testes (`tests/`) conforme o sistema evoluir — hoje cobrem o núcleo mais
  crítico (guardrails de orçamento).
- Considerar alertas (e-mail/Slack) quando a IA sinalizar `flag_for_audience_refresh` ou
  quando muitas ações forem rejeitadas em sequência — hoje isso só aparece no log de
  execução do GitHub Actions.
- Processar vários links de leilão de uma vez (lista de URLs, ou a página de listagem
  completa do site do leilão) em vez de um lote por execução do `suggest_audience.py`.
- Usar a data de encerramento do leilão (`auction_end_at`, já extraída mas ainda não usada
  na lógica) para o otimizador diário priorizar ou acelerar ajustes em lotes perto do fim.
