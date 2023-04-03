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

"""This package contains the rounds of ProposalVoterAbciApp."""

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
from packages.valory.skills.proposal_voter_abci.payloads import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
)


VOTES_TO_CODE = {"FOR": 0, "AGAINST": 1, "ABSTAIN": 2}


class Event(Enum):
    """ProposalVoterAbciApp Events"""

    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"
    DONE = "done"
    CONTRACT_ERROR = "contract_error"


class SynchronizedData(BaseSynchronizedData):
    """
    Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def delegations(self) -> list:
        """Get the delegations."""
        return cast(list, self.db.get("delegations", []))

    @property
    def proposals(self) -> dict:
        """Get the proposals."""
        return cast(dict, self.db.get("proposals", {}))

    @property
    def selected_proposal_id(self) -> str:
        """Get the selected_proposal_id."""
        return cast(str, self.db.get_strict("selected_proposal_id"))

    @property
    def vote_code(self) -> int:
        """Get the vote vote_code."""
        return cast(int, self.db.get_strict("vote_code"))

    @property
    def most_voted_tx_hash(self) -> str:
        """Get the most_voted_tx_hash."""
        return cast(str, self.db.get_strict("most_voted_tx_hash"))


class EstablishVoteRound(CollectSameUntilThresholdRound):
    """EstablishVoteRound"""

    payload_class = EstablishVotePayload
    synchronized_data_class = SynchronizedData

    ERROR_PAYLOAD = "ERROR"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            if self.most_voted_payload == EstablishVoteRound.ERROR_PAYLOAD:
                return self.synchronized_data, Event.CONTRACT_ERROR

            # Set the decided vote in the selected proposal # TODO: this should be done after the vote is verified

            vote = self.most_voted_payload
            vote_code = VOTES_TO_CODE[vote]

            proposals = cast(SynchronizedData, self.synchronized_data).proposals
            selected_proposal_id = cast(
                SynchronizedData, self.synchronized_data
            ).selected_proposal_id

            proposals[selected_proposal_id]["vote"] = vote

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.vote_code): vote_code,
                    get_name(SynchronizedData.proposals): proposals,
                }
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class PrepareVoteTransactionRound(CollectSameUntilThresholdRound):
    """PrepareVoteTransactionRound"""

    payload_class = PrepareVoteTransactionPayload
    synchronized_data_class = SynchronizedData

    ERROR_PAYLOAD = "ERROR"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            if self.most_voted_payload == PrepareVoteTransactionRound.ERROR_PAYLOAD:
                return self.synchronized_data, Event.CONTRACT_ERROR

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(
                        SynchronizedData.most_voted_tx_hash
                    ): self.most_voted_payload,
                }
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedTransactionPreparationRound(DegenerateRound):
    """FinishedTransactionPreparationRound"""


class ProposalVoterAbciApp(AbciApp[Event]):
    """ProposalVoterAbciApp"""

    initial_round_cls: AppState = EstablishVoteRound
    initial_states: Set[AppState] = {EstablishVoteRound}
    transition_function: AbciAppTransitionFunction = {
        EstablishVoteRound: {
            Event.DONE: PrepareVoteTransactionRound,
            Event.NO_MAJORITY: EstablishVoteRound,
            Event.ROUND_TIMEOUT: EstablishVoteRound,
            Event.CONTRACT_ERROR: EstablishVoteRound,
        },
        PrepareVoteTransactionRound: {
            Event.DONE: FinishedTransactionPreparationRound,
            Event.NO_MAJORITY: PrepareVoteTransactionRound,
            Event.ROUND_TIMEOUT: PrepareVoteTransactionRound,
            Event.CONTRACT_ERROR: PrepareVoteTransactionRound,
        },
        FinishedTransactionPreparationRound: {},
    }
    final_states: Set[AppState] = {FinishedTransactionPreparationRound}
    event_to_timeout: EventToTimeout = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    cross_period_persisted_keys: Set[str] = set()
    db_pre_conditions: Dict[AppState, Set[str]] = {
        EstablishVoteRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedTransactionPreparationRound: {"most_voted_tx_hash"},
    }
