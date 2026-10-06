import random

from models.player import (
	Advertisement,
	Candidate,
	DateContext,
	Decision,
	GameContext,
	PlayerSnapshot,
	RoundContext,
)
from models.player import Player as BasePlayer
from models.profile import MAX_VALUE, MIN_VALUE, Profile


class RandomPlayer(BasePlayer):
	"""Posts a random advertisement, asks out a random half of the room, and
	proposes at random once it is allowed to. Behaves and describes itself
	honestly, because that is the default. The do-nothing baseline: any real
	strategy should marry better than it does."""

	def __init__(self, snapshot: PlayerSnapshot, ctx: GameContext) -> None:
		super().__init__(snapshot, ctx)

	def advertise(self) -> Advertisement:
		return Advertisement(
			own_dim=random.randrange(self.dims),
			own_value=random.randint(MIN_VALUE, MAX_VALUE),
			seek_dim=random.randrange(self.dims),
			seek_value=random.randint(MIN_VALUE, MAX_VALUE),
		)

	def choose_dates(self, candidates: tuple[Candidate, ...], turn: RoundContext) -> list[int]:
		return [c.index for c in candidates if random.random() < 0.5]

	def decide(self, date: DateContext, observed: Profile, stated_ideal: Profile) -> Decision:
		propose = date.date_number >= 2 and random.random() < 0.25
		return Decision(again=random.random() < 0.5, propose=propose)
