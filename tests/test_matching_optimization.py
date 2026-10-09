"""The professor's vertex-order matching is maximal and reproducible."""

import random

import pytest

import core.engine
from core.engine import MUTUAL, ONE_SIDED, Engine
from players.greedy_player import GreedyPlayer
from players.random_player import RandomPlayer
from tests.fixtures.scripted import scripted


@pytest.mark.parametrize('n', [4, 20, 60])
@pytest.mark.parametrize('kind', ['random', 'greedy', 'mixed'])
@pytest.mark.parametrize('seed', [1, 7, 4444])
def test_vertex_order_matching_is_reproducible(n, kind, seed):
	roster = {
		'random': [RandomPlayer] * n,
		'greedy': [GreedyPlayer] * n,
		'mixed': [GreedyPlayer] * (n // 2) + [RandomPlayer] * (n // 2),
	}[kind]
	engine = Engine(roster, rounds=20, seed=seed, timeout=0)
	other = Engine(roster, rounds=20, seed=seed, timeout=0)
	assert engine.run() == other.run()
	assert engine.records == other.records
	assert engine.rng.getstate() == other.rng.getstate()


@pytest.mark.parametrize('density', [0, 0.1, 0.5, 1])
@pytest.mark.parametrize('seed', range(10))
def test_each_matching_stage_is_maximal_and_respects_blocks(density, seed):
	rng = random.Random(seed)
	n = 20
	wants = {a: {b for b in range(n) if b != a and rng.random() < density} for a in range(n)}
	player = scripted(
		likes=lambda self, candidates, turn: [
			c.index for c in candidates if c.index in wants[self.index]
		]
	)
	engine = Engine([player] * n, rounds=1, seed=seed, timeout=0, list_multiple=0)
	engine.blocked = {(a, b) for a in range(n) for b in range(n) if a != b and rng.random() < 0.2}
	record = engine.step()
	taken = set()
	for date in record.dates:
		assert engine.allowed(date.a, date.b)
		assert date.a not in taken and date.b not in taken
		taken.update((date.a, date.b))
	remaining = set(range(n))
	for stage in (MUTUAL, ONE_SIDED):
		for date in record.dates:
			if date.how == stage:
				remaining.difference_update((date.a, date.b))
		for a in remaining:
			for b in remaining:
				if a >= b or not engine.allowed(a, b):
					continue
				both = b in record.interest[a] and a in record.interest[b]
				either = b in record.interest[a] or a in record.interest[b]
				assert not (both if stage == MUTUAL else either)
	for a in record.unmatched:
		for b in record.unmatched:
			if a < b:
				assert not engine.allowed(a, b)


def test_first_round_does_not_allocate_a_candidate_for_every_pair(monkeypatch):
	allocations = []
	original = core.engine.Candidate

	def candidate(*args, **kwargs):
		allocations.append(True)
		return original(*args, **kwargs)

	monkeypatch.setattr(core.engine, 'Candidate', candidate)
	engine = Engine([RandomPlayer] * 100, rounds=1, timeout=0)
	engine.step()
	assert len(allocations) <= 200  # formerly 9,900 objects in this round
