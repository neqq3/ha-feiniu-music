# 体验与恢复

1. 在「设置 → 设备与服务 → 飞牛音乐 → 配置」选择已有的 HA 音频输出。
   每个账号与输出组合对应一个固定播放器；不要选择飞牛播放器自身或已包含它的组。
2. 配置集成后刷新页面，在仪表盘添加 FeiNiu Music，使用可视化编辑器选择飞牛播放器、
   紧凑／完整模式、标题和配色。新增卡片默认深色紧凑、自动歌词；旧 YAML 未写 `display_mode` 时保留完整模式。
   紧凑内容可选精简、歌词、自动；歌词模式保留固定歌词区，自动模式有歌词时展开、无歌词时收起为精简播放器。
   背景独立选择：原默认背景与透明度，或随封面变色的氛围背景。后者可选柔和蒙版／通透玻璃，默认柔和蒙版。
   旧 YAML 默认保留原背景；可视化编辑器支持以上选择。
   标题前不显示音符图标；控制按钮排列、图标尺寸及下方进度条沿用原紧凑卡片，点击区域与焦点轮廓保持正圆。
   暂停冻结当前位置，切歌清空旧歌词；纯文本歌词直接显示，固定歌词模式加载／无歌词时显示相应提示。
   不提供额外封面／歌词切换按钮，也不重复显示大封面；自动模式加载中保持精简。
   输出被接管、失败或离线显示真实状态；不增加“正在播放／已暂停”状态标签。
   加载、来源接管、失败和离线统一用进度条下的小提示表示，不用横条遮盖歌词。
   旧紧凑卡片未选内容时保留精简。点封面打开播放页，点展开打开音乐库。
   弹层复用所选播放器，关闭不会停止播放或重建队列。完整模式适合单卡片的 HA 面板视图。
   YAML 示例见 `examples/dashboard.yaml`；起播与续播配置仍属于集成，每个输出独立保存。
3. 在卡片「选择音乐」里展开专辑、歌单、歌手歌曲或所有歌曲。
   歌曲、专辑、歌手及专辑／歌手内容按页读取，每页最多 100 项；底部可翻页。
   侧栏歌单不会挡住主列表，封面仍按需加载。切换分类立即更新标题，等待时不保留旧数量。
   歌单内歌曲及搜索结果仍完整读取；等待超过限定时间可重试，不会把部分结果当成空库。
   「播放整个列表」开始连续播放；单曲的加号只追加这首；下一首加入不会立即发声。
   点歌曲直接播放会保留它的列表上下文。纯 media_source 直接投送仍是单曲能力。
4. 两个输出可同时拥有不同队列。队列中的重复歌曲是不同条目，可以分别移动、删除或跳转。
   随机只调整待播部分；手动下一首不会被单曲循环困住。
5. 暂停/恢复、音量和 seek 取决于输出支持。播放状态、HTTP 已交付与真实出声不是同一回事。
6. 歌词页区分无歌词、纯文本和同步歌词。设置里的秒数偏移只调整显示，不改变音频位置。
   同步歌词右上角可每次提前／延后 0.5 秒，点击偏移数值恢复默认；与设置使用同一个值。
   鼠标进入歌词区或键盘聚焦时显示偏移按钮；触屏操作歌词时也会显示。
   歌词卡片总高 425 像素，顶部名称合并一行，短句可显示当前句和上下各两句；长句换行会减少可见句数。
   偏移按钮在歌词左侧，右侧是时间跳转按钮；紧凑歌词保持清晰，仅保留淡化和最外沿淡出。
   滚轮／触摸滚动后暂停自动跟随，停止操作 8 秒后回到当前歌词，不增加额外返回按钮。
   点击歌词文字只将该句居中，不跳转音频；完整播放页保留边缘模糊，紧凑卡片取消模糊，悬停时均会提亮。
   点击每句右侧的时间可从该句播放；定位会考虑显示偏移，暂停状态下定位成功后恢复播放。
   时间按钮仅在该句被悬停、聚焦或选中时显示，暂停和不可跳转不会让所有按钮出现。
   设备不支持当前歌曲定位时，时间按钮不可操作。纯文本歌词可以用滚轮、触屏或键盘手动浏览，
   但没有时间轴，不能自动跟随播放或按句跳转，也不显示偏移快捷按钮。
   竖屏歌名和副标题与封面居中对齐；播放页进出使用淡入淡出和小幅位移，不缩放封面。
7. 重载集成或重启 HA 后，应恢复队列但不自动播放。点击播放才重新验权并请求恢复。
8. 「设置 → 设备与服务 → 飞牛音乐 → 配置 → 起播与续播设置」先选一个飞牛代理播放器，
   再配置起播确认、结束状态、补发播放和弱反馈续播。每个账号／输出独立保存，无需安装卡片。
   保存立即更新后端，不重载账号、不清空队列、不发送播放命令；重启后仍保留。
   卡片是同一份设置的快捷入口，歌词偏移仍留在卡片。播放兼容设置仅管理员可修改。
   起播失败可下载集成诊断或查看卡片诊断。默认不无限重试；PAUSED/OFF 或弱反馈可能误判手动停止。
9. 移除一个选中输出不应打断另一个；重新选择时保留原队列。删除账号则移除该账号队列。

升级/回滚请先备份集成、配置条目、实体注册表和本集成 Store。旧版本的内存队列无法恢复。
回滚应恢复匹配的旧代码与配置版本，不能只拷回旧 Python 文件。详细边界见 README。

## English

Select outputs in integration options, refresh the browser for the automatically registered card, and replace entity IDs in
`examples/dashboard.yaml`. Browse a list and play it, or add individual songs without starting
an empty queue. Each fixed output owns its queue, occurrence IDs, repeat/shuffle and lyric offset.
Library categories and album/artist relationships load up to 100 items per page. Optional sidebar
playlists do not block main content. Play all still selects the entire list, including on later pages.
Playlist occurrences and search results remain complete reads; timeouts expose a retry action.
Reload restores queues idle; explicit Play revalidates access and requests supported native resume.
Inspect diagnostics when a device does not confirm playback. HTTP delivery is not proof of sound.
Integration options → Playback compatibility selects one FeiNiu player before editing its
start/end detection profile. Each account/output pair keeps its own persisted settings, shared
with the optional card. Saving sends no output command and does not reload the account or queue.
Lyrics offset remains a card display setting. Playback compatibility changes require an administrator.
Back up both code and config/registry/storage before upgrading or rolling back.
