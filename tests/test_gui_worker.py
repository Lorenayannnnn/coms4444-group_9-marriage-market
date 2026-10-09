import csv
import json
import time

import pytest

from core.engine import Engine
from core.gui_worker import SimulationWorker
from players.greedy_player import GreedyPlayer
from players.random_player import RandomPlayer
from tests.fixtures.worker_players import ExitingPlayer, SlowPlayer


def wait_message(worker):
	deadline = time.monotonic() + 15
	while time.monotonic() < deadline:
		message = worker.poll()
		if message is not None:
			return message
		time.sleep(0.005)
	raise AssertionError('worker did not respond')


def options(**kwargs):
	return dict(
		players=[GreedyPlayer] * 4 + [RandomPlayer] * 4,
		rounds=8,
		seed=7,
		timeout=0,
		keep_records=False,
		**kwargs,
	)


def test_spawned_run_matches_engine_and_log_snapshots(tmp_path):
	config = options()
	expected = Engine(**config).run()
	path = tmp_path / 'worker.log'
	worker = SimulationWorker(config, str(path))
	try:
		kind, state, record = wait_message(worker)
		assert kind == 'ready' and state.round == 0 and record is None
		while not state.finished:
			worker.request()
			kind, state, record = wait_message(worker)
			assert kind == 'round' and record.round == state.round
			assert not record.interest
		assert state.scores == [p['happiness'] for p in expected['players']]
		assert state.spouse == [p['partner'] for p in expected['players']]
	finally:
		worker.close()
	assert not worker.process.is_alive()
	assert json.loads(path.read_text().split('========\n', 1)[1]) == expected
	with path.with_suffix('.csv').open(encoding='utf-8-sig', newline='') as stream:
		rows = list(csv.DictReader(stream))
	assert len([r for r in rows if r['event'] == 'result']) == 8
	assert any(r['event'] == 'interest' for r in rows)


def test_request_and_poll_do_not_wait_for_slow_players():
	config = dict(players=[SlowPlayer] * 2, rounds=2, timeout=0)
	worker = SimulationWorker(config)
	try:
		wait_message(worker)
		start = time.monotonic()
		worker.request()
		worker.request()  # duplicate requests cannot queue extra rounds
		assert worker.pending
		assert worker.poll() is None
		assert time.monotonic() - start < 0.2
		_, state, _ = wait_message(worker)
		assert state.round == 1
		assert worker.poll() is None
	finally:
		worker.close()


def test_worker_preserves_player_timeouts(tmp_path):
	worker = SimulationWorker(
		dict(players=[SlowPlayer] * 2, rounds=1, timeout=0.02), str(tmp_path / 'timeout.log')
	)
	try:
		wait_message(worker)
		worker.request()
		_, state, record = wait_message(worker)
		assert state.finished
		assert len(record.faults) == 2
		assert all('exceeded 0.02s' in fault for fault in record.faults)
	finally:
		worker.close()


def test_partial_run_finalizes_logs_on_close(tmp_path):
	path = tmp_path / 'partial.log'
	worker = SimulationWorker(options(), str(path))
	try:
		wait_message(worker)
		for _ in range(2):
			worker.request()
			wait_message(worker)
	finally:
		worker.close()
	worker.close()
	assert json.loads(path.read_text().split('========\n', 1)[1])['rounds_played'] == 2


def test_jump_returns_only_target_snapshot_and_logs_every_round(tmp_path):
	path = tmp_path / 'jump.log'
	config = dict(
		players=[GreedyPlayer] * 4, rounds=8, bonus=0, seed=7, timeout=0, keep_records=False
	)
	worker = SimulationWorker(config, str(path))
	try:
		wait_message(worker)
		worker.request(100)  # clamps to the configured eight-round limit
		_, state, record = wait_message(worker)
		assert state.round == record.round == 8
		assert state.finished
		assert worker.poll() is None  # no intermediate snapshots were queued
	finally:
		worker.close()
	text = path.read_text()
	assert text.count('\nround ') == 8
	assert json.loads(text.split('========\n', 1)[1]) == Engine(**config).run()


