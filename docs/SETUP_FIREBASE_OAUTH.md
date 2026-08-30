# Login com Facebook (Firebase) — configuração inicial

Isso substitui o token manual de "Usuário do Sistema" por um botão de **"Conectar com
Facebook"** na aba Configurações do dashboard. É um projeto à parte do resto do sistema —
depois de configurado uma vez, você nunca mais precisa gerar/trocar token na mão, e o
sistema se renova sozinho.

**O que só você (ou alguém de confiança) pode fazer**, porque exige login nas suas próprias
contas: os passos 1 a 6 abaixo. Depois disso, tudo roda sozinho.

Nenhum passo aqui exige instalar nada no computador — tudo é feito pelo navegador (Firebase
Console, Cloud Shell, GitHub, Meta for Developers).

---

## 1. Criar o projeto no Firebase

1. Acesse [console.firebase.google.com](https://console.firebase.google.com) e entre com a
   conta que você já tem.
2. **Adicionar projeto** → dê um nome (ex: "milan-marketing") → pode desativar o Google
   Analytics (não precisamos) → criar.
3. Anote o **ID do projeto** (aparece embaixo do nome, algo como `milan-marketing-a1b2c`) —
   é diferente do nome, você vai precisar dele várias vezes.

## 2. Ativar o plano Blaze

1. No menu do projeto, clique no ícone de engrenagem → **Uso e faturamento** (ou o aviso
   que já aparece pedindo upgrade).
2. Escolha **Blaze (pague conforme o uso)** e cadastre um cartão.
3. Pelo volume de uso deste sistema (algumas chamadas por dia), o custo esperado é
   **R$ 0,00** — o Blaze já inclui uma cota gratuita generosa que cobre isso.

## 3. Criar uma "conta de serviço" para o GitHub usar (pelo Cloud Shell)

O GitHub Actions precisa de uma credencial pra publicar as Cloud Functions sem você estar
logado. Ainda no [console.firebase.google.com](https://console.firebase.google.com), dentro
do seu projeto, clique no ícone de **Cloud Shell** (`>_`) no topo da página — abre um
terminal no navegador, nenhuma instalação local — e rode os três comandos abaixo, um de
cada vez (troque `SEU-PROJECT-ID` pelo ID do seu projeto nos três):

```bash
gcloud iam service-accounts create firebase-deploy --display-name "Deploy GitHub Actions" --project SEU-PROJECT-ID
```

```bash
gcloud projects add-iam-policy-binding SEU-PROJECT-ID \
  --member="serviceAccount:firebase-deploy@SEU-PROJECT-ID.iam.gserviceaccount.com" \
  --role="roles/editor"
```

```bash
gcloud iam service-accounts keys create ~/firebase-deploy-key.json \
  --iam-account=firebase-deploy@SEU-PROJECT-ID.iam.gserviceaccount.com
```

Por fim, mostre o conteúdo do arquivo gerado:

```bash
cat ~/firebase-deploy-key.json
```

Vai aparecer um bloco de texto começando com `{` e terminando com `}` (é um JSON). **Copie
esse bloco inteiro** (do `{` até o `}` final) — é o valor do secret `GCP_SA_KEY` no próximo
passo.

## 4. Cadastrar os dois primeiros secrets no GitHub

**Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Valor |
|---|---|
| `GCP_SA_KEY` | o bloco JSON inteiro do passo 3 |
| `FIREBASE_PROJECT_ID` | o ID do projeto do passo 1 |

## 5. Configurar os segredos das Cloud Functions (ainda no Cloud Shell)

Estes três valores ficam guardados dentro do próprio Firebase (Secret Manager), não no
GitHub — é o Firebase quem usa. Ainda no Cloud Shell:

```bash
firebase functions:secrets:set META_APP_ID --project SEU-PROJECT-ID
firebase functions:secrets:set META_APP_SECRET --project SEU-PROJECT-ID
firebase functions:secrets:set TOKEN_API_KEY --project SEU-PROJECT-ID
```

(troque `SEU-PROJECT-ID` pelo ID do passo 1 nos três comandos)

Cada comando pede pra colar um valor:
- `META_APP_ID` e `META_APP_SECRET`: os mesmos do seu App em
  [developers.facebook.com/apps](https://developers.facebook.com/apps) → Configurações →
  Básico (se você já tem esses dois de uma configuração anterior, é só reaproveitar).
- `TOKEN_API_KEY`: **você inventa** uma senha longa e aleatória agora — pode gerar uma
  rodando `openssl rand -hex 32` no mesmo Cloud Shell e colando o resultado. Guarde esse
  valor também, você vai usar de novo no passo 8.

## 6. Publicar (deploy)

No GitHub: aba **Actions** → **"Deploy do login com Facebook (Firebase)"** → **Run
workflow** (branch `claude/facebook-ads-marketing-system-66a3tq`) → **Run workflow**.

Espere terminar (ícone verde) e clique na execução → abra o passo **"Deploy das Cloud
Functions..."** → procure linhas parecidas com:

```
Function URL (connect_facebook(...)): https://southamerica-east1-milan-marketing-a1b2c.cloudfunctions.net/connect_facebook
Function URL (oauth_callback(...)): https://southamerica-east1-milan-marketing-a1b2c.cloudfunctions.net/oauth_callback
```

Anote o **endereço base** (tudo antes de `/connect_facebook`) — vai precisar dele nos
passos 7 e 9.

## 7. Autorizar o endereço no App da Meta

1. Em [developers.facebook.com/apps](https://developers.facebook.com/apps) → seu App →
   se ainda não tiver, clique **Adicionar produto** → **Login do Facebook** → **Configurar**.
2. Menu **Login do Facebook → Configurações**.
3. Em **URIs de redirecionamento OAuth válidos**, cole a URL do `oauth_callback` (a linha
   completa que você anotou no passo 6, terminando em `/oauth_callback`) → **Salvar
   alterações**.

> Como esse App gerencia só a conta de anúncios da própria empresa (dentro do mesmo
> Business Manager), isso normalmente não exige passar pela revisão completa da Meta — se
> em algum momento aparecer um pedido de revisão/verificação de negócio bloqueando o login,
> me avise que vejo com você o que fazer.

## 8. Conectar pelo dashboard

1. Abra o dashboard (`https://lapf797.github.io/MARKETING/`) → aba **Configurações**.
2. Cole o **endereço base** do passo 6 → **Salvar**.
3. Clique **Conectar com Facebook** → faça login e autorize as permissões pedidas.
4. Deve aparecer "Conectado com sucesso!" — volte pro dashboard, o status deve virar
   "Conectado ao Facebook".

## 9. Trocar o token estático pelo dinâmico nos workflows

Agora que o login está funcionando, troque como os scripts pegam o token — em vez do
`FB_ACCESS_TOKEN` manual, eles passam a buscar sempre o mais atual:

1. Em **Settings → Secrets and variables → Actions**, adicione:

   | Secret | Valor |
   |---|---|
   | `FB_TOKEN_ENDPOINT_URL` | o endereço base do passo 6 + `/get_token` (ex: `https://southamerica-east1-milan-marketing-a1b2c.cloudfunctions.net/get_token`) |
   | `FB_TOKEN_API_KEY` | o mesmo valor de `TOKEN_API_KEY` que você inventou no passo 5 |

2. Pode deixar o `FB_ACCESS_TOKEN` antigo cadastrado (ele simplesmente deixa de ser usado
   assim que os dois novos existirem) ou apagá-lo — como preferir.

## 10. Testar

Rode a aba **Actions → "Sugerir publico-alvo"** de novo com um link de leilão real — se
funcionar sem erro de autenticação, o login com Facebook está no ar. Dali em diante, o
próprio sistema renova o acesso sozinho, uma vez por semana, sem você precisar voltar
aqui — a única exceção é se você revogar o acesso manualmente lá no Facebook, caso em que
basta clicar em "Conectar com Facebook" de novo.

## 11. (Opcional) Disparar "Sugerir público-alvo", "Analisar catálogo" e aprovar rascunhos direto do dashboard

Por padrão, rodar os workflows "Sugerir público-alvo", "Analisar catálogo do leilão" e
"Aprovar rascunho" ainda exige ir na aba Actions do GitHub. Dá pra fazer isso direto do
dashboard (cards "Analisar catálogo do leilão", "Sugerir público-alvo" e "Rascunhos de
anúncios") — exige mais dois secrets, uma vez só. Os três cards usam a mesma chave, então
essa configuração habilita os três de uma vez:

1. **Gerar um token do GitHub**: em
   [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta)
   → **Generate new token** → dê um nome (ex: "Disparo do dashboard") → em
   **Repository access**, escolha **Only select repositories** → selecione o repositório
   `MARKETING` → em **Permissions → Repository permissions**, procure **Actions** e mude
   pra **Read and write** → **Generate token** → copie o token (começa com `github_pat_`
   ou `ghp_`), só aparece uma vez.
2. No Cloud Shell:
   ```bash
   firebase functions:secrets:set GITHUB_PAT --project cobrancas-whstapp
   ```
   Cole o token do passo 1.
3. Invente outra chave (diferente da `TOKEN_API_KEY` do login) e configure:
   ```bash
   openssl rand -hex 32
   firebase functions:secrets:set DASHBOARD_TRIGGER_KEY --project cobrancas-whstapp
   ```
   Cole o valor gerado. **Guarde esse valor** — é o que você cola no dashboard no
   próximo passo.
4. Se o CLI perguntar sobre reimplantar funções com a versão nova do secret, responda
   `Y`. Senão, rode o deploy pelo GitHub (**Actions → "Deploy do login com Facebook
   (Firebase)" → Run workflow**).
5. No dashboard, card **"Sugerir público-alvo"**, cole a chave do passo 3 → Salvar.

Pronto — os três cards passam a funcionar. Para **um leilão inteiro de uma vez** (até 60
lotes), use o card **"Analisar catálogo do leilão"**: preencha o nome do leilão e a URL
pública do PDF do catálogo, e clique **"Analisar catálogo e gerar rascunhos"** — a IA lê
todos os lotes numa passada só. Para **um lote avulso**, o card **"Sugerir público-alvo"**:
preencha o **nome do leilão** (obrigatório — agrupa este lote com os demais do mesmo envio
no card "Rascunhos de anúncios"), cole o link do lote (ou preencha na aba manual),
opcionalmente a **URL da foto do lote** (gera a pré-visualização do anúncio) e o orçamento
diário, e clique **Gerar rascunho**.

Depois de alguns minutos (tempo do GitHub Actions rodar — mais demorado quanto mais lotes
tiver o catálogo), os rascunhos aparecem no card "Rascunhos de anúncios" — nada foi criado
no Facebook ainda. Revise a recomendação de público, a copy e a pré-visualização de cada
um (use o filtro por leilão pra ver só os deste); se estiver tudo certo, clique **"Aprovar
e criar campanha"** (cria a campanha **pausada** de verdade no Facebook Ads) ou
**"Rejeitar"** — os mesmos botões usam a chave configurada no passo 5. Os rascunhos vindos
do catálogo em PDF ainda precisam de uma foto anexada antes de poder aprovar (via
`create_campaigns_from_drafts.py --draft-id <id> --picture-url ...`) — o card "Rascunhos
de anúncios" mostra "faltam: picture_url" nesses casos.

---

## Se algo der errado

- **"Deploy das Cloud Functions" falhou**: abra o log do passo — se mencionar os secrets
  (`META_APP_ID` etc.) não existirem, volte ao passo 5. Se mencionar erro de autenticação
  (401/permissão negada), confira se `GCP_SA_KEY` no GitHub tem o JSON *completo* (do `{`
  ao `}`, sem cortar nada) e se `FIREBASE_PROJECT_ID` está certo.
- **"Conectado com sucesso" nunca aparece / erro da Meta**: confira se a URL do passo 7
  está *exatamente* igual à do log do deploy (sem barra `/` sobrando no final).
- **Dashboard mostra "não consegui confirmar o status"**: confira se colou o endereço
  *base* (sem `/connect_facebook` no final) na aba Configurações.
- **"Sugerir público-alvo" no dashboard dá "não autorizado"**: a chave colada no card não
  bate com `DASHBOARD_TRIGGER_KEY` — clique "Trocar chave" e cole de novo.
- **"o GitHub recusou o disparo"**: o `GITHUB_PAT` expirou, foi revogado, ou não tem
  permissão de "Actions: write" no repositório — gere um novo token (passo 11.1) e
  regrave o secret.
- **Card "Analisar catálogo do leilão" dá "Configure a chave de disparo..."**: use a
  configuração do passo 11.5 (é feita uma vez só, no card "Sugerir público-alvo" — o card
  do catálogo reaproveita a mesma chave, não tem um campo próprio para colar de novo).
- **Card "Analisar catálogo" roda mas nenhum rascunho aparece**: confira a execução
  "Analisar catalogo do leilao" na aba Actions do GitHub — o log mostra quantos ativos
  foram identificados; se vier "0 ativo(s) identificado(s)", a IA não reconheceu nenhum
  lote no PDF (confira se a URL aponta direto para o arquivo PDF, não para uma página HTML
  que só linka para ele).
- **Botão "Aprovar"/"Rejeitar" no card "Rascunhos de anúncios" dá "Configure o endereço
  das Cloud Functions..."**: mesma configuração da aba Configurações (passo 8) — os
  botões usam o mesmo endereço salvo lá.
- **Botão "Aprovar"/"Rejeitar" dá "Configure a chave de disparo..."**: falta fazer o passo
  11.5 (colar a chave no card "Sugerir público-alvo") — é a mesma chave usada pelos dois
  cards.
- **Cliquei "Aprovar" mas o rascunho nunca vira "Criada"**: confira a execução do workflow
  "Aprovar rascunho" na aba Actions do GitHub — se falhou, o log mostra o motivo (ex:
  `account_id`/`page_id`/`picture_url` faltando, ou a Meta recusou algum campo); o rascunho
  aparece em "Erros recentes" no dashboard com a mensagem.
