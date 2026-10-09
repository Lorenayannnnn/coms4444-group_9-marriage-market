"""Per-run debug log for students.

The engine never opens a file. ``main.py`` constructs a ``RunLog`` and hands
``record_round`` to ``Engine.run`` / the visualiser as an ``on_round``
callback, so sweeps - which never go through ``main.py`` - stay silent.

Written incrementally, one round at a time, so a crash or a GUI quit still
leaves everything that did run. The log is a post-hoc view of the run,
including everybody's true profile: it is for reading after the fact, not a
new channel into player code.
"""

import csv
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from core.engine import DateRecord, Engine, RoundRecord
from models.player import Decision

DEFAULT_DIR = Path('logs')


def default_path(seed: int) -> Path:
	stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
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
		self.csv_path = (
			path.with_suffix('.csv')
			if path.suffix != '.csv'
			else path.with_name(path.stem + '-events.csv')
		)
		self._csv_stream = self.csv_path.open('w', encoding='utf-8-sig', newline='')
		self._csv = None

	@classmethod
	def create(cls, path: str, engine: Engine) -> 'RunLog':
		target = Path(path) if path else default_path(engine.seed)
		target.parent.mkdir(parents=True, exist_ok=True)
		stream = target.open('w', encoding='utf-8')
		log = cls(target, stream)
		log._write_header(engine)
		log._start_csv(engine)
		log.flush()
		return log

	def _start_csv(self, engine: Engine) -> None:
		fields = [
			'event',
			'round',
			'person',
			'player',
			'partner',
			'pairing',
			'date_number',
			'interested_in',
			'again_requested',
			'proposed',
			'incompatible',
			'mutual_again',
			'married',
			'happiness',
			'own_decrement',
			'partner_decrement',
			'fault',
			'own_ad_dim',
			'own_ad_value',
			'seek_ad_dim',
			'seek_ad_value',
			'seed',
			'N',
			'd',
			'm',
			't',
			'B',
			'distribution',
			'list_multiple',
			'list_limit',
			'candidate_policy',
		]
		fields += [
			f'{name}_{i}'
			for name in (
				'true',
				'ideal',
				'projected',
				'observed',
				'stated_ideal',
				'partner_stated_ideal',
			)
			for i in range(engine.dims)
		]
		self._csv = csv.DictWriter(self._csv_stream, fieldnames=fields)
		self._csv.writeheader()
		self._parameters = dict(
			seed=engine.seed,
			N=engine.people,
			d=engine.dims,
			m=engine.monotonic,
			t=engine.rounds,
			B=engine.bonus,
			distribution=engine.distribution_name,
			list_multiple=engine.list_multiple,
			list_limit=engine.list_limit,
			candidate_policy='all',
		)
		for i in range(engine.people):
			ad = engine.ads[i]
			self._csv_row(
				engine,
				'person',
				0,
				i,
				own_ad_dim=ad.own_dim,
				own_ad_value=ad.own_value,
				seek_ad_dim=ad.seek_dim,
				seek_ad_value=ad.seek_value,
			)
		for fault in engine.results()['faults']:
			self._csv_row(engine, 'fault', 0, fault=fault)

	def _csv_row(
		self, engine: Engine, event: str, round_no: int, person: int | None = None, **values
	) -> None:
		row = dict(self._parameters, event=event, round=round_no, **values)
		if person is not None:
			row.update(person=person, player=engine.player_names[person])
			for name, profile in (
				('true', engine.profiles[person]),
				('ideal', engine.ideals[person]),
			):
				row.update({f'{name}_{i}': value for i, value in enumerate(profile)})
		self._csv.writerow(row)

	def _write(self, text: str) -> None:
		self._stream.write(text)
		if not text.endswith('\n'):
			self._stream.write('\n')

	def flush(self) -> None:
		"""Publish a complete header/round, rather than flushing every row."""
		self._stream.flush()
		self._csv_stream.flush()

	def _write_header(self, engine: Engine) -> None:
		self._write('marriage market debug log')
		self._write(
			f'seed={engine.seed}  N={engine.people}  d={engine.dims}  m={engine.monotonic}  '
			f't={engine.rounds}  B={engine.bonus:g}  P={engine.distribution_name}  '
			f'timeout={engine.timeout}  list_multiple={engine.list_multiple:g}  list_limit={engine.list_limit}  candidates=all'
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
		for person, chosen in sorted(record.interest.items()):
			self._csv_row(engine, 'interest', record.round, person, interested_in=_join(chosen))
		for date in record.dates:
			for person, partner in ((date.a, date.b), (date.b, date.a)):
				decision = date.decisions[person]
				values = dict(
					partner=partner,
					pairing=date.how,
					date_number=date.number,
					again_requested=decision.again,
					proposed=decision.propose,
					incompatible=decision.incompatible,
					mutual_again=date.again,
					married=date.married,
				)
				for name, profile in (
					('projected', date.shown[person]),
					('observed', date.shown[partner]),
					('stated_ideal', date.stated[person]),
					('partner_stated_ideal', date.stated[partner]),
				):
					values.update({f'{name}_{i}': value for i, value in enumerate(profile)})
				self._csv_row(engine, 'date', record.round, person, **values)
		for person in record.unmatched:
			self._csv_row(engine, 'unmatched', record.round, person)
		for fault in record.faults:
			self._csv_row(engine, 'fault', record.round, fault=fault)
		self.flush()

	def finish(self, engine: Engine) -> None:
		if self._closed:
			return
		self._write(f'======== snapshot after round {engine.round} / {engine.rounds} ========')
		self._write(json.dumps(engine.results(), indent=2))
		for person in engine.results()['players']:
			self._csv_row(
				engine,
				'result',
				engine.round,
				person['index'],
				partner=person['partner'],
				married=person['married'],
				happiness=person['happiness'],
				own_decrement=person['own_decrement'],
				partner_decrement=person['partner_decrement'],
			)
		self._stream.close()
		self._csv_stream.close()
		self._closed = True

	def close(self) -> None:
		if not self._closed:
			self._stream.close()
			self._csv_stream.close()
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
