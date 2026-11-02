"""Dota 更新弹窗的图像匹配逻辑，可供运行脚本和截图检查工具共用。"""

import os
import math
from pathlib import Path

import cv2


DOTA_UPDATE_MATCH_THRESHOLD = 0.76
DOTA_START_GAME_MATCH_THRESHOLD = 0.80
DOTA_START_CANCEL_MATCH_THRESHOLD = 0.80
DOTA_STARTING_MATCH_THRESHOLD = 0.85
DOTA_ARCADE_UPDATE_MATCH_THRESHOLD = 0.84
DOTA_ARCADE_UNINSTALL_MATCH_THRESHOLD = 0.84
DOTA_ARCADE_INSTALL_MATCH_THRESHOLD = 0.84
DOTA_ARCADE_NAV_MATCH_THRESHOLD = 0.84
DOTA_UPDATE_FALLBACK_TRIGGER = 0.5
DOTA_TEMPLATE_REFERENCE_WIDTH = 1920
DOTA_UPDATE_FALLBACK_SCALES = (0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0, 1.1, 1.2, 1.3, 1.45, 1.6, 1.8)
DOTA_START_CANCEL_SEARCH_REGION = (0.5, 0.5, 1.0, 1.0)
DOTA_STARTING_SEARCH_REGION = (0.65, 0.65, 1.0, 0.9)
# Arcade workshop controls are matched in narrow, normalized client-area regions.
DOTA_ARCADE_ACTION_SEARCH_REGION = (0.68, 0.75, 0.91, 0.91)
DOTA_ARCADE_UNINSTALL_SEARCH_REGION = (0.68, 0.30, 0.91, 0.43)
DOTA_ARCADE_GEM_PAGE_SEARCH_REGION = (0.15, 0.22, 0.50, 0.70)
DOTA_ARCADE_TAB_SEARCH_REGION = (0.52, 0.00, 0.72, 0.13)
DOTA_ARCADE_LIBRARY_SEARCH_REGION = (0.20, 0.04, 0.43, 0.17)
DOTA_ARCADE_GEM_CARD_SEARCH_REGION = (0.25, 0.14, 0.50, 0.43)


def arcade_content_region(screen, region):
    """Translate 16:9 Arcade UI regions into a vertically letterboxed client."""
    height, width = screen.shape[:2]
    content_height = round(width * 9 / 16)
    top = (height - content_height) // 2
    if top <= 0:
        return region
    # Only compensate for actual dark bars, not arbitrary tall game layouts.
    if screen[:top].max() > 8 or screen[top + content_height:].size == 0:
        return region
    if screen[top + content_height:].max() > 8:
        return region
    left, upper, right, lower = region
    return left, (top + upper * content_height) / height, right, (top + lower * content_height) / height


def select_dota_template(template_path, screen_width, screen_height):
    """Select per-image resolution resources; explicit external paths stay unchanged."""
    path = Path(template_path)
    root = path.parent.parent
    if root.name != "dota2" or not root.is_dir():
        return path, (DOTA_TEMPLATE_REFERENCE_WIDTH, 1080)
    candidates = []
    for directory in root.iterdir():
        try:
            width, height = map(int, directory.name.split("_"))
        except ValueError:
            continue
        candidate = directory / path.name
        if width <= 0 or height <= 0 or not candidate.is_file():
            continue
        if (width, height) == (screen_width, screen_height):
            return candidate, (width, height)
        aspect_difference = abs(math.log((width / height) / (screen_width / screen_height)))
        rank = (0 if aspect_difference <= 0.03 else aspect_difference,
                abs(math.log(width / screen_width)), aspect_difference, directory.name)
        candidates.append((rank, candidate, (width, height)))
    if not candidates:
        return path, (DOTA_TEMPLATE_REFERENCE_WIDTH, 1080)
    _, candidate, resolution = min(candidates)
    return candidate, resolution


