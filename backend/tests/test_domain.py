"""Domain and B+ tree behaviour checks."""
import copy

import pytest

from src.services.score_tree import BPlusTree, Score


def test_sample_metrics_match_business_script(services):
    _, domain, _ = services
    report = domain.solve(copy.deepcopy(domain.SPEC['sample']), None)
    for label, expected in domain.SPEC['expect'].items():
        assert report['metrics'][label] == expected
    assert report['exportable'] is True and report['inspection_passed'] is True
    titles = {section['title'] for section in report['sections']}
    assert {'批次摘要', '巡检结论', '范围结果巡检', '结构不变量巡检'} <= titles


def test_empty_catalog_and_empty_range_still_exportable(services):
    _, domain, _ = services
    empty = {'batch_no': 'B-EMPTY', 'page_capacity': 4,
             'range_start': 1, 'range_end': 10, 'scores': []}
    report = domain.solve(empty, None)
    assert report['exportable'] is True
    assert report['metrics']['区间命中曲谱'] == 0
    assert all(row['判定'] == '通过' for row in
               next(s for s in report['sections'] if s['title'] == '范围结果巡检')['rows'])


def test_duplicate_number_in_one_batch_rejected(services, sample):
    _, domain, _ = services
    sample['batch_no'] = 'B-DUP'
    sample['scores'].append(dict(sample['scores'][0]))
    with pytest.raises(ValueError, match='重复'):
        domain.validate(sample)


def test_invalid_capacity_returns_field_error(services, sample):
    _, domain, _ = services
    sample['page_capacity'] = 1
    with pytest.raises(ValueError, match='页容量'):
        domain.validate(sample)


def test_range_lookup_matches_naive_set_across_random_inputs():
    import random
    random.seed(20261121)
    for _ in range(40):
        capacity = random.randint(2, 12)
        numbers = random.sample(range(1, 200), random.randint(0, 60))
        tree = BPlusTree(capacity)
        for number in numbers:
            tree.insert(Score(number, f'曲{number}', random.randint(0, 5)))
        pages, checks, _ = tree.inspect(len(numbers))
        assert all(row['判定'] == '通过' for row in checks)
        lo = random.randint(1, 200)
        hi = random.randint(lo, 200)
        result = tree.lookup(lo, hi)
        assert [s.number for _, s in result.matches] == sorted(
            n for n in numbers if lo <= n <= hi)
        assert all(row['判定'] == '通过' for row in result.range_checks)
        for previous, current in zip(result.visits, list(result.visits)[1:]):
            assert tree._leaf_by_id(previous.page_id).next_leaf.page_id == current.page_id
        assert pages  # page directory always populated


def test_same_input_produces_deterministic_pages():
    numbers = [12, 5, 19, 1, 17, 8, 3, 14, 7, 11]
    def build():
        tree = BPlusTree(3)
        for number in numbers:
            tree.insert(Score(number, f'n{number}', 1))
        pages, _, _ = tree.inspect(len(numbers))
        return [page['页号'] for page in pages], tree.splits
    pages_a, splits_a = build()
    pages_b, splits_b = build()
    assert pages_a == pages_b
    assert [(s.inserted_key, s.separator) for s in splits_a] == \
           [(s.inserted_key, s.separator) for s in splits_b]
