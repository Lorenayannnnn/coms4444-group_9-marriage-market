"""Headless checks for the visualiser and the leaderboard.

The GUI is the thing the TA runs on a projector in front of the class, so the
failure that matters is not a wrong pixel, it is a crash partway through a
run. These drive the real render path under SDL's dummy driver.
"""

import os
import random

import pytest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

pygame = pytest.importorskip('pygame')

from core.engine import Engine  # noqa: E402
from players.greedy_player import GreedyPlayer  # noqa: E402
from players.random_player import RandomPlayer  # noqa: E402
from tests.fixtures.scripted import scripted  # noqa: E402
from ui.gui import HEIGHT, WIDTH, Visualizer, ring_positions  # noqa: E402


@pytest.fixture(scope='module')
def screen():
	pygame.init()
	surface = pygame.display.set_mode((WIDTH, HEIGHT))
	yield surface
	pygame.quit()


def build(**kwargs) -> Engine:
	random.seed(1)
	defaults = dict(
		players=[GreedyPlayer] * 10 + [RandomPlayer] * 10, rounds=100, seed=4444, timeout=0
	)
	defaults.update(kwargs)
	return Engine(**defaults)


def test_renders_a_full_run_without_crashing(screen):
	engine = build()
	view = Visualizer(engine)
	view.draw(screen)
	for _ in range(engine.rounds + 5):
		view.advance()
		view.draw(screen)
	assert view.finished
	assert not view.playing


def test_renders_a_large_market(screen):
	view = Visualizer(build(players=[GreedyPlayer] * 60))
	view.selected = 59
	for _ in range(5):
		view.advance()
		view.draw(screen)


def test_fault_banner_renders(screen):
	broken = scripted('Broken', project=lambda self, date: 'nope')
	view = Visualizer(build(players=[broken] * 2 + [GreedyPlayer] * 2))
	view.advance()
	assert view.fault_log
	view.draw(screen)


def test_ring_positions_start_at_the_top():
	points = ring_positions(4, (100, 100), 50)
	assert points[0] == (100, 50)
	assert points[2] == (100, 150)


def test_click_selects_the_nearest_person(screen):
	view = Visualizer(build())
	view.select_at(view.positions[7])
	assert view.selected == 7
	view.draw(screen)
	view.select_at((1, 1))
	assert view.selected is None


def test_jump_skips_forward_but_never_back():
	view = Visualizer(build())
	view.jump_to(25)
	assert view.engine.round == 25
	view.jump_to(10)
	assert view.engine.round == 25
	assert view.goto_error


def test_typing_a_round_number_jumps():
	view = Visualizer(build())
	for ch in '12':
		view.type_key(0, ch)
	view.type_key(pygame.K_RETURN, '\r')
	assert view.engine.round == 12
	assert view.goto_buffer == ''


def test_speed_controls_clamp():
	view = Visualizer(build())
	for _ in range(20):
		view.faster()
	top = view.speed
	view.faster()
	assert view.speed == top
	for _ in range(20):
		view.slower()
	assert view.speed == 1


def test_on_round_sees_every_round():
	seen = []
	view = Visualizer(build(rounds=7), on_round=lambda record: seen.append(record.round))
	view.jump_to(100)
	assert seen == list(range(1, 8))


def test_skip_input_ignores_nondecimal_digits():
	view = Visualizer(build())
	view.type_key(0, '²')
	view.type_key(pygame.K_RETURN, '\r')
	assert view.engine.round == 0
	assert view.goto_buffer == ''


def test_skip_input_backspace_and_length_limit():
	view = Visualizer(build())
	for digit in '1234567':
		view.type_key(0, digit)
	assert view.goto_buffer == '123456'
	view.type_key(pygame.K_BACKSPACE, '')
	assert view.goto_buffer == '12345'


@pytest.mark.parametrize('quit_key', [pygame.K_q, pygame.K_ESCAPE, None])
def test_real_event_loop_controls_and_partial_log(tmp_path, monkeypatch, quit_key):
	import json

	from core.runlog import RunLog, bind
	from ui.gui import run_gui

	engine = build(rounds=20)
	path = tmp_path / 'gui.log'
	log = RunLog.create(str(path), engine)

	def key(k, u=''):
		return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=u)

	closing = pygame.event.Event(pygame.QUIT) if quit_key is None else key(quit_key)
	frames = iter(
		[
			[
				key(pygame.K_RIGHT),
				key(pygame.K_UP),
				key(pygame.K_DOWN),
				pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(100, 100)),
			],
			[key(pygame.K_3, '3'), key(pygame.K_RETURN, '\r')],
			[key(pygame.K_SPACE)],
			[closing],
		]
	)
	monkeypatch.setattr(pygame.event, 'get', lambda: next(frames, [closing]))
	run_gui(engine, on_round=bind(log, engine))
	log.finish(engine)
	assert engine.round == 3
	text = path.read_text()
	assert text.count('\nround ') == 3
	assert json.loads(text.split('========\n', 1)[1]) == engine.results()
	assert not pygame.get_init()


def test_leaderboard_draws_and_closes():
	from ui.leaderboard import Leaderboard

	board = Leaderboard(title='t', rank_by='positive_rate', total=2, entrants=['g', 'r'])
	row = {
		'code': 'g',
		'rank': 1,
		'positive_rate': {'mean': 0.8},
		'mean_happiness': {'mean': 40.0},
		'married_rate': {'mean': 0.9},
	}
	board.update([row], 1, ['r'], last_match='gx6  seed 1')
	board.update([row], 2, [])
	board.wait_to_close()
	assert not board.open
