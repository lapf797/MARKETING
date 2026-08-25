"""Testes da ligação entre o motor de composição e o resto do sistema
(src/creative/pipeline.py): baixar a foto do rascunho, montar o conteúdo/marca a partir
do AppConfig e devolver bytes JPEG prontos para upload — sem tocar em nenhuma API real
(requests.get é mockado)."""
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from src.config import AdsConfig, AIConfig, AppConfig, CreativeConfig, FacebookConfig, PowerBIConfig, SafetyConfig
from src.creative.pipeline import _format_auction_date, brand_config_from_app_config, generate_ad_image_bytes


def make_config(**creative_overrides) -> AppConfig:
    creative_defaults = dict(
        auto_generate_image=True, brand_name="MILAN LEILÕES", logo_path=None,
        color_dark="#0F1F3D", color_accent="#D6AF5A", color_secondary="#03A3BE",
    )
    creative_defaults.update(creative_overrides)
    return AppConfig(
        safety=SafetyConfig(
            dry_run=True, max_budget_change_pct_per_day=20, min_budget_change_pct_to_act=5,
            min_spend_before_action_cents=5000, cooldown_hours_between_changes=20,
            max_actions_per_run=15, max_pauses_per_run=5, account_daily_budget_cap_cents=500000,
            max_cpa_cents=15000, min_conversions_for_reliable_cpa=3, max_frequency=4.0,
            require_ai_confidence=0.6, currency_minor_unit_factor=100,
            min_impressions_before_placement_action=500,
        ),
        facebook=FacebookConfig(api_version="v23.0", insights_lookback_days=14, conversion_action_type="lead",
                                 access_token="dummy", ad_account_id="act_123", app_id=None, app_secret=None),
        ai=AIConfig(model="claude-opus-5", optimizer_effort="high", audience_advisor_effort="high",
                    catalog_extractor_effort="high", api_key="dummy"),
        powerbi=PowerBIConfig(push_enabled=False, table_campaign_metrics="x", table_actions="y",
                               table_audience="z", tenant_id=None, client_id=None, client_secret=None,
                               workspace_id=None, dataset_id=None),
        ads=AdsConfig(budget_tiers_cents=[], budget_above_max_tier_cents=450000, installment_count=48,
                      highlight_installments=True, highlight_below_market_price=True,
                      default_campaign_status="ACTIVE", use_lookalike_audience=True,
                      lookalike_ratio=0.05, lookalike_country="BR"),
        creative=CreativeConfig(**creative_defaults),
    )


def test_format_auction_date_converts_iso_to_brazilian_format():
    assert _format_auction_date("2026-12-15") == "15/12/2026"


def test_format_auction_date_returns_none_for_missing_or_invalid():
    assert _format_auction_date(None) is None
    assert _format_auction_date("") is None
    assert _format_auction_date("data-invalida") is None


def test_brand_config_from_app_config_maps_all_fields():
    config = make_config(logo_path="assets/brand/logo.png")
    brand = brand_config_from_app_config(config)
    assert brand.name == "MILAN LEILÕES"
    assert brand.logo_path == "assets/brand/logo.png"
    assert brand.color_dark == "#0F1F3D"
    assert brand.color_accent == "#D6AF5A"
    assert brand.color_secondary == "#03A3BE"


def _fake_photo_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1600, 1200), (120, 160, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


@patch("src.creative.pipeline.requests.get")
def test_generate_ad_image_bytes_downloads_composes_and_returns_valid_jpeg(mock_get):
    mock_response = MagicMock()
    mock_response.content = _fake_photo_bytes()
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    config = make_config()
    prop = {"headline": "Casa 3 quartos com piscina", "city": "Porto Alegre", "state": "RS"}
    result = generate_ad_image_bytes(
        picture_url="https://exemplo.com/foto.jpg", prop=prop, pause_date="2026-12-15", config=config,
    )

    mock_get.assert_called_once_with("https://exemplo.com/foto.jpg", timeout=30)
    output_image = Image.open(BytesIO(result))
    assert output_image.size == (1080, 1080)
    assert output_image.format == "JPEG"


@patch("src.creative.pipeline.requests.get")
def test_generate_ad_image_bytes_builds_location_from_city_and_state(mock_get):
    mock_response = MagicMock()
    mock_response.content = _fake_photo_bytes()
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    config = make_config()
    prop = {"headline": "Terreno", "city": "", "state": None}
    # não deve levantar exceção mesmo sem city/state preenchidos
    result = generate_ad_image_bytes(
        picture_url="https://exemplo.com/foto.jpg", prop=prop, pause_date=None, config=config,
    )
    assert Image.open(BytesIO(result)).size == (1080, 1080)


@patch("src.creative.pipeline.requests.get")
def test_generate_ad_image_bytes_propagates_download_failure(mock_get):
    mock_get.side_effect = ConnectionError("timeout")
    config = make_config()
    prop = {"headline": "Casa", "city": "Porto Alegre", "state": "RS"}
    try:
        generate_ad_image_bytes(picture_url="https://exemplo.com/foto.jpg", prop=prop,
                                 pause_date=None, config=config)
        assert False, "deveria ter levantado exceção"
    except ConnectionError:
        pass
