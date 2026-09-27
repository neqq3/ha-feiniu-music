# 体验与恢复

1. 在「设置 → 设备与服务 → 飞牛音乐 → 配置」选择已有的 HA 音频输出。
   每个账号与输出组合对应一个固定播放器；不要选择飞牛播放器自身或已包含它的组。
2. 安装 README 的卡片资源，复制 `examples/dashboard.yaml`，替换成实际固定实体 ID。
3. 在卡片「选择音乐」里展开专辑、歌单、歌手歌曲或所有歌曲。
   「播放整个列表」开始连续播放；单曲的加号只追加这首；下一首加入不会立即发声。
   点歌曲直接播放会保留它的列表上下文。纯 media_source 直接投送仍是单曲能力。
4. 两个输出可同时拥有不同队列。队列中的重复歌曲是不同条目，可以分别移动、删除或跳转。
   随机只调整待播部分；手动下一首不会被单曲循环困住。
5. 暂停/恢复、音量和 seek 取决于输出支持。播放状态、HTTP 已交付与真实出声不是同一回事。
6. 歌词页区分无歌词、纯文本和同步歌词。设置里的秒数偏移只调整显示，不改变音频位置。
7. 重载集成或重启 HA 后，应恢复队列但不自动播放。点击播放才重新验权并请求恢复。
8. 起播失败时查看卡片诊断，确认原输出是否可用以及有无交付证据。默认不无限重试。
   兼容选项应按设备行为调整；PAUSED/OFF 当结束可能把用户暂停误判为自然结束。
9. 移除一个选中输出不应打断另一个；重新选择时保留原队列。删除账号则移除该账号队列。

升级/回滚请先备份集成、配置条目、实体注册表和本集成 Store。旧版本的内存队列无法恢复。
回滚应恢复匹配的旧代码与配置版本，不能只拷回旧 Python 文件。详细边界见 README。

## English

Select outputs in integration options, register the card module, and replace entity IDs in
`examples/dashboard.yaml`. Browse a list and play it, or add individual songs without starting
an empty queue. Each fixed output owns its queue, occurrence IDs, repeat/shuffle and lyric offset.
Reload restores queues idle; explicit Play revalidates access and requests supported native resume.
Inspect diagnostics when a device does not confirm playback. HTTP delivery is not proof of sound.
Back up both code and config/registry/storage before upgrading or rolling back.
