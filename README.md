# 飞牛音乐 · Home Assistant

在 Home Assistant 中浏览飞牛音乐曲库，用已经接入 HA 的音箱播放。

自带音乐库、播放队列和歌词卡片。每台音箱都有独立队列，可以分别播放不同的音乐；也可以不用卡片，直接使用 HA 原生媒体浏览和自动化。

使用普通飞牛音乐账号连接，无需 Music Assistant 或 NAS 管理员权限。本项目为非官方集成，不修改 NAS 上的曲库和歌单。

## 安装

请使用 Home Assistant 2026.9.4 或更新版本，并先将音箱接入 HA。

### 通过 HACS 安装

1. 在 HACS 中添加自定义仓库：`https://github.com/neqq3/ha-feiniu-music`，类型选择 **Integration**。
2. 搜索并下载 **FeiNiu Music**，然后重启 Home Assistant。

### 手动安装

将本仓库的 `custom_components/feiniu_music` 文件夹复制到 HA 配置目录下的 `custom_components` 中，然后重启 HA。

## 连接飞牛音乐

1. 打开 **设置 → 设备与服务 → 添加集成**，搜索 **FeiNiu Music**。
2. 填写飞牛音乐地址，例如 `http://NAS地址:端口/music/`，以及音乐账号的用户名和密码。
3. 选择要使用的音箱。以后也可以在集成配置中增删。

配置完成后，每台选中的音箱会对应一个飞牛播放器实体。打开它的“浏览媒体”，即可按歌曲、专辑、歌手或歌单选曲。

要使用播放队列，请操作这个**飞牛播放器实体**。直接通过原始音箱实体浏览飞牛媒体源时，只会播放所选单曲。

## 添加音乐卡片

卡片随集成安装并自动注册，无需另外下载或手动添加 JavaScript 资源。

配置好集成后，刷新 HA 页面，在仪表盘的“添加卡片”中选择 **FeiNiu Music**，再用可视化编辑器选择飞牛播放器和喜欢的外观即可。卡片会随集成一起更新。

也可以使用 YAML，将 `entity` 换成自己的飞牛播放器实体：

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

如果你使用 YAML 管理仪表盘**资源**（`resource_mode: yaml`），需要自行在 `configuration.yaml` 的 `lovelace.resources` 中添加下面这项；已有 `lovelace` 配置时合并进去：

```yaml
lovelace:
  resource_mode: yaml
  resources:
    - url: /feiniu_music/feiniu-music-card.js?v=0.2.2
      type: module
```

只有资源由 YAML 管理时需要这一步，卡片配置使用 YAML 不受影响。升级后相应修改 `v` 参数并重载资源。

### 选择展示方式

**紧凑卡片**适合放在日常仪表盘上，有三种内容模式：

| 模式 | 显示内容 |
| --- | --- |
| 自动 | 有歌词时显示歌词，没有歌词时收起为精简播放器 |
| 精简播放器 | 封面、歌曲信息、播放控制和进度条 |
| 歌词播放器 | 保留歌词区，无歌词时显示提示 |

背景可以选择固定底色或随封面变化的氛围色；封面氛围下还可以选择柔和蒙版或通透玻璃。

点击封面进入歌曲播放页，右上角的展开按钮打开音乐库，队列按钮打开播放队列。

如果想单独做一个音乐页面，选择**完整界面**，并搭配 HA 的面板视图（`panel`）使用。完整配置示例见 [dashboard.yaml](examples/dashboard.yaml)。

### 歌词与队列

- 支持同步歌词和纯文本歌词。同步歌词可以点击文字居中，点击右侧时间按钮从那一句开始播放；纯文本歌词可以手动滚动阅读，但没有时间轴，不能自动跟随播放或按句跳转。
- 歌词不同步时，可以用提前／延后按钮调整，也可以在“播放与歌词设置”中输入偏移量。
- 队列支持追加、下一首播放、调整顺序、移除、随机和循环。这里的操作只影响播放队列，不会修改 NAS 歌单。
- 重启 HA 后会保留队列，点击播放即可继续；能否恢复到之前的进度取决于音箱是否支持定位。

## 音箱设置

不同音箱的起播和结束反馈可能不同。如果遇到加载后不播放、播完不切歌等情况，打开：

**设置 → 设备与服务 → 飞牛音乐 → 配置 → 起播与续播设置**

先选中对应的飞牛播放器，再调整起播确认、结束状态等选项。每台播放器单独保存设置，不需要安装卡片也能配置。

暂停、音量、进度跳转和音频格式支持取决于底层音箱及其 HA 集成。音频由音箱解码，本集成不提供转码。

## 常见问题

- **登录方式**：目前使用普通飞牛音乐账号登录，暂不支持 FN ID 和 NAS OAuth。
- **实体选择**：卡片应选择集成创建的飞牛播放器，而不是原始音箱实体。
- **无法跳转进度**：需要音箱及其 HA 集成支持定位。歌词时间按钮也使用同一能力。
- **更新后还是旧样式**：更新集成并重启 HA 后，刷新浏览器。资源版本会自动更新；使用 YAML 管理资源时需自行修改 `v` 参数。

升级集成前建议备份 HA。更多操作说明见 [使用说明](EXPERIENCE.md)；遇到问题可以到 [Issues](https://github.com/neqq3/ha-feiniu-music/issues) 反馈，附上 HA 版本、飞牛音乐版本、音箱型号和具体操作步骤。

## 开发与许可

构建和测试方法见 [TESTING.md](TESTING.md)，实现说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

项目使用 [Apache-2.0](LICENSE) 许可证。字体、品牌图案及代码来源说明见 [NOTICE](NOTICE)。

## English

An unofficial Home Assistant integration for FeiNiu Music. Browse your library, play through existing HA speakers, and manage a separate queue for each output. An optional dashboard card adds music browsing, playback controls and lyrics.

Add this repository to HACS as an **Integration**, install **FeiNiu Music**, and restart HA. Then add the integration under **Settings → Devices & services**, sign in with a regular music account, and select your speakers.

The bundled card registers and updates automatically. After setting up the integration, refresh your browser and add a **FeiNiu Music** card through the visual editor. Only YAML-managed dashboard resources require the manual resource entry above. Use the FeiNiu player entity, rather than the underlying speaker. See [examples/dashboard.yaml](examples/dashboard.yaml) for compact and full-page layouts.
