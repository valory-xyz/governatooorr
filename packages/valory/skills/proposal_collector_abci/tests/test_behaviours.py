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

"""This package contains round behaviours of ProposalCollector."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Type

import pytest

from packages.valory.protocols.ledger_api.custom_types import State
from packages.valory.protocols.ledger_api.message import LedgerApiMessage
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.proposal_collector_abci.behaviours import (
    CollectActiveSnapshotProposalsBehaviour,
    CollectActiveTallyProposalsBehaviour,
    ProposalCollectorBaseBehaviour,
    SynchronizeDelegationsBehaviour,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    Event,
    SynchronizedData,
)


TALLY_API_ENDPOINT = "https://api.tally.xyz/query"

DUMMY_GOVERNOR_ADDRESS = "0xEC568fffba86c094cf06b22134B23074DFE2252c"

DUMMY_GOVERNORS_RESPONSE = {
    "data": {
        "governors": [
            {
                "id": f"eip155:1:{DUMMY_GOVERNOR_ADDRESS}",
                "type": "AAVE",
                "name": "Aave",
                "slug": "aave",
                "proposalStats": {
                    "total": 194,
                    "active": 3,
                    "failed": 22,
                    "passed": 169,
                },
            },
        ]
    }
}

DUMMY_RESPONSE_ERROR = {"errors": "errors"}

DUMMY_PROPOSALS_RESPONSE = {
    "data": {
        "proposals": [
            {
                "id": "0",
                "title": "# AIP 5: Adding CRV to Aave",
                "description": "dummy description",
                "proposer": {"address": "0xA7499Aa6464c078EeB940da2fc95C6aCd010c3Cc"},
                "governor": {
                    "id": f"eip155:1:{DUMMY_GOVERNOR_ADDRESS}",
                    "type": "AAVE",
                    "name": "Aave",
                    "tokens": [
                        {
                            "id": "eip155:1/erc20aave:0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9"
                        }
                    ],
                },
                "eta": "1609105448",
                "start": {
                    "id": "eip155:1:11512328",
                    "number": 11512328,
                    "timestamp": "2020-12-23T21:45:20Z",
                },
                "end": {
                    "id": "eip155:1:11531528",
                    "number": 11531528,
                    "timestamp": "2020-12-26T20:38:38Z",
                },
                "voteStats": [
                    {"support": "FOR"},
                    {"support": "AGAINST"},
                    {"support": "ABSTAIN"},
                ],
                "statusChanges": [{"type": "PENDING"}, {"type": "ACTIVE"}],
            },
            {
                "id": "1",
                "title": "# AIP 5: Adding CRV to Aave",
                "description": "dummy description",
                "proposer": {"address": "0xA7499Aa6464c078EeB940da2fc95C6aCd010c3Cc"},
                "governor": {
                    "id": f"eip155:1:{DUMMY_GOVERNOR_ADDRESS}",
                    "type": "AAVE",
                    "name": "Aave",
                    "tokens": [
                        {
                            "id": "eip155:1/erc20aave:0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9"
                        }
                    ],
                },
                "eta": "1609105448",
                "start": {
                    "id": "eip155:1:11512328",
                    "number": 11512328,
                    "timestamp": "2020-12-23T21:45:20Z",
                },
                "end": {
                    "id": "eip155:1:11531528",
                    "number": 11531528,
                    "timestamp": "2020-12-26T20:38:38Z",
                },
                "voteStats": [
                    {"support": "FOR"},
                    {"support": "AGAINST"},
                    {"support": "ABSTAIN"},
                ],
                "statusChanges": [{"type": "PENDING"}, {"type": "ACTIVE"}],
            },
        ]
    }
}


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
    next_behaviour_class = CollectActiveTallyProposalsBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(),
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


class TestCollectActiveTallyProposalsBehaviour(BaseProposalCollectorTest):
    """Tests CollectActiveTallyProposalsBehaviour"""

    behaviour_class = CollectActiveTallyProposalsBehaviour
    next_behaviour_class = CollectActiveSnapshotProposalsBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        proposals={
                            "0": {
                                "governor": {
                                    "id": f"eip155:1:{DUMMY_GOVERNOR_ADDRESS}",
                                    "type": "AAVE",
                                    "name": "Aave",
                                    "tokens": [
                                        {
                                            "id": "eip155:1/erc20aave:0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9"
                                        }
                                    ],
                                },
                                "end": {"number": 50},
                                "vote": None,
                            }
                        }
                    ),
                    event=Event.DONE,
                ),
                {
                    "urls": [TALLY_API_ENDPOINT, TALLY_API_ENDPOINT],
                    "bodies": [
                        json.dumps(
                            DUMMY_GOVERNORS_RESPONSE,
                        ),
                        json.dumps(
                            DUMMY_PROPOSALS_RESPONSE,
                        ),
                    ],
                    "status_code": 200,
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        # Mock API calls
        for i in range(len(kwargs.get("urls"))):
            self.mock_http_request(
                request_kwargs=dict(
                    method="POST",
                    headers="Content-Type: application/json\r\nAccept: application/json\r\nApi-key: <tally_api_key>\r\n",
                    version="",
                    url=kwargs.get("urls")[i],
                ),
                response_kwargs=dict(
                    version="",
                    status_code=kwargs.get("status_code"),
                    status_text="",
                    body=kwargs.get("bodies")[i].encode(),
                ),
            )
        # Mock get block
        self.mock_ledger_api_request(
            request_kwargs=dict(
                performative=LedgerApiMessage.Performative.GET_STATE,
            ),
            response_kwargs=dict(
                performative=LedgerApiMessage.Performative.STATE,
                state=State(
                    ledger_id="ethereum",
                    body={"number": 10000},
                ),
            ),
        )
        self.complete(test_case.event)


class TestCollectActiveProposalsErrorBehaviour(BaseProposalCollectorTest):
    """Tests CollectActiveTallyProposalsBehaviour"""

    behaviour_class = CollectActiveTallyProposalsBehaviour
    next_behaviour_class = CollectActiveTallyProposalsBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Block error",
                    initial_data=dict(),
                    event=Event.BLOCK_RETRIEVAL_ERROR,
                ),
                {
                    "urls": [TALLY_API_ENDPOINT, TALLY_API_ENDPOINT],
                    "bodies": [
                        json.dumps(
                            DUMMY_GOVERNORS_RESPONSE,
                        ),
                        json.dumps(
                            DUMMY_PROPOSALS_RESPONSE,
                        ),
                    ],
                    "status_codes": [200, 200],
                    "block_retrieval_performative": LedgerApiMessage.Performative.ERROR,
                },
            ),
            (
                BehaviourTestCase(
                    "Governor request error",
                    initial_data=dict(),
                    event=Event.API_ERROR,
                ),
                {
                    "urls": [TALLY_API_ENDPOINT],
                    "bodies": [
                        json.dumps(
                            DUMMY_GOVERNORS_RESPONSE,
                        ),
                    ],
                    "status_codes": [404],
                },
            ),
            (
                BehaviourTestCase(
                    "Governor response with errors",
                    initial_data=dict(),
                    event=Event.API_ERROR,
                ),
                {
                    "urls": [TALLY_API_ENDPOINT],
                    "bodies": [
                        json.dumps(
                            DUMMY_RESPONSE_ERROR,
                        ),
                    ],
                    "status_codes": [200],
                },
            ),
            (
                BehaviourTestCase(
                    "Proposal request error",
                    initial_data=dict(),
                    event=Event.API_ERROR,
                ),
                {
                    "urls": [TALLY_API_ENDPOINT, TALLY_API_ENDPOINT],
                    "bodies": [
                        json.dumps(
                            DUMMY_GOVERNORS_RESPONSE,
                        ),
                        json.dumps(
                            DUMMY_PROPOSALS_RESPONSE,
                        ),
                    ],
                    "status_codes": [200, 404],
                },
            ),
            (
                BehaviourTestCase(
                    "Proposal response with errors",
                    initial_data=dict(),
                    event=Event.API_ERROR,
                ),
                {
                    "urls": [TALLY_API_ENDPOINT, TALLY_API_ENDPOINT],
                    "bodies": [
                        json.dumps(
                            DUMMY_GOVERNORS_RESPONSE,
                        ),
                        json.dumps(
                            DUMMY_RESPONSE_ERROR,
                        ),
                    ],
                    "status_codes": [200, 200],
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        # Mock API calls
        for i in range(len(kwargs.get("urls"))):
            self.mock_http_request(
                request_kwargs=dict(
                    method="POST",
                    headers="Content-Type: application/json\r\nAccept: application/json\r\nApi-key: <tally_api_key>\r\n",
                    version="",
                    url=kwargs.get("urls")[i],
                ),
                response_kwargs=dict(
                    version="",
                    status_code=kwargs.get("status_codes")[i],
                    status_text="",
                    body=kwargs.get("bodies")[i].encode(),
                ),
            )
        # Mock get block
        if "block_retrieval_performative" in kwargs:
            self.mock_ledger_api_request(
                request_kwargs=dict(
                    performative=LedgerApiMessage.Performative.GET_STATE,
                ),
                response_kwargs=dict(
                    performative=kwargs.get("block_retrieval_performative"),
                    state=State(
                        ledger_id="ethereum",
                        body={"number": 10000},
                    ),
                ),
            )
        self.complete(test_case.event)
