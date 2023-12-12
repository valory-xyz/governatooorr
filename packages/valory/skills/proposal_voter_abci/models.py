# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This module contains the shared state for the abci skill of ProposalVoterAbciApp."""

from datetime import datetime
from typing import Any

from aea.skills.base import SkillContext

from packages.valory.skills.abstract_round_abci.models import ApiSpecs, BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.proposal_voter_abci.rounds import ProposalVoterAbciApp


class MechCalls:
    """Mech call window."""

    def __init__(
        self,
        mech_call_window_size: float,
        mech_calls_allowed_in_window: int,
    ) -> None:
        """Initialize object."""
        self._calls_made_in_window = 0
        self._calls_allowed_in_window = mech_calls_allowed_in_window
        self._call_window_size = mech_call_window_size
        self._call_window_start = datetime.now().timestamp()

    def increase_call_count(self) -> None:
        """Increase call count."""
        self._calls_made_in_window += 1

    def has_window_expired(self, current_time: float) -> bool:
        """Increase tweet count."""
        return current_time > (self._call_window_start + self._call_window_size)

    def max_calls_reached(self) -> bool:
        """Increase tweet count."""
        return self._calls_made_in_window >= self._calls_allowed_in_window

    def reset(self, current_time: float) -> None:
        """Reset the window if required.."""
        if not self.has_window_expired(current_time=current_time):
            return
        self._calls_made_in_window = 0
        self._call_window_start = current_time


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = ProposalVoterAbciApp

    def __init__(
        self,
        *args: Any,
        skill_context: SkillContext,
        **kwargs: Any,
    ) -> None:
        """Initialize the state."""
        super().__init__(*args, skill_context=skill_context, **kwargs)


class Params(BaseParams):
    """Parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters object."""
        self.voting_block_threshold = self._ensure(
            "voting_block_threshold", kwargs, int
        )
        self.voting_seconds_threshold = self._ensure(
            "voting_seconds_threshold", kwargs, int
        )
        self.signmessagelib_address = self._ensure(
            "signmessagelib_address", kwargs, str
        )
        self.snapshot_vote_endpoint = self._ensure(
            "snapshot_vote_endpoint", kwargs, str
        )
        self.tally_api_call_sleep_seconds = kwargs.get(
            "tally_api_call_sleep_seconds", 15
        )
        self.default_snapshot_vote_on_error = self._ensure(
            "default_snapshot_vote_on_error", kwargs, bool
        )
        self.default_tally_vote_on_error = self._ensure(
            "default_tally_vote_on_error", kwargs, bool
        )
        self.mech_call_window_size = kwargs.get("mech_call_window_size")
        self.mech_calls_allowed_in_window = kwargs.get("mech_calls_allowed_in_window")
        self.mech_calls = MechCalls(
            mech_call_window_size=self.mech_call_window_size,
            mech_calls_allowed_in_window=self.mech_calls_allowed_in_window,
        )
        self.voter_safe_address = kwargs.get(
            "voter_safe_address", "0x0000000000000000000000000000000000000000"
        )
        self.safe_contract_address_copy = kwargs.get(
            "safe_contract_address_copy", "0x0000000000000000000000000000000000000000"
        )
        super().__init__(*args, **kwargs)


class RandomnessApi(ApiSpecs):
    """A model that wraps ApiSpecs for randomness api specifications."""


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool
