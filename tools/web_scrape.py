"""
title: Jina AI Web Scrape
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Using Jina AI for Web Scrape
requirements: httpx
version: 0.0.1
licence: MIT
"""

import traceback
from urllib.parse import quote

from httpx import AsyncClient
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        scrape_proxy: str = Field(default="", description="proxy for scrape")
        timeout: int = Field(default=60, description="timeout waiting for scraping result")

    def __init__(self):
        self.valves = self.Valves()

    async def web_scrape(self, url: str, __event_emitter__: callable) -> str:
        """
        Scrape and process a web page
        :param url: The URL to be scraped.
        :return: The scraped and processed content without the Links/Buttons section, or an error message.
        """

        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": f"scraping {url}", "done": False, "hidden": False},
            }
        )

        client = AsyncClient(
            proxy=self.valves.scrape_proxy or None,
            headers={"X-No-Cache": "true", "X-With-Images-Summary": "true", "X-With-Links-Summary": "true"},
            timeout=self.valves.timeout,
        )
        try:
            response = await client.get(url=f"https://r.jina.ai/{quote(url)}")
            response.raise_for_status()
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": f"scrap success ({url})", "done": True, "hidden": False},
                }
            )
            return response.text
        except Exception as err:
            message = f"failed to scrap {err}"
            print(f"{message}\n{traceback.format_exc()}")
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": message, "done": True, "hidden": True},
                }
            )
            return message
        finally:
            await client.aclose()
