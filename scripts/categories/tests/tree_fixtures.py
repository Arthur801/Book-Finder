"""Synthetic Eslite category tree shared by the eslite and CLI tests (data only, never executed)."""

from __future__ import annotations


def node(node_id: int, depth: int, description: str, children: list | None = None, **extra) -> dict:
    data = {"id": node_id, "depth": depth, "description": description, "children": children or [], "link": ""}
    data.update(extra)
    return data


def synthetic_tree() -> list[dict]:
    literature = node(
        28,
        2,
        "📌文學館79折起",
        [
            node(1001, 3, "小說"),
            node(1002, 3, "散文", link="https://www.eslite.com/exhibitions/CU202206-00348"),  # external link: skipped
            node(1003, 3, "品牌推薦", is_brand=True),  # brand page: skipped
            node(1004, 3, "  科幻 \t 小說\n"),  # whitespace is collapsed
        ],
    )
    promo = node(44444, 2, "📢雙11強檔推薦", [node(2001, 3, "雙11小說")])  # excluded level-2
    philosophy = node(61, 2, "人文史哲", [node(3001, 3, "哲學"), node(3002, 3, "小說")])  # 小說 also under 28
    return [
        node(1057, 1, "品牌旗艦", [node(5001, 2, "藝術在線", [node(5002, 3, "畫廊簡介")])]),
        node(3, 1, "中文書", [literature, promo, philosophy]),
    ]
