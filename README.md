# 飞牛音乐 · Home Assistant

**Experimental / 非官方、只读集成**。普通音乐账号直连 fnOS 官方音乐服务；
不需要 Music Assistant、音桥、NAS 管理员、SSH 或数据库访问。

## 开始体验

已开发验证基线：Home Assistant Core **2026.9.4 / Python 3.14**，
飞牛音乐 **1.0.1 (0.8.41)**。不同版本和所有音箱/音频格式不作保证。

1. 备份 HA 配置，把 `custom_components/feiniu_music` 复制到 HA 的 `custom_components`。
   首次安装或 Python 代码更新后重启 HA；先在测试实例使用。
2. 设置 → 设备与服务 → 添加集成 → **FeiNiu Music**。
   填写官方音乐地址 `http(s)://HOST:PORT/music/`、普通音乐用户名和密码。
3. 勾选已有的 HA 输出播放器。**每个账号 × 选中输出**各有一个固定飞牛队列实体，
   可以同时播放不同音乐。集成选项可以增删输出；不会重载仍启用的其它输出。
4. 打开对应的 **飞牛音乐 · 输出名称**，使用原生“浏览媒体”：歌曲、专辑、歌手、歌单。
   专辑/歌单可整单播放；点击列表中的一首会从该位置继续，保留重复歌曲和上下文。
   搜索结果直接选曲是单曲，不擅自扩展成其它搜索结果。
5. 安装下面的可选卡片，可以编辑队列、查看歌词和选择音乐；标准 HA 播放动作仍可独立使用。

直接在原始音箱实体选择飞牛 `media_source` 仍是**单曲播放**。
完整队列使用飞牛实体；本集成不会把 enqueue/random/repeat 假装交给不支持的音箱。

### 队列／歌词卡片

集成随包提供无 CDN、无额外生产依赖的构建产物。HA 管理员在
设置 → 仪表盘 → 资源中添加（需开启用户高级模式）：

```yaml
url: /feiniu_music/feiniu-music-card.js?v=0.3.0-compact-lyrics-400
type: module
```

在仪表盘的添加卡片中选择 **FeiNiu Music**，可视化选择飞牛播放器、展示模式、紧凑卡片内容、背景、标题和配色。
新添加的卡片默认为深色紧凑卡片，自动显示同步歌词；也可以使用 YAML，替换示例实体 ID：

```yaml
type: custom:feiniu-music-card
entity: media_player.your_feiniu_output
title: 客厅音乐
display_mode: compact
compact_view: auto
compact_background: artwork
compact_mask: soft
theme: dark
```

`compact` 适合普通仪表盘。背景与内容模式分别选择：
`compact_background: default` 保留原默认底色、透明度与边框；`artwork` 使用封面氛围，
背景颜色随封面平滑过渡。旧 YAML 不填此项时保留原默认背景，新添加卡片默认封面氛围。
封面氛围下可选 `compact_mask: soft`（默认柔和蒙版）或 `glass`（通透玻璃）；可视化编辑器提供同样的选择。
播放按钮、队列／音量和下方进度条保留原来的布局与图标尺寸；紧凑标题前不显示音符图标。
按钮点击区域为正方形，焦点轮廓保持正圆；加载、来源接管、失败和离线提示统一放在进度条下方，不覆盖歌词。
`compact_view` 可选 `simple`（精简播放器）、`lyrics`（固定歌词区）或 `auto`（有歌词时展开，无歌词时收起为精简播放器）。
歌词模式加载时显示加载提示，无歌词时显示“暂无歌词”，不会切换成大封面。自动模式在歌词尚未返回时保持精简。
纯文本歌词直接显示，不模拟同步滚动；不提供额外的封面／歌词切换按钮，也不重复放大封面。
歌词播放器卡片总高 400 像素，歌词区 164 像素；短句可同时显示当前句和上下各两句，长句换行时可见句数会减少。
模糊与淡化随歌词距离中心的位置连续变化，只有最外沿用于淡出；悬停、聚焦或选中的句子恢复清晰。
歌词文字点选与时间跳转沿用完整播放页；顶部卡片名与音箱名合并为一行，省出的高度留给歌词；偏移快捷按钮位于歌词左侧独立区域，不占额外一行，与右侧时间按钮分开。
旧紧凑卡片未填 `compact_view` 时保留精简模式。点击封面打开播放／歌词界面，右上角展开按钮
打开音乐库，队列按钮打开队列；它们共用同一个弹层和播放器，关闭不会停止播放。
`full` 保留完整音乐界面，适合 HA 的 `panel` 视图；可选 `height: 700`（600–1200 像素）。
旧 YAML 未填写 `display_mode` 时继续使用 `full`，不会改变已有页面。
外观编辑不会改动队列或输出配置；起播／续播兼容性仍在集成配置中按播放器调整。

