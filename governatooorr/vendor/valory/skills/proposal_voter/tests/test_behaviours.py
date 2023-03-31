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

"""This package contains round behaviours of ProposalVoterAbciApp."""

from pathlib import Path
from typing import Any, Dict, Hashable, Optional, Type
from dataclasses import dataclass, field
from packages.valory.protocols.contract_api.message import ContractApiMessage
import pytest

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
    make_degenerate_behaviour,
)
from packages.valory.skills.proposal_voter.behaviours import (
    ProposalVoterBaseBehaviour,
    ProposalVoterRoundBehaviour,
    EstablishVoteBehaviour,
    PrepareVoteTransactionBehaviour,
)
from packages.valory.skills.proposal_voter.rounds import (
    SynchronizedData,
    DegenerateRound,
    Event,
    ProposalVoterAbciApp,
    EstablishVoteRound,
    FinishedTransactionPreparationRound,
    PrepareVoteTransactionRound,
)

from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.contracts.delegate.contract import DelegateContract
from aea.helpers.transaction.base import RawTransaction
from packages.valory.contracts.gnosis_safe.contract import (
    PUBLIC_ID as GNOSIS_SAFE_CONTRACT_ID,
)


def generate_proposal(
    _id: str = "1", status: str = "PENDING", eta: Optional[str] = None
):
    return {
        "id": _id,
        "title": "dummy_title",
        "eta": eta if eta else "",
        "voteStats": [
            {"support": "FOR"},
            {"support": "AGAINST"},
            {"support": "ABSTAIN"},
        ],
        "statusChanges": [
            {"type": status},
        ],
        "governor": {
            "id": "eip155:1:0x35d9f4953748b318f18c30634bA299b237eeDfff",
            "type": "GOVERNORALPHA",
            "name": "Inverse",
        },
    }


DUMMY_PROPOSALS = [
    generate_proposal("10", "PENDING", "16000"),
    generate_proposal("3000", "ACTIVE", "15000"),
    generate_proposal("700", "PENDING", "16500"),
    generate_proposal("21", "ACTIVE", "60000"),
    generate_proposal("999", "ACTIVE", "700"),
    generate_proposal("81", "ACTIVE"),
    generate_proposal("53000", "ACTIVE"),
]

DUMMY_ACTIVE_DUMMY_PROPOSALS = [
    p for p in DUMMY_PROPOSALS if p["statusChanges"][-1]["type"] == "ACTIVE"
]


DUMMY_TOKEN_TO_DELEGATIONS = {
    "0x35d9f4953748b318f18c30634bA299b237eeDfff": {
        "user": {"voting_preference": "GOOD", "delegation_amount": 1000}
    }
}


@dataclass
class BehaviourTestCase:
    """BehaviourTestCase"""

    name: str
    initial_data: Dict[str, Any]
    event: Event
    next_behaviour_class: Optional[Type[ProposalVoterBaseBehaviour]] = None


class BaseProposalVoterTest(FSMBehaviourBaseCase):
    """Base test case."""

    path_to_skill = Path(__file__).parent.parent

    behaviour: ProposalVoterBaseBehaviour  # type: ignore
    behaviour_class: Type[ProposalVoterBaseBehaviour]
    next_behaviour_class: Type[ProposalVoterBaseBehaviour]
    synchronized_data: SynchronizedData
    done_event = Event.DONE
    image_dir: Path

    def fast_forward(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Fast-forward on initialization"""

        data = data if data is not None else {}
        self.fast_forward_to_behaviour(
            self.behaviour,  # type: ignore
            self.behaviour_class.auto_behaviour_id(),
            SynchronizedData(AbciAppDB(setup_data=AbciAppDB.data_to_lists(data))),
        )
        assert (
            self.behaviour.current_behaviour.auto_behaviour_id()  # type: ignore
            == self.behaviour_class.auto_behaviour_id()
        )

    def complete(self, event: Event) -> None:
        """Complete test"""

        self.behaviour.act_wrapper()
        self.mock_a2a_transaction()
        self._test_done_flag_set()
        self.end_round(done_event=event)
        assert (
            self.behaviour.current_behaviour.auto_behaviour_id()  # type: ignore
            == self.next_behaviour_class.auto_behaviour_id()
        )


class TestEstablishVoteBehaviour(BaseProposalVoterTest):
    """Tests EstablishVoteBehaviour"""

    behaviour_class = EstablishVoteBehaviour
    next_behaviour_class = PrepareVoteTransactionBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data={
                        "active_proposals": DUMMY_ACTIVE_DUMMY_PROPOSALS,
                        "selected_proposal_id": "3000",
                        "current_token_to_delegations": DUMMY_TOKEN_TO_DELEGATIONS,
                    },
                    event=Event.DONE,
                ),
                {},
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.complete(test_case.event)


class TestPrepareVoteTransactionBehaviour(BaseProposalVoterTest):
    """Tests PrepareVoteTransactionBehaviour"""

    behaviour_class = PrepareVoteTransactionBehaviour
    next_behaviour_class = make_degenerate_behaviour(
        FinishedTransactionPreparationRound
    )

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data={"selected_proposal_id": "3000", "vote_code": 0},
                    event=Event.DONE,
                ),
                {},
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()

        self.mock_contract_api_request(
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,
            ),
            contract_id=str(DelegateContract.contract_id),
            response_kwargs=dict(
                performative=ContractApiMessage.Performative.RAW_TRANSACTION,
                callable="get_transmit_data",
                raw_transaction=RawTransaction(
                    ledger_id="ethereum", body={"data": b"data"}  # type: ignore
                ),
            ),
        )

        self.mock_contract_api_request(
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,
            ),
            contract_id=str(GNOSIS_SAFE_CONTRACT_ID),
            response_kwargs=dict(
                performative=ContractApiMessage.Performative.RAW_TRANSACTION,
                callable="get_deploy_transaction",
                raw_transaction=RawTransaction(
                    ledger_id="ethereum",
                    body={
                        "tx_hash": "0xb0e6add595e00477cf347d09797b156719dc5233283ac76e4efce2a674fe72d9"
                    },
                ),
            ),
        )

        self.complete(test_case.event)
