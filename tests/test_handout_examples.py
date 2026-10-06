"""The handout's rules, checked one sentence at a time against a real engine."""

from core.engine import Engine
from models.player import Decision
from tests.fixtures.scripted import propose_when_allowed, scripted


def build(players, **kwargs) -> Engine:
	defaults = dict(rounds=10, bonus=100, dims=3, monotonic=1, seed=7, timeout=0)
	defaults.update(kwargs)
	return Engine(players=players, **defaults)


def test_an_unmarried_person_has_a_happiness_of_zero():
	engine = build([scripted()] * 4)
	results = engine.run()
	assert results['married_people'] == 0
	assert all(p['happiness'] == 0 for p in results['players'])
	assert results['positive_rate'] == 0


def test_a_married_person_gets_the_bonus_minus_both_decrements():
	"""B - own decrement - half the partner's, scored on TRUE profiles."""
	engine = build([scripted(decide=propose_when_allowed)] * 2, bonus=250)
	engine.profiles = [(6, 7, 5), (2, 9, 4)]
	engine.ideals = [(8, 5, 5), (1, 9, 9)]
	engine.run()

	assert engine.spouse == [1, 0]
	# Person 0 wanted (8, 5, 5) and got (2, 9, 4): monotonic 6^2, then 4^2 + 1^2.
	mine = 36 + 16 + 1
	# Person 1 wanted (1, 9, 9) and got (6, 7, 5): monotonic exceeded, 2^2 + 4^2.
	theirs = 4 + 16
	assert engine.happiness(0) == 250 - mine - theirs / 2
	assert engine.happiness(1) == 250 - theirs - mine / 2


def test_projected_profiles_do_not_change_the_score():
	"""Lying during a date changes what the other person sees, not the truth."""
	liar = scripted(
		'Liar',
		project=lambda self, date: (10,) * self.dims,
		describe=lambda self, date, observed: (0,) * self.dims,
		decide=propose_when_allowed,
	)
	honest = build([scripted(decide=propose_when_allowed)] * 2, bonus=250)
	lying = build([liar] * 2, bonus=250)
	for engine in (honest, lying):
		engine.profiles = [(6, 7, 5), (2, 9, 4)]
		engine.ideals = [(8, 5, 5), (1, 9, 9)]
		engine.run()
	assert honest.happiness(0) == lying.happiness(0)
	assert honest.happiness(1) == lying.happiness(1)


def test_a_proposal_needs_at_least_two_dates():
	eager = scripted(decide=lambda self, date, observed, stated: Decision(propose=True))
	engine = build([eager] * 2, rounds=1)
	results = engine.run()
	assert results['married_people'] == 0
	assert any('can only propose after 2 dates' in f for f in results['faults'])


def test_both_proposing_on_the_same_round_settles_the_marriage():
	engine = build([scripted(decide=propose_when_allowed)] * 4)
	results = engine.run()
	assert results['married_people'] == 4
	assert {m['round'] for m in results['marriages']} == {2}
	# Everyone married, so nobody is left to date: the run stops early.
	assert results['rounds_played'] == 2


def test_a_one_sided_proposal_is_revealed_to_the_recipient():
	log: list = []
	suitor = scripted('Suitor', decide=propose_when_allowed, log=log)
	shy = scripted('Shy', decide=lambda self, date, observed, stated: Decision(again=True), log=log)
	engine = build([suitor, shy], rounds=2)
	engine.run()

	assert engine.spouse == [None, None]
	shy_outcomes = [args[0] for index, method, args in log if index == 1 and method == 'on_outcome']
	assert [o.partner_proposed for o in shy_outcomes] == [False, True]
	suitor_outcomes = [
		args[0] for index, method, args in log if index == 0 and method == 'on_outcome'
	]
	assert not any(o.partner_proposed for o in suitor_outcomes)


def test_incompatible_means_never_matched_again():
	picky = scripted(decide=lambda self, date, observed, stated: Decision(incompatible=True))
	engine = build([picky, scripted()], rounds=3)
	engine.run()
	rounds = engine.records
	assert len(rounds[0].dates) == 1
	assert all(not r.dates for r in rounds[1:])
	assert all(r.unmatched == [0, 1] for r in rounds[1:])


def test_listing_somebody_you_previously_dated_is_fine():
	keen = scripted(likes=lambda self, candidates, turn: [c.index for c in candidates])
	engine = build([keen] * 2, rounds=3)
	engine.run()
	assert [r.dates[0].how for r in engine.records] == ['mutual'] * 3
	assert [r.dates[0].number for r in engine.records] == [1, 2, 3]