另一个输出使用另一张卡片。卡片包含原生媒体选择/搜索、追加、下一首播放、
跳播、移除、待播顺序调整、上下首、随机、循环、音量、歌词与视觉偏移。
不会自动修改用户其它仪表盘。卡片 API 经过 HA 用户实体权限检查；队列按页读取，
修改带 revision，旧页面不能悄悄修改新版队列。全文歌词和完整队列不进入实体状态/Recorder。

歌词偏移单位为秒，正值提前显示后续歌词，只影响显示。设备没有可靠位置时明确标记估算；
固定偏移不能消除网络抖动。隐藏页面停止动画与请求。标题/歌词按文本渲染。

## 播放和恢复规则

- 队列项按**出现次数**独立标识，相同歌曲可以重复。随机只重排待播项，保留当前项和历史；
  关闭随机恢复待播的原始相对顺序。repeat-one 只影响自然结束，手动下一首仍前进。
- `play_media` 支持 `replace`（默认）、`add`、`next`、`play`。
  空队列 `add`/`next` 只入队，不自动发声。
- 移除正在播放的当前项会播放后继项；暂停/尚未播放时移除不会自动发声。
  Previous 默认上一项，首项重播自身，repeat-all 可回到末项。
- Stop/Pause 可取消正在读取曲库或等待起播的操作。新的操作会使旧异步结果失效。
  已发往物理设备的远程命令不能被 Python 取消原子撤回。
- 同一 HA 输出只由一个飞牛会话主动控制。显式用另一账号播放时，旧会话失去控制但保留队列。
  这不是外部 TTS/AirPlay 的设备锁，也不能自动识别同一音箱的多个协议实体。
- 默认起播需要当前媒体的播放报告，加音频交付或新鲜设备进度；服务返回 200、HEAD 请求、
  界面外推进度都不单独证明起播。HTTP 下载完成不表示歌播完。
- 默认自动下一首需要已确认当前轮次、关联的结束状态和有效位置/时长。停止、权限失败、掉线、
  其它来源接管会停止自动控制，保留队列。不会自动跳过全部失败歌曲或反复登录。
- 设备侧接近结尾的 Stop 可能与自然结束不可区分；飞牛实体的 Stop 明确优先。
  无可靠反馈的设备可以手动切歌，不保证自动续播。
- 卡片设置允许按输出选择“加载后补一次 Play”、起播确认和结束状态兼容策略。
  默认保守；PAUSED/OFF 或弱反馈结束可能误判用户暂停。兼容 Play 有界、可取消，
  仍受 HA 当前暴露的能力限制，不绕过 HA、不发私有 SOAP。
- 已在隔离测试复现 HA 2026.9.4 DLNA DMR 的一种路径：Stop/SetURI 后缓存仍为 PLAYING，
  Core 可能跳过 Play。该候选提供明确未确认状态与重试入口，**不是对 MA3 所有起播问题的核心修复**。
  本轮没有控制真实 MA3，不能声称真机问题已全部解决。

### 队列保存

HA Store 按账号保存选中输出的队列顺序、偏好和可用的 native 位置。
使用防抖/原子写入，绝不持久化音频 URL、Cookie、签名、任务或 monotonic 值。
重载/重启后队列恢复为待继续，**不自动发声、不抢回音箱**。
用户点击播放后重新验权、获得新音频地址；有准确保存位置且当前输出支持 SEEK 时请求恢复，
以设备反馈为准。否则从头播放，不假装恢复到旧位置。

取消选择或暂时禁用输出保留其队列；永久删除账号只删除该账号的队列。
存储格式损坏会保留原文件并给出 HA Repair 提示，不用空队列静默覆盖它。
恢复方法：先备份 HA；停止 HA，把本集成自己的 `.storage/feiniu_music.queues.<entry_id>`
另存留证，再恢复相同账号的有效备份，或移走该损坏文件以明确重新开始。
不要修改其它 `.storage` 文件，也不要修改存储中的凭据。

## 旧安装迁移与回滚

0.1.x 的 `output_player` 自动迁移为固定选择项。原输出有效时沿用原飞牛实体 unique ID，
保留 entity_id、用户改名和自动化引用。账号、device ID、密码及无关选项不变。
旧输出未明确保存、已不可安全绑定时，提示选择输出，不随机选第一台音箱。
注册表 UUID 绑定跟随输出改 entity_id；离线不移除。未注册实体只能按 entity_id 绑定，
该实体改名需要在选项重新选择，不能保证永远稳定。

