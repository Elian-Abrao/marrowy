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
            page.click(".submit-room")
            page.wait_for_url("**/conversations/*")
            conversation_url = page.url
            page.fill("#chat-input", "Create a todo MVP pipeline, add QA, and prepare deploy validation.")
            page.click(".send-btn")
            page.wait_for_timeout(1500)
            assert page.locator("body").inner_text().find("I received your message") == -1
            assert page.locator("details.thinking-panel").count() >= 1
            page.click("#btn-toggle-tasks")
            page.wait_for_timeout(250)
            body = page.locator("body").inner_text()
            assert "Agent Principal" in body
            assert "Task Pipeline" in body
            assert "Agent QA" in body
            page.click("#btn-toggle-agents")
            page.wait_for_timeout(250)
            assert page.locator("#new-agent-effort").count() == 1
            assert page.locator(".agent-effort-select").count() >= 1
            body = page.locator("body").inner_text()
            assert "BACKGROUND ACTIVITY (TOOLCALLS)" in body
            assert "Listening for jobs..." in body
            page.once("dialog", lambda dialog: dialog.accept())
            page.click("text=Delete Room")
            page.wait_for_url("http://127.0.0.1:8011/")
            home_body = page.locator("body").inner_text()
            assert "Welcome back." in home_body
            page.goto(conversation_url)
            assert page.locator("body").inner_text().find("Not Found") != -1
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
