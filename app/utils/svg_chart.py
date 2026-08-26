from __future__ import annotations


W, H = 640, 220
PAD_L, PAD_R, PAD_T, PAD_B = 46, 16, 16, 28


def build_line_chart(data: list[tuple[str, float | None]], title: str = "", color: str = "#1a73e8") -> str:
    points = [(str(label), float(v)) for label, v in data if v is not None]
    if not points:
        return (
            f'<div class="chart-empty">暂无数据'
            f'<small>{title}</small></div>'
        )

    values = [v for _, v in points]
    v_min, v_max = min(values), max(values)
    span = (v_max - v_min) or 1.0
    v_lo = max(0.0, v_min - span * 0.15)
    v_hi = v_max + span * 0.15
    if v_hi == v_lo:
        v_hi = v_lo + 1

    inner_w = W - PAD_L - PAD_R
    inner_h = H - PAD_T - PAD_B
    n = len(points)

    def x_at(i: int) -> float:
        if n == 1:
            return PAD_L + inner_w / 2
        return PAD_L + inner_w * i / (n - 1)

    def y_at(v: float) -> float:
        return PAD_T + inner_h * (1 - (v - v_lo) / (v_hi - v_lo))

    coords = [f"{x_at(i):.1f},{y_at(v):.1f}" for i, (_, v) in enumerate(points)]
    polyline = f'<polyline fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="{" ".join(coords)}" />'

    dots = []
    labels = []
    step = max(1, n // 8)
    for i, (label, v) in enumerate(points):
        cx, cy = x_at(i), y_at(v)
        dots.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="#fff" stroke="{color}" stroke-width="2">'
            f"<title>{label}：{v:g}分</title></circle>"
        )
        if i % step == 0 or i == n - 1:
            anchor = "middle"
            tx = min(max(cx, PAD_L + 14), W - PAD_R - 14)
            ty = H - 8
            labels.append(f'<text x="{tx:.1f}" y="{ty}" font-size="11" fill="#5f6368" text-anchor="{anchor}">{label}</text>')
            labels.append(
                f'<text x="{tx:.1f}" y="{cy - 10:.1f}" font-size="11" fill="{color}" text-anchor="{anchor}" font-weight="600">{v:g}</text>'
            )

    grid_lines = []
    for frac in (0, 0.5, 1):
        gy = PAD_T + inner_h * frac
        grid_lines.append(
            f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" stroke="#e8eaed" stroke-width="1" />'
        )
    grid_lines.append(
        f'<text x="{PAD_L - 6}" y="{y_at(v_hi):.1f}" font-size="10" fill="#9aa0a6" text-anchor="end">{v_hi:.0f}</text>'
    )
    grid_lines.append(
        f'<text x="{PAD_L - 6}" y="{y_at(v_lo):.1f}" font-size="10" fill="#9aa0a6" text-anchor="end">{v_lo:.0f}</text>'
    )

    title_el = (
        f'<text x="{PAD_L}" y="12" font-size="12" fill="#5f6368">{title}</text>' if title else ""
    )

    return (
        f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg" '
        f'style="background:#fff;border-radius:8px">'
        f'{title_el}{"".join(grid_lines)}{polyline}{"".join(dots)}{"".join(labels)}'
        f"</svg>"
    )
