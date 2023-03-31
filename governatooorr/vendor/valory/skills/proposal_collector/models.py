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

"""This module contains the shared state for the abci skill of ProposalCollectorAbciApp."""

from typing import Any, List

from aea.skills.base import Model, SkillContext

from packages.valory.skills.abstract_round_abci.models import BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.proposal_collector.rounds import ProposalCollectorAbciApp


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = ProposalCollectorAbciApp

    def __init__(self, *args: Any, skill_context: SkillContext, **kwargs: Any) -> None:
        """Init"""
        super().__init__(*args, skill_context=skill_context, **kwargs)

        # Example of delegations
        # new_delegations = [
        #     {
        #         "user_address": "user_address_a",
        #         "token_address": "token_address_a",
        #         "delegation_amount": 1000,
        #         "voting_preference": "Good"
        #     },
        #     {
        #         "user_address": "user_address_b",
        #         "token_address": "token_address_b",
        #         "delegation_amount": 1500,
        #         "voting_preference": "Evil"
        #     }
        # ]

        self.new_delegations: List = []


class Params(BaseParams):
    """Parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters object."""
        self.tally_api_endpoint = self._ensure("tally_api_endpoint", kwargs, str)
        self.tally_api_key = kwargs.pop("tally_api_key", None)
        self.service_endpoint_base = self._ensure("service_endpoint_base", kwargs, str)
        self.compound_contract_address = self._ensure(
            "compound_contract_address", kwargs, str
        )
        super().__init__(*args, **kwargs)


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool
