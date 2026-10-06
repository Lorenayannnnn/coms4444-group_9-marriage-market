"""Boundary markets and end-to-end CLI/log checks."""

import itertools
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

from core.engine import Engine
from core.runlog import RunLog, bind, default_path
from models.player import Decision
from models.profile import validate_distribution
from players.greedy_player import GreedyPlayer
from players.random_player import RandomPlayer
from tests.fixtures.scripted import scripted


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_probabilities_and_parameters_are_rejected(value):
	with pytest.raises(ValueError, match='finite'):
		validate_distribution([[value] + [0.1] * 10], 1)
	for parameter in ('bonus', 'timeout'):
		with pytest.raises(ValueError, match='finite'):
			Engine([GreedyPlayer] * 2, **{parameter: value})


def test_negative_timeout_is_rejected():
	with pytest.raises(ValueError, match='nonnegative'):
		Engine([GreedyPlayer] * 2, timeout=-1)


def test_boundary_market_matrix():
	count = 0
	for n, dims, dist, bonus, rounds, seed in itertools.product(
		(2, 8, 30), (1, 5), ('uniform', 'normal', 'mixed'), (0, 100, 10000), (1, 12), (1, 7)
	):
		for monotonic in (0, dims):
			random.seed(seed)
			engine = Engine(
				[GreedyPlayer, RandomPlayer] * (n // 2),
				dims=dims,
				monotonic=monotonic,
				distribution=dist,
				bonus=bonus,
				rounds=rounds,
				seed=seed,
				timeout=0,
			)
			result = engine.run()
			assert not result['faults']
			assert result['married_people'] == 2 * len(result['marriages'])
			assert result['positive_rate'] == sum(p['happiness'] > 0 for p in result['players']) / n
			for record in engine.records:
				seen = [p for date in record.dates for p in (date.a, date.b)]
				assert len(seen) == len(set(seen))
				assert set(seen).isdisjoint(record.unmatched)
				assert set(seen) | set(record.unmatched) == set(record.singles)
			for p in result['players']:
				if p['partner'] is None:
					assert p['happiness'] == 0
					continue
				q = result['players'][p['partner']]
				assert q['partner'] == p['index']

				def cost(ideal, profile, monotonic=monotonic):
					return sum(
						(max(0, w - v) if i < monotonic else w - v) ** 2
						for i, (w, v) in enumerate(zip(ideal, profile, strict=True))
					)

				assert (
					p['happiness']
					== bonus
					- cost(engine.ideals[p['index']], engine.profiles[q['index']])
					- cost(engine.ideals[q['index']], engine.profiles[p['index']]) / 2
				)
			count += 1
	assert count == 432


@pytest.mark.parametrize('summary', [False, True])
def test_cli_results_equal_log_snapshot(tmp_path, summary):
	path = tmp_path / 'nested' / 'cli.log'
	args = [sys.executable, 'main.py', '--player', 'g', '6', '--rounds', '8', '--log', str(path)]
	if summary:
		args.append('--summary-only')
	run = subprocess.run(args, capture_output=True, text=True, check=True, timeout=15)
	result = json.loads(run.stdout)
	text = path.read_text()
	assert json.loads(text.split('========\n', 1)[1]) == result
	assert text.count('\nround ') == result['rounds_played']
	assert not result['faults']


def test_cli_no_log(tmp_path):
	entry = Path(__file__).resolve().parents[1] / 'main.py'
	run = subprocess.run(
		[sys.executable, str(entry), '--no-log', '--rounds', '1'],
		cwd=tmp_path,
		capture_output=True,
		text=True,
		check=True,
		timeout=15,
	)
	assert json.loads(run.stdout)['rounds_played'] == 1
	assert not (tmp_path / 'logs').exists()


def test_partial_run_logs_faults_and_unmatched_people(tmp_path):
	def decide(self, date, observed, stated):
		return Decision(incompatible=True)

	bad = scripted('Broken', project=lambda self, date: (), decide=decide)
	engine = Engine([bad] * 2, rounds=10, timeout=0)
	path = tmp_path / 'partial.log'
	log = RunLog.create(str(path), engine)
	callback = bind(log, engine)
	for _ in range(2):
		callback(engine.step())
	log.finish(engine)
	text = path.read_text()
	assert 'FAULT' in text and 'no date: 0,1' in text
	assert json.loads(text.split('========\n', 1)[1]) == engine.results()
	assert engine.round == 2


def test_default_log_paths_distinguish_rapid_runs():
	assert len({default_path(1) for _ in range(20)}) == 20
