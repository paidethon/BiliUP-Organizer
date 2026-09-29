# Bilibili Web API 调研报告（BiliUP Organizer）

> 调研日期：2026-09-29
> 目的：为 BiliUP Organizer 的登录、关注列表同步、UP 主视频扫描、历史记录、关注分组管理等功能确定可用的 Bilibili Web API。

## 0. 资料来源与可靠性说明

- 首要资料来源：社区权威文档仓库 **SocialSisterYi/bilibili-API-collect**。
  - **注意**：原仓库 `SocialSisterYi/bilibili-API-collect` 已于 2026 年归档（archived），原 master 分支已删除，仅剩 `deprecated` 分支。
  - 本报告中所有 API 文档内容均从其**活跃贡献者复刻镜像 `pskdje/bilibili-API-collect`（master 分支，2026-01-25 与原仓库基础内容同步）** 逐字核实，镜像 URL 形如 `https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/...`。另一个活跃备份为 [BACNext/BACNext](https://github.com/BACNext/BACNext)。
- `bilibili-API-collect` 属**社区非官方文档**（逆向 + 抓包整理），B 站随时可能变更，无任何官方保证。
- 对未收录于 bilibili-API-collect 的端点（如历史记录搜索），用多个活跃开源项目（Bili23-Downloader、BewlyCat、PiliPlus、omniget）的实现代码交叉验证。
- 所有"未确认，需实测"条目在文中显式标注。

## 1. 通用约定

### 1.1 鉴权 Cookie

| Cookie | 作用 | 备注 |
| --- | --- | --- |
| `SESSDATA` | 登录态凭证 | HttpOnly + Secure，只能从 HTTP 响应头 `Set-Cookie` 读取，**不能**由 JS 读取；有效期约 1 个月（社区观察） |
| `bili_jct` | CSRF Token | 写操作（POST）时以表单参数 `csrf=...` 回传 |
| `DedeUserID` | 当前用户 mid | 配套 `DedeUserID__ckMd5` 校验值 |
| `buvid3` / `buvid4` / `b_nut` | 设备指纹 | 未携带易触发风控，见 §9 |

来源：[login_action/QR.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/login/login_action/QR.md)、[misc/buvid3_4.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/buvid3_4.md)

### 1.2 公共错误码（重点）

来源：[misc/errcode.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/errcode.md)

| code | 含义 | 处置建议 |
| --- | --- | --- |
| `0` | 成功 | — |
| `-101` | 账号未登录（或 SESSDATA 失效） | 触发重新登录流程 |
| `-111` | csrf 校验失败 | 检查 `csrf` 是否等于当前 `bili_jct` |
| `-352` | 风控校验失败（**UA 或 wbi 参数不合法**） | 检查 UA 是否浏览器级、wbi 签名是否正确；连续出现则停止并标记 |
| `-412` | 请求被拦截（**客户端 IP 被服务端风控**） | 立即停止请求、长冷却（分钟级以上）、标记账号/IP |
| `-799` | 请求过于频繁，请稍后再试 | 指数退避后重试 |
| `-400` | 请求错误 | 检查参数 |
| `22115` | 用户已设置隐私，无法查看（关注列表） | 跳过该用户 |

### 1.3 请求头基线（所有 api.bilibili.com 请求）

- `User-Agent`：浏览器级完整 UA（如 `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36`）。**UA 中不得包含 `python`、`curl` 等子串**，否则部分接口返回空列表/风控（见 §4、§9）。
- `Referer: https://www.bilibili.com/`；POST 另加 `Origin: https://www.bilibili.com`。
- Cookie 全量回传（buvid3/b_nut + SESSDATA 等），始终使用同一 cookie jar。

---

## 2. 扫码登录（QR Login）

来源：[docs/login/login_action/QR.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/login/login_action/QR.md)（"web端扫码登录"节）

### 2.1 申请二维码

- **方法/URL**：`GET https://passport.bilibili.com/x/passport-login/web/qrcode/generate`
- **参数**：无；**鉴权**：无（无需 Cookie）；**Wbi**：不需要
- **返回**（根 `code=0`）：
  - `data.url`：二维码内容（登录页 URL），用它生成二维码
  - `data.qrcode_key`：扫码登录秘钥，恒为 32 字符
- **有效期**：qrcode_key 超时 **180 秒**

### 2.2 轮询扫码状态

- **方法/URL**：`GET https://passport.bilibili.com/x/passport-login/web/qrcode/poll`
- **必需参数**：`qrcode_key`（str）
- **鉴权**：无；**Wbi**：不需要
- **返回关键字段**：
  - 根 `code` 恒为 `0`（HTTP 层成功）；**真正的状态在 `data.code`**：
    - `86101` 未扫码
    - `86090` 已扫码未确认
    - `86038` 二维码已失效（180s 超时）
    - `0` 登录成功
  - 成功时 `data.url` 为游戏分站跨域登录 URL（内含 `DedeUserID`、`SESSDATA`、`bili_jct` 等 query），`data.refresh_token` 可用于后续刷新，`data.timestamp` 为登录时间（毫秒）
- **Cookie 获取机制（关键）**：`data.code=0` 的那次 **poll 响应的 HTTP 响应头**直接携带：
  ```http
  set-cookie: SESSDATA=***; Path=/; Domain=bilibili.com; ...; HttpOnly; Secure
  set-cookie: bili_jct=***
  set-cookie: DedeUserID=***
  set-cookie: DedeUserID__ckMd5=***
  set-cookie: sid=***
  ```
  因此 HTTP 客户端**必须启用 cookie jar（自动捕获 Set-Cookie）**，登录成功后从 cookie jar 中读取 `SESSDATA`/`bili_jct`/`DedeUserID` 持久化。不要从 `data.url` 中手动解析（虽可行但非规范路径，且 SESSDATA 在 URL 中属敏感泄漏面）。
- **轮询建议**：每 2~3 秒一次（官方未规定，社区通行做法，需实测），180s 内未成功即放弃并重新生成二维码。
- 旧版 `passport.bilibili.com/qrcode/getLoginInfo` 接口**已失效**（恒返回 code 20000），勿用。

### 2.3 错误码
- HTTP 层 `code`：`0` 成功；`-412` 也有可能（IP 风控）。
- `data.code`：`86101`/`86090`/`86038`/`0`，见上。

---

## 3. Wbi 签名（w_rid / wts）

来源：[docs/misc/sign/wbi.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/sign/wbi.md)；研究出处 [issue #631](https://github.com/SocialSisterYi/bilibili-API-collect/issues/631)、更新 [#885](https://github.com/SocialSisterYi/bilibili-API-collect/issues/885)、[#919](https://github.com/SocialSisterYi/bilibili-API-collect/issues/919)

### 3.1 获取实时口令（img_key / sub_key）

- **方法/URL**：`GET https://api.bilibili.com/x/web-interface/nav`
- **鉴权**：可带 `SESSDATA`（登录可拿完整用户信息）；**未登录也返回 wbi key**（此时根 `code=-101`，`data.isLogin=false`，但 `data.wbi_img` 仍有效）。**Wbi**：不需要。
- **返回关键字段**：`data.wbi_img.img_url`、`data.wbi_img.sub_url` —— 值形如 `https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png`。**截取文件名即 key**（`7cd084941338484aae1ad9425b84077c`）。这两个"图片 URL"只是伪装的实时 Token，**不能也不需要访问**。
- **更替规律**：`img_key`/`sub_key` 全站统一、**观测为每日更替**；实现应做缓存 + 定时刷新（建议 ≤1 小时或每日过期）。
- 缺失/错误签名时接口返回 `v_voucher`（风控凭证提示），见 [misc/sign/v_voucher.md](https://github.com/pskdje/bilibili-API-collect/blob/master/docs/misc/sign/v_voucher.md)。

### 3.2 算法步骤

1. `raw_wbi_key = img_key + sub_key`（64 字符）。
2. 按置换表 `MIXIN_KEY_ENC_TAB`（长 64）逐位重排，**截取前 32 位**得 `mixin_key`。完整表（必须精确抄录）：
   ```
   46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
   27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
   37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
   22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
   ```
   校验用例（来自文档）：`img_key=7cd084941338484aae1ad9425b84077c`、`sub_key=4932caff0ff746eab6f01bf08b70ac45` → `mixin_key=ea1db124af3c7062474693fa704f4ff8`。
3. 复制原始请求参数，添加 `wts` = 当前**秒级** Unix 时间戳。
4. 参数按 **key 升序**排序；**过滤 value 中的 `!'()*` 五个字符**；URL 编码规则同 JS `encodeURIComponent`：保留 `A-Za-z0-9 - _ . ~`，其余转 `%XX` 且**十六进制字母大写**、空格编码为 `%20`（不能是 `+`）。
5. 拼接 `query + mixin_key` 取 **MD5** 得 `w_rid`。
6. 将 `wts`、`w_rid` 追加回原始请求 query（追加时不要求重新排序）。
7. 最终请求必须带上与签名一致的 `wts`/`w_rid`；`wts` 过旧（约 >1 分钟未实测确认）或 key 过期会导致 `-352`/`v_voucher`。

### 3.3 可照抄的 Python 实现

以下为 bilibili-API-collect 官方文档 `wbi.md` 的 Python Demo（依赖 `requests`），出处：
https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/sign/wbi.md （原出处 [SocialSisterYi/bilibili-API-collect wbi.md](https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/sign/wbi.md)）

```python
from functools import reduce
from hashlib import md5
import urllib.parse
import time
import requests

mixinKeyEncTab = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]


def getMixinKey(orig: str):
    "对 imgKey 和 subKey 进行字符顺序打乱编码"
    return reduce(lambda s, i: s + orig[i], mixinKeyEncTab, "")[:32]


def encWbi(params: dict, img_key: str, sub_key: str):
    "为请求参数进行 wbi 签名"
    mixin_key = getMixinKey(img_key + sub_key)
    curr_time = round(time.time())
    params["wts"] = curr_time  # 添加 wts 字段
    params = dict(sorted(params.items()))  # 按照 key 重排参数
    # 过滤 value 中的 "!'()*" 字符
    params = {k: "".join(filter(lambda chr: chr not in "!'()*", str(v))) for k, v in params.items()}
    query = urllib.parse.urlencode(params)  # 序列化参数
    wbi_sign = md5((query + mixin_key).encode()).hexdigest()  # 计算 w_rid
    params["w_rid"] = wbi_sign
    return params


def getWbiKeys() -> tuple[str, str]:
    "获取最新的 img_key 和 sub_key"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
        "Referer": "https://www.bilibili.com/",
    }
    resp = requests.get("https://api.bilibili.com/x/web-interface/nav", headers=headers)
    resp.raise_for_status()
    json_content = resp.json()
    img_url: str = json_content["data"]["wbi_img"]["img_url"]
    sub_url: str = json_content["data"]["wbi_img"]["sub_url"]
    img_key = img_url.rsplit("/", 1)[1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[1].split(".")[0]
    return img_key, sub_key


img_key, sub_key = getWbiKeys()
signed_params = encWbi(params={"foo": "114", "bar": "514", "baz": 1919810}, img_key=img_key, sub_key=sub_key)
query = urllib.parse.urlencode(signed_params)
```

**已知坑（文档正文明确警告，Demo 未处理）**：
- `urllib.parse.urlencode` 默认把空格编码为 `+` 且十六进制小写；规范要求空格为 `%20`、hex 大写（同 `encodeURIComponent`）。若参数值可能含空格/特殊字符，把 `urlencode(params)` 换成 `urllib.parse.quote` 逐键值对编码（`safe=''`）后自行 `&` 拼接，或对结果做 `+.replace('%2B', '%20')` 类修正——**具体以实测为准，未确认**。
- 整数/布尔参数先 `str()` 再过滤；`dict`/`list` 参数值需先序列化（本报告涉及接口均为标量，无此问题）。

---

## 4. 关注列表（followings）

来源：[docs/user/relation.md（"查询用户关注明细"）](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/relation.md)

- **方法/URL**：`GET https://api.bilibili.com/x/relation/followings`
- **必需参数**：`vmid`（目标用户 mid，查自己即自己的 mid）
- **可选参数**：`order_type`（留空=按关注时间；`attention`=最常访问，仅查自己时有效）、`ps`（每页项数，**默认 50**）、`pn`（页码，默认 1）
- **ps 上限**：文档仅写"默认为 50"，未明文写死上限；`ps>50` 是否被钳制**未确认，需实测**。BiliUP Organizer 一律按 `ps=50` 分页最稳妥。
- **鉴权**：Cookie（`SESSDATA`）。**Wbi**：不需要。
- **硬性风控条件（文档原文）**：只有**登录**、请求头 `referer` 为 `bilibili.com` 子域、**UA 不含 `python`** 时才会返回列表，三者缺一返回空 `list`（`code` 仍为 0）。
- **可见性限制**：自己可看全部；**其他用户仅可看前 100 个**（pn 超过时返回空 list、code=0）。
- **返回结构**：
  - `data.total`：关注总数
  - `data.re_version`：内部版本号（忽略）
  - `data.list[]`（关系列表对象）：
    - `mid`、`uname`（昵称）、`face`（头像 URL）、`sign`（签名）
    - `attribute`：`0` 未关注 / `2` 已关注 / `6` 已互粉 / `128` 已拉黑
    - `special`：`0` 否 / `1` 特别关注
    - `mtime`：关注时间（秒级时间戳，互关后刷新）
    - `tag`：所在分组 id 数组（默认分组为 `null`）
    - 其余：`official_verify{type,desc}`、`vip{...}`、`contract_info`、`face_nft` 等
- **错误码**：`-101` 未登录、`-352` 风控拦截、`-400` 请求错误、`22115` 对方隐私设置。
- **频率建议**：单账号翻页间隔 ≥2s（社区经验，未确认上限，需实测）；同步全部关注时按 `total/50` 估页数，逐页拉取并落库。

---

## 5. UP 主投稿视频列表（space arc search）

来源：[docs/user/space.md（"查询用户投稿视频明细"）](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/space.md)

- **方法/URL**：`GET https://api.bilibili.com/x/space/wbi/arc/search`
  - 旧版 `https://api.bilibili.com/x/space/arc/search` **已废弃**（文档保留仅为搜索定位）。
- **必需参数**：`mid`（目标 UP 主）
- **可选参数**：`order`（`pubdate` 最新发布【默认】/ `click` 最多播放 / `stow` 最多收藏）、`tid`（分区筛选，0=全部）、`keyword`（站内关键词过滤该 UP 主稿件）、`pn`（默认 1）、`ps`（每页项数，**默认 30**）
- **ps 上限**：文档未写死上限；任务书提到的 "`pn*ps≤100`" 类限制**官方文档未记载，未确认，需实测**。社区经验：带登录 Cookie 且 wbi 签名正确时 `ps=30` 分页最稳；建议 `ps=30`。
- **鉴权**：Cookie（建议携带 SESSDATA，可降低风控）；**Wbi：必须**（`w_rid` + `wts`，用 §3 算法对全部 query 参数签名）。
- **返回结构**：
  - `data.list.vlist[]`：
    - `bvid`、`aid`、`title`、`pic`（封面）
    - `created`：投稿时间（秒级时间戳）
    - `length`：时长字符串 `MM:SS`
    - `description`：视频简介（**注意字段名是 `description`，不是 `desc`**；任务书中写作 `desc` 系笔误）
    - `author`/`mid`：UP 主昵称/mid（合作视频时可能 ≠ 目标用户）
    - `play`（播放）、`video_review`（弹幕）、`comment`（评论）、`typeid`、`is_union_video`（合作）、`season_id`/`meta`（所属合集/课堂）
  - `data.page`：`count`（总稿件数）、`pn`、`ps` → 用于翻页终止判断
  - `data.list.tlist`：分区索引（可忽略）；`data.is_risk`：风险标记
- **错误码**：`-400` 请求错误、`-412` 请求被拦截（wbi 缺失/错误时高发）。
- **替代（无需 wbi）**：文档同节还有"查询用户投稿明细（APP、无需 wbi 鉴权）"端点（`app.biliapi.net`，接口稳定性差，仅作降级备选）。
- **频率建议**：同一 UP 主逐页间隔 ≥1.5~3s；扫描多个 UP 主时串行 + 随机延迟，见 §9。

---

## 6. 历史记录（History）

> ⚠️ 任务书中写的参数名 `business_type` 与实际不符：所有可查资料与三个独立开源实现使用的参数名均为 **`business`**。`business_type` 未见于任何文档/代码，**未确认，需实测**（可用一次真实请求验证后端是否兼容）。

### 6.1 搜索历史记录 `history/search`（社区非官方，未收录进 bilibili-API-collect）

- **方法/URL**：`GET https://api.bilibili.com/x/web-interface/history/search`
- **来源可靠性**：**不在** bilibili-API-collect 文档中（全仓检索无 `history/search`）。以下参数与字段由三个活跃项目代码交叉验证：
  - [ScottSloan/Bili23-Downloader `src/util/parse/parser/history.py`](https://github.com/ScottSloan/Bili23-Downloader/blob/main/src/util/parse/parser/history.py)：参数 `pn, keyword, business=archive, add_time_start=0, add_time_end=0, arc_max_duration=0, arc_min_duration=0, device_type=0, web_location=333.1391`
  - [BewlyCat `src/background/messageListeners/api/history.ts`](https://github.com/keleus/BewlyCat/blob/main/src/background/messageListeners/api/history.ts)：参数 `pn, keyword, business='all'`
  - [PiliPlus `lib/http/user.dart`](https://github.com/bggRGjQaUbCoE/PiliPlus/blob/master/lib/http/user.dart)：参数 `pn, keyword, business='all'`
  - [omniget `src-tauri/omniget-core/src/platforms/bilibili/parser/history.rs`](https://github.com/OpenSelena/omniget/blob/main/src-tauri/omniget-core/src/platforms/bilibili/parser/history.rs)：参数含 `pn, ps=20, keyword=, business=archive`
- **必需参数**：`pn`、`keyword`（可为空串）、`business`（`all`/`archive`/`live`/`article`/`article-list`/`pgc`；视频稿件用 **`archive`**）
- **可选参数**：`ps`（每页项数，上述项目用 20；上限未确认，需实测）、`add_time_start`/`add_time_end`（时间过滤，0=不限）、`arc_max_duration`/`arc_min_duration`（时长过滤，0=不限）、`device_type`（0）
- **鉴权**：Cookie（`SESSDATA`），**必须登录**。**Wbi**：上述项目均未签名；是否必须**未确认**（建议实测；如遇 `-352`/`v_voucher` 再补 wbi）。
- **返回结构**（与 §6.2 `history/cursor` 的列表项同构，Bili23/omniget 解析代码证实）：
  - `data.page.total`：总条数
  - `data.list[]`：
    - `title`（标题）、`long_title`（副标题/集数标题）、`cover`（封面 URL）、`uri`（重定向 URL）
    - **`view_at`**：观看时间（秒级时间戳）
    - **`progress`**：观看进度（秒；`-1` 表示看完）
    - `duration`（总时长秒；**0 视为稿件已失效**，Bili23/omniget 均按此判断）、`badge`、`show_title`（分 P/剧集标题）
    - `history` 对象：**`bvid`**（仅 archive 业务有值）、`oid`（archive 时=avid）、`cid`、`business`、`epid`（仅 pgc）、`page`、`part`、`dt`（观看平台）
    - 作者字段（顶层）：`author_name`（UP 主昵称）、`author_face`、`author_mid`——判断依据为同构的 cursor 接口文档字段表（§6.2），search 接口未逐字段实测，**需实测确认**
    - 其它：`is_fav`、`kid`、`tag_name`、`live_status`
- **错误码**：`-101` 未登录；风控类同 §9（`-412`/`-352` 可能出现，需实测）。

### 6.2 备选：官方文档化端点（建议作为降级/对照）

来源：[docs/historytoview/history.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/historytoview/history.md)

- **`GET https://api.bilibili.com/x/web-interface/history/cursor`**（web 端现行，游标式）
  - 参数：`ps`（默认 20，**最大 30**）、`type`（`all`/`archive`/`live`/`article`）、`view_at`+`max`+`business`（游标：取上一页 `data.cursor` 三值回传）
  - 鉴权：Cookie（SESSDATA）；无需 wbi
  - 返回：`data.list[]`（字段与 §6.1 相同，含 `history.bvid`、`view_at`、`progress`、`title`、`author_name/author_face/author_mid`——文档字段表明确记载）；错误码 `-101`/`-400`
- **`GET https://api.bilibili.com/x/v2/history`**（旧版，pn/ps 分页）
  - 返回 `data[]` 为完整稿件对象：`bvid`、`aid`、`title`、`pic`、`desc`、`view_at`、`progress`、`business`、`kid`，**作者在 `owner{mid,name,face}`**（注意与 search 的 `author_name` 命名不同）

### 6.3 建议
BiliUP Organizer 主用 §6.1（支持关键词/时间过滤、分页），降级用 §6.2 cursor 接口；两者都以"视频稿件"为目的时传 `business=archive` / `type=archive`。

---

## 7. 关注分组（Relation Tags）

来源：[docs/user/relation.md（"关注分组相关"）](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/relation.md)
> 以下均属**社区非官方文档**（逆向整理），POST 写操作风险高于读操作：参数变更无预告，可能因风控升级失效或触发账号异常。建议实现时对写操作做灰度 + 日志 + 幂等重试保护。

分组 id 特殊值：`0` 默认分组、`-10` 特别关心、`-20` 所有（仅查询分组明细时可用）。所有 POST 均为 `application/x-www-form-urlencoded`，`csrf` 参数取 **Cookie 中的 `bili_jct`**（即 `csrf=bili_jct` 的值；校验失败返回 `-111`）。

| 操作 | 方法/URL | 参数 | 返回/错误 |
| --- | --- | --- | --- |
| 列出分组 | `GET https://api.bilibili.com/x/relation/tags` | 无（Cookie 鉴权） | `data[]: {tagid, name, count, tip}`；`-101` |
| 分组成员 | `GET https://api.bilibili.com/x/relation/tag` | `tagid`（必要）、`order_type`、`ps`（默认 20）、`pn` | 成员列表（关系列表对象）；`22104` 分组不存在 |
| 用户所在分组 | `GET https://api.bilibili.com/x/relation/tag/user` | `fid` | `data` 为 `{分组id: 分组名}` 映射（默认分组不显示） |
| 特别关注 mid 列表 | `GET https://api.bilibili.com/x/relation/tag/special` | 无 | `data[]` 为 mid 数组 |
| **创建分组** | `POST https://api.bilibili.com/x/relation/tag/create` | `tag`（分组名，最长 16 字符）、`csrf` | `data.tagid`；`22101` 名称含非法字符 / `22102` 分组数量超限 / `22103` 过长 / `22106` 已存在 |
| 重命名分组 | `POST https://api.bilibili.com/x/relation/tag/update` | `tagid`、`name`、`csrf` | `22104` 不存在 |
| **删除分组** | `POST https://api.bilibili.com/x/relation/tag/del` | `tagid`、`csrf` | `0` 成功 |
| **把用户加入分组** | `POST https://api.bilibili.com/x/relation/tags/addUsers` | `fids`（mid 列表，逗号分隔）、`tagids`（分组 id 列表，逗号分隔，可多个）、`csrf` | `22104` 分组不存在 / `22105` **未关注该用户**（addUsers 不会自动关注，需先调 §7.1 关注）/ 移除成员时把 `tagids` 设为 `0`（移回默认分组），**不要用取关实现移除** |
| 复制到分组 | `POST https://api.bilibili.com/x/relation/tags/copyUsers` | `fids`、`tagids`、`csrf` | 同上 |
| 移动到分组 | `POST https://api.bilibili.com/x/relation/tags/moveUsers` | `beforeTagids`、`afterTagids`、`fids`、`csrf` | 同上 |

### 7.1 关联端点：关注/取关（配合 addUsers 使用）

来源：[docs/user/relation.md（"操作用户关系"）](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/relation.md)

- `POST https://api.bilibili.com/x/relation/modify`：参数 `fid`（目标 mid）、`act`（`1` 关注 / `2` 取关 / `5` 拉黑 / `6` 取消拉黑 / `7` 踢出粉丝）、`re_src`（来源代码，如 `11`=个人空间）、`csrf`。
- 错误码：`22009` 已达关注上限、`22014` 重复关注、`22002` 对方隐私限制、`22013` 账号已注销等。

### 7.2 风险标注
- `relation.md` 为社区文档，未覆盖：批量 fids/tagids 的数量上限（**未确认，需实测**；建议单次 ≤50）、写操作限频阈值。
- 写操作建议串行、间隔 ≥1s/次，失败不自动重试（除非明确幂等），避免重复建组/重复移动。

---

## 8. 用户信息卡（User Card）

来源：[docs/user/info.md（"用户名片信息"）](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/info.md)

- **方法/URL**：`GET https://api.bilibili.com/x/web-interface/card`
- **必需参数**：`mid`；可选 `photo`（bool，是否返回头图）
- **鉴权**：无需登录（未登录可用）；带 `SESSDATA` 时额外返回 `data.following`。**Wbi**：不需要。
- **返回关键字段**：
  - `data.card`：`mid`（str 型）、`name`（昵称）、`sex`、`face`（头像）、`sign`（签名）、`fans`（粉丝数）、`friend`/`attention`（关注数）、`level_info.current_level`（0-6 级）、`Official{role,title,desc,type}`（认证，`type=-1` 无认证）、`official_verify{type,desc}`、`vip{vipType,vipStatus}`、`space{s_img,l_img}`（头图）、`spacesta`（`0` 正常 / `-2` 封禁）
  - `data.following`：是否已关注（需登录 Cookie，未登录恒 false）
  - `data.archive_count`：稿件数；`data.follower`：粉丝数；`data.like_num`：获赞数
- **错误码**：`-400` 请求错误。
- **频率建议**：公开接口但同受全局风控，批量拉卡时同样要限流（§9）。

---

## 9. 风控与限流最佳实践

依据：[misc/errcode.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/errcode.md)、[misc/buvid3_4.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/buvid3_4.md)、[docs/user/relation.md](https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/relation.md)（followings 的 UA/Referer 条件）、[docs/video/action.md](https://github.com/pskdje/bilibili-API-collect/blob/master/docs/video/action.md)（"请求需 Cookie 中 buvid3 字段存在且正常，否则将导致触发风控"）

1. **请求头**：所有请求带浏览器级 `User-Agent`（同会话固定一个 UA，不要频繁更换）；`Referer: https://www.bilibili.com/`，POST 加 `Origin: https://www.bilibili.com`。UA 含 `python`/`curl` 子串会导致 followings 返回空列表、buvid 下发失败等。
2. **buvid3 初始化（三选一）**：
   - `GET https://www.bilibili.com/`（或 HEAD），从响应 `Set-Cookie` 取 `buvid3` + `b_nut`。要求 UA 不含敏感子串，且**同一 UA 不要短时多次请求**；
   - `GET https://api.bilibili.com/x/frontend/finger/spi` → `data.b_3`(buvid3)/`data.b_4`(buvid4)，需自行写入 cookie；
   - `GET https://api.bilibili.com/x/web-frontend/getbuvid` → `data.buvid`。
   拿到后放入 cookie jar 全程携带。
3. **会话一致性**：登录、wbi key、所有业务请求共用同一 cookie jar 与 UA；`SESSDATA` 失效（`-101`）时走重新登录，不要在失效后继续打业务接口。
4. **Wbi key 缓存**：nav 结果缓存（≤1h 或每日），签名失败（`-352`/`v_voucher`）时强制刷新一次 key 再重试一次。
5. **随机延迟**：翻页/批量请求间加随机 sleep（建议 1.5~3s，UP 主视频扫描 2~5s；数值为社区经验，**未确认，需实测**）。
6. **指数退避**：遇 `-799`/网络错误时按 `2^n * base + jitter` 退避，最多 3~5 次；`-799` 属明确限频，退避有效。
7. **硬熔断**：遇 `-412`（IP 风控）或连续 `-352`：**立即停止该账号/IP 的全部请求并标记**，冷却时间 ≥10 分钟（IP 风控解除时长无文档，**未确认，需实测**）；期间不得重试，避免加重风控。
8. **写操作**（分组、关注）串行低频执行，失败先检查 `-111`（csrf）与 `221xx` 业务码，不盲目重试。

---

## 10. QR 登录是否需要先访问主站拿 buvid3？

- **结论：非硬性要求，但强烈建议**。
  - `passport.bilibili.com/x/passport-login/web/qrcode/generate|poll` 接口本身不校验 Cookie：大量开源实现（如 [CrawlerTutorial 扫码示例](https://github.com/NanmiCoder/CrawlerTutorial)）在"可选携带 buvid3/buvid4"的前提下即可完成登录；社区文档 QR.md 的 curl 示例也未带 Cookie。
  - 但 B 站 gaia 风控体系以 buvid 为设备指纹：`video/action.md` 明确"Cookie 中 buvid3 不存在或异常会触发风控"；登录前先 `GET https://www.bilibili.com/` 取 `buvid3`/`b_nut`，并在 generate/poll 及后续业务请求中携带同一 cookie jar，可显著降低 `86101` 长期不变、poll 被拦截等异常概率。
  - **是否在缺失 buvid3 时会 100% 失败：未确认，需实测**。探测建议：同一 UA 下分别用"空 cookie"与"带 buvid3+b_nut"各完成一次完整扫码，对比 poll 轮询是否出现异常拦截。
- 轮询实现要点：2s 间隔；`data.code` 状态机（86101→86090→0 / 86038 失效重来）；成功后从 poll 响应 `Set-Cookie` 持久化 `SESSDATA`、`bili_jct`、`DedeUserID`、`DedeUserID__ckMd5`、`refresh_token`（JSON 字段）。

---

## 11. 实现建议清单（服务层设计）

### 11.1 应封装的函数（BilibiliClient / BilibiliService）

| 函数 | 对应端点 | 备注 |
| --- | --- | --- |
| `init_session()` | `GET www.bilibili.com` + `GET /x/frontend/finger/spi` | 拿 buvid3/buvid4/b_nut 入 jar，绑定固定 UA |
| `fetch_wbi_keys()` / `_cached` | `GET /x/web-interface/nav` | 缓存 ≤1h；`code in (0, -101)` 均可用 |
| `sign_wbi(params)` | 本地 | §3 算法；返回含 `w_rid/wts` 的新参数 |
| `qr_login(on_status)` | `passport .../qrcode/generate` + `/poll` | 状态机 86101/86090/86038/0；成功落盘 SESSDATA/bili_jct/DedeUserID/refresh_token |
| `check_login()` | `GET /x/web-interface/nav`（带 SESSDATA） | `data.isLogin` 校验，`-101` 触发重登 |
| `get_followings(vmid, pn, ps=50)` | `GET /x/relation/followings` | 返回 `(list, total)`；处理 22115 隐私 |
| `get_uploader_videos(mid, pn, ps=30, order='pubdate')` | `GET /x/space/wbi/arc/search` | wbi 必签；用 `data.page.count` 判终止；纠正字段 `description` |
| `search_history(keyword, pn, ps=20, business='archive')` | `GET /x/web-interface/history/search` | 降级 `history_cursor(type='archive')` |
| `history_cursor(type, view_at, max, business)` | `GET /x/web-interface/history/cursor` | ps≤30 游标翻页 |
| `list_relation_tags()` | `GET /x/relation/tags` | |
| `create_tag(name)` / `delete_tag(tagid)` | `POST /x/relation/tag/create` / `tag/del` | csrf=bili_jct |
| `add_users_to_tag(fids, tagids)` | `POST /x/relation/tags/addUsers` | 前置校验已关注（22105） |
| `follow_user(fid)` / `unfollow_user(fid)` | `POST /x/relation/modify` act=1/2 | |
| `get_user_card(mid)` | `GET /x/web-interface/card` | |

### 11.2 统一请求封装要点

- 单一 `_request(method, url, params, data, auth_required, wbi_required)` 入口：自动补 UA/Referer/Origin、cookie jar；`wbi_required` 时自动签名并处理 key 刷新；返回 JSON 后先判 `code`。
- 错误分类器：`-101`→`NeedRelogin`；`-111`→`CsrfError`；`-352`/`-412`→`RiskControl`（触发熔断）；`-799`→`RateLimited`（退避重试）；`22115`/`22105` 等业务码→`BizError` 透传。
- 重试/限流参数建议（初值，均需实测校准）：
  - 页间随机延迟 `uniform(1.5, 3.0)s`；UP 主视频扫描 `uniform(2, 5)s`；写操作串行 `≥1s`/次。
  - 退避：`base=2s`，`factor=2`，`jitter=±30%`，最多 3 次；仅对 `-799`/5xx/网络错误重试。
  - `-412` 或 2 次 `-352`：账号级熔断 ≥600s，并标记 `risk_flag` 拒绝后续任务直至人工/定时恢复。
  - 全局并发 = 1（单账号串行），任务队列化。
- Cookie 持久化字段：`SESSDATA`、`bili_jct`、`DedeUserID`、`DedeUserID__ckMd5`、`buvid3`、`buvid4`、`b_nut`、`refresh_token`；UA 与 cookie 同生命周期存储。
- 观测：对每次请求记录 `endpoint/code/耗时`，`-352/-412/-799` 计数用于自适应调大延迟。

### 11.3 未确认事项汇总（建议一次性实测脚本验证）

1. `history/search` 是否接受 `business_type`（而非 `business`）；`ps` 上限；作者字段 `author_name/author_mid` 是否存在。
2. `followings` `ps>50` 是否被钳制；`arc/search` 是否存在 `pn*ps≤100` 类限制。
3. `arc/search` 与 `history/search` 是否强制 wbi（遇 `v_voucher`/`-352` 即补签）。
4. 空 cookie 直接扫码登录的成功率 vs 先取 buvid3 的成功率；`-412` 后 IP 冷却时长。
5. `tags/addUsers` 的 fids/tagids 批量上限。

---

### 附：本报告引用源列表

- 镜像仓库（内容核实处）：https://github.com/pskdje/bilibili-API-collect （原仓库 https://github.com/SocialSisterYi/bilibili-API-collect 已归档，仅剩 deprecated 分支）
- 扫码登录：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/login/login_action/QR.md
- Wbi 签名：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/sign/wbi.md （issue #631 / #885 / #919）
- nav 端点：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/login/login_info.md
- 关系与分组：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/relation.md
- 投稿列表：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/space.md
- 历史记录：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/historytoview/history.md
- 用户名片：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/user/info.md
- 错误码：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/errcode.md
- buvid 获取：https://raw.githubusercontent.com/pskdje/bilibili-API-collect/master/docs/misc/buvid3_4.md
- history/search 交叉验证：https://github.com/ScottSloan/Bili23-Downloader/blob/main/src/util/parse/parser/history.py 、https://github.com/keleus/BewlyCat/blob/main/src/background/messageListeners/api/history.ts 、https://github.com/bggRGjQaUbCoE/PiliPlus/blob/master/lib/http/user.dart 、https://github.com/OpenSelena/omniget/blob/main/src-tauri/omniget-core/src/platforms/bilibili/parser/history.rs
- 扫码 + buvid 实践参考：https://github.com/NanmiCoder/CrawlerTutorial
