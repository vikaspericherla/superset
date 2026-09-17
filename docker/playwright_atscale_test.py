# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Headless Playwright smoke test for the AtScale dataset picker."""

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://localhost:8088/login/", wait_until="domcontentloaded")
    if page.locator("input[name='username']").count():
        page.locator("input[name='username']").fill("admin")
        page.locator("input[name='password']").fill("admin")
        page.get_by_role("button", name="Sign In").click()
    page.goto("http://localhost:8088/dataset/add/", wait_until="networkidle")
    login = page.request.post(
        "http://localhost:8088/api/v1/security/login",
        data={"username": "admin", "password": "admin", "provider": "db"},
    )
    assert login.ok, login.text()
    token = login.json()["access_token"]
    response = page.request.get(
        "http://localhost:8088/api/v1/database/2/tables/"
        "?q=(schema_name%3A'Sales%20and%20Order%20Book'%2Cforce%3A!t)",
        headers={"Authorization": f"Bearer {token}"},
    )
    result = response.json()
    assert response.ok, result
    assert result["result"] == [
        {"extra": None, "type": "table", "value": "Sales and Order Book"}
    ], result
    metadata = page.request.get(
        "http://localhost:8088/api/v1/database/2/table_metadata/"
        "?name=Sales%20and%20Order%20Book&schema=Sales%20and%20Order%20Book",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metadata.ok, metadata.text()
    assert len(metadata.json()["columns"]) == 622
    datasets = page.request.get(
        "http://localhost:8088/api/v1/dataset/?q=(page:0,page_size:100)",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert datasets.ok, datasets.text()
    names = {item["table_name"] for item in datasets.json()["result"]}
    assert {"Finance P&L", "Sales and Order Book", "Shopify Orders"} <= names, names
    created = page.request.post(
        "http://localhost:8088/extensions/pentland/atscale-mcp-adapter/dataset",
        data={"model": "Shopify Orders"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.ok, created.text()
    assert "/explore/" in created.json()["result"]["explore_url"]
    print("PLAYWRIGHT_TABLE_PICKER=PASS")
    print("PLAYWRIGHT_MODEL_METADATA=PASS")
    print("PLAYWRIGHT_DATASET_LIST=PASS")
    print("PLAYWRIGHT_CREATE_AND_EXPLORE=PASS")
    browser.close()
