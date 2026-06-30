"""临时脚本：显示自选股 + 半导体产业链行情快照。"""
import json
from datetime import datetime
from pathlib import Path

from mommy_chaogu.semicon import SemiconStore
from mommy_chaogu.watchlist import WatchlistStore

DB_DIR = Path("data")


def main() -> None:
    snap = json.loads((DB_DIR / "quote_snapshot.json").read_text())
    quotes = snap["quotes"]
    ts = datetime.fromtimestamp(snap["ts"]).strftime("%H:%M:%S")
    quote_map = {q["code"]: q for q in quotes if q.get("change_pct") is not None}

    watch = WatchlistStore(DB_DIR / "watchlist.db")
    semi = SemiconStore(DB_DIR / "semicon.db")
    watch_codes = {e.code for e in watch.list_entries()}
    semi_list = semi.list_all()

    print(f"⏰ {ts}  行情快照（腾讯接口）  共 {len(quote_map)} 只\n")

    print("=" * 70)
    print("📌 自选股")
    print("=" * 70)
    for c in sorted(watch_codes):
        q = quote_map.get(c)
        if not q:
            print(f"⚪ {c} (无行情)")
            continue
        price = q.get("price") or 0
        pct = q.get("change_pct") or 0
        cap = (q.get("circulating_market_cap") or 0) / 1e8
        vr = q.get("volume_ratio") or 0
        arrow = "🟢" if pct > 0 else ("🔴" if pct < 0 else "⚪")
        print(
            f"{arrow} {q['name']:8s} {c} 现:{price:>8.2f}  {pct:+6.2f}%  "
            f"量比:{vr:>5.2f}  流通:{cap:>7.0f}亿"
        )

    print("\n" + "=" * 70)
    print("🔬 半导体产业链 — 板块汇总")
    print("=" * 70)
    for pos in ["上游", "中游", "下游", "末端"]:
        codes_in_pos = [s.code for s in semi_list if str(s.chain_position) == pos]
        hit = [c for c in codes_in_pos if c in quote_map]
        if not hit:
            continue
        pcts = [quote_map[c]["change_pct"] for c in hit]
        avg = sum(pcts) / len(pcts)
        up_n = sum(1 for p in pcts if p > 0)
        down_n = sum(1 for p in pcts if p < 0)
        emoji = "🔥" if avg > 0.5 else ("📉" if avg < -0.5 else "➖")
        print(
            f"{emoji} 【{pos}】 {len(hit)}/{len(codes_in_pos)} 只  "
            f"均价 {avg:+.2f}%  涨{up_n}跌{down_n}"
        )

    print("\n" + "=" * 70)
    print("🔬 半导体产业链 — 每板块表现（按涨跌幅排序）")
    print("=" * 70)
    for pos in ["上游", "中游", "下游", "末端"]:
        print(f"\n--- {pos} ---")
        items: list[tuple[float, object, dict | None, str]] = []
        for s in semi_list:
            if str(s.chain_position) != pos:
                continue
            q = quote_map.get(s.code)
            pct = q["change_pct"] if q else 0.0
            arrow = "🟢" if pct > 0 else ("🔴" if pct < 0 else "⚪")
            items.append((pct, s, q, arrow))
        items.sort(key=lambda x: -x[0])
        for pct, s, q, arrow in items:
            tag = "👀" if s.code in watch_codes else "  "
            if not q:
                print(f"  {arrow} {tag} {s.name[:10]:10s} {s.code} (无行情)")
                continue
            price = q.get("price") or 0
            cap = (q.get("circulating_market_cap") or 0) / 1e8
            vr = q.get("volume_ratio") or 0
            print(
                f"  {arrow} {tag} {s.name[:10]:10s} {s.code} "
                f"现:{price:>8.2f} {pct:+6.2f}% 量比:{vr:>5.2f} 流通:{cap:>6.0f}亿"
            )


if __name__ == "__main__":
    main()
