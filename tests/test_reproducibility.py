import os
import random
import subprocess
import sys

from core.engine import Engine
from core.runlog import RunLog, bind
from players.greedy_player import GreedyPlayer
from players.random_player import RandomPlayer


def build():
	return Engine([GreedyPlayer] * 10 + [RandomPlayer] * 10, seed=7, timeout=0)


def test_results_records_and_ids_ignore_global_random_state():
	random.seed(1)
	a = build()
	a_result = a.run()
	random.seed(999)
	b = build()
	assert b.run() == a_result
	assert a.records == b.records
	assert [p.id for p in a.players] == [p.id for p in b.players]


def test_interleaved_engines_have_independent_random_streams():
	expected = build().run()
	a, b = build(), build()
	while not a.finished or not b.finished:
		a.step()
		b.step()
	assert a.results() == b.results() == expected
	assert a.players[0].rng is not a.players[1].rng
	assert a.players[0].rng is not b.players[0].rng


def test_text_and_csv_logs_are_identical(tmp_path):
	contents = []
	for i in range(2):
		engine = build()
		log = RunLog.create(str(tmp_path / f'run{i}.log'), engine)
		engine.run(on_round=bind(log, engine))
		log.finish(engine)
		contents.append((log.path.read_bytes(), log.csv_path.read_bytes()))
	assert contents[0] == contents[1]


def test_cli_is_reproducible_across_processes_and_hash_seeds():
	outputs = []
	for hash_seed in ('1', '999'):
		env = dict(os.environ, PYTHONHASHSEED=hash_seed)
		run = subprocess.run(
			[sys.executable, 'main.py', '--seed', '7', '--timeout', '0', '--no-log'],
			env=env,
			capture_output=True,
			text=True,
			check=True,
			timeout=15,
		)
		outputs.append(run.stdout)
	assert outputs[0] == outputs[1]
