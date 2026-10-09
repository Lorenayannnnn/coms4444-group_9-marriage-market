"""Importable players for spawn-process integration checks."""

import os
import time

from models.player import Decision, Player


class SlowPlayer(Player):
	def choose_dates(self, candidates, turn):
		time.sleep(0.3)
		return [c.index for c in candidates]

	def decide(self, date, observed, stated_ideal):
		return Decision()


class ExitingPlayer(SlowPlayer):
	def choose_dates(self, candidates, turn):
		os._exit(3)
