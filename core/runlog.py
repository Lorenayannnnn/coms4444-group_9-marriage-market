"""Per-run debug log for students.

The engine never opens a file. ``main.py`` constructs a ``RunLog`` and hands
``record_round`` to ``Engine.run`` / the visualiser as an ``on_round``
callback, so sweeps and the tournament - which never go through ``main.py`` -
stay silent.

Written incrementally, one round at a time, so a crash or a GUI quit still
leaves everything that did run. The log is a post-hoc view of the run,
including everybody's true profile: it is for reading after the fact, not a
new channel into player code.
"""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from core.engine import DateRecord, Engine, RoundRecord
from models.player import Decision

DEFAULT_DIR = Path('logs')


def default_path(seed: int) -> Path:
	stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
	return DEFAULT_DIR / f'marriage-{stamp}-seed{seed}.log'


def _join(values: tuple[object, ...] | list[object]) -> str:
	return ','.join(str(v) for v in values) if values else '-'


def _decision(decision: Decision | None) -> str:
	if decision is None:
		return '-'
	flags = [
		name
		for name, on in (
			('again', decision.again),
			('propose', decision.propose),
			('incompatible', decision.incompatible),
		)
		if on
	]
	return '+'.join(flags) or 'pass'


class RunLog:
	"""Append-only text log of a single ``main.py`` run."""

	def __init__(self, path: Path, stream: TextIO) -> None:
		self.path = path
		self._stream = stream
		self._closed = False

	@classmethod
	def create(cls, path: str, engine: Engine) -> 'RunLog':
		target = Path(path) if path else default_path(engine.seed)
		target.parent.mkdir(parents=True, exist_ok=True)
		stream = target.open('w', encoding='utf-8')
		log = cls(target, stream)
		log._write_header(engine)
		return log

	def _write(self, text: str) -> None:
		self._stream.write(text)
		if not text.endswith('\n'):
			self._stream.write('\n')
		self._stream.flush()

	def _write_header(self, engine: Engine) -> None:
		self._write('marriage market debug log')
		self._write(
			f'seed={engine.seed}  N={engine.people}  d={engine.dims}  m={engine.monotonic}  '
			f't={engine.rounds}  B={engine.bonus:g}  P={engine.distribution_name}  '
			f'timeout={engine.timeout}'
		)
		self._write('people:')
		for i, name in enumerate(engine.player_names):
			ad = engine.ads[i]
			self._write(
				f'  [{i}] {name}  true {_join(engine.profiles[i])}  '
				f'ideal {_join(engine.ideals[i])}  '
				f'ad own d{ad.own_dim}={ad.own_value} seek d{ad.seek_dim}={ad.seek_value}'
			)
		self._write('')

	def record_round(self, record: RoundRecord, engine: Engine) -> None:
		"""One block per round: interest lists, then each date in pairing order."""
		lines = [
			f'round {record.round}  singles {len(record.singles)}  '
			f'married {engine.people - len(engine.singles())}'
		]
		for index, chosen in sorted(record.interest.items()):
			lines.append(f'  [{index}] {engine.player_names[index]} likes {_join(chosen)}')
		for date in record.dates:
			lines.append(_date_line(date))
		for a, b in record.marriages:
			lines.append(
				f'  MARRIED {a} & {b}  happiness {engine.happiness(a):,.1f} / '
				f'{engine.happiness(b):,.1f}'
			)
		if record.unmatched:
			lines.append(f'  no date: {_join(record.unmatched)}')
		for fault in record.faults:
			lines.append(f'  FAULT {fault}')
		self._write('\n'.join(lines))
		self._write('')

	def finish(self, engine: Engine) -> None:
		if self._closed:
			return
		self._write(f'======== snapshot after round {engine.round} / {engine.rounds} ========')
		self._write(json.dumps(engine.results(), indent=2))
		self._stream.close()
		self._closed = True

	def close(self) -> None:
		if not self._closed:
			self._stream.close()
			self._closed = True


def _date_line(date: DateRecord) -> str:
	parts = [f'  date {date.a}<->{date.b} ({date.how}, #{date.number})']
	for p in (date.a, date.b):
		parts.append(
			f'{p} shows {_join(date.shown.get(p, ()))} seeks {_join(date.stated.get(p, ()))} '
			f'-> {_decision(date.decisions.get(p))}'
		)
	if date.again:
		parts.append('again')
	return '  |  '.join(parts)


def bind(log: RunLog, engine: Engine) -> Callable[[RoundRecord], None]:
	"""Adapt ``record_round`` to the one-argument ``on_round`` callback."""

	def on_round(record: RoundRecord) -> None:
		log.record_round(record, engine)

	return on_round
