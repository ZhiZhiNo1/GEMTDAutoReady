"""小黑盒按钮和通知图标的模板匹配逻辑。"""

import os

import cv2


XHB_MATCH_THRESHOLD = 0.86
XHB_MATCH_FALLBACK_SCALES = (1.0, 1.25, 1.5)


def match_template_scaled(
    screen_bgr,
    template_path,
    threshold=XHB_MATCH_THRESHOLD,
    preferred_scale=1.0,
):
    """优先按窗口 DPI 缩放模板，失败时再尝试常见显示缩放比例。"""
    if not os.path.exists(template_path):
        return None, 0.0

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        return None, 0.0

    best_center, best_score = None, 0.0

    def search_scales(scales):
        nonlocal best_center, best_score
        screen_h, screen_w = screen_bgr.shape[:2]
        for scale in scales:
            width = max(1, round(template.shape[1] * scale))
            height = max(1, round(template.shape[0] * scale))
            if width > screen_w or height > screen_h:
                continue
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            resized = cv2.resize(template, (width, height), interpolation=interpolation)
            result = cv2.matchTemplate(screen_bgr, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if score > best_score:
                best_score = score
                best_center = (location[0] + width // 2, location[1] + height // 2)

    preferred_scale = round(preferred_scale, 3)
    search_scales((preferred_scale,))
    if best_score >= threshold:
        return best_center, best_score

    # DPI API 不一定反映应用最终渲染尺寸；仅补查常见档位，不做大范围逐档扫描。
    search_scales(scale for scale in XHB_MATCH_FALLBACK_SCALES if scale != preferred_scale)

    return (best_center, best_score) if best_score >= threshold else (None, best_score)
