"""In-memory B+ tree for the score catalog's integer index keys."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from operator import attrgetter


@dataclass(frozen=True)
class Score:
    number: int
    title: str
    available_copies: int


@dataclass
class LeafPage:
    page_id: int
    entries: list[Score] = field(default_factory=list)
    next_leaf: 'LeafPage | None' = None


@dataclass
class InternalPage:
    page_id: int
    separators: list[int]
    children: list['Page']


Page = LeafPage | InternalPage
score_number = attrgetter('number')


@dataclass(frozen=True)
class Split:
    inserted_key: int
    page_type: str
    separator: int
    left_page: int
    right_page: int


@dataclass(frozen=True)
class LeafVisit:
    page_id: int
    first_key: int | None
    last_key: int | None
    matches: int


@dataclass
class RangeResult:
    descent: list[int]
    visits: list[LeafVisit]
    matches: list[tuple[int, Score]]
    range_checks: list[dict] = field(default_factory=list)


class BPlusTree:
    """Each page holds at most capacity keys, including internal separators."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.root: Page = LeafPage(1)
        self._next_page_id = 2
        self.splits: list[Split] = []

    def _allocate_page_id(self) -> int:
        page_id = self._next_page_id
        self._next_page_id += 1
        return page_id

    def insert(self, score: Score) -> None:
        split = self._insert(self.root, score)
        if split is not None:
            separator, sibling = split
            self.root = InternalPage(self._allocate_page_id(), [separator], [self.root, sibling])

    def _insert(self, page: Page, score: Score) -> tuple[int, Page] | None:
        if isinstance(page, LeafPage):
            index = bisect_left(page.entries, score.number, key=score_number)
            if index < len(page.entries) and page.entries[index].number == score.number:
                raise ValueError(f'曲谱编号 {score.number} 重复')
            page.entries.insert(index, score)
            if len(page.entries) <= self.capacity:
                return None

            midpoint = (len(page.entries) + 1) // 2
            sibling = LeafPage(self._allocate_page_id(), page.entries[midpoint:], page.next_leaf)
            del page.entries[midpoint:]
            page.next_leaf = sibling
            separator = sibling.entries[0].number
            self.splits.append(Split(score.number, '叶页', separator, page.page_id, sibling.page_id))
            return separator, sibling

        index = bisect_right(page.separators, score.number)
        split = self._insert(page.children[index], score)
        if split is None:
            return None
        separator, sibling = split
        page.separators.insert(index, separator)
        page.children.insert(index + 1, sibling)
        if len(page.separators) <= self.capacity:
            return None

        midpoint = len(page.separators) // 2
        promoted = page.separators[midpoint]
        right = InternalPage(
            self._allocate_page_id(), page.separators[midpoint + 1:], page.children[midpoint + 1:],
        )
        del page.separators[midpoint:]
        del page.children[midpoint + 1:]
        self.splits.append(Split(score.number, '内部页', promoted, page.page_id, right.page_id))
        return promoted, right

    def lookup(self, first: int, last: int) -> RangeResult:
        page = self.root
        descent = [page.page_id]
        while isinstance(page, InternalPage):
            page = page.children[bisect_right(page.separators, first)]
            descent.append(page.page_id)

        result = RangeResult(descent, [], [])
        offset = bisect_left(page.entries, first, key=score_number)
        leaf: LeafPage | None = page
        while leaf is not None:
            stop = bisect_right(leaf.entries, last, lo=offset, key=score_number)
            batch = leaf.entries[offset:stop]
            result.matches.extend((leaf.page_id, score) for score in batch)
            first_key = leaf.entries[0].number if leaf.entries else None
            last_key = leaf.entries[-1].number if leaf.entries else None
            result.visits.append(LeafVisit(leaf.page_id, first_key, last_key, len(batch)))
            if last_key is not None and last_key >= last:
                break
            leaf = leaf.next_leaf
            offset = 0
        result.range_checks = self._verify_range(first, last, result)
        return result

    def _verify_range(self, first: int, last: int, result: RangeResult) -> list[dict]:
        """巡检闭区间结果：边界闭合、编号升序、叶链连续，且与全量键集合一致。"""
        def row(item: str, passed: bool, basis: str) -> dict:
            return {'检查项': item, '判定': '通过' if passed else '失败', '依据': basis}

        checks: list[dict] = []
        keys = [score.number for _, score in result.matches]
        in_bounds = all(first <= key <= last for key in keys)
        checks.append(row('区间闭合', in_bounds,
                          f'命中 {len(keys)} 条，编号均落在闭区间 [{first}, {last}] 内（含两端）'))
        ordered = all(left < right for left, right in zip(keys, keys[1:]))
        checks.append(row('命中编号升序', ordered, '命中明细按编号严格递增排列'))
        first_leaf_matches = bool(result.visits) and result.visits[0].page_id == result.descent[-1]
        chain_steps = all(
            self._leaf_by_id(previous.page_id).next_leaf is self._leaf_by_id(current.page_id)
            for previous, current in zip(result.visits, list(result.visits)[1:]))
        tail = self._leaf_by_id(result.visits[-1].page_id) if result.visits else None
        tail_ok = tail is None or tail.next_leaf is None or (
            tail.entries and tail.entries[-1].number >= last)
        checks.append(row('叶链读取连续', first_leaf_matches and chain_steps and tail_ok,
                          f'自下探落点叶页起沿后继读取 {len(result.visits)} 个叶页，无跳页、尾页无越界读取'))
        expected = sorted(score.number for score in self._all_scores() if first <= score.number <= last)
        complete = expected == keys
        checks.append(row('范围结果完整', complete,
                          f'区间内全量登记 {len(expected)} 条，叶链命中 {len(keys)} 条，二者一致'))
        return checks

    def _leaf_by_id(self, page_id: int) -> LeafPage:
        page = self.root
        stack = [page]
        while stack:
            current = stack.pop()
            if isinstance(current, LeafPage):
                if current.page_id == page_id:
                    return current
            else:
                stack.extend(current.children)
        raise KeyError(page_id)

    def _all_scores(self) -> list[Score]:
        page = self.root
        while isinstance(page, InternalPage):
            page = page.children[0]
        scores: list[Score] = []
        leaf: LeafPage | None = page
        while leaf is not None:
            scores.extend(leaf.entries)
            leaf = leaf.next_leaf
        return scores

    def inspect(self, expected_count: int) -> tuple[list[dict], list[dict], int]:
        """Walk the child pointers, then verify that leaf links match that traversal."""
        pages: list[dict] = []
        leaves: list[LeafPage] = []
        leaf_depths: set[int] = set()
        seen_page_ids: set[int] = set()

        def require(condition: bool, reason: str) -> None:
            if not condition:
                raise RuntimeError(f'索引结构巡检失败：{reason}')

        def walk(page: Page, depth: int) -> tuple[int | None, int | None, int]:
            require(page.page_id not in seen_page_ids, f'页 {page.page_id} 被重复引用')
            seen_page_ids.add(page.page_id)
            is_root = page is self.root
            if isinstance(page, LeafPage):
                keys = [score.number for score in page.entries]
                minimum = 0 if is_root else (self.capacity + 1) // 2
                leaves.append(page)
                leaf_depths.add(depth)
                children = []
                next_leaf = page.next_leaf.page_id if page.next_leaf is not None else None
            else:
                keys = list(page.separators)
                minimum = 1 if is_root else self.capacity // 2
                children = [child.page_id for child in page.children]
                require(len(children) == len(keys) + 1, f'页 {page.page_id} 的子页数不匹配')
                next_leaf = None
            require(minimum <= len(keys) <= self.capacity, f'页 {page.page_id} 的键数越界')
            require(all(left < right for left, right in zip(keys, keys[1:])),
                    f'页 {page.page_id} 的键未严格递增')
            pages.append({
                '页号': page.page_id, '层级': depth, '根页': '是' if is_root else '否',
                '页类型': '叶页' if isinstance(page, LeafPage) else '内部页',
                '键数': len(keys), '最低键数': minimum, '键容量': self.capacity,
                '键列表': keys, '子页号': children, '下一叶页': next_leaf,
            })

            if isinstance(page, LeafPage):
                return (keys[0], keys[-1], len(keys)) if keys else (None, None, 0)

            spans = [walk(child, depth + 1) for child in page.children]
            for left, separator, right in zip(spans, keys, spans[1:]):
                require(left[1] is not None and left[1] < separator and right[0] == separator,
                        f'页 {page.page_id} 的分隔键 {separator} 与相邻子树边界不符')
            return spans[0][0], spans[-1][1], sum(span[2] for span in spans)

        first, last, count = walk(self.root, 1)
        require(len(seen_page_ids) == self._next_page_id - 1, '存在从根不可达的已分配页')
        require(len(leaf_depths) == 1, '所有叶页应位于同一层')
        require(count == expected_count, f'叶页共 {count} 条，输入 {expected_count} 条')
        for leaf, successor in zip(leaves, [*leaves[1:], None]):
            require(leaf.next_leaf is successor, f'页 {leaf.page_id} 的叶链后继不符')

        depth = next(iter(leaf_depths))
        extent = '空树' if first is None else f'{first} 至 {last}'
        checks = [
            {'检查项': '页可达性与占用', '判定': '通过', '依据': f'从根可达 {len(pages)} 页，键数均在各页上下限内'},
            {'检查项': '键序与分隔边界', '判定': '通过', '依据': f'全树键范围 {extent}，分隔键等于右侧子树最小键'},
            {'检查项': '叶页深度', '判定': '通过', '依据': f'{len(leaves)} 个叶页均在第 {depth} 层'},
            {'检查项': '叶页链', '判定': '通过', '依据': f'从叶页 {leaves[0].page_id} 依次覆盖 {len(leaves)} 页，尾页 {leaves[-1].page_id} 无后继'},
            {'检查项': '记录数守恒', '判定': '通过', '依据': f'录入 {expected_count} 条，叶页合计 {count} 条'},
        ]
        return pages, checks, depth