旧版队列只在内存，不能承诺跨代码重启迁移未保存的队列。
升级前记下需要的曲目/列表；新版本开始使用持久队列。
回滚应停止测试 HA，恢复**升级前的集成和该次配置/注册表备份**，再启动；
不要只降 Python 文件而留下新版配置版本。恢复整份 HA 备份会撤回备份后的其它更改，
因此先保存当前配置，并在隔离实例操作。已有签名播放/封面链接会失效，需重新选择播放。

## 认证、内容与资源边界

- 使用普通音乐账号；不支持 FN ID、NAS OAuth、CUE 分曲、任意反向代理路径前缀。
  服务 URL/用户名固定，改身份需移除后新增；同账号改密码使用 HA Reconfigure/重新认证。
- Track metadata 与 playlist member 只允许明确整数 `accessStatus == 0`，不接受 bool/字符串。
  已测版本 album/artist 的子项由服务端过滤，正常行没有该字段；不能误套 playlist 过滤。
  支持 Artist → Tracks 以及 Artist → Albums。
- 完整分页完成后才返回，途中失败不会缓存半份成功结果；播放前重新读取 track metadata。
- 列表/关系/搜索缓存 30 秒，最多 16 份/10,000 行；详情 30 秒/128 项。
  owner 索引最多 10,000 项，直接查找精确关联，不逐张遍历曲库。命中不会延长权限期限。
  元数据和图片分别最多 4 个请求，按独立通道控制请求开始频率；音频启动不排在图片后面。
  同服务器登录仍串行，认证失败仍有界重试。
  原生 600 像素源图按需生成 128/256/512 像素 WebP，浏览默认 256，播放器默认 512。
  不增加运行时依赖，使用 HA 自带 Pillow，在执行器中处理图片。
  源图内存最多 32 MiB/512 张；资源热缓存最多 16 MiB/512 项。
  `.storage/feiniu_music_artwork` 下每个 entry/账号独立缓存最多 128 MiB/2,048 个文件，
  资源期限 1 小时；重载/重启保留，移除来源清理该来源的文件。文件名仅含哈希。
  相同封面下载/缩略图生成合并，失败短缓存 30 秒；没有全库后台预抓。
  owner 权限和精确 owner→cover 关联始终在取图前检查；缓存命中不等于重新授权。
  封面使用稳定短期路径和预先计算的 ETag。浏览器采用 private 缓存，其 max-age
  不超过剩余 30 秒权限证据及签名/短令牌期限；不沿用 NAS 的 public 缓存头。
  权限证据过期只重新验权，不因此丢掉图片文件。已看过的资源可跨重载/重启复用，
  但账号/owner 的当前检查始终先于磁盘或内存返回，不能保证撤回已经交付的图片。
  卡片按队列出现项 ID 复用行和图片节点；同一地址不重复设置 src，浏览页复用同一缩略图入口。
- 歌词缓存每账号 32 首/5 分钟，读取前验权；切歌后的迟到歌词被丢弃，失败不停止音频。
- 每个输出每轮使用独立 HA 音频路径。Stop/切歌撤销本轮，不中断同账号其它输出；
  保留 HEAD、单 Range、206/416、背压和请求取消。没有新增 FFmpeg/转码服务器。
- 音频由音箱解码；HTTP 有效音频不等于所有格式可播。已交付字节后不会悄悄重登从头重放。
- 上游 token/密码留在服务端。音箱得到的 HA 签名 URL 本身是有限访问能力，应视为敏感信息。
  HA 自己的原始输出实体可能记录它；本集成诊断不包含这些 URL。
- 账号实例隔离不是 HA 用户级音乐 ACL。配置的来源在 HA 的媒体源权限模型下可见。
  已交付或客户端缓存的数据不能保证撤回。不要把这里当 NAS 的即时全局权限系统。

## HACS 与开发

仓库包含 `hacs.json` 和标准 `custom_components/feiniu_music` 结构。
可通过 HACS 自定义 Integration 仓库安装，前提是使用者能访问仓库；**私有仓库不是公开可安装来源**。
没有提交 HACS 默认库，没有官方授权/背书声明。品牌图案的再分发依据仍未单独确认。

开发测试、构建、浏览器检查见 [TESTING.md](TESTING.md)，架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。
安装包只包含集成与说明，不含账号、研究记录、音乐或开发数据库。
完整体验步骤见 [EXPERIENCE.md](EXPERIENCE.md)，卡片示例见 [examples/dashboard.yaml](examples/dashboard.yaml)。

