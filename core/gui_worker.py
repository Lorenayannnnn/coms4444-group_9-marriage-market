"""Run dating and logging in a spawned process, with one request in flight.

Only display state crosses the process boundary, never student instances.
The worker's main thread retains SIGALRM support for player timeouts.
"""

import multiprocessing as mp
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field, replace
from queue import Empty

from core.engine import Engine
from core.runlog import RunLog
from models.player import Decision


@dataclass(frozen=True)
class ParticipantDate:
	round: int
	partner: int
	how: str
	number: int
	shown: tuple
	observed: tuple
	stated: tuple
	partner_stated: tuple
	decision: Decision
	partner_decision: Decision
	married: bool
	again: bool

	@classmethod
	def from_record(cls, record, date, person):
		partner = date.b if person == date.a else date.a
		return cls(
			record.round,
			partner,
			date.how,
			date.number,
			date.shown[person],
			date.shown[partner],
			date.stated[person],
			date.stated[partner],
			date.decisions[person],
			date.decisions[partner],
			date.married,
			date.again,
		)


@dataclass
class DisplayState:
	people: int
	dims: int
	monotonic: int
	rounds: int
	bonus: float
	seed: int
	distribution_name: str
	profiles: list
	ideals: list
	ads: list
	player_names: list
	round: int
	spouse: list
	married_on: list
	marriages: list
	dates_had: list
	proposals_made: list
	proposals_received: list
	scores: list
	finished: bool
	own_decrements: list
	participant: int = 0
	history: list = field(default_factory=list)

	@classmethod
	def from_engine(cls, engine, participant=0, history=None):
		return cls(
			**{
				name: getattr(engine, name)
				for name in cls.__dataclass_fields__
				if name not in ('scores', 'own_decrements', 'participant', 'history')
			},
			scores=[engine.happiness(i) for i in range(engine.people)],
			own_decrements=[engine.own_decrement(i) for i in range(engine.people)],
			participant=participant,
			history=history or [],
		)

	def singles(self):
		return [i for i, partner in enumerate(self.spouse) if partner is None]

	def happiness(self, index):
		return self.scores[index]

	def own_decrement(self, index):
		return self.own_decrements[index]


def _run(options, log_path, commands, responses, stop, cancel_jump, selection):
	engine = None
	log = None
	try:
		engine = Engine(**options)
		histories = [[] for _ in range(engine.people)]

		def snapshot():
			person = selection.value
			return DisplayState.from_engine(engine, person, histories[person])

		if log_path is not None:
			try:
				log = RunLog.create(log_path, engine)
			except OSError as exc:
				print(f'warning: could not write log - {exc}', file=sys.stderr)
			else:
				print(f'log: {log.path}\ncsv: {log.csv_path}', file=sys.stderr)
		responses.put(('ready', snapshot(), None))
		while not stop.is_set():
			try:
				command, target = commands.get(timeout=0.1)
			except Empty:
				continue
			if stop.is_set():
				break
			if command == 'inspect':
				responses.put(('inspect', snapshot(), None))
				continue
			target = engine.round + 1 if target is None else min(target, engine.rounds)
			record = None
			while not engine.finished and engine.round < target:
				record = engine.step()
				for date in record.dates:
					for person in (date.a, date.b):
						histories[person].append(ParticipantDate.from_record(record, date, person))
				if log is not None:
					log.record_round(record, engine)
				if stop.is_set() or cancel_jump.is_set():
					break
			# Interest lists can be quadratic in N; they belong in logs, not frames.
			shown = replace(record, interest={}) if record is not None else None
			responses.put(('round', snapshot(), shown))
	except Exception as exc:
		responses.put(('error', f'{type(exc).__name__}: {exc}', None))
	finally:
		if log is not None:
			log.finish(engine)


class SimulationWorker:
	def __init__(self, options: dict, log_path: str | None = None):
		context = mp.get_context('spawn')
		self.commands = context.Queue(maxsize=1)
		self.responses = context.Queue(maxsize=2)
		self.stop = context.Event()
		self.cancel_jump = context.Event()
		self.selection = context.Value('i', 0)
		self.process = context.Process(
			target=_run,
			args=(
				options,
				log_path,
				self.commands,
				self.responses,
				self.stop,
				self.cancel_jump,
				self.selection,
			),
		)
		self.pending = False
		self.ready = False
		self.closed = False
		self.process.start()

	def request(self, target: int | None = None):
		if self.ready and not self.pending and not self.closed:
			self.cancel_jump.clear()
			self.commands.put_nowait(('advance', target))
			self.pending = True

	def inspect(self, participant):
		self.selection.value = participant
		if self.ready and not self.pending and not self.closed:
			self.commands.put_nowait(('inspect', None))
			self.pending = True

	def poll(self):
		try:
			message = self.responses.get_nowait()
		except Empty:
			if not self.closed and not self.process.is_alive():
				raise RuntimeError(
					f'Simulation worker exited (code {self.process.exitcode})'
				) from None
			return None
		if message[0] == 'error':
			raise RuntimeError(f'Simulation worker: {message[1]}')
		self.ready = True
		self.pending = False
		return message

	def close(self, grace: float = 5.0):
		"""Finish an in-flight round after closing the window, then release IPC.

		An unresponsive player (e.g. timeout disabled) cannot orphan a worker.
		On forced termination, already flushed round logs remain readable.
		"""
		if self.closed:
			return
		self.closed = True
		self.stop.set()
		deadline = time.monotonic() + grace
		while self.process.is_alive() and time.monotonic() < deadline:
			# Drain snapshots so the child queue feeder can finish on shutdown.
			with suppress(Empty):
				self.responses.get(timeout=0.02)
			self.process.join(timeout=0.02)
		if self.process.is_alive():
			self.process.terminate()
			self.process.join(timeout=1)
			if self.process.is_alive():
				self.process.kill()
				self.process.join(timeout=1)
			print(
				'warning: worker stopped before completing a round; logs contain flushed rounds',
				file=sys.stderr,
			)
		self.commands.close()
		self.responses.close()
		self.commands.join_thread()
		self.responses.join_thread()
