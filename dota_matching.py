"""Dota 更新弹窗的图像匹配逻辑，可供运行脚本和截图检查工具共用。"""

import os

import cv2


DOTA_UPDATE_MATCH_THRESHOLD = 0.76
DOTA_START_GAME_MATCH_THRESHOLD = 0.80
DOTA_UPDATE_FALLBACK_TRIGGER = 0.5
DOTA_TEMPLATE_REFERENCE_WIDTH = 1920
DOTA_UPDATE_FALLBACK_SCALES = (0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0, 1.1, 1.2, 1.3, 1.45, 1.6, 1.8)


def match_template_multiscale(screen_bgr, template_path, threshold, scales):
    """灰度多尺度匹配；适配 Dota 界面随游戏分辨率/DPI 变化的缩放。"""
    if not os.path.exists(template_path):
        return None, 0.0, 1.0

    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None, 0.0, 1.0

    screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    screen_h, screen_w = screen_gray.shape[:2]

    # 目标弹窗和按钮位于窗口中央，只在中央区域搜索，避开边缘普通 UI。
    left, top = int(screen_w * 0.2), int(screen_h * 0.2)
    right, bottom = int(screen_w * 0.8), int(screen_h * 0.8)
    search_area = screen_gray[top:bottom, left:right]
    area_h, area_w = search_area.shape[:2]

    # 模板来自 1920 宽的 16:9 游戏画面。使用客户区宽度估算等比例缩放，
    # 不让标题栏、边框、阴影或 4:3 画面上下的黑边影响比例。
    window_scale = screen_w / DOTA_TEMPLATE_REFERENCE_WIDTH
    preferred_scales = sorted({
        round(window_scale * factor, 3)
        for factor in (0.8, 0.9, 1.0, 1.1, 1.2)
        if window_scale * factor >= 0.25
    })

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

    # 常规轮询只搜索窗口宽度对应的比例附近；只有出现较强疑似匹配时才宽范围兜底。
    search_scales(preferred_scales)
    if DOTA_UPDATE_FALLBACK_TRIGGER <= best_score < threshold:
        search_scales(scale for scale in scales if scale not in preferred_scales)

    if best_score >= threshold:
        return best_center, best_score, best_scale
    return None, best_score, best_scale
