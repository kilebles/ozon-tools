import asyncio
import json

from loguru import logger
from playwright.async_api import Page

from core.exceptions import RateLimitError, UnexpectedResponseError

_BASE_URL = "https://seller.ozon.ru"
_LOCATION = {
    "area_id": "0",
    "latitude": 55.728138,
    "longitude": 37.425808,
    "title": "Москва",
    "uuid": "0c5b2444-70a0-4932-980c-b4dc0d3f02b5",
}
_LOCATION_UID = "0c5b2444-70a0-4932-980c-b4dc0d3f02b5"
_RATE_LIMIT_RETRY_DELAYS = [10, 20, 30, 40, 50]

_JS_FETCH = """([url, headers, body]) =>
    fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', ...headers},
        body: JSON.stringify(body),
    }).then(r => r.text())
"""


def _headers(company_id: str) -> dict:
    return {
        "x-o3-app-name": "seller-ui",
        "x-o3-language": "ru",
        "x-o3-company-id": int(company_id),
        "x-o3-page-type": "analytics-search",
    }


async def navigate_to_search_validator(page: Page) -> None:
    url = f"{_BASE_URL}/app/analytics-search/search-results/validator"
    logger.debug(f"Navigating to {url}")
    asyncio.ensure_future(page.goto(url, wait_until="commit"))
    await page.wait_for_url("**/app/**", timeout=30_000)
    logger.debug(f"Page ready: {page.url}")


async def create_search_task(page: Page, company_id: str, query: str, item_ids: list[str]) -> str:
    payload = {
        "company_id": company_id,
        "query": query,
        "item_ids": item_ids,
        "is_legal": False,
        "is_pharmacy": False,
        "location_uid": _LOCATION_UID,
        "coordinates": _LOCATION,
    }
    logger.debug(f"Creating search task | query={query!r} items={item_ids}")

    for attempt, delay in enumerate([0] + _RATE_LIMIT_RETRY_DELAYS):
        if delay:
            logger.warning(f"Rate limit hit, retrying in {delay}s (attempt {attempt}/{len(_RATE_LIMIT_RETRY_DELAYS)})")
            await asyncio.sleep(delay)

        raw = await page.evaluate(
            _JS_FETCH,
            [f"{_BASE_URL}/api/validator-service/v2/get_search_stats", _headers(company_id), payload],
        )
        logger.debug(f"v2 raw response: {raw}")

        if not raw.strip() or raw.lstrip().startswith("<"):
            logger.warning("Got HTML response (antibot), waiting for redirect back to /app/")
            await page.wait_for_url("**/app/**", timeout=60_000)
            continue

        data = json.loads(raw)

        if data.get("message") == "too many requests":
            if attempt == len(_RATE_LIMIT_RETRY_DELAYS):
                raise RateLimitError("Too many requests — all retries exhausted", raw=raw)
            continue

        if "id" not in data:
            raise UnexpectedResponseError(f"Missing 'id' in response: {raw[:300]}", raw=raw)

        task_id = data["id"]
        logger.debug(f"Task created: {task_id}")
        return task_id

    raise RateLimitError("Too many requests — all retries exhausted")


async def poll_search_results(page: Page, company_id: str, task_id: str) -> dict[str, int]:
    logger.debug(f"Polling task {task_id}")
    poll_count = 0

    while True:
        raw = await page.evaluate(
            _JS_FETCH,
            [
                f"{_BASE_URL}/api/validator-service/v1/get_search_stats_by_id",
                _headers(company_id),
                {"id": task_id, "company_id": company_id},
            ],
        )
        poll_count += 1
        logger.debug(f"Poll #{poll_count} response: {raw}")

        if not raw.strip() or raw.lstrip().startswith("<"):
            raise UnexpectedResponseError("Got HTML response during polling (session lost)", raw=raw)

        data = json.loads(raw)

        if "error" in data:
            raise UnexpectedResponseError(f"Poll error: {data['error']}", raw=raw)

        status = data.get("status")
        if status == "COMPLETED":
            items = data["resp"]["items"]
            logger.debug(f"Task {task_id} completed, {len(items)} items returned")
            return {item["itemId"]: int(item["position"]) for item in items}

        logger.debug(f"Task {task_id} status={status}, waiting...")
        await asyncio.sleep(1.5)
