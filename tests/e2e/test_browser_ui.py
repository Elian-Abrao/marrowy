from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.e2e
def test_browser_ui_flow(tmp_path):
    db_path = tmp_path / "browser-e2e.db"
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": "src",
            "MARROWY_MODEL_PROVIDER": "fake",
            "MARROWY_DATABASE_URL": f"sqlite+pysqlite:///{db_path}",
        }
    )

    subprocess.run([".venv/bin/marrowy", "init-db"], cwd=Path.cwd(), check=True, env=env)
    subprocess.run([".venv/bin/marrowy", "seed"], cwd=Path.cwd(), check=True, env=env)

    server = subprocess.Popen(
        [".venv/bin/python", "-m", "uvicorn", "marrowy.api.app:app", "--host", "127.0.0.1", "--port", "8011"],
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            with httpx.Client(timeout=1.0) as client:
                try:
                    response = client.get("http://127.0.0.1:8011/healthz")
                except httpx.HTTPError:
                    time.sleep(0.25)
                    continue
                if response.status_code == 200:
                    break
        else:
            raise AssertionError("server did not start in time")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto("http://127.0.0.1:8011/")
            page.fill("#conversation-title", "Browser E2E Conversation")
            page.select_option("#conversation-project-id", label="Marrowy Demo")
            page.click("text=Start Conversation")
            page.wait_for_url("**/conversations/*")
            page.fill("#chat-input", "Create a todo MVP pipeline, add QA, and prepare deploy validation.")
            page.click("text=Send")
            page.wait_for_timeout(1500)
            body = page.locator("body").inner_text()
            assert "Agent Principal" in body
            assert "Task Board" in body
            assert "Agent QA" in body
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
