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

"""This package contains the rounds of ProposalCollectorAbciApp."""

import json
from enum import Enum
from typing import Dict, Optional, Set, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    BaseSynchronizedData,
    CollectDifferentUntilAllRound,
    CollectSameUntilThresholdRound,
    DegenerateRound,
    EventToTimeout,
    TransactionNotValidError,
    get_name,
)
from packages.valory.skills.proposal_collector_abci.payloads import (
    CollectActiveProposalsPayload,
    SelectProposalPayload,
    SynchronizeDelegationsPayload,
)


class Event(Enum):
    """ProposalCollectorAbciApp Events"""

    VOTE = "vote"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"
    DONE = "done"
    API_ERROR = "api_error"
    NO_PROPOSAL = "no_proposal"
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


class SynchronizeDelegationsRound(CollectDifferentUntilAllRound):
    """SynchronizeDelegations"""

    payload_class = SynchronizeDelegationsPayload
    synchronized_data_class = SynchronizedData

    def check_payload(self, payload: SynchronizeDelegationsPayload) -> None:
        """Check Payload"""
        new = payload.values
        existing = [
            collection_payload.values
            for collection_payload in self.collection.values()
            # do not consider empty delegations
            if json.loads(collection_payload.json["new_delegations"])
        ]

        if payload.sender not in self.collection and new in existing:
            raise TransactionNotValidError(
                f"`CollectDifferentUntilAllRound` encountered a value {new!r} that already exists. "
                f"All values: {existing}"
            )

        if payload.round_count != self.synchronized_data.round_count:
            raise TransactionNotValidError(
                f"Expected round count {self.synchronized_data.round_count} and got {payload.round_count}."
            )

        if payload.sender in self.collection:
            raise TransactionNotValidError(
                f"sender {payload.sender} has already sent value for round: {self.round_id}"
            )

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""

        if self.collection_threshold_reached:

            delegations = cast(SynchronizedData, self.synchronized_data).delegations

            for payload in self.collection.values():
                new_delegations = json.loads(payload.json["new_delegations"])

                # Add this agent's new delegations
                delegations.extend(new_delegations)

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.delegations): delegations,
                }
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class CollectActiveProposalsRound(CollectSameUntilThresholdRound):
    """CollectActiveProposals"""

    ERROR_PAYLOAD = "ERROR_PAYLOAD"

    payload_class = CollectActiveProposalsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            if self.most_voted_payload == CollectActiveProposalsRound.ERROR_PAYLOAD:
                return self.synchronized_data, Event.API_ERROR

            active_proposals = json.loads(self.most_voted_payload)["active_proposals"]
            proposals = cast(SynchronizedData, self.synchronized_data).proposals

            # Set all the proposals "active" field to False
            for p in proposals.values():
                p["active"] = False

            for p in active_proposals:
                if p["id"] not in proposals:
                    proposals[p["id"]] = p  # add the proposal
                    proposals[p["id"]]["active"] = True  # set it to active
                    proposals[p["id"]][
                        "vote"
                    ] = None  # we have not voted for this one yet
                else:
                    # The proposal is still active
                    proposals[p["id"]]["active"] = True

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.proposals): proposals,
                }
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class SelectProposalRound(CollectSameUntilThresholdRound):
    """SelectProposal"""

    NO_PROPOSAL = "NO_PROPOSAL"

    payload_class = SelectProposalPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            proposal_id = self.most_voted_payload

            if proposal_id == SelectProposalRound.NO_PROPOSAL:
                return self.synchronized_data, Event.NO_PROPOSAL

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.selected_proposal_id): proposal_id,
                }
            )
            return synchronized_data, Event.VOTE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedProposalSelectionDoneRound(DegenerateRound):
    """FinishedProposalSelectionDone"""


class FinishedProposalSelectionVoteRound(DegenerateRound):
    """FinishedProposalSelectionVote"""


class ProposalCollectorAbciApp(AbciApp[Event]):
    """ProposalCollectorAbciApp"""

    initial_round_cls: AppState = SynchronizeDelegationsRound
    initial_states: Set[AppState] = {SynchronizeDelegationsRound, SelectProposalRound}
    transition_function: AbciAppTransitionFunction = {
        SynchronizeDelegationsRound: {
            Event.DONE: CollectActiveProposalsRound,
            Event.NO_MAJORITY: SynchronizeDelegationsRound,
            Event.ROUND_TIMEOUT: SynchronizeDelegationsRound,
        },
        CollectActiveProposalsRound: {
            Event.DONE: SelectProposalRound,
            Event.API_ERROR: CollectActiveProposalsRound,
            Event.NO_MAJORITY: CollectActiveProposalsRound,
            Event.ROUND_TIMEOUT: CollectActiveProposalsRound,
        },
        SelectProposalRound: {
            Event.NO_PROPOSAL: FinishedProposalSelectionDoneRound,
            Event.VOTE: FinishedProposalSelectionVoteRound,
            Event.NO_MAJORITY: SelectProposalRound,
            Event.ROUND_TIMEOUT: SelectProposalRound,
        },
        FinishedProposalSelectionDoneRound: {},
        FinishedProposalSelectionVoteRound: {},
    }
    final_states: Set[AppState] = {
        FinishedProposalSelectionDoneRound,
        FinishedProposalSelectionVoteRound,
    }
    event_to_timeout: EventToTimeout = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    cross_period_persisted_keys: Set[str] = {
        "delegations",
        "proposals",
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        SynchronizeDelegationsRound: set(),
        SelectProposalRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedProposalSelectionDoneRound: set(),
        FinishedProposalSelectionVoteRound: set(),
    }
