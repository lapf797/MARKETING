"""Testes do upload de imagem de criativo (FacebookAdsClient.upload_ad_image) e da
precedência image_hash > picture_url em create_ad_creative — sem chamada de rede real,
a sessão HTTP interna é mockada."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.facebook_ads.client import FacebookAdsClient, FacebookAdsError


def make_client() -> FacebookAdsClient:
    return FacebookAdsClient(access_token="token123", ad_account_id="123456", api_version="v23.0")


def _mock_response(json_payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = json.dumps(json_payload).encode()
    response.json.return_value = json_payload
    return response


def test_upload_ad_image_posts_multipart_and_returns_hash():
    client = make_client()
    client._session.post = MagicMock(return_value=_mock_response(
        {"images": {"creative.jpg": {"hash": "abc123hash", "url": "https://fb.example/img.jpg"}}}
    ))

    result = client.upload_ad_image(b"fake-image-bytes", filename="creative.jpg")

    assert result == {"hash": "abc123hash", "url": "https://fb.example/img.jpg"}
    call = client._session.post.call_args
    assert call.args[0] == f"{client.base_url}/act_123456/adimages"
    assert "files" in call.kwargs
    assert call.kwargs["files"]["creative.jpg"][0] == "creative.jpg"
    assert call.kwargs["files"]["creative.jpg"][1] == b"fake-image-bytes"
    assert call.kwargs["data"]["access_token"] == "token123"


def test_upload_ad_image_raises_when_response_has_no_hash():
    client = make_client()
    client._session.post = MagicMock(return_value=_mock_response({"images": {}}))
    try:
        client.upload_ad_image(b"bytes", filename="creative.jpg")
        assert False, "deveria ter levantado FacebookAdsError"
    except FacebookAdsError:
        pass


def test_upload_ad_image_raises_facebook_ads_error_on_http_error():
    client = make_client()
    client._session.post = MagicMock(return_value=_mock_response(
        {"error": {"message": "token inválido"}}, status_code=401,
    ))
    try:
        client.upload_ad_image(b"bytes")
        assert False, "deveria ter levantado FacebookAdsError"
    except FacebookAdsError as exc:
        assert "token inválido" in str(exc)


def test_create_ad_creative_prefers_image_hash_over_picture_url():
    client = make_client()
    client._session.post = MagicMock(return_value=_mock_response({"id": "creative_1"}))

    client.create_ad_creative(
        name="Anúncio", page_id="page1", link="https://x.com", message="msg",
        headline="Título", description="desc",
        picture_url="https://exemplo.com/foto_crua.jpg", image_hash="abc123hash",
    )

    call = client._session.post.call_args
    body = call.kwargs["data"]
    spec = json.loads(body["object_story_spec"])
    assert spec["link_data"]["image_hash"] == "abc123hash"
    assert "picture" not in spec["link_data"]


def test_create_ad_creative_falls_back_to_picture_url_without_image_hash():
    client = make_client()
    client._session.post = MagicMock(return_value=_mock_response({"id": "creative_1"}))

    client.create_ad_creative(
        name="Anúncio", page_id="page1", link="https://x.com", message="msg",
        headline="Título", description="desc",
        picture_url="https://exemplo.com/foto_crua.jpg",
    )

    call = client._session.post.call_args
    body = call.kwargs["data"]
    spec = json.loads(body["object_story_spec"])
    assert spec["link_data"]["picture"] == "https://exemplo.com/foto_crua.jpg"
    assert "image_hash" not in spec["link_data"]
