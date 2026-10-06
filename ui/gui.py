"""Pygame visualiser for the marriage market.

Everybody sits on a ring, coloured by the group whose code runs them. Each
round's dates are drawn as chords across the ring, coloured by how the
simulator paired them, and married couples are joined in gold for the rest of
the run. Click a person to see their true profile, their ideal and their
advertisement - engine truth that no player ever gets to see.

This module contains no game rules. It calls ``engine.step()`` once per round
and renders the returned ``RoundRecord`` plus whatever is already on the
engine. If something here needs a value the engine does not expose, the fix is
to expose it on the engine, not to recompute it up here.
"""

import math
from collections.abc import Callable

import pygame

from core.engine import MUTUAL, ONE_SIDED, RANDOM, REPEAT, DateRecord, Engine, RoundRecord

WIDTH, HEIGHT = 1360, 880
HEADER_H = 76
JUMP_BAR_H = 50
FOOTER_H = 46
BANNER_H = 42
PAD = 18
PANEL_W = 540

BACKDROP = (40, 30, 52)
BACKDROP_DARK = (28, 20, 38)
PANEL = (52, 40, 68)
PANEL_EDGE = (128, 104, 156)
INK = (244, 238, 248)
INK_DIM = (184, 170, 200)
GOLD = (236, 196, 84)
ALERT = (198, 48, 48)
ALERT_TEXT = (255, 226, 226)
GOOD = (140, 220, 150)
WARN = (224, 158, 46)
HEART = (240, 110, 160)
SELECT = (255, 255, 255)

STAGE_COLORS = {
	REPEAT: (96, 200, 230),
	MUTUAL: (120, 214, 130),
	ONE_SIDED: (232, 164, 70),
	RANDOM: (150, 140, 160),
}

GROUP_COLORS = (
	(94, 156, 236),
	(232, 112, 104),
	(126, 206, 140),
	(204, 140, 228),
	(240, 186, 90),
	(96, 210, 206),
	(236, 134, 190),
	(170, 176, 96),
	(150, 130, 236),
	(220, 150, 120),
)

SPEEDS = (1, 2, 4, 8, 16, 32)
DEFAULT_SPEED_INDEX = 1
FAULT_LOG_LIMIT = 4
FAULT_FLASH_ROUNDS = 3


def ring_positions(count: int, center: tuple[float, float], radius: float) -> list[tuple[int, int]]:
	"""Evenly spaced points on a circle, person 0 at twelve o'clock."""
	cx, cy = center
	points = []
	for i in range(count):
		angle = -math.pi / 2 + 2 * math.pi * i / count
		points.append((int(cx + radius * math.cos(angle)), int(cy + radius * math.sin(angle))))
	return points


def _flags(record: DateRecord, person: int) -> str:
	decision = record.decisions.get(person)
	if decision is None:
		return '-'
	parts = []
	if decision.again:
		parts.append('again')
	if decision.propose:
		parts.append('propose')
	if decision.incompatible:
		parts.append('never')
	return '+'.join(parts) or 'pass'


