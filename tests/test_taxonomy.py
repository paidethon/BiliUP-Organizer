"""Unit tests for the taxonomy helpers (normalization, alias resolution,
merge/restore roundtrip, similar-name clustering)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, GroupAlias, GroupLocal, GroupMember, UpUser
from app.services import memberships, taxonomy


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_normalize_name() -> None:
    assert taxonomy.normalize_name("科技区") == "科技"  # generic suffix stripped
    assert taxonomy.normalize_name("科技 频道") == "科技"
    assert taxonomy.normalize_name("科技！") == "科技"  # punctuation dropped
    assert taxonomy.normalize_name("  Tech ") == "tech"  # NFKC + casefold
    assert taxonomy.normalize_name("") == ""
    assert taxonomy.normalize_name("区") == "区"  # too short to strip


def test_similar_names() -> None:
    assert taxonomy.similar_names("科技区", "科技")
    assert taxonomy.similar_names("科技数码", "数码科技")  # reordered compound
    assert taxonomy.similar_names("游戏", "游戏")
    assert not taxonomy.similar_names("游戏", "美食")
    assert not taxonomy.similar_names("", "科技")


def test_ensure_group_resolution_paths(db: Session) -> None:
    group, created = taxonomy.ensure_group(db, "科技数码")
    assert created is True and group is not None

    # exact-name hit
    same, created = taxonomy.ensure_group(db, "科技数码")
    assert same is not None and same.id == group.id and created is False

    # fuzzy near-duplicate resolves onto the existing group and auto-registers
    # an alias so the next occurrence matches exactly
    fuzzy, created = taxonomy.ensure_group(db, "数码科技")
    assert fuzzy is not None and fuzzy.id == group.id and created is False
    alias = db.query(GroupAlias).filter(GroupAlias.alias == "数码科技").first()
    assert alias is not None and alias.group_id == group.id and alias.source == "auto"
    exact_via_alias, _ = taxonomy.ensure_group(db, "数码科技")
    assert exact_via_alias is not None and exact_via_alias.id == group.id

    # explicit-alias hit: register one manually, then resolve through it
    db.add(GroupAlias(group_id=group.id, alias="数码区", source="manual"))
    db.commit()
    via_alias, created = taxonomy.ensure_group(db, "数码区")
    assert via_alias is not None and via_alias.id == group.id and created is False

    # no-create policy leaves unknown names unresolved
    missing, created = taxonomy.ensure_group(db, "绝不存在的分组xyz", allow_create=False)
    assert missing is None and created is False

    # creation path for genuinely new names
    fresh, created = taxonomy.ensure_group(db, "绝不存在的分组xyz")
    assert created is True and fresh is not None and fresh.name == "绝不存在的分组xyz"


def test_merge_and_restore_roundtrip(db: Session) -> None:
    # names chosen so the fuzzy matcher does NOT consider them near-duplicates
    src, _ = taxonomy.ensure_group(db, "源分组甲")
    dst, _ = taxonomy.ensure_group(db, "目标分组乙")
    assert src is not None and dst is not None and src.id != dst.id
    up1 = UpUser(mid=700000001, uname="合并UP一", group_id=src.id)
    up2 = UpUser(mid=700000002, uname="合并UP二", group_id=dst.id)
    db.add_all([up1, up2])
    db.flush()
    db.add(GroupMember(up_mid=up1.mid, group_id=src.id))
    db.add(GroupMember(up_mid=up1.mid, group_id=dst.id))  # dual membership
    db.add(GroupAlias(group_id=src.id, alias="源分组甲别名", source="manual"))
    db.commit()

    snapshot = taxonomy.merge_groups(db, src.id, dst.id)
    db.commit()
    db.expire_all()

    assert db.get(GroupLocal, src.id) is None  # source folded away
    up1 = db.query(UpUser).filter(UpUser.mid == 700000001).first()
    assert up1 is not None and up1.group_id == dst.id  # primary re-pointed
    assert memberships.group_ids_of(db, up1.mid) == [dst.id]
    assert "源分组甲别名" in taxonomy.aliases_of(db, dst.id)  # aliases moved
    assert "源分组甲" in taxonomy.aliases_of(db, dst.id)  # source name kept as alias
    assert snapshot["target_id"] == dst.id
    assert snapshot["member_mids"] == [up1.mid]

    taxonomy.restore_merged_group(db, snapshot)
    db.commit()
    db.expire_all()

    restored = db.query(GroupLocal).filter(GroupLocal.name == "源分组甲").first()
    assert restored is not None and restored.id != src.id  # recreated row, new id
    up1 = db.query(UpUser).filter(UpUser.mid == 700000001).first()
    assert up1 is not None and up1.group_id == restored.id  # primary restored
    assert restored.id in memberships.group_ids_of(db, up1.mid)  # membership re-added
    assert dst.id in memberships.group_ids_of(db, up1.mid)


def test_merge_groups_rejects_bad_targets(db: Session) -> None:
    src, _ = taxonomy.ensure_group(db, "校验源组")
    assert src is not None
    with pytest.raises(ValueError):
        taxonomy.merge_groups(db, src.id, src.id)
    with pytest.raises(ValueError):
        taxonomy.merge_groups(db, src.id, 999999)


def test_similar_group_clusters(db: Session) -> None:
    db.add_all(
        [
            GroupLocal(name="重复甲"),
            GroupLocal(name="甲重复"),  # same character multiset -> similar
            GroupLocal(name="完全不同"),
        ]
    )
    db.commit()
    clusters = taxonomy.similar_group_clusters(db)
    hit = [c for c in clusters if "重复甲" in [g.name for g in c]]
    assert hit and {"重复甲", "甲重复"} <= {g.name for g in hit[0]}
    assert all("完全不同" not in [g.name for g in c] for c in clusters)
