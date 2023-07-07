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

"""This package contains the rounds of ProposalCollectorSolanaAbciApp."""

import json
from enum import Enum
from typing import Dict, Optional, Set, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    DegenerateRound,
    EventToTimeout,
    get_name,
)
from packages.valory.skills.proposal_collector_solana_abci.payloads import (
    CollectActiveRealmsProposalsPayload,
)


class Event(Enum):
    """ProposalCollectorSolanaAbciApp Events"""

    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"
    DONE = "done"


class SynchronizedData(BaseSynchronizedData):
    """
    Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def realms_active_proposals(self) -> dict:
        """Get the active proposals from Realms."""
        return cast(dict, self.db.get("realms_active_proposals", {}))


class CollectActiveRealmsProposalsRound(CollectSameUntilThresholdRound):
    """CollectActiveRealmsProposals"""

    payload_class = CollectActiveRealmsProposalsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            payload = json.loads(self.most_voted_payload)

            realms_active_proposals = payload["realms_active_proposals"]

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.realms_active_proposals): realms_active_proposals,
                },
            )
            return (
                synchronized_data,
                Event.DONE
            )
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedCollectRealmsProposalRound(DegenerateRound):
    """FinishedCollectRealmsProposalRound"""


class ProposalCollectorSolanaAbciApp(AbciApp[Event]):
    """ProposalCollectorSolanaAbciApp"""

    initial_round_cls: AppState = CollectActiveRealmsProposalsRound
    initial_states: Set[AppState] = {
        CollectActiveRealmsProposalsRound,
    }
    transition_function: AbciAppTransitionFunction = {
        CollectActiveRealmsProposalsRound: {
            Event.DONE: FinishedCollectRealmsProposalRound,
            Event.NO_MAJORITY: CollectActiveRealmsProposalsRound,
            Event.ROUND_TIMEOUT: CollectActiveRealmsProposalsRound,
        },
        FinishedCollectRealmsProposalRound: {},
    }
    final_states: Set[AppState] = {
        FinishedCollectRealmsProposalRound,
    }
    event_to_timeout: EventToTimeout = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    cross_period_persisted_keys: Set[str] = set()
    db_pre_conditions: Dict[AppState, Set[str]] = {
        CollectActiveRealmsProposalsRound: set()
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedCollectRealmsProposalRound: {
            get_name(SynchronizedData.realms_active_proposals),
        },
    }
