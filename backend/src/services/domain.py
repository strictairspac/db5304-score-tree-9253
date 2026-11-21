"""Build and inspect a lending catalog index for one submitted batch."""

from .score_tree import BPlusTree, Score


SPEC = {
    'name': '榆弦谱库·曲谱目录页索引',
    'summary': '按曲谱编号圈定团借范围，划出可拣配和需候补的曲谱，并巡检目录索引。',
    'customer': '榆弦社区音乐中心 · 曲谱流通组',
    'entity_labels': ['曲目索引批', '索引巡检', '范围借阅单'],
    'field_labels': {
        'page_capacity': '页容量（最大键数）',
        'range_start': '起始曲谱编号（含）',
        'range_end': '结束曲谱编号（含）',
        'scores': '曲谱目录',
        'number': '曲谱编号',
        'title': '谱名',
        'available_copies': '可借份数',
    },
    'guidance': '按目录到达顺序录入曲谱，编号须唯一。设置每页最大键数和含首尾的编号区间，再核对页分裂、巡检和借阅明细。',
    'sample': {
        'page_capacity': 3,
        'range_start': 1204,
        'range_end': 1212,
        'scores': [
            {'number': 1209, 'title': '江湾晨曲', 'available_copies': 2},
            {'number': 1205, 'title': '松影三重奏', 'available_copies': 3},
            {'number': 1214, 'title': '旧街进行曲', 'available_copies': 2},
            {'number': 1201, 'title': '纸鸢圆舞曲', 'available_copies': 1},
            {'number': 1218, 'title': '河岸序奏', 'available_copies': 0},
            {'number': 1212, 'title': '灯塔小步舞曲', 'available_copies': 1},
            {'number': 1204, 'title': '榆荫弦乐合奏', 'available_copies': 2},
            {'number': 1210, 'title': '竹桥间奏', 'available_copies': 0},
            {'number': 1207, 'title': '溪畔变奏曲', 'available_copies': 0},
            {'number': 1216, 'title': '雾中五重奏', 'available_copies': 4},
            {'number': 1202, 'title': '长廊二重奏', 'available_copies': 2},
            {'number': 1208, 'title': '北窗练习曲', 'available_copies': 1},
            {'number': 1211, 'title': '稻穗随想曲', 'available_copies': 3},
            {'number': 1217, 'title': '晚汐重奏', 'available_copies': 1},
            {'number': 1203, 'title': '石阶小夜曲', 'available_copies': 1},
            {'number': 1213, 'title': '晴堤短歌', 'available_copies': 2},
            {'number': 1219, 'title': '远山终曲', 'available_copies': 2},
        ],
    },
    'expect': {
        '区间命中曲谱': 8,
        '可拣配曲谱': 6,
        '区间可借份数': 12,
        '叶页分裂': 6,
        '内部页分裂': 1,
        '树高': 3,
        '扫描叶页': 4,
    },
}


def _integer(value, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label}必须为 {minimum} 至 {maximum} 之间的整数')
    return value


def _read_payload(payload) -> tuple[int, int, int, list[Score]]:
    if not isinstance(payload, dict):
        raise ValueError('请提交曲目索引批对象')
    capacity = _integer(payload.get('page_capacity'), 2, 128, '页容量')
    first = _integer(payload.get('range_start'), 1, 999_999_999, '起始曲谱编号')
    last = _integer(payload.get('range_end'), 1, 999_999_999, '结束曲谱编号')
    if first > last:
        raise ValueError('起始曲谱编号须小于或等于结束曲谱编号')

    rows = payload.get('scores')
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('曲谱目录须为数组，每批最多 5000 条')
    scores = []
    numbers = set()
    for index, row in enumerate(rows, 1):
        label = f'第 {index} 条曲谱的'
        if not isinstance(row, dict):
            raise ValueError(f'第 {index} 条曲谱须为对象')
        number = _integer(row.get('number'), 1, 999_999_999, f'{label}编号')
        if number in numbers:
            raise ValueError(f'第 {index} 条曲谱的编号 {number} 重复')
        title = row.get('title')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ValueError(f'{label}谱名去除首尾空白后须为 1 至 120 字符')
        available = _integer(row.get('available_copies'), 0, 9999, f'{label}可借份数')
        scores.append(Score(number, title.strip(), available))
        numbers.add(number)
    return capacity, first, last, scores


def validate(payload) -> None:
    _read_payload(payload)


def solve(payload, engine):
    """Rebuild an isolated logical index. The application owns persistence."""
    capacity, first, last, scores = _read_payload(payload)
    tree = BPlusTree(capacity)
    for score in scores:
        tree.insert(score)

    pages, checks, height = tree.inspect(len(scores))
    result = tree.lookup(first, last)
    lending_rows = [
        {'曲谱编号': score.number, '谱名': score.title, '可借份数': score.available_copies,
         '借阅判定': '可拣配' if score.available_copies else '候补', '叶页号': page_id}
        for page_id, score in result.matches
    ]
    found = len(lending_rows)
    ready = sum(score.available_copies > 0 for _, score in result.matches)
    copies = sum(score.available_copies for _, score in result.matches)
    leaf_splits = sum(split.page_type == '叶页' for split in tree.splits)
    visit_rows = [
        {'顺序': index, '叶页号': visit.page_id, '最小编号': visit.first_key,
         '最大编号': visit.last_key, '本页命中': visit.matches}
        for index, visit in enumerate(result.visits, 1)
    ]
    split_rows = [
        {'顺序': index, '触发插入编号': split.inserted_key, '分裂页类型': split.page_type,
         '上送分隔键': split.separator, '原页号': split.left_page, '新页号': split.right_page}
        for index, split in enumerate(tree.splits, 1)
    ]
    interval = f'编号 {first} 至 {last} 的范围内'
    summary = f'{interval}未找到登记曲谱。'
    if found:
        summary = f'{interval}命中 {found} 种曲谱，{ready} 种可拣配共 {copies} 份，{found - ready} 种候补。'
    return {
        'summary': summary,
        'metrics': {
            '区间命中曲谱': found, '可拣配曲谱': ready, '候补曲谱': found - ready,
            '区间可借份数': copies, '树高': height, '根页号': tree.root.page_id,
            '页数': len(pages), '叶页分裂': leaf_splits,
            '内部页分裂': len(tree.splits) - leaf_splits, '扫描叶页': len(result.visits),
        },
        'sections': [
            {'title': '范围借阅单', 'rows': lending_rows},
            {'title': '起始编号寻址', 'rows': [
                {'起始编号': first, '结束编号': last, '根到叶路径': result.descent},
            ]},
            {'title': '叶页链读取', 'rows': visit_rows},
            {'title': '页分裂记录', 'rows': split_rows},
            {'title': '索引页目录', 'rows': pages},
            {'title': '结构不变量巡检', 'rows': checks},
        ],
    }
