import random
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from models.profile import Profile


@dataclass(frozen=True)
class PlayerSnapshot:
	"""Private, per-person information handed over at construction.

	``profile`` is your true profile T_p and ``ideal`` is your desired profile
	D_p. Nobody else ever sees either of them.
	"""

	id: uuid.UUID
	index: int
	profile: Profile
	ideal: Profile


@dataclass(frozen=True)
class GameContext:
	"""Public simulation parameters. Every player sees the same values.

	Per the spec, players know N, d, m, t and B. They do NOT know the
	distribution P that profiles were drawn from.
	"""

	people: int
	dims: int
	monotonic: int
	rounds: int
	bonus: float


@dataclass(frozen=True)
class Advertisement:
	"""What a person posts about themselves, fixed for the whole simulation.

	One of their own characteristics (``own_dim`` = ``own_value``) and one of
	the characteristics they are looking for (``seek_dim`` = ``seek_value``).
	Neither half has to be true.
	"""

	own_dim: int
	own_value: int
	seek_dim: int
	seek_value: int


@dataclass(frozen=True)
class Candidate:
	"""Somebody you could ask for a date this round.

	``dates`` is how many times the two of you have dated so far. The list of
	candidates never includes anyone you have marked incompatible; it can
	include people who have marked *you* incompatible, because you are not told
	about that. The simulator will simply never pair you with them.
	"""

	index: int
	ad: Advertisement
	dates: int


@dataclass(frozen=True)
class RoundContext:
	"""What you know at the start of a round, before dates are assigned."""

	round: int
	rounds_left: int
	singles: int


@dataclass(frozen=True)
class DateContext:
	"""The date you are on right now.

	``date_number`` counts this date: it is 1 on a first date and 2 on the
	first date at which a proposal is allowed. ``repeat`` is True when both of
	you asked for this date at the end of your previous one.
	"""

	round: int
	rounds_left: int
	partner: int
	partner_ad: Advertisement
	date_number: int
	repeat: bool


@dataclass(frozen=True)
class Decision:
	"""What you want after a date.

	again         ask for another date with this person next round
	propose       propose marriage (only legal from the second date on)
	incompatible  never be matched with this person again
	"""

	again: bool = False
	propose: bool = False
	incompatible: bool = False


@dataclass(frozen=True)
class DateOutcome:
	"""What you learn once both sides of a date have decided.

	``partner_proposed`` is the handout's "the recipient of the proposal now
	knows". ``again`` is True only when you *both* asked for another date, in
	which case you are paired first next round. A one-sided request for
	another date is not revealed.
	"""

	round: int
	partner: int
	date_number: int
	partner_proposed: bool
	married: bool
	again: bool


class Player(ABC):
	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		self.id = snapshot.id
		# A private random stream per person; never use the engine's pairing RNG.
		self.rng = random.Random(snapshot.id.int)
		self.index = snapshot.index
		self.name = type(self).__name__
		self.profile = snapshot.profile
		self.ideal = snapshot.ideal
		self.people = ctx.people
		self.dims = ctx.dims
		self.monotonic = ctx.monotonic
		self.rounds = ctx.rounds
		self.bonus = ctx.bonus

	def __repr__(self) -> str:
		return f'{self.name}(index={self.index})'

	def advertise(self) -> Advertisement:
		"""Called once, before round 1. The answer is fixed for the whole run.

		The default is honest and uninspired: dimension 0, both halves true.
		"""
		return Advertisement(
			own_dim=0, own_value=self.profile[0], seek_dim=0, seek_value=self.ideal[0]
		)

	@abstractmethod
	def choose_dates(self, candidates: tuple[Candidate, ...], turn: RoundContext) -> Iterable[int]:
		"""Name the people you would be interested in dating this round.

		Return any subset of ``candidate.index`` values, possibly empty. People
		already paired by a mutual repeat request are not asked.
		"""

	def project(self, date: DateContext) -> Profile:
		"""The profile your behaviour projects on this date. Default: the truth."""
		return self.profile

	def describe_ideal(self, date: DateContext, observed: Profile) -> Profile:
		"""At the end of the date, the ideal partner you describe to your date.

		``observed`` is the profile your date projected. Default: the truth.
		"""
		return self.ideal

	@abstractmethod
	def decide(self, date: DateContext, observed: Profile, stated_ideal: Profile) -> Decision:
		"""After the date: ask again, propose, or mark them incompatible.

		``observed`` is what they projected during the date and
		``stated_ideal`` is the ideal partner they described at the end of it.
		"""

	def on_outcome(self, outcome: DateOutcome) -> None:
		"""Told what happened once both sides decided. Optional to override."""
		return None
