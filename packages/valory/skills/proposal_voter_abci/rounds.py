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
    OnlyKeeperSendsRound,
    get_name,
)
from packages.valory.skills.proposal_voter_abci.payloads import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
    RetrieveSignaturePayload,
    SnapshotAPISendPayload,
    SnapshotAPISendRandomnessPayload,
    SnapshotAPISendSelectKeeperPayload,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    VerificationStatus,
)


class Event(Enum):
    """ProposalVoterAbciApp Events"""

    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"
    DONE = "done"
    CONTRACT_ERROR = "contract_error"
    VOTE = "vote"
    NO_VOTE = "no_vote"
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
    def ceramic_db(self) -> dict:
        """Get the delegations and votes."""
        return cast(dict, self.db.get_strict("ceramic_db"))

    @property
    def active_proposals(self) -> dict:
        """Get the active proposals."""
        return cast(dict, self.db.get("active_proposals", {}))

    @property
    def expiring_proposals(self) -> dict:
        """Get the expiring_proposals."""
        return cast(dict, self.db.get_strict("expiring_proposals"))

    @property
    def most_voted_tx_hash(self) -> str:
        """Get the most_voted_tx_hash."""
        return cast(str, self.db.get_strict("most_voted_tx_hash"))

    @property
    def most_voted_randomness_round(self) -> int:  # pragma: no cover
        """Get the most voted randomness round."""
        round_ = self.db.get_strict("most_voted_randomness_round")
        return cast(int, round_)

    @property
    def final_tx_hash(self) -> str:
        """Get the verified tx hash."""
        return cast(str, self.db.get_strict("final_tx_hash"))

    @property
    def snapshot_api_retries(self) -> int:
        """Get the amount of API call retries."""
        return cast(int, self.db.get("snapshot_api_retries", 0))

    @property
    def pending_write(self) -> bool:
        """Signal if the DB needs writing."""
        return cast(bool, self.db.get("pending_write", False))

    @property
    def snapshot_api_data(self) -> dict:
        """Get the snapshot_api_data."""
        return cast(dict, self.db.get("snapshot_api_data", False))


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
                    get_name(SynchronizedData.expiring_proposals): payload[
                        "expiring_proposals"
                    ],
                },
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
                synchronized_data = self.synchronized_data.update(
                    synchronized_data_class=SynchronizedData,
                    **{
                        get_name(SynchronizedData.active_proposals): payload[
                            "active_proposals"
                        ],
                        get_name(SynchronizedData.expiring_proposals): payload[
                            "expiring_proposals"
                        ],
                        get_name(SynchronizedData.ceramic_db): payload["ceramic_db"],
                        get_name(SynchronizedData.pending_write): payload[
                            "pending_write"
                        ],
                    },
                )
                return synchronized_data, Event.NO_VOTE

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.active_proposals): payload[
                        "active_proposals"
                    ],
                    get_name(SynchronizedData.expiring_proposals): payload[
                        "expiring_proposals"
                    ],
                    get_name(SynchronizedData.ceramic_db): payload["ceramic_db"],
                    get_name(SynchronizedData.pending_write): payload["pending_write"],
                    get_name(SynchronizedData.most_voted_tx_hash): payload["tx_hash"],
                    get_name(SynchronizedData.snapshot_api_data): payload[
                        "snapshot_api_data"
                    ],
                },
            )
            return synchronized_data, Event.VOTE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class RetrieveSignatureRound(CollectSameUntilThresholdRound):
    """RetrieveSignatureRound"""

    payload_class = RetrieveSignaturePayload
    synchronized_data_class = SynchronizedData

    SKIP_PAYLOAD = "skip_payload"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            if self.most_voted_payload == self.SKIP_PAYLOAD:
                return self.synchronized_data, Event.DONE

            payload = json.loads(self.most_voted_payload)
            snapshot_api_data_signature = payload["snapshot_api_data_signature"]

            if not snapshot_api_data_signature:
                return self.synchronized_data, Event.RETRIEVAL_ERROR

            ceramic_db = cast(SynchronizedData, self.synchronized_data).ceramic_db

            snapshot_api_data = cast(
                SynchronizedData, self.synchronized_data
            ).snapshot_api_data

            proposal_id = snapshot_api_data["message"]["proposal"]
            proposal_info = ceramic_db["vote_info"]["snapshot"][proposal_id]
            proposal_info["data"] = snapshot_api_data
            proposal_info["signature"] = snapshot_api_data_signature

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.ceramic_db): ceramic_db,
                },
            )
            return synchronized_data, Event.CALL_API

        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class SnapshotAPISendRandomnessRound(CollectSameUntilThresholdRound):
    """A round for generating randomness"""

    payload_class = SnapshotAPISendRandomnessPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_randomness)
    selection_key = (
        get_name(SynchronizedData.most_voted_randomness_round),
        get_name(SynchronizedData.most_voted_randomness),
    )


class SnapshotAPISendSelectKeeperRound(CollectSameUntilThresholdRound):
    """A round in which a keeper is selected for transaction submission"""

    payload_class = SnapshotAPISendSelectKeeperPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_selection)
    selection_key = get_name(SynchronizedData.most_voted_keeper_address)


class SnapshotAPISendRound(OnlyKeeperSendsRound):
    """StreamWriteRound"""

    payload_class = SnapshotAPISendPayload
    synchronized_data_class = SynchronizedData

    def end_block(
        self,
    ) -> Optional[
        Tuple[BaseSynchronizedData, Enum]
    ]:  # pylint: disable=too-many-return-statements
        """Process the end of the block."""
        if self.keeper_payload is None:
            return None

        payload = json.loads(cast(SnapshotAPISendPayload, self.keeper_payload).content)

        pending_write = (
            payload["pending_write"]
            or cast(SynchronizedData, self.synchronized_data).pending_write
        )

        synchronized_data = self.synchronized_data.update(
            synchronized_data_class=SynchronizedData,
            **{
                get_name(SynchronizedData.ceramic_db): payload["ceramic_db"],
                get_name(SynchronizedData.pending_write): pending_write,
            },
        )
        return synchronized_data, Event.DONE


class FinishedTransactionPreparationVoteRound(DegenerateRound):
    """FinishedTransactionPreparationRound"""


class FinishedTransactionPreparationNoVoteRound(DegenerateRound):
    """FinishedTransactionPreparationRound"""


class ProposalVoterAbciApp(AbciApp[Event]):
    """ProposalVoterAbciApp"""

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
        get_name(SynchronizedData.ceramic_db),
        get_name(SynchronizedData.pending_write),
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        EstablishVoteRound: set(),
        PrepareVoteTransactionRound: {
            get_name(SynchronizedData.active_proposals),
            get_name(SynchronizedData.ceramic_db),
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