def test_jump_cancel_stops_at_round_boundary_and_can_resume():
	worker = SimulationWorker(dict(players=[SlowPlayer] * 2, rounds=10, timeout=0))
	try:
		wait_message(worker)
		worker.request(10)
		time.sleep(0.1)
		worker.cancel_jump.set()
		_, state, _ = wait_message(worker)
		assert state.round == 1 and not state.finished
		worker.request(2)
		_, state, _ = wait_message(worker)
		assert state.round == 2
	finally:
		worker.close()


def test_jump_stops_when_everyone_marries_before_target():
	worker = SimulationWorker(dict(players=[GreedyPlayer] * 4, rounds=20, bonus=10000, timeout=0))
	try:
		wait_message(worker)
		worker.request(20)
		_, state, record = wait_message(worker)
		assert state.round == record.round == 2
		assert state.finished and not state.singles()
	finally:
		worker.close()


def test_invalid_configuration_and_worker_crash_are_reported():
	worker = SimulationWorker(dict(players=[GreedyPlayer] * 3))
	try:
		with pytest.raises(RuntimeError, match='N must be even'):
			wait_message(worker)
	finally:
		worker.close()


def test_worker_crash_is_reported():
	worker = SimulationWorker(dict(players=[ExitingPlayer] * 2, timeout=0))
	try:
		wait_message(worker)
		worker.request()
		with pytest.raises(RuntimeError, match='exited'):
			wait_message(worker)
	finally:
		worker.close()


def test_forced_shutdown_reaps_busy_worker(tmp_path):
	path = tmp_path / 'forced.log'
	worker = SimulationWorker(dict(players=[SlowPlayer] * 2, timeout=0), str(path))
	try:
		wait_message(worker)
		worker.request()
		time.sleep(0.1)
	finally:
		worker.close(grace=0.01)
	assert not worker.process.is_alive()
	assert path.read_text().startswith('marriage market debug log')


def test_main_gui_uses_worker_and_finalizes_logs(tmp_path, monkeypatch):
	import main
	from models.cli import settings
	from ui import gui

	path = tmp_path / 'cli-gui.log'
	args = settings(
		['--gui', '--player', 'r', '4', '--rounds', '2', '--seed', '7', '--log', str(path)]
	)
	monkeypatch.setattr(main, 'settings', lambda: args)
	workers = []

	def run_gui(*, worker):
		workers.append(worker)
		wait_message(worker)
		for _ in range(2):
			worker.request()
			wait_message(worker)

	monkeypatch.setattr(gui, 'run_gui', run_gui)
	main.main()
	assert not workers[0].process.is_alive()
	actual = json.loads(path.read_text().split('========\n', 1)[1])
	assert actual == Engine([RandomPlayer] * 4, rounds=2, seed=7).run()


def test_inspecting_participants_preserves_skipped_history_without_advancing():
	worker = SimulationWorker(dict(players=[RandomPlayer] * 4, rounds=8, seed=7, timeout=0))
	expected = Engine([RandomPlayer] * 4, rounds=8, seed=7, timeout=0)
	expected.run()
	try:
		wait_message(worker)
		worker.request(8)
		_, state, _ = wait_message(worker)
		final_round = state.round
		for person in range(4):
			worker.inspect(person)
			kind, state, record = wait_message(worker)
			assert kind == 'inspect' and record is None
			assert state.round == final_round and state.participant == person
			assert len(state.history) == expected.dates_had[person]
			assert state.scores[person] == expected.happiness(person)
			assert all(entry.partner != person for entry in state.history)
			assert [entry.round for entry in state.history] == sorted(
				entry.round for entry in state.history
			)
	finally:
		worker.close()


def test_capped_worker_matches_engine_and_logs_limit(tmp_path):
	config = dict(players=[RandomPlayer] * 100, rounds=3, seed=7, timeout=0, list_multiple=1)
	path = tmp_path / 'capped.log'
	expected = Engine(**config).run()
	worker = SimulationWorker(config, str(path))
	try:
		wait_message(worker)
		worker.request(3)
		_, state, _ = wait_message(worker)
		assert state.scores == [p['happiness'] for p in expected['players']]
	finally:
		worker.close()
	actual = json.loads(path.read_text().split('========\n', 1)[1])
	assert actual == expected
	with path.with_suffix('.csv').open(encoding='utf-8-sig', newline='') as stream:
		rows = list(csv.DictReader(stream))
	assert all(row['list_limit'] == '10' and row['list_multiple'] == '1.0' for row in rows)
