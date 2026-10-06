import json
import random

import pytest

from core.engine import MUTUAL, ONE_SIDED, RANDOM, REPEAT, Engine
from models.player import Decision
from models.profile import MAX_VALUE, MIN_VALUE, uniform_row
from players.greedy_player import GreedyPlayer
from players.random_player import RandomPlayer
from tests.fixtures.scripted import always_again, scripted


def build(players=None, **kwargs) -> Engine:
	defaults = dict(rounds=20, bonus=100, dims=5, monotonic=2, seed=1, timeout=0)
	defaults.update(kwargs)
	return Engine(players=[GreedyPlayer] * 10 if players is None else players, **defaults)


# ---------------------------------------------------------------- parameters


@pytest.mark.parametrize('count', [0, 1, 3, 7])
def test_people_must_be_even_and_at_least_two(count):
	with pytest.raises(ValueError, match='N must be even'):
		build([GreedyPlayer] * count)


def test_monotonic_cannot_exceed_dims():
	with pytest.raises(ValueError, match='m must lie between 0 and d'):
		build(dims=3, monotonic=4)


def test_rounds_must_be_positive():
	with pytest.raises(ValueError, match='t must be at least 1'):
		build(rounds=0)


def test_custom_distribution_is_validated():
	with pytest.raises(ValueError, match='one row per dimension'):
		build(dims=2, distribution=[uniform_row()])
	engine = build(dims=1, monotonic=0, distribution=[uniform_row()])
	assert engine.distribution_name == 'custom'


def test_profiles_are_drawn_on_the_scale():
	engine = build(dims=7, monotonic=3)
	for profile in engine.profiles + engine.ideals:
		assert len(profile) == 7
		assert all(MIN_VALUE <= v <= MAX_VALUE for v in profile)


def test_players_receive_only_their_own_profile():
	engine = build()
	for i, player in enumerate(engine.players):
		assert player.profile == engine.profiles[i]
		assert player.ideal == engine.ideals[i]
		assert player.index == i
		assert player.people == 10


# ---------------------------------------------------------------- determinism


def test_same_seed_same_results():
	def once() -> str:
		random.seed(3)
		engine = build([GreedyPlayer] * 6 + [RandomPlayer] * 6, seed=11)
		return json.dumps(engine.run(), sort_keys=True)

	assert once() == once()


def test_different_seeds_draw_different_people():
	assert build(seed=1).profiles != build(seed=2).profiles


def test_keep_records_off_does_not_change_results():
	random.seed(5)
	kept = build(keep_records=True).run()
	random.seed(5)
	dropped_engine = build(keep_records=False)
	dropped = dropped_engine.run()
	assert kept == dropped
	assert dropped_engine.records == []


# ---------------------------------------------------------------- pairing


def test_everyone_dates_at_most_once_per_round():
	random.seed(2)
	engine = build([RandomPlayer] * 12, rounds=30)
	engine.run()
	for record in engine.records:
		seen = [p for date in record.dates for p in (date.a, date.b)]
		assert len(seen) == len(set(seen))
		assert set(seen) | set(record.unmatched) == set(record.singles)


def test_pairing_stages_run_in_the_handouts_order():
	"""0 and 1 like each other, 2 likes 3 who likes nobody, 4 and 5 like nobody."""
	wants = {0: [1], 1: [0], 2: [3]}
	player = scripted(likes=lambda self, candidates, turn: wants.get(self.index, []))
	engine = build([player] * 6, rounds=1)
	record = engine.step()
	got = {(d.a, d.b): d.how for d in record.dates}
	assert got == {(0, 1): MUTUAL, (2, 3): ONE_SIDED, (4, 5): RANDOM}


def test_mutual_repeat_requests_are_paired_first():
	engine = build([scripted(decide=always_again)] * 6, rounds=3)
	first = engine.step()
	pairs = {(d.a, d.b) for d in first.dates}
	second = engine.step()
	assert {(d.a, d.b) for d in second.dates} == pairs
	assert all(d.how == REPEAT for d in second.dates)
	assert all(d.number == 2 for d in second.dates)


def test_repeat_daters_are_not_asked_to_choose():
	log: list = []
	engine = build([scripted(decide=always_again, log=log)] * 4, rounds=2)
	engine.run()
	chooses = [(i, args[1].round) for i, method, args in log if method == 'choose_dates']
	assert {r for _, r in chooses} == {1}


def test_one_sided_repeat_request_is_not_a_repeat():
	keen = scripted('Keen', decide=always_again)
	engine = build([keen, scripted('Cold')], rounds=2)
	engine.run()
	assert [r.dates[0].how for r in engine.records] == [RANDOM, RANDOM]


