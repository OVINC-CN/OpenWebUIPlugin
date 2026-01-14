"""
title: Claude Code Execution
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Claude Code Execution
version: 0.0.1
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
            "Nvbi1jb2RlIiBzdHJva2Utd2lkdGg9IjQiIHN0cm9rZS1saW5lY2FwPSJidXR0IiBzdHJva2UtbGluZWpvaW49Im1pdGVyIiBmaWx0ZX"
            "I9ImNvZGUiIHN0eWxlPSJmb250LXNpemU6IDMycHg7Ij48cGF0aCBkPSJNMTYuNzM0IDEyLjY4NiA1LjQyIDI0bDExLjMxNCAxMS4zMT"
            "RtMTQuNTIxLTIyLjYyOEw0Mi41NyAyNCAzMS4yNTUgMzUuMzE0TTI3LjIgNi4yOGwtNi4yNTEgMzUuNDUzIj48L3BhdGg+PC9zdmc+"
        )

    def inlet(self, body: dict) -> dict:
        if body.get("tools"):
            body["tools"].append({"type": "code_execution_20250825", "name": "code_execution"})
        else:
            body["tools"] = [{"type": "code_execution_20250825", "name": "code_execution"}]
        return body
