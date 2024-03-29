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

"""This module contains the transaction payloads of the ProposalVoterAbciApp."""

from dataclasses import dataclass
from typing import Optional

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload


@dataclass(frozen=True)
class MechCallCheckPayload(BaseTxPayload):
    """Represent a transaction payload for the MechCallCheckRound."""

    content: Optional[str]


@dataclass(frozen=True)
class PrepareMechRequestPayload(BaseTxPayload):
    """Represent a transaction payload for the PrepareMechRequestsRound."""

    content: str


@dataclass(frozen=True)
class EstablishVotePayload(BaseTxPayload):
    """Represent a transaction payload for the EstablishVoteRound."""

    expiring_proposals: str


@dataclass(frozen=True)
class PrepareVoteTransactionsPayload(BaseTxPayload):
    """Represent a transaction payload for the PrepareVoteTransactionRound."""

    content: str


@dataclass(frozen=True)
class DecisionMakingPayload(BaseTxPayload):
    """Represent a transaction payload for the DecisionMakingRound."""

    content: str


@dataclass(frozen=True)
class PostVoteDecisionMakingPayload(BaseTxPayload):
    """Represent a transaction payload for the PostVoteDecisionMakingRound."""

    content: str


@dataclass(frozen=True)
class SnapshotAPISendRandomnessPayload(BaseTxPayload):
    """Represent a transaction payload of type 'randomness'."""

    round_id: int
    randomness: str


@dataclass(frozen=True)
class SnapshotAPISendSelectKeeperPayload(BaseTxPayload):
    """Represent a transaction payload of type 'select_keeper'."""

    keeper: str


@dataclass(frozen=True)
class SnapshotAPISendPayload(BaseTxPayload):
    """Represent a transaction payload for the SnapshotAPISendRound."""

    success: bool


@dataclass(frozen=True)
class PostTxDecisionMakingPayload(BaseTxPayload):
    """Represent a transaction payload for the PostTxDecisionMakingRound."""

    event: str


@dataclass(frozen=True)
class SnapshotOffchainSignaturePayload(BaseTxPayload):
    """Represent a transaction payload for the SnapshotOffchainSignatureRound."""

    success: bool