def test_candidates_exclude_yourself_married_people_and_people_you_blocked():
	log: list = []

	def decide(self, date, observed, stated):
		if self.index == 0 and date.partner == 1:
			return Decision(incompatible=True)
		if self.index in (2, 3):
			return Decision(again=True, propose=date.date_number >= 2)
		return Decision()

	def likes(self, candidates, turn):
		open_to = {c.index for c in candidates}
		return [w for w in wants.get(self.index, []) if w in open_to]

	wants = {0: [1], 1: [0], 2: [3], 3: [2]}
	player = scripted(likes=likes, decide=decide, log=log)
	engine = build([player] * 6, rounds=4)
	engine.run()

	def candidates(person: int, round_no: int) -> set[int]:
		for index, method, args in log:
			if method == 'choose_dates' and index == person and args[1].round == round_no:
				return {c.index for c in args[0]}
		raise AssertionError(f'{person} was not asked in round {round_no}')

	assert engine.spouse[2] == 3
	# Person 0 blocked 1 in round 1, and 2 and 3 married in round 2.
	assert candidates(0, 3) == {4, 5}
	# Person 1 is not told it was blocked, so 0 still shows up for it.
	assert 0 in candidates(1, 3)
	assert not engine.allowed(0, 1)


def test_candidates_report_past_dates():
	log: list = []
	keen = scripted(likes=lambda self, candidates, turn: [c.index for c in candidates], log=log)
	engine = build([keen] * 2, rounds=3)
	engine.run()
	counts = [args[0][0].dates for i, method, args in log if method == 'choose_dates' and i == 0]
	assert counts == [0, 1, 2]


def test_rounds_left_counts_the_current_round():
	log: list = []
	engine = build([scripted(log=log)] * 2, rounds=5)
	engine.run()
	rounds_left = [args[1].rounds_left for i, m, args in log if m == 'choose_dates' and i == 0]
	assert rounds_left == [5, 4, 3, 2, 1]


# ---------------------------------------------------------------- dating


def test_partners_see_each_others_projection_and_stated_ideal():
	log: list = []
	player = scripted(
		project=lambda self, date: (self.index,) * self.dims,
		describe=lambda self, date, observed: (9 - self.index,) * self.dims,
		log=log,
	)
	engine = build([player] * 2, rounds=1)
	engine.run()
	decides = {i: args for i, method, args in log if method == 'decide'}
	_, observed, stated = decides[0]
	assert observed == (1,) * 5
	assert stated == (8,) * 5
	_, observed, stated = decides[1]
	assert observed == (0,) * 5
	assert stated == (9,) * 5


def test_describe_ideal_sees_the_projection_but_not_the_partners_ideal():
	log: list = []
	engine = build([scripted(log=log)] * 2, rounds=1)
	engine.run()
	describes = {i: args for i, method, args in log if method == 'describe_ideal'}
	assert describes[0][1] == engine.profiles[1]
	assert describes[1][1] == engine.profiles[0]


def test_dates_are_counted_per_pair():
	engine = build([scripted(decide=always_again)] * 4, rounds=4)
	engine.run()
	for date in engine.records[-1].dates:
		assert date.number == 4
		assert engine.dates_between(date.a, date.b) == 4
	assert engine.dates_had == [4, 4, 4, 4]


def test_proposals_are_tallied():
	engine = build(
		[scripted('A', decide=lambda s, d, o, st: Decision(again=True, propose=d.date_number >= 2))]
		+ [scripted('B', decide=always_again)],
		rounds=3,
	)
	results = engine.run()
	assert results['players'][0]['proposals_made'] == 2
	assert results['players'][1]['proposals_received'] == 2


# ---------------------------------------------------------------- results


def test_results_are_consistent():
	random.seed(4)
	results = build([GreedyPlayer] * 10 + [RandomPlayer] * 10, rounds=50).run()
	players = results['players']
	married = [p for p in players if p['married']]
	assert results['married_people'] == len(married) == 2 * len(results['marriages'])
	assert results['married_rate'] == len(married) / 20
	assert results['positive_rate'] == sum(p['positive'] for p in players) / 20
	assert results['mean_happiness'] == pytest.approx(sum(p['happiness'] for p in players) / 20)
	for p in married:
		partner = players[p['partner']]
		assert partner['partner'] == p['index']
		assert p['happiness'] == 100 - p['own_decrement'] - p['partner_decrement'] / 2
	for p in players:
		if not p['married']:
			assert p['happiness'] == 0
			assert p['own_decrement'] is None


def test_greedy_beats_random_on_the_default_market():
	random.seed(9)
	results = build([GreedyPlayer] * 10 + [RandomPlayer] * 10, rounds=100, seed=4444).run()
	by_name: dict[str, list[float]] = {}
	for p in results['players']:
		by_name.setdefault(p['name'], []).append(p['happiness'])
	greedy = sum(by_name['GreedyPlayer']) / 10
	rand = sum(by_name['RandomPlayer']) / 10
	assert greedy > rand
