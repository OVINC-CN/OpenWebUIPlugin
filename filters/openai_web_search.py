"""
title: OpenAI Web Search
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: OpenAI Web Search
version: 0.0.2
licence: MIT
"""

from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="filter priority")

    def __init__(self):
        self.valves = self.Valves()
        self.toggle = True
        self.icon = (
            "data:image/svg+xml;base64,PHN2ZyBkYXRhLXYtMmJjNjQ2MGU9IiIgdmlld0JveD0iMCAwIDQ4IDQ4IiBmaWxsPSJub25lIiB4bW"
            "xucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHN0cm9rZT0iY3VycmVudENvbG9yIiBjbGFzcz0iYXJjby1pY29uIGFyY28taW"
            "Nvbi1zZWFyY2giIHN0cm9rZS13aWR0aD0iNCIgc3Ryb2tlLWxpbmVjYXA9ImJ1dHQiIHN0cm9rZS1saW5lam9pbj0ibWl0ZXIiIGZpbH"
            "Rlcj0ic2VhciIgc3R5bGU9ImZvbnQtc2l6ZTogMzJweDsiPjxwYXRoIGQ9Ik0zMy4wNzIgMzMuMDcxYzYuMjQ4LTYuMjQ4IDYuMjQ4LT"
            "E2LjM3OSAwLTIyLjYyNy02LjI0OS02LjI0OS0xNi4zOC02LjI0OS0yMi42MjggMC02LjI0OCA2LjI0OC02LjI0OCAxNi4zNzkgMCAyMi"
            "42MjcgNi4yNDggNi4yNDggMTYuMzggNi4yNDggMjIuNjI4IDBabTAgMCA4LjQ4NSA4LjQ4NSI+PC9wYXRoPjwvc3ZnPg=="
        )

    def inlet(self, body: dict) -> dict:
        if body.get("tools"):
            body["tools"].append({"type": "web_search"})
        else:
            body["tools"] = [{"type": "web_search"}]
        return body
