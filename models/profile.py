"""Profiles, the value distribution P, and the happiness arithmetic.

Everything here is public knowledge. The handout gives every player the
scoring formula, so ``decrement`` and ``happiness`` are importable from player
code; what a player does not get is anybody else's true profile, nor the
distribution P a given simulation drew its people from.
"""

import json
import math
import random
from pathlib import Path

MIN_VALUE = 0
MAX_VALUE = 10
VALUES = tuple(range(MIN_VALUE, MAX_VALUE + 1))

Profile = tuple[int, ...]
Distribution = tuple[tuple[float, ...], ...]

PRESETS = ('uniform', 'normal', 'mixed')

# Rows of P are allowed this much slack when checking they sum to 1, so a
# hand-written config with values like 0.1 x 10 + 0.0 does not trip on float
# rounding.
SUM_TOLERANCE = 1e-6


def uniform_row() -> tuple[float, ...]:
	return tuple(1.0 / len(VALUES) for _ in VALUES)


def normal_row(mean: float = 5.0, sd: float = 2.0) -> tuple[float, ...]:
	"""A discretised normal over 0-10, renormalised so the row sums to 1."""
	weights = [math.exp(-((v - mean) ** 2) / (2 * sd * sd)) for v in VALUES]
	total = sum(weights)
	return tuple(w / total for w in weights)


def build_distribution(name: str, dims: int, monotonic: int) -> Distribution:
	"""One of the named presets.

	``mixed`` is the default and the one closest to the handout's description:
	monotonic dimensions are roughly normal (most people are middling, a 10 is
	rare), and the remaining dimensions alternate between uniform and normal.
	"""
	if name == 'uniform':
		return tuple(uniform_row() for _ in range(dims))
	if name == 'normal':
		return tuple(normal_row() for _ in range(dims))
	if name == 'mixed':
		rows = []
		for i in range(dims):
			if i < monotonic:
				rows.append(normal_row(5.0, 2.0))
			elif (i - monotonic) % 2 == 0:
				rows.append(uniform_row())
			else:
				rows.append(normal_row(5.0, 2.5))
		return tuple(rows)
	raise ValueError(f'unknown distribution {name!r}; choose one of {", ".join(PRESETS)}')


def validate_distribution(rows: object, dims: int) -> Distribution:
	"""Check P is a d x 11 table of probabilities whose rows each sum to 1."""
	table = tuple(tuple(float(p) for p in row) for row in rows)
	if len(table) != dims:
		raise ValueError(f'P must have one row per dimension: expected {dims}, got {len(table)}')
	for i, row in enumerate(table):
		if len(row) != len(VALUES):
			raise ValueError(f'P[{i}] must have {len(VALUES)} entries (values 0-10)')
		if any(p < 0 for p in row):
			raise ValueError(f'P[{i}] has a negative probability')
		if abs(sum(row) - 1.0) > SUM_TOLERANCE:
			raise ValueError(f'P[{i}] sums to {sum(row):g}, not 1')
	return table


def load_distribution(path: str | Path, dims: int) -> Distribution:
	"""Read P from JSON: either a bare list of rows or ``{"P": [...]}``."""
	raw = json.loads(Path(path).read_text())
	rows = raw['P'] if isinstance(raw, dict) else raw
	return validate_distribution(rows, dims)


def sample_profile(rng: random.Random, distribution: Distribution) -> Profile:
	return tuple(rng.choices(VALUES, weights=row)[0] for row in distribution)


def decrement(desired: Profile, partner: Profile, monotonic: int) -> int:
	"""How far ``partner``'s true profile falls short of ``desired``.

	The first ``monotonic`` dimensions only count a shortfall: if the partner
	meets or beats what was wanted there is no penalty. Every other dimension
	is penalised by the squared distance in either direction.
	"""
	total = 0
	for i, (want, have) in enumerate(zip(desired, partner, strict=True)):
		gap = want - have
		if i < monotonic and gap <= 0:
			continue
		total += gap * gap
	return total


def happiness(
	bonus: float,
	own_profile: Profile,
	own_ideal: Profile,
	partner_profile: Profile,
	partner_ideal: Profile,
	monotonic: int,
) -> float:
	"""A married person's final score: the bonus, minus their own decrement,
	minus half of their partner's."""
	mine = decrement(own_ideal, partner_profile, monotonic)
	theirs = decrement(partner_ideal, own_profile, monotonic)
	return bonus - mine - theirs / 2
