"""What the engine does when player code misbehaves.

Every failure here must cost the offending person its own move and nothing
else: the run finishes, the fault is reported, and the other person on the
date sees the engine's honest fallback.
"""

import signal
import time

import numpy as np
import pytest

from core.engine import Engine
from models.player import Advertisement, Decision
from tests.fixtures.scripted import propose_when_allowed, scripted


def build(players, **kwargs) -> Engine:
	defaults = dict(rounds=3, bonus=100, dims=4, monotonic=1, seed=3, timeout=0)
	defaults.update(kwargs)
	return Engine(players=players, **defaults)


def boom(*args):
	raise RuntimeError('boom')


def test_exceptions_in_every_hook_are_faults_not_crashes():
	broken = scripted(
		'Broken', likes=boom, project=boom, describe=boom, decide=boom, advertise=boom
	)
	engine = build([broken, scripted('Fine')])
	results = engine.run()
	faults = results['faults']
	for hook in ('advertise', 'choose_dates', 'project', 'describe_ideal', 'decide'):
		assert any(f'Broken[0] {hook}: RuntimeError: boom' in f for f in faults), hook
	assert results['rounds_played'] == 3


def test_fallbacks_are_honest():
	log: list = []
	broken = scripted('Broken', project=boom, describe=boom, advertise=boom)
	engine = build([broken, scripted('Watcher', log=log)], rounds=1)
	engine.run()
	_, observed, stated = next(args for i, m, args in log if m == 'decide')
	assert observed == engine.profiles[0]
	assert stated == engine.ideals[0]
	assert engine.ads[0] == Advertisement(0, engine.profiles[0][0], 0, engine.ideals[0][0])


def test_a_broken_constructor_does_not_stop_the_run():
	def explode(self):
		raise ValueError('bad init')

	engine = build([scripted('Fragile', init=explode), scripted('Fine')])
	results = engine.run()
	assert any('could not be constructed - ValueError: bad init' in f for f in results['faults'])
	assert any('unusable' in f for f in results['faults'])
	assert results['rounds_played'] == 3


def test_numpy_ints_are_named_in_the_fault():
	numpy_liar = scripted('Numpy', project=lambda self, date: np.array(self.profile))
	results = build([numpy_liar, scripted()], rounds=1).run()
	assert any('plain ints, not numpy.int64' in f for f in results['faults'])


@pytest.mark.parametrize(
	('profile', 'message'),
	[
		((5, 5, 5), 'must have 4 values, not 3'),
		((5, 5, 5, 11), 'must lie in [0, 10]'),
		((5, 5, 5, -1), 'must lie in [0, 10]'),
		((5, 5, 5, 5.0), 'plain ints, not float'),
		((5, 5, 5, True), 'plain ints, not bool'),
	],
)
def test_malformed_profiles_are_rejected(profile, message):
	bad = scripted('Bad', describe=lambda self, date, observed: profile)
	results = build([bad, scripted()], rounds=1).run()
	assert any(message in f for f in results['faults'])


def test_non_bool_decision_flags_are_rejected():
	sloppy = scripted('Sloppy', decide=lambda self, date, observed, stated: Decision(again=1))
	results = build([sloppy, scripted()], rounds=1).run()
	assert any('again must be a bool, not int' in f for f in results['faults'])


def test_contradictory_decisions_are_rejected():
	torn = scripted(
		'Torn', decide=lambda self, date, observed, stated: Decision(again=True, incompatible=True)
	)
	engine = build([torn, scripted(decide=lambda s, d, o, st: Decision(again=True))], rounds=2)
	results = engine.run()
	assert any('cannot mark someone incompatible' in f for f in results['faults'])
	# The fallback is Decision(), so nothing was blocked and nobody repeated.
	assert engine.allowed(0, 1)
	assert engine.records[1].dates[0].how == 'random'


def test_returning_something_that_is_not_a_decision_is_a_fault():
	weird = scripted('Weird', decide=lambda self, date, observed, stated: 'yes please')
	results = build([weird, scripted()], rounds=1).run()
	assert any('Weird[0] decide: AttributeError' in f for f in results['faults'])


@pytest.mark.parametrize(
	('choice', 'message'),
	[
		(None, 'TypeError'),
		([99], 'not among this round'),
		([np.int64(1)], 'plain int indices, not numpy.int64'),
	],
)
def test_bad_interest_lists_are_faults(choice, message):
	bad = scripted('Bad', likes=lambda self, candidates, turn: choice)
	results = build([bad, scripted()], rounds=1).run()
	assert any(message in f for f in results['faults'])


def test_naming_yourself_is_not_allowed():
	vain = scripted('Vain', likes=lambda self, candidates, turn: [self.index])
	results = build([vain, scripted()], rounds=1).run()
	assert any('not among this round' in f for f in results['faults'])


@pytest.mark.parametrize(
	'ad',
	[
		Advertisement(9, 5, 0, 5),
		Advertisement(0, 11, 0, 5),
		Advertisement(0, 5, 0, np.int64(5)),
	],
)
def test_bad_advertisements_fall_back_to_honest(ad):
	engine = build([scripted('Bad', advertise=lambda self: ad), scripted()])
	assert engine.ads[0] == Advertisement(0, engine.profiles[0][0], 0, engine.ideals[0][0])
	assert any('Bad[0] advertise' in f for f in engine.results()['faults'])


def test_a_failed_proposal_does_not_marry_anyone():
	flaky = scripted('Flaky', decide=boom)
	engine = build([flaky, scripted(decide=propose_when_allowed)], rounds=4)
	results = engine.run()
	assert results['married_people'] == 0


def test_mutating_your_own_profile_does_not_change_the_score():
	def tamper(self, date, observed, stated):
		self.profile = (10,) * self.dims
		self.ideal = (0,) * self.dims
		return Decision(again=True, propose=date.date_number >= 2)

	engine = build([scripted(decide=tamper)] * 2, bonus=500)
	truth = (list(engine.profiles), list(engine.ideals))
	engine.run()
	assert (engine.profiles, engine.ideals) == truth


@pytest.mark.skipif(not hasattr(signal, 'SIGALRM'), reason='timeouts need SIGALRM')
def test_slow_players_time_out():
	def slow(self, candidates, turn):
		time.sleep(0.5)
		return []

	results = build([scripted('Slow', likes=slow), scripted()], rounds=1, timeout=0.05).run()
	assert any('Slow[0] choose_dates: exceeded 0.05s time budget' in f for f in results['faults'])
