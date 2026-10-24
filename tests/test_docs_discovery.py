"""Tests for the discovery documents served to agents.

``/llms.txt`` is generated from the live configuration (so it always names the
aliases and limits of *this* deployment) and must never leak the master key;
``/swagger-ui`` and ``/openapi.json`` make the same surface explorable.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from litegm import docs_discovery


def _state(config):
    return SimpleNamespace(config=config)


@pytest.fixture
def llms(config, master_key):
    return docs_discovery.llms_txt(_state(config), base_url="http://127.0.0.1:8080")


def test_llms_txt_follows_llmstxt_shape(llms):
    # llmstxt.org: H1 title, a blockquote summary, then "## Name" link lists.
    lines = llms.splitlines()
    assert lines[0].startswith("# ")
    assert any(line.startswith("> ") for line in lines[:6])
    assert any(line.startswith("## ") for line in lines)


def test_llms_txt_points_at_agent_entry_points(llms):
    for url in (
        "http://127.0.0.1:8080/swagger-ui",
        "http://127.0.0.1:8080/openapi.json",
        "http://127.0.0.1:8080/v1/models",
        "http://127.0.0.1:8080/v1/health",
        "http://127.0.0.1:8080/llms.txt",
    ):
        assert url in llms, url


def test_llms_txt_lists_configured_aliases_only(config, llms):
    aliases = {m.alias for t in config.tasks.values() for m in t.models}
    for alias in aliases:
        assert alias in llms, alias
    # Families are callable names too.
    for family in config.routing.video_families:
        assert family.family in llms


def test_llms_txt_does_not_leak_master_key(llms, master_key):
    assert master_key not in llms
    assert "master_key" in llms or "MASTER_KEY" in llms


def test_llms_txt_mentions_protocols_and_errors(llms):
    for needle in (
        "/v1/images/generations",
        "/v1/images/edits",
        "/v1/videos",
        "/v1/audio/generations",
        "/v1/tasks/{id}",
        "X-Litegm-Task-Id",
        "invalid_api_key",
        "Authorization: Bearer",
        "from openai import OpenAI",
    ):
        assert needle in llms, needle


def test_llms_txt_defaults_to_configured_base_url(config):
    text = docs_discovery.llms_txt(_state(config))
    assert config.server.public_base_url.rstrip("/") in text


def test_llms_txt_reflects_constraints(config, llms):
    # Video duration limits come from configuration, not from a constant.
    for task in config.tasks.values():
        for m in task.models:
            c = m.constraints
            if c.duration_max is not None:
                assert f"{c.duration_max:g}" in llms or str(int(c.duration_max)) in llms


def test_swagger_html_references_openapi_and_llms():
    html = docs_discovery.swagger_html(openapi_url="/openapi.json", llms_url="/llms.txt")
    assert "<!DOCTYPE html>" in html or "<!doctype html>" in html
    assert "swagger-ui" in html
    assert "/openapi.json" in html
    assert "/llms.txt" in html


def test_openapi_extras_keeps_paths_and_adds_security(config):
    from fastapi import FastAPI

    from litegm import api as api_mod

    app = FastAPI(title="litegm")
    app.include_router(api_mod.router)
    base = app.openapi()
    doc = docs_discovery.openapi_extras(app, base_url="http://127.0.0.1:8080")

    assert set(base["paths"]).issubset(set(doc["paths"]))
    assert doc["servers"][0]["url"].startswith("http://127.0.0.1:8080")
    schemes = doc["components"]["securitySchemes"]
    assert any(v.get("scheme") == "bearer" for v in schemes.values())
    assert "/llms.txt" in doc["info"]["description"]
    json.dumps(doc)  # must be JSON serialisable


def test_openapi_extras_documents_key_endpoints(config):
    from fastapi import FastAPI

    from litegm import api as api_mod, audio as audio_mod, video as video_mod

    app = FastAPI(title="litegm")
    for router in (api_mod.router, video_mod.router, audio_mod.router):
        app.include_router(router)
    doc = docs_discovery.openapi_extras(app)

    for path in (
        "/v1/images/generations",
        "/v1/images",
        "/v1/images/edits",
        "/v1/videos",
        "/v1/audio/generations",
        "/v1/models",
        "/v1/tasks/{task_id}",
    ):
        assert path in doc["paths"], path
        for op in doc["paths"][path].values():
            if isinstance(op, dict) and "responses" in op:
                assert op.get("summary") or op.get("description"), (path, op)
