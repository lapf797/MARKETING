# Configuração da API de Marketing do Facebook

Você já indicou que tem Business Manager, App e token. Este guia cobre os pontos que
costumam travar uma automação diária: tipo de token, permissões, e como descobrir o
`conversion_action_type` certo para o seu funil.

## 1. Token de acesso — use um System User, não um token pessoal

Um token gerado a partir do seu usuário pessoal expira (60 dias, ou menos se você trocar
a senha) e quebra a automação sem aviso. Para produção, use um **usuário do sistema
(System User)**:

1. No Business Manager, vá em **Configurações do Negócio → Usuários → Usuários do sistema**.
2. Crie um usuário do sistema com papel **Admin** (ou Employee, se seu App só precisa de
   `ads_management`/`ads_read`).
3. Atribua a ele acesso à conta de anúncios (`Ad Account`) que você vai automatizar.
4. Gere um token para esse usuário do sistema, selecionando o App e as permissões:
   `ads_management`, `ads_read`, `business_management`.
5. Escolha validade **"Nunca expira"** (tokens de usuário de sistema podem ser gerados
   sem expiração). Guarde esse token com segurança — ele equivale a uma senha.

Esse é o valor de `FB_ACCESS_TOKEN`.

## 2. ID da conta de anúncios

No Gerenciador de Anúncios, o ID aparece como `act_1234567890` ou apenas `1234567890`
(o código já lida com os dois formatos). Esse é o `FB_AD_ACCOUNT_ID`.

## 3. Descobrindo o `conversion_action_type` certo

O sistema calcula CPA (custo por conversão) usando um `action_type` específico da Graph
API — precisa ser exatamente o resultado que representa valor para o seu negócio (um
cadastro/lead para dar lance, uma compra, etc.). Formas comuns:

- `"lead"` — evento de lead padrão (Facebook Lead Ads ou pixel configurado como lead).
- `"offsite_conversion.fb_pixel_lead"` — lead via pixel no seu site.
- `"purchase"` / `"offsite_conversion.fb_pixel_purchase"` — compra.
- `"offsite_conversion.custom.<ID_DO_EVENTO>"` — uma conversão personalizada específica.

Como descobrir o valor exato da sua conta: rode o sistema uma vez em dry-run
(`python scripts/run_daily_optimization.py`) e inspecione a resposta bruta de insights, ou
consulte o **Gerenciador de Eventos** (Events Manager) → seu pixel/conjunto de dados →
aba de eventos, e veja o nome técnico do evento que representa sua conversão principal.
Ajuste `facebook.conversion_action_type` em `config/settings.yaml` de acordo.

## 4. Orçamento de Campanha Otimizado (CBO) vs. orçamento por adset

Se suas campanhas usam CBO, o campo `daily_budget` fica na **campanha**, não no adset. O
sistema já detecta isso automaticamente (coluna `budget_control_level` nos metadados
enviados à IA) e direciona as ações de orçamento para o nível correto — mas vale conferir
no Gerenciador de Anúncios se o comportamento faz sentido para o seu setup.

## 5. Interesses e localizações — limitação conhecida

Quando `scripts/suggest_audience.py` sugere interesses (ex: "Real estate", "Automóveis")
e localizações, esses são **nomes**, não os IDs que a Graph API realmente exige para
segmentação (`targeting.flexible_spec` para interesses, `targeting.geo_locations` para
localização). Para resolver:

- Interesses: `GET /search?type=adinterest&q=<termo>&access_token=...`
- Localizações: `GET /search?type=adgeolocation&q=<termo>&access_token=...`

O script cria a campanha e o adset **pausados** justamente para você revisar e completar
essa segmentação no Gerenciador de Anúncios antes de ativar — evita lançar uma campanha
com público mal configurado.

## 6. Limites de taxa (rate limits)

A Graph API tem limites de chamadas por hora, por conta de anúncios. Para uma execução
diária única, isso raramente é um problema — mas se você expandir para múltiplas contas
ou rodar o script com mais frequência, monitore o header `X-Business-Use-Case-Usage` das
respostas.
