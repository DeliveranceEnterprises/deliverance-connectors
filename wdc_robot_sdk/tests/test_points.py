# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

import os

import pytest

from wdc_points import PointsFileError, load_points, normalize_point_name, parse_points, resolve_goto

EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "points.example.yaml")


def test_example_file_loads():
    points = load_points(EXAMPLE)
    assert set(points) == {"A", "B", "HOME"}
    assert points["B"] == (0.0, 1.0, 1.5708)


def test_example_points_have_matching_actions():
    import yaml

    actions = os.path.join(os.path.dirname(EXAMPLE), "..", "cac", "actions.yaml")
    with open(actions) as f:
        messages = {
            arg["value"]
            for doc in yaml.safe_load_all(f)
            for arg in doc["spec"]["arguments"]
            if arg["name"] == "message"
        }
    gotos = {m[len("GOTO_"):] for m in messages if m.startswith("GOTO_")}
    assert gotos == set(load_points(EXAMPLE))


def test_names_are_normalized_and_yaw_defaults_to_zero():
    points = parse_points({"points": {"dock_2": {"x": 1, "y": -2}}})
    assert points == {"DOCK_2": (1.0, -2.0, 0.0)}


def test_empty_document_has_no_points():
    assert parse_points(None) == {}
    assert parse_points({"points": None}) == {}


@pytest.mark.parametrize(
    "document",
    [
        ["A"],
        {"points": ["A"]},
        {"points": {"A": {"x": 1}}},
        {"points": {"A": {"x": "1", "y": 0}}},
        {"points": {"A": {"x": True, "y": 0}}},
        {"points": {"A": {"x": float("nan"), "y": 0}}},
        {"points": {"bad name": {"x": 0, "y": 0}}},
        {"points": {"a": {"x": 0, "y": 0}, "A": {"x": 1, "y": 1}}},
    ],
)
def test_invalid_documents_are_rejected(document):
    with pytest.raises(PointsFileError):
        parse_points(document)


def test_missing_and_malformed_files(tmp_path):
    with pytest.raises(PointsFileError):
        load_points(str(tmp_path / "missing.yaml"))
    bad = tmp_path / "bad.yaml"
    bad.write_text("points: [unclosed")
    with pytest.raises(PointsFileError):
        load_points(str(bad))


@pytest.mark.parametrize(
    "name, expected",
    [("a", "A"), (" Home ", "HOME"), ("P_1", "P_1"), ("", None), ("A B", None),
     ("A;rm", None), ("X" * 33, None), (None, None)],
)
def test_normalize_point_name(name, expected):
    assert normalize_point_name(name) == expected


def test_resolve_goto():
    points = {"A": (1.0, 2.0, 0.0)}
    assert resolve_goto("GOTO_A", points) == ("A", (1.0, 2.0, 0.0))
    assert resolve_goto("GOTO_C", points) == ("C", None)
    assert resolve_goto("GOTO_", points) == (None, None)
    assert resolve_goto("GOTO_A B", points) == (None, None)
    assert resolve_goto("STOP", points) == (None, None)
    assert resolve_goto("GOTO_A", {}) == ("A", None)
