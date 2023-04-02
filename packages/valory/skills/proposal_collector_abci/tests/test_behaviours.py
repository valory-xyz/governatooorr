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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Type

import pytest

from packages.valory.contracts.compound.contract import CompoundContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.contract_api.custom_types import State
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.behaviours import (
    make_degenerate_behaviour,
)
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.proposal_collector_abci.behaviours import (
    CollectActiveProposalsBehaviour,
    ProposalCollectorBaseBehaviour,
    SelectProposalBehaviour,
    SynchronizeDelegationsBehaviour,
    VerifyDelegationsBehaviour,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    Event,
    FinishedProposalSelectionVoteRound,
    SynchronizedData,
)


COMPOUND_CONTRACT_ADDRESS = "0xc00e94Cb662C3520282E6f5717214004A7f26888"

DEFAULT_TALLY_API_URL = "https://api.tally.xyz/query"

DUMMY_AGENT_TO_DELEGATION_NUMBER = {
    "test_agent_address": 1,
    "test_agent_address_2": 2,
}

DUMMY_NEW_DELEGATIONS = [
    {
        "user_address": "user_address_a",
        "token_address": "token_address_a",
        "delegation_amount": 1000,
        "voting_preference": "Good",
    },
    {
        "user_address": "user_address_b",
        "token_address": "token_address_b",
        "delegation_amount": 2000,
        "voting_preference": "Evil",
    },
]


def generate_proposal(
    _id: str = "1", status: str = "PENDING", eta: Optional[str] = None
):
    """Method to generate a proposal."""
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

DUMMY_TALLY_API_RESPONSE = {"data": {"proposals": DUMMY_PROPOSALS}}

DUMMY_ACTIVE_DUMMY_PROPOSALS = [
    p for p in DUMMY_PROPOSALS if p["statusChanges"][-1]["type"] == "ACTIVE"
]


@dataclass
class BehaviourTestCase:
    """BehaviourTestCase"""

    name: str
    initial_data: Dict[str, Any]
    event: Event
    next_behaviour_class: Optional[Type[ProposalCollectorBaseBehaviour]] = None


class BaseProposalCollectorTest(FSMBehaviourBaseCase):
    """Base test case."""

    path_to_skill = Path(__file__).parent.parent

    behaviour: ProposalCollectorBaseBehaviour  # type: ignore
    behaviour_class: Type[ProposalCollectorBaseBehaviour]
    next_behaviour_class: Type[ProposalCollectorBaseBehaviour]
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


class TestSynchronizeDelegationsBehaviour(BaseProposalCollectorTest):
    """Tests SynchronizeDelegationsBehaviour"""

    behaviour_class = SynchronizeDelegationsBehaviour
    next_behaviour_class = VerifyDelegationsBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data={},
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


class TestVerifyDelegationsBehaviour(BaseProposalCollectorTest):
    """Tests VerifyDelegationsBehaviour"""

    behaviour_class = VerifyDelegationsBehaviour
    next_behaviour_class = CollectActiveProposalsBehaviour

    def _mock_compound_contract_request(
        self,
        response_body: Dict,
        response_performative: ContractApiMessage.Performative,
    ) -> None:
        """Mock the contract."""
        self.mock_contract_api_request(
            contract_id=str(CompoundContract.contract_id),
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
                contract_address=COMPOUND_CONTRACT_ADDRESS,
            ),
            response_kwargs=dict(
                performative=response_performative,
                state=State(
                    ledger_id="ethereum",
                    body=response_body,
                ),
            ),
        )

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data={
                        "new_delegations": DUMMY_NEW_DELEGATIONS,
                        "agent_to_delegation_number": DUMMY_AGENT_TO_DELEGATION_NUMBER,
                    },
                    event=Event.DONE,
                ),
                {
                    "mock_response_data": dict(votes=1000),
                    "mock_response_performative": ContractApiMessage.Performative.STATE,
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        for _ in range(len(DUMMY_NEW_DELEGATIONS)):
            self._mock_compound_contract_request(
                response_body=kwargs.get("mock_response_data"),
                response_performative=kwargs.get("mock_response_performative"),
            )
        self.complete(test_case.event)


class TestCollectActiveProposalsBehaviour(BaseProposalCollectorTest):
    """Tests LeaderboardObservationBehaviour"""

    behaviour_class = CollectActiveProposalsBehaviour
    next_behaviour_class = SelectProposalBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data={
                        "new_delegations": DUMMY_NEW_DELEGATIONS,
                    },
                    event=Event.DONE,
                ),
                {
                    "body": json.dumps(
                        DUMMY_TALLY_API_RESPONSE,
                    ),
                    "status_code": 200,
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.mock_http_request(
            request_kwargs=dict(
                method="POST",
                headers="Accept: application/json\r\nApi-key: <tally_api_key>\r\n",
                version="",
                url=DEFAULT_TALLY_API_URL,
            ),
            response_kwargs=dict(
                version="",
                status_code=kwargs.get("status_code"),
                status_text="",
                headers="",
                body=kwargs.get("body").encode(),
            ),
        )
        self.complete(test_case.event)


class TestSelectProposalBehaviourr(BaseProposalCollectorTest):
    """Tests SelectProposalBehaviour"""

    behaviour_class = SelectProposalBehaviour
    next_behaviour_class = make_degenerate_behaviour(FinishedProposalSelectionVoteRound)

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data={
                        "active_proposals": DUMMY_ACTIVE_DUMMY_PROPOSALS,
                    },
                    event=Event.VOTE,
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
