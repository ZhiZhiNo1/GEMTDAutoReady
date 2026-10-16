# Dota2Auto

自动处理小黑盒 PC 客户端中的宝石 TD 组队邀请和准备操作，并监控 Dota 2 更新弹窗；检测到更新时会通过 Steam 重启 Dota 2。

Dota 更新监控和小黑盒邀请/准备识别独立运行。接受邀请、点击准备等后续步骤各自最多等待 3 秒；超时会立即恢复常规识别。

Dota 更新弹窗使用中央区域的灰度多尺度模板匹配，截图只取 Dota 客户区以排除标题栏、边框和阴影；优先按 1920 模板宽度和客户区宽度估算缩放（忽略 4:3 窗口上下的 16:9 黑边）。只有出现较强疑似匹配时才做宽范围兜底搜索，避免无弹窗时反复扫描所有比例。

小黑盒模板优先按窗口所在显示器的 DPI 缩放比例匹配（如 100%、125%、150%）；未命中时只补查 1.0、1.25、1.5 三个常见比例，首次检测和 DPI 比例变化时会输出日志。

## 使用

启动脚本前，请保持 Dota 2 和小黑盒 PC 客户端已打开。运行源码：

```powershell
pip install -r requirements.txt
python main.py
```

源码运行时建议以管理员身份打开终端，以便脚本调整两个客户端窗口层级。

在控制台按 `Ctrl+C` 正常退出，脚本会恢复 Dota 和小黑盒窗口层级。点击控制台关闭按钮时也会尝试清理；通过任务管理器强制结束进程则无法保证清理完成。

## 检查截图识别

收到用户反馈的截图时，可按要检查的识别项运行对应脚本。每个脚本使用程序实际调用的匹配逻辑，并输出匹配分数、缩放比例和识别位置：

```powershell
python tests/check_dota_update_popup.py "G:\path\to\screenshot.png"
python tests/check_xhb_notification_badge.py "G:\path\to\screenshot.png"
python tests/check_xhb_accept_invite.py "G:\path\to\screenshot.png"
python tests/check_xhb_ready.py "G:\path\to\screenshot.png"
python tests/check_xhb_cancel_ready.py "G:\path\to\screenshot.png"
python tests/check_xhb_arcade_match.py "G:\path\to\screenshot.png"
python tests/check_xhb_gem_td.py "G:\path\to\screenshot.png"
```

默认阈值与程序一致（Dota 为 `0.76`，小黑盒为 `0.86`）。可用 `--threshold` 临时指定阈值、`--template` 指定模板；小黑盒截图还可用 `--scale` 指定显示缩放比例（默认 `1.0`）。返回 `MATCH` 表示达到阈值，`NO MATCH` 表示未达到。

小黑盒如果回到默认页面，脚本会识别并点击“游廊匹配”，随后识别宝石 TD 图标并进入该游戏页面，再恢复邀请和准备状态监控。

## 打包为 EXE

在项目根目录运行以下命令：

```powershell
pyinstaller -F -c --uac-admin --add-data "templates;templates" main.py
```

打包结果位于 `dist/main.exe`。启动时 Windows 会请求管理员权限。
