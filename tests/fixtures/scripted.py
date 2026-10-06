from collections.abc import Callable
from typing import Any

from models.player import Decision
from models.player import Player as BasePlayer


def scripted(
	name: str = 'Scripted',
	*,
	likes: Callable[[Any, tuple, Any], Any] | None = None,
	decide: Callable[[Any, Any, tuple, tuple], Any] | None = None,
	project: Callable[[Any, Any], Any] | None = None,
	describe: Callable[[Any, Any, tuple], Any] | None = None,
	advertise: Callable[[Any], Any] | None = None,
	init: Callable[[Any], None] | None = None,
	log: list | None = None,
) -> type[BasePlayer]:
	"""A Player subclass driven by the given callables.

	Each callable receives the player instance first, so it can read
	``self.index`` or ``self.profile``. Anything left out keeps the base
	class's honest default; ``likes`` defaults to nobody and ``decide`` to
	``Decision()``. Every call is appended to ``log`` as ``(index, method,
	args)`` when one is given.
	"""

	def record(self, method: str, *args: Any) -> None:
		if log is not None:
			log.append((self.index, method, args))

	class Scripted(BasePlayer):
		def __init__(self, snapshot, ctx) -> None:
			super().__init__(snapshot, ctx)
			if init is not None:
				init(self)

		def advertise(self):
			record(self, 'advertise')
			if advertise is None:
				return super().advertise()
			return advertise(self)

		def choose_dates(self, candidates, turn):
			record(self, 'choose_dates', candidates, turn)
			return () if likes is None else likes(self, candidates, turn)

		def project(self, date):
			record(self, 'project', date)
			return self.profile if project is None else project(self, date)

		def describe_ideal(self, date, observed):
			record(self, 'describe_ideal', date, observed)
			return self.ideal if describe is None else describe(self, date, observed)

		def decide(self, date, observed, stated_ideal):
			record(self, 'decide', date, observed, stated_ideal)
			if decide is None:
				return Decision()
			return decide(self, date, observed, stated_ideal)

		def on_outcome(self, outcome):
			record(self, 'on_outcome', outcome)

	Scripted.__name__ = name
	Scripted.__qualname__ = name
	return Scripted


def always_again(self, date, observed, stated):
	return Decision(again=True)


def propose_when_allowed(self, date, observed, stated):
	return Decision(again=True, propose=date.date_number >= 2)