class Visualizer:
	"""Simulation state plus drawing. Kept separate from the event loop so a
	test can advance and render a full run headlessly."""

	def __init__(
		self,
		engine: Engine,
		on_round: Callable[[RoundRecord], None] | None = None,
	) -> None:
		self.engine = engine
		self.on_round = on_round
		self.record: RoundRecord | None = None
		self.playing = False
		self.speed_index = DEFAULT_SPEED_INDEX
		self.finished = engine.finished
		self.selected: int | None = None
		self.fault_log: list[tuple[int, str]] = []
		self.last_fault_round = -FAULT_FLASH_ROUNDS - 1
		self.fonts: dict[str, pygame.font.Font] = {}
		# Always-visible skip box. Digits land here; Enter jumps forward.
		# Cannot rewind: the engine has already consumed the RNG.
		self.goto_buffer = ''
		self.goto_error: str | None = None

		self.groups: dict[str, tuple[int, int, int]] = {}
		for name in engine.player_names:
			if name not in self.groups:
				self.groups[name] = GROUP_COLORS[len(self.groups) % len(GROUP_COLORS)]

		arena_w = WIDTH - PANEL_W - 3 * PAD
		top = HEADER_H + JUMP_BAR_H + PAD
		arena_h = HEIGHT - top - FOOTER_H - PAD
		self.arena = pygame.Rect(PAD, top, arena_w, arena_h)
		self.panel = pygame.Rect(self.arena.right + PAD, top, PANEL_W, arena_h)
		ring = min(arena_w, arena_h - 60) / 2 - 36
		center = (self.arena.centerx, self.arena.y + (arena_h - 60) / 2 + 6)
		self.positions = ring_positions(engine.people, center, ring)
		spacing = 2 * math.pi * ring / engine.people
		self.node_r = int(max(5, min(22, spacing * 0.38)))

	# ------------------------------------------------------------------ state

	@property
	def speed(self) -> int:
		return SPEEDS[self.speed_index]

	def advance(self) -> None:
		"""Play one round. The engine owns every rule; this only records what
		came back so the next frame can draw it."""
		record = self.engine.step()
		if record is None:
			self.finished = True
			self.playing = False
			return
		self.record = record
		for fault in record.faults:
			self.fault_log.append((record.round, fault))
			self.last_fault_round = record.round
		del self.fault_log[:-FAULT_LOG_LIMIT]
		if self.on_round is not None:
			self.on_round(record)
		if self.engine.finished:
			self.finished = True
			self.playing = False

	def toggle(self) -> None:
		if not self.finished:
			self.playing = not self.playing

	def faster(self) -> None:
		self.speed_index = min(len(SPEEDS) - 1, self.speed_index + 1)

	def slower(self) -> None:
		self.speed_index = max(0, self.speed_index - 1)

	def jump_to(self, target: int) -> None:
		"""Advance until ``target`` rounds have been played, or the run ends."""
		if target <= self.engine.round:
			self.goto_error = f'already past round {target}'
			return
		self.goto_error = None
		while not self.finished and self.engine.round < target:
			self.advance()

	def type_key(self, key: int, unicode: str) -> None:
		if unicode.isdigit() and len(self.goto_buffer) < 6:
			self.goto_buffer += unicode
		elif key == pygame.K_BACKSPACE:
			self.goto_buffer = self.goto_buffer[:-1]
		elif key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.goto_buffer:
			self.jump_to(int(self.goto_buffer))
			self.goto_buffer = ''

	def select_at(self, pos: tuple[int, int]) -> None:
		"""Select the person under ``pos``, or clear the selection."""
		reach = max(self.node_r, 8) + 3
		best = None
		for i, (x, y) in enumerate(self.positions):
			dist = math.hypot(pos[0] - x, pos[1] - y)
			if dist <= reach and (best is None or dist < best[0]):
				best = (dist, i)
		self.selected = None if best is None else best[1]

	# ------------------------------------------------------------------ drawing

	def font(self, name: str) -> pygame.font.Font:
		if not self.fonts:
			self.fonts = {
				'big': pygame.font.Font(None, 40),
				'mid': pygame.font.Font(None, 28),
				'small': pygame.font.Font(None, 22),
				'tiny': pygame.font.Font(None, 18),
			}
		return self.fonts[name]

	def text(
		self,
		surface: pygame.Surface,
		value: str,
		pos: tuple[int, int],
		name: str = 'small',
		color: tuple[int, int, int] = INK,
		anchor: str = 'topleft',
	) -> pygame.Rect:
		image = self.font(name).render(value, True, color)
		rect = image.get_rect()
		setattr(rect, anchor, pos)
		surface.blit(image, rect)
		return rect

	def draw(self, surface: pygame.Surface) -> None:
		surface.fill(BACKDROP)
		self.draw_header(surface)
		self.draw_jump_bar(surface)
		self.draw_arena(surface)
		self.draw_panel(surface)
		self.draw_footer(surface)
		if self.engine.round - self.last_fault_round < FAULT_FLASH_ROUNDS and self.fault_log:
			self.draw_banner(surface)

	def draw_header(self, surface: pygame.Surface) -> None:
		engine = self.engine
		pygame.draw.rect(surface, BACKDROP_DARK, pygame.Rect(0, 0, WIDTH, HEADER_H))
		self.text(surface, 'Marriage Market', (PAD, 14), 'big')
		params = (
			f'N={engine.people}  d={engine.dims}  m={engine.monotonic}  t={engine.rounds}  '
			f'B={engine.bonus:g}  P={engine.distribution_name}  seed={engine.seed}'
		)
		self.text(surface, params, (PAD, 50), 'small', INK_DIM)
		if self.finished:
			state, color = 'finished', GOOD
		elif self.playing:
			state, color = f'playing  {self.speed} rounds/s', WARN
		else:
			state, color = 'paused', INK_DIM
		self.text(
			surface,
			f'round {engine.round} / {engine.rounds}',
			(WIDTH - PAD, 14),
			'big',
			INK,
			'topright',
		)
		self.text(surface, state, (WIDTH - PAD, 50), 'small', color, 'topright')
		frac = engine.round / engine.rounds
		pygame.draw.rect(surface, PANEL_EDGE, pygame.Rect(0, HEADER_H - 5, WIDTH, 5))
		pygame.draw.rect(surface, GOLD, pygame.Rect(0, HEADER_H - 5, int(WIDTH * frac), 5))

	def draw_jump_bar(self, surface: pygame.Surface) -> None:
		y = HEADER_H + 10
		self.text(surface, 'Skip to round', (PAD, y + 7), 'small', INK_DIM)
		box = pygame.Rect(PAD + 120, y, 110, 30)
		pygame.draw.rect(surface, PANEL, box, border_radius=6)
		pygame.draw.rect(surface, PANEL_EDGE, box, width=2, border_radius=6)
		self.text(surface, self.goto_buffer or '#', (box.x + 10, box.y + 7), 'small', INK)
		self.text(surface, 'Enter to jump', (box.right + 12, y + 7), 'small', INK_DIM)
		if self.goto_error:
			self.text(surface, self.goto_error, (box.right + 140, y + 7), 'small', WARN)

	def draw_arena(self, surface: pygame.Surface) -> None:
		engine = self.engine
		pygame.draw.rect(surface, PANEL, self.arena, border_radius=12)
		pygame.draw.rect(surface, PANEL_EDGE, self.arena, width=2, border_radius=12)
		pos = self.positions

		done: set[int] = set()
		for i, partner in enumerate(engine.spouse):
			if partner is None or i in done:
				continue
			done.update((i, partner))
			pygame.draw.line(surface, GOLD, pos[i], pos[partner], 3)

		if self.record is not None:
			for date in self.record.dates:
				color = GOLD if date.married else STAGE_COLORS[date.how]
				width = 4 if date.married else 2
				pygame.draw.line(surface, color, pos[date.a], pos[date.b], width)
				for proposer, other in ((date.a, date.b), (date.b, date.a)):
					decision = date.decisions.get(proposer)
					if decision is not None and decision.propose and not date.married:
						x = pos[proposer][0] + (pos[other][0] - pos[proposer][0]) * 0.22
						y = pos[proposer][1] + (pos[other][1] - pos[proposer][1]) * 0.22
						pygame.draw.circle(surface, HEART, (int(x), int(y)), 5)

		r = self.node_r
		for i, (x, y) in enumerate(pos):
			color = self.groups[engine.player_names[i]]
			if engine.spouse[i] is not None:
				color = tuple(int(c * 0.6) for c in color)
			pygame.draw.circle(surface, color, (x, y), r)
			ring = GOLD if engine.spouse[i] is not None else INK_DIM
			pygame.draw.circle(surface, ring, (x, y), r, 2)
			if self.selected == i:
				pygame.draw.circle(surface, SELECT, (x, y), r + 5, 3)
			if r >= 11:
				self.text(surface, str(i), (x, y), 'tiny', BACKDROP_DARK, 'center')

		legend_y = self.arena.bottom - 46
		x = self.arena.x + 16
		for name, color in self.groups.items():
			count = engine.player_names.count(name)
			pygame.draw.circle(surface, color, (x + 7, legend_y + 9), 7)
			x = self.text(surface, f'{name} x{count}', (x + 20, legend_y + 1), 'small').right + 22
		x = self.arena.x + 16
		for stage, color in STAGE_COLORS.items():
			pygame.draw.line(surface, color, (x, legend_y + 32), (x + 22, legend_y + 32), 3)
			x = self.text(surface, stage, (x + 28, legend_y + 25), 'small', INK_DIM).right + 18
		pygame.draw.line(surface, GOLD, (x, legend_y + 32), (x + 22, legend_y + 32), 3)
		x = self.text(surface, 'married', (x + 28, legend_y + 25), 'small', INK_DIM).right + 18
		pygame.draw.circle(surface, HEART, (x + 6, legend_y + 32), 5)
		self.text(surface, 'proposed', (x + 16, legend_y + 25), 'small', INK_DIM)

	def draw_panel(self, surface: pygame.Surface) -> None:
		engine = self.engine
		panel = self.panel
		pygame.draw.rect(surface, PANEL, panel, border_radius=12)
		pygame.draw.rect(surface, PANEL_EDGE, panel, width=2, border_radius=12)
		x = panel.x + 16
		y = panel.y + 14

		married = [i for i in range(engine.people) if engine.spouse[i] is not None]
		scores = [engine.happiness(i) for i in married]
		positive = sum(1 for s in scores if s > 0)
		self.text(surface, 'Market', (x, y), 'mid')
		y += 30
		stats = [
			('single', str(len(engine.singles()))),
			('married', f'{len(married)}  ({len(engine.marriages)} couples)'),
			(
				'married happiness',
				f'{sum(scores) / len(scores):,.1f} avg' if scores else '-',
			),
			('positive so far', f'{positive} / {engine.people}'),
		]
		for label, value in stats:
			self.text(surface, label, (x, y), 'small', INK_DIM)
			self.text(surface, value, (x + 170, y), 'small')
			y += 22

		y += 10
		self.text(surface, 'This round', (x, y), 'mid')
		y += 30
		detail_h = 200 if self.selected is not None else 0
		bottom = panel.bottom - detail_h - 12
		if self.record is None:
			self.text(surface, 'press SPACE or RIGHT to start', (x, y), 'small', INK_DIM)
		else:
			lines = list(self.record.dates)
			room = max(0, (bottom - y) // 21)
			shown = lines if len(lines) <= room else lines[: max(0, room - 1)]
			for date in shown:
				color = GOLD if date.married else STAGE_COLORS[date.how]
				label = f'{date.a:>2} & {date.b:<2}  {date.how} #{date.number}'
				self.text(surface, label, (x, y), 'small', color)
				outcome = (
					'MARRIED'
					if date.married
					else (f'{_flags(date, date.a)} / {_flags(date, date.b)}')
				)
				self.text(surface, outcome, (x + 220, y), 'small', INK)
				y += 21
			if len(shown) < len(lines):
				self.text(surface, f'+{len(lines) - len(shown)} more', (x, y), 'small', INK_DIM)
				y += 21
			if self.record.unmatched:
				no_date = ', '.join(str(i) for i in self.record.unmatched)
				self.text(surface, f'no date: {no_date}', (x, y), 'small', WARN)

		if self.selected is not None:
			self.draw_person(surface, pygame.Rect(panel.x, bottom, panel.w, detail_h))

	def draw_person(self, surface: pygame.Surface, area: pygame.Rect) -> None:
		engine = self.engine
		i = self.selected
		pygame.draw.line(surface, PANEL_EDGE, (area.x + 12, area.y), (area.right - 12, area.y), 1)
		x = area.x + 16
		y = area.y + 10
		color = self.groups[engine.player_names[i]]
		self.text(surface, f'person {i}  -  {engine.player_names[i]}', (x, y), 'mid', color)
		y += 30
		ad = engine.ads[i]
		partner = engine.spouse[i]
		status = (
			f'married to {partner} in round {engine.married_on[i]}  -  happiness '
			f'{engine.happiness(i):,.1f}'
			if partner is not None
			else 'single'
		)
		rows = [
			('true', ' '.join(f'{v:>2}' for v in engine.profiles[i])),
			('ideal', ' '.join(f'{v:>2}' for v in engine.ideals[i])),
			('ad', f'own d{ad.own_dim}={ad.own_value}   seeks d{ad.seek_dim}={ad.seek_value}'),
			('status', status),
			(
				'history',
				f'{engine.dates_had[i]} dates, proposed {engine.proposals_made[i]}, '
				f'proposed to {engine.proposals_received[i]}',
			),
		]
		for label, value in rows:
			self.text(surface, label, (x, y), 'small', INK_DIM)
			self.text(surface, value, (x + 80, y), 'small')
			y += 24
		self.text(
			surface,
			f'first {engine.monotonic} dimension(s) monotonic',
			(x, y + 4),
			'tiny',
			INK_DIM,
		)

	def draw_footer(self, surface: pygame.Surface) -> None:
		pygame.draw.rect(surface, BACKDROP_DARK, pygame.Rect(0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H))
		self.text(
			surface,
			'SPACE play/pause    RIGHT/S next round    UP/DOWN speed    click a person    Q quit',
			(PAD, HEIGHT - FOOTER_H + 14),
			'small',
			INK_DIM,
		)

	def draw_banner(self, surface: pygame.Surface) -> None:
		rect = pygame.Rect(0, HEADER_H, WIDTH, BANNER_H)
		pygame.draw.rect(surface, ALERT, rect)
		round_no, fault = self.fault_log[-1]
		extra = f'  (+{len(self.fault_log) - 1} more)' if len(self.fault_log) > 1 else ''
		self.text(
			surface,
			f'FAULT round {round_no}: {fault}{extra}'[:150],
			(PAD, HEADER_H + 12),
			'small',
			ALERT_TEXT,
		)


def run_gui(engine: Engine, on_round: Callable[[RoundRecord], None] | None = None) -> None:
	pygame.init()
	pygame.display.set_caption('COMS W4444 - Marriage Market')
	screen = pygame.display.set_mode((WIDTH, HEIGHT))
	clock = pygame.time.Clock()
	view = Visualizer(engine, on_round=on_round)
	carry = 0.0

	running = True
	while running:
		dt = clock.tick(60) / 1000.0
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				running = False
			elif event.type == pygame.KEYDOWN:
				if event.key in (pygame.K_q, pygame.K_ESCAPE):
					running = False
				elif event.key == pygame.K_SPACE:
					view.toggle()
				elif event.key in (pygame.K_RIGHT, pygame.K_s):
					view.advance()
				elif event.key == pygame.K_UP:
					view.faster()
				elif event.key == pygame.K_DOWN:
					view.slower()
				else:
					view.type_key(event.key, event.unicode)
			elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				view.select_at(event.pos)

		if view.playing:
			carry += dt * view.speed
			while carry >= 1.0 and view.playing:
				carry -= 1.0
				view.advance()
		else:
			carry = 0.0

		view.draw(screen)
		pygame.display.flip()

	pygame.quit()
