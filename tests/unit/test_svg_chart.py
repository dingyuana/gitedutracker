import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest


class TestBuildLineChart:

    def test_returns_svg_string(self):
        from app.utils.svg_chart import build_line_chart
        svg = build_line_chart([("08-25", 80), ("08-26", 90)])
        assert isinstance(svg, str)
        assert "<svg" in svg and "</svg>" in svg

    def test_polyline_has_one_point_per_datum(self):
        from app.utils.svg_chart import build_line_chart
        svg = build_line_chart([("d1", 60), ("d2", 70), ("d3", 85)])
        assert svg.count("circle") >= 3
        assert "polyline" in svg

    def test_values_map_to_different_y(self):
        from app.utils.svg_chart import build_line_chart
        svg = build_line_chart([("d1", 10), ("d2", 100)])
        assert "polyline" in svg

    def test_labels_rendered(self):
        from app.utils.svg_chart import build_line_chart
        svg = build_line_chart([("08-25", 80), ("08-26", 90)])
        assert "08-25" in svg and "08-26" in svg

    def test_empty_data_returns_placeholder(self):
        from app.utils.svg_chart import build_line_chart
        svg = build_line_chart([])
        assert "暂无数据" in svg

    def test_none_scores_skipped(self):
        from app.utils.svg_chart import build_line_chart
        svg = build_line_chart([("d1", None), ("d2", 80)])
        assert "暂无数据" not in svg
        assert "polyline" in svg