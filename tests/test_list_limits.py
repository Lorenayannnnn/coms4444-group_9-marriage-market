import math

import pytest

from core.engine import Engine
from models.cli import settings
from players.random_player import RandomPlayer
from tests.fixtures.scripted import always_again, scripted


@pytest.mark.parametrize('multiple', [0, 0.01, 2, 4, 8, 1e308])
def test_all_candidates_visible_with_only_returned_lists_limited(multiple):
	seen = []
	player = scripted(
		likes=lambda self, candidates, turn: (
			seen.append((self.index, candidates))
			or [c.index for c in candidates[: self.list_limit]]
		)
	)
	engine = Engine([player] * 100, rounds=2, seed=7, timeout=0, list_multiple=multiple)
	results = engine.run()
	limit = None if multiple == 0 else (99 if multiple >= 9.9 else math.ceil(multiple * 10))
	assert engine.list_limit == limit
	assert all(p.list_limit == limit for p in engine.players)
	assert not results['faults']
	for person, candidates in seen:
		assert len(candidates) == 99
		assert len({c.index for c in candidates}) == len(candidates)
		assert person not in {c.index for c in candidates}
	for record in engine.records:
		assert all(len(choices) <= (limit or 99) for choices in record.interest.values())


@pytest.mark.parametrize('blocked_count', [0, 1, 20, 80, 99])
def test_all_unblocked_candidates_remain_visible(blocked_count):
	seen = []
	player = scripted(
		likes=lambda self, candidates, turn: seen.append((self.index, candidates)) or []
	)
	engine = Engine([player] * 100, rounds=1, timeout=0)
	engine.blocked = {(0, i) for i in range(1, blocked_count + 1)}
	engine.run()
	candidates = next(c for person, c in seen if person == 0)
	assert len(candidates) == 99 - blocked_count
	assert all((0, c.index) not in engine.blocked for c in candidates)
	assert len({c.index for c in candidates}) == len(candidates)


def test_limit_rejects_overlong_generators_and_duplicate_lists():
	def likes(self, candidates, turn):
		while True:
			yield candidates[0].index

	engine = Engine([scripted(likes=likes)] * 100, rounds=1, timeout=0)
	result = engine.run()
	assert len(result['faults']) == 100
	assert all('at most 40 entries' in fault for fault in result['faults'])
	assert all(not choices for choices in engine.records[0].interest.values())


def test_interest_cap_preserves_repeat_priority_and_history_counts():
	log = []
	player = scripted(decide=always_again, log=log)
	engine = Engine([player] * 100, rounds=3, timeout=0)
	engine.run()
	assert all(date.how == 'repeat' for date in engine.records[1].dates)
	assert all(date.number == 3 for date in engine.records[2].dates)
	assert len([item for item in log if item[1] == 'choose_dates']) == 100
	seen = []
	player = scripted(
		likes=lambda self, candidates, turn: seen.append((self.index, candidates)) or []
	)
	engine = Engine([player] * 100, rounds=1, timeout=0)
	engine.date_counts[(0, 1)] = 3
	engine.run()
	for person, candidates in seen:
		for candidate in candidates:
			assert candidate.dates == (3 if {person, candidate.index} == {0, 1} else 0)


def test_capped_runs_are_reproducible_and_report_settings():
	a = Engine([RandomPlayer] * 100, rounds=5, seed=7, timeout=0)
	b = Engine([RandomPlayer] * 100, rounds=5, seed=7, timeout=0)
	assert a.run() == b.run()
	assert a.records == b.records
	assert a.results()['parameters']['list_limit'] == 40
	assert a.results()['parameters']['list_multiple'] == 4
	assert settings([]).list_multiple == 4
	assert settings(['--list-multiple', '0']).list_multiple == 0


@pytest.mark.parametrize('multiple', [-1, float('nan'), float('inf')])
def test_invalid_multiples_are_rejected(multiple):
	with pytest.raises(ValueError, match='list_multiple'):
		Engine([scripted()] * 2, list_multiple=multiple)
