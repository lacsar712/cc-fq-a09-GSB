"""Unit tests for job tag normalization (no DB required)."""

import pytest
from fastapi import HTTPException

from app.api import MAX_TAGS_PER_JOB, normalize_tags


def test_normalize_strip_and_dedupe_keeps_order():
    assert normalize_tags([" night-qc ", "night-qc", "batch.1", "batch_1"]) == [
        "night-qc",
        "batch.1",
        "batch_1",
    ]


def test_normalize_skips_empty():
    assert normalize_tags(["", "  ", "night-qc"]) == ["night-qc"]


def test_normalize_empty_list_clears_tags():
    assert normalize_tags([]) == []


@pytest.mark.parametrize(
    "bad",
    [
        "-night-qc",  # 必须字母/数字开头
        ".dot",
        "has space",
        "中文标记",
        "x" * 33,  # 超长
        "a/b",
    ],
)
def test_normalize_rejects_illegal_names(bad):
    with pytest.raises(HTTPException) as exc:
        normalize_tags([bad])
    assert exc.value.status_code == 400


def test_normalize_rejects_too_many_tags():
    with pytest.raises(HTTPException) as exc:
        normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_JOB + 1)])
    assert exc.value.status_code == 400


def test_normalize_accepts_max_tags():
    names = [f"t{i}" for i in range(MAX_TAGS_PER_JOB)]
    assert normalize_tags(names) == names
