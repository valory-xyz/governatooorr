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
from packages.valory.protocols.llm.message import LlmMessage
from packages.valory.protocols.ledger_api.custom_types import State
from packages.valory.protocols.ledger_api.message import LedgerApiMessage
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.behaviours import (
    make_degenerate_behaviour,
)
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.proposal_voter_abci.behaviours import (
    ProposalVoterBaseBehaviour,
    EstablishVoteBehaviour,
    PrepareVoteTransactionBehaviour,
)
from packages.valory.skills.proposal_voter_abci.rounds import (
    Event,
    FinishedTransactionPreparationNoVoteRound,
    FinishedTransactionPreparationNoVoteRound,
    SynchronizedData,
)
from packages.valory.connections.openai.connection import (
    PUBLIC_ID as LLM_CONNECTION_PUBLIC_ID,
)

DUMMY_GOVERNOR_ADDRESS = "0xEC568fffba86c094cf06b22134B23074DFE2252c"
OPENAI_API_ENDPOINT =
OPENAI_RESPONSE =

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

    def mock_llm_request(
        self, request_kwargs: Dict, response_kwargs: Dict
    ) -> None:
        """
        Mock LLM request.

        :param request_kwargs: keyword arguments for request check.
        :param response_kwargs: keyword arguments for mock response.
        """

        self.assert_quantity_in_outbox(1)
        actual_llm_message = self.get_message_from_outbox()
        assert actual_llm_message is not None, "No message in outbox."  # nosec
        has_attributes, error_str = self.message_has_attributes(
            actual_message=actual_llm_message,
            message_type=LlmMessage,
            to=str(LLM_CONNECTION_PUBLIC_ID),
            sender=str(self.skill.skill_context.skill_id),
            **request_kwargs,
        )

        assert has_attributes, error_str  # nosec
        incoming_message = self.build_incoming_message(
            message_type=LlmMessage,
            dialogue_reference=(
                actual_llm_message.dialogue_reference[0],
                "stub",
            ),
            target=actual_llm_message.message_id,
            message_id=-1,
            to=str(self.skill.skill_context.skill_id),
            sender=str(LLM_CONNECTION_PUBLIC_ID),
            ledger_id=str(LLM_CONNECTION_PUBLIC_ID),
            **response_kwargs,
        )
        llm_handler.handle(incoming_message)
        self.behaviour.act_wrapper()

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
                    initial_data=dict(
                        proposals= {
                            "0": {
                                "votable": False
                            },
                            "1": {
                                "votable": True,
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
                    "urls": [OPENAI_API_ENDPOINT],
                    "bodies": [
                        json.dumps(
                            OPENAI_RESPONSE,
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
        self.complete(test_case.event)