---

## English quick start

An experimental, unofficial, read-only integration for the official FeiNiu Music service.
Use a regular music account, then select existing HA outputs. Each account/output pair has
an independent queue; the original `media_source` remains available for direct single-track playback.
No Music Assistant, bridge, NAS administrator access, external database or transcoding service is required.

Install `custom_components/feiniu_music`, restart HA, add the integration and select outputs.
Register `/feiniu_music/feiniu-music-card.js?v=0.3.0-compact-lyrics-400` as a Lovelace JavaScript module and add
`type: custom:feiniu-music-card` with the fixed FeiNiu `entity` ID. The visual editor selects the
player, display mode, compact content, title and colors. New picker cards default to
`display_mode: compact`, `compact_view: auto`, `compact_background: artwork`, `compact_mask: soft`, and dark colors.
Compact content can be `simple`, `lyrics`, or `auto`. Auto expands for available lyrics and
collapses to the simple player when lyrics are absent or pending. Explicit lyrics mode keeps its
lyric region and displays loading/empty text; it never substitutes enlarged artwork. Existing compact
YAML without `compact_view` keeps the simple player. The independent background preset is
`default` (original colors/opacity, also used by older YAML) or `artwork` (cover ambiance), with
`compact_mask: soft` (default soft veil) or `glass` (translucent glass) available for artwork.
The 400 px lyrics card devotes 164 px to lyrics, fitting the current short line and two on each
side; wrapped lyrics show fewer entries. Blur and opacity vary continuously with distance from
the centre, with a fade at the outer edge. Hover, focus and selection restore clear text.
The single-line header saves space for lyrics. Offset controls sit on the left, separate from
timestamps on the right. The simple player retains its compact size.
Legacy YAML without `display_mode` keeps the full interface. Compact cards expand into a shared
modal for the library, queue or lyrics without changing playback. `display_mode: full` suits a
panel view, with optional `height` (600–1200 pixels). The optional card provides
queue editing, native browsing/search, lyrics, controls and per-output compatibility preferences.
Chinese and English are included. The backend remains authoritative, including with multiple browsers.

Queues persist through reload/restart but never autoplay on restore. Explicit resume revalidates
access and mints a new playback address. Saved native positions are requested only when SEEK is
available; unsupported/unconfirmed seek is not presented as accurate resume. Shuffle only changes
pending items; duplicate tracks retain distinct occurrence IDs. Empty `add`/`next` does not autoplay.

Upgrading from 0.1.x preserves the old entity identity when its saved output can be safely bound.
No saved output means a repair prompt, never automatic speaker selection. Legacy in-memory queues
cannot be recovered across restart. Back up integration/configuration/registry/storage before upgrading;
rollback requires the matching pre-upgrade code and configuration backup, not code alone.

Validated versions: HA 2026.9.4 / Python 3.14 and FeiNiu Music 1.0.1 (0.8.41). Other releases,
large libraries and all speaker/codec combinations remain unverified. No FN ID, NAS OAuth, CUE
split tracks or arbitrary proxy prefixes. Formats are decoded by the output device. The local DLNA
cached-PLAYING reproduction does not establish that every MA3 startup issue is fixed. Physical speaker
control was not exercised in this candidate's tests; distinguish HA state, HTTP delivery and actual sound.

The default completion policy is conservative. External takeover, access failures, disconnects and
unconfirmed startup halt automatic control and retain the queue. Optional PAUSED/OFF or weak end-state
profiles can misinterpret manual device-side pauses/stops. Integration leases coordinate only FeiNiu
sessions, not external controllers or different protocol entities for the same physical speaker.

Caches are account-scoped and bounded: browse/detail/access evidence 30 seconds, lyrics 5 minutes,
and image resources 1 hour. Persistent source/128/256/512 px thumbnails share a 128 MiB/2,048-file
cap per entry/account; memory resources are also bounded. Current owner access is checked before
cached pixels, including after reload/restart. Browser private max-age cannot outlive the remaining
30-second access evidence or signed-link/grant expiry. Separate, limited request lanes prevent image
downloads from serializing metadata/audio startup. Cached or already delivered content cannot be
instantly recalled. Account isolation is not HA-user library ACL.
The card's queue API enforces HA entity permissions and revisions. Music credentials remain server-side;
HA playback URLs are short-lived access grants and should not be logged or shared. Diagnostics omit them.
The private repository must remain accessible to an installer; HACS metadata does not make it public.
