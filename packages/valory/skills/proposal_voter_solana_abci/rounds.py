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

"""This package contains the rounds of ProposalVoterSolanaAbciApp."""

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
from packages.valory.skills.proposal_voter_solana_abci.payloads import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    VerificationStatus,
)


class Event(Enum):
    """ProposalVoterSolanaAbciApp Events"""

    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"
    DONE = "done"
    CONTRACT_ERROR = "contract_error"
    VOTE = "vote"
    NO_VOTE = "no_vote"
    DID_NOT_SEND = "did_not_send"
    API_ERROR = "api_error"
    CALL_API = "call_api"
    RETRIEVAL_ERROR = "retrieval_error"


class SynchronizedData(BaseSynchronizedData):
    """
    Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def just_voted(self) -> bool:
        """Get the final verification status."""
        status_value = self.db.get(
            "final_verification_status", VerificationStatus.NOT_VERIFIED.value
        )
        return status_value == VerificationStatus.VERIFIED.value

    @property
    def realms_active_proposals(self) -> dict:
        """Get the active proposals from Realms."""
        return cast(dict, self.db.get("realms_active_proposals", {}))

    @property
    def votable_proposal_ids(self) -> set:
        """Get the votable proposal ids, sorted by their remaining blocks until expiration, in ascending order."""
        return cast(set, self.db.get("votable_proposal_ids", {}))

    @property
    def most_voted_tx_hash(self) -> str:
        """Get the most_voted_tx_hash."""
        return cast(str, self.db.get_strict("most_voted_tx_hash"))


class EstablishVoteRound(CollectSameUntilThresholdRound):
    """EstablishVoteRound"""

    payload_class = EstablishVotePayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            payload = json.loads(self.most_voted_payload)
            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.realms_active_proposals): payload[
                        "realms_active_proposals"
                    ],
                    get_name(SynchronizedData.votable_proposal_ids): payload[
                        "votable_proposal_ids"
                    ],
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

    NO_VOTE_PAYLOAD = "NO_VOTE"
    ERROR_PAYLOAD = "ERROR"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            payload = json.loads(self.most_voted_payload)

            if payload["tx_hash"] == PrepareVoteTransactionRound.ERROR_PAYLOAD:
                return self.synchronized_data, Event.CONTRACT_ERROR

            if payload["tx_hash"] == PrepareVoteTransactionRound.NO_VOTE_PAYLOAD:
                return self.synchronized_data, Event.NO_VOTE

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.most_voted_tx_hash): payload["tx_hash"],
                    get_name(SynchronizedData.votable_proposal_ids): payload[
                        "votable_proposal_ids"
                    ],
                }
            )
            return synchronized_data, Event.VOTE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedTransactionPreparationVoteRound(DegenerateRound):
    """FinishedTransactionPreparationRound"""


class FinishedTransactionPreparationNoVoteRound(DegenerateRound):
    """FinishedTransactionPreparationRound"""


class ProposalVoterSolanaAbciApp(AbciApp[Event]):
    """ProposalVoterSolanaAbciApp"""

    initial_round_cls: AppState = EstablishVoteRound
    initial_states: Set[AppState] = {
        EstablishVoteRound,
        PrepareVoteTransactionRound,
        RetrieveSignatureRound,
    }
    transition_function: AbciAppTransitionFunction = {
        EstablishVoteRound: {
            Event.DONE: PrepareVoteTransactionRound,
            Event.NO_MAJORITY: EstablishVoteRound,
            Event.ROUND_TIMEOUT: EstablishVoteRound,
        },
        PrepareVoteTransactionRound: {
            Event.NO_VOTE: FinishedTransactionPreparationNoVoteRound,
            Event.VOTE: FinishedTransactionPreparationVoteRound,
            Event.NO_MAJORITY: PrepareVoteTransactionRound,
            Event.ROUND_TIMEOUT: PrepareVoteTransactionRound,
            Event.CONTRACT_ERROR: PrepareVoteTransactionRound,
        },
        FinishedTransactionPreparationNoVoteRound: {},
        RetrieveSignatureRound: {
            Event.DONE: PrepareVoteTransactionRound,
            Event.RETRIEVAL_ERROR: RetrieveSignatureRound,
            Event.CALL_API: SnapshotAPISendRandomnessRound,
            Event.NO_MAJORITY: EstablishVoteRound,
            Event.ROUND_TIMEOUT: EstablishVoteRound,
        },
        SnapshotAPISendRandomnessRound: {
            Event.DONE: SnapshotAPISendSelectKeeperRound,
            Event.NO_MAJORITY: SnapshotAPISendRandomnessRound,
            Event.ROUND_TIMEOUT: SnapshotAPISendRandomnessRound,
        },
        SnapshotAPISendSelectKeeperRound: {
            Event.DONE: SnapshotAPISendRound,
            Event.NO_MAJORITY: SnapshotAPISendRandomnessRound,
            Event.ROUND_TIMEOUT: SnapshotAPISendRandomnessRound,
        },
        SnapshotAPISendRound: {
            Event.API_ERROR: SnapshotAPISendRandomnessRound,
            Event.DID_NOT_SEND: SnapshotAPISendRandomnessRound,
            Event.DONE: PrepareVoteTransactionRound,
            Event.ROUND_TIMEOUT: SnapshotAPISendRandomnessRound,
        },
        FinishedTransactionPreparationVoteRound: {},
    }
    final_states: Set[AppState] = {
        FinishedTransactionPreparationVoteRound,
        FinishedTransactionPreparationNoVoteRound,
    }
    event_to_timeout: EventToTimeout = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    cross_period_persisted_keys: Set[str] = {
        get_name(SynchronizedData.delegations),
        get_name(SynchronizedData.proposals),
        get_name(SynchronizedData.votable_proposal_ids),
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        EstablishVoteRound: set(),
        PrepareVoteTransactionRound: {
            get_name(SynchronizedData.proposals),
            get_name(SynchronizedData.delegations),
            get_name(SynchronizedData.votable_proposal_ids),
        },
        RetrieveSignatureRound: set(
            get_name(SynchronizedData.most_voted_tx_hash),
        ),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedTransactionPreparationVoteRound: {
            get_name(SynchronizedData.most_voted_tx_hash)
        },
        FinishedTransactionPreparationNoVoteRound: set(),
    }
