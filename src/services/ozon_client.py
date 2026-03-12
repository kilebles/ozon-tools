from pathlib import Path

from loguru import logger
from playwright.async_api import Page

from core.exceptions import OzonApiError
from services.browser import ozon_page
from services.ozon_api import navigate_to_search_validator, create_search_task, poll_search_results


class OzonSearchClient:
    def __init__(self, company_id: str, cookies_path: Path, headless: bool = False, proxy_path: Path | None = None) -> None:
        self._company_id = company_id
        self._cookies_path = cookies_path
        self._headless = headless
        self._proxy_path = proxy_path
        self._page: Page | None = None

    async def __aenter__(self) -> "OzonSearchClient":
        logger.info("Starting OzonSearchClient session")
        self._ctx_manager = ozon_page(self._cookies_path, self._headless, self._proxy_path)
        self._page = await self._ctx_manager.__aenter__()
        await navigate_to_search_validator(self._page)
        logger.info("Session ready")
        return self

    async def __aexit__(self, *args) -> None:
        logger.info("Closing OzonSearchClient session")
        await self._ctx_manager.__aexit__(*args)
        self._page = None

    async def get_search_positions(self, query: str, item_ids: list[str]) -> dict[str, int]:
        logger.info(f"Fetching positions | query={query!r} items={len(item_ids)}")
        try:
            task_id = await create_search_task(self._page, self._company_id, query, item_ids)
            results = await poll_search_results(self._page, self._company_id, task_id)
            logger.info(f"Got {len(results)} results for query={query!r}")
            return results
        except OzonApiError as e:
            logger.error(f"API error for query={query!r}: {e} | raw={e.raw[:200] if e.raw else ''}")
            raise
