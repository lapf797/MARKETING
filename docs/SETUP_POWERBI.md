# Configuração do Power BI (Push Dataset em tempo real)

O sistema envia dados para o Power BI via **Push Dataset API**, autenticando como uma
aplicação (não como um usuário) usando um App Registration do Azure AD com o fluxo
*client credentials*. Isso permite que o GitHub Actions envie dados automaticamente, sem
um usuário precisar estar logado.

## 1. Criar o App Registration no Azure AD

1. Acesse o [Portal do Azure](https://portal.azure.com) → **Azure Active Directory
   (Microsoft Entra ID) → App registrations → New registration**.
2. Dê um nome (ex: "Marketing Leiloes - Push Dataset") e registre.
3. Anote o **Application (client) ID** → `POWERBI_CLIENT_ID`.
4. Anote o **Directory (tenant) ID** → `POWERBI_TENANT_ID`.
5. Em **Certificates & secrets → New client secret**, crie um segredo, copie o **Value**
   (não o Secret ID) → `POWERBI_CLIENT_SECRET`. Ele só aparece uma vez.
6. Em **API permissions**, adicione a permissão de aplicativo (Application permission)
   `Dataset.ReadWrite.All` da API **Power BI Service**, e clique em "Grant admin consent"
   (precisa de um admin do tenant).

## 2. Habilitar acesso de service principal no Power BI

No [portal de administração do Power BI](https://app.powerbi.com/admin-portal/tenantSettings)
(precisa ser admin do Power BI):

1. Em **Developer settings**, habilite **"Allow service principals to use Power BI APIs"**.
2. Restrinja a um grupo de segurança específico se quiser limitar o escopo (recomendado) —
   crie um grupo de segurança no Azure AD, adicione o App Registration a ele, e aponte a
   configuração para esse grupo.

## 3. Dar acesso do App Registration ao workspace

1. No Power BI, crie (ou use) um **workspace** dedicado (ex: "Marketing Leiloes").
   Push Datasets exigem um workspace Pro/Premium/PPU — não funcionam no "Meu espaço de
   trabalho" pessoal.
2. Em **Configurações do workspace → Acesso**, adicione o App Registration (pelo nome
   dele) com papel **Membro** ou **Contribuidor**.
3. Copie o **Workspace ID** da URL do workspace (`.../groups/<WORKSPACE_ID>/...`) →
   `POWERBI_WORKSPACE_ID`.

## 4. Criar o dataset de push

Com `POWERBI_TENANT_ID`, `POWERBI_CLIENT_ID`, `POWERBI_CLIENT_SECRET` e
`POWERBI_WORKSPACE_ID` já preenchidos no seu `.env`, rode uma única vez:

```bash
python scripts/setup_powerbi_dataset.py
```

O script cria o dataset com as três tabelas usadas pelo sistema (`CampaignPerformance`,
`OptimizerActions`, `AudienceRecommendations`) e imprime o `dataset_id` — copie para
`POWERBI_DATASET_ID` no `.env` e nos Secrets do GitHub.

## 5. Construir os relatórios

No Power BI Desktop ou na web, conecte-se ao dataset de push (workspace →
"Marketing Leiloes - Facebook Ads") como qualquer outra fonte de dados, e monte os
relatórios/dashboards em cima das três tabelas. Como é um dataset de push (não import),
os visuais atualizam conforme novos dados chegam — não precisa configurar refresh
agendado para essas tabelas.

## Observações

- Push Datasets mantêm um histórico limitado por padrão (a tabela cresce continuamente a
  cada execução diária). Se quiser evitar acúmulo indefinido, use `PowerBIClient.clear_table`
  (em `src/reporting/powerbi_push.py`) periodicamente, ou configure retenção via a API do
  Power BI.
- Se preferir trocar para importação/agendamento em vez de push em tempo real no futuro,
  a trilha de auditoria (`logs/audit_log.jsonl`) e os dados brutos de insights continuam
  disponíveis como fonte alternativa.
