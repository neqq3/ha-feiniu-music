# 浏览分页、缓存与生命周期验收

本轮让首屏只取所需的一页，解除不同列表之间的全局锁等待，合并相同请求，并保持原有播放授权和队列语义。没有延长 30 秒权限窗口，也没有加入数据库、后台全库同步、额外日志中心或 MA 运行时依赖。

## 基线与范围

- HA 集成公开 main 基线：`40f97a1c02ff47cff99c6afc9542331e1ef6e229`。
- 实施起点：当前工作区 `dev/support-diagnostics` 的 `bdce18cef0e572c59e365d48ba97ce6b7ce7e065`，已有原生 Diagnostics、logging 和故障引导；开始时工作区干净。
- 先补失败用例：`38deb23`；主要实现：`02e7bab`；兼容类型标注、恢复场景和测量补充：`e86723d`。
- 经用户单独授权，仅推送 `dev/browse-performance-checks` 用于 Actions；不合并 main，不创建 PR，不打 tag 或发布 release。
- 支持版本仍为 HA **2025.12.2**（Python 3.13），同时测试 HA **2026.9.4**（Python 3.14）。没有更新、重载或重启生产 HA，也没有修改 MA 工作区。

Music Assistant 参考的是 server **dev 源码** `2168c3a5db695e6de3878d41043ef76766d96c65`，不是对 MA 发布版本或本机安装版本的描述。核对了 #6416、#6680 的最终合并记录：

