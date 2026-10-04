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
from app.services.taxonomy import set_status_labels, set_up_tags
from app.util import utcnow

log = logging.getLogger(__name__)

rng = random.Random(20260929)

_GROUPS = [
    ("科技数码", "#6366f1", 0, True, "数码产品、硬件与科技评测"),
    ("影像创作", "#10b981", 1, False, "摄影、摄像与后期制作"),
    ("游戏", "#f59e0b", 2, False, "游戏视频与实况"),
    ("音乐", "#ec4899", 3, False, "翻唱、原创与演奏"),
    ("知识科普", "#0ea5e9", 4, True, "科普、课程与知识分享"),
    ("生活娱乐", "#22c55e", 5, False, "日常与娱乐内容"),
    ("运动户外", "#f97316", 6, False, "运动、健身与户外"),
    ("美食生活", "#eab308", 7, False, "美食制作与探店"),
]

_UPS = [
    # (uname, sign, group_idx, follow_d, video_d, watched, watch_d, missing)
    ("何同学", "科技美学的极致追求", 0, 400, 12, 23, 5, False),
    ("老师好我叫何同学", "不定期更新", 0, 380, 90, 3, 120, False),
    ("稚晖君", "机器人工程师", 0, 500, 30, 41, 15, False),
    ("影视飓风", "Infinity HD", 1, 600, 3, 88, 2, False),
    ("极客湾", "芯片与数码评测", 0, 450, 60, 12, 60, False),
    ("在下哲别", "极限运动", 6, 200, 20, 5, 40, False),
    ("敬汉卿", "日常整活", 7, 700, 200, 2, 300, False),
    ("翔翔大作战", "美食与生活", 7, 300, 45, 7, 90, False),
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
    ("吕永汉", "已停更大佬", None, 800, 400, 0, None, True),
    ("早睡早起冠军", "从不更新的账号", None, 350, 500, 0, None, False),
    ("数码闲聊站", "爆料数码", 0, 90, 2, 15, 1, False),
    ("新关注的UP", "刚刚关注", None, 0, 1, 0, None, False),
]

# content tags applied through the taxonomy service (source="ai")
_TAGS_BY_UP_INDEX = {
    0: ["数码", "DIY"],  # 何同学
    2: ["机器人", "硬件", "工程"],  # 稚晖君
    3: ["摄影", "后期", "视频制作"],  # 影视飓风
    4: ["硬件", "芯片", "性能"],  # 极客湾
}

# explicit status labels on ungrouped/attention UPs
_LABELS_BY_UP_INDEX = {
    20: ["吃灰", "待整理"],  # 吕永汉
    21: ["吃灰", "待整理"],  # 早睡早起冠军
    23: ["新关注"],  # 新关注的UP
}


def _demo_previous_group(db: Session, up: UpUser) -> str | None:
    if up.group_id is None:
        return None
    group = db.get(GroupLocal, up.group_id)
    return group.name if group is not None else None


def _demo_evidence(db: Session, up: UpUser) -> dict:
    vids = db.query(Video).filter(Video.up_mid == up.mid).order_by(Video.pubdate.desc()).limit(3).all()
    count = db.query(Video.id).filter(Video.up_mid == up.mid).count()
    return {
        "video_count": count,
        "source": "db_cache",
        "sample_titles": [v.title[:20] for v in vids],
    }


