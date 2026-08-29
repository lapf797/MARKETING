# Marketing — Leilões no Facebook Ads com IA

Sistema de marketing automatizado para promover ativos de leilão (imóveis, veículos,
máquinas, equipamentos etc.) no Facebook Ads, com cinco camadas:

1. **Criação de anúncios a partir do catálogo do leilão** — envie o PDF do catálogo
   inteiro (dezenas de lotes de uma vez); a Claude lê o documento (texto e fotos, com
   visão nativa de PDF — sem nenhum código de extração de imagem escrito à mão), extrai
   cada ativo e já gera a copy do anúncio, o público-alvo e o orçamento sugerido. Cada
   extração vira um **rascunho** para revisão humana antes de qualquer chamada real ao
   Facebook. Ao aprovar, a imagem do criativo é composta automaticamente (foto do ativo
   realçada + marca + selos de preço/parcelamento/data — veja "Geração automática da
   imagem do anúncio").
2. **Públicos semelhantes (lookalike)** — a partir de uma lista de arrematantes/leads
   anteriores, o sistema cria um público personalizado e um semelhante no Facebook,
   aplicados automaticamente em toda nova campanha junto com os interesses sugeridos.
3. **Recomendação de público-alvo avulsa** — para um único ativo (por link ou dados
   manuais), a Claude analisa o histórico de performance da conta e sugere o público ideal.
4. **Otimização diária automática** — todo dia, a Claude analisa a performance recente de
   todas as campanhas ativas em duas frentes: orçamento (aumentar/diminuir/pausar/retomar)
   e, separadamente, posicionamento/demografia sem tocar em orçamento (concentrar a mesma
   verba onde o clique já saiu mais barato). Ambas passam por **guardrails de segurança**
   (limites configuráveis por você) antes de serem aplicadas de verdade no Facebook Ads.
5. **Dashboard web + Power BI** — um painel estático (`docs/index.html`, publicável via
   GitHub Pages) mostra gasto, conversões, decisões da IA, rascunhos pendentes de
   aprovação e recomendações — sem precisar de nenhuma ferramenta externa. O Power BI
   (opcional) recebe os mesmos dados em tempo real, para relatórios mais robustos e
   compartilhamento com a equipe.

Tudo isso roda sozinho via GitHub Actions, sem precisar de servidor.

> **Origem:** a criação a partir de catálogo (item 1), a otimização de posicionamento, os
> públicos semelhantes e a geração automática de imagem portaram para cá a fórmula de copy,
> as faixas de orçamento, a lógica de segmentação (interesses/geolocalização resolvidos em
> IDs reais da Meta, `end_time` automático na data do leilão) e a identidade visual de um
> protótipo que já rodava em produção em Base44 — trocando o `InvokeLLM` genérico do Base44
> pela Claude, adicionando guardrails de segurança que o protótipo não tinha, e mantendo o
> dashboard já existente neste repositório.

## Criar anúncios a partir do catálogo do leilão

Este é o fluxo pensado para a maioria dos seus anúncios. Dois passos, dois scripts —
nenhum deles precisa de conta de anúncios configurada antes de você já ver os rascunhos.

### 1. Analisar o catálogo (não toca no Facebook)

```bash
python scripts/analyze_catalog.py \
  --pdf caminho/ou/url/do/catalogo.pdf \
  --link-url "https://milanleiloes.com.br/leilao/imoveis" \
  --account-id act_123456 --page-id 987654321
```

A Claude lê o PDF inteiro (texto e fotos) numa única chamada e devolve, para cada ativo:
categoria, cidade/UF, preço, público-alvo (idade/gênero/interesses), e a copy pronta do
anúncio (headline até 40 caracteres, texto principal até 125, descrição até 200) — seguindo
uma fórmula de copywriting testada em uso real (gancho de preço abaixo do mercado +
parcelamento, sem clichês, sem caixa alta). O orçamento total e a data de pausa **não** são
decididos pela IA: são calculados por código determinístico
(`src/ai/budget_rules.py`), por faixa de valor do ativo — ajustável em
`config/settings.yaml` → `ads.budget_tiers`.

Cada ativo extraído vira um **rascunho** em `logs/ad_drafts.json` (visível também no
dashboard, seção "Rascunhos de anúncios") — nada é criado no Facebook nesta etapa.

### 2. Revisar e aprovar

Cada rascunho precisa de uma foto (o sistema não extrai/associa imagens automaticamente —
veja "Limitações conhecidas") e, se não foram passados no passo 1, de conta e página:

```bash
python scripts/create_campaigns_from_drafts.py --draft-id <id> --picture-url "https://.../foto.jpg"
```

Revise o que seria criado (sem aplicar nada):

```bash
python scripts/create_campaigns_from_drafts.py
```

Aprove — cria de verdade a campanha, o conjunto de anúncios, o criativo e o anúncio no
Facebook (segmentação com interesses e geolocalização já resolvidos para os IDs reais que a
Meta exige, orçamento diário = orçamento total ÷ dias até o leilão, e o anúncio programado
para pausar sozinho na data do leilão via `end_time` nativo do Facebook):

```bash
python scripts/create_campaigns_from_drafts.py --confirm          # todos os rascunhos prontos
python scripts/create_campaigns_from_drafts.py --draft-id <id> --confirm   # só um
python scripts/create_campaigns_from_drafts.py --draft-id <id> --reject    # descarta sem criar
```

Por padrão a campanha já nasce **ativa** (`ads.default_campaign_status` em
`config/settings.yaml`) — igual ao comportamento validado no protótipo anterior, já que essa
etapa em si *é* a aprovação humana. Mude para `"PAUSED"` se preferir sempre revisar no
Gerenciador de Anúncios antes de ativar.

## Públicos semelhantes (lookalike)

Se você tem uma exportação de arrematantes/leads anteriores (um CSV com e-mail e/ou
telefone), dá para usar isso como uma camada a mais de segmentação — além dos interesses
que a IA sugere:

```bash
python scripts/sync_custom_audience.py --csv contatos.csv --name "Compradores de Leilao" \
  --email-column email --phone-column celular
```

O script normaliza e transforma cada contato em um hash SHA-256 (a Graph API nunca recebe
e-mail/telefone em texto puro), cria um **Público Personalizado** no Facebook, envia os
contatos em lotes, e a partir dele cria um **Público Semelhante (Lookalike)** — por padrão,
os 5% de usuários mais parecidos com a sua base (`ads.lookalike_ratio` em
`config/settings.yaml`). Note que a Meta pode levar algumas horas para processar um público
novo antes de aceitar gerar o semelhante a partir dele; se isso acontecer, o script avisa e
basta rodar de novo mais tarde.

A partir daí, toda nova campanha criada por `create_campaigns_from_drafts.py` (ou por
`suggest_audience.py`) passa a aplicar automaticamente o público semelhante mais recente,
junto com os interesses — sem precisar de nenhum passo extra. Para desligar isso, mude
`ads.use_lookalike_audience` para `false`.

## Geração automática da imagem do anúncio

Antes de subir o anúncio, o sistema compõe automaticamente uma imagem de criativo a
partir da foto real do ativo (`src/creative/`): realça a foto (contraste, cor,
nitidez, upscale se for pequena demais), sobrepõe a marca (logo real, se configurada, ou
um selo de texto — nunca inventa uma logo gráfica), o título, a localização, a data do
leilão e selos de "preço abaixo do mercado" / parcelamento. O resultado é uma imagem
1080x1080 (compatível com feed do Facebook e do Instagram), enviada para a biblioteca de
imagens da conta (`FacebookAdsClient.upload_ad_image`) e usada no lugar da foto crua.

Está ligado por padrão (`creative.auto_generate_image: true` em
`config/settings.yaml`). Se a foto não puder ser baixada/processada por qualquer motivo,
`create_campaigns_from_drafts.py` cai de volta para a foto original sem interromper a
criação da campanha, e registra um aviso.

**Para usar a logo real da sua marca**, em vez do selo de texto padrão, edite
`config/settings.yaml`:

```yaml
creative:
  logo_path: "assets/brand/sua_logo.png"   # PNG com fundo transparente, de preferência
  color_dark: "#0F1F3D"      # cores da sua identidade visual
  color_accent: "#D6AF5A"
  color_secondary: "#03A3BE"
```

`logo_path` aceita tanto um caminho local (dentro do repositório, ex:
`assets/brand/sua_logo.png`) quanto uma URL pública.

**Para ver o resultado antes de aprovar qualquer rascunho**, sem gastar nenhuma chamada
de API (Facebook ou Claude):

```bash
python scripts/preview_ad_creative.py --photo foto_do_imovel.jpg \
  --headline "Casa 3 quartos com piscina no Jardim das Flores" \
  --location "Porto Alegre, RS" --auction-date 15/12/2026
```

Isso salva `preview_creative.jpg` na pasta atual (ajustável com `--output`) para você
abrir e conferir — útil para testar títulos, cores ou uma logo diferente
(`--logo outra_logo.png`) antes de mexer em qualquer campanha de verdade.

## Otimização de posicionamento e demografia (sem mexer em orçamento)

Complementar à otimização diária de orçamento (abaixo): todo dia, antes de decidir quanto
gastar, `scripts/optimize_placements.py` analisa cada campanha ativa e — com o **mesmo**
orçamento — concentra a verba nos posicionamentos (feed, stories, reels, etc.) e na faixa
de idade/gênero que já provaram clique mais barato. Nunca propõe mudança de valor gasto —
essa é a alavanca mais conservadora do sistema, e roda automaticamente todo dia junto com o
resto (`.github/workflows/daily-optimization.yml`). Pode ser rodado manualmente também:

```bash
python scripts/optimize_placements.py --dry-run          # só mostra o plano
python scripts/optimize_placements.py --campaign-id 123   # uma campanha específica
```

Só age quando há volume suficiente para decidir com segurança
(`safety.min_impressions_before_placement_action`), nunca estreita a faixa etária abaixo de
15 anos de amplitude, e só restringe gênero quando a diferença de CTR/CPC entre eles for
grande (mais de 40%). Se a Meta recusar o recorte de posicionamentos, o sistema tenta de
novo aplicando só o ajuste de idade/gênero antes de desistir.

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
**novo ativo avulso** para anunciar (fora de um catálogo em PDF — para catálogos, use
"Criar anúncios a partir do catálogo do leilão" acima). O jeito mais rápido é passar o link
da página do lote:

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

## Caminho rápido: testar agora pelo GitHub, sem instalar nada

Você não precisa de Python, git, nem terminal para começar a testar de verdade — dá para
disparar tudo pela própria interface do GitHub. O Power BI é opcional e vem desligado por
padrão (`config/settings.yaml` → `powerbi.push_enabled: false`), então só precisa das
credenciais que você já tem (Facebook + Anthropic).

1. No repositório no GitHub, vá em **Settings → Secrets and variables → Actions → New
   repository secret** e cadastre, um de cada vez: `FB_ACCESS_TOKEN`, `FB_AD_ACCOUNT_ID`,
   `FB_APP_ID`, `FB_APP_SECRET`, `ANTHROPIC_API_KEY`.
2. Vá na aba **Actions** do repositório. Na lista à esquerda, escolha um dos dois workflows:
   - **"Sugerir publico-alvo (sob demanda)"** — para testar com o link de um leilão real.
   - **"Otimizacao diaria de campanhas (Facebook Ads)"** — para testar a análise e otimização
     das campanhas já ativas na sua conta (sempre em modo simulação por enquanto, já que
     `safety.dry_run` começa `true`).
3. Clique em **Run workflow**. No campo **Use workflow from**, troque para o branch
   `claude/facebook-ads-marketing-system-66a3tq` (o workflow ainda não está no branch
   principal). Preencha os campos do formulário (ex: o link do leilão e o orçamento) e
   clique em **Run workflow** de novo para confirmar.
4. Acompanhe a execução clicando nela na lista — o log mostra tudo: o que a IA extraiu da
   página, o que ela recomendou, e (no caso da otimização diária) o que as guardrails
   aprovaram ou bloquearam.

Depois que tiver testado o suficiente, os próximos passos (instalação local opcional,
GitHub Pages para o dashboard, Power BI, e finalmente desligar o dry-run) estão detalhados
a seguir.

## Estrutura do projeto

```
config/settings.yaml           # limites de segurança, orçamento e parâmetros (sem segredos)
src/facebook_ads/               # cliente da Graph API + coleta de métricas + resolução de segmentação
src/ai/                         # prompts e chamadas à Claude (catálogo, recomendação, otimização)
src/creative/                   # geração automática da imagem do anúncio (realce + marca + selos)
src/safety/                     # guardrails + trilha de auditoria + rascunhos + log de recomendações
src/reporting/                  # push para o Power BI
src/facebook_ads/dynamic_token.py  # busca o token no login com Facebook (Firebase), se configurado
assets/fonts/                   # fonte vendorizada (Instrument Sans, licença OFL) usada nos criativos
functions/                      # Cloud Functions do login com Facebook (Firebase) — ver docs/SETUP_FIREBASE_OAUTH.md
scripts/analyze_catalog.py             # PDF do catálogo -> rascunhos de anúncio (não toca no Facebook)
scripts/create_campaigns_from_drafts.py  # rascunhos aprovados -> campanhas reais no Facebook
scripts/preview_ad_creative.py      # gera uma prévia local do criativo, sem usar nenhuma API
scripts/sync_custom_audience.py     # CSV de contatos -> público personalizado + semelhante (lookalike)
scripts/optimize_placements.py      # roda todo dia — posicionamento/demografia, nunca orçamento
scripts/run_daily_optimization.py   # roda todo dia via GitHub Actions — orçamento
scripts/suggest_audience.py         # roda sob demanda para um ativo avulso (CLI local)
scripts/run_suggest_audience_from_env.py  # mesma coisa, via variáveis de ambiente (GitHub Actions)
scripts/setup_powerbi_dataset.py    # roda uma única vez, na configuração inicial
scripts/rollback.py                 # reverte manualmente a última ação em um alvo
.github/workflows/daily-optimization.yml   # agenda a execução diária (posicionamento + orçamento)
.github/workflows/suggest-audience.yml     # dispara scripts/suggest_audience.py pela interface do GitHub
.github/workflows/ci.yml                   # roda os testes em cada PR
.github/workflows/deploy-firebase.yml      # publica o login com Facebook (Firebase) sob demanda
docs/index.html                 # dashboard web (publicável via GitHub Pages)
docs/dashboard_data.json        # dados do pipeline diário que alimentam o dashboard
docs/drafts_data.json           # rascunhos de anúncio que alimentam o dashboard
logs/audit_log.jsonl            # trilha de auditoria (append-only, versionada no git)
logs/audience_recommendations.jsonl   # histórico de recomendações de público avulsas
logs/ad_drafts.json             # rascunhos de anúncio do catálogo (mutável — status muda com a revisão)
logs/custom_audiences.json      # públicos personalizados/semelhantes sincronizados (mutável)
tests/                          # testes das guardrails, regras de orçamento, targeting e rascunhos
```

## Configuração inicial

### 1. Requisitos

- Python 3.11+
- Uma conta de anúncios do Facebook (Business Manager) com um App no
  [Meta for Developers](https://developers.facebook.com/) e um **token de acesso** com as
  permissões `ads_management`, `ads_read` e `business_management`. Para automação diária,
  use um **token de usuário do sistema (System User)** de longa duração, não o token de um
  usuário pessoal (que expira). Veja `docs/SETUP_FACEBOOK.md`.
  - **Alternativa sem gerar token na mão**: um botão "Conectar com Facebook" na aba
    Configurações do dashboard, que renova o acesso sozinho — exige uma configuração
    inicial à parte (usa Firebase). Veja `docs/SETUP_FIREBASE_OAUTH.md`.
- Uma chave de API da Anthropic (`ANTHROPIC_API_KEY`).
- **Opcional, pode configurar depois:** um workspace do Power BI Pro/PPU + um App
  Registration no Azure AD para autenticação via client credentials. Veja
  `docs/SETUP_POWERBI.md`.

### 2. Instalação local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# edite .env com suas credenciais
```

### 3. Configurar o Power BI (opcional, uma única vez)

Pode pular esta etapa por enquanto — o sistema funciona inteiro sem ela
(`powerbi.push_enabled: false` já vem desligado em `config/settings.yaml`). Quando quiser
ligar:

```bash
python scripts/setup_powerbi_dataset.py
```

Isso cria o dataset de push no seu workspace e imprime o `dataset_id` — copie esse valor
para `POWERBI_DATASET_ID` no `.env` (local) e nos Secrets do GitHub (produção), cadastre os
outros `POWERBI_*` (veja `docs/SETUP_POWERBI.md`) e mude `push_enabled` para `true`.

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

Em **Settings → Secrets and variables → Actions** do repositório, cadastre pelo menos:

`FB_ACCESS_TOKEN`, `FB_AD_ACCOUNT_ID`, `FB_APP_ID`, `FB_APP_SECRET`, `ANTHROPIC_API_KEY`.

Os `POWERBI_*` (`POWERBI_TENANT_ID`, `POWERBI_CLIENT_ID`, `POWERBI_CLIENT_SECRET`,
`POWERBI_WORKSPACE_ID`, `POWERBI_DATASET_ID`) só são necessários quando você ligar
`powerbi.push_enabled` (passo 3).

Há dois workflows:

- `.github/workflows/daily-optimization.yml` roda automaticamente todo dia às 09:00 UTC
  (06:00 no horário de Brasília) — ajuste o `cron` se quiser outro horário. O agendamento só
  dispara no branch padrão do repositório; após o merge desta branch, confirme que o `cron`
  está ativo em **Actions**. Também pode ser disparado manualmente a qualquer momento
  (**Run workflow**), em qualquer branch.
- `.github/workflows/suggest-audience.yml` só roda sob demanda (**Run workflow**, com o link
  do leilão e o orçamento) — não tem agendamento.

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

A aba **Configurações**, no topo, tem o botão "Conectar com Facebook" (login OAuth, sem
precisar gerar token manualmente — ver `docs/SETUP_FIREBASE_OAUTH.md`). O endereço das
Cloud Functions fica salvo só no navegador (`localStorage`); nenhum token passa pelo
dashboard em nenhum momento.

O card **"Sugerir público-alvo"** dispara o workflow correspondente do GitHub Actions
direto do dashboard (cola o link do leilão e o orçamento, sem abrir o GitHub) — exige uma
configuração opcional à parte (`docs/SETUP_FIREBASE_OAUTH.md`, seção 11).

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

- **A imagem final é composta automaticamente, mas a foto crua ainda é anexada à mão.**
  O sistema não extrai a foto do ativo do PDF sozinho — cada rascunho ainda precisa de uma
  `picture_url` (uma URL pública de imagem) anexada manualmente antes de aprovar
  (`create_campaigns_from_drafts.py --draft-id <id> --picture-url ...`). A IA aponta em
  `photo_page_reference` onde a foto certa está no PDF, para facilitar localizá-la. A
  partir daí, a composição (realce, marca, título, selos) é 100% automática — ver "Geração
  automática da imagem do anúncio".
- **Sem uma logo real configurada, o criativo usa um selo de texto.** O sistema nunca
  inventa uma marca gráfica; até você apontar `creative.logo_path` para um arquivo real
  (`config/settings.yaml`), o topo do criativo mostra o nome da marca em texto. A
  composição de imagem foi testada visualmente com fotos e logo sintéticas (o ambiente de
  desenvolvimento não tinha uma foto real de imóvel nem a logo da Milan Leilões à mão) —
  vale gerar uma prévia (`scripts/preview_ad_creative.py`) com uma foto e a logo reais
  antes de aprovar o primeiro rascunho de verdade.
- `scripts/suggest_audience.py` (o fluxo avulso, sem catálogo) cria campanha e adset com
  segmentação já resolvida em IDs reais da Meta, mas **não cria o criativo/anúncio** — só
  o fluxo de catálogo (`analyze_catalog.py` + `create_campaigns_from_drafts.py`) vai até o
  anúncio completo, pronto para veicular. Isso é intencional: criar um anúncio pronto para
  veicular sem revisão humana explícita é um risco desnecessário fora do fluxo com
  aprovação por rascunho.
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

Ficaram de fora desta rodada, por escopo/tempo — nenhum deles é grande o suficiente para
travar o uso do que já existe, mas valem uma rodada dedicada quando fizer sentido:

- **Extrair automaticamente a foto do ativo direto do PDF/página do leilão.** A
  composição da imagem final (realce, marca, selos, data — ver "Geração automática da
  imagem do anúncio" acima) já é automática; falta só a etapa anterior, hoje manual: cada
  rascunho ainda depende de uma `picture_url` anexada com `--picture-url`.
- Workflow do GitHub Actions (`workflow_dispatch`) para `analyze_catalog.py`,
  `create_campaigns_from_drafts.py` e `sync_custom_audience.py`, nos moldes de
  `suggest-audience.yml` — hoje os três só rodam localmente (o PDF do catálogo e o CSV de
  contatos precisariam estar hospedados numa URL, já que formulários do GitHub Actions não
  aceitam upload de arquivo). `optimize_placements.py` já roda automaticamente todo dia,
  sem precisar disso.
- Criar relatórios/dashboards no Power BI em cima das tabelas `CampaignPerformance`,
  `OptimizerActions` e `AudienceRecommendations`.
- Considerar alertas (e-mail/Slack) quando a IA sinalizar `flag_for_audience_refresh` ou
  quando muitas ações forem rejeitadas em sequência — hoje isso só aparece no log de
  execução do GitHub Actions.
- Usar a data de encerramento do leilão para o otimizador diário priorizar ou acelerar
  ajustes em campanhas perto do fim do prazo.
