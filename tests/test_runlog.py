import csv
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


def test_csv_dates_and_results_match_engine(tmp_path):
	random.seed(1)
	engine = Engine([GreedyPlayer] * 6, rounds=10, bonus=1000, seed=2, timeout=0)
	log = RunLog.create(str(tmp_path / 'run.log'), engine)
	results = engine.run(on_round=bind(log, engine))
	log.finish(engine)
	with log.csv_path.open(encoding='utf-8-sig', newline='') as stream:
		rows = list(csv.DictReader(stream))
	assert len([r for r in rows if r['event'] == 'person']) == 6
	dates = [r for r in rows if r['event'] == 'date']
	assert len(dates) == sum(len(r.dates) * 2 for r in engine.records)
	for row in dates:
		person = int(row['person'])
		record = engine.records[int(row['round']) - 1]
		date = next(d for d in record.dates if person in (d.a, d.b))
		assert row['proposed'] == str(date.decisions[person].propose)
		assert tuple(int(row[f'projected_{i}']) for i in range(engine.dims)) == date.shown[person]
	for row in (r for r in rows if r['event'] == 'result'):
		person = results['players'][int(row['person'])]
		assert float(row['happiness']) == person['happiness']
		assert row['married'] == str(person['married'])
		assert row['B'] == '1000.0'


def test_csv_preserves_partial_run_without_records(tmp_path):
	engine = Engine([GreedyPlayer] * 2, rounds=20, timeout=0, keep_records=False)
	log = RunLog.create(str(tmp_path / 'partial.log'), engine)
	bind(log, engine)(engine.step())
	log.finish(engine)
	log.finish(engine)
	with log.csv_path.open(encoding='utf-8-sig', newline='') as stream:
		rows = list(csv.DictReader(stream))
	assert len([r for r in rows if r['event'] == 'date']) == 2
	assert len([r for r in rows if r['event'] == 'result']) == 2
	assert engine.records == []
