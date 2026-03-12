import json
from contextlib import asynccontextmanager
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright
from playwright_stealth import Stealth

_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-site-isolation-trials",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--disable-background-networking",
    "--disable-breakpad",
    "--no-first-run",
    "--no-default-browser-check",
    "--password-store=basic",
    "--use-mock-keychain",
    "--enable-webgl",
    "--enable-webgl2",
    "--ignore-gpu-blocklist",
    "--enable-gpu-rasterization",
    "--disable-gpu",
    "--window-size=1920,1080",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-hang-monitor",
    "--disable-popup-blocking",
    "--font-render-hinting=none",
    "--mute-audio",
    "--disable-sync",
]


def _load_cookies(cookies_path: Path) -> list[dict]:
    logger.debug(f"Loading cookies from {cookies_path}")
    raw = json.loads(cookies_path.read_text())
    result = []
    for c in raw:
        cookie: dict = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": True,
            "httpOnly": c.get("httpOnly", False),
        }
        ss = c.get("sameSite", "unspecified")
        cookie["sameSite"] = (
            "Lax" if ss == "lax"
            else "Strict" if ss == "strict"
            else "None"
        )
        if c.get("expirationDate"):
            cookie["expires"] = int(c["expirationDate"])
        result.append(cookie)
    logger.debug(f"Loaded {len(result)} cookies")
    return result


def _parse_proxy(proxy_path: Path) -> dict | None:
    if not proxy_path.exists():
        return None
    line = proxy_path.read_text().strip()
    if not line:
        return None
    parts = line.split(":")
    if len(parts) != 4:
        logger.warning(f"Invalid proxy format in {proxy_path}, expected host:port:user:password")
        return None
    host, port, user, password = parts
    return {
        "server": f"http://{host}:{port}",
        "username": user,
        "password": password,
    }


async def _launch_context(p: Playwright, headless: bool, proxy_path: Path | None = None) -> BrowserContext:
    user_data_dir = Path("browser_data")
    user_data_dir.mkdir(exist_ok=True)
    proxy = _parse_proxy(proxy_path) if proxy_path else None
    logger.debug(f"Launching Chromium | headless={headless} user_data_dir={user_data_dir} proxy={'yes' if proxy else 'no'}")
    ctx = await p.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=headless,
        viewport={"width": 1920, "height": 1080},
        locale="ru-RU",
        color_scheme="light",
        timezone_id="Europe/Moscow",
        geolocation={"latitude": 55.7558, "longitude": 37.6173},
        permissions=["geolocation"],
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        args=_CHROMIUM_ARGS,
        proxy=proxy,
    )
    logger.debug("Browser context launched")
    return ctx


async def _new_page(ctx: BrowserContext) -> Page:
    page = await ctx.new_page()
    page.set_default_timeout(30_000)
    stealth = Stealth(
        navigator_languages_override=("ru-RU", "ru"),
        navigator_platform_override="Win32",
    )
    await stealth.apply_stealth_async(page)
    await page.add_init_script("""
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        delete window.__playwright;
        delete window.__puppeteer_evaluation_script__;
    """)
    logger.debug("New stealth page created")
    return page


@asynccontextmanager
async def ozon_page(cookies_path: Path, headless: bool = True, proxy_path: Path | None = None):
    """Context manager that yields an authenticated Ozon seller page."""
    async with async_playwright() as p:
        ctx = await _launch_context(p, headless, proxy_path)
        await ctx.add_cookies(_load_cookies(cookies_path))
        page = await _new_page(ctx)
        logger.debug("Browser ready with cookies applied")
        try:
            yield page
        finally:
            logger.debug("Closing browser context")
            await ctx.close()