- [#6416](https://github.com/music-assistant/server/pull/6416)：merge `d6eb8e9a31850ad035676ef553e46a9ae4592031`。
- [#6680](https://github.com/music-assistant/server/pull/6680)：merge `9c8e9d957bb9e5f8998a321fe6612141bf058791`；属于 MA setup-flow 错误翻译元数据修复。

## 已验证的机制

旧代码在账户级 browse 锁里等待完整分页，慢歌单读取能挡住不相关的专辑请求。旧展示缓存从请求开始计时：若读取超过 TTL，刚返回的结果就可能再次请求。前端先启动可选侧栏，切换时还会短暂保留旧标题或数量。

提交实现前，双版本 Actions 都得到 **13 个新增用例失败、原有 375 项通过**：[基线回归](https://github.com/neqq3/ha-feiniu-music/actions/runs/37178045496)。这些是可控后端复现出的代码机制，不能据此宣称复现了 issue #1 用户的 NAS 现场。截图中的“4 项”符合账号根节点的四个分类，不是四首歌；加载区域属于曲库浏览，与小爱音箱是否支持播放无直接结论。

## 调用关系与覆盖范围

```text
卡片 / 飞牛播放器的原生浏览
  → HA 标准 media_player/browse_media
  → Selection.browse → FeiNiuMediaSource
原生 media_source 浏览
  → FeiNiuMediaSource
共同路径
  → runtime.browse_page → 单页 client.page / client.related
  → 本次 HA 调用者的 BrowseMedia / 签名缩略图 URL

根节点 → 四个轻量目录（无 NAS 扫描、详情或封面请求）
卡片主分类完成 → 可选侧栏 playlist/list（单独去重）
封面 → 现有图片通道 / owner 校验 / 字节缓存
歌词 → 详情验权 → 原有歌词缓存

播放全部 / 从列表某位置播放
  → Selection.items → fresh 完整枚举
  → 验证全局位置 + GUID → 原有 QueueItem / session
  → 起播前 fresh 单曲详情 → 原有音频轮次授权
追加 / 下一首 → 保留被选中的一个歌曲 occurrence
原生底层音箱直接 resolve → fresh 单曲详情 → 单曲音频
```

| 入口 | 本轮行为 |
| --- | --- |
| 歌曲、专辑、歌手分类 | 第一页只取一次原生请求，每页最多 100 项 |
| 歌手歌曲、歌手专辑、专辑歌曲 | 同一页级服务，不先枚举再切片 |
| 歌单列表 | `/playlist/list` 仍为单个非分页接口 |
| 歌单歌曲 | 保留完整读取；按原始行数判断分页结束，过滤后保序且保留重复 GUID |
| 搜索 | 保留完整结果；没有偷偷截断为一页 |
| 播放全部 | 完整 fresh 列表，第二页点击也不只播放当前页 |
| 第二页选歌 | 后端给出全局位置与 GUID；fresh 列表不匹配时失败，避免静默播错 |
| 已保存 URI / 队列 | 原 URI 保留；新增页链接不可播放；底层音箱直接 resolve 仍只播放一首 |

后端提供 `.../page/2/100` 一类目录链接；卡片使用返回的链接，不拼接 NAS 地址，不向标准 HA 命令追加 `page` / `offset` 参数。原生浏览器将上一页／下一页显示为目录，卡片将其放到列表底部的翻页区。`feiniu_paging` 仅是返回结果中的展示信息，缓存不保存完整的带签名 BrowseMedia。

页响应还给出 `refresh_id`，可通过同一个标准浏览入口强制刷新；服务层也保留 `fresh=True`。没有新增第二套 WS 服务、客户端或权限模型。

## 并发、截止时间与失效

每个 runtime 自有缓存和 flight 字典；账号与生命周期通过实例及失效代次隔离。操作、分类、关系 ID、页码、页大小、搜索词参与各自 key。身份失效后清空可复用 flight 索引，旧任务写入和调用者接收结果时都检查代次。

- 同 key 普通读取共享一个任务，各等待者得到深拷贝；取消一个等待者不影响其他人，最后一个退出时取消并回收任务。
- 不同 key 最多 **4** 个 browse 作业运行；最多接纳 **32** 个尚未结束的作业，超过后明确失败，不无限排队。
- `fresh` 不使用旧缓存或旧 flight，且让同 key 旧任务无法回写。重登录、认证／权限拒绝、无效元数据和卸载清空相关元数据；旧响应不能复活访问证据。
- 页级浏览总预算 **25 秒**，完整枚举／搜索 **90 秒**。包括等待 browse 槽位、HTTP、节流、重新登录和分页；保持原有单次 HTTP 超时及独立 interactive/artwork/audio 通道。
- 90 秒用于保留完整列表的操作，不用于掩盖首屏串行枚举；50 页、每页 300 ms 的合成完整读取仍可以完成。顺序读页，不无限 `gather` 全库。
- 客户端解析秒数和 HTTP 日期格式 `Retry-After`，上限 **120 秒**；无效值使用有限默认值。它影响后续请求的等待，不自动无限重试；浏览总截止时间可先到期，取消和卸载能打断等待。
- 客户端及 runtime 跟踪各自任务；卸载回收排队、重新登录和响应中的工作，异常均被接收。

前端在切换时立即更换标题、清除旧数量，5 秒后给等待提示，最迟 95 秒显示错误和重试；这个兜底覆盖完整搜索 90 秒的后端预算。慢侧栏和图片不挡住主要文字。重复 `hass` 更新不会在失败后自动形成重试风暴。

标准 HA WS 没有单命令取消接口。前端 abort/epoch 只释放自己的等待、忽略过期结果，**不等于取消已经发到服务端的命令**。服务端仍依靠去重、并发上限和截止时间收敛工作。直接 runtime 调用者全部退出以及卸载，才会取消其实际共享任务。

## 缓存和授权边界

所有容量均按账号 runtime 或账号资源目录隔离，没有跨账号缓存。除已有图片资源外，元数据只存内存。

| 层 | 用途与上限 | TTL 起点 | 失效／访问规则 |
| --- | --- | --- | --- |
| 分类入口 | 静态四类，无远端缓存 | 无 | 根据当前有效条目生成 |
| 浏览页／完整列表／搜索展示 | 最多 16 个结果且合计 10,000 条紧凑记录 | 成功完整读取完成后 30 秒 | fresh、到期、容量淘汰、元数据失效、卸载；无 SWR、无过期兜底 |
| 单对象详情 | 128 条 | 请求观察开始时起 30 秒，重认证重试重新观察 | fresh 绕过；拒绝／协议异常／重登录／卸载清除 |
| 封面 owner 访问证据 | 最多 10,000 个 owner，记录精确 cover 关联 | 本次实际读取开始时起 30 秒；完整多页保守使用最早起点 | 缓存命中、组装、重绘和图片返回均不续期；缺失／过期时检查详情 |
| 歌词内容 | 32 首 | 原有请求开始时起 300 秒 | 每次先走上述详情访问检查；身份／元数据失效与卸载清除 |
| 原封面字节内存 | 32 MiB / 512 份 | 实际源图取回后 1 小时 | 使用前先校验 owner；命中不改变源图年龄；重登录／卸载清内存 |
| 图片资源／缩略图 | 内存 16 MiB / 512 份；磁盘 128 MiB / 2048 份；单份最多 8 MiB | 1 小时源图年龄；缩略图继承源图时间 | owner 校验在内存／磁盘读取之前；过期、损坏、容量淘汰；删除账号清其目录 |
| 图片失败短缓存 | 最多 512 个，只存异常类别 | 失败后 30 秒 | 不缓存凭据或异常正文；不替代权限校验 |
| HA 会话签名路径 | 最多 2048 个，按浏览器 issuer + path 区分 | 签名 30 分钟，提前 1 分钟换新 | 组装时按当前会话生成；重登录／元数据失效／卸载清映射；不在列表元数据里缓存 |
| 播放器封面 grant | 最多 128 个，绑定精确 owner/cover | 发放时起 2 小时 | 到期／卸载失效；每次依然校验 owner 当前权限 |
| 音频播放轮次 | 每个输出仅当前轮次 | 原有轮次生命周期 | 停止、换曲、撤销或卸载失效；起播 fresh 验权，不使用 browse 缓存授权 |

**展示数据年龄与权限证据年龄是两件事。** 例如读完整列表花了 31 秒，返回后展示缓存仍可复用 30 秒，但该次最早 owner 证据已经过期，图片访问需重新核实。展示缓存命中不刷新 owner 时间。`MAX_BROWSE_ROWS` 只是缓存预算；超出预算的合法完整结果仍返回，不变成曲库显示上限。

列表缓存保留显示及可播放性需要的标量、album/artists 简短引用和必要 audioSpec；不保存路径、标签、递归曲库对象或 HA 会话签名。旧图像像素留在磁盘不表示仍有访问权。

## MA 改进取舍

| 最终上游实现／原则 | HA 原有状态 | 本轮处理 | 验证 |
| --- | --- | --- | --- |
| 接口分别解释 accessStatus | 单曲 metadata 已严格处理 0/2/3；歌单未知状态曾被过滤 | 歌单只接受整数 0/2，拒绝缺失、bool、字符串、3 及未知值；服务端过滤且缺该字段的列表不强行要求它 | 歌单未知状态、过滤空原始页、重复 occurrence 用例 |
| 单对象读取不触发全库扫描 | 已有直读 detail 和 fresh 起播检查 | 保留原路径，不为同步上游重写 | 原生 resolve、详情、封面精确 owner 回归 |
| 紧凑元数据、逐页读取 | 原浏览先全量读完 | 采用 HA 独立字段白名单和页级服务 | 100/1000/5000 条调用数、递归字段剔除、内存测量 |
| 相同请求合并、结果副本 | 原来通过全局锁后的缓存复查去重 | 账户内按 key flight 和深拷贝，有界不同 key 并发 | 20 等待者、20/40 不同请求、单个／最后等待者取消 |
| 有界 Retry-After、资源关闭 | 有独立通道、缺有限头解析和等待任务清理 | 采用有限头解析及可取消生命周期；保留 HA 的通道和隔离 session | 日期／非有限值／上限、冷却／槽位等待时关闭 |
| 搜索显式限制、提前结束生成器 | HA 搜索入口未标明结果上限 | 不截断；仍完整读完并设总预算；客户端音频生成器关闭受生命周期管理 | 多页搜索、错误重试、流提前关闭回归 |
| 数据库缓存、SWR、MA models 与异常 | HA 无 MA 依赖 | 不移植，展示缓存也可能含私有元数据 | 失效、签名会话隔离、诊断隐私用例 |
| 全请求锁／节流和共享 session Cookie 修补 | HA 已有独立 session、DummyCookieJar、分通道限流 | 不覆盖现有设计，不引入 async-lru 依赖 | 请求通道及多账号回归 |
| seek、FFmpeg/CUSTOM stream、媒体预检优化 | HA 已有独立播放轮次与流交付实现 | 本轮无明确重复预检证据，不改流架构和播放状态机 | 原有播放、HTTP、轮次和队列测试继续执行 |
| #6680 setup-flow 错误翻译元数据 | HA 已有自己的异常与翻译 | 仅借鉴保留错误语义的原则，不移植 MA setup-flow 类 | 原生配置流程和诊断／日志回归 |

来源与 Apache-2.0 说明保留在 [NOTICE](../NOTICE)。没有引入已被评审替代的全库 membership 缓存方案，也没有照搬 OpenSubsonic 的 500 条页上限。

## 测量与回归

测量数据来自 `tests/test_browse_benchmark.py`。对照是当前保留的完整枚举服务（旧浏览路径必须完成的工作）与新增单页服务，**不是对旧二进制和生产 NAS 做 A/B 压测**。首个有用内容时间指 runtime 返回 100 条记录的时间，不包含浏览器绘制或音箱出声。请求计数是 fake client 的原生 API 调用数，不是网络抓包。

以下为 `e86723d` 的 [Actions 实测](https://github.com/neqq3/ha-feiniu-music/actions/runs/37179870161)，双版本后端、类型／格式检查、前端构建、单元测试、Chromium 和 WebKit 作业均通过。原始计数和分配峰值见 [测量 JSON](benchmarks/browse-2026-10-04.json)。后续消费者接收结果时的权限检查也在本测试分支运行同一完整矩阵；最新状态见 [本分支 Actions](https://github.com/neqq3/ha-feiniu-music/actions?query=branch%3Adev%2Fbrowse-performance-checks)。

| HA | 条数 | 单页模拟延迟 | 完整枚举 ms | 第一页 ms | 再次打开 ms | 原生请求：全量 → 首屏 → 热页 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2025.12.2 | 100 | 0 ms | 9.87 | 8.93 | 0.48 | 1 → 1 → 0 |
| 2025.12.2 | 1000 | 0 ms | 88.64 | 9.13 | 0.45 | 10 → 1 → 0 |
| 2025.12.2 | 5000 | 0 ms | 451.96 | 11.59 | 0.53 | 50 → 1 → 0 |
| 2025.12.2 | 100 | 300 ms | 311.39 | 311.25 | 0.66 | 1 → 1 → 0 |
| 2025.12.2 | 1000 | 300 ms | 3102.45 | 311.40 | 0.44 | 10 → 1 → 0 |
| 2025.12.2 | 5000 | 300 ms | 15518.53 | 313.04 | 0.46 | 50 → 1 → 0 |
| 2026.9.4 | 100 | 0 ms | 13.72 | 12.07 | 0.37 | 1 → 1 → 0 |
| 2026.9.4 | 1000 | 0 ms | 92.28 | 12.33 | 0.35 | 10 → 1 → 0 |
| 2026.9.4 | 5000 | 0 ms | 499.37 | 13.81 | 0.36 | 50 → 1 → 0 |
| 2026.9.4 | 100 | 300 ms | 315.74 | 314.33 | 0.37 | 1 → 1 → 0 |
| 2026.9.4 | 1000 | 300 ms | 3116.68 | 314.57 | 0.39 | 10 → 1 → 0 |
| 2026.9.4 | 5000 | 300 ms | 15622.56 | 316.13 | 0.40 | 50 → 1 → 0 |

5000 条慢后端案例中，Python 分配峰值由完整枚举的约 **9.7–9.8 MiB** 降为单页的约 **199–220 KiB**。这不是减少歌曲可见数量，而是首屏没有提前分配整库列表。

单次运行只作量化观察；确定性断言检查调用数、顺序、峰值并发、缓存命中和任务回收，不比较精确毫秒。

基准执行串行页读取，冷页峰值并发为 1，热页额外请求为 0、命中 1 次、结束后 flight 为 0。另有 20 个相同并发请求只读取一次、不同请求峰值 4、40 个独立请求最多接纳 32 个的事件驱动测试。不会把这些不同场景的并发数字混成一个基准值。

Python `tracemalloc` 同时用于冷完整枚举和冷单页阶段，只计这段代码的 Python 分配峰值，不代表 HA 进程 RSS、浏览器或 NAS 内存。热页时间不含 tracing。各 HA 版本的 runner、Python 和依赖不同，不把版本间的时差归因于某个 HA 改动。

本地浏览器检查使用 Edge；Actions 执行完整 Chromium 套件和 WebKit 浏览生命周期的触屏模拟。覆盖慢侧栏、慢封面、导航与账号切换、错误／超时重试、反复 `hass` 更新、组件移除再插入、关闭弹窗后晚到响应。没有实体 iOS WebView 现场结果。

## 诊断、隐私与交付边界

前一轮 `bdce18c` 的原生诊断改进也包含在本测试分支中，并参加相同兼容矩阵：

| 项目 | 原来 | 现在 |
| --- | --- | --- |
| 集成／runtime | 固定版本字符串、HA 版本、已创建播放器 | 从 HA loader 读取版本；条目状态与版本、runtime 是否初始化／关闭、代次、活跃音频轮次／请求数 |
| 地址 | 不提供连接上下文 | scheme、端口、标准路径；host 脱敏，仅保留进程内匿名关联值 |
| 输出 | 已创建代理的 platform、available | 遍历所有已配置输出，含未初始化／缺失绑定；registry、改名状态、原始 feature 整数及 PLAY_MEDIA/PLAY/PAUSE/STOP/SEEK/音量布尔能力 |
| 播放 | 已有 phase、reason、history 等 | 复用会话诊断，补充受控播放观察和流事件日志；不输出媒体身份或流 URL |
| 浏览 | 缺少耗时和工作量 | 本轮增加缓存、flight、排队／读取／组装和错误统计 |

DEBUG 边界包括配置登录开始／结果、登录响应结构错误阶段、输出验证原因、播放意图和解析／服务发送／返回／确认／结束等原有事件、状态观察变化、HEAD/GET/first-byte/EOF，以及本轮浏览观察。不记录每次进度／音量变化的重复状态，不提高正常播放的 INFO/WARNING 噪声。

Config Flow 使用 `OutputValidationError` 保留以下错误 key，并同步中英文：`output_not_media_player`、`output_self`、`output_missing_registry`、`output_unavailable`、`output_no_play_media`、`output_wrapper_loop`、`output_wrapped_feiniu`；未知错误仍为 `invalid_output`。缺少 PLAY_MEDIA 时说明该实体不能加载新的媒体，不只显示技术常量。

输出选择使用 HA 官方 `EntitySelectorConfig(filter={domain: media_player, supported_features: [media_player.MediaPlayerEntityFeature.PLAY_MEDIA]}, multiple=True)`；两个支持版本均核对和测试，后端 `validate_output` 继续独立验证。声明能力只是准入条件，不承诺音箱一定支持格式或能访问 HA 音频地址。

README 中英文同步补全连接地址、端口、音箱能力、加载、格式和日志反馈方法；不自动补 5666。Issue Form 要求发生阶段、版本、复现步骤、实际／预期结果与隐私勾选，提供 Diagnostics 附件说明和可选日志／截图，不要求用户填写设备唯一 ID 或内部 session 字段。小米相关说明仅保留已反馈的 OH2P / Miot play_control 个案，不推广到所有设备，也不新增适配。

Diagnostics 只读有界内存：最近 32 次浏览观察、累计计数上限 1,000,000、当前／峰值作业数、缓存条数。记录操作、种类、页码、返回条数、排队、读取、组装、总耗时和固定错误分类。`upstream_ms` 包括读取函数内的请求等待及逐页解析；`assembly_ms` 统计缓存副本和 owner 索引组装，不能把前者当成纯网络耗时。

日志和诊断不输出 flight key、原搜索词、账号名、设备 ID、曲名、完整 URL/query、Cookie、Authorization、authSig、授权 token、裸响应或异常正文。`client` 是此前诊断工作提供的进程内匿名关联值。下载诊断不会主动扫描曲库，日志和诊断不自动上传。首次配置失败没有 Diagnostics 时，仍按 README 使用 HA 原生 Logger 收集信息。

构建仍通过 `frontend/build.mjs` 生成内置卡片，`frontend.py` 用内容 hash 更新资源 URL。本轮不改最低 HA 版本，不变更发行版本号。公开账号／实体示例使用 `test`。测试分支只包含审阅过的代码、文档和合成测试；研究目录、真实凭据、HA 配置和现场日志未加入提交。

主要文件：`browse.py` 新增页值和行验证；`runtime.py` 管理分页、flight、缓存及失效；`media_source.py` / `selection.py` 管理标准浏览链接与全局队列位置；`client.py` 处理有限退避和关闭；`diagnostics.py` 接入浏览统计；前端源码与 `www` 构建产物实现翻页和加载恢复。对应测试位于 `test_browse_paging.py`、`test_browse_benchmark.py`、`test_client_backoff.py`、`test_media_source.py` 及 `frontend/browse-check.mjs`。诊断轮的 `support.py`、`output.py`、`config_flow.py`、`session.py`、翻译和 Issue Form 继续保留；没有借本轮改动队列核心算法。

## 已知限制与后续

- 歌单歌曲和搜索保留完整枚举；大列表播放全部也需要完整读取。它们可能比第一页慢，超过总预算会明确失败，不能称为所有入口均已分页。
- 服务器列表不提供快照版本；跨页浏览可能遇到正在变化的内容。播放时重新完整枚举并核对选中位置/GUID；不匹配则要求重新浏览，不能保证跨请求快照一致性。
- NAS 正确页大小上限仍按已验证的 100 处理；未知状态或不完整页明确失败，可能需要通过脱敏日志确认不同服务版本的协议差异。
- 本轮没有新的真实 NAS、用户故障现场、物理 iOS 设备或实际音箱听音数据。不宣称已定位所有“正在加载”或输出无声问题。
- 不做自动全库预取、数据库、SWR、转码、CUE、Xiaomi/MiNA 适配，也不修改起播与续播核心策略。

## 发布说明草稿（尚未发布）

- 曲库分类和专辑／歌手内容支持分页，首次打开只读取当前页。
- 侧栏歌单与封面不阻塞主要内容；重复请求合并，不同列表可有限并发。
- 修复快速切换、切换账号、关闭弹窗和断线后旧响应干扰页面的问题；加载失败可重试。
- 保持完整播放列表、第二页选曲位置和重复歌单歌曲；未知服务端状态明确提示失败。
- 增强 HA 原生 Diagnostics 的浏览耗时与错误分类，保持脱敏和短期权限校验。
- 最低版本继续为 HA 2025.12.2。

## 参考资料

HA 官方：[数据获取](https://developers.home-assistant.io/docs/integration_fetching_data/)、[Media player](https://developers.home-assistant.io/docs/core/entity/media-player/)、[Media source](https://developers.home-assistant.io/docs/core/platform/media_source/)、[Diagnostics](https://developers.home-assistant.io/docs/core/integration/diagnostics/)、[避免阻塞事件循环](https://developers.home-assistant.io/docs/asyncio_blocking_operations/)、[Web session](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/inject-websession/)。同时核对 core `2025.12.2`、`2026.9.4` 标签的 media_player/browse_media、media_source/models、sonos/favorites、plex/media_browser 原生模型／浏览实现。

MA 固定源码：[飞牛 provider](https://github.com/music-assistant/server/tree/2168c3a5db695e6de3878d41043ef76766d96c65/music_assistant/providers/feiniu_music)、[回归测试](https://github.com/music-assistant/server/tree/2168c3a5db695e6de3878d41043ef76766d96c65/tests/providers/feiniu_music)、[缓存控制器](https://github.com/music-assistant/server/tree/2168c3a5db695e6de3878d41043ef76766d96c65/music_assistant/controllers/cache)、[媒体基类](https://github.com/music-assistant/server/blob/2168c3a5db695e6de3878d41043ef76766d96c65/music_assistant/controllers/music/media/base.py)、[OpenSubsonic provider](https://github.com/music-assistant/server/blob/2168c3a5db695e6de3878d41043ef76766d96c65/music_assistant/providers/opensubsonic/sonic_provider.py)。另参考 [async-lru](https://github.com/aio-libs/async-lru) 的请求合并思路及 [OpenSubsonic 分页接口](https://opensubsonic.netlify.app/docs/endpoints/getalbumlist2/)，未机械引入其依赖或参数。