def match_template_multiscale(
    screen_bgr,
    template_path,
    threshold,
    scales,
    search_region=(0.2, 0.2, 0.8, 0.8),
    force_fallback=False,
    refine_scales=False,
):
    """灰度多尺度匹配；search_region 为归一化的 (左, 上, 右, 下) 区域。

    force_fallback=True 时，在首选比例未达阈值后继续尝试完整候选比例集合。
    """
    screen_h, screen_w = screen_bgr.shape[:2]
    template_path, reference_size = select_dota_template(template_path, screen_w, screen_h)
    exact_resolution = reference_size == (screen_w, screen_h)
    if not os.path.exists(template_path):
        return None, 0.0, 1.0

    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None, 0.0, 1.0

    screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    screen_h, screen_w = screen_gray.shape[:2]

    if Path(template_path).name.startswith('dota_arcade_'):
        search_region = arcade_content_region(screen_bgr, search_region)
    left_ratio, top_ratio, right_ratio, bottom_ratio = search_region
    left, top = int(screen_w * left_ratio), int(screen_h * top_ratio)
    right, bottom = int(screen_w * right_ratio), int(screen_h * bottom_ratio)
    search_area = screen_gray[top:bottom, left:right]
    area_h, area_w = search_area.shape[:2]

    # 每张模板独立选择分辨率组；缺少当前分辨率时按所选组宽度缩放。
    window_scale = screen_w / reference_size[0]
    preferred_scales = sorted({
        round(window_scale * factor, 3)
        for factor in (0.8, 0.9, 1.0, 1.1, 1.2)
        if window_scale * factor >= 0.25
    })

    if exact_resolution:
        preferred_scales = [1.0]

    best_center = None
    best_score = 0.0
    best_scale = 1.0

    def search_scales(candidate_scales):
        nonlocal best_center, best_score, best_scale
        for scale in candidate_scales:
            width = max(1, round(template.shape[1] * scale))
            height = max(1, round(template.shape[0] * scale))
            if width > area_w or height > area_h:
                continue

            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            resized = cv2.resize(template, (width, height), interpolation=interpolation)
            result = cv2.matchTemplate(search_area, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if score > best_score:
                best_score = score
                best_scale = scale
                best_center = (
                    left + location[0] + width // 2,
                    top + location[1] + height // 2,
                )

    # 常规识别只搜索窗口宽度对应的比例附近；特殊状态可要求未命中时做全范围兜底。
    search_scales(preferred_scales)
    if best_score >= threshold:
        return best_center, best_score, best_scale
    if not exact_resolution and (force_fallback or best_score >= DOTA_UPDATE_FALLBACK_TRIGGER):
        fallback_scales = (round(scale * DOTA_TEMPLATE_REFERENCE_WIDTH / reference_size[0], 3)
                           for scale in scales)
        search_scales(scale for scale in fallback_scales if scale not in preferred_scales)

    # Small text templates are sensitive to rounding at fractional window sizes.
    # Only refine a plausible match, keeping the common no-popup path inexpensive.
    if not exact_resolution and refine_scales and DOTA_UPDATE_FALLBACK_TRIGGER <= best_score < threshold:
        search_scales(sorted({
            round(window_scale * (0.8 + step * 0.01), 3)
            for step in range(41)
            if window_scale * (0.8 + step * 0.01) >= 0.25
        }))
    if best_score >= threshold:
        return best_center, best_score, best_scale
    return None, best_score, best_scale


def match_any_template_multiscale(
    screen_bgr,
    template_paths,
    threshold,
    scales,
    search_region=(0.2, 0.2, 0.8, 0.8),
):
    """Match the strongest of several visual states of the same control."""
    best = (None, 0.0, 1.0)
    for template_path in template_paths:
        center, score, scale = match_template_multiscale(
            screen_bgr,
            template_path,
            threshold,
            scales,
            search_region=search_region,
        )
        if score > best[1]:
            best = (center, score, scale)
    return best
