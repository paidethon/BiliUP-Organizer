"""Read-only reconnaissance of the production account's native groups.

Uses the app's own throttled client (cookies stay in the DB, never printed).
Prints tag inventory and finds a followed UP that belongs to >= 2 tags
(multi-group evidence). No writes.
"""

import time


def main() -> None:
    from app.db import get_session_factory
    from app.services.bilibili.native_groups import (
        list_tag_users,
        list_tags,
        user_tag_ids,
    )
    from app.services.bilibili.qrlogin import build_client

    db = get_session_factory()()
    client = build_client(db)
    try:
        tags = list_tags(db, client=client)
        print("tag_count", len(tags))
        members: dict[int, list[int]] = {}
        complete = True
        for tag in tags:
            mids, ok = list_tag_users(db, tag["bili_tag_id"], client=client)
            members[tag["bili_tag_id"]] = mids
            complete = complete and ok
            print(
                "tag",
                tag["bili_tag_id"],
                tag["bili_tag_name"],
                "members",
                len(mids),
                "read_complete",
                ok,
            )
            time.sleep(0.2)
        # a mid present in >= 2 tags = multi-group evidence
        seen: dict[int, list[int]] = {}
        for tag_id, mids in members.items():
            for mid in mids:
                seen.setdefault(mid, []).append(tag_id)
        multi = {mid: ids for mid, ids in seen.items() if len(ids) >= 2}
        print("multi_group_ups", len(multi))
        sample = dict(list(multi.items())[:5])
        for mid, ids in sample.items():
            live = user_tag_ids(db, int(mid), client=client)
            print("multi_sample", mid, "from_tag_scans", sorted(ids), "live_read_back", sorted(live))
        if not multi:
            # fall back: pick the most-followed mid and read its tags
            first = next((mid for mid, ids in seen.items() if ids), None)
            if first:
                print("single_group_sample", first, sorted(user_tag_ids(db, int(first), client=client)))
        print("all_reads_complete", complete)
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    main()