def _demo_suggestion(
    db: Session,
    up: UpUser,
    *,
    group_id: int | None,
    group_name: str,
    tags: list[str],
    confidence: float,
    rationale: str,
    status: str,
) -> AiSuggestion:
    return AiSuggestion(
        up_mid=up.mid,
        suggested_group_id=group_id,
        suggested_group_name=group_name,
        suggested_tags=json.dumps(tags, ensure_ascii=False),
        previous_group_name=_demo_previous_group(db, up),
        evidence=json.dumps(_demo_evidence(db, up), ensure_ascii=False),
        confidence=confidence,
        rationale=rationale,
        model="demo-model",
        provider="demo",
        prompt_version="v2",
        status=status,
    )


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
                # half of the demo records land inside the current Shanghai
                # week so the weekly charts have real data in dev/e2e
                if k % 2 == 0:
                    view = now - timedelta(days=rng.randint(0, 6), hours=rng.randint(0, 23))
                else:
                    view = now - timedelta(days=rng.randint(7, 120), hours=rng.randint(0, 23))
                duration = rng.randint(90, 1800)
                progress = rng.choice([-1, rng.randint(0, duration)])
                db.add(
                    WatchHistory(
                        bvid=f"BV1d{i:03d}{k:02d}{rng.randint(10**6, 10**7 - 1)}",
                        up_mid=up.mid,
                        title=f"【{up.uname}】观看记录 {k + 1}",
                        view_at=view.strftime("%Y-%m-%d %H:%M:%S"),
                        progress=progress,
                        duration_seconds=duration,
                    )
                )

    for idx, tag_names in _TAGS_BY_UP_INDEX.items():
        set_up_tags(db, ups[idx].mid, tag_names, source="ai")
    for idx, labels in _LABELS_BY_UP_INDEX.items():
        set_status_labels(db, ups[idx].mid, labels, source="manual")

    he_class = ups[1]  # 老师好我叫何同学: low-confidence pending suggestion
    db.add(
        _demo_suggestion(
            db,
            he_class,
            group_id=groups[0].id,
            group_name=groups[0].name,
            tags=["数码", "测评"],
            confidence=0.42,
            rationale="签名与科技相关但样本较少，置信度不足",
            status="pending",
        )
    )
    hanqing = ups[6]  # 敬汉卿: high-confidence pending suggestion
    db.add(
        _demo_suggestion(
            db,
            hanqing,
            group_id=groups[7].id,
            group_name=groups[7].name,
            tags=["美食", "Vlog"],
            confidence=0.87,
            rationale="美食生活创作者，历史观看集中于该分组",
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


_DEMO_GROUP_CYCLE = ("科技数码", "影像创作", "游戏", "音乐", "知识科普")
_DEMO_TAG_CYCLE = ("数码", "测评", "Vlog", "硬件", "游戏")


def demo_classify_batch(
    db: Session, mids: list[int], auto_apply: bool = False, threshold: float = 0.9
) -> dict:
    """Deterministic offline stand-in for ai_classifier.classify_batch.

    The branch depends only on mid arithmetic so every path is reproducible:
    mid%17==0 -> failure path (ai_status=error), mid%5==0 -> unclassifiable,
    mid%3==0 -> pending review, otherwise high confidence (applied when
    auto_apply is set). Never touches the network.
    """
    from app.services import memberships
    from app.services.taxonomy import clear_status_labels, ensure_group

    result: dict = {
        "classified": 0,
        "auto_applied": 0,
        "needs_review": 0,
        "unclassifiable": 0,
        "failed": 0,
        "created_groups": [],
    }
    for i, mid in enumerate(mids):
        up = db.query(UpUser).filter(UpUser.mid == mid).first()
        if up is None:
            result["failed"] += 1
            continue
        # same idempotency rule as the real classifier: replace open
        # suggestions instead of stacking duplicates on re-runs
        db.query(AiSuggestion).filter(
            AiSuggestion.up_mid == mid,
            AiSuggestion.status.in_(("pending", "unclassifiable")),
        ).delete(synchronize_session=False)
        if mid % 17 == 0:
            up.ai_status = "error"
            result["failed"] += 1
            continue
        if mid % 5 == 0:
            db.add(
                _demo_suggestion(
                    db,
                    up,
                    group_id=None,
                    group_name="",
                    tags=[],
                    confidence=0.4,
                    rationale="内容信号不足，无法确定分组",
                    status="unclassifiable",
                )
            )
            up.ai_status = "done"
            set_status_labels(db, up.mid, ["待整理"], source="ai")
            result["unclassifiable"] += 1
            continue
        if mid % 3 == 0:
            confidence = 0.65 + (mid % 25) / 100
            name = _DEMO_GROUP_CYCLE[i % len(_DEMO_GROUP_CYCLE)]
            tags = list(_DEMO_TAG_CYCLE[: mid % 4])
            group, _created = ensure_group(db, name)
            db.add(
                _demo_suggestion(
                    db,
                    up,
                    group_id=group.id if group else None,
                    group_name=group.name if group else name,
                    tags=tags,
                    confidence=confidence,
                    rationale="近期投稿与该分组相关，但置信度一般",
                    status="pending",
                )
            )
            up.ai_status = "pending"
            result["needs_review"] += 1
            result["classified"] += 1
            continue
        confidence = 0.9 + (mid % 10) / 100
        name = _DEMO_GROUP_CYCLE[i % len(_DEMO_GROUP_CYCLE)]
        tags = list(_DEMO_TAG_CYCLE[: mid % 4])
        group, created = ensure_group(db, name)
        if group is None:
            result["failed"] += 1
            continue
        if created:
            result["created_groups"].append(group.name)
        suggestion = _demo_suggestion(
            db,
            up,
            group_id=group.id,
            group_name=group.name,
            tags=tags,
            confidence=confidence,
            rationale="近期投稿主题明确，归属该分组",
            status="pending",
        )
        db.add(suggestion)
        if auto_apply and confidence >= threshold:
            up.group_id = group.id  # primary
            memberships.add_membership(db, up, group.id)
            if tags:
                set_up_tags(db, up.mid, tags, source="ai")
            clear_status_labels(db, up.mid, ["待整理", "无法确定"])
            up.ai_status = "done"
            suggestion.status = "accepted"
            suggestion.decided_at = utcnow()
            result["auto_applied"] += 1
        else:
            up.ai_status = "pending"
            result["needs_review"] += 1
        result["classified"] += 1
    db.commit()
    return result


def review_run(batch_size: int) -> dict:
    """Offline /review/run: deterministic suggestions for the next batch."""
    from app.db import get_session_factory

    db = get_session_factory()()
    try:
        mids = [
            row[0]
            for row in (
                db.query(UpUser.mid)
                .filter(UpUser.ai_status.in_(("none", "error")), UpUser.missing.is_(False))
                .order_by(UpUser.followed_at.asc(), UpUser.mid.asc())
                .limit(batch_size)
                .all()
            )
        ]
        return demo_classify_batch(db, mids)
    finally:
        db.close()
