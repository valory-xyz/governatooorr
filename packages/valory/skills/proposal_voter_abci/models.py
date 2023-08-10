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

from dataclasses import dataclass
from typing import Any, Optional, Union

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


@dataclass
class PendingVote:
    """Represents a proposal vote that is pending to be submitted and verified."""

    proposal_id: str
    vote_choice: Union[str, int]
    is_snapshot: bool  # onchain or snapshot


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
        self.pending_vote: Optional[PendingVote] = None


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
        self.snapshot_vote_endpoint = kwargs.get(
            "snapshot_vote_endpoint", "https://relayer.snapshot.org/"
        )
        self.tally_api_call_sleep_seconds = kwargs.get(
            "tally_api_call_sleep_seconds", 2
        )
        super().__init__(*args, **kwargs)


class RandomnessApi(ApiSpecs):
    """A model that wraps ApiSpecs for randomness api specifications."""


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool
