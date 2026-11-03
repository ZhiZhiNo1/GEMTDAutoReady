# GEMTDAutoReady

自动处理小黑盒 PC 客户端中的宝石 TD 组队邀请和准备操作，并监控 Dota 2 更新弹窗和宝石 TD 地图更新。

当前主程序不自动点击 Dota 游戏内“开始游戏”按钮，不检测开局倒计时，也不执行开局失败后的取消和重试。相关截图识别工具仍保留，但不参与主程序运行流程；虚拟桌面入口 `scripts/main_multi_desktops.py` 复用相同的监控逻辑。

Dota 更新监控和小黑盒邀请/准备识别独立运行。接受邀请、点击准备等后续步骤各自最多等待 3 秒；超时会立即恢复常规识别。

Dota 出现需要更新的系统弹窗时，仍按原流程通过 Steam 重启 Dota 2。小黑盒提示宝石 TD 地图版本落后时，程序会在 Dota 中依次打开“游廊 → 游戏库 → 宝石 TD”，刷新地图状态；出现“更新”按钮后不会点击它，而是先点“卸载”，待页面出现“安装”后再点击安装。若导航过程中 Dota 界面暂时不可识别，会继续等待对应页面；卸载后 60 秒仍未出现“安装”时会暂停并提示检查页面（例如是否需要确认卸载）。刷新后连续 3 次确认宝石 TD 页面已安装且无需更新，会恢复常规监控；刷新等待 60 秒仍无法确认状态时也会退出本次刷新。安装按钮点击后若仍停留在宝石 TD 安装页面，至少间隔 8 秒重试，合计最多点击 3 次；安装等待 180 秒仍未完成时暂停并提示手动检查，手动完成后可自动恢复监控。

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

窗口分开且已经置顶时，截图轮询不再重复设置窗口层级；恢复最小化窗口时也不主动激活窗口。若窗口层级操作期间前台窗口发生变化，日志会记录 `target`、`before`、`after` 窗口句柄，供 Win10 反馈排查（用户同时切换窗口也可能产生此日志）。窗口重叠时仍需轮流调整层级以保证截图正确，接受邀请等操作仍使用真实鼠标点击；此修改需在反馈的 Win10 环境实际验证。

启动时会关闭 Windows 控制台的快速编辑模式，避免误选文字后阻塞日志输出、暂停两个监控通道。若旧版本已因选择文字而暂停，可按 `Esc` 退出选择以恢复。`Ctrl+C` 退出功能保持可用。

在控制台按 `Ctrl+C` 正常退出，脚本会恢复 Dota 和小黑盒窗口层级。点击控制台关闭按钮时也会尝试清理；通过任务管理器强制结束进程则无法保证清理完成。

Windows 锁屏时暂停监控通道的截图、窗口切换和点击，每 2 秒检测解锁状态；解锁后重新识别并重置小黑盒邀请流程。锁屏状态查询失败时也会暂停自动化并记录错误。

## 检查截图识别

Steam 显示“服务器指定的 app id 无效”时，测试版会先关闭该错误框，再识别同一游戏信息窗口中的 Dota 2 及“加入游戏”按钮（不限定服务器地图名称）并点击。不会对普通游戏信息窗口直接点击加入。等待错误关闭最多 10 秒，每轮间隔至少 30 秒；每个持续存在的窗口最多尝试 3 轮。只处理 Steam 进程所属可见窗口，安全桌面上不操作。Steam 窗口会在截图期间临时前置，随后恢复原有置顶状态。只接受已注册安装目录内、签名有效且签名主体为 Valve 的 Steam 程序；辅助进程还需属于有效 Steam 进程树。未注册安装目录或无法验证签名时跳过自动操作，点击前确认实际命中同一窗口。此流程已通过截图和模拟状态测试，真实进房结果仍待验证。

收到用户反馈的截图时，可按要检查的识别项运行对应脚本。这些工具共用 `dota_matching.py` 或 `xhb_matching.py` 的匹配函数，仅检查输入截图并输出结果，不执行点击或自动化流程。保留工具不代表对应功能当前已启用。

当前自动化流程使用的识别项：

```powershell
python tests/check_dota_update_popup.py "G:\path\to\screenshot.png"
python tests/check_dota_arcade_update.py "G:\path\to\screenshot.png"
python tests/check_dota_arcade_uninstall.py "G:\path\to\screenshot.png"
python tests/check_dota_arcade_install.py "G:\path\to\screenshot.png"
python tests/check_dota_arcade_gem_page.py "G:\path\to\screenshot.png"
python tests/check_dota_arcade_tab.py "G:\path\to\screenshot.png"
python tests/check_dota_arcade_library.py "G:\path\to\screenshot.png"
python tests/check_dota_arcade_gem_card.py "G:\path\to\screenshot.png"
python tests/check_xhb_notification_badge.py "G:\path\to\screenshot.png"
python tests/check_xhb_accept_invite.py "G:\path\to\screenshot.png"
python tests/check_xhb_ready.py "G:\path\to\screenshot.png"
python tests/check_xhb_cancel_ready.py "G:\path\to\screenshot.png"
python tests/check_xhb_arcade_match.py "G:\path\to\screenshot.png"
python tests/check_xhb_gem_td.py "G:\path\to\screenshot.png"
python tests/check_xhb_version_mismatch.py "G:\path\to\screenshot.png"
```

默认阈值与程序一致（Dota 更新弹窗 `0.76`、地图更新和导航按钮 `0.84`、小黑盒 `0.86`）。可用 `--threshold` 临时指定阈值、`--template` 指定模板；小黑盒截图还可用 `--scale` 指定显示缩放比例（默认 `1.0`）。返回 `MATCH` 表示达到阈值，`NO MATCH` 表示未达到。

游廊标签和“游戏库”路径导航分别保存了选中、未选中的模板；对应检查脚本会同时匹配两种外观。

小黑盒如果回到默认页面，脚本会识别并点击“游廊匹配”，随后识别宝石 TD 图标并进入该游戏页面，再恢复邀请和准备状态监控。

## Dota 分辨率模板

Dota 模板按游戏客户区尺寸组织（不包含标题栏和边框）：

```text
templates/dota2/
  1920_1080/
    update_popup.png
    start_game.png
    dota_start_cancel.png
    dota_starting.png
  1176_664/
    update_popup.png
```

优先选择与客户区宽高完全一致的目录，原尺寸匹配；没有对应目录时，优先从宽高比接近（约 3% 以内）的组中选择宽度最近的一组，再按该组宽度缩放。每张图片独立选择资源，目录里缺少某张图片不会阻断其他组的回退。更新弹窗出现疑似匹配但未达到阈值时，额外以 1% 步长搜索附近比例；无疑似匹配时不增加精细搜索。

新增分辨率时，从该客户区尺寸下的真实游戏截图裁剪同名模板，放入 `宽_高` 目录即可，无需修改代码。不要将已有模板缩放后另存为新分辨率模板。`1176_664/update_popup.png` 来自本次反馈截图；基准组迁移现有模板，其余分辨率可逐步补充。小黑盒模板仍保留在原目录，按 DPI 匹配。

截图检查工具会打印选择的模板路径及来源分辨率。传入截图应只包含游戏客户区；使用 `--template` 指向分辨率目录外的自定义图片时，沿用 1920 宽基准缩放。打包配置会递归包含这些目录。

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
python -m PyInstaller --noconfirm main.spec
```

打包配置自动读取 `main.py` 的 `__version__`，输出 `dist/GEMTDAutoReady-v<版本号>.exe`，例如 `GEMTDAutoReady-v2.1.2.exe`。发布新版本时只需更新版本号，再运行上述命令。程序使用 `assets/gem-td-icon.ico` 作为图标，启动时 Windows 会请求管理员权限。

地图操作仅针对 Steam 库中 app 570 清单对应、Valve 签名有效的 Dota 进程，截图与点击之间核对 PID、创建时间和 HWND。新地图操作使用指定窗口的鼠标消息，不发送全局鼠标点击；游戏是否接受此输入方式仍需实机验证。虚拟桌面切换与 Steam 恢复使用同一把协调锁。
