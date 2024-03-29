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

"""This module contains the transaction payloads of the ProposalCollectorAbciApp."""

from dataclasses import dataclass

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload


@dataclass(frozen=True)
class SynchronizeDelegationsPayload(BaseTxPayload):
    """Represent a transaction payload for the SynchronizeDelegations."""

    new_delegations: str


@dataclass(frozen=True)
class WriteDBPayload(BaseTxPayload):
    """Represent a transaction payload for the WriteDB."""

    write_data: str


@dataclass(frozen=True)
class CollectActiveTallyProposalsPayload(BaseTxPayload):
    """Represent a transaction payload for the CollectActiveTallyProposals."""

    proposal_data: str


@dataclass(frozen=True)
class CollectActiveSnapshotProposalsPayload(BaseTxPayload):
    """Represent a transaction payload for the CollectActiveSnapshotProposals."""

    proposal_data: str
