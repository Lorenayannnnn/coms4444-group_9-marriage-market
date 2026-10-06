import json
import random

from core.engine import Engine
from core.runlog import RunLog, bind
from players.greedy_player import GreedyPlayer
from players.random_player import RandomPlayer


def test_log_has_header_rounds_and_snapshot(tmp_path):
	random.seed(1)
	engine = Engine([GreedyPlayer] * 4 + [RandomPlayer] * 4, rounds=10, seed=2, timeout=0)
	path = tmp_path / 'nested' / 'run.log'
	log = RunLog.create(str(path), engine)
	results = engine.run(on_round=bind(log, engine))
	log.finish(engine)

	text = path.read_text()
	assert text.startswith('marriage market debug log')
	assert 'N=8  d=5  m=2  t=10  B=100' in text
	assert '[0] GreedyPlayer  true ' in text
	assert 'round 1  singles 8' in text
	assert 'date ' in text
	snapshot = text.split('========\n', 1)[1]
	assert json.loads(snapshot) == results


def test_marriages_are_logged(tmp_path):
	random.seed(1)
	engine = Engine([GreedyPlayer] * 6, rounds=100, bonus=1000, seed=2, timeout=0)
	path = tmp_path / 'run.log'
	log = RunLog.create(str(path), engine)
	engine.run(on_round=bind(log, engine))
	log.finish(engine)
	assert 'MARRIED' in path.read_text()


def test_finish_is_idempotent(tmp_path):
	engine = Engine([GreedyPlayer] * 2, rounds=1, timeout=0)
	log = RunLog.create(str(tmp_path / 'run.log'), engine)
	log.finish(engine)
	log.finish(engine)
	log.close()
