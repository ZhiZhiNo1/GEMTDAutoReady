# GEMTDAutoReady

自动处理小黑盒 PC 客户端中的宝石 TD 组队邀请和准备操作，并监控 Dota 2 更新弹窗；检测到更新时会通过 Steam 重启 Dota 2。

当前主程序不自动点击 Dota 游戏内“开始游戏”按钮，不检测开局倒计时，也不执行开局失败后的取消和重试。相关截图识别工具仍保留，但不参与主程序运行流程；虚拟桌面入口 `scripts/main_multi_desktops.py` 复用相同的监控逻辑。

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

Dota 和小黑盒窗口分开时，程序分别置顶并独立识别；窗口外框重叠时，才会交替置顶，避免互相遮挡。

在控制台按 `Ctrl+C` 正常退出，脚本会恢复 Dota 和小黑盒窗口层级。点击控制台关闭按钮时也会尝试清理；通过任务管理器强制结束进程则无法保证清理完成。

## 检查截图识别

收到用户反馈的截图时，可按要检查的识别项运行对应脚本。这些工具共用 `dota_matching.py` 或 `xhb_matching.py` 的匹配函数，仅检查输入截图并输出结果，不执行点击或自动化流程。保留工具不代表对应功能当前已启用。

当前自动化流程使用的识别项：

```powershell
python tests/check_dota_update_popup.py "G:\path\to\screenshot.png"
python tests/check_xhb_notification_badge.py "G:\path\to\screenshot.png"
python tests/check_xhb_accept_invite.py "G:\path\to\screenshot.png"
python tests/check_xhb_ready.py "G:\path\to\screenshot.png"
python tests/check_xhb_cancel_ready.py "G:\path\to\screenshot.png"
python tests/check_xhb_arcade_match.py "G:\path\to\screenshot.png"
python tests/check_xhb_gem_td.py "G:\path\to\screenshot.png"
```

以上工具的默认阈值与当前主程序一致：Dota 更新弹窗 `0.76`，小黑盒各项 `0.86`。

仅供独立测试的历史识别工具（当前主程序未调用）：

```powershell
python tests/check_dota_start_game.py "G:\path\to\screenshot.png"
python tests/check_dota_start_cancel.py "G:\path\to\screenshot.png"
python tests/check_dota_starting.py "G:\path\to\screenshot.png"
```

这三个工具分别检查 Dota 开始按钮、取消按钮和倒计时提示，默认阈值分别为 `0.80`、`0.80`、`0.85`。这些值是保留工具的默认值，不代表当前主程序启用了对应检测。

所有截图检查工具均可用 `--threshold` 临时指定阈值、`--template` 指定模板；小黑盒截图还可用 `--scale` 指定显示缩放比例（默认 `1.0`）。输出包含匹配分数、缩放比例和识别位置；返回 `MATCH` 表示达到阈值，`NO MATCH` 表示未达到。

小黑盒如果回到默认页面，脚本会识别并点击“游廊匹配”，随后识别宝石 TD 图标并进入该游戏页面，再恢复邀请和准备状态监控。

## 许可证与界面模板

本项目的原创源代码、测试脚本和文档采用仓库根目录 `LICENSE` 中的 MIT License。

`templates/` 中的图片是从 Dota 2 和小黑盒客户端界面裁剪的识别模板，不属于本项目原创内容，也不包含在本项目的 MIT 授权范围内。MIT 许可证不授予这些第三方界面素材的使用或再分发权利；相关权利归各自权利人所有。本项目与 Dota 2、Valve 或小黑盒没有官方关联。

## 打包为 EXE

截图失败时暂停两个监控通道的识别和点击，每 4 秒左右自动重试。
失败通道全部恢复后自动继续，暂停前的旧截图不会用于点击。
日志在首次失败、持续失败每 60 秒及恢复时记录截图区域、输入桌面、线程桌面、窗口站、会话 ID、连接状态和虚拟屏幕范围；状态查询无权限时记录错误，不影响重试。
Windows 的输入桌面与 Win+Tab 虚拟桌面不同，不能仅凭桌面名称或连接状态认定发生了锁屏或 UAC 提示。

在项目根目录运行以下命令：

```powershell
pyinstaller -F -c --uac-admin --icon "assets\gem-td-icon.ico" --add-data "templates;templates" main.py
```

打包结果位于 `dist/main.exe`，并使用 `assets/gem-td-icon.ico` 作为程序图标。启动时 Windows 会请求管理员权限。
