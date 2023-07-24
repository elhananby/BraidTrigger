from itertools import product

import numpy as np
import pandas as pd
import pygame

from . import BaseStim


class LoomingStim(BaseStim):
    """_summary_

    Args:
        BaseStim (_type_): _description_
    """

    def __init__(self, radius, duration, position, *args, **kwargs):
        """_summary_

        Args:
            radius (_type_): _description_
            duration (_type_): _description_
            position (_type_): _description_
        """
        super(LoomingStim, self).__init__(*args, **kwargs)

        # Define stimulus parameters
        self.radius = radius
        self.duration = duration
        self.position = position

        # Define stimulus flag
        self.is_looming = False

        # Define and generate stimuli
        self.define_stimulus()
        self.generate_stimuli()

    def define_stimulus(self):
        """_summary_"""
        # Define stimulus based on parameters

        # Get radius
        if self.radius == "random":
            self.possible_radii = [32, 64]
        elif isinstance(self.radius, int):
            self.possible_radii = [self.radius]
        else:
            self.possible_radii = self.radius

        # Get duration
        if self.duration == "random":
            self.possible_durations = [300, 500]
        elif isinstance(self.duration, int):
            self.possible_durations = [self.duration]
        else:
            self.possible_durations = self.duration

        # Get position
        if self.position == "random":
            possible_x = list(range(0, self.screen.get_width(), 32))
            # possible_y = [self.screen.get_height() // 2] * len(possible_x)
            self.possible_positions = np.asarray(possible_x).T
        elif isinstance(self.position, int):
            self.possible_positions = np.asarray(self.position).T
        else:
            self.possible_positions = self.position

    def generate_stimuli(self):
        """_summary_"""
        # Stimuli combinations
        combinations = np.asarray(
            list(
                product(
                    self.possible_radii,
                    self.possible_durations,
                    self.possible_positions,
                )
            )
        )

        # Convert to pandas dataframe
        self.stimuli_df = pd.DataFrame(
            data=combinations, columns=["radius", "duration", "position"]
        )

        # Get all possible combinations in a pandas dataframe
        stimuli = []
        for index, row in self.stimuli_df.iterrows():
            stimuli.append(
                self._generate_stimulus(row["radius"], row["duration"], row["position"])
            )

        # Add stimuli to dataframe
        self.stimuli_df["stim"] = stimuli

    def _generate_stimulus(self, radius, duration, position):
        """_summary_

        Args:
            radius (_type_): _description_
            duration (_type_): _description_

        Returns:
            _type_: _description_
        """
        n_frames = int(duration / (1000 / 60))
        return np.linspace(1, radius, n_frames)

    def draw(self):
        """_summary_"""
        # Draw stimulus
        pygame.draw.circle(self.screen, self.color, (self.x, self.y), self.radius)

        # wraparound the x position if the circle goes off the screen
        if self.x - self.radius < 0:
            pygame.draw.circle(
                self.screen,
                self.color,
                (self.x + self.screen.get_width(), self.y),
                self.radius,
            )
        elif self.x + self.radius > self.screen.get_width():
            pygame.draw.circle(
                self.screen,
                self.color,
                (self.x - self.screen.get_width(), self.y),
                self.radius,
            )

    def init_loom(self):
        self.curr_loom = self.stimuli_df.sample().iloc[0]
        return True

    def loom(self):
        """_summary_

        Returns:
            _type_: _description_
        """
        # Loom stimulus
        if self.is_looming is False:
            # Get a random row from the DF
            self.curr_radius = self.curr_loom["radius"]
            self.curr_duration = self.curr_loom["duration"]

            # Get all parameters from the row
            self.x = self.curr_loom["position"]
            self.y = self.screen.get_height() // 2

            # Define our radius array as an iterator
            self.radius_array = iter(self.curr_loom["stim"])

            # And get the first value
            self.radius = next(self.radius_array)

            # set looming flag as True
            self.is_looming = True

        # Otherwise, if we started the looming alread
        else:
            try:
                # Get the next value from the iterator
                self.radius = next(self.radius_array)
                self.draw()
                return True

            except StopIteration:
                # If the iterator is exhausted, reset the radius and set the looming flag to False  # noqa: E501
                self.radius = 0
                self.is_looming = False
                self.draw()
                return False