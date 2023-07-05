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

"""This package contains round behaviours of ProposalCollectorAbciApp."""

import json
from abc import ABC
from typing import Generator, Set, Type, cast

from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.proposal_collector_solana_abci.models import Params
from packages.valory.skills.proposal_collector_solana_abci.payloads import (
    CollectActiveRealmsProposalsPayload,
)
from packages.valory.skills.proposal_collector_solana_abci.rounds import (
    CollectActiveRealmsProposalsRound,
    ProposalCollectorAbciApp,
    SynchronizedData,
)


class ProposalCollectorBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_collector_solana_abci skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, super().params)


class CollectActiveRealmsProposalsBehaviour(ProposalCollectorBaseBehaviour):
    """
    CollectActiveRealmsProposals

    Behaviour used to collect active proposals from Snapshot
    """

    matching_round: Type[AbstractRound] = CollectActiveRealmsProposalsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            realms_active_proposals = self._get_realms_active_proposals()
            sender = self.context.agent_address
            payload = CollectActiveRealmsProposalsPayload(
                sender=sender, proposals=realms_active_proposals
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_realms_active_proposals(self) -> str:
        """Get updated proposals"""

        realms_active_proposals = {
            self.params.target_proposal_id: {
                "proposal_id": self.params.target_proposal_id,
                "title": "Triton rpc payment Jul",
                "description": "Payment for triton rpc service invoice date 1 Jul 2023 - 7200 USDC"
            }
        }

        return json.dumps(
            {
                "realms_active_proposals": realms_active_proposals,
            },
            sort_keys=True,
        )


class ProposalCollectorRoundBehaviour(AbstractRoundBehaviour):
    """ProposalCollectorRoundBehaviour"""

    initial_behaviour_cls = CollectActiveRealmsProposalsBehaviour
    abci_app_cls = ProposalCollectorAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        CollectActiveRealmsProposalsBehaviour,
    ]
