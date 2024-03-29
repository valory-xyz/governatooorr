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

"""This module contains the shared state for the abci skill of Governatooorr."""

from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.ceramic_read_abci.models import (
    Params as CeramicReadAbciParams,
)
from packages.valory.skills.ceramic_read_abci.rounds import Event as CeramicReadEvent
from packages.valory.skills.ceramic_write_abci.models import (
    Params as CeramicWriteAbciParams,
)
from packages.valory.skills.ceramic_write_abci.rounds import Event as CeramicWriteEvent
from packages.valory.skills.governatooorr_abci.composition import GovernatooorrAbciApp
from packages.valory.skills.mech_interact_abci.models import (
    MechResponseSpecs as BaseMechResponseSpecs,
)
from packages.valory.skills.mech_interact_abci.models import (
    Params as MechInteractAbciParams,
)
from packages.valory.skills.mech_interact_abci.rounds import Event as MechInteractEvent
from packages.valory.skills.proposal_collector_abci.models import (
    Params as ProposalCollectorAbciParams,
)
from packages.valory.skills.proposal_collector_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    Event as ProposalCollectorEvent,
)
from packages.valory.skills.proposal_voter_abci.models import (
    Params as ProposalVoterAbciParams,
)
from packages.valory.skills.proposal_voter_abci.rounds import (
    Event as ProposalVoterEvent,
)
from packages.valory.skills.reset_pause_abci.rounds import Event as ResetPauseEvent
from packages.valory.skills.termination_abci.models import TerminationParams


ProposalCollectorParams = ProposalCollectorAbciParams
ProposalVoterParams = ProposalVoterAbciParams
CeramicReadParams = CeramicReadAbciParams
CeramicWriteParams = CeramicWriteAbciParams
MechInteractParams = MechInteractAbciParams

Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool
MechResponseSpecs = BaseMechResponseSpecs


class RandomnessApi(ApiSpecs):
    """A model that wraps ApiSpecs for randomness api specifications."""


MARGIN = 5
MULTIPLIER = 10


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = GovernatooorrAbciApp

    def setup(self) -> None:
        """Set up."""
        super().setup()
        GovernatooorrAbciApp.event_to_timeout[
            CeramicReadEvent.ROUND_TIMEOUT
        ] = self.context.params.round_timeout_seconds
        GovernatooorrAbciApp.event_to_timeout[ProposalCollectorEvent.ROUND_TIMEOUT] = (
            self.context.params.round_timeout_seconds * MULTIPLIER
        )
        GovernatooorrAbciApp.event_to_timeout[
            CeramicWriteEvent.ROUND_TIMEOUT
        ] = self.context.params.round_timeout_seconds
        GovernatooorrAbciApp.event_to_timeout[ProposalVoterEvent.ROUND_TIMEOUT] = (
            self.context.params.round_timeout_seconds * MULTIPLIER
        )
        GovernatooorrAbciApp.event_to_timeout[
            ResetPauseEvent.ROUND_TIMEOUT
        ] = self.context.params.round_timeout_seconds
        GovernatooorrAbciApp.event_to_timeout[
            ResetPauseEvent.RESET_AND_PAUSE_TIMEOUT
        ] = (self.context.params.reset_pause_duration + MARGIN)
        GovernatooorrAbciApp.event_to_timeout[
            MechInteractEvent.ROUND_TIMEOUT
        ] = self.context.params.round_timeout_seconds


class Params(
    CeramicReadParams,
    ProposalCollectorParams,
    CeramicWriteParams,
    ProposalVoterParams,
    MechInteractParams,
    TerminationParams,
):
    """A model to represent params for multiple abci apps."""
