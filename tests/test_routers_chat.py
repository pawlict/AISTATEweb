"""Tests for webapp.routers.chat module."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from webapp.routers.chat import _parse_messages


def test_parse_messages_with_system_prompt():
    """Should prepend system message."""
    msgs = _parse_messages(
        [{"role": "user", "content": "Hello"}],
        system_prompt="You are helpful.",
    )
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": "You are helpful."}
    assert msgs[1] == {"role": "user", "content": "Hello"}


def test_parse_messages_without_system_prompt():
    """Should not prepend system message when empty."""
    msgs = _parse_messages([{"role": "user", "content": "Hi"}], system_prompt="")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_parse_messages_filters_invalid():
    """Should skip messages without role/content."""
    msgs = _parse_messages([
        {"role": "user", "content": "OK"},
        {"bad": "data"},
        "not a dict",
        {"role": "assistant", "content": "Sure"},
    ])
    assert len(msgs) == 2
    assert msgs[0]["content"] == "OK"
    assert msgs[1]["content"] == "Sure"


def test_parse_messages_empty():
    """Empty input should return empty list."""
    msgs = _parse_messages([], system_prompt="")
    assert msgs == []


def test_parse_messages_coerces_to_string():
    """Role and content should be coerced to strings."""
    msgs = _parse_messages([{"role": 123, "content": 456}])
    assert msgs[0]["role"] == "123"
    assert msgs[0]["content"] == "456"
