"""DEMO_MODE: synthetic dataset and stubbed external actions.

Demo mode lets the app run fully offline for development, e2e tests and
screenshots: no Bilibili/AI/SMTP/LumiRSS network calls are made, actions
return deterministic synthetic responses, and the DB is seeded on boot.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    AiSuggestion,
    BilibiliAccount,
    FeedToken,
    GroupLocal,
    Reminder,
    SyncRun,
    UpUser,
    Video,
    WatchHistory,
)
from app.schemas import BilibiliAccountOut
from app.util import utcnow

log = logging.getLogger(__name__)

rng = random.Random(20260929)

_GROUPS = [
    ("技术区", "#6366f1", 0, True, "编程、开源、科技资讯"),
    ("生活记录", "#10b981", 1, False, "Vlog 与日常"),
    ("游戏实况", "#f59e0b", 2, False, "游戏视频与直播回放"),
    ("音乐", "#ec4899", 3, False, "翻唱、原创与演奏"),
    ("知识科普", "#0ea5e9", 4, True, "科普、纪录片与课程"),
    ("吃灰区", "#71717a", 9, False, "长期未观看，待清理"),
]

_UPS = [
    # (uname, sign, group, follow_d, video_d, watched, watch_d, missing)
    ("何同学", "科技美学的极致追求", 0, 400, 12, 23, 5, False),
    ("老师好我叫何同学", "不定期更新", 0, 380, 90, 3, 120, False),
    ("稚晖君", "机器人工程师", 0, 500, 30, 41, 15, False),
    ("影视飓风", "Infinity HD", 0, 600, 3, 88, 2, False),
    ("极客湾", "芯片与数码评测", 0, 450, 60, 12, 60, False),
    ("在下哲别", "极限运动", 1, 200, 20, 5, 40, False),
    ("敬汉卿", "日常整活", 1, 700, 200, 2, 300, False),
    ("翔翔大作战", "美食与生活", 1, 300, 45, 7, 90, False),
    ("中国BOY超级大猩猩", "游戏与日常", 2, 550, 7, 34, 9, False),
    ("老番茄", "游戏区一哥", 2, 800, 15, 56, 20, False),
    ("某幻君", "游戏解说", 2, 520, 100, 1, 200, True),
    ("花少北", "游戏实况", 2, 490, 25, 18, 30, False),
    ("ilem", "VOCALOID 教父", 3, 900, 70, 44, 80, False),
    ("泡芙喵PuFF", "翻唱歌手", 3, 260, 35, 9, 100, False),
    ("Vic extant", "钢琴演奏", 3, 180, 12, 25, 6, False),
    ("罗翔说刑法", "法外狂徒张三", 4, 1000, 5, 66, 4, False),
    ("李永乐老师", "科普数学物理", 4, 900, 18, 52, 25, False),
    ("毕导THU", "硬核科普", 4, 650, 40, 30, 55, False),
    ("芳斯塔芙", "古生物科普", 4, 540, 55, 21, 70, False),
    ("无穷小亮", "网络热传生物鉴定", 4, 720, 8, 47, 3, False),
    ("吕永汉", "已停更大佬", 5, 800, 400, 0, None, True),
    ("早睡早起冠军", "从不更新的账号", 5, 350, 500, 0, None, False),
    ("数码闲聊站", "爆料数码", None, 90, 2, 15, 1, False),
    ("新关注的UP", "刚刚关注", None, 0, 1, 0, None, False),
]


def seed(db: Session) -> None:
    if db.query(UpUser).count() > 0:
        return
    log.info("demo mode: seeding synthetic dataset")
    now = datetime.now(UTC)
    groups: list[GroupLocal] = []
    for name, color, order, important, desc in _GROUPS:
        g = GroupLocal(name=name, color=color, sort_order=order, is_important=important, description=desc)
        db.add(g)
        groups.append(g)
    db.flush()

    account = db.get(BilibiliAccount, 1)
    if account is not None:
        account.mid = 20260929
        account.uname = "demo_user"
        account.avatar = ""
        account.login_status = "active"
        account.cookie_json = json.dumps({"SESSDATA": "demo", "bili_jct": "demo", "DedeUserID": "20260929"})
        account.cookie_updated_at = utcnow()

    for uname, sign, gidx, follow_days, video_days, watched, watch_days, missing in _UPS:
        last_video_at = (
            (now - timedelta(days=video_days)).strftime("%Y-%m-%d %H:%M:%S")
            if video_days is not None
            else None
        )
        last_watched = (
            (now - timedelta(days=watch_days)).strftime("%Y-%m-%d %H:%M:%S")
            if watch_days is not None
            else None
        )
        up = UpUser(
            mid=rng.randint(10_000_000, 99_999_999),
            uname=uname,
            sign=sign,
            face="",
            official_type=-1,
            special=bool(rng.getrandbits(1)),
            followed_at=(now - timedelta(days=follow_days)).strftime("%Y-%m-%d %H:%M:%S"),
            group_id=groups[gidx].id if gidx is not None else None,
            last_video_bvid=f"BV1demo{rng.randint(10**8, 10**9 - 1)}" if last_video_at else None,
            last_video_title=f"【{uname}】最新一期视频" if last_video_at else None,
            last_video_at=last_video_at,
            last_seen_at=utcnow()
            if not missing
            else (now - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S"),
            missing=missing,
            last_watched_at=last_watched,
            watched_count=watched,
            blacklisted=False,
        )
        db.add(up)
    db.flush()

    # memberships mirror the primary group; a few UPs get a second group so the
    # many-to-many behaviour is visible in the demo
    from app.models import GroupMember

    for up in db.query(UpUser).all():
        if up.group_id is not None:
            db.add(GroupMember(up_mid=up.mid, group_id=up.group_id))
    db.flush()
    multi = [u for u in db.query(UpUser).all() if u.group_id is not None][:3]
    for up in multi:
        other = next((g for g in groups if g.id != up.group_id), None)
        if other is not None:
            db.add(GroupMember(up_mid=up.mid, group_id=other.id))
    db.flush()

    ups = db.query(UpUser).all()
    for i, up in enumerate(ups):
        if up.last_video_at is None:
            continue
        base = datetime.strptime(up.last_video_at, "%Y-%m-%d %H:%M:%S")
        for k in range(3):
            pub = base - timedelta(days=7 * (k + 1) + i)
            db.add(
                Video(
                    bvid=f"BV1d{i:03d}{k:02d}{rng.randint(10**6, 10**7 - 1)}",
                    up_mid=up.mid,
                    title=f"【{up.uname}】第 {k + 1} 期投稿",
                    pubdate=pub.strftime("%Y-%m-%d %H:%M:%S"),
                    cover="",
                    duration=f"{rng.randint(3, 30)}:{rng.randint(10, 59)}",
                )
            )
        if up.watched_count:
            for k in range(min(up.watched_count, 4)):
                view = (now - timedelta(days=rng.randint(1, 120), hours=rng.randint(0, 23))).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                db.add(
                    WatchHistory(
                        bvid=f"BV1d{i:03d}{k:02d}{rng.randint(10**6, 10**7 - 1)}",
                        up_mid=up.mid,
                        title=f"【{up.uname}】观看记录 {k + 1}",
                        view_at=view,
                        progress=rng.randint(-1, 300),
                    )
                )

    low_conf_up = ups[1]
    db.add(
        AiSuggestion(
            up_mid=low_conf_up.mid,
            suggested_group_id=groups[0].id,
            suggested_group_name=groups[0].name,
            confidence=0.42,
            rationale="签名与科技相关但样本较少，置信度不足",
            model="demo-model",
            status="pending",
        )
    )
    db.add(
        AiSuggestion(
            up_mid=ups[6].mid,
            suggested_group_id=groups[1].id,
            suggested_group_name=groups[1].name,
            confidence=0.87,
            rationale="生活区创作者，历史观看集中于该分组",
            model="demo-model",
            status="pending",
        )
    )

    stale = ups[6]
    db.add(
        Reminder(
            rule_key="stale_uploader",
            severity="info",
            title=f"{stale.uname} 已 200 天未更新",
            body="自上次投稿以来已超过阈值，考虑取消关注或移入吃灰区。",
            entity_type="up",
            entity_id=str(stale.mid),
            dedup_key=f"stale_uploader:{stale.mid}:200",
        )
    )
    db.add(
        Reminder(
            rule_key="never_watched",
            severity="warning",
            title=f"{ups[21].uname} 从未观看",
            body="关注已久但没有任何观看记录。",
            entity_type="up",
            entity_id=str(ups[21].mid),
            dedup_key=f"never_watched:{ups[21].mid}",
        )
    )
    db.add(
        SyncRun(
            kind="followings",
            status="success",
            finished_at=utcnow(),
            stats_json=json.dumps({"total": len(_UPS), "new": len(_UPS)}),
        )
    )
    db.add(FeedToken(name="全部更新", token="demo-feed-token", group_id=None, max_items=50))
    db.commit()


def bilibili_account_stub(active: bool = True) -> BilibiliAccountOut:
    return BilibiliAccountOut(
        login_status="active" if active else "none",
        mid=20260929 if active else None,
        uname="demo_user" if active else None,
        avatar="",
        cookie_updated_at=utcnow() if active else None,
        risk_flag=False,
        cookie_masked="SESSDATA=••••; bili_jct=••••" if active else "",
    )


def qr_start() -> dict:
    return {"qrcode_key": f"demo-{utcnow()}", "qr_url": "https://demo.local/qr", "expires_at": utcnow()}


def qr_poll() -> dict:
    return {"status": "confirmed", "account": bilibili_account_stub()}


def sync_run(kind: str) -> dict:
    stats = {"total": len(_UPS), "new": 1, "updated": 3, "missing": 2, "demo": True}
    run = SyncRun(kind=kind, status="success", finished_at=utcnow(), stats_json=json.dumps(stats))
    return run


def review_run(batch_size: int) -> dict:
    return {"classified": min(batch_size, 5), "pending": 2, "demo": True}
