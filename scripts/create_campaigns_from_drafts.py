"""Cria de verdade, no Facebook Ads, as campanhas a partir dos rascunhos aprovados
(logs/ad_drafts.json, gerados por scripts/analyze_catalog.py). Só escreve no Facebook com
--confirm — sem essa flag, só mostra o que seria feito.

Uso:
    # Revisar o que seria criado, sem aplicar nada:
    python scripts/create_campaigns_from_drafts.py

    # Anexar a foto de um rascunho específico (obrigatório antes de aprovar):
    python scripts/create_campaigns_from_drafts.py --draft-id <id> --picture-url <url>

    # Criar todos os rascunhos pendentes ("rascunho") que já tenham foto/conta/página:
    python scripts/create_campaigns_from_drafts.py --confirm

    # Criar só um rascunho específico:
    python scripts/create_campaigns_from_drafts.py --draft-id <id> --confirm

    # Rejeitar um rascunho sem criar nada no Facebook:
    python scripts/create_campaigns_from_drafts.py --draft-id <id> --reject
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai.budget_rules import days_until
from src.config import AppConfig, load_config
from src.creative.pipeline import generate_ad_image_bytes
from src.facebook_ads.client import FacebookAdsClient
from src.facebook_ads.targeting import resolve_geo_locations, resolve_interests
from src.safety.audience_registry import get_latest_lookalike
from src.safety.audit_log import log_action
from src.safety.draft_log import get_draft, read_drafts, update_draft, write_dashboard_snapshot

_GENDER_CODES = {"male": [1], "female": [2], "all": [0]}


def _create_one(fb_client: FacebookAdsClient, draft: dict, *, config: AppConfig) -> dict:
    default_status = config.ads.default_campaign_status
    prop = draft["property"]
    account_id = draft.get("account_id")
    page_id = draft.get("page_id")
    link_url = draft.get("link_url")
    picture_url = draft.get("picture_url")

    missing = [name for name, value in [
        ("account_id", account_id), ("page_id", page_id),
        ("link_url", link_url), ("picture_url", picture_url),
    ] if not value]
    if missing:
        raise ValueError(f"faltam campos obrigatórios no rascunho: {', '.join(missing)}")

    if draft.get("daily_budget_cents"):
        # Rascunho do fluxo avulso (scripts/suggest_audience.py): o usuário já informou um
        # orçamento diário fixo, não um total a diluir até a data do leilão.
        daily_budget_cents = draft["daily_budget_cents"]
    else:
        days = days_until(draft.get("pause_date"))
        daily_budget_cents = max(1, round(draft["total_budget_cents"] / days))

    campaign = fb_client.create_campaign(
        name=draft["campaign_name"], objective="OUTCOME_TRAFFIC", status=default_status,
        # Categoria especial vazia de propósito: o serviço anunciado é o leilão em si
        # (prestação de serviço do leiloeiro), não a venda direta do imóvel/veículo — isso
        # preserva a segmentação por idade/gênero/interesses, que a Meta remove
        # automaticamente para as special_ad_categories de moradia/emprego/crédito.
        special_ad_categories=[],
    )
    campaign_id = campaign["id"]

    geo = resolve_geo_locations(fb_client, city=prop.get("city"), state=prop.get("state"))
    interests = resolve_interests(fb_client, prop.get("interests") or [])
    genders = _GENDER_CODES[prop["gender_targeting"]]

    lookalike_id = None
    if config.ads.use_lookalike_audience:
        lookalike = get_latest_lookalike()
        if lookalike:
            lookalike_id = lookalike["lookalike_audience_id"]

    base_targeting = {
        "geo_locations": geo,
        "age_min": prop["age_min"],
        "age_max": prop["age_max"],
        "genders": genders,
        # A Meta exige declarar isso explicitamente para a segmentação manual não ser
        # sobrescrita pelo público automático "Advantage+".
        "targeting_automation": {"advantage_audience": 0},
    }
    targeting = dict(base_targeting)
    if interests:
        targeting["flexible_spec"] = [{"interests": interests}]
    if lookalike_id:
        # Camada extra de segmentação por cima dos interesses: um público semelhante aos
        # arrematantes/leads anteriores (sincronizado via scripts/sync_custom_audience.py).
        targeting["custom_audiences"] = [{"id": lookalike_id}]

    end_time = f"{draft['pause_date']}T23:59:59-03:00" if draft.get("pause_date") else None

    warning = None
    try:
        adset = fb_client.create_adset(
            campaign_id=campaign_id, name=f"{draft['campaign_name']} - Conjunto",
            daily_budget_cents=daily_budget_cents, targeting=targeting,
            optimization_goal="LINK_CLICKS", billing_event="IMPRESSIONS", status=default_status,
            end_time=end_time,
        )
    except Exception as exc:
        if not interests and not lookalike_id:
            raise  # nada de refinado a remover — o erro não é sobre o público, repropagar
        warning = f"a Meta recusou os interesses/público semelhante sugeridos e eles foram removidos: {exc}"
        adset = fb_client.create_adset(
            campaign_id=campaign_id, name=f"{draft['campaign_name']} - Conjunto",
            daily_budget_cents=daily_budget_cents, targeting=base_targeting,
            optimization_goal="LINK_CLICKS", billing_event="IMPRESSIONS", status=default_status,
            end_time=end_time,
        )
    adset_id = adset["id"]

    image_hash = None
    if config.creative.auto_generate_image:
        try:
            image_bytes = generate_ad_image_bytes(
                picture_url=picture_url, prop=prop, pause_date=draft.get("pause_date"), config=config,
            )
            image_hash = fb_client.upload_ad_image(image_bytes, filename=f"{draft['draft_id']}.jpg")["hash"]
        except Exception as exc:
            image_note = f"não foi possível gerar o criativo automático, usando a foto original: {exc}"
            warning = f"{warning}; {image_note}" if warning else image_note

    creative = fb_client.create_ad_creative(
        name=f"{draft['campaign_name']} - Criativo", page_id=page_id, link=link_url,
        message=prop["primary_text"], headline=prop["headline"], description=prop["ad_description"],
        picture_url=picture_url, image_hash=image_hash,
    )
    ad = fb_client.create_ad(name=f"{draft['campaign_name']} - Anúncio", adset_id=adset_id,
                              creative_id=creative["id"], status=default_status)

    return {
        "campaign_id": campaign_id, "adset_id": adset_id, "creative_id": creative["id"],
        "ad_id": ad["id"], "daily_budget_cents": daily_budget_cents, "warning": warning,
        "interests_applied": [i["name"] for i in interests],
        "lookalike_applied": lookalike_id,
        "image_generated": image_hash is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria no Facebook Ads as campanhas a partir dos rascunhos aprovados.")
    parser.add_argument("--draft-id", default=None,
                         help="Processa só este rascunho (por padrão, processa todos com status 'rascunho')")
    parser.add_argument("--picture-url", default=None,
                         help="Anexa esta URL de foto ao rascunho (precisa de --draft-id) e sai, sem criar nada")
    parser.add_argument("--reject", action="store_true",
                         help="Marca o rascunho como rejeitado, sem criar nada no Facebook (precisa de --draft-id)")
    parser.add_argument("--confirm", action="store_true",
                         help="Cria de verdade no Facebook Ads. Sem esta flag, só mostra o que seria feito.")
    args = parser.parse_args()

    if args.picture_url:
        if not args.draft_id:
            parser.error("--picture-url precisa de --draft-id")
        update_draft(args.draft_id, picture_url=args.picture_url)
        write_dashboard_snapshot()
        print(f"Foto anexada ao rascunho {args.draft_id}.")
        return

    if args.reject:
        if not args.draft_id:
            parser.error("--reject precisa de --draft-id")
        update_draft(args.draft_id, status="rejeitado")
        write_dashboard_snapshot()
        print(f"Rascunho {args.draft_id} marcado como rejeitado.")
        return

    config: AppConfig = load_config()
    fb_client = FacebookAdsClient(config.facebook.access_token, config.facebook.ad_account_id,
                                   config.facebook.api_version)

    if args.draft_id:
        draft = get_draft(args.draft_id)
        drafts = [draft] if draft and draft.get("status") == "rascunho" else []
        if not drafts:
            print(f"Rascunho {args.draft_id} não encontrado ou não está com status 'rascunho'.")
            return
    else:
        drafts = read_drafts(status="rascunho")

    if not drafts:
        print("Nenhum rascunho pendente (status 'rascunho') encontrado em logs/ad_drafts.json.")
        return

    print(f"{len(drafts)} rascunho(s) para processar.")
    if not args.confirm:
        print("Modo de revisão (sem --confirm) — nada será criado no Facebook.\n")

    for draft in drafts:
        prop = draft["property"]
        print(f"  [{draft['draft_id'][:8]}] {prop['title']}")
        if not args.confirm:
            continue
        try:
            result = _create_one(fb_client, draft, config=config)
        except Exception as exc:
            print(f"      ERRO: {exc}")
            update_draft(draft["draft_id"], status="erro", error_message=str(exc))
            log_action(
                action_type="create_campaign_from_draft", target_type="campaign",
                target_id=draft["draft_id"], target_name=prop["title"],
                before_value=None, after_value=None,
                reasoning=f"criação a partir de rascunho de catálogo: {prop['title']}",
                confidence=prop.get("confidence", 0.5), status="rejected", dry_run=False,
                rejection_reason=str(exc),
            )
            continue

        update_draft(draft["draft_id"], status="criado", meta_campaign_id=result["campaign_id"],
                     meta_adset_id=result["adset_id"], meta_ad_id=result["ad_id"])
        log_action(
            action_type="create_campaign_from_draft", target_type="campaign",
            target_id=result["campaign_id"], target_name=prop["title"],
            before_value=None, after_value=str(result["daily_budget_cents"]),
            reasoning=(f"campanha criada a partir do catálogo — interesses aplicados: "
                       f"{', '.join(result['interests_applied']) or 'nenhum'}"
                       f"{'; público semelhante aplicado' if result['lookalike_applied'] else ''}"
                       f"{'; imagem do criativo gerada automaticamente' if result['image_generated'] else ''}"),
            confidence=prop.get("confidence", 0.5), status="applied", dry_run=False,
        )
        print(f"      Criado: campanha {result['campaign_id']}, "
              f"orçamento R$ {result['daily_budget_cents'] / 100:.2f}/dia"
              f"{', com público semelhante' if result['lookalike_applied'] else ''}"
              f"{', com imagem gerada automaticamente' if result['image_generated'] else ''}")
        if result["warning"]:
            print(f"      Aviso: {result['warning']}")

    if args.confirm:
        write_dashboard_snapshot()
    else:
        print("\nRode de novo com --confirm para criar de verdade no Facebook Ads.")


if __name__ == "__main__":
    main()
